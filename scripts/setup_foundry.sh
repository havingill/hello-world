#!/usr/bin/env bash
#
# Provision Microsoft Foundry (Azure AI Foundry) for the dashboard and write a
# .env pointing at it.
#
# Run this on a machine with the Azure CLI installed and logged in — it needs
# the Azure control plane, which the cloud dev container cannot reach.
#
#   az login
#   ./scripts/setup_foundry.sh
#
# Everything is overridable by environment variable:
#
#   LOCATION=swedencentral MODEL_NAME=gpt-4o ./scripts/setup_foundry.sh
#
# The script is safe to re-run: it reuses anything that already exists rather
# than failing or duplicating.

set -euo pipefail

RESOURCE_GROUP="${RESOURCE_GROUP:-rg-finance-workflow}"
LOCATION="${LOCATION:-eastus}"
DEPLOYMENT_NAME="${DEPLOYMENT_NAME:-gpt-4o}"
MODEL_NAME="${MODEL_NAME:-gpt-4o}"
MODEL_VERSION="${MODEL_VERSION:-}"        # blank = pick the newest available
SKU_NAME="${SKU_NAME:-GlobalStandard}"
SKU_CAPACITY="${SKU_CAPACITY:-20}"
WRITE_KEY="${WRITE_KEY:-0}"               # 1 = also put an API key in .env
ENV_FILE="${ENV_FILE:-.env}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

say()  { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
info() { printf '    %s\n' "$*"; }
die()  { printf '\n\033[31mError: %s\033[0m\n' "$*" >&2; exit 1; }

# --- preflight -------------------------------------------------------------

command -v az >/dev/null 2>&1 || die "The Azure CLI is not installed. See https://aka.ms/azure-cli"

say "Checking your Azure login"
if ! ACCOUNT_JSON="$(az account show -o json 2>/dev/null)"; then
  die "Not logged in. Run 'az login' first."
fi

SUBSCRIPTION_ID="$(printf '%s' "$ACCOUNT_JSON" | az account show --query id -o tsv)"
SUBSCRIPTION_NAME="$(az account show --query name -o tsv)"
info "Subscription: $SUBSCRIPTION_NAME ($SUBSCRIPTION_ID)"

# Cognitive Services custom-domain names are globally unique, so derive a
# default from the subscription id rather than risking a collision on a
# generic name. Override with ACCOUNT_NAME if you prefer something readable.
DEFAULT_ACCOUNT="fnwf$(printf '%s' "$SUBSCRIPTION_ID" | tr -d '-' | cut -c1-12)"
ACCOUNT_NAME="${ACCOUNT_NAME:-$DEFAULT_ACCOUNT}"
info "Foundry resource: $ACCOUNT_NAME"
info "Region: $LOCATION"

printf '\nProceed against this subscription? [y/N] '
read -r reply
case "$reply" in [yY]*) ;; *) die "Cancelled." ;; esac

# --- provider registration -------------------------------------------------

say "Ensuring the Microsoft.CognitiveServices provider is registered"
STATE="$(az provider show --namespace Microsoft.CognitiveServices --query registrationState -o tsv 2>/dev/null || echo "NotRegistered")"
if [ "$STATE" != "Registered" ]; then
  info "Registering (this can take a minute or two)…"
  az provider register --namespace Microsoft.CognitiveServices --wait
fi
info "Registered."

# --- resource group --------------------------------------------------------

say "Resource group: $RESOURCE_GROUP"
az group create --name "$RESOURCE_GROUP" --location "$LOCATION" --output none
info "Ready."

# --- Foundry resource ------------------------------------------------------

say "Foundry resource: $ACCOUNT_NAME"
if az cognitiveservices account show -n "$ACCOUNT_NAME" -g "$RESOURCE_GROUP" -o none 2>/dev/null; then
  info "Already exists, reusing it."
else
  info "Creating…"
  # kind=AIServices is the Foundry resource. --custom-domain is REQUIRED for
  # Entra ID (keyless) authentication to work against it.
  az cognitiveservices account create \
    --name "$ACCOUNT_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --location "$LOCATION" \
    --kind AIServices \
    --sku S0 \
    --custom-domain "$ACCOUNT_NAME" \
    --yes \
    --output none
  info "Created."
fi

# --- model version ---------------------------------------------------------

say "Resolving the model to deploy"
if [ -z "$MODEL_VERSION" ]; then
  MODEL_VERSION="$(az cognitiveservices account list-models \
      -n "$ACCOUNT_NAME" -g "$RESOURCE_GROUP" \
      --query "[?name=='$MODEL_NAME' && format=='OpenAI'].version" -o tsv \
      | sort | tail -1)"
fi

