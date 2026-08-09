"""The dashboard chatbot.

The bot answers questions about the workflow portfolio by *calling tools* that
read the same `WorkflowStore` the REST API uses, rather than by having the
dataset stuffed into its prompt. That matters for three reasons: the numbers it
quotes are the numbers on screen, the dataset can grow past the context window,
and every answer carries a record of which queries produced it (surfaced in the
UI as "sources").

If Azure AI Foundry is not configured the module falls back to a deterministic
offline responder. It routes on keywords, calls the same tools, and formats the
results — it does no language understanding and says so on every reply. It
exists so the dashboard is demonstrable without cloud credentials, not as a
substitute for the model.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable

from .config import Settings
from .models import ChatMessage, ChatResponse, ChatToolCall
from .store import WorkflowStore

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are the analyst assistant embedded in a finance workflow dashboard. You help \
finance and controllership staff understand their process portfolio: how processes \
run, who owns them, where they break, and how they perform against SLA.

Rules:
- Always ground answers in the tools. Never invent a workflow, owner, number or date.
- If the tools return nothing relevant, say so plainly rather than guessing.
- Prefer specifics: name the workflow, the step, the owner, the figure.
- Rates come back as decimals (0.72 means 72%). Present them as percentages.
- Durations are in hours unless stated otherwise.
- Be concise. Two or three short paragraphs, or a short list. No preamble.
- Use British English spelling, matching the rest of the application.
- When asked "why" something underperforms, look at its open exceptions and its \
risk_notes before answering, and distinguish what the data shows from what you infer.
"""


