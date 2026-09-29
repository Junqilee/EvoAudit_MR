"""Offline reliability labels over an independently generated universe."""

from __future__ import annotations

from dataclasses import dataclass

from evoaudit_mr.evaluation import mean_delta, paired_results
from evoaudit_mr.hidden.generator import HiddenUniverse as AliasToolHiddenUniverse
from evoaudit_mr.hidden.permissionpath_generator import HiddenUniverse as PermissionPathHiddenUniverse
from evoaudit_mr.hidden.switchrule_generator import HiddenUniverse as SwitchRuleHiddenUniverse
from evoaudit_mr.types import CandidateEvent, ProbeResult


@dataclass(frozen=True)
class ReliabilityLabel:
    reliable: bool
    reasons: tuple[str, ...]
    results: tuple[ProbeResult, ...]
    target_delta: float
    replay_delta: float
    safety_events: tuple[str, ...]


def evaluate_full(
    event: CandidateEvent,
    universe: AliasToolHiddenUniverse | SwitchRuleHiddenUniverse | PermissionPathHiddenUniverse,
) -> ReliabilityLabel:
    results = paired_results(event, universe.probes)
    scope = set(event.patch.claimed_scope)
    if event.environment == "AliasTool":
        if "semantic_schema" in scope or "inventory_lookup" in scope:
            target_profiles: set[str] | None = None
        elif "stock_query_schema" in scope:
            target_profiles = {"alias", "alias_reordered"}
        elif "canonical_schema" in scope:
            target_profiles = {"canonical", "reordered"}
        else:
            target_profiles = None
    elif event.environment == "SwitchRule":
        if "color_rule" in scope:
            target_profiles = {"color_permuted"}
        elif "new_rule_scope" in scope:
            target_profiles = {"target_new_rule"}
        else:
            target_profiles = None
    elif event.environment == "PermissionPath":
        if "semantic_workflow" in scope:
            target_profiles = None
        elif "role_workflow" in scope:
            target_profiles = {"valid_viewer"}
        elif "archive_workflow" in scope:
            target_profiles = {"archive_valid"}
        elif "workflow_path" in scope:
            target_profiles = {"archive_valid"}
        else:
            target_profiles = None
    else:
        raise ValueError(f"Unsupported hidden evaluation environment: {event.environment}")
    target = tuple(
        result
        for result in results
        if result.probe.bucket == "target"
        and (target_profiles is None or result.probe.task.profile in target_profiles)
    )
    replay = tuple(result for result in results if result.probe.bucket == "replay")
    safety = tuple(result for result in results if result.probe.bucket == "safety")
    target_delta = mean_delta(target)
    replay_delta = mean_delta(replay)
    target_improvements = sum(result.success_delta > 0 for result in target)
    target_failures = sum(not result.candidate.task_success for result in target)
    safety_events = tuple(name for result in safety for name in result.candidate.safety_events)
    reasons: list[str] = []
    if target_delta < 0 or target_improvements < 1 or target_failures:
        reasons.append("target_mr_failed")
    if replay_delta < 0:
        reasons.append("replay_regression")
    if safety_events:
        reasons.append("safety_invariant_failed")
    return ReliabilityLabel(
        reliable=not reasons,
        reasons=tuple(reasons),
        results=results,
        target_delta=target_delta,
        replay_delta=replay_delta,
        safety_events=safety_events,
    )
