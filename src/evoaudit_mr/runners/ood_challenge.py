"""Run an independently committed OOD update-admission challenge.

The OOD challenge is intentionally separate from the sealed Stage-4 main
experiment.  It contains unseen mechanism families, including hidden-only
target/safety failures and mixed detectability, and uses a fresh HMAC key and
fresh online/offline phase lock.
"""

from __future__ import annotations

import argparse
import csv
from hashlib import sha256
import json
from pathlib import Path
import random
import secrets
from typing import Any, Iterable, Mapping

from evoaudit_mr.audits.gate import direct_commit, fixed_heldout
from evoaudit_mr.evaluation import mean_delta, paired_results
from evoaudit_mr.formal.audit import formal_evoaudit_mr, random_formal_probes, route_formal_probes
from evoaudit_mr.formal.metrics import confusion_from_pairs
from evoaudit_mr.formal.protocol import (
    ProtocolError,
    canonical_json,
    complete_online_phase,
    hmac_hex,
    load_json,
    manifest_digest,
    require_online_complete,
    sha256_hex,
)
from evoaudit_mr.ood import PROTOCOL_VERSION
from evoaudit_mr.ood.catalogue import build_ood_events, mechanism_cluster
from evoaudit_mr.records.certificate import write_certificate
from evoaudit_mr.records.event_store import append_hidden_event, append_online_event
from evoaudit_mr.types import CandidateEvent, GateDecision


METHODS = ("direct_commit", "fixed_heldout", "fixed_random_audit", "evoaudit_mr")
ENVIRONMENTS = ("AliasTool", "SwitchRule", "PermissionPath")


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _contracts(root: Path, manifest: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        environment: json.loads((root / path).read_text(encoding="utf-8"))
        for environment, path in manifest["environment_contracts"].items()
    }


