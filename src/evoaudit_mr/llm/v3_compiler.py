"""Materialize public v3 typed-policy deltas into replayable harness patches."""

from __future__ import annotations

from typing import Any, Mapping

from evoaudit_mr.llm.v3_ir import (
    V3IRValidationError,
    V3ProposedPatch,
    apply_typed_delta,
    audit_context_from_policy_delta,
    initial_typed_policy,
    policy_hash,
)
from evoaudit_mr.types import Harness, Patch


class V3ProposalCompilationError(ValueError):
    """A valid v3 JSON proposal cannot be materialized against its parent."""


def materialize_v3_patch(
    proposal: V3ProposedPatch,
    *,
    environment: str,
    patch_id: str,
    parent: Harness,
) -> Patch:
    """Apply a public delta to one parent without inspecting any hidden signal."""
    try:
        before = dict(parent.typed_policy) if parent.typed_policy else initial_typed_policy(environment)
        after = apply_typed_delta(before, proposal, environment=environment)
    except V3IRValidationError as exc:
        raise V3ProposalCompilationError(str(exc)) from exc
    changed_component = proposal.claimed_scope[0]
    audit_context = audit_context_from_policy_delta(proposal, environment=environment)
    return Patch(
        patch_id=patch_id,
        patch_type=proposal.patch_type,
        claimed_target=proposal.claimed_target,
        claimed_scope=proposal.claimed_scope,
        diff={
            "changed_component": changed_component,
            "typed_policy_before": before,
            "typed_policy_after": after,
            "actual_diff_features": {
                "changed_component": changed_component,
                "compiler_version": "typed-policy-ir-v3",
                "typed_delta": [assignment.to_dict() for assignment in proposal.policy_delta],
                "typed_delta_signature": proposal.fingerprint[:16],
                **audit_context,
            },
            "before": policy_hash(before),
            "after": policy_hash(after),
        },
        candidate_adapter=f"typed_{environment.lower()}_policy",
        evidence_trace_ids=proposal.evidence_trace_ids,
        rationale=proposal.rationale,
    )
