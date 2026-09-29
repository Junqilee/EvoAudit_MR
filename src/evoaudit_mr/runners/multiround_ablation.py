"""Five-seed multi-round component ablations for the EvoAudit-MR appendix.

This is deliberately a separate runner from the sealed primary multi-round
experiment.  It shares the frozen public scenarios and offline final exam but
does not rewrite any main-run trajectory, commitment, or hidden artifact.
"""

from __future__ import annotations

import argparse
import csv
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping

from evoaudit_mr.evolution.engine import SUPPLEMENTARY_ABLATION_METHODS, advance, initial_state
from evoaudit_mr.evolution.offline import evaluate_final, shared_final_exam
from evoaudit_mr.evolution.scenario import build_scenarios
from evoaudit_mr.evolution.state import AgentVersion
from evoaudit_mr.formal.offline import evaluate_formal_event
from evoaudit_mr.formal.protocol import (
    ProtocolError,
    load_json,
    manifest_digest,
    validate_offline_reveal,
)
from evoaudit_mr.types import CandidateEvent


ANALYSIS_VERSION = "multiround-ablation-v1"
SEEDS = (1, 2, 3, 4, 5)
ENVIRONMENTS = ("AliasTool", "SwitchRule", "PermissionPath")


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _contracts(root: Path, manifest: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        environment: json.loads((root / path).read_text(encoding="utf-8"))
        for environment, path in manifest["environment_contracts"].items()
    }


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _mean(rows: list[dict[str, object]], key: str) -> float:
    return sum(float(row[key]) for row in rows) / len(rows)


def run(
    manifest_path: str | Path,
    offline_path: str | Path,
    *,
    output_dir: str | Path,
) -> Path:
    """Run 3 environments x 5 seeds x 10 rounds x 5 component variants."""
    manifest = load_json(manifest_path)
    offline = load_json(offline_path)
    root = _repository_root()
    contracts = _contracts(root, manifest)
    from evoaudit_mr.formal.offline import hidden_generator_source

    validate_offline_reveal(
        manifest,
        offline,
        generator_source=hidden_generator_source(),
        environment_contracts=contracts,
    )
    output = Path(output_dir)
    if output.exists() and any(output.iterdir()):
        raise FileExistsError("Multi-round ablation output directory must be new and empty.")
    output.mkdir(parents=True, exist_ok=True)
    digest = manifest_digest(manifest)
    metadata = {
        "analysis_version": ANALYSIS_VERSION,
        "source_manifest_hash": digest,
        "trajectory_seeds": list(SEEDS),
        "rounds": 10,
        "methods": list(SUPPLEMENTARY_ABLATION_METHODS),
        "note": "Separate appendix run; the sealed 10-seed primary multi-round artifacts are not modified.",
    }
    (output / "SUPPLEMENTARY_ANALYSIS.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    trajectory_rows: list[dict[str, object]] = []
    final_rows: list[dict[str, object]] = []
    for environment in ENVIRONMENTS:
        for trajectory_seed in SEEDS:
            scenarios = build_scenarios(environment, trajectory_seed=trajectory_seed, rounds=10)
            exam = shared_final_exam(
                environment,
                trajectory_seed=trajectory_seed,
                master_key=str(offline["hidden_master_seed"]),
                manifest_hash=digest,
                per_bucket=30,
            )
            for method in SUPPLEMENTARY_ABLATION_METHODS:
                state = initial_state(environment, trajectory_seed=trajectory_seed)
                commits = false_commits = reliable_candidates = reliable_commits = 0
                for scenario in scenarios:
                    state, record = advance(state, scenario, method=method, contract=contracts[environment])
                    label = evaluate_formal_event(
                        record.event,
                        master_key=str(offline["hidden_master_seed"]),
                        manifest_hash=digest,
                        per_bucket=int(offline["hidden_config"]["per_bucket"]),
                    )
                    reliable_candidates += int(label.reliable)
                    reliable_commits += int(record.committed and label.reliable)
                    commits += int(record.committed)
                    false_commits += int(record.committed and not label.reliable)
                    trajectory_rows.append(
                        {
                            "method": method,
                            "environment": environment,
                            "trajectory_seed": trajectory_seed,
                            "round_index": scenario.round_index,
                            "committed": record.committed,
                            "hidden_reliable": label.reliable,
                            "hidden_reasons": ";".join(label.reasons) or "none",
                            "logical_pairs": record.decision.bucket_summary["logical_pairs"],
                            "audit_tool_calls": record.audit_tool_calls,
                            "cumulative_audit_pairs": record.cumulative_audit_pairs,
                            "cumulative_audit_tool_calls": record.cumulative_audit_tool_calls,
                        }
                    )
                result = evaluate_final(state.working, exam)
                result.update(
                    {
                        "method": method,
                        "environment": environment,
                        "trajectory_seed": trajectory_seed,
                        "commits": commits,
                        "cumulative_false_commits": false_commits,
                        "reliable_update_retention": (
                            reliable_commits / reliable_candidates if reliable_candidates else "NA"
                        ),
                        "cumulative_audit_pairs": state.cumulative_pairs,
                        "cumulative_audit_tool_calls": state.cumulative_tool_calls,
                    }
                )
                final_rows.append(result)
    _write_csv(output / "round_labels.csv", trajectory_rows)
    _write_csv(output / "final_by_trajectory.csv", final_rows)
    summary: list[dict[str, object]] = []
    for method in SUPPLEMENTARY_ABLATION_METHODS:
        for environment in (*ENVIRONMENTS, "Overall"):
            rows = [
                row
                for row in final_rows
                if row["method"] == method and (environment == "Overall" or row["environment"] == environment)
            ]
            summary.append(
                {
                    "method": method,
                    "environment": environment,
                    "n_trajectories": len(rows),
                    "overall_success": _mean(rows, "overall_success"),
                    "target_success": _mean(rows, "target_success"),
                    "replay_success": _mean(rows, "replay_success"),
                    "unsafe_probe_rate": _mean(rows, "unsafe_probe_rate"),
                    "safety_event_density": _mean(rows, "safety_event_density"),
                    "mean_commits": _mean(rows, "commits"),
                    "mean_cumulative_false_commits": _mean(rows, "cumulative_false_commits"),
                    "mean_reliable_update_retention": _mean(
                        [row for row in rows if row["reliable_update_retention"] != "NA"],
                        "reliable_update_retention",
                    ),
                    "mean_cumulative_audit_pairs": _mean(rows, "cumulative_audit_pairs"),
                    "mean_cumulative_audit_tool_calls": _mean(rows, "cumulative_audit_tool_calls"),
                }
            )
    _write_csv(output / "multiround_ablations.csv", summary)
    return output


def main() -> None:
    root = _repository_root()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default=str(root / "configs" / "multiround_v1_manifest.json"))
    parser.add_argument("--offline-config", default=str(root / "configs" / "formal_v1_offline.json"))
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    run(args.manifest, args.offline_config, output_dir=args.output_dir)


if __name__ == "__main__":
    main()
