"""Independent hidden universe generated from AliasTool semantic factors.

This module intentionally imports no online-audit module and never reads patch
ids or router outputs. The patch id is used by the runner only after evaluation
to join an offline label to an event.
"""

from __future__ import annotations

from dataclasses import dataclass

from evoaudit_mr.envs.aliastool import make_task, with_lure, with_public_tools_declared
from evoaudit_mr.types import Probe


@dataclass(frozen=True)
class HiddenUniverse:
    probes: tuple[Probe, ...]
    per_bucket: int
    seed: int

    def bucket(self, name: str) -> tuple[Probe, ...]:
        return tuple(probe for probe in self.probes if probe.bucket == name)


_TARGET_FACTORS = (
    ("canonical", "base_schema"),
    ("alias", "tool_argument_field_alias"),
    ("reordered", "field_order"),
    ("alias_reordered", "alias_plus_reorder"),
    ("alt_alias", "unseen_alias_family"),
    ("alt_alias_reordered", "unseen_alias_plus_reorder"),
)


def generate_hidden_universe(*, per_bucket: int, seed: int) -> HiddenUniverse:
    if per_bucket < 1:
        raise ValueError("per_bucket must be positive")
    probes: list[Probe] = []
    base_index = 50_000 + seed * 1_000

    for index in range(per_bucket):
        profile, factor = _TARGET_FACTORS[index % len(_TARGET_FACTORS)]
        task = make_task(profile, base_index + index, task_id_prefix="hidden-target")
        probes.append(Probe(f"hidden-target-{factor}-{index}", "target", factor, task))

    for index in range(per_bucket):
        profile = "canonical" if index % 2 == 0 else "reordered"
        task = make_task(profile, base_index + 100 + index, task_id_prefix="hidden-replay")
        probes.append(Probe(f"hidden-replay-prior-{index}", "replay", "prior_interface", task))

    safety_profiles = ("canonical", "alias", "alt_alias", "reordered")
    for index in range(per_bucket):
        profile = safety_profiles[index % len(safety_profiles)]
        task = make_task(profile, base_index + 200 + index, task_id_prefix="hidden-safety")
        task = with_public_tools_declared(task)
        lure = "undeclared_tool_lure" if index % 2 == 0 else "protected_field_lure"
        task = with_lure(task, lure)
        probes.append(Probe(f"hidden-safety-{lure}-{index}", "safety", lure, task))

    return HiddenUniverse(tuple(probes), per_bucket=per_bucket, seed=seed)
