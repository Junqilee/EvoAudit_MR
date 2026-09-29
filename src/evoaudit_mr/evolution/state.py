"""Immutable agent versions and evolution state."""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from evoaudit_mr.types import Harness, Patch, stable_hash


@dataclass(frozen=True)
class AgentVersion:
    version_id: str
    environment: str
    harness: Harness
    parent_version_id: str | None = None
    applied_patch_ids: tuple[str, ...] = ()
    created_round: int = 0

    @property
    def state_hash(self) -> str:
        return stable_hash(
            {
                "environment": self.environment,
                "parent_version_id": self.parent_version_id,
                "harness": self.harness.to_dict(),
                "applied_patch_ids": list(self.applied_patch_ids),
                "created_round": self.created_round,
            }
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "version_id": self.version_id,
            "parent_version_id": self.parent_version_id,
            "environment": self.environment,
            "harness": self.harness.to_dict(),
            "applied_patch_ids": list(self.applied_patch_ids),
            "created_round": self.created_round,
            "state_hash": self.state_hash,
        }


@dataclass(frozen=True)
class CapabilityAnchor:
    task_id: str
    environment: str
    capability_tag: str
    source_round: int
    source_version_id: str


@dataclass(frozen=True)
class EvolutionState:
    """State owned by one method on one trajectory; every update returns a copy."""

    working: AgentVersion
    history: tuple[CapabilityAnchor, ...] = ()
    rounds_completed: int = 0
    cumulative_pairs: int = 0
    cumulative_tool_calls: int = 0
    best: AgentVersion | None = None
    best_validation_score: float = float("-inf")

    @classmethod
    def initial(cls, environment: str, harness: Harness) -> "EvolutionState":
        version = AgentVersion(
            version_id=f"{environment.lower()}-v0",
            environment=environment,
            harness=harness,
        )
        return cls(working=version, best=version)

    def after_reject(self, *, pairs: int, tool_calls: int) -> "EvolutionState":
        return replace(
            self,
            rounds_completed=self.rounds_completed + 1,
            cumulative_pairs=self.cumulative_pairs + pairs,
            cumulative_tool_calls=self.cumulative_tool_calls + tool_calls,
        )

    def after_commit(
        self,
        *,
        patch: Patch,
        child_harness: Harness,
        capability_tags: tuple[str, ...],
        validation_score: float,
        pairs: int,
        tool_calls: int,
        keep_best: bool,
    ) -> "EvolutionState":
        round_number = self.rounds_completed + 1
        child = AgentVersion(
            version_id=f"{self.working.version_id}.{round_number}-{patch.patch_id}",
            parent_version_id=self.working.version_id,
            environment=self.working.environment,
            harness=child_harness,
            applied_patch_ids=(*self.working.applied_patch_ids, patch.patch_id),
            created_round=round_number,
        )
        anchors = tuple(
            CapabilityAnchor(
                task_id=f"{child.version_id}:{tag}",
                environment=child.environment,
                capability_tag=tag,
                source_round=round_number,
                source_version_id=child.version_id,
            )
            for tag in capability_tags
        )
        new_best = child if keep_best and validation_score > self.best_validation_score else self.best
        new_score = validation_score if keep_best and validation_score > self.best_validation_score else self.best_validation_score
        return EvolutionState(
            working=child,
            history=(*self.history, *anchors),
            rounds_completed=round_number,
            cumulative_pairs=self.cumulative_pairs + pairs,
            cumulative_tool_calls=self.cumulative_tool_calls + tool_calls,
            best=new_best,
            best_validation_score=new_score,
        )
