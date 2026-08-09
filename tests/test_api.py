"""Tests for the HTTP surface and the chatbot's offline path."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.chat import ChatEngine
from app.config import Settings
from app.dependencies import get_store
from app.main import app


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


def test_health_reports_data_freshness_and_chat_mode(client: TestClient) -> None:
    payload = client.get("/api/health").json()
    assert payload["status"] == "ok"
    assert payload["as_of"]
    assert payload["chat"]["mode"] in ("azure_ai_foundry", "offline")


def test_index_and_static_assets_are_served(client: TestClient) -> None:
    index = client.get("/")
    assert index.status_code == 200
    assert "Finance Workflow Dashboard" in index.text

    for asset in ("/static/app.js", "/static/styles.css"):
        assert client.get(asset).status_code == 200


def test_list_workflows_returns_summaries_with_metrics(client: TestClient) -> None:
    payload = client.get("/api/workflows").json()
    assert payload

    first = payload[0]
    # The list view renders names, not ids, so the API must resolve them.
    assert first["domain_name"] and first["owner_name"]
    assert "metrics" in first
    assert "steps" not in first, "the list shape should stay light"


def test_workflow_filters_are_applied(client: TestClient) -> None:
    filtered = client.get("/api/workflows", params={"domain_id": "p2p"}).json()
    assert filtered
    assert all(w["domain_id"] == "p2p" for w in filtered)

    combined = client.get(
        "/api/workflows", params={"domain_id": "p2p", "criticality": "critical"}
    ).json()
    assert all(w["criticality"] == "critical" for w in combined)
    assert len(combined) <= len(filtered)


def test_workflow_search_parameter(client: TestClient) -> None:
    hits = client.get("/api/workflows", params={"search": "vat"}).json()
    assert any("VAT" in w["name"] for w in hits)


def test_workflow_detail_includes_steps_and_resolved_references(client: TestClient) -> None:
    detail = client.get("/api/workflows/wf-invoice-processing").json()

    assert detail["workflow"]["name"] == "Vendor Invoice Processing"
    assert detail["domain"]["name"] == "Procure to Pay"
    assert detail["owner"]["name"]
    assert detail["systems"] and detail["data_objects"]

    steps = detail["workflow"]["steps"]
    assert [s["seq"] for s in steps] == sorted(s["seq"] for s in steps)
    assert any(s["controls"] for s in steps), "this process has SOX controls"


def test_unknown_workflow_is_404(client: TestClient) -> None:
    response = client.get("/api/workflows/wf-nope")
    assert response.status_code == 404


def test_runs_endpoint_filters_and_limits(client: TestClient) -> None:
    runs = client.get("/api/runs", params={"workflow_id": "wf-payment-run", "limit": 5}).json()
    assert len(runs) <= 5
    assert all(r["workflow_id"] == "wf-payment-run" for r in runs)

    failed = client.get("/api/runs", params={"status": "failed", "limit": 50}).json()
    assert all(r["status"] == "failed" for r in failed)


def test_runs_limit_is_bounded(client: TestClient) -> None:
    assert client.get("/api/runs", params={"limit": 5000}).status_code == 422


def test_exceptions_endpoint(client: TestClient) -> None:
    exceptions = client.get("/api/exceptions", params={"severity": "high"}).json()
    assert all(e["severity"] == "high" for e in exceptions)
    assert all(e["workflow_name"] for e in exceptions)


def test_reference_endpoint_serves_every_filter_list(client: TestClient) -> None:
    reference = client.get("/api/reference").json()
    for key in ("domains", "owners", "systems", "data_objects"):
        assert reference[key], f"{key} should not be empty"


def test_metrics_endpoint_shape(client: TestClient) -> None:
    metrics = client.get("/api/metrics").json()
    assert metrics["total_workflows"] > 0
    assert 0 <= metrics["automation_rate"] <= 1
    assert metrics["by_domain"]


def test_empty_chat_message_is_rejected(client: TestClient) -> None:
    assert client.post("/api/chat", json={"message": "   "}).status_code == 400


# --- offline chatbot ------------------------------------------------------
#
# These pin the fallback's behaviour: it must answer from the store, label
# itself, and never claim to be the model.


@pytest.fixture(scope="module")
def offline_engine() -> ChatEngine:
    return ChatEngine(get_store(), Settings(azure_ai_endpoint="", azure_ai_api_key=""))


def test_offline_engine_is_not_marked_available(offline_engine: ChatEngine) -> None:
    assert offline_engine.available is False


def test_offline_reply_is_labelled_and_grounded(offline_engine: ChatEngine) -> None:
    response = offline_engine.answer("How is the portfolio doing overall?")
    assert response.mode == "offline"
    assert response.notice and "not configured" in response.notice
    assert response.tool_calls, "the offline path must still read from the store"
    assert "17" in response.reply or "processes" in response.reply


def test_offline_routes_a_named_workflow_to_its_detail(offline_engine: ChatEngine) -> None:
    response = offline_engine.answer("Tell me about the Month-End Close")
    assert response.tool_calls[0].name == "get_workflow"
    assert response.tool_calls[0].arguments["workflow_id"] == "wf-month-end-close"
    assert "Sub-ledger cut-off" in response.reply


def test_offline_prefers_the_longest_workflow_name_matched(offline_engine: ChatEngine) -> None:
    """'Customer Credit Review' must not lose to a shorter overlapping name."""
    response = offline_engine.answer("what happens in customer credit review?")
    assert response.tool_calls[0].arguments["workflow_id"] == "wf-credit-review"


def test_offline_routes_exception_questions(offline_engine: ChatEngine) -> None:
    response = offline_engine.answer("What is going wrong at the moment?")
    assert response.tool_calls[0].name == "list_open_exceptions"


def test_offline_routes_risk_questions(offline_engine: ChatEngine) -> None:
    response = offline_engine.answer("Which processes are missing their SLA?")
    assert response.tool_calls[0].name == "list_workflows"
    assert "on time" in response.reply.lower()


def test_offline_routes_ontology_questions(offline_engine: ChatEngine) -> None:
    response = offline_engine.answer("What would the ontology entities be?")
    assert response.tool_calls[0].name == "list_reference_data"
    assert "Vendor Invoice" in response.reply


def test_chat_endpoint_returns_a_reply(client: TestClient) -> None:
    payload = client.post("/api/chat", json={"message": "Which processes are at risk?"}).json()
    assert payload["reply"]
    assert payload["mode"] in ("azure_ai_foundry", "offline")


def test_chat_tools_cover_every_advertised_schema(offline_engine: ChatEngine) -> None:
    """The schemas sent to the model and the callables that run must not drift."""
    from app.chat import TOOL_SCHEMAS

    advertised = {schema["function"]["name"] for schema in TOOL_SCHEMAS}
    implemented = set(offline_engine._tools)
    assert advertised == implemented


def test_chat_tools_return_json_native_values(offline_engine: ChatEngine) -> None:
    """Tool results are serialised into the model's context, so every value must
    already be JSON-native. A raw enum survives `default=str` as
    'Criticality.CRITICAL', which is what the model then quotes back."""
    import json

    for name, tool in offline_engine._tools.items():
        result = tool() if name != "get_workflow" else tool(workflow_id="wf-payment-run")
        assert result
        dumped = json.dumps(result)  # no default= : must not need coercing
        for enum_name in ("Criticality.", "RunStatus.", "StepType.", "WorkflowStatus."):
            assert enum_name not in dumped


def test_offline_reply_never_shows_enum_reprs(offline_engine: ChatEngine) -> None:
    for question in ("Which processes are at risk?", "Tell me about the Month-End Close"):
        reply = offline_engine.answer(question).reply
        assert "Criticality." not in reply
        assert "RunStatus." not in reply
        assert "StepType." not in reply
