"""Online-only multi-round engine for Direct, RSEA-style, random, and EvoAudit."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Mapping

from evoaudit_mr.audits.gate import direct_commit, fixed_heldout
from evoaudit_mr.evaluation import mean_delta, paired_results
from evoaudit_mr.evolution.replay import capability_tags, replay_probes
from evoaudit_mr.evolution.scenario import RoundScenario, mechanism_for_scenario
from evoaudit_mr.evolution.state import EvolutionState
from evoaudit_mr.evolution.transforms import apply_patch
from evoaudit_mr.formal.audit import formal_evoaudit_mr, random_formal_probes, route_formal_probes
from evoaudit_mr.formal.catalogue import fixed_validation_tasks
from evoaudit_mr.harness import execute
from evoaudit_mr.types import AuditSuite, CandidateEvent, GateDecision, Harness, Patch, Probe


METHODS = ("direct_commit", "rsea_fixed_validation", "fixed_random_audit", "evoaudit_mr")
SUPPLEMENTARY_ABLATION_METHODS = (
    "evoaudit_mr",
    "no_target_mr",
    "no_replay_mr",
    "no_safety_gate",
    "no_scope_routing",
)


@dataclass(frozen=True)
class RoundRecord:
    method: str
    environment: str
    trajectory_seed: int
    round_index: int
    event: CandidateEvent
    parent_version_id: str
    parent_state_hash: str
    child_state_hash: str
    decision: GateDecision
    committed: bool
    working_version_id: str
    rsea_best_version_id: str | None
    validation_score: float
    parent_harness: Harness
    candidate_harness: Harness
    audit_tool_calls: int
    cumulative_audit_pairs: int
    cumulative_audit_tool_calls: int

    def to_dict(self) -> dict[str, object]:
        return {
            "method": self.method,
            "environment": self.environment,
            "trajectory_seed": self.trajectory_seed,
            "round_index": self.round_index,
            "event_id": self.event.event_id,
            "patch_id": self.event.patch.patch_id,
            "patch": self.event.patch.to_dict(),
            "parent_version_id": self.parent_version_id,
            "parent_state_hash": self.parent_state_hash,
            "child_state_hash": self.child_state_hash,
            "parent_harness": self.parent_harness.to_dict(),
            "candidate_harness": self.candidate_harness.to_dict(),
            "decision": self.decision.decision,
            "decision_reasons": list(self.decision.reasons),
            "working_version_id": self.working_version_id,
            "rsea_best_version_id": self.rsea_best_version_id,
            "validation_score": self.validation_score,
            "logical_pairs": self.decision.bucket_summary.get("logical_pairs", 0),
            "audit_tool_calls": self.audit_tool_calls,
            "cumulative_audit_pairs": self.cumulative_audit_pairs,
            "cumulative_audit_tool_calls": self.cumulative_audit_tool_calls,
        }


def initial_harness(environment: str) -> Harness:
    adapters = {
        "AliasTool": "broken_adapter",
        "SwitchRule": "broken_rule_adapter",
        "PermissionPath": "broken_workflow_adapter",
    }
    return Harness(adapter_name=adapters[environment])


def initial_state(environment: str, *, trajectory_seed: int) -> EvolutionState:
    """Initialize working and frozen-best state from the same validation suite.

    The RSEA-style best checkpoint can advance only on strict validation
    improvement because its initial score is explicitly measured here.
    """
    state = EvolutionState.initial(environment, initial_harness(environment))
    validation = fixed_validation_tasks(environment, count=6, seed=90_000 + trajectory_seed)
    return replace(state, best_validation_score=validation_score(state.working.harness, validation))


def _tasks(environment: str, profile: str, *, count: int, seed: int, prefix: str):
    from evoaudit_mr.formal.catalogue import _tasks as catalogue_tasks  # shared public task factory

    return catalogue_tasks(environment, profile, count=count, seed=seed, prefix=prefix)


def build_round_event(state: EvolutionState, scenario: RoundScenario, *, evolve_tasks: int = 12) -> CandidateEvent:
    """Apply a shared total scenario to the current state to construct one patch."""
    mechanism = mechanism_for_scenario(scenario)
    patch_id = f"mr-{scenario.environment[:2].lower()}-{scenario.trajectory_seed:02d}-{scenario.round_index:02d}"
    visible = _tasks(
        scenario.environment,
        mechanism.visible_profile,
        count=evolve_tasks,
        seed=scenario.external_seed,
        prefix=f"mr-visible-{patch_id}",
    )
    patch = Patch(
        patch_id=patch_id,
        patch_type=mechanism.patch_type,
        claimed_target=mechanism.claimed_target,
        claimed_scope=mechanism.claimed_scope,
        diff={
            "changed_component": mechanism.actual_diff_features["changed_component"],
            "actual_diff_features": dict(mechanism.actual_diff_features),
            "before": state.working.harness.adapter_name,
            "after": mechanism.candidate_adapter,
            "round_external_seed": scenario.external_seed,
        },
        candidate_adapter=mechanism.candidate_adapter,
        evidence_trace_ids=tuple(task.task_id for task in visible),
        rationale="One total, pre-generated multi-round proposal; no retry permitted.",
    )
    validation = fixed_validation_tasks(
        scenario.environment,
        count=6,
        seed=90_000 + scenario.trajectory_seed,
    )
    return CandidateEvent(
        event_id=f"event-{patch_id}",
        parent=state.working.harness,
        patch=patch,
        visible_tasks=visible,
        heldout_tasks=validation,
        environment=scenario.environment,
    )


def validation_score(harness: Harness, tasks: tuple) -> float:
    return sum(execute(harness, task).task_success for task in tasks) / len(tasks)


def _random_gate(event: CandidateEvent, probes: tuple) -> GateDecision:
    results = paired_results(event, probes)
    grouped = {bucket: tuple(result for result in results if result.probe.bucket == bucket) for bucket in ("target", "replay", "safety")}
    target_delta = mean_delta(grouped["target"])
    replay_delta = mean_delta(grouped["replay"])
    safety_events = tuple(name for result in grouped["safety"] for name in result.candidate.safety_events)
    target_improvements = sum(result.success_delta > 0 for result in grouped["target"])
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
            "replay_delta": replay_delta,
            "target_strict_improvement": target_improvements >= 1,
            "safety_events": list(safety_events),
            "logical_pairs": len(probes),
        },
    )


def _evo_suite_with_history(event: CandidateEvent, state: EvolutionState, *, contract: Mapping[str, Any], seed: int):
    suite = route_formal_probes(event, budget_pairs=6, seed=seed, contract=contract)
    history = replay_probes(state, namespace=event.patch.patch_id, seed=seed, count=2)
    probes = tuple(probe for probe in suite.probes if probe.bucket != "replay") + history
    return replace(suite, probes=probes)


def _target_safety_suite(event: CandidateEvent, *, contract: Mapping[str, Any], seed: int) -> AuditSuite:
    """Keep target and safety MRs while removing every replay constraint."""
    suite = route_formal_probes(event, budget_pairs=6, seed=seed, contract=contract)
    retained = tuple(probe for probe in suite.probes if probe.bucket != "replay")
    # Six logical pairs remain budget-matched; duplicated target tasks are
    # explicitly a no-replay control rather than independent evidence.
    duplicated_target = tuple(
        Probe(
            probe_id=f"{probe.probe_id}-no-replay-fill",
            bucket="target",
            mr_id=probe.mr_id,
            task=probe.task,
        )
        for probe in retained
        if probe.bucket == "target"
    )
    return AuditSuite(retained + duplicated_target, 6, "ablation_without_replay")


def _fixed_iid_suite(event: CandidateEvent) -> AuditSuite:
    """A six-task, patch-agnostic control retaining only gate syntax."""
    if len(event.heldout_tasks) < 6:
        raise ValueError("The fixed i.i.d. ablation requires six validation tasks.")
    buckets = ("target", "replay", "safety")
    probes = tuple(
        Probe(
            probe_id=f"{event.event_id}-ablation-fixed-iid-{index}",
            bucket=buckets[index % len(buckets)],
            mr_id="fixed_iid_ablation",
            task=task,
        )
        for index, task in enumerate(event.heldout_tasks[:6])
    )
    return AuditSuite(probes, 6, "ablation_fixed_iid")


def _ablation_decision(
    state: EvolutionState,
    event: CandidateEvent,
    *,
    method: str,
    contract: Mapping[str, Any],
    seed: int,
) -> GateDecision:
    """Component-removal controls used only by the separate appendix runner."""
    routed = _evo_suite_with_history(event, state, contract=contract, seed=seed)
    if method == "no_target_mr":
        iid_target = tuple(probe for probe in _fixed_iid_suite(event).probes if probe.bucket == "target")
        retained = tuple(probe for probe in routed.probes if probe.bucket != "target")
        suite = AuditSuite(iid_target + retained, 6, "ablation_generic_target_iid")
        return formal_evoaudit_mr(event, suite, method=method)
    if method == "no_replay_mr":
        return formal_evoaudit_mr(event, _target_safety_suite(event, contract=contract, seed=seed), method=method)
    if method == "no_safety_gate":
        return formal_evoaudit_mr(event, routed, method=method, check_safety=False)
    if method == "no_scope_routing":
        return formal_evoaudit_mr(event, _fixed_iid_suite(event), method=method)
    raise ValueError(f"Unsupported supplementary ablation method: {method}")


def decide_round(
    state: EvolutionState,
    event: CandidateEvent,
    *,
    method: str,
    contract: Mapping[str, Any],
    seed: int,
) -> GateDecision:
    if method == "direct_commit":
        return direct_commit(event)
    if method == "rsea_fixed_validation":
        decision = fixed_heldout(event, budget_pairs=6)
        return replace(decision, method=method)
    if method == "fixed_random_audit":
        return _random_gate(event, random_formal_probes(event, budget_pairs=6, seed=seed))
    if method == "evoaudit_mr":
        return formal_evoaudit_mr(event, _evo_suite_with_history(event, state, contract=contract, seed=seed))
    if method in set(SUPPLEMENTARY_ABLATION_METHODS) - {"evoaudit_mr"}:
        return _ablation_decision(state, event, method=method, contract=contract, seed=seed)
    raise ValueError(f"Unsupported multi-round method: {method}")


def advance(
    state: EvolutionState,
    scenario: RoundScenario,
    *,
    method: str,
    contract: Mapping[str, Any],
) -> tuple[EvolutionState, RoundRecord]:
    """Execute exactly one online proposal and deterministically update state."""
    event = build_round_event(state, scenario)
    seed = scenario.external_seed + sum(ord(char) for char in method)
    decision = decide_round(state, event, method=method, contract=contract, seed=seed)
    candidate_harness = apply_patch(state.working.harness, event.patch)
    score = validation_score(candidate_harness, event.heldout_tasks)
    pairs = int(decision.bucket_summary.get("logical_pairs", 0))
    tool_calls = (
        sum(len(result.parent.tool_calls) + len(result.candidate.tool_calls) for result in decision.probe_results)
        if pairs
        else 0
    )
    child_hash = state.working.state_hash
    if decision.committed:
        next_state = state.after_commit(
            patch=event.patch,
            child_harness=candidate_harness,
            capability_tags=capability_tags(event.environment, round_index=scenario.round_index),
            validation_score=score,
            pairs=pairs,
            tool_calls=tool_calls,
            keep_best=method == "rsea_fixed_validation",
        )
        child_hash = next_state.working.state_hash
    else:
        next_state = state.after_reject(pairs=pairs, tool_calls=tool_calls)
    record = RoundRecord(
        method=method,
        environment=scenario.environment,
        trajectory_seed=scenario.trajectory_seed,
        round_index=scenario.round_index,
        event=event,
        parent_version_id=state.working.version_id,
        parent_state_hash=state.working.state_hash,
        child_state_hash=child_hash,
        decision=decision,
        committed=decision.committed,
        working_version_id=next_state.working.version_id,
        rsea_best_version_id=next_state.best.version_id if method == "rsea_fixed_validation" and next_state.best else None,
        validation_score=score,
        parent_harness=state.working.harness,
        candidate_harness=candidate_harness,
        audit_tool_calls=tool_calls,
        cumulative_audit_pairs=next_state.cumulative_pairs,
        cumulative_audit_tool_calls=next_state.cumulative_tool_calls,
    )
    return next_state, record
