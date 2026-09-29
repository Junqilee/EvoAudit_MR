"""Total, deterministic patch transforms over composite harness components."""

from __future__ import annotations

from dataclasses import replace

from evoaudit_mr.types import Harness, Patch


def _append_once(values: tuple[str, ...], item: str) -> tuple[str, ...]:
    return values if item in values else (*values, item)


def apply_patch(parent: Harness, patch: Patch) -> Harness:
    """Apply every formal patch to any reachable state without retrying.

    A duplicate component insertion is intentionally a deterministic no-op at
    the component level, but the candidate executable adapter is still updated
    so the round has a real, auditable proposal and no hidden re-sampling.
    """
    component = patch.diff.get("changed_component")
    typed_policy = patch.diff.get("typed_policy_after")
    if typed_policy is not None and not isinstance(typed_policy, dict):
        raise ValueError("typed_policy_after must be a mapping when present.")
    if component == "tool_adapter":
        return replace(
            parent,
            adapter_name=patch.candidate_adapter,
            tool_adapters=_append_once(parent.tool_adapters, patch.candidate_adapter),
            typed_policy=dict(typed_policy) if typed_policy is not None else parent.typed_policy,
        )
    if component == "prompt_rules":
        return replace(
            parent,
            adapter_name=patch.candidate_adapter,
            prompt_rules=_append_once(parent.prompt_rules, patch.candidate_adapter),
            typed_policy=dict(typed_policy) if typed_policy is not None else parent.typed_policy,
        )
    if component == "memory_skills":
        return replace(
            parent,
            adapter_name=patch.candidate_adapter,
            memory_skills=_append_once(parent.memory_skills, patch.candidate_adapter),
            typed_policy=dict(typed_policy) if typed_policy is not None else parent.typed_policy,
        )
    if component == "workflow":
        return replace(
            parent,
            adapter_name=patch.candidate_adapter,
            workflow_steps=_append_once(parent.workflow_steps, patch.candidate_adapter),
            typed_policy=dict(typed_policy) if typed_policy is not None else parent.typed_policy,
        )
    raise ValueError(f"Unsupported or unverifiable changed_component: {component!r}")
