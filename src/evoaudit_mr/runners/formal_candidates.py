"""Run the committed 180-event formal candidate experiment in two phases.

``--phase online`` contains no import from ``evoaudit_mr.formal.offline``.
``--phase offline`` verifies commitments and reads already sealed online logs.
"""

from __future__ import annotations

import argparse
import csv
from hashlib import sha256
import json
from pathlib import Path
import random
from typing import Any, Iterable, Mapping

from evoaudit_mr.audits.gate import direct_commit, fixed_heldout
from evoaudit_mr.evaluation import mean_delta, paired_results
from evoaudit_mr.formal.audit import formal_evoaudit_mr, random_formal_probes, route_formal_probes
from evoaudit_mr.formal.catalogue import build_formal_events, mechanism_cluster
from evoaudit_mr.formal.metrics import confusion_from_pairs
from evoaudit_mr.formal.protocol import (
    ProtocolError,
    complete_online_phase,
    load_json,
    manifest_digest,
    require_online_complete,
    validate_offline_reveal,
)
from evoaudit_mr.records.certificate import write_certificate
from evoaudit_mr.records.event_store import append_hidden_event, append_online_event
from evoaudit_mr.types import CandidateEvent, GateDecision


METHODS = ("direct_commit", "fixed_heldout", "fixed_random_audit", "evoaudit_mr")


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _contracts(root: Path, manifest: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        environment: json.loads((root / path).read_text(encoding="utf-8"))
        for environment, path in manifest["environment_contracts"].items()
    }


def _online_record_hash(output_dir: Path) -> str:
    hasher = sha256()
    for method in METHODS:
        path = output_dir / "online" / method / "events.jsonl"
        if not path.exists():
            raise ProtocolError(f"Missing online log for {method}.")
        hasher.update(method.encode("utf-8"))
        hasher.update(path.read_bytes())
        certificate_dir = output_dir / method / "certificates"
        if not certificate_dir.exists():
            raise ProtocolError(f"Missing certificate directory for {method}.")
        for certificate in sorted(certificate_dir.glob("*.json")):
            hasher.update(certificate.relative_to(output_dir).as_posix().encode("utf-8"))
            hasher.update(certificate.read_bytes())
    thinning = output_dir / "THINNING_COMPLETE.json"
    if not thinning.exists():
        raise ProtocolError("Missing online-frozen random-thinning indices.")
    hasher.update(b"THINNING_COMPLETE")
    hasher.update(thinning.read_bytes())
    return hasher.hexdigest()


