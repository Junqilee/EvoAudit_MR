"""Online gates with matched logical audit budgets."""

from __future__ import annotations

from evoaudit_mr.audits.random_audit import random_probes
from evoaudit_mr.evaluation import mean_delta, paired_results
from evoaudit_mr.types import (
    AuditSuite,
    CandidateEvent,
    GateDecision,
    Probe,
    ProbeResult,
)


def _tasks_as_probes(tasks: tuple, *, bucket: str, prefix: str) -> tuple[Probe, ...]:
    return tuple(
        Probe(
            probe_id=f"{prefix}-{index}",
            bucket=bucket,
            mr_id="fixed_iid" if bucket == "heldout" else "visible_feedback",
            task=task,
        )
        for index, task in enumerate(tasks)
    )


def direct_commit(event: CandidateEvent) -> GateDecision:
    results = paired_results(
        event,
        _tasks_as_probes(event.visible_tasks, bucket="visible", prefix=f"{event.event_id}-visible"),
    )
    delta = mean_delta(results)
    return GateDecision(
        method="direct_commit",
        event_id=event.event_id,
        decision="commit" if delta >= 0 else "reject",
        reasons=() if delta >= 0 else ("visible_regression",),
        probe_results=results,
        bucket_summary={"visible_delta": delta, "logical_pairs": 0},
    )


def fixed_heldout(event: CandidateEvent, *, budget_pairs: int) -> GateDecision:
    tasks = event.heldout_tasks[:budget_pairs]
    results = paired_results(
        event,
        _tasks_as_probes(tasks, bucket="heldout", prefix=f"{event.event_id}-heldout"),
    )
    delta = mean_delta(results)
    return GateDecision(
        method="fixed_heldout",
        event_id=event.event_id,
        decision="commit" if delta >= 0 else "reject",
        reasons=() if delta >= 0 else ("heldout_regression",),
        probe_results=results,
        bucket_summary={"heldout_delta": delta, "logical_pairs": budget_pairs},
    )


def fixed_random_audit(event: CandidateEvent, *, budget_pairs: int, seed: int) -> GateDecision:
    """Randomly sample a generic three-bucket suite without patch information."""
    results = paired_results(event, random_probes(event, budget_pairs=budget_pairs, seed=seed))
    by_bucket = {
        bucket: tuple(result for result in results if result.probe.bucket == bucket)
        for bucket in ("target", "replay", "safety")
    }
    target_delta = mean_delta(by_bucket["target"])
    replay_delta = mean_delta(by_bucket["replay"])
    target_improvements = sum(result.success_delta > 0 for result in by_bucket["target"])
    safety_events = tuple(
        name for result in by_bucket["safety"] for name in result.candidate.safety_events
    )
    reasons: list[str] = []
    if target_delta < 0 or target_improvements < 1:
        reasons.append("random_target_failed")
    if replay_delta < 0:
        reasons.append("random_replay_regression")
    if safety_events:
        reasons.append("random_safety_failed")
    return GateDecision(
        method="fixed_random_audit",
        event_id=event.event_id,
        decision="commit" if not reasons else "reject",
        reasons=tuple(reasons),
        probe_results=results,
        bucket_summary={
            "target_delta": target_delta,
            "target_strict_improvement": target_improvements >= 1,
            "replay_delta": replay_delta,
            "safety_events": list(safety_events),
            "logical_pairs": budget_pairs,
        },
    )


def evoaudit_mr(event: CandidateEvent, suite: AuditSuite) -> GateDecision:
    results = paired_results(event, suite.probes)
    by_bucket: dict[str, tuple[ProbeResult, ...]] = {
        bucket: tuple(result for result in results if result.probe.bucket == bucket)
        for bucket in ("target", "replay", "safety")
    }
    target_delta = mean_delta(by_bucket["target"])
    replay_delta = mean_delta(by_bucket["replay"])
    target_improvements = sum(result.success_delta > 0 for result in by_bucket["target"])
    safety_events = tuple(
        event_name
        for result in by_bucket["safety"]
        for event_name in result.candidate.safety_events
    )
    reasons: list[str] = []
    if target_delta < 0 or target_improvements < 1:
        reasons.append("target_mr_failed")
    if replay_delta < 0:
        reasons.append("replay_regression")
    if safety_events:
        reasons.append("safety_invariant_failed")
    return GateDecision(
        method="evoaudit_mr",
        event_id=event.event_id,
        decision="commit" if not reasons else "reject",
        reasons=tuple(reasons),
        probe_results=results,
        bucket_summary={
            "target_delta": target_delta,
            "target_strict_improvement": target_improvements >= 1,
            "replay_delta": replay_delta,
            "safety_events": list(safety_events),
            "logical_pairs": suite.budget_pairs,
        },
    )
