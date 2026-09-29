"""Online-only gate execution. This module has no hidden-evaluation imports."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from evoaudit_mr.audits.gate import direct_commit, evoaudit_mr, fixed_heldout, fixed_random_audit
from evoaudit_mr.audits.router import route_probes
from evoaudit_mr.records.certificate import write_certificate
from evoaudit_mr.records.event_store import append_online_event
from evoaudit_mr.types import CandidateEvent, GateDecision


def online_decisions(
    event: CandidateEvent,
    manifest: dict[str, Any],
    contract: dict[str, Any],
) -> dict[str, GateDecision]:
    budget = int(manifest["audit_budget_pairs"])
    seed = int(manifest["seed"])
    suite = route_probes(
        event.patch,
        environment=event.environment,
        budget_pairs=budget,
        seed=seed,
        contract=contract,
    )
    return {
        "direct_commit": direct_commit(event),
        "fixed_heldout": fixed_heldout(event, budget_pairs=budget),
        "fixed_random_audit": fixed_random_audit(event, budget_pairs=budget, seed=seed),
        "evoaudit_mr": evoaudit_mr(event, suite),
    }


def persist_online_decisions(
    output_dir: Path,
    event: CandidateEvent,
    decisions: dict[str, GateDecision],
    *,
    manifest_digest: str,
    run_id: str,
) -> None:
    for decision in decisions.values():
        append_online_event(
            output_dir / decision.method / "online" / "events.jsonl",
            event,
            decision,
        )
        write_certificate(
            output_dir,
            event,
            decision,
            manifest_hash=manifest_digest,
            run_id=run_id,
        )
