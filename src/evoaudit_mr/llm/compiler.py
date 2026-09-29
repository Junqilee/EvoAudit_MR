"""Compile a validated LLM patch DSL into an executable compact harness patch."""

from __future__ import annotations

from evoaudit_mr.llm.proposal import ProposedPatch, executable_intent
from evoaudit_mr.types import Patch


class ProposalCompilationError(ValueError):
    """A valid proposal cannot be executed by the compact public DSL."""


_ADAPTERS = {
    "AliasTool": {
        "semantic": "llm_semantic_adapter",
        "visible_shortcut": "llm_positional_adapter",
    },
    "SwitchRule": {
        "semantic": "llm_semantic_rule_adapter",
        "visible_shortcut": "llm_color_shortcut_adapter",
    },
    "PermissionPath": {
        "semantic": "llm_semantic_workflow_adapter",
        "visible_shortcut": "llm_fast_bypass_workflow_adapter",
    },
}


def compile_proposed_patch(
    proposal: ProposedPatch,
    *,
    environment: str,
    patch_id: str,
    parent_adapter: str,
) -> Patch:
    """Create an auditable candidate without exposing a pre-labelled choice."""
    try:
        intent = executable_intent(proposal)
        candidate_adapter = _ADAPTERS[environment][intent]
    except (KeyError, ValueError) as exc:
        raise ProposalCompilationError(str(exc)) from exc
    changed_component = proposal.claimed_scope[0]
    return Patch(
        patch_id=patch_id,
        patch_type=proposal.patch_type,
        claimed_target=proposal.claimed_target,
        claimed_scope=proposal.claimed_scope,
        diff={
            "changed_component": changed_component,
            "actual_diff_features": {
                "changed_component": changed_component,
                "llm_patch_dsl": proposal.to_dict(),
                "compiled_intent": intent,
                "compiler_version": "llm-patch-compiler-v1",
            },
            "before": parent_adapter,
            "after": candidate_adapter,
        },
        candidate_adapter=candidate_adapter,
        evidence_trace_ids=proposal.evidence_trace_ids,
        rationale=proposal.rationale,
    )
