"""Deterministic routing from a typed patch to the compatible MR library."""

from __future__ import annotations

from typing import Mapping, Any

from evoaudit_mr.audits.mr_library import online_probes
from evoaudit_mr.audits.permissionpath_mr import online_probes as permissionpath_online_probes
from evoaudit_mr.audits.switchrule_mr import online_probes as switchrule_online_probes
from evoaudit_mr.types import AuditSuite, Patch


class UnsupportedScopeError(ValueError):
    """Raised when the environment contract cannot audit a proposed patch."""


def route_probes(
    patch: Patch,
    *,
    environment: str,
    budget_pairs: int,
    seed: int,
    contract: Mapping[str, Any] | None = None,
) -> AuditSuite:
    if contract is not None:
        if contract.get("environment") != environment:
            raise UnsupportedScopeError("Environment contract does not match the requested audit environment.")
        required_invariants = (
            {"tool_must_be_declared", "protected_field_must_not_be_read"}
            if environment == "AliasTool"
            else (
                {"protected_attribute_must_not_be_read", "prohibited_action_must_not_be_selected"}
                if environment == "SwitchRule"
                else {
                    "authorization_before_execution",
                    "confirmation_before_irreversible_execution",
                    "tenant_isolation",
                    "execution_must_be_logged",
                }
            )
        )
        if not required_invariants.issubset(set(contract.get("safety_invariants", []))):
            raise UnsupportedScopeError("Environment contract lacks required safety invariants.")
    if budget_pairs != 6:
        raise ValueError("The Stage-4 pilot router supports exactly six probe pairs (2 per bucket).")
    audit_context = patch.diff.get("audit_context")
    if not isinstance(audit_context, Mapping):
        raise UnsupportedScopeError("Patch diff must include a structured audit_context.")
    if environment == "AliasTool":
        if patch.patch_type != "tool_adapter" or "tool_adapter" not in patch.claimed_scope:
            raise UnsupportedScopeError("AliasTool requires a tool_adapter patch and matching declared scope.")
        probes = online_probes(audit_context, probe_namespace=patch.patch_id, seed=seed)
    elif environment == "SwitchRule":
        if patch.patch_type not in {"prompt_strategy", "memory_skill"}:
            raise UnsupportedScopeError("SwitchRule requires a prompt_strategy or memory_skill patch.")
        if not {"prompt_strategy", "memory_skill"}.intersection(patch.claimed_scope):
            raise UnsupportedScopeError("SwitchRule patch scope must declare prompt_strategy or memory_skill.")
        probes = switchrule_online_probes(audit_context, probe_namespace=patch.patch_id, seed=seed)
    elif environment == "PermissionPath":
        if patch.patch_type not in {"workflow", "tool_adapter"}:
            raise UnsupportedScopeError("PermissionPath requires a workflow or tool_adapter patch.")
        if not {"workflow", "tool_adapter"}.intersection(patch.claimed_scope):
            raise UnsupportedScopeError("PermissionPath scope must declare workflow or tool_adapter.")
        probes = permissionpath_online_probes(audit_context, probe_namespace=patch.patch_id, seed=seed)
    else:
        raise UnsupportedScopeError(f"Unsupported environment: {environment}")
    return AuditSuite(probes=probes, budget_pairs=budget_pairs, source="patch_conditional_router")
