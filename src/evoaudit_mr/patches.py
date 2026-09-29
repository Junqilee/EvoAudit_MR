"""Controlled proposal source with the same typed interface as future Trace2Patch."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from evoaudit_mr.envs.aliastool import sample_base_tasks
from evoaudit_mr.types import CandidateEvent, Harness, Patch


def _adapter_diff(parent: str, candidate: str) -> dict[str, Any]:
    return {
        "field": "tool_adapter",
        "before": parent,
        "after": candidate,
    }


class PatchCatalogue:
    """Loads controlled patch events from the frozen prototype manifest."""

    def __init__(self, candidate_specs_path: str | Path, *, seed: int = 0) -> None:
        self.seed = seed
        self._specs = json.loads(Path(candidate_specs_path).read_text(encoding="utf-8"))

    def events(
        self,
        *,
        evolve_tasks: int,
        heldout_tasks: int,
        base_profiles: tuple[str, ...] = ("canonical", "alias", "reordered", "alias_reordered"),
        evolve_seed: int | None = None,
        heldout_seed: int | None = None,
    ) -> tuple[CandidateEvent, ...]:
        events: list[CandidateEvent] = []
        for offset, spec in enumerate(self._specs):
            candidate_id = spec["candidate_id"]
            parent = Harness(adapter_name=spec["parent_adapter"])
            visible = sample_base_tasks(
                evolve_tasks,
                seed=(self.seed + 11 if evolve_seed is None else evolve_seed) + offset * 101,
                task_id_prefix=f"visible-{candidate_id}",
                profiles=base_profiles,
            )
            heldout = sample_base_tasks(
                heldout_tasks,
                seed=(self.seed + 29 if heldout_seed is None else heldout_seed) + offset * 101,
                task_id_prefix=f"heldout-{candidate_id}",
                profiles=base_profiles,
            )
            audit_context = {
                "active_schema": spec["active_schema"],
                "preserve_schema": "canonical",
            }
            patch = Patch(
                patch_id=candidate_id,
                patch_type="tool_adapter",
                claimed_target=spec["claimed_target"],
                claimed_scope=tuple(spec["claimed_scope"]),
                diff={
                    **_adapter_diff(spec["parent_adapter"], spec["candidate_adapter"]),
                    "audit_context": audit_context,
                },
                candidate_adapter=spec["candidate_adapter"],
                evidence_trace_ids=tuple(task.task_id for task in visible),
                rationale="PatchCatalogue controlled candidate selected from visible traces.",
            )
            events.append(
                CandidateEvent(
                    event_id=f"event-{candidate_id}",
                    parent=parent,
                    patch=patch,
                    visible_tasks=visible,
                    heldout_tasks=heldout,
                )
            )
        return tuple(events)


class Trace2PatchStub:
    """Stage-3 placeholder for a trace-conditioned proposal model.

    The catalogue is deliberately deterministic. Its evidence trace identifiers
    are retained so a future LLM implementation can replace only this proposal
    source while leaving the audit interface unchanged.
    """

    def propose(self, event: CandidateEvent) -> Patch:
        return event.patch
