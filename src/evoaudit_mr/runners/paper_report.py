"""Create paper-ready tables and paired bootstrap CIs from immutable artifacts.

The runner is analysis-only.  It reads final CSV/JSONL artifacts and writes a
new report directory; no online or offline experimental record is changed.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import random
from typing import Any, Iterable


BOOTSTRAP_SEED = 2027
BOOTSTRAP_SAMPLES = 1_000


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _fmt(value: float | str) -> str:
    return value if isinstance(value, str) else f"{value:.3f}"


def _quantile(values: list[float], quantile: float) -> float:
    values = sorted(values)
    return values[min(len(values) - 1, int(quantile * len(values)))]


def _paired_bootstrap(
    candidate: list[dict[str, Any]],
    baseline: list[dict[str, Any]],
    *,
    metric: str,
    rng: random.Random,
) -> tuple[float, float, float]:
    keyed_candidate = {(row["environment"], int(row["trajectory_seed"])): row for row in candidate}
    keyed_baseline = {(row["environment"], int(row["trajectory_seed"])): row for row in baseline}
    keys = sorted(set(keyed_candidate).intersection(keyed_baseline))
    if not keys:
        raise ValueError("No shared trajectory keys for paired bootstrap.")
    deltas = [float(keyed_candidate[key][metric]) - float(keyed_baseline[key][metric]) for key in keys]
    mean = sum(deltas) / len(deltas)
    samples = []
    for _ in range(BOOTSTRAP_SAMPLES):
        sampled = [deltas[rng.randrange(len(deltas))] for _ in deltas]
        samples.append(sum(sampled) / len(sampled))
    return mean, _quantile(samples, 0.025), _quantile(samples, 0.975)


def _multiround_rows(directory: Path, filename: str) -> list[dict[str, Any]]:
    return _jsonl(directory / "final_hidden" / filename)


def run(
    *,
    formal_dir: str | Path,
    multiround_dir: str | Path,
    formal_appendix_dir: str | Path,
    multiround_ablation_dir: str | Path,
    output_dir: str | Path,
) -> Path:
    """Write tables and CIs from the specified immutable experiment artifacts."""
    formal = Path(formal_dir)
    multiround = Path(multiround_dir)
    appendix = Path(formal_appendix_dir)
    ablation = Path(multiround_ablation_dir)
    output = Path(output_dir)
    if output.exists() and any(output.iterdir()):
        raise FileExistsError("Paper-report output directory must be new and empty.")
    output.mkdir(parents=True, exist_ok=True)

    candidate = [row for row in _rows(formal / "formal_main.csv") if row["environment"] == "Overall"]
    budget = [row for row in _rows(appendix / "budget_scan.csv") if row["environment"] == "Overall"]
    candidate_ablation = [row for row in _rows(appendix / "ablations.csv") if row["environment"] == "Overall"]
    multi_summary = _rows(multiround / "multiround_main.csv")
    multi_ablation = [row for row in _rows(ablation / "multiround_ablations.csv") if row["environment"] == "Overall"]

    evo = _multiround_rows(multiround, "evoaudit_mr.jsonl")
    baselines = {
        "direct_commit (working@T)": _multiround_rows(multiround, "direct_commit.jsonl"),
        "RSEA-style (working@T)": _multiround_rows(multiround, "rsea_fixed_validation.jsonl"),
        "RSEA-style (frozen-best)": _multiround_rows(multiround, "rsea_frozen_best.jsonl"),
        "fixed_random_audit (working@T)": _multiround_rows(multiround, "fixed_random_audit.jsonl"),
    }
    rng = random.Random(BOOTSTRAP_SEED)
    bootstrap_rows: list[dict[str, object]] = []
    for comparison, baseline in baselines.items():
        for metric in (
            "overall_success",
            "target_success",
            "replay_success",
            "unsafe_probe_rate",
            "safety_event_density",
        ):
            estimate, ci_low, ci_high = _paired_bootstrap(evo, baseline, metric=metric, rng=rng)
            bootstrap_rows.append(
                {
                    "comparison": f"EvoAudit-MR minus {comparison}",
                    "metric": metric,
                    "n_paired_trajectories": len(evo),
                    "estimate": estimate,
                    "ci_low": ci_low,
                    "ci_high": ci_high,
                    "bootstrap_samples": BOOTSTRAP_SAMPLES,
                    "seed": BOOTSTRAP_SEED,
                }
            )
    _write_csv(output / "multiround_paired_bootstrap.csv", bootstrap_rows)

    lines = [
        "# EvoAudit-MR formal experiment report",
        "",
        "## Primary candidate-level result (sealed online run; offline hidden evaluation)",
        "",
        "| Method | TP | FP | TN | FN | FAR | FDR | UUR | SVR | Audit pairs | Tool calls |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in candidate:
        lines.append(
            "| {method} | {tp} | {fp} | {tn} | {fn} | {far} | {fdr} | {uur} | {svr} | {pairs} | {tools} |".format(
                method=row["method"], tp=row["tp"], fp=row["fp"], tn=row["tn"], fn=row["fn"],
                far=row["far"], fdr=row["fdr"], uur=row["uur"], svr=row["svr"],
                pairs=row["mean_logical_pairs"], tools=row["mean_tool_calls"],
            )
        )
    lines.extend([
        "",
        "The sealed main protocol uses six parent-candidate probe pairs. Cluster-bootstrap CIs are retained in `cluster_bootstrap.csv` in the formal artifact directory.",
        "",
        "## Primary multi-round result (30 shared scenarios; 120 method trajectories; shared 90-task hidden final exam)",
        "",
        "| Method | Checkpoint | Overall | Target | Replay | Unsafe-probe rate | Safety-event density |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ])
    for row in multi_summary:
        lines.append(
            "| {method} | {checkpoint} | {overall} | {target} | {replay} | {unsafe_rate} | {event_density} |".format(
                method=row["method"], checkpoint=row["checkpoint"], overall=_fmt(float(row["overall_success"])),
                target=_fmt(float(row["target_success"])), replay=_fmt(float(row["replay_success"])),
                unsafe_rate=_fmt(float(row["unsafe_probe_rate"])),
                event_density=_fmt(float(row["safety_event_density"])),
            )
        )
    lines.extend([
        "",
        "## Paired multi-round bootstrap: EvoAudit-MR minus baseline",
        "",
        "| Baseline | Metric | Estimate | 95% CI |",
        "| --- | --- | ---: | --- |",
    ])
    for row in bootstrap_rows:
        lines.append(
            f"| {row['comparison'].replace('EvoAudit-MR minus ', '')} | {row['metric']} | "
            f"{_fmt(float(row['estimate']))} | [{_fmt(float(row['ci_low']))}, {_fmt(float(row['ci_high']))}] |"
        )
    lines.extend([
        "",
        "## Appendix diagnostics (post-reveal, separate from primary sealed decisions)",
        "",
        "### Candidate-level budget scan",
        "",
        "| Budget | Method | FAR | UUR | Tool calls |",
        "| --- | --- | ---: | ---: | ---: |",
    ])
    for row in budget:
        lines.append(
            f"| {row['setting']} | {row['method']} | {row['far']} | {row['uur']} | {row['mean_tool_calls']} |"
        )
    lines.extend([
        "",
        "### Candidate-level component ablation (six pairs)",
        "",
        "| Variant | FAR | UUR | SVR |",
        "| --- | ---: | ---: | ---: |",
    ])
    for row in candidate_ablation:
        lines.append(f"| {row['method']} | {row['far']} | {row['uur']} | {row['svr']} |")
    lines.extend([
        "",
        "### Five-seed multi-round component ablation",
        "",
        "| Variant | Overall | Replay | Unsafe-probe rate | False commits |",
        "| --- | ---: | ---: | ---: | ---: |",
    ])
    for row in multi_ablation:
        lines.append(
            f"| {row['method']} | {_fmt(float(row['overall_success']))} | "
            f"{_fmt(float(row['replay_success']))} | {_fmt(float(row['unsafe_probe_rate']))} | "
            f"{_fmt(float(row['mean_cumulative_false_commits']))} |"
        )
    lines.extend([
        "",
        "The five-seed multi-round no-replay control is a null result in this curriculum: the target-MR strict-improvement requirement rejects the same replay-regressive proposals before the replay check changes the decision. This is reported as a boundary of the current sequence design, not converted into a positive component claim.",
        "",
        "All appendix tables are analysis-only and leave the primary online logs, certificates, phase locks, and hidden labels unchanged.",
    ])
    (output / "paper_results.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--formal-dir", required=True)
    parser.add_argument("--multiround-dir", required=True)
    parser.add_argument("--formal-appendix-dir", required=True)
    parser.add_argument("--multiround-ablation-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    run(
        formal_dir=args.formal_dir,
        multiround_dir=args.multiround_dir,
        formal_appendix_dir=args.formal_appendix_dir,
        multiround_ablation_dir=args.multiround_ablation_dir,
        output_dir=args.output_dir,
    )


if __name__ == "__main__":
    main()
