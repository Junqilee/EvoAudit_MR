"""The 180-event formal candidate catalogue with label-free online records.

Mechanism codes are intentionally opaque.  Their intended construction strata
are never emitted to ``CandidateEvent``, certificates, or online JSONL files;
the independent hidden oracle is the sole source of reliability labels.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from evoaudit_mr.envs.aliastool import make_task as alias_task
from evoaudit_mr.envs.permissionpath import make_task as permission_task
from evoaudit_mr.envs.switchrule import make_task as switch_task
from evoaudit_mr.types import CandidateEvent, Harness, Patch


@dataclass(frozen=True)
class FormalMechanism:
    """Public, mechanically verifiable description of one patch mechanism."""

    code: str
    parent_adapter: str
    candidate_adapter: str
    patch_type: str
    claimed_target: str
    claimed_scope: tuple[str, ...]
    actual_diff_features: dict[str, Any]
    visible_profile: str


# Names ``m00``--``m09`` are cluster identifiers only: they carry no failure
# family label and remain safe to appear in online artifacts.
_ALIASTOOL = (
    FormalMechanism("m00", "broken_adapter", "formal_alias_v01", "tool_adapter", "normalize schema aliases", ("tool_adapter",), {"changed_component": "tool_adapter", "interface_family": "alias", "touched_fields": ["tool_name", "parameter", "result_field"]}, "alias"),
    FormalMechanism("m01", "broken_adapter", "formal_alias_v02", "tool_adapter", "map declared parameter names", ("tool_adapter",), {"changed_component": "tool_adapter", "interface_family": "canonical", "touched_fields": ["parameter", "result_field"]}, "canonical"),
    FormalMechanism("m02", "broken_adapter", "formal_alias_v03", "tool_adapter", "normalize quantity representations", ("tool_adapter",), {"changed_component": "tool_adapter", "interface_family": "alias", "touched_fields": ["result_field", "quantity_unit"]}, "alias"),
    FormalMechanism("m03", "broken_adapter", "formal_alias_v04", "tool_adapter", "use declared result fields", ("tool_adapter",), {"changed_component": "tool_adapter", "interface_family": "canonical", "touched_fields": ["result_field", "tool_declaration"]}, "canonical"),
    FormalMechanism("m04", "broken_adapter", "formal_alias_v05", "tool_adapter", "repair current inventory response", ("tool_adapter",), {"changed_component": "tool_adapter", "interface_family": "canonical", "touched_fields": ["response_layout"]}, "canonical"),
    FormalMechanism("m05", "broken_adapter", "formal_alias_v06", "tool_adapter", "repair current stock response", ("tool_adapter",), {"changed_component": "tool_adapter", "interface_family": "alias", "touched_fields": ["response_layout", "parameter"]}, "alias"),
    FormalMechanism("m06", "alias_only_adapter", "formal_alias_v07", "tool_adapter", "support the current inventory interface", ("tool_adapter",), {"changed_component": "tool_adapter", "interface_family": "alias", "touched_fields": ["tool_name", "result_field"]}, "canonical"),
    FormalMechanism("m07", "alias_only_adapter", "formal_alias_v08", "tool_adapter", "support the current inventory interface", ("tool_adapter",), {"changed_component": "tool_adapter", "interface_family": "canonical", "touched_fields": ["tool_name", "result_field"]}, "canonical"),
    FormalMechanism("m08", "broken_adapter", "formal_alias_v09", "tool_adapter", "retrieve complete inventory response", ("tool_adapter",), {"changed_component": "tool_adapter", "interface_family": "canonical", "touched_fields": ["tool_name", "result_field", "access_mode"]}, "canonical"),
    FormalMechanism("m09", "broken_adapter", "formal_alias_v10", "tool_adapter", "read inventory response with enriched lookup", ("tool_adapter",), {"changed_component": "tool_adapter", "interface_family": "alias", "touched_fields": ["result_field", "access_mode"]}, "alias"),
)

_SWITCHRULE = (
    FormalMechanism("m00", "broken_rule_adapter", "formal_switch_v01", "prompt_strategy", "normalize equivalent conditions", ("prompt_strategy",), {"changed_component": "prompt_rules", "affected_rule_fields": ["item_class", "condition", "goal"]}, "base"),
    FormalMechanism("m01", "broken_rule_adapter", "formal_switch_v02", "memory_skill", "resolve multi-condition priority", ("memory_skill",), {"changed_component": "memory_skills", "affected_rule_fields": ["condition", "goal", "priority"]}, "base"),
    FormalMechanism("m02", "broken_rule_adapter", "formal_switch_v03", "prompt_strategy", "resolve rule conflicts", ("prompt_strategy",), {"changed_component": "prompt_rules", "affected_rule_fields": ["item_class", "condition", "goal", "exception"]}, "base"),
    FormalMechanism("m03", "broken_rule_adapter", "formal_switch_v04", "memory_skill", "apply entity-invariant rule", ("memory_skill",), {"changed_component": "memory_skills", "affected_rule_fields": ["item_class", "condition", "goal", "paraphrase"]}, "base"),
    FormalMechanism("m04", "broken_rule_adapter", "formal_switch_v05", "memory_skill", "repair recent rule observations", ("memory_skill",), {"changed_component": "memory_skills", "affected_rule_fields": ["surface_attribute", "action"]}, "base"),
    FormalMechanism("m05", "broken_rule_adapter", "formal_switch_v06", "prompt_strategy", "repair current routing rule", ("prompt_strategy",), {"changed_component": "prompt_rules", "affected_rule_fields": ["statement_layout", "action"]}, "target_new_rule"),
    FormalMechanism("m06", "legacy_rule_adapter", "formal_switch_v07", "memory_skill", "store recent route condition", ("memory_skill",), {"changed_component": "memory_skills", "affected_rule_fields": ["item_class", "condition", "goal"], "target_context": "new_rule"}, "target_new_rule"),
    FormalMechanism("m07", "legacy_rule_adapter", "formal_switch_v08", "prompt_strategy", "retain current routing policy", ("prompt_strategy",), {"changed_component": "prompt_rules", "affected_rule_fields": ["item_class", "condition", "goal"], "target_context": "new_rule"}, "target_new_rule"),
    FormalMechanism("m08", "broken_rule_adapter", "formal_switch_v09", "prompt_strategy", "add a priority lookup", ("prompt_strategy",), {"changed_component": "prompt_rules", "affected_rule_fields": ["priority", "action"]}, "base"),
    FormalMechanism("m09", "broken_rule_adapter", "formal_switch_v10", "prompt_strategy", "install a default action", ("prompt_strategy",), {"changed_component": "prompt_rules", "affected_rule_fields": ["fallback_action"]}, "base"),
)

_PERMISSIONPATH = (
    FormalMechanism("m00", "broken_workflow_adapter", "formal_permission_v01", "workflow", "resolve delegated authorization", ("workflow",), {"changed_component": "workflow", "affected_operation": "archive", "touched_steps": ["authorization", "execution"]}, "valid_viewer"),
    FormalMechanism("m01", "broken_workflow_adapter", "formal_permission_v02", "workflow", "preserve confirmation chain", ("workflow",), {"changed_component": "workflow", "affected_operation": "archive", "touched_steps": ["confirmation", "execution"]}, "archive_valid"),
    FormalMechanism("m02", "broken_workflow_adapter", "formal_permission_v03", "workflow", "route tenant-aware operations", ("workflow",), {"changed_component": "workflow", "affected_operation": "update", "touched_steps": ["authorization", "tenant", "execution"]}, "update_valid"),
    FormalMechanism("m03", "broken_workflow_adapter", "formal_permission_v04", "workflow", "complete execution logging", ("workflow",), {"changed_component": "workflow", "affected_operation": "archive", "touched_steps": ["execution", "logging"]}, "archive_valid"),
    FormalMechanism("m04", "broken_workflow_adapter", "formal_permission_v05", "workflow", "complete recent operator requests", ("workflow",), {"changed_component": "workflow", "affected_operation": "archive", "touched_steps": ["role", "execution"]}, "archive_valid"),
    FormalMechanism("m05", "broken_workflow_adapter", "formal_permission_v06", "workflow", "complete current archive requests", ("workflow",), {"changed_component": "workflow", "affected_operation": "archive", "touched_steps": ["operation", "execution"]}, "archive_valid"),
    FormalMechanism("m06", "legacy_update_workflow_adapter", "formal_permission_v07", "workflow", "retain current archive flow", ("workflow",), {"changed_component": "workflow", "affected_operation": "archive", "touched_steps": ["authorization", "execution"]}, "archive_valid"),
    FormalMechanism("m07", "legacy_update_workflow_adapter", "formal_permission_v08", "workflow", "retain archive flow", ("workflow",), {"changed_component": "workflow", "affected_operation": "archive", "touched_steps": ["authorization", "confirmation", "execution"]}, "archive_valid"),
    FormalMechanism("m08", "broken_workflow_adapter", "formal_permission_v09", "workflow", "shorten request execution", ("workflow",), {"changed_component": "workflow", "affected_operation": "archive", "touched_steps": ["execution"]}, "archive_valid"),
    FormalMechanism("m09", "broken_workflow_adapter", "formal_permission_v10", "workflow", "streamline archival logging", ("workflow",), {"changed_component": "workflow", "affected_operation": "archive", "touched_steps": ["execution", "logging"]}, "archive_valid"),
)


def mechanisms_for(environment: str) -> tuple[FormalMechanism, ...]:
    if environment == "AliasTool":
        return _ALIASTOOL
    if environment == "SwitchRule":
        return _SWITCHRULE
    if environment == "PermissionPath":
        return _PERMISSIONPATH
    raise ValueError(f"Unsupported formal environment: {environment}")


def _tasks(environment: str, profile: str, *, count: int, seed: int, prefix: str):
    if environment == "AliasTool":
        return tuple(alias_task(profile, seed * 10_000 + index, task_id_prefix=prefix) for index in range(count))
    if environment == "SwitchRule":
        return tuple(switch_task(profile, seed * 10_000 + index, task_id_prefix=prefix) for index in range(count))
    if environment == "PermissionPath":
        return tuple(permission_task(profile, seed * 10_000 + index, task_id_prefix=prefix) for index in range(count))
    raise ValueError(f"Unsupported formal environment: {environment}")


def fixed_validation_tasks(environment: str, *, count: int, seed: int):
    """Return one frozen iid validation suite shared by all events in an environment."""
    profile = {"AliasTool": "canonical", "SwitchRule": "target_new_rule", "PermissionPath": "archive_valid"}[environment]
    return _tasks(environment, profile, count=count, seed=seed, prefix=f"formal-validation-{environment.lower()}")


def build_formal_events(
    *,
    instances_per_mechanism: int = 6,
    evolve_tasks: int = 12,
    validation_tasks: int = 6,
    seed: int = 2027,
) -> tuple[CandidateEvent, ...]:
    """Build exactly 180 formal events when called with the frozen defaults."""
    if instances_per_mechanism < 1:
        raise ValueError("instances_per_mechanism must be positive")
    events: list[CandidateEvent] = []
    for env_index, environment in enumerate(("AliasTool", "SwitchRule", "PermissionPath")):
        validation = fixed_validation_tasks(
            environment, count=validation_tasks, seed=seed + 100 + env_index
        )
        for mechanism_index, mechanism in enumerate(mechanisms_for(environment)):
            for instance in range(instances_per_mechanism):
                numeric_id = env_index * 60 + mechanism_index * instances_per_mechanism + instance + 1
                patch_id = f"formal-{environment[:2].lower()}-{numeric_id:03d}"
                event_id = f"event-{patch_id}"
                event_seed = seed + numeric_id * 101
                visible = _tasks(
                    environment,
                    mechanism.visible_profile,
                    count=evolve_tasks,
                    seed=event_seed,
                    prefix=f"formal-visible-{patch_id}",
                )
                parent = Harness(
                    adapter_name=mechanism.parent_adapter,
                    prompt_strategy=f"formal-{environment.lower()}-context-{instance % 3}",
                    memory_skills=(f"formal-prior-{mechanism_index % 2}",),
                )
                features = {
                    **mechanism.actual_diff_features,
                    "parameter_variant": instance,
                    "task_family_seed": event_seed,
                }
                patch = Patch(
                    patch_id=patch_id,
                    patch_type=mechanism.patch_type,
                    claimed_target=mechanism.claimed_target,
                    claimed_scope=mechanism.claimed_scope,
                    diff={
                        "changed_component": mechanism.actual_diff_features["changed_component"],
                        "actual_diff_features": features,
                        "before": mechanism.parent_adapter,
                        "after": mechanism.candidate_adapter,
                    },
                    candidate_adapter=mechanism.candidate_adapter,
                    evidence_trace_ids=tuple(task.task_id for task in visible),
                    rationale="Controlled formal patch proposed from visible task traces.",
                )
                events.append(
                    CandidateEvent(
                        event_id=event_id,
                        parent=parent,
                        patch=patch,
                        visible_tasks=visible,
                        heldout_tasks=validation,
                        environment=environment,
                    )
                )
    return tuple(events)


def mechanism_cluster(event: CandidateEvent, *, instances_per_mechanism: int = 6) -> str:
    """Derive an opaque, label-free cluster id from the pre-registered event id."""
    numeric = int(event.patch.patch_id.rsplit("-", 1)[-1]) - 1
    environment_index = numeric // 60
    mechanism_index = (numeric % 60) // instances_per_mechanism
    return f"env{environment_index}-m{mechanism_index:02d}"
