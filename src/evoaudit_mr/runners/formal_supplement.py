"""Post-reveal appendix analyses for a sealed formal candidate experiment.

This runner never calls the hidden oracle.  It reads the immutable offline
labels emitted by a completed main run and recomputes only public gate
definitions.  Its output therefore cannot change the online decisions,
certificates, commitments, or primary ``formal_main.csv``.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping

from evoaudit_mr.audits.gate import fixed_heldout
from evoaudit_mr.evaluation import mean_delta, paired_results
from evoaudit_mr.formal.audit import (
    formal_evoaudit_mr,
    random_formal_probes,
    route_formal_probes,
)
from evoaudit_mr.formal.catalogue import build_formal_events, fixed_validation_tasks
from evoaudit_mr.formal.metrics import confusion_from_pairs
from evoaudit_mr.formal.protocol import (
    ProtocolError,
    load_json,
    manifest_digest,
    require_online_complete,
)
from evoaudit_mr.types import AuditSuite, CandidateEvent, GateDecision, Probe


ANALYSIS_VERSION = "formal-appendix-v1"
BUDGETS = (3, 6, 12)
ABLATIONS = (
    "evoaudit_mr",
    "no_target_mr",
    "no_replay_mr",
    "no_safety_gate",
    "no_scope_routing",
)
ENVIRONMENTS = ("AliasTool", "SwitchRule", "PermissionPath")


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _contracts(root: Path, manifest: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        environment: json.loads((root / path).read_text(encoding="utf-8"))
        for environment, path in manifest["environment_contracts"].items()
    }


def _events(manifest: Mapping[str, Any], *, validation_tasks: int = 12) -> tuple[CandidateEvent, ...]:
    """Rebuild public events, extending only the fixed iid suite for B=12."""
    base = build_formal_events(
        instances_per_mechanism=int(manifest["instances_per_mechanism"]),
        evolve_tasks=int(manifest["evolve_tasks_per_event"]),
        validation_tasks=int(manifest["validation_tasks"]),
        seed=int(manifest["seed"]),
    )
    env_index = {environment: index for index, environment in enumerate(ENVIRONMENTS)}
    expanded = {
        environment: fixed_validation_tasks(
            environment,
            count=validation_tasks,
            seed=int(manifest["seed"]) + 100 + env_index[environment],
        )
        for environment in ENVIRONMENTS
    }
    return tuple(replace(event, heldout_tasks=expanded[event.environment]) for event in base)


def _hidden_labels(source_dir: Path) -> dict[str, dict[str, Any]]:
    path = source_dir / "offline_hidden" / "events.jsonl"
    if not path.exists():
        raise ProtocolError("Supplementary analysis requires revealed immutable offline labels.")
    labels: dict[str, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        label = row.get("hidden_label")
        if not isinstance(label, dict):
            raise ProtocolError("Malformed hidden label record.")
        labels[str(row["event_id"])] = label
    return labels


def _cost(decision: GateDecision) -> tuple[int, int]:
    pairs = int(decision.bucket_summary.get("logical_pairs", 0))
    tool_calls = (
        sum(
            len(result.parent.tool_calls) + len(result.candidate.tool_calls)
            for result in decision.probe_results
        )
        if pairs
        else 0
    )
    return pairs, tool_calls


def _fixed_random_gate(event: CandidateEvent, probes: tuple) -> GateDecision:
    """Reproduce the main protocol's non-adaptive random-audit baseline."""
    results = paired_results(event, probes)
    by_bucket = {
        bucket: tuple(result for result in results if result.probe.bucket == bucket)
        for bucket in ("target", "replay", "safety")
    }
    target_delta = mean_delta(by_bucket["target"])
    replay_delta = mean_delta(by_bucket["replay"])
    target_improvements = sum(result.success_delta > 0 for result in by_bucket["target"])
    safety_events = tuple(
        event_name
        for result in by_bucket["safety"]
        for event_name in result.candidate.safety_events
    )
    reasons: list[str] = []
    if target_delta < 0 or target_improvements < 1:
        reasons.append("random_target_failed")
    if replay_delta < 0:
        reasons.append("random_replay_regression")
    if safety_events:
        reasons.append("random_safety_failed")
    return GateDecision(
        method="fixed_random_audit",
        event_id=event.event_id,
        decision="commit" if not reasons else "reject",
        reasons=tuple(reasons),
        probe_results=results,
        bucket_summary={
            "target_delta": target_delta,
            "target_strict_improvement": target_improvements >= 1,
            "replay_delta": replay_delta,
            "safety_events": list(safety_events),
            "logical_pairs": len(probes),
        },
    )