def _generic_gate(event: CandidateEvent, *, method: str, probes: tuple) -> GateDecision:
    results = paired_results(event, probes)
    grouped = {bucket: tuple(row for row in results if row.probe.bucket == bucket) for bucket in ("target", "replay", "safety")}
    target_delta = mean_delta(grouped["target"])
    replay_delta = mean_delta(grouped["replay"])
    target_improvements = sum(row.success_delta > 0 for row in grouped["target"])
    safety_events = tuple(name for row in grouped["safety"] for name in row.candidate.safety_events)
    reasons: list[str] = []
    if target_delta < 0 or target_improvements < 1:
        reasons.append("random_target_failed")
    if replay_delta < 0:
        reasons.append("random_replay_regression")
    if safety_events:
        reasons.append("random_safety_failed")
    return GateDecision(
        method=method,
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


def formal_online_decisions(
    event: CandidateEvent,
    *,
    manifest: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> dict[str, GateDecision]:
    budget = int(manifest["audit_budget_pairs"])
    seed = int(manifest["seed"]) + sum(ord(char) for char in event.event_id)
    suite = route_formal_probes(event, budget_pairs=budget, seed=seed, contract=contract)
    random_suite = random_formal_probes(event, budget_pairs=budget, seed=seed)
    return {
        "direct_commit": direct_commit(event),
        "fixed_heldout": fixed_heldout(event, budget_pairs=budget),
        "fixed_random_audit": _generic_gate(event, method="fixed_random_audit", probes=random_suite),
        "evoaudit_mr": formal_evoaudit_mr(event, suite),
    }


def _read_decisions(output_dir: Path) -> dict[str, dict[str, bool]]:
    decisions: dict[str, dict[str, bool]] = {}
    for method in METHODS:
        path = output_dir / "online" / method / "events.jsonl"
        for line in path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            decisions.setdefault(str(row["event_id"]), {})[method] = row["decision"] == "commit"
    return decisions


def _read_costs(output_dir: Path) -> dict[str, dict[str, dict[str, float]]]:
    costs: dict[str, dict[str, dict[str, float]]] = {}
    for method in METHODS:
        path = output_dir / "online" / method / "events.jsonl"
        for line in path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            raw = row.get("logical_cost", {})
            costs.setdefault(str(row["event_id"]), {})[method] = {
                "paired_rollouts": float(raw.get("paired_rollouts", 0)),
                "tool_calls": float(raw.get("tool_calls", 0)),
            }
    return costs


def _write_thinning(output_dir: Path, decisions: Mapping[str, Mapping[str, bool]], analysis_seeds: Iterable[int]) -> None:
    target = [event_id for event_id, by_method in decisions.items() if by_method["evoaudit_mr"]]
    payload: dict[str, Any] = {"target_method": "evoaudit_mr", "target_count": len(target), "comparisons": {}}
    for method in ("direct_commit", "fixed_heldout", "fixed_random_audit"):
        available = [event_id for event_id, by_method in decisions.items() if by_method[method]]
        common = min(len(target), len(available))
        rows = []
        for seed in analysis_seeds:
            rng = random.Random(seed + sum(ord(char) for char in method))
            baseline = sorted(rng.sample(available, common))
            evo = sorted(rng.sample(target, common)) if common < len(target) else sorted(target)
            rows.append({"seed": seed, "baseline_event_ids": baseline, "evoaudit_event_ids": evo})
        payload["comparisons"][method] = {
            "baseline_accept_count": len(available),
            "common_count": common,
            "symmetric_fallback": len(available) < len(target),
            "samples": rows,
        }
    path = output_dir / "THINNING_COMPLETE.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run_online(manifest_path: str | Path, output_dir: str | Path) -> Path:
    """Run and seal all online decisions.  Safe only for a new output directory."""
    manifest = load_json(manifest_path)
    digest = manifest_digest(manifest)
    root = _repository_root()
    target = Path(output_dir)
    if target.exists() and any(target.iterdir()):
        raise FileExistsError("Formal online output directory must be new and empty.")
    target.mkdir(parents=True, exist_ok=True)
    events = build_formal_events(
        instances_per_mechanism=int(manifest["instances_per_mechanism"]),
        evolve_tasks=int(manifest["evolve_tasks_per_event"]),
        validation_tasks=int(manifest["validation_tasks"]),
        seed=int(manifest["seed"]),
    )
    if len(events) != 180:
        raise ProtocolError(f"Formal manifest must produce 180 events, got {len(events)}.")
    contracts = _contracts(root, manifest)
    decisions_by_event: dict[str, dict[str, bool]] = {}
    for event in events:
        decisions = formal_online_decisions(event, manifest=manifest, contract=contracts[event.environment])
        decisions_by_event[event.event_id] = {method: value.committed for method, value in decisions.items()}
        for decision in decisions.values():
            append_online_event(target / "online" / decision.method / "events.jsonl", event, decision)
            write_certificate(target, event, decision, manifest_hash=digest, run_id=f"formal-v1-{digest[:12]}")
    seed_start = int(manifest["analysis_seed_start"])
    seed_count = int(manifest["analysis_seed_count"])
    _write_thinning(target, decisions_by_event, range(seed_start, seed_start + seed_count))
    record_hash = _online_record_hash(target)
    complete_online_phase(target, manifest_hash=digest, event_count=len(events), online_record_hash=record_hash)
    return target


def _format(value: float | None) -> str:
    return "NA" if value is None else f"{value:.3f}"


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _metrics_rows(
    events: tuple[CandidateEvent, ...],
    decisions: Mapping[str, Mapping[str, bool]],
    labels: Mapping[str, Any],
    costs: Mapping[str, Mapping[str, Mapping[str, float]]],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for environment in ("AliasTool", "SwitchRule", "PermissionPath", "Overall"):
        selected = events if environment == "Overall" else tuple(event for event in events if event.environment == environment)
        for method in METHODS:
            confusion = confusion_from_pairs(
                (
                    decisions[event.event_id][method],
                    labels[event.event_id].reliable,
                    "safety_invariant_failed" in labels[event.event_id].reasons,
                )
                for event in selected
            )
            row: dict[str, object] = {"environment": environment, "method": method, "n_events": len(selected)}
            row.update({key: _format(value) if isinstance(value, float) or value is None else value for key, value in confusion.to_dict().items()})
            row["mean_logical_pairs"] = _format(
                sum(costs[event.event_id][method]["paired_rollouts"] for event in selected) / len(selected)
            )
            row["mean_tool_calls"] = _format(
                sum(costs[event.event_id][method]["tool_calls"] for event in selected) / len(selected)
            )
            rows.append(row)
    return rows


def _cluster_bootstrap(
    events: tuple[CandidateEvent, ...],
    decisions: Mapping[str, Mapping[str, bool]],
    labels: Mapping[str, Any],
    *,
    samples: int = 1_000,
    seed: int = 71,
) -> list[dict[str, object]]:
    clusters_by_env: dict[str, dict[str, list[CandidateEvent]]] = {}
    for event in events:
        clusters_by_env.setdefault(event.environment, {}).setdefault(mechanism_cluster(event), []).append(event)
    deltas: dict[str, dict[str, list[float]]] = {
        baseline: {"far": [], "uur": []} for baseline in ("direct_commit", "fixed_heldout", "fixed_random_audit")
    }
    rng = random.Random(seed)
    for _ in range(samples):
        sample_events: list[CandidateEvent] = []
        for clusters in clusters_by_env.values():
            keys = sorted(clusters)
            for key in (rng.choice(keys) for _ in keys):
                sample_events.extend(clusters[key])
        for baseline in deltas:
            baseline_confusion = confusion_from_pairs(
                (decisions[event.event_id][baseline], labels[event.event_id].reliable, "safety_invariant_failed" in labels[event.event_id].reasons)
                for event in sample_events
            )
            evo_confusion = confusion_from_pairs(
                (decisions[event.event_id]["evoaudit_mr"], labels[event.event_id].reliable, "safety_invariant_failed" in labels[event.event_id].reasons)
                for event in sample_events
            )
            if baseline_confusion.far is not None and evo_confusion.far is not None:
                deltas[baseline]["far"].append(evo_confusion.far - baseline_confusion.far)
            if baseline_confusion.uur is not None and evo_confusion.uur is not None:
                deltas[baseline]["uur"].append(evo_confusion.uur - baseline_confusion.uur)
    rows: list[dict[str, object]] = []
    for baseline, metrics in deltas.items():
        for metric, values in metrics.items():
            values.sort()
            rows.append({
                "comparison": f"evoaudit_mr_minus_{baseline}",
                "metric": metric,
                "n_bootstrap": len(values),
                "ci_low": _format(values[int(0.025 * len(values))]) if values else "NA",
                "ci_high": _format(values[max(0, int(0.975 * len(values)) - 1)]) if values else "NA",
            })
    return rows


def _thinning_rows(
    output_dir: Path,
    decisions: Mapping[str, Mapping[str, bool]],
    labels: Mapping[str, Any],
) -> list[dict[str, object]]:
    """Score frozen matched-commit selections over the full candidate universe.

    A thinning sample selects which already accepted updates remain committed;
    every other candidate is a reject.  Computing a confusion matrix only on
    sampled commits would mechanically omit TN/FN and misstate both FAR and
    UUR.  The random indices remain frozen online; this function merely gives
    them their correct all-180-event interpretation after hidden reveal.
    """
    payload = json.loads((output_dir / "THINNING_COMPLETE.json").read_text(encoding="utf-8"))
    all_event_ids = set(labels)
    rows: list[dict[str, object]] = []
    for baseline, comparison in payload["comparisons"].items():
        for sample in comparison["samples"]:
            for method, event_ids in ((baseline, sample["baseline_event_ids"]), ("evoaudit_mr", sample["evoaudit_event_ids"])):
                committed_ids = set(event_ids)
                if not committed_ids.issubset(all_event_ids):
                    raise ProtocolError("Frozen thinning indices include an unknown candidate event.")
                if any(not decisions[event_id][method] for event_id in committed_ids):
                    raise ProtocolError("Frozen thinning indices include an online rejection.")
                confusion = confusion_from_pairs(
                    (
                        event_id in committed_ids,
                        labels[event_id].reliable,
                        "safety_invariant_failed" in labels[event_id].reasons,
                    )
                    for event_id in sorted(all_event_ids)
                )
                rows.append({
                    "comparison": baseline,
                    "analysis_seed": sample["seed"],
                    "method": method,
                    "n_events": len(all_event_ids),
                    "n_committed": len(committed_ids),
                    "far": _format(confusion.far),
                    "fdr": _format(confusion.fdr),
                    "ap": _format(confusion.ap),
                    "uur": _format(confusion.uur),
                    "svr": _format(confusion.svr),
                })
    return rows


def run_offline(manifest_path: str | Path, offline_path: str | Path, output_dir: str | Path) -> Path:
    """Verify commitments, reveal hidden labels, and produce offline metrics."""
    manifest = load_json(manifest_path)
    offline = load_json(offline_path)
    digest = manifest_digest(manifest)
    root = _repository_root()
    contracts = _contracts(root, manifest)
    target = Path(output_dir)
    events = build_formal_events(
        instances_per_mechanism=int(manifest["instances_per_mechanism"]),
        evolve_tasks=int(manifest["evolve_tasks_per_event"]),
        validation_tasks=int(manifest["validation_tasks"]),
        seed=int(manifest["seed"]),
    )
    marker = require_online_complete(target, expected_manifest_hash=digest, expected_event_count=len(events))
    if marker["online_record_hash"] != _online_record_hash(target):
        raise ProtocolError("Online decision records were modified after ONLINE_COMPLETE.")
    # The only offline-only import lives inside the offline command body.
    from evoaudit_mr.formal.offline import evaluate_formal_event, hidden_generator_source

    validate_offline_reveal(
        manifest,
        offline,
        generator_source=hidden_generator_source(),
        environment_contracts=contracts,
    )
    hidden_log = target / "offline_hidden" / "events.jsonl"
    if hidden_log.exists():
        raise FileExistsError("Offline labels already exist; formal hidden results are immutable.")
    labels: dict[str, Any] = {}
    for event in events:
        label = evaluate_formal_event(
            event,
            master_key=str(offline["hidden_master_seed"]),
            manifest_hash=digest,
            per_bucket=int(offline["hidden_config"]["per_bucket"]),
        )
        labels[event.event_id] = label
        append_hidden_event(hidden_log, event, label)
    decisions = _read_decisions(target)
    costs = _read_costs(target)
    if set(decisions) != {event.event_id for event in events} or any(set(by_method) != set(METHODS) for by_method in decisions.values()):
        raise ProtocolError("Online logs do not contain exactly one decision per event and method.")
    candidate_rows = []
    for event in events:
        label = labels[event.event_id]
        candidate_rows.append({
            "event_id": event.event_id,
            "patch_id": event.patch.patch_id,
            "environment": event.environment,
            "mechanism_cluster": mechanism_cluster(event),
            "hidden_reliable": label.reliable,
            "hidden_reasons": ";".join(label.reasons) or "none",
            **{method: "commit" if decisions[event.event_id][method] else "reject" for method in METHODS},
        })
    _write_csv(target / "candidate_offline.csv", candidate_rows)
    _write_csv(target / "formal_main.csv", _metrics_rows(events, decisions, labels, costs))
    _write_csv(target / "cluster_bootstrap.csv", _cluster_bootstrap(events, decisions, labels))
    _write_csv(target / "thinning_offline.csv", _thinning_rows(target, decisions, labels))
    return target


def main() -> None:
    root = _repository_root()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", required=True, choices=("online", "offline"))
    parser.add_argument("--manifest", default=str(root / "configs" / "formal_v1_manifest.json"))
    parser.add_argument("--offline-config", default=str(root / "configs" / "formal_v1_offline.json"))
    parser.add_argument("--output-dir", default=str(root / "artifacts_formal" / "formal-v1"))
    args = parser.parse_args()
    if args.phase == "online":
        run_online(args.manifest, args.output_dir)
    else:
        run_offline(args.manifest, args.offline_config, args.output_dir)


if __name__ == "__main__":
    main()
