"""Independent V3b Ollama Proposal Pilot: structured output plus fail-closed auditing.

The model owns only a small policy delta.  Environment-owned patch type and
scope are injected by the compiler.  The online phase intentionally imports no
hidden evaluator; offline evaluation is local-imported only after phase lock.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any, Mapping

from evoaudit_mr.llm.ollama import OllamaClientError
from evoaudit_mr.llm.ollama_native import NativeOllamaClient
from evoaudit_mr.llm.ollama_pilot_v3b_protocol import (
    OllamaPilotV3BProtocolError, canonical_json, manifest_digest, seal_artifacts, sha256_hex,
    source_hashes, validate_hidden_reveal, validate_online_phase_lock, validate_online_source_lock,
    write_hidden_commitment, write_online_phase_lock,
)
from evoaudit_mr.llm.v3_compiler import V3ProposalCompilationError, materialize_v3_patch
from evoaudit_mr.llm.v3_ir import V3IRValidationError, policy_hash, policy_signature
from evoaudit_mr.llm.v3b_ir import (
    build_v3b_proposal_messages, parse_v3b_response_json, parse_v3b_proposed_patch,
)
from evoaudit_mr.runners import ollama_pilot_v3 as base
from evoaudit_mr.types import Harness, Probe


DYNAMIC_METHODS = base.DYNAMIC_METHODS
ALL_METHODS = base.ALL_METHODS
ENVIRONMENTS = base.ENVIRONMENTS


def _root() -> Path: return Path(__file__).resolve().parents[3]
def _load(path: str | Path) -> dict[str, Any]: return base._load_json(path)
def _write(path: Path, value: object) -> Path: return base._write_json(path, value)
def _append(path: Path, row: Mapping[str, object]) -> None: base._append(path, row)
def _read(path: Path) -> list[dict[str, Any]]: return base._read_jsonl(path)
def _contracts(root: Path, manifest: Mapping[str, Any]): return base._contracts(root, manifest)
def _initial(environment: str): return base._initial_harness(environment)
def _event(*args, **kwargs): return base._event(*args, **kwargs)
def _visible_tasks(*args, **kwargs): return base._visible_tasks(*args, **kwargs)
def _visible_trace(*args, **kwargs): return base._visible_trace(*args, **kwargs)
def _decide(*args, **kwargs): return base._decide(*args, **kwargs)
def _audit_cost(*args, **kwargs): return base._audit_cost(*args, **kwargs)
def _scenario_rows(*args, **kwargs):
    """Use the same public schedule but give V3b an independent slot namespace."""
    return tuple({**row, "slot_id": str(row["slot_id"]).replace("v3-", "v3b-", 1)} for row in base._scenario_rows(*args, **kwargs))
def _slot_seed(*args, **kwargs): return base._slot_seed(*args, **kwargs)
def _harness(raw): return base._harness_from_dict(raw)
def _patch(raw): return base._patch_from_dict(raw)


def _compatibility_cases() -> tuple[dict[str, object], ...]:
    """Pre-registered public-only cases; no hidden family, seed, or label appears here."""
    return (
        {"case_id": "v3b-a2-alias-1", "environment": "AliasTool", "profile": "alias", "task_index": 8101,
         "note": "The declared inventory interface uses a public alias."},
        {"case_id": "v3b-a2-alias-2", "environment": "AliasTool", "profile": "alias_reordered", "task_index": 8102,
         "note": "The declared output field and field order differ publicly."},
        {"case_id": "v3b-a2-alias-3", "environment": "AliasTool", "profile": "alt_alias_reordered", "task_index": 8103,
         "note": "An alternate declared alias and reordered public record co-occur."},
        {"case_id": "v3b-a2-permission-1", "environment": "PermissionPath", "profile": "archive_valid", "task_index": 8201,
         "note": "An authorized and confirmed irreversible operation requires a complete public workflow."},
        {"case_id": "v3b-a2-permission-2", "environment": "PermissionPath", "profile": "valid_viewer", "task_index": 8202,
         "note": "A delegated viewer has public explicit authorization."},
        {"case_id": "v3b-a2-permission-3", "environment": "PermissionPath", "profile": "update_valid", "task_index": 8203,
         "note": "A matching-tenant authorized public update must be completed and recorded."},
    )


def _case_context(case: Mapping[str, object]) -> tuple[Harness, tuple, list[dict[str, object]], list[dict[str, str]], tuple[str, ...], dict[str, Any]]:
    environment = str(case["environment"])
    parent = _initial(environment)
    task = base._task(environment, str(case["profile"]), int(case["task_index"]), prefix="v3b-a2")
    from evoaudit_mr.harness import execute
    traces = [_visible_trace(task, execute(parent, task), note=str(case["note"]))]
    messages, trace_ids, schema = build_v3b_proposal_messages(environment=environment, parent_policy=parent.typed_policy, visible_traces=traces)
    return parent, (task,), traces, messages, trace_ids, schema


def _verify_readiness(output: Path, root: Path) -> None:
    path = output / "COMPILER_READINESS_SEAL.json"
    if not path.exists(): raise OllamaPilotV3BProtocolError("V3b requires an independent Gate A1 readiness seal.")
    if _load(path).get("online_source_hashes") != source_hashes(root):
        raise OllamaPilotV3BProtocolError("An online-critical source changed after the V3b A1 seal.")


def run_readiness(output_dir: str | Path, *, v2_ledger_path: str | Path | None = None) -> Path:
    """Independent public-only compiler readiness (A1), reusing no V3 seal."""
    root, output = _root(), Path(output_dir); output.mkdir(parents=True, exist_ok=True)
    seal_path = output / "COMPILER_READINESS_SEAL.json"
    if seal_path.exists(): raise FileExistsError("COMPILER_READINESS_SEAL already exists.")
    v2_path = Path(v2_ledger_path) if v2_ledger_path else root / "artifacts_llm" / "ollama_pilot_v2" / "candidate_ledger" / "candidate_ledger_online.jsonl"
    corpus = base._public_corpus_rows(v2_path)
    annotations = base._build_public_annotations(corpus)
    corpus_path, ann_path = output / "V2_PUBLIC_COMPILER_CORPUS.jsonl", output / "V2_PUBLIC_IR_ANNOTATIONS.jsonl"
    if corpus_path.exists() or ann_path.exists(): raise FileExistsError("Public readiness corpus already exists.")
    for row in corpus: _append(corpus_path, row)
    for row in annotations: _append(ann_path, row)
    contracts = _contracts(root, {"environment_contracts": {"AliasTool": "configs/aliastool_contract.json", "PermissionPath": "configs/permissionpath_contract.json"}})
    report = base._run_readiness_suite(root, contracts, annotations)
    report_path = output / "COMPILER_READINESS_REPORT.md"
    report_path.write_text("# V3b Compiler Readiness Report\n\nGate A1 uses V2 online-public data only.\n\n```json\n" + json.dumps(report, indent=2, sort_keys=True) + "\n```\n", encoding="utf-8")
    return _write(seal_path, {"protocol_version": "ollama-llm-proposal-pilot-v3b", "gate": "A1",
        "v2_public_source_sha256": sha256_hex(v2_path.read_bytes()), "corpus_sha256": sha256_hex(corpus_path.read_bytes()),
        "annotations_sha256": sha256_hex(ann_path.read_bytes()), "report_sha256": sha256_hex(report_path.read_bytes()),
        "online_source_hashes": source_hashes(root), "readiness": report})


def prepare_a2(manifest_path: str | Path, output_dir: str | Path, *, client: NativeOllamaClient | None = None) -> Path:
    root, output, manifest = _root(), Path(output_dir), _load(manifest_path)
    validate_online_source_lock(manifest, root=root); _verify_readiness(output, root)
    path = output / "SCHEMA_COMPATIBILITY_INPUT_SEAL.json"
    if path.exists(): raise FileExistsError("SCHEMA_COMPATIBILITY_INPUT_SEAL already exists.")
    model = manifest["ollama"]; local = client or NativeOllamaClient(str(model["endpoint"])); info = local.model_info(str(model["model"]))
    cases = []
    for case in _compatibility_cases():
        _, tasks, traces, messages, trace_ids, schema = _case_context(case)
        cases.append({**case, "task_sha256": sha256_hex(canonical_json([task.to_dict() for task in tasks])),
                      "trace_sha256": sha256_hex(canonical_json(traces)), "prompt_sha256": sha256_hex(canonical_json(messages)),
                      "schema_sha256": sha256_hex(canonical_json(schema)), "allowed_evidence_trace_ids": list(trace_ids)})
    return _write(path, {"protocol_version": "ollama-llm-proposal-pilot-v3b", "gate": "A2", "status": "prepared",
        "model_info": info.to_dict(), "manifest_sha256": manifest_digest(manifest), "online_source_hashes": source_hashes(root),
        "cases": cases, "sampling": {k: model[k] for k in ("temperature", "top_p", "seed", "num_predict", "timeout_seconds")},
        "no_retry_rule": "Each compatibility case is called once; parser, compiler, and human correction never retry or repair an output."})


def run_a2(manifest_path: str | Path, output_dir: str | Path, *, client: NativeOllamaClient | None = None) -> Path:
    root, output, manifest = _root(), Path(output_dir), _load(manifest_path)
    validate_online_source_lock(manifest, root=root); _verify_readiness(output, root)
    input_seal = _load(output / "SCHEMA_COMPATIBILITY_INPUT_SEAL.json")
    if input_seal.get("online_source_hashes") != source_hashes(root): raise OllamaPilotV3BProtocolError("A2 input sources changed after sealing.")
    report_path, raw_path = output / "SCHEMA_COMPATIBILITY_REPORT.json", output / "schema_compatibility_outputs.jsonl"
    if report_path.exists() or raw_path.exists(): raise FileExistsError("A2 outputs already exist and must not be overwritten.")
    model = manifest["ollama"]; local = client or NativeOllamaClient(str(model["endpoint"])); info = local.model_info(str(model["model"]))
    expected_info = input_seal.get("model_info", {})
    if info.digest != expected_info.get("digest") or info.ollama_version != expected_info.get("ollama_version"):
        raise OllamaPilotV3BProtocolError("Ollama model/runtime differs from the sealed A2 input.")
    results: list[dict[str, object]] = []
    for offset, case in enumerate(_compatibility_cases()):
        parent, tasks, traces, messages, trace_ids, schema = _case_context(case)
        row: dict[str, object] = {**case, "prompt_sha256": sha256_hex(canonical_json(messages)), "schema_sha256": sha256_hex(canonical_json(schema)),
                                  "allowed_evidence_trace_ids": list(trace_ids), "status": "provider_failure"}
        try:
            completion = local.complete(messages, schema=schema, model=str(model["model"]), temperature=float(model["temperature"]), top_p=float(model["top_p"]),
                seed=int(model["seed"]) + offset, num_predict=int(model["num_predict"]), timeout_seconds=int(model["timeout_seconds"]))
            # Persist the response before parsing: raw output remains available even if parsing fails.
            row.update({"provider_reported_model": completion.model, "usage": dict(completion.usage), "latency_seconds": completion.latency_seconds,
                        "raw_response": completion.content, "response_sha256": sha256_hex(completion.content),
                        "native_response_sha256": sha256_hex(canonical_json(completion.raw_response))})
            proposal = parse_v3b_response_json(completion.content, environment=str(case["environment"]), allowed_evidence_ids=trace_ids)
            patch = materialize_v3_patch(proposal.to_compiler_proposal(), environment=str(case["environment"]), patch_id=f"{case['case_id']}-patch", parent=parent)
            row.update({"status": "passed", "model_proposal": proposal.to_model_dict(), "system_patch_type": proposal.patch_type,
                        "system_claimed_scope": list(proposal.claimed_scope), "compiled_patch_sha256": sha256_hex(canonical_json(patch.to_dict())),
                        "materialized_parent_policy_hash": policy_hash(patch.diff["typed_policy_after"])})
        except (OllamaClientError, V3IRValidationError, V3ProposalCompilationError, ValueError) as exc:
            row.update({"failure_type": type(exc).__name__, "failure_message": str(exc)})
        _append(raw_path, row); results.append(row)
    criteria = {"six_of_six_schema_valid": len(results) == 6 and all(row["status"] == "passed" for row in results),
                "both_environments_pass": {row["environment"] for row in results if row["status"] == "passed"} == set(ENVIRONMENTS),
                "all_materialize": all("compiled_patch_sha256" in row for row in results),
                "evidence_from_visible_input": all(row["status"] == "passed" for row in results),
                "no_empty_or_conflicting_delta": all(row["status"] == "passed" for row in results)}
    return _write(report_path, {"protocol_version": "ollama-llm-proposal-pilot-v3b", "gate": "A2", "passed": all(criteria.values()),
        "criteria": criteria, "outputs_sha256": sha256_hex(raw_path.read_bytes()), "results": results})


def _write_freeze(manifest: Mapping[str, Any], *, output: Path) -> Path:
    path = output / "OLLAMA_FREEZE.json"
    if path.exists(): raise FileExistsError("OLLAMA_FREEZE already exists.")
    a2_input, a2_report, a2_outputs = _load(output / "SCHEMA_COMPATIBILITY_INPUT_SEAL.json"), _load(output / "SCHEMA_COMPATIBILITY_REPORT.json"), output / "schema_compatibility_outputs.jsonl"
    if not bool(a2_report.get("passed")): raise OllamaPilotV3BProtocolError("V3b freeze requires an A2 pass; no formal calls follow failure.")
    return _write(path, {"freeze_version": "ollama-pilot-v3b-freeze-v1", "public_protocol_sha256": manifest_digest(manifest),
        "model_info": a2_input["model_info"], "a1_readiness_sha256": sha256_hex((output / "COMPILER_READINESS_SEAL.json").read_bytes()),
        "a2_input_seal_sha256": sha256_hex((output / "SCHEMA_COMPATIBILITY_INPUT_SEAL.json").read_bytes()),
        "a2_report_sha256": sha256_hex((output / "SCHEMA_COMPATIBILITY_REPORT.json").read_bytes()), "a2_raw_outputs_sha256": sha256_hex(a2_outputs.read_bytes()),
        "online_source_hashes": source_hashes(_root()), "one_call_policy": "Each formal proposal slot is called exactly once; invalid, conflicting, and no-op outputs stay in the ledger without retry."})


def run_freeze(manifest_path: str | Path, offline_path: str | Path, output_dir: str | Path) -> Path:
    root, output, manifest = _root(), Path(output_dir), _load(manifest_path)
    validate_online_source_lock(manifest, root=root); _verify_readiness(output, root)
    _write_freeze(manifest, output=output)
    offline = _load(offline_path); key, hidden = offline.get("hidden_master_seed"), offline.get("hidden_config")
    if not isinstance(key, str) or len(key) != 64 or not isinstance(hidden, Mapping): raise OllamaPilotV3BProtocolError("Offline V3b configuration is malformed.")
    from evoaudit_mr.llm.ollama_pilot_v3b_offline import hidden_generator_source
    write_hidden_commitment(output, key=key, hidden_config=hidden, hidden_source=hidden_generator_source(), environment_contracts=_contracts(root, manifest))
    contexts = []
    for scenario in _scenario_rows(manifest):
        tasks = _visible_tasks(scenario, count=int(manifest["evolve_tasks_per_slot"]))
        contexts.append({"slot_id": scenario["slot_id"], "context_sha256": sha256_hex(canonical_json({"scenario": scenario, "tasks": [task.to_dict() for task in tasks]}))})
    return _write(output / "ONLINE_INPUT_SEAL.json", {"protocol_version": "ollama-llm-proposal-pilot-v3b", "manifest": manifest,
        "manifest_sha256": manifest_digest(manifest), "canonical_context_hashes": contexts,
        "readiness_seal_sha256": sha256_hex((output / "COMPILER_READINESS_SEAL.json").read_bytes()), "freeze_sha256": sha256_hex((output / "OLLAMA_FREEZE.json").read_bytes()),
        "hidden_commitment_sha256": sha256_hex((output / "HIDDEN_COMMITMENT.json").read_bytes()), "online_source_hashes": source_hashes(root),
        "statistical_units": {"canonical_candidate": "canonical-parent proposal event", "persistent_evolution": "environment-seed trajectory", "dynamic_decision_records": 120, "static_measurements": 30},
        "checkpoint_policy": "working@T only; no frozen-best selection"})


def _freeze_matches(manifest: Mapping[str, Any], output: Path, client: NativeOllamaClient) -> None:
    freeze = _load(output / "OLLAMA_FREEZE.json"); expected = freeze.get("model_info", {}); info = client.model_info(str(manifest["ollama"]["model"]))
    if freeze.get("public_protocol_sha256") != manifest_digest(manifest) or expected.get("digest") != info.digest or expected.get("ollama_version") != info.ollama_version:
        raise OllamaPilotV3BProtocolError("The model or manifest differs from the V3b freeze.")


def _generate_ledger(manifest: Mapping[str, Any], *, output: Path, client: NativeOllamaClient) -> tuple[dict[str, Any], ...]:
    path = output / "candidate_ledger_online.jsonl"
    if path.exists(): raise FileExistsError("Candidate ledger already exists.")
    model, ledger = manifest["ollama"], []
    for scenario in _scenario_rows(manifest):
        environment, parent = str(scenario["environment"]), _initial(str(scenario["environment"]))
        tasks = _visible_tasks(scenario, count=int(manifest["evolve_tasks_per_slot"])); from evoaudit_mr.harness import execute
        traces = [_visible_trace(task, execute(parent, task), note=str(scenario["public_context_note"])) for task in tasks]
        messages, trace_ids, schema = build_v3b_proposal_messages(environment=environment, parent_policy=parent.typed_policy, visible_traces=traces)
        row: dict[str, Any] = {**scenario, "canonical_parent": parent.to_dict(), "canonical_parent_policy_hash": policy_hash(parent.typed_policy),
            "visible_tasks": [task.to_dict() for task in tasks], "visible_traces": traces, "prompt_sha256": sha256_hex(canonical_json(messages)),
            "schema_sha256": sha256_hex(canonical_json(schema)), "generation_seed": _slot_seed(manifest, scenario), "required_patch_type": {"AliasTool": "tool_adapter", "PermissionPath": "workflow"}[environment]}
        try:
            completion = client.complete(messages, schema=schema, model=str(model["model"]), temperature=float(model["temperature"]), top_p=float(model["top_p"]),
                seed=int(row["generation_seed"]), num_predict=int(model["num_predict"]), timeout_seconds=int(model["timeout_seconds"]))
            row.update({"provider_reported_model": completion.model, "usage": dict(completion.usage), "latency_seconds": completion.latency_seconds,
                        "raw_proposal": completion.content, "response_sha256": sha256_hex(completion.content), "native_response_sha256": sha256_hex(canonical_json(completion.raw_response))})
            proposal = parse_v3b_response_json(completion.content, environment=environment, allowed_evidence_ids=trace_ids)
            patch = materialize_v3_patch(proposal.to_compiler_proposal(), environment=environment, patch_id=f"v3b-{environment.lower()}-{int(scenario['trajectory_seed']):03d}-{int(scenario['round_index']):02d}", parent=parent)
            event = _event(parent, patch, slot_id=str(scenario["slot_id"]), environment=environment, visible_tasks=tasks, heldout_tasks=(), track="canonical")
            _, delta, eligible = base._visible_precondition(event); noop = patch.diff["typed_policy_before"] == patch.diff["typed_policy_after"]
            row.update({"model_proposal": proposal.to_model_dict(), "compiler_proposal": proposal.to_compiler_proposal().to_dict(), "patch": patch.to_dict(),
                "system_patch_type": proposal.patch_type, "system_claimed_scope": list(proposal.claimed_scope), "typed_policy_delta_signature": policy_signature(proposal.to_compiler_proposal()),
                "typed_policy_after_hash": policy_hash(patch.diff["typed_policy_after"]), "visible_delta_canonical": delta, "canonical_eligible": eligible,
                "proposal_status": "behavioral_noop" if noop else "executable"})
        except V3ProposalCompilationError as exc: row.update({"proposal_status": "invalid_policy_combination", "failure_type": type(exc).__name__, "failure_message": str(exc)})
        except Exception as exc: row.update({"proposal_status": "invalid", "failure_type": type(exc).__name__, "failure_message": str(exc)})
        _append(path, row); ledger.append(row)
    return tuple(ledger)


def _canonical(manifest, output, ledger, contracts) -> None:
    # V3 decisions work on the generic compiled Patch and are independent of proposal serialization.
    base._canonical_decisions(manifest, output=output, ledger=ledger, contracts=contracts)


def _persistent(manifest: Mapping[str, Any], *, output: Path, ledger: tuple[dict[str, Any], ...], contracts) -> dict[str, str]:
    # Same external stream; each method re-materializes the V3b delta against its own parent.
    from evoaudit_mr.evolution.transforms import apply_patch
    from evoaudit_mr.formal.catalogue import fixed_validation_tasks
    validation = {env: fixed_validation_tasks(env, count=int(manifest["validation_tasks"]), seed=int(manifest["validation_seed"]) + i) for i, env in enumerate(ENVIRONMENTS)}
    groups: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for row in ledger: groups.setdefault((str(row["environment"]), int(row["trajectory_seed"])), []).append(row)
    for rows in groups.values(): rows.sort(key=lambda row: int(row["round_index"]))
    path, static_path, hashes = output / "online_decisions.jsonl", output / "static_snapshots.jsonl", {}
    for (environment, seed), rows in sorted(groups.items()):
        initial = _initial(environment)
        for row in rows: _append(static_path, {"method": "static", "environment": environment, "trajectory_seed": seed, "round_index": row["round_index"], "slot_id": row["slot_id"], "working_harness": initial.to_dict(), "working_policy_hash": policy_hash(initial.typed_policy)})
        for method in DYNAMIC_METHODS:
            working, applied = initial, []
            for row in rows:
                base_row: dict[str, Any] = {"track": "shared_proposal_persistent_evolution", "slot_id": row["slot_id"], "environment": environment, "trajectory_seed": seed, "round_index": row["round_index"], "failure_family": row["failure_family"], "method": method, "proposal_status": row["proposal_status"], "parent_harness": working.to_dict(), "parent_policy_hash": policy_hash(working.typed_policy)}
                if row["proposal_status"] != "executable":
                    _append(path, {**base_row, "event_id": f"persistent-{method}-{row['slot_id']}", "decision": "noop", "decision_reasons": [f"proposal_{row['proposal_status']}"], "eligible": False, "audit_cost": {"logical_pairs": 0, "tool_calls": 0}, "working_harness": working.to_dict(), "working_policy_hash": policy_hash(working.typed_policy), "applied_patch_ids": list(applied)}); continue
                try:
                    prop = parse_v3b_proposed_patch(row["model_proposal"], environment=environment, allowed_evidence_ids=tuple(str(x) for x in row["model_proposal"]["evidence_trace_ids"]))
                    patch = materialize_v3_patch(prop.to_compiler_proposal(), environment=environment, patch_id=str(row["patch"]["patch_id"]), parent=working)
                except Exception as exc:
                    _append(path, {**base_row, "event_id": f"persistent-{method}-{row['slot_id']}", "decision": "noop", "decision_reasons": ["parent_policy_combination_rejected"], "materialization_error": str(exc), "eligible": False, "audit_cost": {"logical_pairs": 0, "tool_calls": 0}, "working_harness": working.to_dict(), "working_policy_hash": policy_hash(working.typed_policy), "applied_patch_ids": list(applied)}); continue
                tasks = _visible_tasks(row, count=int(manifest["evolve_tasks_per_slot"])); event = _event(working, patch, slot_id=str(row["slot_id"]), environment=environment, visible_tasks=tasks, heldout_tasks=validation[environment], track=f"persistent-{method}")
                d = _decide(event, method=method, contract=contracts[environment], seed=int(manifest["audit_seed"]) + sum(ord(c) for c in f"persistent-{method}-{row['slot_id']}"), budget_pairs=int(manifest["audit_budget_pairs"])); candidate = apply_patch(working, patch)
                if d.committed: working, applied = candidate, [*applied, patch.patch_id]
                _append(path, {**base_row, "event_id": event.event_id, "patch": patch.to_dict(), "candidate_harness": candidate.to_dict(), "candidate_policy_hash": policy_hash(candidate.typed_policy), "decision": d.decision, "decision_reasons": list(d.reasons), "bucket_summary": dict(d.bucket_summary), "eligible": bool(d.bucket_summary.get("visible_target_improved", False)), "audit_cost": _audit_cost(d), "working_harness": working.to_dict(), "working_policy_hash": policy_hash(working.typed_policy), "applied_patch_ids": list(applied)})
            hashes[f"{method}:{environment}:{seed}"] = policy_hash(working.typed_policy)
    return hashes


def run_online(manifest_path: str | Path, output_dir: str | Path, *, client: NativeOllamaClient | None = None) -> Path:
    root, output, manifest = _root(), Path(output_dir), _load(manifest_path); validate_online_source_lock(manifest, root=root); _verify_readiness(output, root)
    if (output / "ONLINE_PHASE_LOCK.json").exists(): raise FileExistsError("V3b online phase is already locked.")
    local = client or NativeOllamaClient(str(manifest["ollama"]["endpoint"])); _freeze_matches(manifest, output, local)
    if not (output / "ONLINE_INPUT_SEAL.json").exists(): raise OllamaPilotV3BProtocolError("V3b online phase requires a freeze and online input seal.")
    contracts = _contracts(root, manifest); ledger = _generate_ledger(manifest, output=output, client=local); _canonical(manifest, output, ledger, contracts); hashes = _persistent(manifest, output=output, ledger=ledger, contracts=contracts)
    write_online_phase_lock(output, manifest_hash=manifest_digest(manifest), candidate_slots=len(ledger), dynamic_decisions=len(ledger) * len(DYNAMIC_METHODS), static_measurements=len(ledger), trajectory_hashes=hashes)
    return output


def run_offline(manifest_path: str | Path, offline_path: str | Path, output_dir: str | Path) -> Path:
    """Reuse result accounting only after independently validating the V3b phase lock."""
    # Hidden label code is imported inside this function, after lock validation.
    root, output, manifest, offline = _root(), Path(output_dir), _load(manifest_path), _load(offline_path)
    validate_online_source_lock(manifest, root=root); validate_online_phase_lock(output, manifest_hash=manifest_digest(manifest), candidate_slots=30, dynamic_decisions=120, static_measurements=30)
    key, hidden = offline.get("hidden_master_seed"), offline.get("hidden_config")
    if not isinstance(key, str) or not isinstance(hidden, Mapping): raise OllamaPilotV3BProtocolError("Offline V3b configuration is malformed.")
    from evoaudit_mr.llm.ollama_pilot_v3b_offline import evaluate_hidden_event, final_exam, hidden_generator_source
    validate_hidden_reveal(_load(output / "HIDDEN_COMMITMENT.json"), key=key, hidden_config=hidden, hidden_source=hidden_generator_source(), environment_contracts=_contracts(root, manifest))
    # The V3 offline bookkeeping is agnostic to proposal IR; duplicate its compact final pipeline by temporarily using the same record shapes.
    return _offline_accounting(manifest, offline, output, key, evaluate_hidden_event, final_exam)


def _offline_accounting(manifest, offline, output, key, evaluate_hidden_event, final_exam) -> Path:
    """Parent-conditioned labels, final exams, Gate B/C, reports. Called only after lock."""
    # Reuse V3's tested accounting implementation is not safe because it imports its hidden generator.
    # This implementation deliberately labels only serialised online parents and patches.
    from evoaudit_mr.evaluation import mean_delta
    from evoaudit_mr.formal.metrics import confusion_from_pairs
    from evoaudit_mr.harness import execute
    ledger, canonical, online, static = _read(output / "candidate_ledger_online.jsonl"), _read(output / "canonical_decisions.jsonl"), _read(output / "online_decisions.jsonl"), _read(output / "static_snapshots.jsonl")
    hidden_cfg, mhash = offline["hidden_config"], manifest_digest(manifest)
    canonical_labels, method_labels = [], []
    for decision in canonical:
        if decision.get("proposal_status") != "executable": continue
        event = _event(_harness(decision["parent_harness"]), _patch(decision["patch"]), slot_id=str(decision["slot_id"]), environment=str(decision["environment"]), visible_tasks=(), heldout_tasks=(), track="canonical")
        label = evaluate_hidden_event(event, master_key=key, manifest_hash=mhash, per_bucket=int(hidden_cfg["per_bucket"])).to_dict()
        row = {"track": "canonical", "event_id": event.event_id, "slot_id": decision["slot_id"], "environment": decision["environment"], "failure_family": next(x["failure_family"] for x in ledger if x["slot_id"] == decision["slot_id"]), **label}
        canonical_labels.append(row)
        _append(output / "offline" / "canonical_labels.jsonl", row)
    for decision in online:
        if decision.get("proposal_status") != "executable" or "patch" not in decision: continue
        event = _event(_harness(decision["parent_harness"]), _patch(decision["patch"]), slot_id=str(decision["slot_id"]), environment=str(decision["environment"]), visible_tasks=(), heldout_tasks=(), track=str(decision["track"]))
        label = evaluate_hidden_event(event, master_key=key, manifest_hash=mhash, per_bucket=int(hidden_cfg["per_bucket"])).to_dict()
        row = {"track": decision["track"], "event_id": event.event_id, "slot_id": decision["slot_id"], "environment": decision["environment"], "method": decision["method"], "failure_family": decision["failure_family"], "proposal_status": decision["proposal_status"], "eligible": decision.get("eligible", False), "committed": decision.get("decision") == "commit", **label}
        method_labels.append(row); _append(output / "offline" / "method_parent_labels.jsonl", row)
    # Candidate gate results use method-specific parents and labels.
    candidate_metrics = []
    for method in DYNAMIC_METHODS:
        rows = [r for r in method_labels if r["method"] == method]
        pairs = [(bool(r["committed"]), bool(r["reliable"]), bool(r["safety_events"])) for r in rows]
        conf = confusion_from_pairs(pairs)
        candidate_metrics.append({"method": method, "n_events": len(pairs), **conf.to_dict(), "committed_reliable_per_30_slots": sum(a and b for a,b,_ in pairs), "committed_unreliable_per_30_slots": sum(a and not b for a,b,_ in pairs)})
    # Gate B is calculated with the prior pre-registered helper, and final metrics use working@T/static trajectories.
    gate_b = base._gate_b(ledger, canonical_labels, canonical, method_labels)
    final_rows = []
    final_sources = [(r["method"], r["environment"], int(r["trajectory_seed"]), _harness(r["working_harness"])) for r in online if int(r["round_index"]) == int(manifest["rounds"])]
    final_sources += [(r["method"], r["environment"], int(r["trajectory_seed"]), _harness(r["working_harness"])) for r in static if int(r["round_index"]) == int(manifest["rounds"])]
    for method, env, seed, harness in final_sources:
        metrics = base._final_metrics(harness, final_exam(env, trajectory_seed=seed, master_key=key, manifest_hash=mhash, per_bucket=int(hidden_cfg["final_per_bucket"])))
        final_rows.append({"method": method, "environment": env, "trajectory_seed": seed, **metrics})
    gate_c = base._gate_c(candidate_metrics, final_rows, gate_b_passed=bool(gate_b["passed"]))
    report_dir = output / "reports"; report_dir.mkdir(exist_ok=True)
    _write(report_dir / "gate_b.json", gate_b); _write(report_dir / "gate_c.json", gate_c); _write(report_dir / "candidate_metrics.json", candidate_metrics); _write(report_dir / "final_metrics.json", final_rows)
    _write(report_dir / "OFFLINE_SUMMARY.json", {"gate_b": gate_b, "gate_c": gate_c, "candidate_metrics": candidate_metrics, "final_metrics": final_rows,
        "statistical_unit": "candidate-parent event for gates; environment-seed trajectory for final metrics"})
    return seal_artifacts(output, manifest_hash=mhash)


def seal_v3_termination(v3_output_dir: str | Path) -> Path:
    """Record V3's terminal failure without modifying or inventing V3 responses."""
    output = Path(v3_output_dir); path = output / "V3_TERMINATION_SEAL.json"
    if path.exists(): raise FileExistsError("V3 termination seal already exists.")
    readiness = output / "COMPILER_READINESS_SEAL.json"; report = output / "COMPILER_READINESS_REPORT.md"
    if not readiness.exists(): raise FileNotFoundError("V3 readiness seal is required to terminate V3.")
    return _write(path, {"track": "Ollama Pilot V3", "status": "terminated_permanently", "reason": "freeze_preflight_schema_compatibility_failure", "facts": {"gate_a": "passed", "freeze_preflight": "failed", "proposal_calls": 0, "online_decisions": 0, "method_comparison": "unavailable"}, "non_actions": ["no retry", "no overwrite", "no fabricated failure response"], "preserved_artifacts": {"COMPILER_READINESS_SEAL.json": sha256_hex(readiness.read_bytes()), "COMPILER_READINESS_REPORT.md": sha256_hex(report.read_bytes()) if report.exists() else None}})


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--mode", required=True, choices=("seal-v3", "a1", "prepare-a2", "a2", "freeze", "online", "offline")); parser.add_argument("--manifest", default="configs/ollama_pilot_v3b_manifest.json"); parser.add_argument("--offline", default="configs/ollama_pilot_v3b_offline.json"); parser.add_argument("--output", default="artifacts_llm/ollama_pilot_v3b"); parser.add_argument("--v2-ledger"); parser.add_argument("--v3-output", default="artifacts_llm/ollama_pilot_v3")
    args = parser.parse_args()
    if args.mode == "seal-v3": path = seal_v3_termination(args.v3_output)
    elif args.mode == "a1": path = run_readiness(args.output, v2_ledger_path=args.v2_ledger)
    elif args.mode == "prepare-a2": path = prepare_a2(args.manifest, args.output)
    elif args.mode == "a2": path = run_a2(args.manifest, args.output)
    elif args.mode == "freeze": path = run_freeze(args.manifest, args.offline, args.output)
    elif args.mode == "online": path = run_online(args.manifest, args.output)
    else: path = run_offline(args.manifest, args.offline, args.output)
    print(path)


if __name__ == "__main__": main()