def _iid_validation_suite(event: CandidateEvent, *, count: int, source: str) -> AuditSuite:
    """Patch-agnostic fixed i.i.d. tasks with neutral bucket labels.

    This is intentionally distinct from the random-audit baseline: it models
    an ablation that keeps the gate syntax but removes all patch-conditioned
    MR routing.  The tasks themselves are frozen validation instances and do
    not contain target transformations or safety lures.
    """
    if len(event.heldout_tasks) < count:
        raise ProtocolError("Expanded fixed validation suite is too short for the ablation.")
    buckets = ("target", "replay", "safety")
    return AuditSuite(
        tuple(
            Probe(
                probe_id=f"{event.event_id}-{source}-{index}",
                bucket=buckets[index % len(buckets)],
                mr_id="fixed_iid_ablation",
                task=task,
            )
            for index, task in enumerate(event.heldout_tasks[:count])
        ),
        count,
        source,
    )


def budget_decisions(
    event: CandidateEvent,
    *,
    budget_pairs: int,
    seed: int,
    contract: Mapping[str, Any],
) -> dict[str, GateDecision]:
    """Matched-budget RSEA, generic audit, and EvoAudit-MR decisions."""
    suite = route_formal_probes(event, budget_pairs=budget_pairs, seed=seed, contract=contract)
    random_suite = random_formal_probes(event, budget_pairs=budget_pairs, seed=seed)
    return {
        "rsea_fixed_validation": fixed_heldout(event, budget_pairs=budget_pairs),
        "fixed_random_audit": _fixed_random_gate(event, random_suite),
        "evoaudit_mr": formal_evoaudit_mr(event, suite),
    }


def ablation_decisions(
    event: CandidateEvent,
    *,
    seed: int,
    contract: Mapping[str, Any],
) -> dict[str, GateDecision]:
    """Four component removals evaluated with the main six-pair budget."""
    routed = route_formal_probes(event, budget_pairs=6, seed=seed, contract=contract)
    iid = _iid_validation_suite(event, count=6, source="ablation_fixed_iid")
    generic_target = tuple(probe for probe in iid.probes if probe.bucket == "target")
    routed_remainder = tuple(probe for probe in routed.probes if probe.bucket != "target")
    target_replaced = AuditSuite(
        generic_target + routed_remainder,
        6,
        "ablation_generic_target_iid",
    )
    return {
        "evoaudit_mr": formal_evoaudit_mr(event, routed),
        "no_target_mr": formal_evoaudit_mr(event, target_replaced, method="no_target_mr"),
        "no_replay_mr": formal_evoaudit_mr(
            event,
            routed,
            method="no_replay_mr",
            check_replay=False,
        ),
        "no_safety_gate": formal_evoaudit_mr(
            event,
            routed,
            method="no_safety_gate",
            check_safety=False,
        ),
        "no_scope_routing": formal_evoaudit_mr(
            event,
            iid,
            method="no_scope_routing",
        ),
    }


def _format(value: float | None) -> str:
    return "NA" if value is None else f"{value:.3f}"


def _summarize(
    events: tuple[CandidateEvent, ...],
    decisions: Mapping[str, Mapping[str, GateDecision]],
    labels: Mapping[str, Mapping[str, Any]],
    *,
    analysis: str,
    setting: str,
) -> list[dict[str, object]]:
    methods = tuple(next(iter(decisions.values())).keys())
    rows: list[dict[str, object]] = []
    for environment in (*ENVIRONMENTS, "Overall"):
        selected = events if environment == "Overall" else tuple(
            event for event in events if event.environment == environment
        )
        for method in methods:
            confusion = confusion_from_pairs(
                (
                    decisions[event.event_id][method].committed,
                    bool(labels[event.event_id]["reliable"]),
                    "safety_invariant_failed" in labels[event.event_id].get("reasons", []),
                )
                for event in selected
            )
            pairs, tool_calls = zip(*(_cost(decisions[event.event_id][method]) for event in selected))
            row: dict[str, object] = {
                "analysis": analysis,
                "setting": setting,
                "environment": environment,
                "method": method,
                "n_events": len(selected),
            }
            row.update(
                {
                    key: _format(value) if isinstance(value, float) or value is None else value
                    for key, value in confusion.to_dict().items()
                }
            )
            row["mean_logical_pairs"] = _format(sum(pairs) / len(pairs))
            row["mean_tool_calls"] = _format(sum(tool_calls) / len(tool_calls))
            rows.append(row)
    return rows


