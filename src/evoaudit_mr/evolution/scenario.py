"""Shared, total multi-round scenarios without online failure labels."""

from __future__ import annotations

from dataclasses import dataclass
import random

from evoaudit_mr.formal.catalogue import FormalMechanism, mechanisms_for


@dataclass(frozen=True)
class RoundScenario:
    environment: str
    trajectory_seed: int
    round_index: int
    mechanism_code: str
    external_seed: int


def build_scenarios(environment: str, *, trajectory_seed: int, rounds: int = 10) -> tuple[RoundScenario, ...]:
    """Create one shared, opaque mechanism order for all methods in a trajectory."""
    mechanisms = mechanisms_for(environment)
    if rounds != len(mechanisms):
        raise ValueError("Formal multi-round protocol requires exactly ten rounds/mechanisms.")
    codes = [mechanism.code for mechanism in mechanisms]
    rng = random.Random(trajectory_seed * 10_003 + sum(ord(char) for char in environment))
    rng.shuffle(codes)
    return tuple(
        RoundScenario(
            environment=environment,
            trajectory_seed=trajectory_seed,
            round_index=index,
            mechanism_code=code,
            external_seed=rng.randrange(1, 2**31),
        )
        for index, code in enumerate(codes, start=1)
    )


def mechanism_for_scenario(scenario: RoundScenario) -> FormalMechanism:
    return next(
        mechanism
        for mechanism in mechanisms_for(scenario.environment)
        if mechanism.code == scenario.mechanism_code
    )
