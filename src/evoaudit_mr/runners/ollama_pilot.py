"""Run the sealed Ollama LLM Proposal Pilot v2 in freeze/online/offline phases.

The online phase imports no hidden evaluator.  It has two deliberately
separate analyses: canonical-parent candidate selection and shared-proposal
persistent evolution with method-specific parents.
"""

from __future__ import annotations

import argparse
import csv
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping

from evoaudit_mr.audits.gate import fixed_heldout, fixed_random_audit
from evoaudit_mr.evaluation import mean_delta, paired_results
from evoaudit_mr.evolution.transforms import apply_patch
from evoaudit_mr.formal.audit import formal_evoaudit_mr, route_formal_probes
from evoaudit_mr.formal.catalogue import fixed_validation_tasks
from evoaudit_mr.formal.metrics import confusion_from_pairs
from evoaudit_mr.llm.compiler import ProposalCompilationError, compile_proposed_patch
from evoaudit_mr.llm.ollama import OllamaClient, OllamaClientError, OllamaCompletion
from evoaudit_mr.llm.ollama_freeze import freeze_ollama
from evoaudit_mr.llm.ollama_pilot_protocol import (
    OllamaPilotProtocolError,
    canonical_json,
    complete_online_phase,
    manifest_digest,
    require_online_phase,
    seal_artifacts,
    sha256_hex,
    source_hashes,
    validate_offline_commitments,
    validate_online_source_lock,
)
from evoaudit_mr.llm.proposal import ProposalValidationError, build_proposal_messages, parse_response_json
from evoaudit_mr.records.certificate import write_certificate
from evoaudit_mr.types import CandidateEvent, GateDecision, Harness, Patch, Probe


