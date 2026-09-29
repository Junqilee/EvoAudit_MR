"""Run the frozen Stage-4 candidate-level Pilot on AliasTool and SwitchRule.

Online admission decisions and hidden labels are written through separate
runners. This module joins them only after both computations have completed in
order to compute offline research metrics.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from evoaudit_mr.pilot import build_pilot_events
from evoaudit_mr.records.certificate import manifest_hash
from evoaudit_mr.runners.offline import offline_label
from evoaudit_mr.runners.online import online_decisions, persist_online_decisions
from evoaudit_mr.types import CandidateEvent, GateDecision


METHODS = ("direct_commit", "fixed_heldout", "fixed_random_audit", "evoaudit_mr")


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _load_contracts(root: Path, manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        environment: json.loads((root / relative_path).read_text(encoding="utf-8"))
        for environment, relative_path in manifest["environment_contracts"].items()
    }


def _clear_owned_outputs(output_dir: Path, events: tuple[CandidateEvent, ...]) -> None:
    """Remove only files this exact deterministic run owns; never clear a directory."""
    for filename in ("candidate_results.csv", "candidate_results.md", "main_results.csv", "main_results.md", "pilot_cases.md"):
        path = output_dir / filename
        if path.exists():
            path.unlink()
    hidden_log = output_dir / "offline_hidden" / "events.jsonl"
    if hidden_log.exists():
        hidden_log.unlink()
    for event in events:
        for method in METHODS:
            online_log = output_dir / method / "online" / "events.jsonl"
            if online_log.exists():
                online_log.unlink()
            certificate = output_dir / method / "certificates" / f"{event.patch.patch_id}.json"
            if certificate.exists():
                certificate.unlink()


def _bool_text(value: bool) -> str:
    return "yes" if value else "no"


def _candidate_rows(
    events: tuple[CandidateEvent, ...],
    decisions_by_event: dict[str, dict[str, GateDecision]],
    labels_by_event: dict[str, Any],
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for event in events:
        decisions = decisions_by_event[event.event_id]
        label = labels_by_event[event.event_id]
        rows.append(
            {
                "environment": event.environment,
                "patch_id": event.patch.patch_id,
                "archetype": str(event.patch.diff["archetype"]),
                "patch_type": event.patch.patch_type,
                "hidden_truth": "reliable" if label.reliable else "unreliable",
                "hidden_reasons": ", ".join(label.reasons) or "none",
                **{method: decisions[method].decision for method in METHODS},
                "evoaudit_reasons": ", ".join(decisions["evoaudit_mr"].reasons) or "none",
            }
        )
    return rows


def _rate(numerator: int, denominator: int) -> str:
    return "NA" if denominator == 0 else f"{numerator / denominator:.3f}"


def _metric_rows(
    events: tuple[CandidateEvent, ...],
    decisions_by_event: dict[str, dict[str, GateDecision]],
    labels_by_event: dict[str, Any],
) -> list[dict[str, str]]:
    grouped = {"AliasTool": [], "SwitchRule": [], "PermissionPath": [], "Overall": list(events)}
    for event in events:
        grouped[event.environment].append(event)
    rows: list[dict[str, str]] = []
    for environment, group in grouped.items():
        for method in METHODS:
            commits = [event for event in group if decisions_by_event[event.event_id][method].committed]
            reliable = [event for event in group if labels_by_event[event.event_id].reliable]
            false_accepts = [event for event in commits if not labels_by_event[event.event_id].reliable]
            true_accepts = [event for event in commits if labels_by_event[event.event_id].reliable]
            severe = [
                event
                for event in commits
                if "safety_invariant_failed" in labels_by_event[event.event_id].reasons
            ]
            logical_pairs = [
                int(decisions_by_event[event.event_id][method].bucket_summary.get("logical_pairs", 0))
                for event in group
            ]
            tool_calls = [
                (
                    sum(
                        len(result.parent.tool_calls) + len(result.candidate.tool_calls)
                        for result in decisions_by_event[event.event_id][method].probe_results
                    )
                    if int(decisions_by_event[event.event_id][method].bucket_summary.get("logical_pairs", 0)) > 0
                    else 0
                )
                for event in group
            ]
            rows.append(
                {
                    "environment": environment,
                    "method": method,
                    "n_events": str(len(group)),
                    "n_reliable": str(len(reliable)),
                    "commit_rate": _rate(len(commits), len(group)),
                    "far": _rate(len(false_accepts), len(commits)),
                    "acceptance_precision": _rate(len(true_accepts), len(commits)),
                    "uur": _rate(len(true_accepts), len(reliable)),
                    "svr": _rate(len(severe), len(commits)),
                    "mean_logical_pairs": f"{sum(logical_pairs) / len(logical_pairs):.1f}",
                    "mean_audit_tool_calls": f"{sum(tool_calls) / len(tool_calls):.1f}",
                }
            )
    return rows


def _write_csv_and_markdown(
    output_dir: Path,
    filename: str,
    rows: list[dict[str, str]],
    title: str,
) -> None:
    if not rows:
        return
    fields = list(rows[0])
    with (output_dir / f"{filename}.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    markdown = [f"# {title}", "", "| " + " | ".join(fields) + " |", "| " + " | ".join("---" for _ in fields) + " |"]
    markdown.extend("| " + " | ".join(row[field] for field in fields) + " |" for row in rows)
    (output_dir / f"{filename}.md").write_text("\n".join(markdown) + "\n", encoding="utf-8")


def _write_cases(
    output_dir: Path,
    candidate_rows: list[dict[str, str]],
    decisions_by_event: dict[str, dict[str, GateDecision]],
    labels_by_event: dict[str, Any],
) -> None:
    lines = ["# Fixed-heldout misses in the Stage-4 Pilot", ""]
    for environment in ("AliasTool", "SwitchRule", "PermissionPath"):
        candidate = next(
            row
            for row in candidate_rows
            if row["environment"] == environment
            and row["hidden_truth"] == "unreliable"
            and row["fixed_heldout"] == "commit"
            and row["evoaudit_mr"] == "reject"
        )
        patch_id = candidate["patch_id"]
        decision = decisions_by_event[f"event-{patch_id}"]["evoaudit_mr"]
        label = labels_by_event[f"event-{patch_id}"]
        lines.extend(
            [
                f"## {environment}: `{patch_id}`",
                "",
                f"- Hidden truth: **unreliable** ({', '.join(label.reasons)}).",
                "- Fixed heldout: **commit** on independent same-distribution tasks.",
                f"- EvoAudit-MR: **reject** ({', '.join(decision.reasons)}).",
                "",
                "| bucket | MR | parent success | candidate success | candidate safety events |",
                "| --- | --- | ---: | ---: | --- |",
            ]
        )
        for result in decision.probe_results:
            lines.append(
                f"| {result.probe.bucket} | {result.probe.mr_id} | {int(result.parent.task_success)} | "
                f"{int(result.candidate.task_success)} | {', '.join(result.candidate.safety_events) or 'none'} |"
            )
        lines.append("")
    lines.append("Hidden labels were created after all online decisions and are stored only in `offline_hidden/events.jsonl`.")
    (output_dir / "pilot_cases.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(manifest_path: str | Path, output_root: str | Path | None = None) -> Path:
    manifest_path = Path(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    root = _repository_root()
    run_id = f"stage4-candidate-pilot-seed-{manifest['seed']}"
    output_dir = Path(output_root) if output_root else root / "artifacts_pilot" / run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    events = build_pilot_events(
        repetitions=int(manifest["candidate_repetitions_per_archetype"]),
        evolve_tasks=int(manifest["evolve_tasks_per_event"]),
        heldout_tasks=int(manifest["heldout_tasks_per_event"]),
        evolve_seed=int(manifest["evolve_seed"]),
        heldout_seed=int(manifest["heldout_seed"]),
    )
    _clear_owned_outputs(output_dir, events)
    contracts = _load_contracts(root, manifest)
    digest = manifest_hash(manifest)
    decisions_by_event: dict[str, dict[str, GateDecision]] = {}
    labels_by_event: dict[str, Any] = {}

    for event in events:
        decisions = online_decisions(event, manifest, contracts[event.environment])
        persist_online_decisions(
            output_dir,
            event,
            decisions,
            manifest_digest=digest,
            run_id=run_id,
        )
        label = offline_label(
            output_dir,
            event,
            per_bucket=int(manifest["hidden_probes_per_bucket"]),
            seed=int(manifest["seed"]),
        )
        decisions_by_event[event.event_id] = decisions
        labels_by_event[event.event_id] = label

    candidate_rows = _candidate_rows(events, decisions_by_event, labels_by_event)
    metrics = _metric_rows(events, decisions_by_event, labels_by_event)
    _write_csv_and_markdown(output_dir, "candidate_results", candidate_rows, "Stage-4 candidate-level Pilot results")
    _write_csv_and_markdown(output_dir, "main_results", metrics, "Stage-4 candidate-level Pilot main results")
    _write_cases(output_dir, candidate_rows, decisions_by_event, labels_by_event)
    print(f"Stage-4 Pilot completed: {len(events)} candidate events")
    for row in metrics:
        if row["environment"] == "Overall":
            print(
                f"  {row['method']}: FAR={row['far']}, UUR={row['uur']}, "
                f"commit={row['commit_rate']}, SVR={row['svr']}, pairs={row['mean_logical_pairs']}"
            )
    return output_dir


def main() -> None:
    root = _repository_root()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        default=str(root / "configs" / "stage4_pilot_manifest.json"),
        help="Path to the frozen Stage-4 Pilot manifest.",
    )
    parser.add_argument("--output-root", default=None, help="Optional artifact output directory.")
    args = parser.parse_args()
    run(args.manifest, args.output_root)


if __name__ == "__main__":
    main()
