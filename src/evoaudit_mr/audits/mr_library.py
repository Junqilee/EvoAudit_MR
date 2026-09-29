"""Pre-registered online AliasTool probes. Hidden truth is generated elsewhere."""

from __future__ import annotations

from typing import Any, Mapping

from evoaudit_mr.envs.aliastool import make_task, with_lure
from evoaudit_mr.types import Probe


_ONLINE_TEMPLATES: dict[str, tuple[tuple[str, str], ...]] = {
    "replay": (
        ("canonical_schema", "canonical"),
        ("canonical_new_record", "canonical"),
    ),
    "safety": (
        ("undeclared_tool_lure", "canonical"),
        ("protected_field_lure", "reordered"),
    ),
}


def online_probes(
    audit_context: Mapping[str, Any],
    *,
    probe_namespace: str,
    seed: int = 0,
) -> tuple[Probe, ...]:
    """Return six fixed, patch-conditional AliasTool probes.

    Probe semantics depend only on structured patch context, never patch id.
    ``probe_namespace`` affects identifiers only.
    """
    templates = dict(_ONLINE_TEMPLATES)
    # Safety probes preserve the current public interface of a patch unless the
    # patch itself chooses an undeclared shortcut. This prevents replay and
    # target failures from being artificially counted as authorization failures.
    active_schema = audit_context.get("active_schema", "canonical")
    if active_schema == "alias":
        templates["target"] = (
            ("tool_alias", "alias"),
            ("field_rename_and_reorder", "alias_reordered"),
        )
        templates["safety"] = (
            ("undeclared_tool_lure", "alias"),
            ("protected_field_lure", "alias_reordered"),
        )
    elif active_schema == "canonical":
        templates["target"] = (
            ("canonical_field_reorder", "reordered"),
            ("canonical_irrelevant_field_reorder", "reordered"),
        )
        templates["safety"] = (
            ("undeclared_tool_lure", "canonical"),
            ("protected_field_lure", "canonical"),
        )
    else:
        raise ValueError(f"Unsupported active schema: {active_schema}")
    probes: list[Probe] = []
    index = seed * 100
    for bucket, bucket_templates in templates.items():
        for offset, (mr_id, profile) in enumerate(bucket_templates):
            task = make_task(profile, index + offset, task_id_prefix=f"online-{probe_namespace}-{bucket}")
            if mr_id.endswith("lure"):
                task = with_lure(task, mr_id)
            probes.append(
                Probe(
                    probe_id=f"{probe_namespace}-{bucket}-{mr_id}",
                    bucket=bucket,
                    mr_id=mr_id,
                    task=task,
                )
            )
        index += 10
    return tuple(probes)
