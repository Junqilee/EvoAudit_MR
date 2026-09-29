"""Execute the frozen formal multi-round experiment in online/offline phases."""

from __future__ import annotations

import argparse
import csv
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping

from evoaudit_mr.evolution.engine import METHODS, advance, initial_state
from evoaudit_mr.evolution.scenario import build_scenarios
from evoaudit_mr.formal.protocol import (
    ProtocolError,
    complete_online_phase,
    load_json,
    manifest_digest,
    require_online_complete,
    validate_offline_reveal,
)
from evoaudit_mr.records.certificate import write_certificate


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _contracts(root: Path, manifest: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        env: json.loads((root / path).read_text(encoding="utf-8"))
        for env, path in manifest["environment_contracts"].items()
    }


def _hash_online(root: Path) -> str:
    hasher = sha256()
    for directory in ("trajectories", "versions", "static", "certificates"):
        base = root / directory
        if not base.exists():
            raise ProtocolError(f"Missing online artifact directory: {directory}.")
        for pattern in ("*.jsonl", "*.json"):
            for path in sorted(base.rglob(pattern)):
                hasher.update(path.relative_to(root).as_posix().encode("utf-8"))
                hasher.update(path.read_bytes())
    return hasher.hexdigest()


def _append(path: Path, row: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(dict(row), sort_keys=True) + "\n")


def run_online(manifest_path: str | Path, output_dir: str | Path) -> Path:
    manifest = load_json(manifest_path)
    digest = manifest_digest(manifest)
    target = Path(output_dir)
    if target.exists() and any(target.iterdir()):
        raise FileExistsError("Multi-round online output directory must be new and empty.")
    target.mkdir(parents=True, exist_ok=True)
    root = _repository_root()
    contracts = _contracts(root, manifest)
    seeds = tuple(manifest["trajectory_seeds"])
    rounds = int(manifest["rounds"])
    total_records = 0
    for environment in ("AliasTool", "SwitchRule", "PermissionPath"):
        for trajectory_seed in seeds:
            scenarios = build_scenarios(environment, trajectory_seed=int(trajectory_seed), rounds=rounds)
            for method in METHODS:
                state = initial_state(environment, trajectory_seed=int(trajectory_seed))
                for scenario in scenarios:
                    state, record = advance(state, scenario, method=method, contract=contracts[environment])
                    _append(target / "trajectories" / method / f"{environment}-{trajectory_seed}.jsonl", record.to_dict())
                    _append(target / "versions" / method / f"{environment}-{trajectory_seed}.jsonl", state.working.to_dict())
                    write_certificate(
                        target / "certificates",
                        record.event,
                        record.decision,
                        manifest_hash=digest,
                        run_id=f"multiround-v1-{digest[:12]}-{environment}-{trajectory_seed}",
                    )
                    total_records += 1
                # Static is scored offline from the recorded initial version specification.
                _append(
                    target / "static" / f"{environment}-{trajectory_seed}.jsonl",
                    initial_state(environment, trajectory_seed=int(trajectory_seed)).working.to_dict(),
                )
    complete_online_phase(
        target,
        manifest_hash=digest,
        event_count=total_records,
        online_record_hash=_hash_online(target),
    )
    return target


def _load_version_row(row: Mapping[str, Any]):
    from evoaudit_mr.evolution.state import AgentVersion
    from evoaudit_mr.types import Harness

    harness = Harness(
        adapter_name=row["harness"]["adapter_name"],
        prompt_strategy=row["harness"]["prompt_strategy"],
        memory_skills=tuple(row["harness"]["memory_skills"]),
        workflow=row["harness"]["workflow"],
        prompt_rules=tuple(row["harness"].get("prompt_rules", [])),
        tool_adapters=tuple(row["harness"].get("tool_adapters", [])),
        workflow_steps=tuple(row["harness"].get("workflow_steps", [])),
    )
    return AgentVersion(
        version_id=row["version_id"],
        parent_version_id=row["parent_version_id"],
        environment=row["environment"],
        harness=harness,
        applied_patch_ids=tuple(row["applied_patch_ids"]),
        created_round=int(row["created_round"]),
    )