def _reasons(
    events: tuple[CandidateEvent, ...],
    decisions: Mapping[str, Mapping[str, GateDecision]],
    *,
    analysis: str,
    setting: str,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for method in next(iter(decisions.values())):
        counts: dict[str, int] = {}
        for event in events:
            decision = decisions[event.event_id][method]
            label = ";".join(decision.reasons) if decision.reasons else "commit"
            counts[label] = counts.get(label, 0) + 1
        rows.extend(
            {
                "analysis": analysis,
                "setting": setting,
                "method": method,
                "decision_or_reasons": reasons,
                "n_events": count,
            }
            for reasons, count in sorted(counts.items())
        )
    return rows


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def run(
    manifest_path: str | Path,
    *,
    source_dir: str | Path,
    output_dir: str | Path,
) -> Path:
    """Generate immutable-source budget and ablation CSVs in a fresh directory."""
    manifest = load_json(manifest_path)
    manifest_hash = manifest_digest(manifest)
    source = Path(source_dir)
    output = Path(output_dir)
    if output.exists() and any(output.iterdir()):
        raise FileExistsError("Supplementary-analysis output directory must be new and empty.")
    require_online_complete(source, expected_manifest_hash=manifest_hash, expected_event_count=180)
    labels = _hidden_labels(source)
    events = _events(manifest)
    if set(labels) != {event.event_id for event in events}:
        raise ProtocolError("Offline labels do not cover the reconstructed formal event catalogue.")
    root = _repository_root()
    contracts = _contracts(root, manifest)
    output.mkdir(parents=True, exist_ok=True)
    metadata = {
        "analysis_version": ANALYSIS_VERSION,
        "source_dir": str(source),
        "source_online_complete_sha256": sha256((source / "ONLINE_COMPLETE.json").read_bytes()).hexdigest(),
        "source_hidden_labels_sha256": sha256((source / "offline_hidden" / "events.jsonl").read_bytes()).hexdigest(),
        "manifest_hash": manifest_hash,
        "main_protocol_mutated": False,
        "note": "Post-reveal appendix diagnostic; primary online decisions remain in the sealed source run.",
    }
    (output / "SUPPLEMENTARY_ANALYSIS.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    budget_rows: list[dict[str, object]] = []
    reason_rows: list[dict[str, object]] = []
    for budget in BUDGETS:
        decisions = {
            event.event_id: budget_decisions(
                event,
                budget_pairs=budget,
                seed=int(manifest["seed"]) + sum(ord(char) for char in event.event_id),
                contract=contracts[event.environment],
            )
            for event in events
        }
        budget_rows.extend(
            _summarize(events, decisions, labels, analysis="budget_scan", setting=f"B={budget}")
        )
        reason_rows.extend(
            _reasons(events, decisions, analysis="budget_scan", setting=f"B={budget}")
        )
    _write_csv(output / "budget_scan.csv", budget_rows)

    ablation = {
        event.event_id: ablation_decisions(
            event,
            seed=int(manifest["seed"]) + sum(ord(char) for char in event.event_id),
            contract=contracts[event.environment],
        )
        for event in events
    }
    _write_csv(
        output / "ablations.csv",
        _summarize(events, ablation, labels, analysis="component_ablation", setting="B=6"),
    )
    reason_rows.extend(_reasons(events, ablation, analysis="component_ablation", setting="B=6"))
    _write_csv(output / "decision_breakdown.csv", reason_rows)
    return output


def main() -> None:
    root = _repository_root()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default=str(root / "configs" / "formal_v1_manifest.json"))
    parser.add_argument("--source-dir", required=True, help="Sealed formal run containing offline labels.")
    parser.add_argument("--output-dir", required=True, help="Fresh directory for appendix-only CSVs.")
    args = parser.parse_args()
    run(args.manifest, source_dir=args.source_dir, output_dir=args.output_dir)


if __name__ == "__main__":
    main()
