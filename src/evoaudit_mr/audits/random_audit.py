"""Non-adaptive, budget-matched generic audit suites for control comparisons."""

from __future__ import annotations

import random

from evoaudit_mr.envs.aliastool import make_task as make_aliastool_task
from evoaudit_mr.envs.aliastool import with_lure, with_public_tools_declared
from evoaudit_mr.envs.permissionpath import make_task as make_permissionpath_task
from evoaudit_mr.envs.switchrule import make_task as make_switchrule_task
from evoaudit_mr.types import CandidateEvent, Probe


def random_probes(event: CandidateEvent, *, budget_pairs: int, seed: int) -> tuple[Probe, ...]:
    """Sample a generic three-bucket suite without inspecting patch metadata."""
    if budget_pairs % 3:
        raise ValueError("Random audit budget must divide evenly across three buckets.")
    per_bucket = budget_pairs // 3
    rng = random.Random(seed)
    probes: list[Probe] = []

    if event.environment == "AliasTool":
        profiles = ("canonical", "alias", "reordered", "alias_reordered")
        for bucket_index, bucket in enumerate(("target", "replay", "safety")):
            candidates: list[Probe] = []
            for index in range(8):
                task = make_aliastool_task(
                    profiles[(index + bucket_index) % len(profiles)],
                    700 + bucket_index * 100 + index,
                    task_id_prefix=f"random-{bucket}",
                )
                mr_id = "generic_random_probe"
                if bucket == "safety":
                    task = with_lure(with_public_tools_declared(task), "generic_safety_lure")
                    mr_id = "generic_safety_lure"
                candidates.append(
                    Probe(f"{event.event_id}-random-{bucket}-{index}", bucket, mr_id, task)
                )
            rng.shuffle(candidates)
            probes.extend(candidates[:per_bucket])
        return tuple(probes)

    if event.environment == "SwitchRule":
        profiles = ("base", "color_permuted", "target_new_rule", "legacy_replay")
        for bucket_index, bucket in enumerate(("target", "replay", "safety")):
            candidates = [
                Probe(
                    f"{event.event_id}-random-{bucket}-{index}",
                    bucket,
                    "generic_random_probe",
                    make_switchrule_task(
                        profiles[(index + bucket_index) % len(profiles)],
                        900 + bucket_index * 100 + index,
                        task_id_prefix=f"random-{bucket}",
                    ),
                )
                for index in range(8)
            ]
            rng.shuffle(candidates)
            probes.extend(candidates[:per_bucket])
        return tuple(probes)

    if event.environment == "PermissionPath":
        profiles = ("archive_valid", "update_valid", "valid_viewer", "unauthorized", "unconfirmed", "cross_tenant")
        for bucket_index, bucket in enumerate(("target", "replay", "safety")):
            candidates = [
                Probe(
                    f"{event.event_id}-random-{bucket}-{index}",
                    bucket,
                    "generic_random_probe",
                    make_permissionpath_task(
                        profiles[(index + bucket_index) % len(profiles)],
                        1100 + bucket_index * 100 + index,
                        task_id_prefix=f"random-{bucket}",
                    ),
                )
                for index in range(8)
            ]
            rng.shuffle(candidates)
            probes.extend(candidates[:per_bucket])
        return tuple(probes)

    raise ValueError(f"Unsupported environment: {event.environment}")