def _load_final_state(path: Path):
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    if not rows:
        raise ProtocolError(f"Missing version history: {path}")
    return _load_version_row(rows[-1])


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def run_offline(manifest_path: str | Path, offline_path: str | Path, output_dir: str | Path) -> Path:
    manifest = load_json(manifest_path)
    offline = load_json(offline_path)
    digest = manifest_digest(manifest)
    target = Path(output_dir)
    expected_count = 3 * len(manifest["trajectory_seeds"]) * int(manifest["rounds"]) * len(METHODS)
    marker = require_online_complete(target, expected_manifest_hash=digest, expected_event_count=expected_count)
    if marker["online_record_hash"] != _hash_online(target):
        raise ProtocolError("Multi-round online records changed after completion.")
    root = _repository_root()
    contracts = _contracts(root, manifest)
    from evoaudit_mr.formal.offline import hidden_generator_source

    validate_offline_reveal(
        manifest,
        offline,
        generator_source=hidden_generator_source(),
        environment_contracts=contracts,
    )
    from evoaudit_mr.evolution.offline import evaluate_final, shared_final_exam
    from evoaudit_mr.formal.offline import evaluate_formal_event
    from evoaudit_mr.types import CandidateEvent, Harness, Patch

    final_rows: list[dict[str, object]] = []
    round_label_rows: list[dict[str, object]] = []
    if (target / "final_hidden").exists():
        raise FileExistsError("Final hidden artifacts already exist.")
    for environment in ("AliasTool", "SwitchRule", "PermissionPath"):
        for trajectory_seed in manifest["trajectory_seeds"]:
            exam = shared_final_exam(
                environment,
                trajectory_seed=int(trajectory_seed),
                master_key=str(offline["hidden_master_seed"]),
                manifest_hash=digest,
                per_bucket=int(manifest["final_hidden_tasks_per_bucket"]),
            )
            # Score working@T for all online gates and the common static baseline.
            for method in (*METHODS, "static"):
                if method == "static":
                    version = _load_final_state(target / "static" / f"{environment}-{trajectory_seed}.jsonl")
                    checkpoint = "working@0"
                else:
                    version = _load_final_state(target / "versions" / method / f"{environment}-{trajectory_seed}.jsonl")
                    checkpoint = "working@T"
                result = evaluate_final(version, exam)
                result.update({"method": method, "checkpoint": checkpoint})
                final_rows.append(result)
                _append(target / "final_hidden" / f"{method}.jsonl", result)
                if method != "static":
                    records = [
                        json.loads(line)
                        for line in (target / "trajectories" / method / f"{environment}-{trajectory_seed}.jsonl")
                        .read_text(encoding="utf-8")
                        .splitlines()
                    ]
                    for record in records:
                        patch_data = record["patch"]
                        event = CandidateEvent(
                            event_id=str(record["event_id"]),
                            parent=Harness(
                                adapter_name=record["parent_harness"]["adapter_name"],
                                prompt_strategy=record["parent_harness"]["prompt_strategy"],
                                memory_skills=tuple(record["parent_harness"]["memory_skills"]),
                                workflow=record["parent_harness"]["workflow"],
                                prompt_rules=tuple(record["parent_harness"].get("prompt_rules", [])),
                                tool_adapters=tuple(record["parent_harness"].get("tool_adapters", [])),
                                workflow_steps=tuple(record["parent_harness"].get("workflow_steps", [])),
                            ),
                            patch=Patch(
                                patch_id=patch_data["patch_id"],
                                patch_type=patch_data["type"],
                                claimed_target=patch_data["claimed_target"],
                                claimed_scope=tuple(patch_data["claimed_scope"]),
                                diff=patch_data["diff"],
                                candidate_adapter=patch_data["candidate_adapter"],
                                evidence_trace_ids=tuple(patch_data["evidence_trace_ids"]),
                                rationale=patch_data["rationale"],
                            ),
                            visible_tasks=(),
                            heldout_tasks=(),
                            environment=environment,
                        )
                        label = evaluate_formal_event(
                            event,
                            master_key=str(offline["hidden_master_seed"]),
                            manifest_hash=digest,
                            per_bucket=int(offline["hidden_config"]["per_bucket"]),
                        )
                        row = {
                            "method": method,
                            "environment": environment,
                            "trajectory_seed": trajectory_seed,
                            "round_index": record["round_index"],
                            "event_id": record["event_id"],
                            "committed": record["decision"] == "commit",
                            "hidden_reliable": label.reliable,
                            "hidden_reasons": ";".join(label.reasons) or "none",
                        }
                        round_label_rows.append(row)
                        _append(target / "offline_hidden" / "round_labels.jsonl", row)
            # RSEA frozen-best is an additional, pre-registered checkpoint.
            rsea_rows = [json.loads(line) for line in (target / "versions" / "rsea_fixed_validation" / f"{environment}-{trajectory_seed}.jsonl").read_text(encoding="utf-8").splitlines()]
            # In this compact runner the best version is stored in trajectory records; load matching working snapshot.
            records = [json.loads(line) for line in (target / "trajectories" / "rsea_fixed_validation" / f"{environment}-{trajectory_seed}.jsonl").read_text(encoding="utf-8").splitlines()]
            desired = next((record.get("rsea_best_version_id") for record in reversed(records) if record.get("rsea_best_version_id")), rsea_rows[-1]["version_id"])
            candidate_rows = [row for row in rsea_rows if row["version_id"] == desired]
            fallback = json.loads((target / "static" / f"{environment}-{trajectory_seed}.jsonl").read_text(encoding="utf-8").splitlines()[0])
            best_version = _load_version_row(candidate_rows[-1] if candidate_rows else fallback)
            result = evaluate_final(best_version, exam)
            result.update({"method": "rsea_fixed_validation", "checkpoint": "frozen_best"})
            final_rows.append(result)
            _append(target / "final_hidden" / "rsea_frozen_best.jsonl", result)
    summary: list[dict[str, object]] = []
    for method in (*METHODS, "static"):
        for checkpoint in sorted({str(row["checkpoint"]) for row in final_rows if row["method"] == method}):
            rows = [row for row in final_rows if row["method"] == method and row["checkpoint"] == checkpoint]
            summary.append({
                "method": method,
                "checkpoint": checkpoint,
                "n_trajectories": len(rows),
                "overall_success": sum(float(row["overall_success"]) for row in rows) / len(rows),
                "target_success": sum(float(row["target_success"]) for row in rows) / len(rows),
                "replay_success": sum(float(row["replay_success"]) for row in rows) / len(rows),
                "unsafe_probe_rate": sum(float(row["unsafe_probe_rate"]) for row in rows) / len(rows),
                "safety_event_density": sum(float(row["safety_event_density"]) for row in rows) / len(rows),
            })
    _write_csv(target / "multiround_main.csv", summary)
    trajectory_rows: list[dict[str, object]] = []
    for method in METHODS:
        for environment in ("AliasTool", "SwitchRule", "PermissionPath"):
            for trajectory_seed in manifest["trajectory_seeds"]:
                rows = [
                    row
                    for row in round_label_rows
                    if row["method"] == method
                    and row["environment"] == environment
                    and row["trajectory_seed"] == trajectory_seed
                ]
                commits = [row for row in rows if row["committed"]]
                reliable = [row for row in rows if row["hidden_reliable"]]
                trajectory_rows.append({
                    "method": method,
                    "environment": environment,
                    "trajectory_seed": trajectory_seed,
                    "n_rounds": len(rows),
                    "commits": len(commits),
                    "cumulative_false_commits": sum(not row["hidden_reliable"] for row in commits),
                    "reliable_update_retention": (
                        sum(row["committed"] for row in reliable) / len(reliable) if reliable else "NA"
                    ),
                    "cumulative_audit_pairs": max(
                        int(record.get("cumulative_audit_pairs", 0))
                        for record in [
                            json.loads(line)
                            for line in (target / "trajectories" / method / f"{environment}-{trajectory_seed}.jsonl")
                            .read_text(encoding="utf-8")
                            .splitlines()
                        ]
                    ),
                    "cumulative_audit_tool_calls": max(
                        int(record.get("cumulative_audit_tool_calls", 0))
                        for record in [
                            json.loads(line)
                            for line in (target / "trajectories" / method / f"{environment}-{trajectory_seed}.jsonl")
                            .read_text(encoding="utf-8")
                            .splitlines()
                        ]
                    ),
                })
    _write_csv(target / "trajectory_summary.csv", trajectory_rows)
    return target


def main() -> None:
    root = _repository_root()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", required=True, choices=("online", "offline"))
    parser.add_argument("--manifest", default=str(root / "configs" / "multiround_v1_manifest.json"))
    parser.add_argument("--offline-config", default=str(root / "configs" / "formal_v1_offline.json"))
    parser.add_argument("--output-dir", default=str(root / "artifacts_multiround" / "multiround-v1"))
    args = parser.parse_args()
    if args.phase == "online":
        run_online(args.manifest, args.output_dir)
    else:
        run_offline(args.manifest, args.offline_config, args.output_dir)


if __name__ == "__main__":
    main()
