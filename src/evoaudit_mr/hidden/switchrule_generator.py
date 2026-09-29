"""Independent hidden factor universe for SwitchRule candidate labels.

This module intentionally does not import online audit code or patch metadata.
It contains semantic variations beyond the online suite, including a previously
unseen color permutation pattern represented by a different seed range.
"""

from __future__ import annotations

from dataclasses import dataclass

from evoaudit_mr.envs.switchrule import make_task
from evoaudit_mr.types import Probe


@dataclass(frozen=True)
class HiddenUniverse:
    probes: tuple[Probe, ...]
    per_bucket: int
    seed: int

    def bucket(self, name: str) -> tuple[Probe, ...]:
        return tuple(probe for probe in self.probes if probe.bucket == name)


def generate_hidden_universe(*, per_bucket: int, seed: int) -> HiddenUniverse:
    if per_bucket < 1:
        raise ValueError("per_bucket must be positive")
    probes: list[Probe] = []
    base_index = 80_000 + seed * 1_000
    target_profiles = ("base", "color_permuted", "target_new_rule", "color_permuted")
    for index in range(per_bucket):
        profile = target_profiles[index % len(target_profiles)]
        probes.append(
            Probe(
                f"hidden-switch-target-{profile}-{index}",
                "target",
                f"hidden_{profile}",
                make_task(profile, base_index + index, task_id_prefix="hidden-switch-target"),
            )
        )
    for index in range(per_bucket):
        probes.append(
            Probe(
                f"hidden-switch-replay-legacy-{index}",
                "replay",
                "hidden_legacy_replay",
                make_task("legacy_replay", base_index + 100 + index, task_id_prefix="hidden-switch-replay"),
            )
        )
    for index in range(per_bucket):
        profile = "base" if index % 2 == 0 else "color_permuted"
        probes.append(
            Probe(
                f"hidden-switch-safety-{profile}-{index}",
                "safety",
                "hidden_protected_attribute_or_action",
                make_task(profile, base_index + 200 + index, task_id_prefix="hidden-switch-safety"),
            )
        )
    return HiddenUniverse(tuple(probes), per_bucket=per_bucket, seed=seed)

