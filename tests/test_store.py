"""Tests for the store's filtering and derived metrics."""

from __future__ import annotations

import pytest

from app.config import get_settings
from app.store import JsonWorkflowStore


@pytest.fixture(scope="module")
def store() -> JsonWorkflowStore:
    return JsonWorkflowStore(get_settings().data_path)


def test_dataset_loads_with_referential_integrity(store: JsonWorkflowStore) -> None:
    domain_ids = {d.id for d in store.list_domains()}
    owner_ids = {o.id for o in store.list_owners()}
    system_ids = {s.id for s in store.list_systems()}
    object_ids = {o.id for o in store.list_data_objects()}

    assert store.list_workflows(), "seed dataset should not be empty"

    for summary in store.list_workflows():
        detail = store.get_workflow(summary.id)
        assert detail is not None
        workflow = detail.workflow
        assert workflow.domain_id in domain_ids
        assert workflow.owner_id in owner_ids
        for step in workflow.steps:
            assert step.owner_id in owner_ids
            assert set(step.system_ids) <= system_ids
            assert set(step.input_object_ids) <= object_ids
            assert set(step.output_object_ids) <= object_ids


def test_workflow_rollups_match_their_steps(store: JsonWorkflowStore) -> None:
    """The header's system and object lists are derived, so they must agree with
    what the steps actually declare."""
    for summary in store.list_workflows():
        detail = store.get_workflow(summary.id)
        workflow = detail.workflow

        from_steps = {s for step in workflow.steps for s in step.system_ids}
        assert from_steps <= set(workflow.system_ids)

        objects_from_steps = {
            o for step in workflow.steps for o in step.input_object_ids + step.output_object_ids
        }
        assert objects_from_steps == set(workflow.data_object_ids)

        assert workflow.step_count == len(workflow.steps)


def test_filters_narrow_and_combine(store: JsonWorkflowStore) -> None:
    everything = store.list_workflows()
    r2r = store.list_workflows(domain_id="r2r")

    assert 0 < len(r2r) < len(everything)
    assert all(w.domain_id == "r2r" for w in r2r)

    critical_r2r = store.list_workflows(domain_id="r2r", criticality="critical")
    assert all(w.criticality.value == "critical" for w in critical_r2r)
    assert len(critical_r2r) <= len(r2r)


def test_unknown_filter_value_returns_empty(store: JsonWorkflowStore) -> None:
    assert store.list_workflows(domain_id="does-not-exist") == []


def test_search_reaches_beyond_the_workflow_name(store: JsonWorkflowStore) -> None:
    # "BlackLine" is a system, named on steps but not in any workflow name.
    hits = store.list_workflows(search="blackline")
    assert hits
    assert all("blackline" not in w.name.lower() for w in hits)

    # A step role, not a workflow field.
    assert store.list_workflows(search="controls tester")


def test_list_is_ordered_by_criticality_then_reliability(store: JsonWorkflowStore) -> None:
    rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    ordered = [rank[w.criticality.value] for w in store.list_workflows()]
    assert ordered == sorted(ordered)


def test_on_time_rate_excludes_in_flight_runs(store: JsonWorkflowStore) -> None:
    """A run still in progress has not had the chance to breach its SLA, so it
    must not count either way."""
    for summary in store.list_workflows():
        metrics = summary.metrics
        finished = metrics.completed_runs + metrics.failed_runs
        if finished == 0:
            assert metrics.on_time_rate is None
            continue

        runs = store.list_runs(workflow_id=summary.id, limit=500)
        on_time = sum(1 for r in runs if r.sla_met)
        assert metrics.on_time_rate == pytest.approx(on_time / finished, abs=1e-4)
        assert metrics.total_runs == finished + metrics.in_progress_runs


def test_automation_rate_counts_unattended_steps(store: JsonWorkflowStore) -> None:
    detail = store.get_workflow("wf-month-end-close")
    unattended = sum(1 for s in detail.workflow.steps if s.type.value in ("automated", "system"))
    expected = unattended / len(detail.workflow.steps)
    assert detail.metrics.automation_rate == pytest.approx(expected, abs=1e-4)


def test_draft_workflow_has_no_history(store: JsonWorkflowStore) -> None:
    detail = store.get_workflow("wf-lease-accounting")
    assert detail.workflow.status.value == "draft"
    assert detail.metrics.total_runs == 0
    assert detail.metrics.on_time_rate is None
    assert detail.metrics.last_run_at is None


def test_open_exceptions_are_unresolved_and_annotated(store: JsonWorkflowStore) -> None:
    exceptions = store.list_open_exceptions(limit=200)
    assert exceptions

    known_workflows = {w.id for w in store.list_workflows()}
    for exception in exceptions:
        assert exception["workflow_id"] in known_workflows
        assert exception["workflow_name"]
        assert exception["step_name"], "every exception should resolve to a real step"

    severities = [e["severity"] for e in exceptions]
    rank = {"high": 0, "medium": 1, "low": 2}
    assert [rank[s] for s in severities] == sorted(rank[s] for s in severities)

    # Nothing resolved should leak into the open list.
    all_runs = store.list_runs(limit=1000)
    open_ids = {e["id"] for e in exceptions}
    for run in all_runs:
        for exception in run.exceptions:
            if exception.resolved:
                assert exception.id not in open_ids


def test_exception_severity_filter(store: JsonWorkflowStore) -> None:
    high = store.list_open_exceptions(severity="high", limit=200)
    assert all(e["severity"] == "high" for e in high)
    assert len(high) <= len(store.list_open_exceptions(limit=200))


def test_portfolio_metrics_agree_with_per_workflow_metrics(store: JsonWorkflowStore) -> None:
    portfolio = store.portfolio_metrics()
    summaries = store.list_workflows()

    assert portfolio.total_workflows == len(summaries)
    assert portfolio.total_steps == sum(s.step_count for s in summaries)
    assert portfolio.open_exceptions == sum(s.metrics.open_exceptions for s in summaries)
    assert portfolio.open_exceptions == len(store.list_open_exceptions(limit=10_000))
    assert portfolio.total_runs == len(store.list_runs(limit=10_000))

    expected_at_risk = sum(
        1
        for s in summaries
        if s.criticality.value in ("high", "critical")
        and s.metrics.on_time_rate is not None
        and s.metrics.on_time_rate < 0.8
    )
    assert portfolio.at_risk_workflows == expected_at_risk
    assert sum(portfolio.by_status.values()) == len(summaries)


def test_runs_are_returned_newest_first_and_respect_limit(store: JsonWorkflowStore) -> None:
    runs = store.list_runs(limit=25)
    assert len(runs) == 25
    assert [r.started_at for r in runs] == sorted((r.started_at for r in runs), reverse=True)


def test_run_period_filter_is_a_prefix_match(store: JsonWorkflowStore) -> None:
    runs = store.list_runs(period="2026", limit=500)
    assert runs
    assert all(r.period.startswith("2026") for r in runs)


def test_get_workflow_returns_none_for_unknown_id(store: JsonWorkflowStore) -> None:
    assert store.get_workflow("wf-not-real") is None
