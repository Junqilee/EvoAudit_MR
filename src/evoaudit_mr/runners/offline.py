"""Offline-only hidden evaluation, physically separate from online gates."""

from __future__ import annotations

from pathlib import Path

from evoaudit_mr.hidden.evaluator import ReliabilityLabel, evaluate_full
from evoaudit_mr.hidden.generator import generate_hidden_universe as generate_aliastool_hidden_universe
from evoaudit_mr.hidden.permissionpath_generator import generate_hidden_universe as generate_permissionpath_hidden_universe
from evoaudit_mr.hidden.switchrule_generator import generate_hidden_universe as generate_switchrule_hidden_universe
from evoaudit_mr.records.event_store import append_hidden_event
from evoaudit_mr.types import CandidateEvent


def offline_label(
    output_dir: Path,
    event: CandidateEvent,
    *,
    per_bucket: int,
    seed: int,
) -> ReliabilityLabel:
    if event.environment == "AliasTool":
        universe = generate_aliastool_hidden_universe(per_bucket=per_bucket, seed=seed)
    elif event.environment == "SwitchRule":
        universe = generate_switchrule_hidden_universe(per_bucket=per_bucket, seed=seed)
    elif event.environment == "PermissionPath":
        universe = generate_permissionpath_hidden_universe(per_bucket=per_bucket, seed=seed)
    else:
        raise ValueError(f"Unsupported hidden evaluation environment: {event.environment}")
    label = evaluate_full(event, universe)
    append_hidden_event(output_dir / "offline_hidden" / "events.jsonl", event, label)
    return label
