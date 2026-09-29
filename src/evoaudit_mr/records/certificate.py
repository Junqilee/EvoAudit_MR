"""Stable certificates for online update-admission decisions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from evoaudit_mr.types import CandidateEvent, GateDecision, stable_hash


def certificate_payload(
    event: CandidateEvent,
    decision: GateDecision,
    *,
    manifest_hash: str,
    run_id: str,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "run_id": run_id,
        "method": decision.method,
        "manifest_hash": manifest_hash,
        "parent_harness_hash": event.parent.fingerprint,
        "candidate_harness_hash": event.candidate.fingerprint,
        "patch": event.patch.to_dict(),
        "audit_suite": {
            "budget_pairs": decision.bucket_summary.get("logical_pairs", 0),
            "probe_ids": [result.probe.probe_id for result in decision.probe_results],
        },
        "bucket_summary": dict(decision.bucket_summary),
        "decision": decision.decision,
        "decision_reasons": list(decision.reasons),
        "logical_cost": {
            "paired_rollouts": decision.bucket_summary.get("logical_pairs", 0),
            # Direct commitment consumes visible feedback but no *audit* probe
            # budget, matching the online event log and reported cost metric.
            "tool_calls": (
                sum(
                    len(result.parent.tool_calls) + len(result.candidate.tool_calls)
                    for result in decision.probe_results
                )
                if decision.bucket_summary.get("logical_pairs", 0)
                else 0
            ),
        },
        "probe_results": [result.to_dict() for result in decision.probe_results],
    }
    payload["certificate_hash"] = stable_hash(payload)
    return payload


def write_certificate(
    output_dir: str | Path,
    event: CandidateEvent,
    decision: GateDecision,
    *,
    manifest_hash: str,
    run_id: str,
) -> Path:
    directory = Path(output_dir) / decision.method / "certificates"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{event.patch.patch_id}.json"
    path.write_text(
        json.dumps(
            certificate_payload(
                event,
                decision,
                manifest_hash=manifest_hash,
                run_id=run_id,
            ),
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return path


def manifest_hash(manifest: dict[str, Any]) -> str:
    return stable_hash(manifest)
