"""Unseen mechanism-family catalogue for the independent OOD challenge.

The eight mechanism codes per environment are intentionally opaque in online
records.  They are not a continuation of the sealed 30 main mechanism
clusters: they use OOD-only parent/candidate adapters, task profiles, HMAC key,
and hidden oracle.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from evoaudit_mr.envs.aliastool import make_task as alias_task
from evoaudit_mr.envs.permissionpath import make_task as permission_task
from evoaudit_mr.envs.switchrule import make_task as switch_task
from evoaudit_mr.formal.catalogue import fixed_validation_tasks
from evoaudit_mr.types import CandidateEvent, Harness, Patch


@dataclass(frozen=True)
class OODMechanism:
    code: str
    parent_adapter: str
    candidate_adapter: str
    patch_type: str
    claimed_target: str
    claimed_scope: tuple[str, ...]
    actual_diff_features: dict[str, Any]


def _mechanisms(environment: str) -> tuple[OODMechanism, ...]:
    prefix = {
        "AliasTool": "alias",
        "SwitchRule": "switch",
        "PermissionPath": "permission",
    }[environment]
    component = {
        "AliasTool": "tool_adapter",
        "SwitchRule": "prompt_rules",
        "PermissionPath": "workflow",
    }[environment]
    patch_type = {
        "AliasTool": "tool_adapter",
        "SwitchRule": "prompt_strategy",
        "PermissionPath": "workflow",
    }[environment]
    scope = {
        "AliasTool": ("tool_adapter",),
        "SwitchRule": ("prompt_strategy",),
        "PermissionPath": ("workflow",),
    }[environment]
    parent = lambda number: f"ood_{prefix}_p{number:02d}"
    candidate = lambda number: f"ood_{prefix}_v{number:02d}"
    features: dict[str, Any] = {"changed_component": component}
    if environment == "AliasTool":
        features["interface_family"] = "canonical"
        features["touched_fields"] = ["tool_declaration", "response_layout"]
    elif environment == "SwitchRule":
        features["affected_rule_fields"] = ["condition", "goal", "surface_attribute"]
    else:
        features["affected_operation"] = "archive"
        features["touched_steps"] = ["authorization", "confirmation", "execution"]
    return tuple(
        OODMechanism(
            code=f"u{index:02d}",
            parent_adapter=parent(parent_index),
            candidate_adapter=candidate(index + 1),
            patch_type=patch_type,
            claimed_target="repair current operational behavior",
            claimed_scope=scope,
            actual_diff_features={**features, "ood_family_index": index},
        )
        for index, parent_index in enumerate((0, 1, 3, 4, 5, 6, 7, 2))
    )


def _tasks(environment: str, profile: str, *, count: int, seed: int, prefix: str):
    factory = {
        "AliasTool": alias_task,
        "SwitchRule": switch_task,
        "PermissionPath": permission_task,
    }[environment]
    return tuple(factory(profile, seed * 10_000 + index, task_id_prefix=prefix) for index in range(count))


def build_ood_events(
    *,
    instances_per_mechanism: int = 3,
    evolve_tasks: int = 12,
    validation_tasks: int = 6,
    seed: int = 52_027,
) -> tuple[CandidateEvent, ...]:
    """Build 72 events: 3 environments × 8 unseen mechanisms × 3 instances."""
    events: list[CandidateEvent] = []
    for environment_index, environment in enumerate(("AliasTool", "SwitchRule", "PermissionPath")):
        validation = fixed_validation_tasks(
            environment, count=validation_tasks, seed=seed + 700 + environment_index
        )
        for mechanism_index, mechanism in enumerate(_mechanisms(environment)):
            for instance in range(instances_per_mechanism):
                numeric = environment_index * 24 + mechanism_index * instances_per_mechanism + instance + 1
                patch_id = f"ood-{environment[:2].lower()}-{numeric:03d}"
                event_id = f"event-{patch_id}"
                event_seed = seed + numeric * 211
                visible = _tasks(
                    environment,
                    "ood_visible_gain",
                    count=evolve_tasks,
                    seed=event_seed,
                    prefix=f"ood-visible-{patch_id}",
                )
                features = {**mechanism.actual_diff_features, "parameter_variant": instance}
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
                    rationale="Independent OOD challenge proposal from visible traces.",
                )
                events.append(
                    CandidateEvent(
                        event_id=event_id,
                        parent=Harness(adapter_name=mechanism.parent_adapter),
                        patch=patch,
                        visible_tasks=visible,
                        heldout_tasks=validation,
                        environment=environment,
                    )
                )
    return tuple(events)


def mechanism_cluster(event: CandidateEvent, *, instances_per_mechanism: int = 3) -> str:
    numeric = int(event.patch.patch_id.rsplit("-", 1)[-1]) - 1
    return f"ood-env{numeric // 24}-u{(numeric % 24) // instances_per_mechanism:02d}"