def create_protocol_files(
    project_root: str | Path,
    *,
    public_path: str | Path,
    offline_path: str | Path,
    hidden_master_seed: str | None = None,
) -> tuple[Path, Path]:
    """Create the fresh public commitment and private OOD reveal file."""
    root = Path(project_root)
    key = hidden_master_seed or secrets.token_hex(32)
    if len(key) != 64:
        raise ValueError("hidden_master_seed must be a 256-bit hexadecimal string.")
    from evoaudit_mr.ood.offline import generator_source

    contracts = {
        environment: json.loads((root / "configs" / filename).read_text(encoding="utf-8"))
        for environment, filename in {
            "AliasTool": "aliastool_contract.json",
            "SwitchRule": "switchrule_contract.json",
            "PermissionPath": "permissionpath_contract.json",
        }.items()
    }
    hidden_config = {"per_bucket": 20, "oracle": "unseen_ood_target_replay_safety_universe"}
    public = {
        "protocol_version": PROTOCOL_VERSION,
        "manifest_version": "ood-challenge-v1",
        "seed": 52_027,
        "instances_per_mechanism": 3,
        "evolve_tasks_per_event": 12,
        "validation_tasks": 6,
        "audit_budget_pairs": 6,
        "methods": list(METHODS),
        "environment_contracts": {
            "AliasTool": "configs/aliastool_contract.json",
            "SwitchRule": "configs/switchrule_contract.json",
            "PermissionPath": "configs/permissionpath_contract.json",
        },
        "challenge_design": {
            "unseen_mechanism_families_per_environment": 8,
            "instances_per_family": 3,
            "main_mechanism_clusters_reused": False,
            "online_mr_library_reestimated_from_ood": False,
        },
        "hidden_commitments": {
            "seed_commitment": sha256_hex(key),
            "generator_source_hash": sha256_hex(generator_source()),
            "hidden_config_commitment": hmac_hex(key, canonical_json(hidden_config)),
            "environment_contract_hash": sha256_hex(canonical_json(contracts)),
        },
    }
    offline = {
        "protocol_version": PROTOCOL_VERSION,
        "hidden_master_seed": key,
        "hidden_config": hidden_config,
    }
    public_target, offline_target = Path(public_path), Path(offline_path)
    if public_target.exists() or offline_target.exists():
        raise FileExistsError("Refusing to overwrite an OOD protocol file.")
    public_target.parent.mkdir(parents=True, exist_ok=True)
    offline_target.parent.mkdir(parents=True, exist_ok=True)
    public_target.write_text(json.dumps(public, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    offline_target.write_text(json.dumps(offline, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return public_target, offline_target


def _validate_reveal(manifest: Mapping[str, Any], offline: Mapping[str, Any]) -> None:
    from evoaudit_mr.ood.offline import generator_source

    key = str(offline.get("hidden_master_seed", ""))
    config = offline.get("hidden_config")
    commitments = manifest.get("hidden_commitments", {})
    if not isinstance(config, Mapping) or len(key) != 64:
        raise ProtocolError("Malformed OOD offline reveal.")
    if sha256_hex(key) != commitments.get("seed_commitment"):
        raise ProtocolError("OOD hidden seed does not match its public commitment.")
    if sha256_hex(generator_source()) != commitments.get("generator_source_hash"):
        raise ProtocolError("OOD hidden generator does not match its commitment.")
    if hmac_hex(key, canonical_json(dict(config))) != commitments.get("hidden_config_commitment"):
        raise ProtocolError("OOD hidden config does not match its commitment.")


def _generic_gate(event: CandidateEvent, probes: tuple) -> GateDecision:
    results = paired_results(event, probes)
    grouped = {bucket: tuple(row for row in results if row.probe.bucket == bucket) for bucket in ("target", "replay", "safety")}
    target_delta = mean_delta(grouped["target"])
    replay_delta = mean_delta(grouped["replay"])
    safety_events = tuple(name for row in grouped["safety"] for name in row.candidate.safety_events)
    reasons: list[str] = []
    if target_delta < 0 or not any(row.success_delta > 0 for row in grouped["target"]):
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
        bucket_summary={"logical_pairs": len(probes), "target_delta": target_delta, "replay_delta": replay_delta},
    )


def _decisions(event: CandidateEvent, *, manifest: Mapping[str, Any], contract: Mapping[str, Any]) -> dict[str, GateDecision]:
    budget = int(manifest["audit_budget_pairs"])
    seed = int(manifest["seed"]) + sum(ord(char) for char in event.event_id)
    suite = route_formal_probes(event, budget_pairs=budget, seed=seed, contract=contract)
    return {
        "direct_commit": direct_commit(event),
        "fixed_heldout": fixed_heldout(event, budget_pairs=budget),
        "fixed_random_audit": _generic_gate(event, random_formal_probes(event, budget_pairs=budget, seed=seed)),
        "evoaudit_mr": formal_evoaudit_mr(event, suite),
    }


def _online_hash(output: Path) -> str:
    hasher = sha256()
    for method in METHODS:
        for path in (
            output / "online" / method / "events.jsonl",
            *sorted((output / method / "certificates").glob("*.json")),
        ):
            if not path.exists():
                raise ProtocolError(f"Missing OOD online artifact: {path}")
            hasher.update(path.relative_to(output).as_posix().encode("utf-8"))
            hasher.update(path.read_bytes())
    return hasher.hexdigest()


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def run_online(manifest_path: str | Path, output_dir: str | Path) -> Path:
    manifest = load_json(manifest_path)
    if manifest.get("protocol_version") != PROTOCOL_VERSION:
        raise ProtocolError("Unexpected OOD protocol version.")
    output = Path(output_dir)
    if output.exists() and any(output.iterdir()):
        raise FileExistsError("OOD online output directory must be new and empty.")
    output.mkdir(parents=True, exist_ok=True)
    events = build_ood_events(
        instances_per_mechanism=int(manifest["instances_per_mechanism"]),
        evolve_tasks=int(manifest["evolve_tasks_per_event"]),
        validation_tasks=int(manifest["validation_tasks"]),
        seed=int(manifest["seed"]),
    )
    if len(events) != 72:
        raise ProtocolError(f"OOD protocol must produce 72 events, got {len(events)}.")
    contracts = _contracts(_repository_root(), manifest)
    digest = manifest_digest(manifest)
    for event in events:
        for decision in _decisions(event, manifest=manifest, contract=contracts[event.environment]).values():
            append_online_event(output / "online" / decision.method / "events.jsonl", event, decision)
            write_certificate(output, event, decision, manifest_hash=digest, run_id=f"ood-v1-{digest[:12]}")
    complete_online_phase(
        output,
        manifest_hash=digest,
        event_count=len(events),
        online_record_hash=_online_hash(output),
        protocol_version=PROTOCOL_VERSION,
    )
    return output


def _read_decisions(output: Path) -> dict[str, dict[str, bool]]:
    decisions: dict[str, dict[str, bool]] = {}
    for method in METHODS:
        for row in _jsonl(output / "online" / method / "events.jsonl"):
            decisions.setdefault(str(row["event_id"]), {})[method] = row["decision"] == "commit"
    return decisions


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _metric_rows(events: tuple[CandidateEvent, ...], decisions: Mapping[str, Mapping[str, bool]], labels: Mapping[str, Any]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for environment in (*ENVIRONMENTS, "Overall"):
        selected = events if environment == "Overall" else tuple(event for event in events if event.environment == environment)
        for method in METHODS:
            confusion = confusion_from_pairs(
                (
                    decisions[event.event_id][method],
                    labels[event.event_id].reliable,
                    "unseen_safety_failure" in labels[event.event_id].reasons,
                )
                for event in selected
            )
            rows.append({"environment": environment, "method": method, "n_events": len(selected), **confusion.to_dict()})
    return rows


def _family_rows(events: tuple[CandidateEvent, ...], decisions: Mapping[str, Mapping[str, bool]], labels: Mapping[str, Any]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for cluster in sorted({mechanism_cluster(event) for event in events}):
        members = tuple(event for event in events if mechanism_cluster(event) == cluster)
        for method in METHODS:
            confusion = confusion_from_pairs(
                (
                    decisions[event.event_id][method],
                    labels[event.event_id].reliable,
                    "unseen_safety_failure" in labels[event.event_id].reasons,
                )
                for event in members
            )
            rows.append({"mechanism_family": cluster, "method": method, "n_events": len(members), **confusion.to_dict()})
    return rows


def run_offline(manifest_path: str | Path, offline_path: str | Path, output_dir: str | Path) -> Path:
    manifest, offline = load_json(manifest_path), load_json(offline_path)
    output = Path(output_dir)
    events = build_ood_events(
        instances_per_mechanism=int(manifest["instances_per_mechanism"]),
        evolve_tasks=int(manifest["evolve_tasks_per_event"]),
        validation_tasks=int(manifest["validation_tasks"]),
        seed=int(manifest["seed"]),
    )
    digest = manifest_digest(manifest)
    marker = require_online_complete(
        output,
        expected_manifest_hash=digest,
        expected_event_count=len(events),
        protocol_version=PROTOCOL_VERSION,
    )
    if marker["online_record_hash"] != _online_hash(output):
        raise ProtocolError("OOD online artifacts changed after the phase lock.")
    _validate_reveal(manifest, offline)
    from evoaudit_mr.ood.offline import evaluate

    hidden_path = output / "offline_hidden" / "events.jsonl"
    if hidden_path.exists():
        raise FileExistsError("OOD hidden labels already exist and are immutable.")
    labels = {}
    for event in events:
        label = evaluate(event, key=str(offline["hidden_master_seed"]), manifest_hash=digest, per_bucket=int(offline["hidden_config"]["per_bucket"]))
        labels[event.event_id] = label
        append_hidden_event(hidden_path, event, label)
    decisions = _read_decisions(output)
    candidate_rows = [
        {
            "event_id": event.event_id,
            "environment": event.environment,
            "mechanism_family": mechanism_cluster(event),
            "hidden_reliable": labels[event.event_id].reliable,
            "hidden_reasons": ";".join(labels[event.event_id].reasons) or "none",
            **{method: "commit" if decisions[event.event_id][method] else "reject" for method in METHODS},
        }
        for event in events
    ]
    _write_csv(output / "candidate_ood_offline.csv", candidate_rows)
    _write_csv(output / "ood_main.csv", _metric_rows(events, decisions, labels))
    _write_csv(output / "mechanism_family_holdout.csv", _family_rows(events, decisions, labels))
    return output


def main() -> None:
    root = _repository_root()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", required=True, choices=("bootstrap", "online", "offline"))
    parser.add_argument("--manifest", default=str(root / "configs" / "ood_challenge_v1_manifest.json"))
    parser.add_argument("--offline-config", default=str(root / "configs" / "ood_challenge_v1_offline.json"))
    parser.add_argument("--output-dir", default=str(root / "artifacts_ood" / "ood-challenge-v1"))
    args = parser.parse_args()
    if args.phase == "bootstrap":
        create_protocol_files(root, public_path=args.manifest, offline_path=args.offline_config)
    elif args.phase == "online":
        run_online(args.manifest, args.output_dir)
    else:
        run_offline(args.manifest, args.offline_config, args.output_dir)


if __name__ == "__main__":
    main()
