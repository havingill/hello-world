"""REST API for the dashboard.

Everything the front end needs, and nothing it does not. Read-only for now:
process authoring lands in a later phase, at which point this module gains the
write endpoints and the store interface gains the matching methods.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from ..chat import ChatEngine
from ..config import Settings, get_settings
from ..dependencies import get_chat_engine, get_store
from ..models import (
    ChatRequest,
    ChatResponse,
    DataObject,
    Domain,
    Owner,
    PortfolioMetrics,
    Run,
    System,
    WorkflowDetail,
    WorkflowSummary,
)
from ..store import WorkflowStore

router = APIRouter(prefix="/api")


@router.get("/health")
def health(
    settings: Settings = Depends(get_settings),
    store: WorkflowStore = Depends(get_store),
) -> dict:
    """Liveness plus the two facts the front end needs at boot: how fresh the
    data is, and whether the chatbot has a model behind it."""
    return {
        "status": "ok",
        "app": settings.app_name,
        "as_of": getattr(store, "as_of", None),
        "chat": {
            "mode": "azure_ai_foundry" if settings.azure_configured else "offline",
            "deployment": settings.azure_ai_deployment if settings.azure_configured else None,
        },
    }


@router.get("/metrics", response_model=PortfolioMetrics)
def portfolio_metrics(store: WorkflowStore = Depends(get_store)) -> PortfolioMetrics:
    return store.portfolio_metrics()


@router.get("/workflows", response_model=list[WorkflowSummary])
def list_workflows(
    domain_id: str | None = None,
    status: str | None = None,
    owner_id: str | None = None,
    criticality: str | None = None,
    frequency: str | None = None,
    tag: str | None = None,
    search: str | None = None,
    store: WorkflowStore = Depends(get_store),
) -> list[WorkflowSummary]:
    return store.list_workflows(
        domain_id=domain_id,
        status=status,
        owner_id=owner_id,
        criticality=criticality,
        frequency=frequency,
        tag=tag,
        search=search,
    )


@router.get("/workflows/{workflow_id}", response_model=WorkflowDetail)
def get_workflow(
    workflow_id: str, store: WorkflowStore = Depends(get_store)
) -> WorkflowDetail:
    detail = store.get_workflow(workflow_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"No workflow with id {workflow_id!r}")
    return detail


@router.get("/runs", response_model=list[Run])
def list_runs(
    workflow_id: str | None = None,
    status: str | None = None,
    period: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    store: WorkflowStore = Depends(get_store),
) -> list[Run]:
    return store.list_runs(
        workflow_id=workflow_id, status=status, period=period, limit=limit
    )


@router.get("/exceptions")
def list_open_exceptions(
    workflow_id: str | None = None,
    severity: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    store: WorkflowStore = Depends(get_store),
) -> list[dict]:
    return store.list_open_exceptions(
        workflow_id=workflow_id, severity=severity, limit=limit
    )


@router.get("/reference")
def reference_data(store: WorkflowStore = Depends(get_store)) -> dict:
    """Domains, owners, systems and data objects in one call, so the front end
    can populate every filter without a request waterfall."""
    return {
        "domains": store.list_domains(),
        "owners": store.list_owners(),
        "systems": store.list_systems(),
        "data_objects": store.list_data_objects(),
    }


@router.get("/domains", response_model=list[Domain])
def list_domains(store: WorkflowStore = Depends(get_store)) -> list[Domain]:
    return store.list_domains()


@router.get("/owners", response_model=list[Owner])
def list_owners(store: WorkflowStore = Depends(get_store)) -> list[Owner]:
    return store.list_owners()


@router.get("/systems", response_model=list[System])
def list_systems(store: WorkflowStore = Depends(get_store)) -> list[System]:
    return store.list_systems()


@router.get("/data-objects", response_model=list[DataObject])
def list_data_objects(store: WorkflowStore = Depends(get_store)) -> list[DataObject]:
    """The business objects the processes touch — the raw material for the
    ontology work that comes later."""
    return store.list_data_objects()


@router.post("/chat", response_model=ChatResponse)
def chat(
    request: ChatRequest, engine: ChatEngine = Depends(get_chat_engine)
) -> ChatResponse:
    message = request.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="message must not be empty")
    return engine.answer(message, request.history)
