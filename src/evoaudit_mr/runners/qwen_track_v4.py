"""Independent 80-slot Qwen proposal track with A3, B, and P gates.

V4 keeps the V3 artifacts untouched.  It uses multiple *public* parent
snapshots for canonical candidates and an external shared proposal stream for
method-conditioned persistent evolution.  Hidden labels are imported only in
``run_offline`` after an immutable online lock exists.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from evoaudit_mr.llm.client import Completion, LLMClientError, OpenAICompatibleClient
from evoaudit_mr.llm.config import load_config
from evoaudit_mr.llm.qwen_track_v4_protocol import (
    DYNAMIC_METHODS,
    PROTOCOL_VERSION,
    QwenTrackV4ProtocolError,
    canonical_json,
    classify_proposal_failure,
    environments,
    evaluate_gate_a3,
    evaluate_gate_b,
    evaluate_gate_p,
    family_ids,
    manifest_digest,
    public_parent,
    public_parent_state_report,
    scenario_rows,
    seal_artifacts,
    sha256_hex,
    source_hashes,
    validate_hidden_reveal,
    validate_online_phase_lock,
    validate_source_lock,
    write_hidden_commitment,
    write_online_phase_lock,
)
from evoaudit_mr.llm.v3_compiler import V3ProposalCompilationError, materialize_v3_patch
from evoaudit_mr.llm.v3_ir import V3IRValidationError, policy_hash, policy_signature
from evoaudit_mr.llm.v3b_ir import build_v3b_proposal_messages, parse_v3b_proposed_patch, parse_v3b_response_json
from evoaudit_mr.runners import ollama_pilot_v3 as base
from evoaudit_mr.runners import qwen_track_v1 as legacy


def _root() -> Path:
    return Path(__file__).resolve().parents[3]


def _load(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise QwenTrackV4ProtocolError(f"Expected JSON object at {path}.")
    return payload


def _write(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _append(path: Path, row: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(dict(row), sort_keys=True) + "\n")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _contracts(root: Path, manifest: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    raw = manifest.get("environment_contracts")
    if not isinstance(raw, Mapping):
        raise QwenTrackV4ProtocolError("V4 manifest lacks environment contracts.")
    return {environment: _load(root / str(raw[environment])) for environment in environments(manifest)}


def _visible_tasks(scenario: Mapping[str, object], *, count: int) -> tuple:
    environment = str(scenario["environment"])
    base_index = int(scenario["trajectory_seed"]) * 10_000 + int(scenario["round_index"]) * 100
    tasks = tuple(
        base._task(environment, str(scenario["visible_profile"]), base_index + offset, prefix=f"qwen-v4-{scenario['slot_id']}")
        for offset in range(count)
    )
    modifier = str(scenario.get("task_modifier", "none"))
    if modifier == "none":
        return tasks
    if modifier == "with_public_tools_declared" and environment == "AliasTool":
        from evoaudit_mr.envs.aliastool import with_public_tools_declared

        return tuple(with_public_tools_declared(task) for task in tasks)
    raise QwenTrackV4ProtocolError(f"Unsupported public task modifier {modifier!r}.")


def _visible_traces(parent, scenario: Mapping[str, object], tasks: Sequence[object]) -> list[dict[str, object]]:
    from evoaudit_mr.harness import execute

    return [
        base._visible_trace(task, execute(parent, task), note=str(scenario["public_context_note"]))
        for task in tasks
    ]


def _persistent_initial_parent(manifest: Mapping[str, Any], environment: str):
    raw = manifest.get("persistent_initial_parent_state")
    if not isinstance(raw, Mapping) or not isinstance(raw.get(environment), str):
        raise QwenTrackV4ProtocolError("V4 manifest lacks a persistent initial parent state.")
    return public_parent(manifest, {"environment": environment, "parent_state": raw[environment]})


def _scenario_context(scenario: Mapping[str, object], *, task_count: int):
    parent = public_parent(_ACTIVE_MANIFEST.get(), scenario)
    tasks = _visible_tasks(scenario, count=task_count)
    traces = _visible_traces(parent, scenario, tasks)
    messages, trace_ids, schema = build_v3b_proposal_messages(
        environment=str(scenario["environment"]), parent_policy=parent.typed_policy, visible_traces=traces
    )
    return parent, tasks, traces, messages, trace_ids, schema


class _ManifestContext:
    """Small explicit context holder avoiding hidden globals in online/offline logic."""

    def __init__(self) -> None:
        self.value: Mapping[str, Any] | None = None

    def set(self, manifest: Mapping[str, Any]) -> None:
        self.value = manifest

    def get(self) -> Mapping[str, Any]:
        if self.value is None:
            raise QwenTrackV4ProtocolError("No active V4 manifest context.")
        return self.value


_ACTIVE_MANIFEST = _ManifestContext()


def _a3_scenarios(manifest: Mapping[str, Any]) -> tuple[dict[str, object], ...]:
    definitions, states = manifest.get("public_failure_families"), manifest.get("parent_state_bank")
    if not isinstance(definitions, Mapping) or not isinstance(states, Mapping):
        raise QwenTrackV4ProtocolError("V4 manifest lacks public A3 definitions.")
    seed = int(manifest["a3_seed"])
    rows: list[dict[str, object]] = []
    for environment in environments(manifest):
        for index, family_id in enumerate(family_ids(manifest), start=1):
            definition = definitions[environment][family_id]
            rows.append(
                {
                    "case_id": f"qwen-v4-a3-{environment.lower()}-{family_id.lower()}",
                    "slot_id": f"qwen-v4-a3-{environment.lower()}-{family_id.lower()}",
                    "environment": environment,
                    "trajectory_seed": seed,
                    "round_index": index,
                    "family_id": family_id,
                    "failure_family": str(definition["name"]),
                    "parent_state": str(definition["parent_state"]),
                    "visible_profile": str(definition["profile"]),
                    "task_modifier": str(definition.get("task_modifier", "none")),
                    "public_context_note": str(definition.get("public_context_note", "")),
                }
            )
    expected = int(manifest["gates"]["A3"]["cases"])
    if len(rows) != expected:
        raise QwenTrackV4ProtocolError("A3 case count must match the pre-registered threshold.")
    return tuple(rows)


def _accounting_smoke() -> dict[str, int]:
    from evoaudit_mr.llm.proposal_track_accounting import validate_label_cardinalities

    ledger = [
        {"slot_id": "smoke-a", "environment": "AliasTool", "trajectory_seed": 1, "proposal_status": "executable"},
        {"slot_id": "smoke-b", "environment": "PermissionPath", "trajectory_seed": 2, "proposal_status": "executable"},
    ]
    canonical = [{"event_id": "canonical-smoke-a", "slot_id": "smoke-a"}, {"event_id": "canonical-smoke-b", "slot_id": "smoke-b"}]
    parents = [
        {"event_id": f"persistent-{method}-{slot}", "slot_id": slot, "method": method}
        for slot in ("smoke-a", "smoke-b")
        for method in DYNAMIC_METHODS
    ]
    return validate_label_cardinalities(ledger, canonical, parents, dynamic_methods=DYNAMIC_METHODS).to_dict()


def run_a1(manifest_path: str | Path, model_config_path: str | Path, output_dir: str | Path) -> Path:
    root, manifest, output = _root(), _load(manifest_path), Path(output_dir)
    validate_source_lock(manifest, root=root)
    config = load_config(model_config_path)
    if config.proposal_schema_version != "typed-policy-ir-v3b":
        raise QwenTrackV4ProtocolError("V4 requires the typed-policy-ir-v3b proposal contract.")
    seal_path = output / "COMPILER_ACCOUNTING_READINESS_SEAL.json"
    if seal_path.exists():
        raise FileExistsError("V4 A1 readiness seal already exists.")
    output.mkdir(parents=True, exist_ok=True)
    _ACTIVE_MANIFEST.set(manifest)
    # Public compiler coverage is intentionally inherited from a frozen public corpus only.
    v2_ledger = root / "artifacts_llm" / "ollama_pilot_v2" / "candidate_ledger" / "candidate_ledger_online.jsonl"
    corpus = base._public_corpus_rows(v2_ledger)
    annotations = base._build_public_annotations(corpus)
    corpus_path, annotations_path = output / "V2_PUBLIC_COMPILER_CORPUS.jsonl", output / "V2_PUBLIC_IR_ANNOTATIONS.jsonl"
    for row in corpus:
        _append(corpus_path, row)
    for row in annotations:
        _append(annotations_path, row)
    state_report = public_parent_state_report(manifest)
    from evoaudit_mr.harness import execute

    for scenario in scenario_rows(manifest):
        parent = public_parent(manifest, scenario)
        for task in _visible_tasks(scenario, count=int(manifest["evolve_tasks_per_slot"])):
            execute(parent, task)
    report = {
        "typed_policy_readiness": base._run_readiness_suite(root, _contracts(root, manifest), annotations),
        "parent_state_readiness": state_report,
        "accounting_smoke": _accounting_smoke(),
        "model_config_sha256": config.fingerprint,
    }
    report_path = _write(output / "COMPILER_ACCOUNTING_READINESS_REPORT.json", report)
    return _write(
        seal_path,
        {
            "protocol_version": PROTOCOL_VERSION,
            "gate": "A1",
            "manifest_sha256": manifest_digest(manifest),
            "model_config_sha256": config.fingerprint,
            "v2_public_source_sha256": sha256_hex(v2_ledger.read_bytes()),
            "corpus_sha256": sha256_hex(corpus_path.read_bytes()),
            "annotations_sha256": sha256_hex(annotations_path.read_bytes()),
            "report_sha256": sha256_hex(report_path.read_bytes()),
            "source_hashes": source_hashes(root),
            "readiness": report,
        },
    )


def _verify_a1(output: Path, root: Path) -> None:
    path = output / "COMPILER_ACCOUNTING_READINESS_SEAL.json"
    if not path.exists():
        raise QwenTrackV4ProtocolError("V4 requires a completed A1 readiness seal.")
    if _load(path).get("source_hashes") != source_hashes(root):
        raise QwenTrackV4ProtocolError("V4 source changed after A1.")


def prepare_a3(manifest_path: str | Path, model_config_path: str | Path, offline_path: str | Path, output_dir: str | Path) -> Path:
    root, manifest, output = _root(), _load(manifest_path), Path(output_dir)
    validate_source_lock(manifest, root=root)
    _verify_a1(output, root)
    path = output / "QWEN_A3_INPUT_SEAL.json"
    if path.exists():
        raise FileExistsError("V4 A3 input seal already exists.")
    config, offline = load_config(model_config_path), _load(offline_path)
    key, hidden = offline.get("hidden_master_seed"), offline.get("hidden_config")
    if not isinstance(key, str) or len(key) != 64 or not isinstance(hidden, Mapping):
        raise QwenTrackV4ProtocolError("Malformed V4 offline config.")
    from evoaudit_mr.llm.qwen_track_v1_offline import hidden_generator_source

    write_hidden_commitment(
        output,
        key=key,
        hidden_config=hidden,
        hidden_source=hidden_generator_source(),
        environment_contracts=_contracts(root, manifest),
    )
    _ACTIVE_MANIFEST.set(manifest)
    cases = []
    for scenario in _a3_scenarios(manifest):
        parent, tasks, traces, messages, trace_ids, schema = _scenario_context(scenario, task_count=1)
        cases.append(
            {
                **scenario,
                "parent_policy_sha256": sha256_hex(canonical_json(parent.typed_policy)),
                "tasks_sha256": sha256_hex(canonical_json([task.to_dict() for task in tasks])),
                "trace_sha256": sha256_hex(canonical_json(traces)),
                "prompt_sha256": sha256_hex(canonical_json(messages)),
                "schema_sha256": sha256_hex(canonical_json(schema)),
                "allowed_evidence_trace_ids": list(trace_ids),
            }
        )
    return _write(
        path,
        {
            "protocol_version": PROTOCOL_VERSION,
            "gate": "A3",
            "status": "prepared",
            "manifest_sha256": manifest_digest(manifest),
            "model_config": config.to_dict(),
            "model_config_sha256": config.fingerprint,
            "source_hashes": source_hashes(root),
            "cases": cases,
            "transport_retry_rule": "up to two retries only when no completion is received",
            "content_failure_rule": "a received invalid completion is recorded without retry",
        },
    )


def run_a3(manifest_path: str | Path, model_config_path: str | Path, output_dir: str | Path, *, client: OpenAICompatibleClient | None = None) -> Path:
    root, manifest, output = _root(), _load(manifest_path), Path(output_dir)
    validate_source_lock(manifest, root=root)
    _verify_a1(output, root)
    seal, config = _load(output / "QWEN_A3_INPUT_SEAL.json"), load_config(model_config_path)
    if seal.get("model_config_sha256") != config.fingerprint or seal.get("source_hashes") != source_hashes(root):
        raise QwenTrackV4ProtocolError("V4 A3 inputs differ from their frozen configuration.")
    report_path, raw_path = output / "QWEN_A3_REPORT.json", output / "qwen_a3_outputs.jsonl"
    if report_path.exists() or raw_path.exists():
        raise FileExistsError("V4 A3 outputs are immutable and already exist.")
    _ACTIVE_MANIFEST.set(manifest)
    local, results = client or OpenAICompatibleClient(config), []
    for scenario in _a3_scenarios(manifest):
        parent, _, _, messages, trace_ids, schema = _scenario_context(scenario, task_count=1)
        row: dict[str, object] = {
            **scenario,
            "status": "api_transport_failed",
            "prompt_sha256": sha256_hex(canonical_json(messages)),
            "schema_sha256": sha256_hex(canonical_json(schema)),
        }
        try:
            completion = legacy._request_once_or_transport_retry(local, messages, output=output, logical_id=str(scenario["case_id"]), phase="a3")
            row.update({"raw_response": completion.content, "response_sha256": sha256_hex(completion.content), "provider_reported_model": completion.model, "usage": dict(completion.usage)})
            proposal = parse_v3b_response_json(completion.content, environment=str(scenario["environment"]), allowed_evidence_ids=trace_ids)
            patch = materialize_v3_patch(proposal.to_compiler_proposal(), environment=str(scenario["environment"]), patch_id=f"{scenario['case_id']}-patch", parent=parent)
            signature = policy_signature(proposal.to_compiler_proposal())
            row.update({"model_proposal": proposal.to_model_dict(), "typed_policy_delta_signature": signature, "compiled_patch_sha256": sha256_hex(canonical_json(patch.to_dict()))})
            row["status"] = "semantic_noop" if patch.diff["typed_policy_before"] == patch.diff["typed_policy_after"] else "passed"
        except (LLMClientError, V3IRValidationError, V3ProposalCompilationError, ValueError) as exc:
            row.update({"status": classify_proposal_failure(exc), "failure_type": type(exc).__name__, "failure_message": str(exc)})
        _append(raw_path, row)
        results.append(row)
    gate = evaluate_gate_a3(manifest, results)
    return _write(report_path, {"protocol_version": PROTOCOL_VERSION, **gate, "outputs_sha256": sha256_hex(raw_path.read_bytes()), "results": results})


def run_freeze(manifest_path: str | Path, model_config_path: str | Path, output_dir: str | Path) -> Path:
    root, manifest, output = _root(), _load(manifest_path), Path(output_dir)
    validate_source_lock(manifest, root=root)
    _verify_a1(output, root)
    report, config = _load(output / "QWEN_A3_REPORT.json"), load_config(model_config_path)
    if not report.get("passed"):
        raise QwenTrackV4ProtocolError("V4 A3 failed; formal proposal slots must not run.")
    freeze = output / "QWEN_FREEZE.json"
    if freeze.exists():
        raise FileExistsError("V4 model freeze already exists.")
    models = sorted({str(row["provider_reported_model"]) for row in report["results"] if row.get("provider_reported_model")})
    _write(
        freeze,
        {
            "freeze_version": "qwen-track-v4-freeze-v1",
            "manifest_sha256": manifest_digest(manifest),
            "model_config": config.to_dict(),
            "model_config_sha256": config.fingerprint,
            "provider_reported_models": models,
            "a3_report_sha256": sha256_hex((output / "QWEN_A3_REPORT.json").read_bytes()),
            "source_hashes": source_hashes(root),
            "one_logical_proposal_per_slot": True,
        },
    )
    _ACTIVE_MANIFEST.set(manifest)
    contexts = []
    for scenario in scenario_rows(manifest):
        parent, tasks, traces, messages, _, _ = _scenario_context(scenario, task_count=int(manifest["evolve_tasks_per_slot"]))
        contexts.append({"slot_id": scenario["slot_id"], "context_sha256": sha256_hex(canonical_json({"scenario": scenario, "parent": parent.typed_policy, "tasks": [task.to_dict() for task in tasks], "traces": traces, "messages": messages}))})
    return _write(
        output / "ONLINE_INPUT_SEAL.json",
        {
            "protocol_version": PROTOCOL_VERSION,
            "manifest": manifest,
            "manifest_sha256": manifest_digest(manifest),
            "model_config_sha256": config.fingerprint,
            "contexts": contexts,
            "source_hashes": source_hashes(root),
            "statistical_units": {
                "unique_canonical_candidates": "executable ledger entries",
                "method_parent_decision_events": "executable candidates x 4 dynamic methods",
                "trajectory_clusters": 10,
                "terminal_method_records": 50,
            },
        },
    )


def _generate_ledger(manifest: Mapping[str, Any], *, output: Path, client: OpenAICompatibleClient) -> list[dict[str, Any]]:
    path = output / "candidate_ledger_online.jsonl"
    if path.exists():
        raise FileExistsError("V4 candidate ledger already exists.")
    _ACTIVE_MANIFEST.set(manifest)
    rows: list[dict[str, Any]] = []
    for scenario in scenario_rows(manifest):
        parent, tasks, traces, messages, trace_ids, schema = _scenario_context(scenario, task_count=int(manifest["evolve_tasks_per_slot"]))
        row: dict[str, Any] = {
            **scenario,
            "canonical_parent": parent.to_dict(),
            "visible_tasks": [task.to_dict() for task in tasks],
            "visible_traces": traces,
            "prompt_sha256": sha256_hex(canonical_json(messages)),
            "schema_sha256": sha256_hex(canonical_json(schema)),
            "proposal_status": "api_transport_failed",
        }
        try:
            completion = legacy._request_once_or_transport_retry(client, messages, output=output, logical_id=str(scenario["slot_id"]), phase="online")
            row.update({"raw_proposal": completion.content, "response_sha256": sha256_hex(completion.content), "provider_reported_model": completion.model, "usage": dict(completion.usage)})
            proposal = parse_v3b_response_json(completion.content, environment=str(scenario["environment"]), allowed_evidence_ids=trace_ids)
            patch = materialize_v3_patch(proposal.to_compiler_proposal(), environment=str(scenario["environment"]), patch_id=f"{scenario['slot_id']}-patch", parent=parent)
            event = base._event(parent, patch, slot_id=str(scenario["slot_id"]), environment=str(scenario["environment"]), visible_tasks=tasks, heldout_tasks=(), track="qwen-v4-canonical")
            _, delta, eligible = base._visible_precondition(event)
            row.update({"model_proposal": proposal.to_model_dict(), "patch": patch.to_dict(), "typed_policy_delta_signature": policy_signature(proposal.to_compiler_proposal()), "canonical_eligible": eligible, "visible_delta_canonical": delta})
            row["proposal_status"] = "semantic_noop" if patch.diff["typed_policy_before"] == patch.diff["typed_policy_after"] else "executable"
        except (LLMClientError, V3IRValidationError, V3ProposalCompilationError, ValueError) as exc:
            row.update({"proposal_status": classify_proposal_failure(exc), "failure_type": type(exc).__name__, "failure_message": str(exc)})
        _append(path, row)
        rows.append(row)
    return rows


def _online_decisions(manifest: Mapping[str, Any], *, output: Path, ledger: Sequence[Mapping[str, Any]], contracts: Mapping[str, Mapping[str, Any]]) -> dict[str, str]:
    from evoaudit_mr.evolution.transforms import apply_patch
    from evoaudit_mr.formal.catalogue import fixed_validation_tasks

    envs = environments(manifest)
    validation = {environment: fixed_validation_tasks(environment, count=int(manifest["validation_tasks"]), seed=int(manifest["validation_seed"]) + index) for index, environment in enumerate(envs)}
    canonical_path, online_path, static_path = output / "canonical_decisions.jsonl", output / "online_decisions.jsonl", output / "static_snapshots.jsonl"
    for row in ledger:
        for method in DYNAMIC_METHODS:
            common = {"track": "canonical_paired", "slot_id": row["slot_id"], "environment": row["environment"], "method": method, "proposal_status": row["proposal_status"]}
            if row["proposal_status"] != "executable":
                _append(canonical_path, {**common, "event_id": f"canonical-{method}-{row['slot_id']}", "decision": "noop", "eligible": False, "audit_cost": {"logical_pairs": 0, "tool_calls": 0}})
                continue
            parent, patch = base._harness_from_dict(row["canonical_parent"]), base._patch_from_dict(row["patch"])
            event = base._event(parent, patch, slot_id=str(row["slot_id"]), environment=str(row["environment"]), visible_tasks=_visible_tasks(row, count=int(manifest["evolve_tasks_per_slot"])), heldout_tasks=validation[str(row["environment"])], track="canonical")
            decision = base._decide(event, method=method, contract=contracts[event.environment], seed=int(manifest["audit_seed"]) + sum(map(ord, f"canonical-{method}-{row['slot_id']}")), budget_pairs=int(manifest["audit_budget_pairs"]))
            _append(canonical_path, {**common, "event_id": event.event_id, "decision": decision.decision, "eligible": bool(decision.bucket_summary.get("visible_target_improved", False)), "parent_harness": parent.to_dict(), "patch": patch.to_dict(), "audit_cost": base._audit_cost(decision)})
    grouped: dict[tuple[str, int], list[Mapping[str, Any]]] = {}
    for row in ledger:
        grouped.setdefault((str(row["environment"]), int(row["trajectory_seed"])), []).append(row)
    hashes: dict[str, str] = {}
    for (environment, seed), rows in sorted(grouped.items()):
        rows.sort(key=lambda row: int(row["round_index"]))
        initial = _persistent_initial_parent(manifest, environment)
        for row in rows:
            _append(static_path, {"method": "static", "environment": environment, "trajectory_seed": seed, "round_index": row["round_index"], "slot_id": row["slot_id"], "working_harness": initial.to_dict(), "working_policy_hash": policy_hash(initial.typed_policy)})
        for method in DYNAMIC_METHODS:
            working = initial
            for row in rows:
                common = {"track": "persistent", "slot_id": row["slot_id"], "environment": environment, "trajectory_seed": seed, "round_index": row["round_index"], "method": method, "proposal_status": row["proposal_status"], "parent_harness": working.to_dict()}
                if row["proposal_status"] != "executable":
                    _append(online_path, {**common, "event_id": f"persistent-{method}-{row['slot_id']}", "decision": "noop", "eligible": False, "working_harness": working.to_dict(), "audit_cost": {"logical_pairs": 0, "tool_calls": 0}})
                    continue
                try:
                    proposal = parse_v3b_proposed_patch(row["model_proposal"], environment=environment, allowed_evidence_ids=tuple(row["model_proposal"]["evidence_trace_ids"]))
                    patch = materialize_v3_patch(proposal.to_compiler_proposal(), environment=environment, patch_id=row["patch"]["patch_id"], parent=working)
                except (V3IRValidationError, V3ProposalCompilationError, ValueError) as exc:
                    _append(online_path, {**common, "event_id": f"persistent-{method}-{row['slot_id']}", "decision": "reject", "eligible": False, "parent_materialization_failed": True, "materialization_error": str(exc), "working_harness": working.to_dict(), "audit_cost": {"logical_pairs": 0, "tool_calls": 0}})
                    continue
                event = base._event(working, patch, slot_id=str(row["slot_id"]), environment=environment, visible_tasks=_visible_tasks(row, count=int(manifest["evolve_tasks_per_slot"])), heldout_tasks=validation[environment], track=f"persistent-{method}")
                decision = base._decide(event, method=method, contract=contracts[environment], seed=int(manifest["audit_seed"]) + sum(map(ord, f"persistent-{method}-{row['slot_id']}")), budget_pairs=int(manifest["audit_budget_pairs"]))
                candidate = apply_patch(working, patch)
                if decision.committed:
                    working = candidate
                _append(online_path, {**common, "event_id": event.event_id, "patch": patch.to_dict(), "decision": decision.decision, "eligible": bool(decision.bucket_summary.get("visible_target_improved", False)), "working_harness": working.to_dict(), "audit_cost": base._audit_cost(decision)})
            hashes[f"{method}:{environment}:{seed}"] = policy_hash(working.typed_policy)
    return hashes


def run_online(manifest_path: str | Path, model_config_path: str | Path, output_dir: str | Path, *, client: OpenAICompatibleClient | None = None) -> Path:
    root, manifest, output = _root(), _load(manifest_path), Path(output_dir)
    validate_source_lock(manifest, root=root)
    _verify_a1(output, root)
    if not (output / "QWEN_FREEZE.json").exists() or not (output / "ONLINE_INPUT_SEAL.json").exists():
        raise QwenTrackV4ProtocolError("V4 online phase requires a completed model freeze.")
    if (output / "ONLINE_PHASE_LOCK.json").exists():
        raise FileExistsError("V4 online phase is already locked.")
    config = load_config(model_config_path)
    ledger = _generate_ledger(manifest, output=output, client=client or OpenAICompatibleClient(config))
    hashes = _online_decisions(manifest, output=output, ledger=ledger, contracts=_contracts(root, manifest))
    write_online_phase_lock(output, manifest_hash=manifest_digest(manifest), logical_slots=len(ledger), dynamic_decisions=len(ledger) * len(DYNAMIC_METHODS), static_measurements=len(ledger), trajectory_hashes=hashes)
    return output


def _metric(rows: Sequence[Mapping[str, Any]]) -> dict[str, object]:
    pairs = [(bool(row["committed"]), bool(row["reliable"])) for row in rows]
    tp = sum(committed and reliable for committed, reliable in pairs)
    fp = sum(committed and not reliable for committed, reliable in pairs)
    fn = sum(not committed and reliable for committed, reliable in pairs)
    tn = sum(not committed and not reliable for committed, reliable in pairs)
    return {"n": len(pairs), "tp": tp, "fp": fp, "tn": tn, "fn": fn, "far": fp / (fp + tn) if fp + tn else None, "fdr": fp / (tp + fp) if tp + fp else None, "uur": tp / (tp + fn) if tp + fn else None}


def run_offline(manifest_path: str | Path, offline_path: str | Path, output_dir: str | Path) -> Path:
    """Reveal committed hidden labels and stop before inferential claims if B/P fail."""
    root, manifest, output, offline = _root(), _load(manifest_path), Path(output_dir), _load(offline_path)
    validate_source_lock(manifest, root=root)
    slots = scenario_rows(manifest)
    validate_online_phase_lock(output, manifest_hash=manifest_digest(manifest), logical_slots=len(slots), dynamic_decisions=len(slots) * len(DYNAMIC_METHODS), static_measurements=len(slots))
    key, hidden = offline.get("hidden_master_seed"), offline.get("hidden_config")
    if not isinstance(key, str) or not isinstance(hidden, Mapping):
        raise QwenTrackV4ProtocolError("Malformed V4 offline reveal.")
    from evoaudit_mr.llm.qwen_track_v1_offline import evaluate_hidden_event, final_exam, hidden_generator_source

    validate_hidden_reveal(_load(output / "HIDDEN_COMMITMENT.json"), key=key, hidden_config=hidden, hidden_source=hidden_generator_source(), environment_contracts=_contracts(root, manifest))
    ledger = _read_jsonl(output / "candidate_ledger_online.jsonl")
    canonical = _read_jsonl(output / "canonical_decisions.jsonl")
    online = _read_jsonl(output / "online_decisions.jsonl")
    static = _read_jsonl(output / "static_snapshots.jsonl")
    if (output / "canonical_labels_offline.jsonl").exists() or (output / "method_parent_labels_offline.jsonl").exists():
        raise FileExistsError("V4 offline labels already exist.")
    manifest_hash, labels, parents = manifest_digest(manifest), [], []
    for row in ledger:
        if row.get("proposal_status") != "executable":
            continue
        parent = base._harness_from_dict(row["canonical_parent"])
        patch = base._patch_from_dict(row["patch"])
        event = base._event(parent, patch, slot_id=str(row["slot_id"]), environment=str(row["environment"]), visible_tasks=(), heldout_tasks=(), track="canonical")
        label = {"event_id": event.event_id, "slot_id": row["slot_id"], "environment": row["environment"], "failure_family": row["failure_family"], **evaluate_hidden_event(event, master_key=key, manifest_hash=manifest_hash, per_bucket=int(hidden["per_bucket"])).to_dict()}
        labels.append(label)
        _append(output / "canonical_labels_offline.jsonl", label)
    for row in online:
        if row.get("proposal_status") != "executable":
            continue
        base_row: dict[str, Any] = {"event_id": row["event_id"], "slot_id": row["slot_id"], "environment": row["environment"], "trajectory_seed": row["trajectory_seed"], "method": row["method"], "committed": row["decision"] == "commit", "eligible": bool(row.get("eligible")), "proposal_status": row["proposal_status"]}
        if row.get("parent_materialization_failed"):
            label = {**base_row, "reliable": False, "reasons": ["parent_materialization_failed"], "safety_events": [], "label_status": "fail_closed"}
        else:
            event = base._event(base._harness_from_dict(row["parent_harness"]), base._patch_from_dict(row["patch"]), slot_id=str(row["slot_id"]), environment=str(row["environment"]), visible_tasks=(), heldout_tasks=(), track="persistent")
            label = {**base_row, **evaluate_hidden_event(event, master_key=key, manifest_hash=manifest_hash, per_bucket=int(hidden["per_bucket"])).to_dict(), "label_status": "evaluated"}
        parents.append(label)
        _append(output / "method_parent_labels_offline.jsonl", label)
    gate_b = evaluate_gate_b(manifest, ledger, labels, canonical, parents)
    gate_p = evaluate_gate_p(manifest, online)
    labels_by_slot = {str(label["slot_id"]): label for label in labels}
    canonical_metrics = []
    for method in DYNAMIC_METHODS:
        rows = [{**labels_by_slot[str(row["slot_id"])], "committed": row["decision"] == "commit"} for row in canonical if row.get("proposal_status") == "executable" and row.get("method") == method]
        canonical_metrics.append({"method": method, **_metric(rows)})
    parent_metrics = [{"method": method, **_metric([row for row in parents if row["method"] == method])} for method in DYNAMIC_METHODS]
    finals = []
    for row in [item for item in online if int(item["round_index"]) == int(manifest["rounds"])]:
        probes = final_exam(str(row["environment"]), trajectory_seed=int(row["trajectory_seed"]), master_key=key, manifest_hash=manifest_hash, per_bucket=int(hidden["final_per_bucket"]))
        finals.append({"method": row["method"], "environment": row["environment"], "trajectory_seed": row["trajectory_seed"], **base._final_metrics(base._harness_from_dict(row["working_harness"]), probes)})
    for row in [item for item in static if int(item["round_index"]) == int(manifest["rounds"])]:
        probes = final_exam(str(row["environment"]), trajectory_seed=int(row["trajectory_seed"]), master_key=key, manifest_hash=manifest_hash, per_bucket=int(hidden["final_per_bucket"]))
        finals.append({"method": "static", "environment": row["environment"], "trajectory_seed": row["trajectory_seed"], **base._final_metrics(base._harness_from_dict(row["working_harness"]), probes)})
    report = output / "reports"
    report.mkdir(exist_ok=True)
    _write(report / "gate_b.json", gate_b)
    _write(report / "gate_p.json", gate_p)
    _write(report / "canonical_candidate_metrics.json", canonical_metrics)
    _write(report / "method_parent_metrics.json", parent_metrics)
    _write(report / "trajectory_metrics.json", finals)
    _write(report / "final_analysis_status.json", {"status": "testable" if gate_b["passed"] and gate_p["passed"] else "not_testable", "gate_b_passed": gate_b["passed"], "gate_p_passed": gate_p["passed"], "trajectory_clusters": len({(row["environment"], row["trajectory_seed"]) for row in finals}), "terminal_method_records": len(finals)})
    return seal_artifacts(output, manifest_hash=manifest_hash)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("a1", "schedule", "prepare-a3", "a3", "freeze", "online", "offline"), required=True)
    parser.add_argument("--manifest", default="configs/qwen_track_v4_manifest_draft.json")
    parser.add_argument("--model-config", default="configs/qwen_track_v4_model.json")
    parser.add_argument("--offline", default="configs/qwen_track_v4_offline.json")
    parser.add_argument("--output", default="artifacts_llm/qwen_track_v4")
    args = parser.parse_args()
    if args.mode == "schedule":
        print(json.dumps(scenario_rows(_load(args.manifest)), indent=2))
        return
    if args.mode == "a1":
        path = run_a1(args.manifest, args.model_config, args.output)
    elif args.mode == "prepare-a3":
        path = prepare_a3(args.manifest, args.model_config, args.offline, args.output)
    elif args.mode == "a3":
        path = run_a3(args.manifest, args.model_config, args.output)
    elif args.mode == "freeze":
        path = run_freeze(args.manifest, args.model_config, args.output)
    elif args.mode == "online":
        path = run_online(args.manifest, args.model_config, args.output)
    else:
        path = run_offline(args.manifest, args.offline, args.output)
    print(path)


if __name__ == "__main__":
    main()
