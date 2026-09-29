"""Recompute corrected paper statistics from sealed Stage-4 artifacts.

``formal-v1-final2`` and ``multiround-v1-final2`` are immutable experimental
records.  This runner is deliberately analysis-only: it corrects two reporting
definitions without rerunning gates or changing a decision, certificate,
commitment, hidden label, or trajectory.

1. Matched-commit thinning evaluates sampled commits over all 180 candidates;
   every unselected candidate is a reject.
2. Safety is reported as both unsafe-probe rate and safety-event density.
"""

from __future__ import annotations

import argparse
import csv
from hashlib import sha256
import json
from pathlib import Path
import random
from statistics import mean
from typing import Any, Iterable, Mapping

from evoaudit_mr.formal.metrics import Confusion, confusion_from_pairs


ANALYSIS_VERSION = "stage4-results-correction-v1"
BOOTSTRAP_SEED = 2027
BOOTSTRAP_SAMPLES = 1_000


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _fmt(value: float | str | None) -> str:
    if value is None:
        return "NA"
    return value if isinstance(value, str) else f"{value:.3f}"


def _quantile(values: Iterable[float], quantile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("Cannot compute a quantile of an empty sequence.")
    return ordered[min(len(ordered) - 1, int(quantile * len(ordered)))]


def _formal_labels(formal_dir: Path) -> dict[str, dict[str, Any]]:
    labels: dict[str, dict[str, Any]] = {}
    for row in _jsonl(formal_dir / "offline_hidden" / "events.jsonl"):
        labels[str(row["event_id"])] = dict(row["hidden_label"])
    if len(labels) != 180:
        raise ValueError(f"Expected 180 sealed hidden labels, found {len(labels)}.")
    return labels


def corrected_thinning_rows(
    labels: Mapping[str, Mapping[str, Any]],
    thinning_payload: Mapping[str, Any],
) -> list[dict[str, object]]:
    """Compute each frozen thinning sample over the complete candidate universe."""
    all_event_ids = set(labels)
    rows: list[dict[str, object]] = []
    for baseline, comparison in thinning_payload["comparisons"].items():
        for sample in comparison["samples"]:
            selected_by_method = {
                baseline: set(sample["baseline_event_ids"]),
                "evoaudit_mr": set(sample["evoaudit_event_ids"]),
            }
            for method, committed_ids in selected_by_method.items():
                if not committed_ids.issubset(all_event_ids):
                    raise ValueError("A frozen thinning sample contains an unknown event id.")
                confusion = confusion_from_pairs(
                    (
                        event_id in committed_ids,
                        bool(labels[event_id]["reliable"]),
                        "safety_invariant_failed" in labels[event_id].get("reasons", []),
                    )
                    for event_id in sorted(all_event_ids)
                )
                rows.append(
                    {
                        "comparison": baseline,
                        "analysis_seed": int(sample["seed"]),
                        "method": method,
                        "n_events": len(all_event_ids),
                        "n_committed": len(committed_ids),
                        **confusion.to_dict(),
                    }
                )
    return rows


def thinning_summary(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    """Summarize the 1,000 pre-frozen selections with mean and percentile CI."""
    groups: dict[tuple[str, str], list[dict[str, object]]] = {}
    for row in rows:
        groups.setdefault((str(row["comparison"]), str(row["method"])), []).append(row)
    summary: list[dict[str, object]] = []
    for (comparison, method), samples in sorted(groups.items()):
        for metric in ("far", "fdr", "ap", "uur", "svr"):
            values = [float(row[metric]) for row in samples if row[metric] is not None]
            summary.append(
                {
                    "comparison": comparison,
                    "method": method,
                    "metric": metric,
                    "n_samples": len(values),
                    "mean": mean(values) if values else "NA",
                    "ci_low": _quantile(values, 0.025) if values else "NA",
                    "ci_high": _quantile(values, 0.975) if values else "NA",
                }
            )
    return summary


def safety_metrics_from_final_row(row: Mapping[str, Any]) -> dict[str, object]:
    """Recompute bounded unsafe-probe rate and event density from raw outcomes."""
    safety_outcomes = [
        item["outcome"] for item in row["probes"] if item["probe"]["bucket"] == "safety"
    ]
    if not safety_outcomes:
        raise ValueError("Final-exam row has no safety probes.")
    unsafe_probe_count = sum(bool(outcome["safety_events"]) for outcome in safety_outcomes)
    event_count = sum(len(outcome["safety_events"]) for outcome in safety_outcomes)
    return {
        "unsafe_probe_count": unsafe_probe_count,
        "safety_event_count": event_count,
        "n_safety_probes": len(safety_outcomes),
        "unsafe_probe_rate": unsafe_probe_count / len(safety_outcomes),
        "safety_event_density": event_count / len(safety_outcomes),
    }


def corrected_final_rows(multiround_dir: Path) -> list[dict[str, object]]:
    filenames = {
        "direct_commit": "direct_commit.jsonl",
        "rsea_fixed_validation": "rsea_fixed_validation.jsonl",
        "fixed_random_audit": "fixed_random_audit.jsonl",
        "evoaudit_mr": "evoaudit_mr.jsonl",
        "static": "static.jsonl",
        "rsea_frozen_best": "rsea_frozen_best.jsonl",
    }
    rows: list[dict[str, object]] = []
    for artifact_method, filename in filenames.items():
        for raw in _jsonl(multiround_dir / "final_hidden" / filename):
            checkpoint = str(raw["checkpoint"])
            method = "rsea_fixed_validation" if artifact_method == "rsea_frozen_best" else str(raw["method"])
            rows.append(
                {
                    "artifact_method": artifact_method,
                    "method": method,
                    "checkpoint": checkpoint,
                    "environment": str(raw["environment"]),
                    "trajectory_seed": int(raw["trajectory_seed"]),
                    "overall_success": float(raw["overall_success"]),
                    "target_success": float(raw["target_success"]),
                    "replay_success": float(raw["replay_success"]),
                    "safety_success": float(raw["safety_success"]),
                    **safety_metrics_from_final_row(raw),
                }
            )
    return rows


def final_summary(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    groups: dict[tuple[str, str], list[dict[str, object]]] = {}
    for row in rows:
        groups.setdefault((str(row["method"]), str(row["checkpoint"])), []).append(row)
    summary: list[dict[str, object]] = []
    for (method, checkpoint), group in groups.items():
        summary.append(
            {
                "method": method,
                "checkpoint": checkpoint,
                "n_shared_scenarios": len(group),
                "n_method_trajectories": len(group),
                "overall_success": mean(float(row["overall_success"]) for row in group),
                "target_success": mean(float(row["target_success"]) for row in group),
                "replay_success": mean(float(row["replay_success"]) for row in group),
                "unsafe_probe_rate": mean(float(row["unsafe_probe_rate"]) for row in group),
                "safety_event_density": mean(float(row["safety_event_density"]) for row in group),
            }
        )
    return summary


def paired_bootstrap_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    evo = [
        row for row in rows if row["method"] == "evoaudit_mr" and row["checkpoint"] == "working@T"
    ]
    baselines = {
        "direct_commit (working@T)": [
            row for row in rows if row["method"] == "direct_commit" and row["checkpoint"] == "working@T"
        ],
        "RSEA-style (working@T)": [
            row for row in rows if row["method"] == "rsea_fixed_validation" and row["checkpoint"] == "working@T"
        ],
        "RSEA-style (frozen-best)": [
            row for row in rows if row["method"] == "rsea_fixed_validation" and row["checkpoint"] == "frozen_best"
        ],
        "fixed_random_audit (working@T)": [
            row for row in rows if row["method"] == "fixed_random_audit" and row["checkpoint"] == "working@T"
        ],
    }
    evo_by_key = {(row["environment"], row["trajectory_seed"]): row for row in evo}
    rng = random.Random(BOOTSTRAP_SEED)
    output: list[dict[str, object]] = []
    for name, baseline in baselines.items():
        baseline_by_key = {(row["environment"], row["trajectory_seed"]): row for row in baseline}
        keys = sorted(set(evo_by_key).intersection(baseline_by_key))
        if len(keys) != 30:
            raise ValueError(f"Expected 30 paired shared scenarios for {name}, got {len(keys)}.")
        for metric in (
            "overall_success",
            "target_success",
            "replay_success",
            "unsafe_probe_rate",
            "safety_event_density",
        ):
            deltas = [
                float(evo_by_key[key][metric]) - float(baseline_by_key[key][metric])
                for key in keys
            ]
            samples = [
                mean(deltas[rng.randrange(len(deltas))] for _ in deltas)
                for _ in range(BOOTSTRAP_SAMPLES)
            ]
            output.append(
                {
                    "comparison": f"EvoAudit-MR minus {name}",
                    "metric": metric,
                    "n_paired_shared_scenarios": len(keys),
                    "estimate": mean(deltas),
                    "ci_low": _quantile(samples, 0.025),
                    "ci_high": _quantile(samples, 0.975),
                    "bootstrap_samples": BOOTSTRAP_SAMPLES,
                    "seed": BOOTSTRAP_SEED,
                }
            )
    return output


def _render_report(
    thinning: list[dict[str, object]],
    final: list[dict[str, object]],
    bootstrap: list[dict[str, object]],
) -> str:
    lines = [
        "# EvoAudit-MR corrected Stage-4 results",
        "",
        "This report is analysis-only. It recomputes statistics from sealed `final2` artifacts and does not change an online decision, certificate, hidden label, or trajectory.",
        "",
        "## Statistical units",
        "",
        "- Candidate-level inference: 180 events grouped into **30 independent mechanism clusters** (six parameter instances per cluster).",
        "- Multi-round inference: **30 shared `(environment, seed)` scenarios**. Four gates yield 120 method trajectories and 1,200 round records; the paired bootstrap uses the 30 shared scenarios, not rounds as independent samples.",
        "",
        "## Corrected matched-commit thinning",
        "",
        "Each of the 1,000 frozen thinning samples marks the selected updates as commits and all other candidates in the full 180-event universe as rejects. FAR and UUR therefore retain their intended denominators.",
        "",
        "| Baseline comparison | Method | FAR mean [95% CI] | UUR mean [95% CI] |",
        "| --- | --- | --- | --- |",
    ]
    grouped = {(str(row["comparison"]), str(row["method"]), str(row["metric"])): row for row in thinning}
    comparisons = sorted({str(row["comparison"]) for row in thinning})
    for comparison in comparisons:
        for method in (comparison, "evoaudit_mr"):
            far = grouped[(comparison, method, "far")]
            uur = grouped[(comparison, method, "uur")]
            lines.append(
                f"| {comparison} | {method} | {_fmt(far['mean'])} [{_fmt(far['ci_low'])}, {_fmt(far['ci_high'])}] | "
                f"{_fmt(uur['mean'])} [{_fmt(uur['ci_low'])}, {_fmt(uur['ci_high'])}] |"
            )
    lines.extend([
        "",
        "## Corrected multi-round safety metrics",
        "",
        "`unsafe_probe_rate` is the fraction of safety probes with at least one violation and lies in [0, 1]. `safety_event_density` is the mean number of violation events per safety probe and may exceed one.",
        "",
        "| Method | Checkpoint | Overall | Target | Replay | Unsafe-probe rate | Safety-event density |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ])
    for row in final:
        lines.append(
            f"| {row['method']} | {row['checkpoint']} | {_fmt(row['overall_success'])} | "
            f"{_fmt(row['target_success'])} | {_fmt(row['replay_success'])} | "
            f"{_fmt(row['unsafe_probe_rate'])} | {_fmt(row['safety_event_density'])} |"
        )
    lines.extend([
        "",
        "## Paired bootstrap: EvoAudit-MR minus baseline",
        "",
        "| Baseline | Metric | Estimate | 95% CI |",
        "| --- | --- | ---: | --- |",
    ])
    for row in bootstrap:
        lines.append(
            f"| {str(row['comparison']).replace('EvoAudit-MR minus ', '')} | {row['metric']} | "
            f"{_fmt(row['estimate'])} | [{_fmt(row['ci_low'])}, {_fmt(row['ci_high'])}] |"
        )
    return "\n".join(lines) + "\n"


def run(*, formal_dir: str | Path, multiround_dir: str | Path, output_dir: str | Path) -> Path:
    """Write a new, versioned results layer from sealed Stage-4 artifacts."""
    formal = Path(formal_dir)
    multiround = Path(multiround_dir)
    output = Path(output_dir)
    if output.exists() and any(output.iterdir()):
        raise FileExistsError("Corrected-results output directory must be new and empty.")
    output.mkdir(parents=True, exist_ok=True)
    labels = _formal_labels(formal)
    thinning_payload = json.loads((formal / "THINNING_COMPLETE.json").read_text(encoding="utf-8"))
    thinning_raw = corrected_thinning_rows(labels, thinning_payload)
    thinning = thinning_summary(thinning_raw)
    final_rows = corrected_final_rows(multiround)
    final = final_summary(final_rows)
    bootstrap = paired_bootstrap_rows(final_rows)
    _write_csv(output / "thinning_corrected_samples.csv", thinning_raw)
    _write_csv(output / "thinning_corrected_summary.csv", thinning)
    _write_csv(output / "multiround_final_corrected_by_scenario.csv", final_rows)
    _write_csv(output / "multiround_final_corrected_summary.csv", final)
    _write_csv(output / "multiround_paired_bootstrap_corrected.csv", bootstrap)
    metadata = {
        "analysis_version": ANALYSIS_VERSION,
        "formal_source": str(formal),
        "multiround_source": str(multiround),
        "formal_online_complete_sha256": sha256((formal / "ONLINE_COMPLETE.json").read_bytes()).hexdigest(),
        "formal_hidden_events_sha256": sha256((formal / "offline_hidden" / "events.jsonl").read_bytes()).hexdigest(),
        "multiround_online_complete_sha256": sha256((multiround / "ONLINE_COMPLETE.json").read_bytes()).hexdigest(),
        "analysis_only": True,
        "corrections": [
            "matched_commit_thinning_uses_full_180_event_universe",
            "safety_violation_rate_split_into_unsafe_probe_rate_and_safety_event_density",
            "multi_round_statistical_unit_is_30_shared_environment_seed_scenarios",
        ],
    }
    (output / "RESULTS_CORRECTION.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (output / "paper_results_corrected.md").write_text(
        _render_report(thinning, final, bootstrap), encoding="utf-8"
    )
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--formal-dir", required=True)
    parser.add_argument("--multiround-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    run(
        formal_dir=args.formal_dir,
        multiround_dir=args.multiround_dir,
        output_dir=args.output_dir,
    )


if __name__ == "__main__":
    main()
