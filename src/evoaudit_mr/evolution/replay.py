"""Online-only history replay selection; it never accesses hidden labels."""

from __future__ import annotations

from evoaudit_mr.envs.aliastool import make_task as alias_task
from evoaudit_mr.envs.permissionpath import make_task as permission_task
from evoaudit_mr.envs.switchrule import make_task as switch_task
from evoaudit_mr.evolution.state import EvolutionState
from evoaudit_mr.types import Probe


def capability_tags(environment: str, *, round_index: int) -> tuple[str, ...]:
    return (f"{environment.lower()}-round-{round_index}-core", f"{environment.lower()}-round-{round_index}-adjacent")


def replay_probes(state: EvolutionState, *, namespace: str, seed: int, count: int = 2) -> tuple[Probe, ...]:
    """Select stable online history probes, falling back to public neighbors."""
    tags = [anchor.capability_tag for anchor in state.history]
    selected = tags[-count:] if len(tags) >= count else [f"neighbor-{index}" for index in range(count)]
    probes: list[Probe] = []
    for index, tag in enumerate(selected):
        task_index = seed * 10_000 + index
        if state.working.environment == "AliasTool":
            task = alias_task("canonical", task_index, task_id_prefix=f"history-{namespace}")
        elif state.working.environment == "SwitchRule":
            task = switch_task("legacy_replay", task_index, task_id_prefix=f"history-{namespace}")
        elif state.working.environment == "PermissionPath":
            task = permission_task("update_valid", task_index, task_id_prefix=f"history-{namespace}")
        else:
            raise ValueError(f"Unsupported evolution environment: {state.working.environment}")
        probes.append(Probe(f"{namespace}-replay-history-{index}", "replay", f"history:{tag}", task))
    return tuple(probes)