if [ -z "$MODEL_VERSION" ]; then
  printf '\n'
  info "'$MODEL_NAME' is not available in $LOCATION. What is available:"
  az cognitiveservices account list-models -n "$ACCOUNT_NAME" -g "$RESOURCE_GROUP" \
    --query "[?format=='OpenAI'].{model:name, version:version, skus:join(',', skus[].name)}" \
    -o table 2>/dev/null | head -40
  die "Pick one and re-run with MODEL_NAME=… (and optionally LOCATION=… for a different region)."
fi
info "$MODEL_NAME version $MODEL_VERSION"

AVAILABLE_SKUS="$(az cognitiveservices account list-models \
    -n "$ACCOUNT_NAME" -g "$RESOURCE_GROUP" \
    --query "[?name=='$MODEL_NAME' && version=='$MODEL_VERSION'].skus[].name" -o tsv)"
if ! printf '%s\n' "$AVAILABLE_SKUS" | grep -qx "$SKU_NAME"; then
  info "SKU '$SKU_NAME' is not offered for this model here. Offered: $(printf '%s' "$AVAILABLE_SKUS" | tr '\n' ' ')"
  SKU_NAME="$(printf '%s\n' "$AVAILABLE_SKUS" | head -1)"
  [ -n "$SKU_NAME" ] || die "No deployment SKU available for $MODEL_NAME in $LOCATION."
  info "Falling back to '$SKU_NAME'."
fi

# --- deployment ------------------------------------------------------------

say "Model deployment: $DEPLOYMENT_NAME"
if az cognitiveservices account deployment show \
     -n "$ACCOUNT_NAME" -g "$RESOURCE_GROUP" --deployment-name "$DEPLOYMENT_NAME" -o none 2>/dev/null; then
  info "Already exists, reusing it."
else
  info "Creating ($MODEL_NAME $MODEL_VERSION, $SKU_NAME, capacity $SKU_CAPACITY)…"
  az cognitiveservices account deployment create \
    --name "$ACCOUNT_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --deployment-name "$DEPLOYMENT_NAME" \
    --model-name "$MODEL_NAME" \
    --model-version "$MODEL_VERSION" \
    --model-format OpenAI \
    --sku-name "$SKU_NAME" \
    --sku-capacity "$SKU_CAPACITY" \
    --output none
  info "Created."
fi

# --- keyless access --------------------------------------------------------

say "Granting your account permission to call the model"
ACCOUNT_ID="$(az cognitiveservices account show -n "$ACCOUNT_NAME" -g "$RESOURCE_GROUP" --query id -o tsv)"
USER_OID="$(az ad signed-in-user show --query id -o tsv 2>/dev/null || true)"

if [ -z "$USER_OID" ]; then
  info "Could not read your user object id (common with service principals)."
  info "Assign 'Cognitive Services OpenAI User' on the resource manually, or re-run with WRITE_KEY=1."
else
  if az role assignment create \
      --assignee-object-id "$USER_OID" \
      --assignee-principal-type User \
      --role "Cognitive Services OpenAI User" \
      --scope "$ACCOUNT_ID" \
      --output none 2>/dev/null; then
    info "Role assigned. It can take a couple of minutes to take effect."
  else
    info "Role already assigned (or you lack rights to assign it) — continuing."
  fi
fi

# --- write .env ------------------------------------------------------------

ENDPOINT="$(az cognitiveservices account show -n "$ACCOUNT_NAME" -g "$RESOURCE_GROUP" --query properties.endpoint -o tsv)"

say "Writing $ENV_FILE"
TARGET="$REPO_ROOT/$ENV_FILE"
if [ -f "$TARGET" ]; then
  cp "$TARGET" "$TARGET.bak"
  info "Existing file backed up to $ENV_FILE.bak"
fi

{
  echo "# Written by scripts/setup_foundry.sh"
  echo "AZURE_AI_ENDPOINT=$ENDPOINT"
  echo "AZURE_AI_DEPLOYMENT=$DEPLOYMENT_NAME"
  if [ "$WRITE_KEY" = "1" ]; then
    KEY="$(az cognitiveservices account keys list -n "$ACCOUNT_NAME" -g "$RESOURCE_GROUP" --query key1 -o tsv)"
    echo "AZURE_AI_API_KEY=$KEY"
  else
    echo "# No key: the app authenticates as your 'az login' identity."
    echo "AZURE_AI_API_KEY="
  fi
  echo "AZURE_AI_API_VERSION=2024-10-21"
} > "$TARGET"

chmod 600 "$TARGET"
info "Done."

cat <<EOF

  Endpoint:   $ENDPOINT
  Deployment: $DEPLOYMENT_NAME  ($MODEL_NAME $MODEL_VERSION, $SKU_NAME)
  Auth:       $([ "$WRITE_KEY" = "1" ] && echo "API key" || echo "Entra ID (your az login)")

Next:

  python -m pip install -r requirements-dev.txt
  python scripts/check_foundry.py          # verify the connection
  python -m uvicorn app.main:app --reload

To tear the whole thing down again:

  az group delete --name $RESOURCE_GROUP --yes --no-wait

EOF