DYNAMIC_METHODS = ("direct_commit", "rsea_fixed_validation", "fixed_random_audit", "evoaudit_mr")
ALL_METHODS = (*DYNAMIC_METHODS, "static")
ENVIRONMENTS = ("AliasTool", "PermissionPath")
REQUIRED_PATCH_TYPES = {"AliasTool": "tool_adapter", "PermissionPath": "workflow"}
INITIAL_ADAPTERS = {"AliasTool": "broken_adapter", "PermissionPath": "broken_workflow_adapter"}


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _load_json(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise OllamaPilotProtocolError(f"Expected a JSON object at {path}.")
    return payload


def _append(path: Path, row: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(dict(row), sort_keys=True) + "\n")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _contracts(root: Path, manifest: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    raw = manifest.get("environment_contracts")
    if not isinstance(raw, Mapping):
        raise OllamaPilotProtocolError("Manifest lacks environment_contracts.")
    return {environment: _load_json(root / str(raw[environment])) for environment in ENVIRONMENTS}


def _initial_harness(environment: str) -> Harness:
    return Harness(adapter_name=INITIAL_ADAPTERS[environment])


def _task(environment: str, profile: str, index: int, *, prefix: str):
    if environment == "AliasTool":
        from evoaudit_mr.envs.aliastool import make_task

        return make_task(profile, index, task_id_prefix=prefix)
    if environment == "PermissionPath":
        from evoaudit_mr.envs.permissionpath import make_task

        return make_task(profile, index, task_id_prefix=prefix)
    raise ValueError(f"Unsupported environment: {environment}")


def _scenario_rows(manifest: Mapping[str, Any]) -> tuple[dict[str, object], ...]:
    schedules = manifest.get("public_failure_schedule")
    seeds = manifest.get("trajectory_seeds")
    rounds = int(manifest.get("rounds", 0))
    if not isinstance(schedules, Mapping) or not isinstance(seeds, list) or rounds != 5:
        raise OllamaPilotProtocolError("Pilot v2 requires three trajectory seeds and exactly five frozen rounds.")
    if len(seeds) != 3 or len(set(seeds)) != 3:
        raise OllamaPilotProtocolError("Pilot v2 requires exactly three distinct trajectory seeds.")
    rows: list[dict[str, object]] = []
    for environment in ENVIRONMENTS:
        families = schedules.get(environment)
        if not isinstance(families, list) or len(families) != rounds:
            raise OllamaPilotProtocolError(f"{environment} must specify five public failure-family entries.")
        for trajectory_seed in seeds:
            for round_index, family in enumerate(families, start=1):
                if not isinstance(family, Mapping) or not isinstance(family.get("profile"), str):
                    raise OllamaPilotProtocolError("Each public failure family must define a visible task profile.")
                slot_id = f"slot-{environment.lower()}-{int(trajectory_seed):03d}-{round_index:02d}"
                rows.append(
                    {
                        "slot_id": slot_id,
                        "environment": environment,
                        "trajectory_seed": int(trajectory_seed),
                        "round_index": round_index,
                        "failure_family": str(family.get("name", f"round_{round_index}")),
                        "visible_profile": str(family["profile"]),
                        "public_context_note": str(family.get("public_context_note", "")),
                    }
                )
    return tuple(rows)


def _visible_tasks(scenario: Mapping[str, object], *, count: int) -> tuple:
    base = int(scenario["trajectory_seed"]) * 10_000 + int(scenario["round_index"]) * 100
    return tuple(
        _task(
            str(scenario["environment"]),
            str(scenario["visible_profile"]),
            base + index,
            prefix=f"ollama-evolve-{scenario['slot_id']}",
        )
        for index in range(count)
    )


def _visible_trace(task, outcome, *, note: str) -> dict[str, object]:
    if hasattr(task, "public_record"):
        observation = {
            "tool_name": task.tool_name,
            "declared_tools": list(task.declared_tools),
            "request": {"sku": task.sku, "requested_units": task.requested_units},
            "rendered_tool_record": dict(task.public_record()),
            "public_note": note,
        }
    else:
        observation = {
            "operation": task.operation,
            "user_role": task.user_role,
            "authorized": task.authorized,
            "confirmed": task.confirmed,
            "tenant_match": task.tenant_match,
            "irreversible": task.irreversible,
            "public_note": note,
        }
    return {
        "trace_id": task.task_id,
        "observation": observation,
        "outcome": {
            "task_success": outcome.task_success,
            "answer": outcome.answer,
            "error": outcome.error,
            "safety_events": list(outcome.safety_events),
        },
    }


def _patch_from_dict(raw: Mapping[str, Any]) -> Patch:
    return Patch(
        patch_id=str(raw["patch_id"]),
        patch_type=str(raw["type"]),
        claimed_target=str(raw["claimed_target"]),
        claimed_scope=tuple(raw["claimed_scope"]),
        diff=dict(raw["diff"]),
        candidate_adapter=str(raw["candidate_adapter"]),
        evidence_trace_ids=tuple(raw.get("evidence_trace_ids", [])),
        rationale=str(raw.get("rationale", "")),
    )


def _harness_from_dict(raw: Mapping[str, Any]) -> Harness:
    return Harness(
        adapter_name=str(raw["adapter_name"]),
        prompt_strategy=str(raw.get("prompt_strategy", "inventory assistant")),
        memory_skills=tuple(raw.get("memory_skills", [])),
        workflow=str(raw.get("workflow", "query_then_answer")),
        prompt_rules=tuple(raw.get("prompt_rules", [])),
        tool_adapters=tuple(raw.get("tool_adapters", [])),
        workflow_steps=tuple(raw.get("workflow_steps", [])),
    )


def _canonical_event(ledger: Mapping[str, Any], *, visible_tasks: tuple, heldout_tasks: tuple) -> CandidateEvent:
    return CandidateEvent(
        event_id=f"candidate-{ledger['slot_id']}",
        parent=_harness_from_dict(ledger["canonical_parent"]),
        patch=_patch_from_dict(ledger["patch"]),
        visible_tasks=visible_tasks,
        heldout_tasks=heldout_tasks,
        environment=str(ledger["environment"]),
    )


def _method_event(parent: Harness, ledger: Mapping[str, Any], *, visible_tasks: tuple, heldout_tasks: tuple, method: str) -> CandidateEvent:
    return CandidateEvent(
        event_id=f"trajectory-{method}-{ledger['slot_id']}",
        parent=parent,
        patch=_patch_from_dict(ledger["patch"]),
        visible_tasks=visible_tasks,
        heldout_tasks=heldout_tasks,
        environment=str(ledger["environment"]),
    )


def _visible_precondition(event: CandidateEvent):
    probes = tuple(
        Probe(f"{event.event_id}-evolve-{index}", "visible", "evolve_target", task)
        for index, task in enumerate(event.visible_tasks)
    )
    results = paired_results(event, probes)
    delta = mean_delta(results)
    return results, delta, delta > 0


def _precondition_reject(method: str, event: CandidateEvent, visible_results, visible_delta: float) -> GateDecision:
    return GateDecision(
        method=method,
        event_id=event.event_id,
        decision="reject",
        reasons=("visible_target_not_improved",),
        probe_results=visible_results,
        bucket_summary={"visible_delta": visible_delta, "visible_target_improved": False, "logical_pairs": 0},
    )


def _direct_after_visible(event: CandidateEvent, visible_results, visible_delta: float) -> GateDecision:
    return GateDecision(
        method="direct_commit",
        event_id=event.event_id,
        decision="commit",
        reasons=(),
        probe_results=visible_results,
        bucket_summary={"visible_delta": visible_delta, "visible_target_improved": True, "logical_pairs": 0},
    )


def _decide(
    event: CandidateEvent,
    *,
    method: str,
    contract: Mapping[str, Any],
    audit_seed: int,
    budget_pairs: int,
) -> GateDecision:
    visible_results, visible_delta, improved = _visible_precondition(event)
    if not improved:
        return _precondition_reject(method, event, visible_results, visible_delta)
    if method == "direct_commit":
        return _direct_after_visible(event, visible_results, visible_delta)
    if method == "rsea_fixed_validation":
        decision = fixed_heldout(event, budget_pairs=budget_pairs)
    elif method == "fixed_random_audit":
        decision = fixed_random_audit(event, budget_pairs=budget_pairs, seed=audit_seed)
    elif method == "evoaudit_mr":
        suite = route_formal_probes(event, budget_pairs=budget_pairs, seed=audit_seed, contract=contract)
        decision = formal_evoaudit_mr(event, suite)
    else:
        raise ValueError(f"Unsupported method: {method}")
    return GateDecision(
        method=method,
        event_id=event.event_id,
        decision=decision.decision,
        reasons=decision.reasons,
        probe_results=decision.probe_results,
        bucket_summary={**decision.bucket_summary, "visible_delta": visible_delta, "visible_target_improved": True},
    )


def _audit_cost(decision: GateDecision) -> dict[str, int]:
    logical_pairs = int(decision.bucket_summary.get("logical_pairs", 0))
    audit_results = tuple(result for result in decision.probe_results if result.probe.bucket != "visible")
    return {
        "logical_pairs": logical_pairs,
        "tool_calls": sum(len(result.parent.tool_calls) + len(result.candidate.tool_calls) for result in audit_results),
    }


def _slot_generation_seed(manifest: Mapping[str, Any], scenario: Mapping[str, object]) -> int:
    base = int(manifest["ollama"]["seed"])
    offset = sum(ord(char) for char in str(scenario["slot_id"]))
    return base + offset


def _generate_ledger(
    manifest: Mapping[str, Any],
    *,
    output: Path,
    client: OllamaClient,
) -> tuple[dict[str, Any], ...]:
    path = output / "candidate_ledger" / "candidate_ledger_online.jsonl"
    if path.exists():
        raise FileExistsError("Candidate ledger already exists; online candidate generation is immutable.")
    model_config = manifest["ollama"]
    evolve_tasks = int(manifest["evolve_tasks_per_slot"])
    ledger: list[dict[str, Any]] = []
    for scenario in _scenario_rows(manifest):
        environment = str(scenario["environment"])
        parent = _initial_harness(environment)
        tasks = _visible_tasks(scenario, count=evolve_tasks)
        from evoaudit_mr.harness import execute

        traces = [_visible_trace(task, execute(parent, task), note=str(scenario["public_context_note"])) for task in tasks]
        messages, trace_ids = build_proposal_messages(
            environment=environment,
            parent_harness=parent.to_dict(),
            visible_traces=traces,
            required_patch_type=REQUIRED_PATCH_TYPES[environment],
        )
        generation_seed = _slot_generation_seed(manifest, scenario)
        base: dict[str, Any] = {
            **scenario,
            "canonical_parent": parent.to_dict(),
            "canonical_parent_hash": parent.fingerprint,
            "visible_tasks": [task.to_dict() for task in tasks],
            "visible_traces": traces,
            "prompt_sha256": sha256_hex(json.dumps(messages, sort_keys=True, separators=(",", ":"))),
            "generation_seed": generation_seed,
            "required_patch_type": REQUIRED_PATCH_TYPES[environment],
        }
        try:
            completion = client.complete(
                messages,
                model=str(model_config["model"]),
                temperature=float(model_config["temperature"]),
                top_p=float(model_config["top_p"]),
                seed=generation_seed,
                num_predict=int(model_config["num_predict"]),
                timeout_seconds=int(model_config["timeout_seconds"]),
            )
            base.update(
                {
                    "provider_reported_model": completion.model,
                    "usage": dict(completion.usage),
                    "latency_seconds": completion.latency_seconds,
                    "raw_proposal": completion.content,
                    "response_sha256": sha256_hex(completion.content),
                }
            )
            proposal = parse_response_json(
                completion.content,
                allowed_evidence_ids=trace_ids,
                required_patch_type=REQUIRED_PATCH_TYPES[environment],
            )
            try:
                patch = compile_proposed_patch(
                    proposal,
                    environment=environment,
                    patch_id=f"ollama-{environment.lower()}-{int(scenario['trajectory_seed']):03d}-{int(scenario['round_index']):02d}",
                    parent_adapter=parent.adapter_name,
                )
            except ProposalCompilationError as exc:
                base.update({"proposal_status": "valid_but_unexecutable", "failure_type": type(exc).__name__, "failure_message": str(exc), "proposal": proposal.to_dict()})
            else:
                event = CandidateEvent(
                    event_id=f"candidate-{scenario['slot_id']}",
                    parent=parent,
                    patch=patch,
                    visible_tasks=tasks,
                    heldout_tasks=(),
                    environment=environment,
                )
                _, visible_delta, visible_improved = _visible_precondition(event)
                base.update(
                    {
                        "proposal_status": "executable",
                        "proposal": proposal.to_dict(),
                        "patch": patch.to_dict(),
                        "compiled_intent": patch.diff["actual_diff_features"]["compiled_intent"],
                        "behavioral_noop": not visible_improved,
                        "visible_delta_canonical": visible_delta,
                    }
                )
        except (OllamaClientError, ProposalValidationError, ProposalCompilationError, ValueError) as exc:
            base.update({"proposal_status": "invalid", "failure_type": type(exc).__name__, "failure_message": str(exc)})
        except Exception as exc:  # Local provider errors become logged no-ops; no retry is allowed.
            base.update({"proposal_status": "invalid", "failure_type": type(exc).__name__, "failure_message": str(exc)})
        _append(path, base)
        ledger.append(base)
    return tuple(ledger)


def _verify_freeze(manifest: Mapping[str, Any], *, output: Path, client: OllamaClient) -> None:
    freeze = output / "OLLAMA_FREEZE.json"
    if not freeze.exists():
        raise OllamaPilotProtocolError("Online phase requires OLLAMA_FREEZE.json from the frozen local model.")
    record = _load_json(freeze)
    if record.get("public_protocol_sha256") != sha256_hex(canonical_json(manifest)):
        raise OllamaPilotProtocolError("OLLAMA_FREEZE does not match this public manifest.")
    expected = record.get("model_info")
    if not isinstance(expected, Mapping):
        raise OllamaPilotProtocolError("OLLAMA_FREEZE lacks model metadata.")
    current = client.model_info(str(manifest["ollama"]["model"]))
    if expected.get("digest") != current.digest or expected.get("ollama_version") != current.ollama_version:
        raise OllamaPilotProtocolError("Local Ollama model digest or runtime version differs from OLLAMA_FREEZE.")


def _online_protocol_record(manifest: Mapping[str, Any], *, output: Path) -> None:
    payload = {
        "manifest": manifest,
        "manifest_sha256": manifest_digest(manifest),
        "online_source_hashes": source_hashes(_repository_root()),
        "statistical_units": {
            "candidate_level": "canonical-parent candidate event",
            "persistent_evolution": "environment-seed trajectory",
            "dynamic_decision_round_records": 120,
            "static_measurement_records": 30,
        },
        "frozen_best_policy": "not_used; final evaluation scores working@T only",
    }
    target = output / "online_protocol" / "public_protocol.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run_freeze(manifest_path: str | Path, output_dir: str | Path, *, client: OllamaClient | None = None) -> Path:
    manifest = _load_json(manifest_path)
    validate_online_source_lock(manifest, root=_repository_root())
    output = Path(output_dir)
    if output.exists() and any(output.iterdir()):
        raise FileExistsError("Ollama Pilot freeze directory must be new and empty.")
    output.mkdir(parents=True, exist_ok=True)
    return freeze_ollama(manifest, output_path=output / "OLLAMA_FREEZE.json", client=client)


def run_online(manifest_path: str | Path, output_dir: str | Path, *, client: OllamaClient | None = None) -> Path:
    manifest = _load_json(manifest_path)
    root = _repository_root()
    validate_online_source_lock(manifest, root=root)
    output = Path(output_dir)
    local_client = client or OllamaClient(str(manifest["ollama"]["endpoint"]))
    _verify_freeze(manifest, output=output, client=local_client)
    if (output / "ONLINE_COMPLETE.json").exists():
        raise FileExistsError("Ollama Pilot online phase already completed.")
    _online_protocol_record(manifest, output=output)
    ledger = _generate_ledger(manifest, output=output, client=local_client)
    contracts = _contracts(root, manifest)
    validation_by_environment = {
        environment: fixed_validation_tasks(environment, count=int(manifest["validation_tasks"]), seed=int(manifest["validation_seed"]) + index)
        for index, environment in enumerate(ENVIRONMENTS)
    }
    budget = int(manifest["audit_budget_pairs"])
    candidate_decisions = 0
    dynamic_decisions = 0
    static_measurements = 0

    # Candidate-level track: every executable candidate is assessed from the same canonical parent.
    for row in ledger:
        if row.get("proposal_status") != "executable":
            for method in DYNAMIC_METHODS:
                _append(
                    output / "candidate_level" / "decisions.jsonl",
                    {"track": "canonical_candidate", "slot_id": row["slot_id"], "method": method, "decision": "noop", "proposal_status": row.get("proposal_status")},
                )
            continue
        tasks = _visible_tasks(row, count=int(manifest["evolve_tasks_per_slot"]))
        event = _canonical_event(row, visible_tasks=tasks, heldout_tasks=validation_by_environment[str(row["environment"])])
        for method in DYNAMIC_METHODS:
            audit_seed = int(manifest["audit_seed"]) + sum(ord(char) for char in f"canonical-{method}-{row['slot_id']}")
            decision = _decide(event, method=method, contract=contracts[event.environment], audit_seed=audit_seed, budget_pairs=budget)
            cost = _audit_cost(decision)
            record = {
                "track": "canonical_candidate",
                "slot_id": row["slot_id"],
                "event_id": event.event_id,
                "environment": event.environment,
                "method": method,
                "proposal_status": "executable",
                "parent_harness": event.parent.to_dict(),
                "patch": event.patch.to_dict(),
                "decision": decision.decision,
                "decision_reasons": list(decision.reasons),
                "bucket_summary": dict(decision.bucket_summary),
                "audit_cost": cost,
            }
            _append(output / "candidate_level" / "decisions.jsonl", record)
            write_certificate(output / "certificates" / "candidate_level", event, decision, manifest_hash=manifest_digest(manifest), run_id=f"ollama-pilot-v2-canonical-{row['slot_id']}")
            candidate_decisions += 1

    # Persistent track: one external proposal stream, method-specific parent states and labels.
    by_trajectory: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for row in ledger:
        by_trajectory.setdefault((str(row["environment"]), int(row["trajectory_seed"])), []).append(row)
    for key in by_trajectory:
        by_trajectory[key].sort(key=lambda row: int(row["round_index"]))
    for (environment, trajectory_seed), rows in sorted(by_trajectory.items()):
        initial = _initial_harness(environment)
        for row in rows:
            _append(
                output / "static" / f"{environment}-{trajectory_seed}.jsonl",
                {"method": "static", "environment": environment, "trajectory_seed": trajectory_seed, "round_index": row["round_index"], "slot_id": row["slot_id"], "working_harness": initial.to_dict()},
            )
            static_measurements += 1
        for method in DYNAMIC_METHODS:
            working = initial
            applied_patch_ids: list[str] = []
            for row in rows:
                status = str(row.get("proposal_status"))
                visible_tasks = _visible_tasks(row, count=int(manifest["evolve_tasks_per_slot"]))
                if status == "executable":
                    event = _method_event(
                        working,
                        row,
                        visible_tasks=visible_tasks,
                        heldout_tasks=validation_by_environment[environment],
                        method=method,
                    )
                    audit_seed = int(manifest["audit_seed"]) + sum(ord(char) for char in f"trajectory-{method}-{row['slot_id']}")
                    decision = _decide(event, method=method, contract=contracts[environment], audit_seed=audit_seed, budget_pairs=budget)
                    candidate_harness = apply_patch(working, event.patch)
                    if decision.committed:
                        working = candidate_harness
                        applied_patch_ids.append(event.patch.patch_id)
                    cost = _audit_cost(decision)
                    write_certificate(output / "certificates" / "trajectories", event, decision, manifest_hash=manifest_digest(manifest), run_id=f"ollama-pilot-v2-trajectory-{method}-{row['slot_id']}")
                    dynamic_decisions += 1
                    record = {
                        "track": "shared_proposal_persistent_evolution",
                        "slot_id": row["slot_id"],
                        "event_id": event.event_id,
                        "environment": environment,
                        "trajectory_seed": trajectory_seed,
                        "round_index": row["round_index"],
                        "failure_family": row["failure_family"],
                        "method": method,
                        "proposal_status": status,
                        "parent_harness": event.parent.to_dict(),
                        "candidate_harness": candidate_harness.to_dict(),
                        "working_harness": working.to_dict(),
                        "patch": event.patch.to_dict(),
                        "decision": decision.decision,
                        "decision_reasons": list(decision.reasons),
                        "bucket_summary": dict(decision.bucket_summary),
                        "audit_cost": cost,
                        "applied_patch_ids": list(applied_patch_ids),
                    }
                else:
                    dynamic_decisions += 1
                    record = {
                        "track": "shared_proposal_persistent_evolution",
                        "slot_id": row["slot_id"],
                        "event_id": f"trajectory-{method}-{row['slot_id']}",
                        "environment": environment,
                        "trajectory_seed": trajectory_seed,
                        "round_index": row["round_index"],
                        "failure_family": row["failure_family"],
                        "method": method,
                        "proposal_status": status,
                        "parent_harness": working.to_dict(),
                        "candidate_harness": working.to_dict(),
                        "working_harness": working.to_dict(),
                        "decision": "noop",
                        "decision_reasons": [f"proposal_{status}"],
                        "bucket_summary": {"logical_pairs": 0},
                        "audit_cost": {"logical_pairs": 0, "tool_calls": 0},
                        "applied_patch_ids": list(applied_patch_ids),
                    }
                _append(output / "trajectories" / method / f"{environment}-{trajectory_seed}.jsonl", record)
    expected_slots = len(ledger)
    complete_online_phase(
        output,
        manifest_hash=manifest_digest(manifest),
        candidate_slots=expected_slots,
        dynamic_decisions=dynamic_decisions,
        static_measurements=static_measurements,
    )
    return output


def _final_metrics(harness: Harness, probes: tuple[Probe, ...]) -> dict[str, object]:
    from evoaudit_mr.harness import execute

    outcomes = [(probe, execute(harness, probe.task)) for probe in probes]
    grouped = {bucket: [(probe, outcome) for probe, outcome in outcomes if probe.bucket == bucket] for bucket in ("target", "replay", "safety")}
    score = lambda rows: sum(outcome.task_success for _, outcome in rows) / len(rows)
    safety_outcomes = [outcome for _, outcome in grouped["safety"]]
    safety_events = tuple(event for outcome in safety_outcomes for event in outcome.safety_events)
    return {
        "target_success": score(grouped["target"]),
        "replay_success": score(grouped["replay"]),
        "safety_success": score(grouped["safety"]),
        "overall_success": score(outcomes),
        "unsafe_probe_rate": sum(bool(outcome.safety_events) for outcome in safety_outcomes) / len(safety_outcomes),
        "safety_event_density": len(safety_events) / len(safety_outcomes),
        "safety_event_count": len(safety_events),
    }


def _mean(rows: list[dict[str, Any]], field: str) -> float | None:
    values = [float(row[field]) for row in rows if isinstance(row.get(field), (int, float))]
    return sum(values) / len(values) if values else None


def run_offline(manifest_path: str | Path, offline_path: str | Path, output_dir: str | Path) -> Path:
    """Reveal hidden labels only after online phase lock; imports hidden code locally."""
    manifest = _load_json(manifest_path)
    offline = _load_json(offline_path)
    output = Path(output_dir)
    slots = _scenario_rows(manifest)
    require_online_phase(
        output,
        manifest_hash=manifest_digest(manifest),
        candidate_slots=len(slots),
        dynamic_decisions=len(slots) * len(DYNAMIC_METHODS),
        static_measurements=len(slots),
    )
    if (output / "offline_hidden").exists():
        raise FileExistsError("Offline labels already exist and are immutable.")
    root = _repository_root()
    contracts = _contracts(root, manifest)
    # Offline-only import: online callers never import this module.
    from evoaudit_mr.llm.ollama_pilot_offline import evaluate_hidden_event, final_exam, hidden_generator_source

    validate_offline_commitments(
        manifest,
        offline,
        hidden_generator_source=hidden_generator_source(),
        environment_contracts=contracts,
    )
    key = str(offline["hidden_master_seed"])
    hidden_config = offline["hidden_config"]
    per_bucket = int(hidden_config["per_bucket"])
    final_per_bucket = int(hidden_config["final_per_bucket"])
    ledger = _read_jsonl(output / "candidate_ledger" / "candidate_ledger_online.jsonl")
    candidate_rows = _read_jsonl(output / "candidate_level" / "decisions.jsonl")
    labels: dict[str, Any] = {}
    canonical_label_rows: list[dict[str, object]] = []
    for row in ledger:
        if row.get("proposal_status") != "executable":
            continue
        tasks = _visible_tasks(row, count=int(manifest["evolve_tasks_per_slot"]))
        event = _canonical_event(row, visible_tasks=tasks, heldout_tasks=())
        label = evaluate_hidden_event(event, master_key=key, manifest_hash=manifest_digest(manifest), per_bucket=per_bucket)
        labels[event.event_id] = label
        log = {"label_kind": "canonical_parent", "slot_id": row["slot_id"], "event_id": event.event_id, **label.to_dict()}
        canonical_label_rows.append(log)
        _append(output / "offline_hidden" / "canonical_labels.jsonl", log)

    trajectory_label_rows: list[dict[str, object]] = []
    for method in DYNAMIC_METHODS:
        for path in sorted((output / "trajectories" / method).glob("*.jsonl")):
            for record in _read_jsonl(path):
                if record.get("proposal_status") != "executable":
                    continue
                event = CandidateEvent(
                    event_id=str(record["event_id"]),
                    parent=_harness_from_dict(record["parent_harness"]),
                    patch=_patch_from_dict(record["patch"]),
                    visible_tasks=(),
                    heldout_tasks=(),
                    environment=str(record["environment"]),
                )
                label = evaluate_hidden_event(event, master_key=key, manifest_hash=manifest_digest(manifest), per_bucket=per_bucket)
                log = {
                    "label_kind": "method_specific_parent",
                    "slot_id": record["slot_id"],
                    "event_id": event.event_id,
                    "method": method,
                    "environment": record["environment"],
                    "trajectory_seed": record["trajectory_seed"],
                    "round_index": record["round_index"],
                    "committed": record["decision"] == "commit",
                    **label.to_dict(),
                }
                trajectory_label_rows.append(log)
                _append(output / "offline_hidden" / "trajectory_labels.jsonl", log)

    candidate_metrics: list[dict[str, object]] = []
    executable = [row for row in ledger if row.get("proposal_status") == "executable"]
    for method in DYNAMIC_METHODS:
        decisions = {str(row["event_id"]): row for row in candidate_rows if row.get("method") == method and row.get("proposal_status") == "executable"}
        pairs = [
            (
                decisions[event_id]["decision"] == "commit",
                labels[event_id].reliable,
                bool(labels[event_id].safety_events),
            )
            for event_id in labels
            if event_id in decisions
        ]
        confusion = confusion_from_pairs(pairs)
        candidate_metrics.append(
            {
                "metric_scope": "conditional_executable_canonical_candidates",
                "method": method,
                "n_executable": len(pairs),
                **confusion.to_dict(),
                "committed_reliable_per_30_slots": sum(committed and reliable for committed, reliable, _ in pairs),
                "committed_unreliable_per_30_slots": sum(committed and not reliable for committed, reliable, _ in pairs),
            }
        )
    generator = {
        "metric_scope": "generator_unconditional_30_slots",
        "total_slots": len(ledger),
        "executable": len(executable),
        "invalid": sum(row.get("proposal_status") == "invalid" for row in ledger),
        "unexecutable": sum(row.get("proposal_status") == "valid_but_unexecutable" for row in ledger),
        "behavioral_noop": sum(bool(row.get("behavioral_noop")) for row in executable),
        "raw_proposal_unique": len({row.get("raw_proposal") for row in ledger if isinstance(row.get("raw_proposal"), str)}),
        "compiled_intent_unique": len({row.get("compiled_intent") for row in executable}),
        "behavior_signature_unique": len({(row.get("compiled_intent"), row.get("visible_delta_canonical")) for row in executable}),
    }
    _write_csv(output / "reports" / "candidate_metrics.csv", candidate_metrics)
    _write_csv(output / "reports" / "generator_metrics.csv", [generator])

    final_rows: list[dict[str, object]] = []
    for environment in ENVIRONMENTS:
        for trajectory_seed in manifest["trajectory_seeds"]:
            exam = final_exam(environment, trajectory_seed=int(trajectory_seed), master_key=key, manifest_hash=manifest_digest(manifest), per_bucket=final_per_bucket)
            static_harness = _initial_harness(environment)
            for method in ALL_METHODS:
                if method == "static":
                    harness = static_harness
                else:
                    records = _read_jsonl(output / "trajectories" / method / f"{environment}-{trajectory_seed}.jsonl")
                    if len(records) != int(manifest["rounds"]):
                        raise OllamaPilotProtocolError("Trajectory lacks exactly five online records.")
                    harness = _harness_from_dict(records[-1]["working_harness"])
                row = {
                    "environment": environment,
                    "trajectory_seed": int(trajectory_seed),
                    "method": method,
                    "checkpoint": "working@0" if method == "static" else "working@T",
                    "harness_hash": harness.fingerprint,
                    **_final_metrics(harness, exam),
                }
                final_rows.append(row)
                _append(output / "offline_hidden" / "final_metrics.jsonl", row)
    _write_csv(output / "reports" / "trajectory_metrics.csv", final_rows)
    summary: list[dict[str, object]] = []
    for environment in (*ENVIRONMENTS, "Overall"):
        for method in ALL_METHODS:
            subset = [row for row in final_rows if row["method"] == method and (environment == "Overall" or row["environment"] == environment)]
            summary.append(
                {
                    "environment": environment,
                    "method": method,
                    "n_trajectories": len(subset),
                    **{field: _mean(subset, field) for field in ("target_success", "replay_success", "safety_success", "overall_success", "unsafe_probe_rate", "safety_event_density")},
                }
            )
    _write_csv(output / "reports" / "trajectory_summary.csv", summary)
    _write_report(output, generator=generator, candidate_metrics=candidate_metrics, summary=summary, labels=canonical_label_rows)
    return output


def _write_report(
    output: Path,
    *,
    generator: Mapping[str, object],
    candidate_metrics: list[Mapping[str, object]],
    summary: list[Mapping[str, object]],
    labels: list[Mapping[str, object]],
) -> None:
    reliable = sum(bool(row["reliable"]) for row in labels)
    unreliable = len(labels) - reliable
    criteria = {
        "executable_at_least_18": int(generator["executable"]) >= 18,
        "both_environments_executable": len({row["environment"] for row in _read_jsonl(output / "candidate_ledger" / "candidate_ledger_online.jsonl") if row.get("proposal_status") == "executable"}) == 2,
        "canonical_reliable_at_least_3": reliable >= 3,
        "canonical_unreliable_at_least_3": unreliable >= 3,
    }
    lines = [
        "# Ollama LLM Proposal Pilot v2 report",
        "",
        "This is a development Pilot for constrained LLM-proposed updates. It reports descriptive, not significance, evidence.",
        "",
        "## Generator",
        "",
        "```json",
        json.dumps(dict(generator), indent=2, sort_keys=True),
        "```",
        "",
        "## Candidate-diversity criteria",
        "",
        "```json",
        json.dumps(criteria, indent=2, sort_keys=True),
        "```",
        "",
        "## Conditional candidate metrics",
        "",
        "| Method | FAR | FDR | UUR | Reliable commits / 30 slots | Unreliable commits / 30 slots |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in candidate_metrics:
        lines.append(
            f"| {row['method']} | {row['far']} | {row['fdr']} | {row['uur']} | "
            f"{row['committed_reliable_per_30_slots']} | {row['committed_unreliable_per_30_slots']} |"
        )
    lines.extend(["", "## Persistent-evolution final summary", "", "| Environment | Method | n trajectories | Target | Replay | Unsafe probe rate | Overall |", "| --- | --- | ---: | ---: | ---: | ---: | ---: |"])
    for row in summary:
        lines.append(
            f"| {row['environment']} | {row['method']} | {row['n_trajectories']} | {row['target_success']} | "
            f"{row['replay_success']} | {row['unsafe_probe_rate']} | {row['overall_success']} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation boundary",
            "",
            "The compiler maps a restricted public DSL into a finite policy family. Therefore this Pilot can support only the claim that EvoAudit-MR audits constrained LLM-proposed updates; it does not demonstrate arbitrary free-form prompt, tool, memory, or workflow modification.",
        ]
    )
    path = output / "reports" / "pilot_report.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    root = _repository_root()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", required=True, choices=("freeze", "online", "offline", "seal"))
    parser.add_argument("--manifest", default=str(root / "configs" / "ollama_pilot_v2_manifest.json"))
    parser.add_argument("--offline-config", default=str(root / "configs" / "ollama_pilot_v2_offline.json"))
    parser.add_argument("--output-dir", default=str(root / "artifacts_llm" / "ollama_pilot_v2"))
    args = parser.parse_args()
    if args.phase == "freeze":
        print(run_freeze(args.manifest, args.output_dir))
    elif args.phase == "online":
        print(run_online(args.manifest, args.output_dir))
    elif args.phase == "offline":
        print(run_offline(args.manifest, args.offline_config, args.output_dir))
    else:
        manifest = _load_json(args.manifest)
        print(seal_artifacts(args.output_dir, manifest_hash=manifest_digest(manifest)))


if __name__ == "__main__":
    main()
