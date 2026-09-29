"""Independent hidden factor universe for PermissionPath candidate labels."""

from __future__ import annotations

from dataclasses import dataclass

from evoaudit_mr.envs.permissionpath import make_task
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
    base_index = 120_000 + seed * 1_000
    target_profiles = ("archive_valid", "valid_viewer", "update_valid", "archive_valid")
    for index in range(per_bucket):
        profile = target_profiles[index % len(target_profiles)]
        probes.append(
            Probe(
                f"hidden-permission-target-{profile}-{index}",
                "target",
                f"hidden_{profile}",
                make_task(profile, base_index + index, task_id_prefix="hidden-permission-target"),
            )
        )
    for index in range(per_bucket):
        probes.append(
            Probe(
                f"hidden-permission-replay-update-{index}",
                "replay",
                "hidden_update_replay",
                make_task("update_valid", base_index + 100 + index, task_id_prefix="hidden-permission-replay"),
            )
        )
    safety_profiles = ("unauthorized", "unconfirmed", "cross_tenant", "unauthorized_viewer")
    for index in range(per_bucket):
        profile = safety_profiles[index % len(safety_profiles)]
        probes.append(
            Probe(
                f"hidden-permission-safety-{profile}-{index}",
                "safety",
                f"hidden_{profile}",
                make_task(profile, base_index + 200 + index, task_id_prefix="hidden-permission-safety"),
            )
        )
    return HiddenUniverse(tuple(probes), per_bucket=per_bucket, seed=seed)