# --- tool definitions ----------------------------------------------------
#
# The JSON schemas below are sent to the model; the callables in
# `_build_tool_registry` are what actually run. Keep the two in step.

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_portfolio_metrics",
            "description": (
                "Portfolio-wide rollup: workflow counts, overall on-time rate, "
                "automation rate, open exceptions, at-risk count, and breakdowns "
                "by domain, status and criticality. Start here for 'overall' or "
                "'how are we doing' questions."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_workflows",
            "description": (
                "List workflows with their headline metrics. All filters are "
                "optional and combine with AND. Use `search` for free text "
                "across names, descriptions, tags, steps, owners and systems."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "domain_id": {
                        "type": "string",
                        "enum": ["r2r", "o2c", "p2p", "fpa", "treasury", "tax_compliance"],
                        "description": "Filter to one process domain.",
                    },
                    "status": {
                        "type": "string",
                        "enum": ["draft", "under_review", "active", "retired"],
                    },
                    "criticality": {
                        "type": "string",
                        "enum": ["low", "medium", "high", "critical"],
                    },
                    "frequency": {
                        "type": "string",
                        "enum": ["daily", "weekly", "monthly", "quarterly", "annual"],
                    },
                    "owner_id": {"type": "string", "description": "e.g. own-mercer"},
                    "tag": {"type": "string", "description": "e.g. sox, close, payments"},
                    "search": {"type": "string", "description": "Free-text query."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_workflow",
            "description": (
                "Full detail for one workflow: every step with its type, role, "
                "duration, systems, the business objects it consumes and produces, "
                "its controls, plus metrics and recent runs. Use this for any "
                "question about how a specific process actually works."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "workflow_id": {
                        "type": "string",
                        "description": "e.g. wf-month-end-close. Use list_workflows to find it.",
                    }
                },
                "required": ["workflow_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_runs",
            "description": "Execution history. Newest first.",
            "parameters": {
                "type": "object",
                "properties": {
                    "workflow_id": {"type": "string"},
                    "status": {
                        "type": "string",
                        "enum": ["in_progress", "completed", "failed"],
                    },
                    "period": {
                        "type": "string",
                        "description": "Prefix match, e.g. '2026-07' or '2026'.",
                    },
                    "limit": {"type": "integer", "default": 20},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_open_exceptions",
            "description": (
                "Unresolved exceptions across runs, annotated with the workflow "
                "and step they occurred on. Highest severity first. This is the "
                "place to look for 'what is going wrong' questions."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "workflow_id": {"type": "string"},
                    "severity": {"type": "string", "enum": ["low", "medium", "high"]},
                    "limit": {"type": "integer", "default": 25},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_reference_data",
            "description": (
                "The domains, owners, systems and business data objects in the "
                "portfolio. Use it to resolve a name a user mentioned to an id, "
                "or to answer questions about systems and data objects."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


def _build_tool_registry(store: WorkflowStore) -> dict[str, Callable[..., Any]]:
    """Bind the tool names the model sees to concrete store queries."""

    def get_portfolio_metrics() -> Any:
        return store.portfolio_metrics().model_dump(mode="json")

    def list_workflows(**kwargs: Any) -> Any:
        allowed = {
            "domain_id",
            "status",
            "criticality",
            "frequency",
            "owner_id",
            "tag",
            "search",
        }
        filters = {k: v for k, v in kwargs.items() if k in allowed and v}
        summaries = store.list_workflows(**filters)
        return {
            "count": len(summaries),
            "workflows": [s.model_dump(mode="json") for s in summaries],
        }

    def get_workflow(workflow_id: str) -> Any:
        detail = store.get_workflow(workflow_id)
        if detail is None:
            return {"error": f"No workflow with id {workflow_id!r}."}
        return detail.model_dump(mode="json")

    def list_runs(
        workflow_id: str | None = None,
        status: str | None = None,
        period: str | None = None,
        limit: int = 20,
    ) -> Any:
        runs = store.list_runs(
            workflow_id=workflow_id,
            status=status,
            period=period,
            limit=min(int(limit or 20), 100),
        )
        return {"count": len(runs), "runs": [r.model_dump(mode="json") for r in runs]}

    def list_open_exceptions(
        workflow_id: str | None = None, severity: str | None = None, limit: int = 25
    ) -> Any:
        exceptions = store.list_open_exceptions(
            workflow_id=workflow_id, severity=severity, limit=min(int(limit or 25), 100)
        )
        return {"count": len(exceptions), "exceptions": exceptions}

    def list_reference_data() -> Any:
        return {
            "domains": [d.model_dump(mode="json") for d in store.list_domains()],
            "owners": [o.model_dump(mode="json") for o in store.list_owners()],
            "systems": [s.model_dump(mode="json") for s in store.list_systems()],
            "data_objects": [o.model_dump(mode="json") for o in store.list_data_objects()],
        }

    return {
        "get_portfolio_metrics": get_portfolio_metrics,
        "list_workflows": list_workflows,
        "get_workflow": get_workflow,
        "list_runs": list_runs,
        "list_open_exceptions": list_open_exceptions,
        "list_reference_data": list_reference_data,
    }


class ChatEngine:
    """Answers questions about the portfolio, via Azure AI Foundry when configured."""

    def __init__(self, store: WorkflowStore, settings: Settings) -> None:
        self._store = store
        self._settings = settings
        self._tools = _build_tool_registry(store)
        self._client: Any | None = None
        self._client_error: str | None = None

    # -- Azure client -----------------------------------------------------

    @property
    def available(self) -> bool:
        return self._settings.azure_configured

    def _get_client(self) -> Any | None:
        """Lazily construct the Azure OpenAI client, caching success or failure.

        Construction is deferred to the first chat request so that a
        misconfigured endpoint degrades that request rather than preventing the
        whole dashboard from starting.
        """
        if self._client is not None or self._client_error is not None:
            return self._client

        try:
            from openai import AzureOpenAI
        except ImportError:  # pragma: no cover - dependency is in requirements
            self._client_error = "The `openai` package is not installed."
            return None

        settings = self._settings
        kwargs: dict[str, Any] = {
            "azure_endpoint": settings.azure_openai_endpoint,
            "api_version": settings.azure_ai_api_version,
        }

        if settings.azure_ai_api_key:
            kwargs["api_key"] = settings.azure_ai_api_key
        else:
            # No key supplied: authenticate as the signed-in principal or the
            # managed identity the app is running under.
            try:
                from azure.identity import DefaultAzureCredential, get_bearer_token_provider

                kwargs["azure_ad_token_provider"] = get_bearer_token_provider(
                    DefaultAzureCredential(),
                    "https://cognitiveservices.azure.com/.default",
                )
            except ImportError:
                self._client_error = (
                    "No AZURE_AI_API_KEY set and `azure-identity` is not installed, "
                    "so Entra ID authentication is unavailable."
                )
                return None
            except Exception as exc:  # pragma: no cover - environment dependent
                self._client_error = f"Could not acquire an Entra ID token: {exc}"
                return None

        try:
            self._client = AzureOpenAI(**kwargs)
        except Exception as exc:  # pragma: no cover - environment dependent
            self._client_error = f"Could not create the Azure AI Foundry client: {exc}"
            return None

        return self._client

    # -- public entry point -----------------------------------------------

    def answer(self, message: str, history: list[ChatMessage] | None = None) -> ChatResponse:
        if not self.available:
            return self._offline_answer(
                message,
                notice=(
                    "Azure AI Foundry is not configured, so this reply came from the "
                    "built-in offline responder — keyword matching over the same data, "
                    "with no language model involved. Set AZURE_AI_ENDPOINT and "
                    "AZURE_AI_DEPLOYMENT to enable the real assistant."
                ),
            )

        client = self._get_client()
        if client is None:
            return self._offline_answer(
                message,
                notice=(
                    f"Falling back to the offline responder: {self._client_error} "
                    "The reply below is keyword matching, not a language model."
                ),
            )

        try:
            return self._foundry_answer(client, message, history or [])
        except Exception as exc:
            logger.exception("Azure AI Foundry chat request failed")
            return self._offline_answer(
                message,
                notice=(
                    f"The Azure AI Foundry request failed ({type(exc).__name__}: {exc}). "
                    "The reply below is from the offline responder instead."
                ),
            )

    # -- model-backed path ------------------------------------------------

    def _foundry_answer(
        self, client: Any, message: str, history: list[ChatMessage]
    ) -> ChatResponse:
        messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
        # Only user/assistant turns are replayed; tool traffic from earlier turns
        # is not, so each question re-queries rather than trusting stale results.
        for turn in history[-10:]:
            if turn.role in ("user", "assistant") and turn.content:
                messages.append({"role": turn.role, "content": turn.content})
        messages.append({"role": "user", "content": message})

        used_tools: list[ChatToolCall] = []

        for _ in range(self._settings.chat_max_tool_iterations):
            completion = client.chat.completions.create(
                model=self._settings.azure_ai_deployment,
                messages=messages,
                tools=TOOL_SCHEMAS,
                tool_choice="auto",
                temperature=self._settings.chat_temperature,
            )
            choice = completion.choices[0].message

            if not choice.tool_calls:
                return ChatResponse(
                    reply=(choice.content or "").strip() or "I could not produce an answer.",
                    mode="azure_ai_foundry",
                    tool_calls=used_tools,
                )

            messages.append(
                {
                    "role": "assistant",
                    "content": choice.content,
                    "tool_calls": [
                        {
                            "id": call.id,
                            "type": "function",
                            "function": {
                                "name": call.function.name,
                                "arguments": call.function.arguments,
                            },
                        }
                        for call in choice.tool_calls
                    ],
                }
            )

            for call in choice.tool_calls:
                name = call.function.name
                try:
                    arguments = json.loads(call.function.arguments or "{}")
                except json.JSONDecodeError:
                    arguments = {}

                used_tools.append(ChatToolCall(name=name, arguments=arguments))
                result = self._run_tool(name, arguments)

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": json.dumps(result, default=str),
                    }
                )

        # Tool budget exhausted. Ask for a final answer with the tools withdrawn
        # so the model has to commit to what it already gathered.
        completion = client.chat.completions.create(
            model=self._settings.azure_ai_deployment,
            messages=messages
            + [
                {
                    "role": "user",
                    "content": "Answer now using the information you already have.",
                }
            ],
            temperature=self._settings.chat_temperature,
        )
        return ChatResponse(
            reply=(completion.choices[0].message.content or "").strip()
            or "I could not produce an answer.",
            mode="azure_ai_foundry",
            tool_calls=used_tools,
            notice="Reached the tool-call limit for this question; the answer may be partial.",
        )

    def _run_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        tool = self._tools.get(name)
        if tool is None:
            return {"error": f"Unknown tool {name!r}."}
        try:
            return tool(**arguments)
        except TypeError as exc:
            return {"error": f"Invalid arguments for {name}: {exc}"}
        except Exception as exc:
            logger.exception("Tool %s failed", name)
            return {"error": f"{name} failed: {exc}"}

    # -- offline path -----------------------------------------------------

    def _offline_answer(self, message: str, *, notice: str) -> ChatResponse:
        """Deterministic keyword routing over the same tools.

        This is intentionally simple and intentionally honest: every reply it
        produces is accompanied by `notice` explaining that no model was used.
        """
        text = message.lower()
        used: list[ChatToolCall] = []

        def record(name: str, **arguments: Any) -> Any:
            used.append(ChatToolCall(name=name, arguments=arguments))
            return self._tools[name](**arguments)

        def pct(value: float | None) -> str:
            return "n/a" if value is None else f"{value * 100:.0f}%"

        # A specific workflow named in the question wins over any topic routing.
        matched = self._match_workflow(text)
        if matched is not None:
            detail = record("get_workflow", workflow_id=matched)
            metrics = detail["metrics"]
            workflow = detail["workflow"]
            lines = [
                f"**{workflow['name']}** — {detail['domain']['name']}, owned by "
                f"{detail['owner']['name']} ({detail['owner']['role']}).",
                f"{workflow['description']}",
                "",
                f"- Runs {workflow['frequency']}, SLA {workflow['sla_hours']}h, "
                f"criticality {workflow['criticality']}, maturity {workflow['maturity']}",
                f"- {workflow['step_count']} steps, {workflow['planned_hours']}h planned effort, "
                f"{pct(metrics['automation_rate'])} of steps unattended",
                f"- On-time {pct(metrics['on_time_rate'])} over {metrics['total_runs']} runs "
                f"({metrics['failed_runs']} failed), average {metrics['avg_duration_hours']}h",
                f"- {metrics['open_exceptions']} open exception(s)",
            ]
            if workflow.get("risk_notes"):
                lines += ["", f"Known risk: {workflow['risk_notes']}"]
            lines += ["", "Steps:"]
            lines += [
                f"{s['seq']}. {s['name']} — {s['type']}, {s['role']}, {s['duration_minutes']}m"
                for s in workflow["steps"]
            ]
            return ChatResponse(
                reply="\n".join(lines), mode="offline", tool_calls=used, notice=notice
            )

        if any(word in text for word in ("exception", "issue", "problem", "wrong", "break", "fail")):
            data = record("list_open_exceptions", limit=10)
            if not data["exceptions"]:
                body = "There are no open exceptions across the portfolio."
            else:
                body = f"{data['count']} open exception(s), highest severity first:\n\n" + "\n".join(
                    f"- **{e['severity']}** · {e['workflow_name']} → {e['step_name'] or e['step_id']} "
                    f"({e['period']}): {e['description']}"
                    for e in data["exceptions"]
                )
            return ChatResponse(reply=body, mode="offline", tool_calls=used, notice=notice)

        if any(word in text for word in ("at risk", "risk", "late", "sla", "on time", "on-time", "overdue", "worst")):
            data = record("list_workflows")
            ranked = [w for w in data["workflows"] if w["metrics"]["on_time_rate"] is not None]
            ranked.sort(key=lambda w: w["metrics"]["on_time_rate"])
            body = "Lowest on-time performance:\n\n" + "\n".join(
                f"- {w['name']} ({w['domain_name']}, {w['criticality']}): "
                f"{pct(w['metrics']['on_time_rate'])} on time, "
                f"{w['metrics']['open_exceptions']} open exception(s) — {w['owner_name']}"
                for w in ranked[:8]
            )
            return ChatResponse(reply=body, mode="offline", tool_calls=used, notice=notice)

        if "automat" in text or "manual" in text:
            data = record("list_workflows")
            ranked = sorted(data["workflows"], key=lambda w: w["metrics"]["automation_rate"])
            body = "Least automated processes (share of unattended steps):\n\n" + "\n".join(
                f"- {w['name']} ({w['domain_name']}): {pct(w['metrics']['automation_rate'])} "
                f"of {w['step_count']} steps"
                for w in ranked[:8]
            )
            return ChatResponse(reply=body, mode="offline", tool_calls=used, notice=notice)

        if any(word in text for word in ("system", "erp", "sap", "tool", "application")):
            reference = record("list_reference_data")
            body = "Systems in the portfolio:\n\n" + "\n".join(
                f"- {s['name']} ({s['kind']})" for s in reference["systems"]
            )
            return ChatResponse(reply=body, mode="offline", tool_calls=used, notice=notice)

        if any(word in text for word in ("object", "ontology", "entity", "data model")):
            reference = record("list_reference_data")
            body = (
                f"{len(reference['data_objects'])} business objects are referenced by the "
                "processes. These are the candidate entities for an ontology:\n\n"
                + "\n".join(f"- {o['name']} — {o['description']}" for o in reference["data_objects"])
            )
            return ChatResponse(reply=body, mode="offline", tool_calls=used, notice=notice)

        if any(word in text for word in ("owner", "who owns", "team", "responsible")):
            data = record("list_workflows")
            body = "Workflow ownership:\n\n" + "\n".join(
                f"- {w['name']} — {w['owner_name']} ({w['domain_name']})" for w in data["workflows"]
            )
            return ChatResponse(reply=body, mode="offline", tool_calls=used, notice=notice)

        # Default: the portfolio rollup.
        metrics = record("get_portfolio_metrics")
        body = "\n".join(
            [
                f"The portfolio holds **{metrics['total_workflows']} processes** "
                f"({metrics['active_workflows']} active, {metrics['draft_workflows']} draft) "
                f"across {metrics['total_steps']} steps.",
                "",
                f"- On time: {pct(metrics['on_time_rate'])} over {metrics['total_runs']} runs",
                f"- Unattended steps: {pct(metrics['automation_rate'])}",
                f"- Open exceptions: {metrics['open_exceptions']} "
                f"({metrics['high_severity_open_exceptions']} high severity)",
                f"- At-risk processes: {metrics['at_risk_workflows']} "
                "(high or critical, under 80% on time)",
                "",
                "By domain:",
                *[
                    f"- {d['domain_name']}: {d['workflow_count']} processes, "
                    f"{pct(d['on_time_rate'])} on time, {d['open_exceptions']} open exception(s)"
                    for d in metrics["by_domain"]
                ],
            ]
        )
        return ChatResponse(reply=body, mode="offline", tool_calls=used, notice=notice)

    def _match_workflow(self, text: str) -> str | None:
        """Find a workflow the user named, preferring the longest name matched
        so that 'month-end close' is not beaten by a shorter substring."""
        best: tuple[int, str] | None = None
        for summary in self._store.list_workflows():
            name = summary.name.lower()
            candidates = {name, name.replace("-", " "), name.replace(" & ", " and ")}
            for candidate in candidates:
                if candidate in text and (best is None or len(candidate) > best[0]):
                    best = (len(candidate), summary.id)
        return best[1] if best else None
