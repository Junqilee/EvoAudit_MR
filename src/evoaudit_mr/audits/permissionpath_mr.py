"""Pre-registered target, replay, and safety probes for PermissionPath."""

from __future__ import annotations

from typing import Any, Mapping

from evoaudit_mr.envs.permissionpath import make_task
from evoaudit_mr.types import Probe


def online_probes(
    audit_context: Mapping[str, Any],
    *,
    probe_namespace: str,
    seed: int = 0,
) -> tuple[Probe, ...]:
    focus = audit_context.get("workflow_focus")
    if focus == "semantic":
        target = (("valid_archive_path", "archive_valid"), ("delegated_valid_role", "valid_viewer"))
        safety = (("unauthorized_denial", "unauthorized"), ("confirmation_denial", "unconfirmed"))
    elif focus == "role_shortcut":
        target = (("delegated_valid_role", "valid_viewer"), ("delegated_valid_role_variant", "valid_viewer"))
        safety = (("unauthorized_viewer_denial", "unauthorized_viewer"), ("cross_tenant_viewer_denial", "cross_tenant"))
    elif focus == "archive_only":
        target = (("valid_archive_path", "archive_valid"), ("valid_archive_variant", "archive_valid"))
        safety = (("unauthorized_archive_denial", "unauthorized"), ("confirmation_denial", "unconfirmed"))
    elif focus == "fast_bypass":
        target = (("valid_archive_path", "archive_valid"), ("valid_archive_variant", "archive_valid"))
        safety = (("authorization_before_execution", "unauthorized"), ("confirmation_before_execution", "unconfirmed"))
    else:
        raise ValueError(f"Unsupported PermissionPath focus: {focus}")
    templates = {
        "target": target,
        "replay": (("legacy_update_replay", "update_valid"), ("legacy_update_variant", "update_valid")),
        "safety": safety,
    }
    probes: list[Probe] = []
    index = seed * 100
    for bucket, bucket_templates in templates.items():
        for offset, (mr_id, profile) in enumerate(bucket_templates):
            task = make_task(profile, index + offset, task_id_prefix=f"online-{probe_namespace}-{bucket}")
            probes.append(Probe(f"{probe_namespace}-{bucket}-{mr_id}", bucket, mr_id, task))
        index += 10
    return tuple(probes)
