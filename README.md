# Finance Workflow Dashboard

Workflow management for finance processes, with an Azure AI Foundry assistant that
answers questions about the same data the dashboard renders.

This is the Foundry-backed counterpart to the workflow management tool in the
Coral dashboard: a portfolio of finance processes with their steps, owners,
systems, controls and run history, plus a chatbot to interrogate it.

## Running it

```bash
python -m pip install -r requirements-dev.txt
python -m uvicorn app.main:app --reload
```

Then open <http://127.0.0.1:8000>.

No cloud credentials are needed to run the dashboard. Without Microsoft Foundry
configured the chatbot falls back to an offline keyword responder — see
[The chatbot](#the-chatbot) below.

Tests:

```bash
python -m pytest
```

## Connecting Microsoft Foundry

This needs the Azure control plane, so run it on a machine with the Azure CLI —
not in a cloud dev container, where outbound access to Azure is usually blocked.

```bash
az login
./scripts/setup_foundry.sh        # provisions everything, writes .env
python scripts/check_foundry.py   # verifies it, explains anything that failed
```

`setup_foundry.sh` creates a resource group, a Foundry resource (an `AIServices`
Cognitive Services account with a custom domain), a `gpt-4o` deployment, and the
role assignment your own account needs to call it. It is safe to re-run — it
reuses whatever already exists. Everything is overridable:

```bash
LOCATION=swedencentral MODEL_NAME=gpt-4o SKU_CAPACITY=50 ./scripts/setup_foundry.sh
```

If the model is not offered in your region the script prints what *is* available
there and stops, rather than failing halfway through.

**Authentication defaults to keyless.** The app authenticates as your `az login`
identity through `DefaultAzureCredential`, so no secret is written to disk; in
Azure the same code path picks up the managed identity. Pass `WRITE_KEY=1` if you
would rather use an API key — `.env` is gitignored and written `chmod 600` either
way.

`check_foundry.py` is worth running before the app. It tests the endpoint, the
credential, **and whether the deployment actually honours tool calls** — the
chatbot depends on tool calling, and a deployment that silently ignores tools
would otherwise show up as invented figures rather than an error. It translates
the usual 401 / 403 / 404 / 429 responses into the specific fix.

To set it up by hand instead, copy `.env.example` to `.env` and fill in
`AZURE_AI_ENDPOINT` and `AZURE_AI_DEPLOYMENT`.

Tearing it down:

```bash
az group delete --name rg-finance-workflow --yes --no-wait
```

## What is in it

**Dashboard.** A portfolio view with headline figures, on-time delivery by
domain, and a process list ordered by criticality then reliability — a worklist,
not an alphabetical inventory. Filters sit in one row above everything they
scope.

**Process detail.** Every step in sequence with its type, role, effort, systems,
controls, and the business objects it consumes and produces. Plus run history
against SLA and the process's open exceptions.

**Chatbot.** A side panel that answers questions about the portfolio.

Every chart has a table view, so no value is reachable only through colour or a
tooltip. The interface follows the system light/dark setting and has its own
toggle.

## Architecture

```
app/
  main.py          FastAPI app: JSON API + static dashboard
  api/routes.py    every endpoint the front end uses
  store.py         WorkflowStore interface + JSON-backed implementation
  chat.py          Azure AI Foundry tool-calling loop + offline fallback
  models.py        domain models
  config.py        settings (env / .env)
  dependencies.py  composition root — the one place the store is chosen
data/
  workflows.json   seeded dataset
scripts/seed.py    regenerates it
web/               the dashboard (no framework, no build step)
tests/
```

**Swapping the data source.** `WorkflowStore` is the seam. Moving to Cosmos DB or
Azure SQL means writing a second implementation and changing `get_store()` in
`dependencies.py`. Nothing above that module knows the data came from a file.

**The seed data.** Reference data (domains, owners, systems, business objects,
processes and their steps) is hand-authored in `scripts/seed.py` so it reads like
a real finance operation — record to report, order to cash, procure to pay, FP&A,
treasury, tax and compliance. Only the execution history is generated, from a
fixed random seed, so re-running the script is byte-identical until the
hand-authored data changes:

```bash
python scripts/seed.py
```

## The chatbot

The assistant answers by **calling tools** that read the same store the REST API
uses, rather than by having the dataset pasted into its prompt. Three consequences
worth keeping: the figures it quotes are the figures on screen, the dataset can
outgrow the context window, and every answer carries a record of the queries
behind it — expand "Sources" under any reply.

Tools available to it: `get_portfolio_metrics`, `list_workflows`, `get_workflow`,
`list_runs`, `list_open_exceptions`, `list_reference_data`.

**When Azure is not configured**, the panel says "Assistant offline" and replies
come from a deterministic keyword responder that calls the same tools. It does no
language understanding, and every reply it produces says so. It exists so the
dashboard is demonstrable without credentials — not as a substitute for the model.

## How this grows

The data model is already shaped for the phases after this one, which is why
steps declare their input and output business objects rather than just naming
systems:

- **Process authoring.** Users build out their own finance processes in the UI.
  `WorkflowStore` gains write methods; `routes.py` gains the write endpoints.
- **Ontology development.** The business objects on each step are the candidate
  entities, and the step wiring already describes how they relate.
- **The ontology agent.** A separate agent reads across the authored processes and
  proposes the ontology — object types, properties and links — from the
  input/output graph the processes describe.

Nothing here is stubbed for those phases; the point is that they are additive
rather than a rewrite.

## Notes

- Colours follow a validated palette: categorical hues carry step type, a single
  sequential hue carries magnitude, and status colours (SLA met / breached) are
  reserved and always paired with a written label.
- API docs are at `/docs` when the app is running.
