"""Pre-registered online probes for the SwitchRule environment."""

from __future__ import annotations

from typing import Any, Mapping

from evoaudit_mr.envs.switchrule import make_task
from evoaudit_mr.types import Probe


def online_probes(
    audit_context: Mapping[str, Any],
    *,
    probe_namespace: str,
    seed: int = 0,
) -> tuple[Probe, ...]:
    """Build a six-probe suite from structured rule-patch features.

    The patch identifier only namespaces records; ``rule_focus`` determines the
    semantic content. This mirrors the AliasTool router and supports the same
    two target, two replay, and two safety paired rollouts.
    """
    focus = audit_context.get("rule_focus")
    if focus == "semantic":
        target_templates = (("semantic_rule_target", "target_new_rule"), ("color_invariance", "color_permuted"))
    elif focus == "color_shortcut":
        target_templates = (("break_color_correlation", "color_permuted"), ("entity_paraphrase", "color_permuted"))
    elif focus == "new_rule":
        target_templates = (("new_rule_target", "target_new_rule"), ("new_rule_paraphrase", "target_new_rule"))
    else:
        raise ValueError(f"Unsupported SwitchRule focus: {focus}")

    templates = {
        "target": target_templates,
        "replay": (("legacy_rule_replay", "legacy_replay"), ("legacy_rule_replay_variant", "legacy_replay")),
        "safety": (("protected_attribute_lure", "base"), ("prohibited_action_lure", "base")),
    }
    probes: list[Probe] = []
    index = seed * 100
    for bucket, bucket_templates in templates.items():
        for offset, (mr_id, profile) in enumerate(bucket_templates):
            task = make_task(profile, index + offset, task_id_prefix=f"online-{probe_namespace}-{bucket}")
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

