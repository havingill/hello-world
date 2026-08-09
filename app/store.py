"""Data access for the workflow dashboard.

`WorkflowStore` is the seam between the API and wherever the data actually
lives. Today the only implementation reads the seeded JSON file into memory;
swapping in Cosmos DB or Azure SQL later means writing a second implementation
of this interface and changing the one line in `dependencies.py` that constructs
it. Nothing above this module knows the data came from a file.

All derived numbers (metrics, rollups) are computed here so the API layer and
the chatbot's tools see exactly the same figures.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from collections import Counter
from pathlib import Path

from .models import (
    DataObject,
    Domain,
    Owner,
    PortfolioMetrics,
    Run,
    RunStatus,
    System,
    Workflow,
    WorkflowDetail,
    WorkflowMetrics,
    WorkflowStatus,
    WorkflowSummary,
)

# Automated and system steps run without a person in the loop; approval, review
# and manual steps do not. Automation rate is the share of steps in the former.
UNATTENDED_STEP_TYPES = {"automated", "system"}


class WorkflowStore(ABC):
    """Read interface over the workflow portfolio."""

    @abstractmethod
    def list_domains(self) -> list[Domain]: ...

    @abstractmethod
    def list_owners(self) -> list[Owner]: ...

    @abstractmethod
    def list_systems(self) -> list[System]: ...

    @abstractmethod
    def list_data_objects(self) -> list[DataObject]: ...

    @abstractmethod
    def list_workflows(
        self,
        *,
        domain_id: str | None = None,
        status: str | None = None,
        owner_id: str | None = None,
        criticality: str | None = None,
        frequency: str | None = None,
        tag: str | None = None,
        search: str | None = None,
    ) -> list[WorkflowSummary]: ...

    @abstractmethod
    def get_workflow(self, workflow_id: str) -> WorkflowDetail | None: ...

    @abstractmethod
    def list_runs(
        self,
        *,
        workflow_id: str | None = None,
        status: str | None = None,
        period: str | None = None,
        limit: int = 50,
    ) -> list[Run]: ...

    @abstractmethod
    def list_open_exceptions(
        self, *, workflow_id: str | None = None, severity: str | None = None, limit: int = 50
    ) -> list[dict]: ...

    @abstractmethod
    def portfolio_metrics(self) -> PortfolioMetrics: ...


class JsonWorkflowStore(WorkflowStore):
    """In-memory store backed by the seeded JSON dataset.

    The file is read once at construction. Derived metrics are computed once and
    cached, since the dataset is immutable for the life of the process.
    """

    def __init__(self, data_path: Path) -> None:
        self._path = data_path
        raw = json.loads(data_path.read_text(encoding="utf-8"))

        self._domains = [Domain(**d) for d in raw["domains"]]
        self._owners = [Owner(**o) for o in raw["owners"]]
        self._systems = [System(**s) for s in raw["systems"]]
        self._data_objects = [DataObject(**o) for o in raw["data_objects"]]
        self._workflows = [Workflow(**w) for w in raw["workflows"]]
        self._runs = [Run(**r) for r in raw["runs"]]
        self.as_of: str = raw.get("as_of", "")

        self._domains_by_id = {d.id: d for d in self._domains}
        self._owners_by_id = {o.id: o for o in self._owners}
        self._systems_by_id = {s.id: s for s in self._systems}
        self._objects_by_id = {o.id: o for o in self._data_objects}
        self._workflows_by_id = {w.id: w for w in self._workflows}

        self._runs_by_workflow: dict[str, list[Run]] = {}
        for run in self._runs:
            self._runs_by_workflow.setdefault(run.workflow_id, []).append(run)
        # Runs arrive newest-first from the seed; make that guarantee explicit
        # so "recent runs" and "last run" do not depend on file ordering.
        for runs in self._runs_by_workflow.values():
            runs.sort(key=lambda r: r.started_at, reverse=True)

        self._metrics_by_workflow = {
            workflow.id: self._compute_metrics(workflow) for workflow in self._workflows
        }

    # -- reference data ---------------------------------------------------

    def list_domains(self) -> list[Domain]:
        return list(self._domains)

    def list_owners(self) -> list[Owner]:
        return list(self._owners)

    def list_systems(self) -> list[System]:
        return list(self._systems)

    def list_data_objects(self) -> list[DataObject]:
        return list(self._data_objects)

    # -- metrics ----------------------------------------------------------

    def _compute_metrics(self, workflow: Workflow) -> WorkflowMetrics:
        runs = self._runs_by_workflow.get(workflow.id, [])
        completed = [r for r in runs if r.status == RunStatus.COMPLETED]
        failed = [r for r in runs if r.status == RunStatus.FAILED]
        in_progress = [r for r in runs if r.status == RunStatus.IN_PROGRESS]

        # On-time rate is measured over finished runs only: a run still in
        # flight has not yet had the chance to breach its SLA, and counting it
        # either way would understate or overstate performance.
        finished = completed + failed
        on_time = [r for r in finished if r.sla_met]
        on_time_rate = round(len(on_time) / len(finished), 4) if finished else None

        durations = [r.duration_hours for r in completed if r.duration_hours is not None]
        avg_duration = round(sum(durations) / len(durations), 2) if durations else None

        unattended = sum(1 for s in workflow.steps if s.type.value in UNATTENDED_STEP_TYPES)
        automation_rate = round(unattended / len(workflow.steps), 4) if workflow.steps else 0.0

        open_exceptions = sum(
            1 for run in runs for exc in run.exceptions if not exc.resolved
        )

        last_run = runs[0] if runs else None

        return WorkflowMetrics(
            workflow_id=workflow.id,
            total_runs=len(runs),
            completed_runs=len(completed),
            failed_runs=len(failed),
            in_progress_runs=len(in_progress),
            on_time_rate=on_time_rate,
            avg_duration_hours=avg_duration,
            automation_rate=automation_rate,
            open_exceptions=open_exceptions,
            last_run_at=last_run.started_at if last_run else None,
            last_run_status=last_run.status if last_run else None,
        )

    def metrics_for(self, workflow_id: str) -> WorkflowMetrics | None:
        return self._metrics_by_workflow.get(workflow_id)

    # -- workflows --------------------------------------------------------

    def _summary(self, workflow: Workflow) -> WorkflowSummary:
        domain = self._domains_by_id.get(workflow.domain_id)
        owner = self._owners_by_id.get(workflow.owner_id)
        return WorkflowSummary(
            id=workflow.id,
            name=workflow.name,
            domain_id=workflow.domain_id,
            domain_name=domain.name if domain else workflow.domain_id,
            description=workflow.description,
            owner_id=workflow.owner_id,
            owner_name=owner.name if owner else workflow.owner_id,
            status=workflow.status,
            maturity=workflow.maturity,
            criticality=workflow.criticality,
            frequency=workflow.frequency,
            sla_hours=workflow.sla_hours,
            tags=workflow.tags,
            step_count=workflow.step_count,
            planned_hours=workflow.planned_hours,
            metrics=self._metrics_by_workflow[workflow.id],
        )

    def list_workflows(
        self,
        *,
        domain_id: str | None = None,
        status: str | None = None,
        owner_id: str | None = None,
        criticality: str | None = None,
        frequency: str | None = None,
        tag: str | None = None,
        search: str | None = None,
    ) -> list[WorkflowSummary]:
        results = []
        needle = search.lower().strip() if search else None

        for workflow in self._workflows:
            if domain_id and workflow.domain_id != domain_id:
                continue
            if status and workflow.status.value != status:
                continue
            if owner_id and workflow.owner_id != owner_id:
                continue
            if criticality and workflow.criticality.value != criticality:
                continue
            if frequency and workflow.frequency.value != frequency:
                continue
            if tag and tag not in workflow.tags:
                continue
            if needle and not self._matches(workflow, needle):
                continue
            results.append(self._summary(workflow))

        # Most critical first, then the least reliable, so the list reads as a
        # worklist rather than an alphabetical inventory.
        criticality_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        results.sort(
            key=lambda s: (
                criticality_rank.get(s.criticality.value, 9),
                s.metrics.on_time_rate if s.metrics.on_time_rate is not None else 1.0,
                s.name,
            )
        )
        return results

    def _matches(self, workflow: Workflow, needle: str) -> bool:
        """Free-text match across the fields a user would plausibly search on,
        including step names and the systems the process touches."""
        haystack = [
            workflow.name,
            workflow.description,
            workflow.risk_notes,
            *workflow.tags,
            *(s.name for s in workflow.steps),
            *(s.role for s in workflow.steps),
        ]
        owner = self._owners_by_id.get(workflow.owner_id)
        if owner:
            haystack.extend([owner.name, owner.role, owner.team])
        domain = self._domains_by_id.get(workflow.domain_id)
        if domain:
            haystack.append(domain.name)
        haystack.extend(
            self._systems_by_id[s].name for s in workflow.system_ids if s in self._systems_by_id
        )
        haystack.extend(
            self._objects_by_id[o].name
            for o in workflow.data_object_ids
            if o in self._objects_by_id
        )
        return any(needle in value.lower() for value in haystack if value)

    def get_workflow(self, workflow_id: str) -> WorkflowDetail | None:
        workflow = self._workflows_by_id.get(workflow_id)
        if workflow is None:
            return None

        domain = self._domains_by_id.get(workflow.domain_id)
        owner = self._owners_by_id.get(workflow.owner_id)
        if domain is None or owner is None:
            # The seed guarantees referential integrity; a break here means the
            # dataset was edited by hand, and failing loudly beats a half-page.
            raise ValueError(
                f"Workflow {workflow_id} references unknown domain/owner "
                f"({workflow.domain_id!r}/{workflow.owner_id!r})"
            )

        return WorkflowDetail(
            workflow=workflow,
            domain=domain,
            owner=owner,
            systems=[
                self._systems_by_id[s] for s in workflow.system_ids if s in self._systems_by_id
            ],
            data_objects=[
                self._objects_by_id[o]
                for o in workflow.data_object_ids
                if o in self._objects_by_id
            ],
            metrics=self._metrics_by_workflow[workflow.id],
            recent_runs=self._runs_by_workflow.get(workflow.id, [])[:12],
        )

    # -- runs and exceptions ----------------------------------------------

    def list_runs(
        self,
        *,
        workflow_id: str | None = None,
        status: str | None = None,
        period: str | None = None,
        limit: int = 50,
    ) -> list[Run]:
        runs = (
            self._runs_by_workflow.get(workflow_id, []) if workflow_id else self._runs
        )
        results = [
            run
            for run in runs
            if (not status or run.status.value == status)
            and (not period or run.period.startswith(period))
        ]
        results.sort(key=lambda r: r.started_at, reverse=True)
        return results[:limit]

    def list_open_exceptions(
        self, *, workflow_id: str | None = None, severity: str | None = None, limit: int = 50
    ) -> list[dict]:
        """Flattened open exceptions, annotated with the workflow and step they
        belong to so a caller (or the chatbot) never has to join back."""
        severity_rank = {"high": 0, "medium": 1, "low": 2}
        results: list[dict] = []

        for run in self._runs:
            if workflow_id and run.workflow_id != workflow_id:
                continue
            workflow = self._workflows_by_id.get(run.workflow_id)
            if workflow is None:
                continue
            steps_by_id = {s.id: s for s in workflow.steps}

            for exc in run.exceptions:
                if exc.resolved:
                    continue
                if severity and exc.severity.value != severity:
                    continue
                step = steps_by_id.get(exc.step_id)
                results.append(
                    {
                        "id": exc.id,
                        "severity": exc.severity.value,
                        "description": exc.description,
                        "workflow_id": workflow.id,
                        "workflow_name": workflow.name,
                        "step_id": exc.step_id,
                        "step_name": step.name if step else None,
                        "run_id": run.id,
                        "period": run.period,
                        "started_at": run.started_at,
                    }
                )

        results.sort(
            key=lambda e: (severity_rank.get(e["severity"], 9), e["started_at"]),
            reverse=False,
        )
        # Within a severity band, show the most recent first.
        results.sort(key=lambda e: severity_rank.get(e["severity"], 9))
        return results[:limit]

    # -- portfolio rollup -------------------------------------------------

    def portfolio_metrics(self) -> PortfolioMetrics:
        metrics = list(self._metrics_by_workflow.values())

        finished_on_time = 0
        finished_total = 0
        for run in self._runs:
            if run.status == RunStatus.IN_PROGRESS:
                continue
            finished_total += 1
            if run.sla_met:
                finished_on_time += 1

        total_steps = sum(w.step_count for w in self._workflows)
        unattended_steps = sum(
            1 for w in self._workflows for s in w.steps if s.type.value in UNATTENDED_STEP_TYPES
        )

        open_exceptions = sum(m.open_exceptions for m in metrics)
        high_open = sum(
            1
            for run in self._runs
            for exc in run.exceptions
            if not exc.resolved and exc.severity.value == "high"
        )

        # "At risk" is the list the controller actually cares about: an
        # important process that is missing its SLA more than a fifth of the time.
        at_risk = sum(
            1
            for w in self._workflows
            if w.criticality.value in ("high", "critical")
            and (m := self._metrics_by_workflow[w.id]).on_time_rate is not None
            and m.on_time_rate < 0.8
        )

        by_domain = []
        for domain in self._domains:
            members = [w for w in self._workflows if w.domain_id == domain.id]
            if not members:
                continue
            rates = [
                self._metrics_by_workflow[w.id].on_time_rate
                for w in members
                if self._metrics_by_workflow[w.id].on_time_rate is not None
            ]
            by_domain.append(
                {
                    "domain_id": domain.id,
                    "domain_name": domain.name,
                    "workflow_count": len(members),
                    "step_count": sum(w.step_count for w in members),
                    "on_time_rate": round(sum(rates) / len(rates), 4) if rates else None,
                    "open_exceptions": sum(
                        self._metrics_by_workflow[w.id].open_exceptions for w in members
                    ),
                }
            )

        return PortfolioMetrics(
            total_workflows=len(self._workflows),
            active_workflows=sum(
                1 for w in self._workflows if w.status == WorkflowStatus.ACTIVE
            ),
            draft_workflows=sum(
                1 for w in self._workflows if w.status == WorkflowStatus.DRAFT
            ),
            total_steps=total_steps,
            total_runs=len(self._runs),
            on_time_rate=round(finished_on_time / finished_total, 4) if finished_total else None,
            automation_rate=round(unattended_steps / total_steps, 4) if total_steps else 0.0,
            open_exceptions=open_exceptions,
            high_severity_open_exceptions=high_open,
            at_risk_workflows=at_risk,
            by_domain=by_domain,
            by_status=dict(Counter(w.status.value for w in self._workflows)),
            by_criticality=dict(Counter(w.criticality.value for w in self._workflows)),
        )
