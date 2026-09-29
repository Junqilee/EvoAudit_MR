"""Online and offline event stores with no cross-layer payload leakage."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from evoaudit_mr.types import CandidateEvent, GateDecision


def _append(path: str | Path, payload: dict[str, object]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def append_online_event(path: str | Path, event: CandidateEvent, decision: GateDecision) -> None:
    logical_pairs = int(decision.bucket_summary.get("logical_pairs", 0))
    # Visible feedback is shared candidate-generation input, not audit budget.
    # Only probes counted as logical audit pairs contribute to audit tool cost.
    tool_calls = (
        sum(
            len(result.parent.tool_calls) + len(result.candidate.tool_calls)
            for result in decision.probe_results
        )
        if logical_pairs
        else 0
    )
    _append(
        path,
        {
            "event_id": event.event_id,
            "patch_id": event.patch.patch_id,
            "method": decision.method,
            "decision": decision.decision,
            "decision_reasons": list(decision.reasons),
            "bucket_summary": dict(decision.bucket_summary),
            "logical_cost": {
                "paired_rollouts": logical_pairs,
                "tool_calls": tool_calls,
            },
        },
    )


def append_hidden_event(path: str | Path, event: CandidateEvent, label: Any) -> None:
    _append(
        path,
        {
            "event_id": event.event_id,
            "patch_id": event.patch.patch_id,
            "hidden_label": {
                "reliable": label.reliable,
                "reasons": list(label.reasons),
                "target_delta": label.target_delta,
                "replay_delta": label.replay_delta,
                "safety_events": list(label.safety_events),
            },
            "probe_results": [result.to_dict() for result in label.results],
        },
    )
