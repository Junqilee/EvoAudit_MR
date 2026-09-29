"""Run the reproducible Stage-3 AliasTool demonstration."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from evoaudit_mr.patches import PatchCatalogue, Trace2PatchStub
from evoaudit_mr.records.certificate import manifest_hash
from evoaudit_mr.runners.offline import offline_label
from evoaudit_mr.runners.online import online_decisions, persist_online_decisions
from evoaudit_mr.types import CandidateEvent, GateDecision


_METHODS = ("direct_commit", "fixed_heldout", "fixed_random_audit", "evoaudit_mr")


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _write_summary(output_dir: Path, rows: list[dict[str, Any]]) -> None:
    csv_path = output_dir / "summary.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        fields = [
            "patch_id",
            "hidden_truth",
            "hidden_reasons",
            "direct_commit",
            "fixed_heldout",
            "fixed_random_audit",
            "evoaudit_mr",
            "evoaudit_reasons",
        ]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    header = "| Patch | Hidden full audit | Direct | Fixed heldout | Fixed random | EvoAudit-MR | EvoAudit-MR reason |"
    divider = "| --- | --- | --- | --- | --- | --- | --- |"
    markdown_rows = [header, divider]
    for row in rows:
        markdown_rows.append(
            "| {patch_id} | {hidden_truth} | {direct_commit} | {fixed_heldout} | {fixed_random_audit} | {evoaudit_mr} | {evoaudit_reasons} |".format(
                **row
            )
        )
    (output_dir / "summary.md").write_text("\n".join(markdown_rows) + "\n", encoding="utf-8")


def _write_case(output_dir: Path, rows: list[dict[str, Any]], decisions: dict[str, dict[str, GateDecision]]) -> None:
    missed = next(
        row
        for row in rows
        if row["hidden_truth"] == "unreliable"
        and row["fixed_heldout"] == "commit"
        and row["evoaudit_mr"] == "reject"
    )
    patch_id = missed["patch_id"]
    evo_decision = decisions[patch_id]["evoaudit_mr"]
    detail_lines = [
        "# Fixed-heldout miss caught by EvoAudit-MR",
        "",
        f"- Patch: `{patch_id}`",
        f"- Hidden full-audit truth: **{missed['hidden_truth']}** ({missed['hidden_reasons']})",
        "- Fixed heldout decision: **commit**. It samples the same base distribution but does not condition on this patch.",
        f"- EvoAudit-MR decision: **reject** ({', '.join(evo_decision.reasons)}).",
        "",
        "## Online EvoAudit-MR evidence",
        "",
        "| Bucket | MR | Parent success | Candidate success | Candidate safety events |",
        "| --- | --- | ---: | ---: | --- |",
    ]
    for result in evo_decision.probe_results:
        detail_lines.append(
            "| {bucket} | {mr} | {parent} | {candidate} | {events} |".format(
                bucket=result.probe.bucket,
                mr=result.probe.mr_id,
                parent=int(result.parent.task_success),
                candidate=int(result.candidate.task_success),
                events=", ".join(result.candidate.safety_events) or "none",
            )
        )
    detail_lines.extend(
        [
            "",
            "The hidden audit is evaluated only after these online decisions. It is not available to the heldout gate or the EvoAudit-MR router.",
        ]
    )
    (output_dir / "case_fixed_holdout_missed.md").write_text("\n".join(detail_lines) + "\n", encoding="utf-8")


def _print_terminal_summary(rows: list[dict[str, Any]]) -> None:
    print("Stage-3 EvoAudit-MR prototype")
    for row in rows:
        print(
            f"  {row['patch_id']}: truth={row['hidden_truth']}; "
            f"heldout={row['fixed_heldout']}; evoaudit={row['evoaudit_mr']} "
            f"({row['evoaudit_reasons']})"
        )
    for method in _METHODS:
        false_accepts = sum(
            row[method] == "commit" and row["hidden_truth"] == "unreliable" for row in rows
        )
        commits = sum(row[method] == "commit" for row in rows)
        print(f"  {method}: commits={commits}; false_accepts={false_accepts}")


def run(manifest_path: str | Path, output_root: str | Path | None = None) -> Path:
    manifest_path = Path(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    root = _repository_root()
    candidate_path = root / manifest["candidate_specs"]
    contract_path = root / manifest["environment_contract"]
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    run_id = f"prototype-hardened-seed-{manifest['seed']}"
    output_dir = Path(output_root) if output_root else root / "artifacts_hardened" / run_id
    output_dir.mkdir(parents=True, exist_ok=True)

    # Never clear an arbitrary user-selected output directory. Only remove the
    # exact, reproducible files that this runner itself owns for this manifest.
    owned_files = (
        "events.jsonl",  # Stage-3 v1 migration artifact.
        "summary.csv",
        "summary.md",
        "case_fixed_holdout_missed.md",
    )
    for filename in owned_files:
        path = output_dir / filename
        if path.exists():
            path.unlink()

    catalogue = PatchCatalogue(candidate_path, seed=int(manifest["seed"]))
    stub = Trace2PatchStub()
    base_profiles = tuple(manifest["base_distribution"]["profiles"])
    events = catalogue.events(
        evolve_tasks=int(manifest["evolve_tasks_per_event"]),
        heldout_tasks=int(manifest["heldout_tasks_per_event"]),
        base_profiles=base_profiles,
        evolve_seed=int(manifest["evolve_seed"]),
        heldout_seed=int(manifest["heldout_seed"]),
    )
    hidden_event_log = output_dir / "offline_hidden" / "events.jsonl"
    if hidden_event_log.exists():
        hidden_event_log.unlink()
    for method in _METHODS:
        online_log = output_dir / method / "online" / "events.jsonl"
        if online_log.exists():
            online_log.unlink()
    manifest_digest = manifest_hash(manifest)
    rows: list[dict[str, Any]] = []
    decisions_by_patch: dict[str, dict[str, GateDecision]] = {}

    certificate_dir = output_dir / "certificates"  # Stage-3 v1 migration directory.
    for spec in json.loads(candidate_path.read_text(encoding="utf-8")):
        path = certificate_dir / f"{spec['candidate_id']}.json"
        if path.exists():
            path.unlink()

    for event in events:
        assert stub.propose(event) == event.patch
        decisions = online_decisions(event, manifest, contract)
        persist_online_decisions(
            output_dir,
            event,
            decisions,
            manifest_digest=manifest_digest,
            run_id=run_id,
        )
        label = offline_label(
            output_dir,
            event,
            per_bucket=int(manifest["hidden_probes_per_bucket"]),
            seed=int(manifest["seed"]),
        )
        row = {
            "patch_id": event.patch.patch_id,
            "hidden_truth": "reliable" if label.reliable else "unreliable",
            "hidden_reasons": ", ".join(label.reasons) or "none",
            **{method: decisions[method].decision for method in _METHODS},
            "evoaudit_reasons": ", ".join(decisions["evoaudit_mr"].reasons) or "none",
        }
        rows.append(row)
        decisions_by_patch[event.patch.patch_id] = decisions

    _write_summary(output_dir, rows)
    _write_case(output_dir, rows, decisions_by_patch)
    _print_terminal_summary(rows)
    return output_dir


def main() -> None:
    root = _repository_root()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        default=str(root / "configs" / "prototype_manifest.json"),
        help="Path to the frozen prototype manifest.",
    )
    parser.add_argument("--output-root", default=None, help="Optional artifact output directory.")
    args = parser.parse_args()
    run(args.manifest, args.output_root)


if __name__ == "__main__":
    main()
