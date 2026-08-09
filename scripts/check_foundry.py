"""Verify the Microsoft Foundry connection and explain any failure.

Run this after scripts/setup_foundry.sh, before starting the app:

    python scripts/check_foundry.py

It checks the three things that actually break, in order: can we resolve the
endpoint, can we authenticate, and does the deployment support tool calling —
which the chatbot depends on, and which is the one failure that would otherwise
only show up as a bad answer rather than an error.
"""

from __future__ import annotations

import socket
import sys
from urllib.parse import urlparse

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))

from app.config import get_settings  # noqa: E402

GREEN, RED, YELLOW, BOLD, RESET = "\033[32m", "\033[31m", "\033[33m", "\033[1m", "\033[0m"

ok = lambda msg: print(f"  {GREEN}✓{RESET} {msg}")  # noqa: E731
bad = lambda msg: print(f"  {RED}✗{RESET} {msg}")  # noqa: E731
warn = lambda msg: print(f"  {YELLOW}!{RESET} {msg}")  # noqa: E731
step = lambda msg: print(f"\n{BOLD}{msg}{RESET}")  # noqa: E731


def fail(message: str, *hints: str) -> None:
    bad(message)
    for hint in hints:
        print(f"    → {hint}")
    sys.exit(1)


def main() -> None:
    settings = get_settings()

    step("Configuration")
    if not settings.azure_ai_endpoint:
        fail(
            "AZURE_AI_ENDPOINT is not set.",
            "Run ./scripts/setup_foundry.sh, or copy .env.example to .env and fill it in.",
        )
    ok(f"Endpoint: {settings.azure_openai_endpoint}")
    ok(f"Deployment: {settings.azure_ai_deployment}")
    ok(f"API version: {settings.azure_ai_api_version}")

    if settings.azure_ai_api_key:
        tail = settings.azure_ai_api_key[-4:]
        ok(f"Auth: API key (…{tail})")
    else:
        ok("Auth: Entra ID — your 'az login' identity or the host's managed identity")

    step("Reaching the endpoint")
    host = urlparse(settings.azure_openai_endpoint).hostname
    if not host:
        fail(f"Could not parse a hostname out of {settings.azure_ai_endpoint!r}.")
    try:
        socket.getaddrinfo(host, 443)
        ok(f"{host} resolves")
    except socket.gaierror as exc:
        fail(
            f"{host} does not resolve ({exc}).",
            "Check AZURE_AI_ENDPOINT for a typo.",
            "It should look like https://<resource>.openai.azure.com/ or "
            "https://<resource>.cognitiveservices.azure.com/",
        )

    step("Authenticating and calling the deployment")
    try:
        from openai import AzureOpenAI  # noqa: F401
    except ImportError:
        fail("The `openai` package is missing.", "python -m pip install -r requirements.txt")

    from app.chat import ChatEngine
    from app.dependencies import get_store

    engine = ChatEngine(get_store(), settings)
    client = engine._get_client()
    if client is None:
        fail(engine._client_error or "The client could not be constructed.")

    try:
        completion = client.chat.completions.create(
            model=settings.azure_ai_deployment,
            messages=[{"role": "user", "content": "Reply with the single word: ready"}],
            max_tokens=10,
            temperature=0,
        )
    except Exception as exc:  # noqa: BLE001 - the whole point is to explain it
        diagnose(exc, settings)
        raise SystemExit(1) from exc

    ok(f"Model replied: {(completion.choices[0].message.content or '').strip()!r}")

    step("Checking tool calling")
    # The chatbot answers by calling tools. A deployment that ignores them would
    # still "work" here but would invent figures in the app, so test it directly.
    from app.chat import TOOL_SCHEMAS

    probe = client.chat.completions.create(
        model=settings.azure_ai_deployment,
        messages=[
            {"role": "system", "content": "Use the tools to answer."},
            {"role": "user", "content": "How many processes are in the portfolio overall?"},
        ],
        tools=TOOL_SCHEMAS,
        tool_choice="auto",
        temperature=0,
    )
    calls = probe.choices[0].message.tool_calls
    if calls:
        ok(f"Tool calling works — the model asked for: {', '.join(c.function.name for c in calls)}")
    else:
        warn("The model answered without calling a tool.")
        print("    → Tool calling may be unsupported on this model or API version.")
        print("    → gpt-4o with API version 2024-10-21 or newer is a known-good combination.")

    step("End-to-end through the app's own chat engine")
    response = engine.answer("Which two processes have the worst on-time rate?")
    if response.mode != "azure_ai_foundry":
        fail(
            f"The engine fell back to {response.mode} mode.",
            response.notice or "No reason given.",
        )
    ok(f"Mode: {response.mode}")
    ok(f"Queries used: {', '.join(c.name for c in response.tool_calls) or 'none'}")
    print(f"\n{response.reply}\n")

    print(f"{GREEN}{BOLD}All good.{RESET} Start the app with: python -m uvicorn app.main:app --reload\n")


def diagnose(exc: Exception, settings) -> None:
    """Turn the usual Azure errors into something actionable."""
    status = getattr(exc, "status_code", None)
    text = str(exc)

    if status == 401 or "401" in text:
        bad("401 Unauthorized — the credential was rejected.")
        if settings.azure_ai_api_key:
            print("    → The API key looks wrong. Re-read it with:")
            print("      az cognitiveservices account keys list -n <resource> -g <group>")
        else:
            print("    → Run 'az login' first, or set AZURE_AI_API_KEY.")
    elif status == 403 or "403" in text or "PermissionDenied" in text:
        bad("403 Forbidden — authenticated, but not allowed to call this resource.")
        print("    → You need the 'Cognitive Services OpenAI User' role on the resource:")
        print("      az role assignment create --assignee-object-id $(az ad signed-in-user show --query id -o tsv) \\")
        print("        --assignee-principal-type User --role 'Cognitive Services OpenAI User' \\")
        print("        --scope $(az cognitiveservices account show -n <resource> -g <group> --query id -o tsv)")
        print("    → If you just assigned it, wait a couple of minutes and retry — it propagates slowly.")
    elif status == 404 or "404" in text or "DeploymentNotFound" in text:
        bad(f"404 — no deployment named {settings.azure_ai_deployment!r} on this resource.")
        print("    → AZURE_AI_DEPLOYMENT is the *deployment* name you chose, not the model name.")
        print("    → List what exists:")
        print("      az cognitiveservices account deployment list -n <resource> -g <group> -o table")
    elif status == 429 or "429" in text:
        bad("429 — rate limited or out of quota.")
        print("    → Raise the deployment capacity, or wait and retry.")
    else:
        bad(f"The request failed: {type(exc).__name__}: {exc}")
        print("    → If this mentions credentials, 'az login' is the usual fix.")


if __name__ == "__main__":
    main()
