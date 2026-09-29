"""Public protocol primitives for the independent Qwen Track V4.

V4 is deliberately separate from the sealed V3 run.  It defines an 80-slot,
multi-parent-state proposal stream and the pre-registered A3/B/P gates.  This
module contains no hidden evaluator and no provider client.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from hashlib import sha256
import hmac
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from evoaudit_mr.llm.client import LLMClientError
from evoaudit_mr.llm.proposal_track_accounting import validate_label_cardinalities
from evoaudit_mr.llm.v3_compiler import V3ProposalCompilationError
from evoaudit_mr.llm.v3_ir import V3IRValidationError, validate_typed_policy
from evoaudit_mr.types import Harness


PROTOCOL_VERSION = "qwen-llm-proposal-track-v4"
DYNAMIC_METHODS = ("direct_commit", "rsea_fixed_validation", "fixed_random_audit", "evoaudit_mr")


class QwenTrackV4ProtocolError(ValueError):
    """A V4 manifest, ledger, or gate input violates a public invariant."""


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_hex(value: str | bytes) -> str:
    return sha256(value.encode("utf-8") if isinstance(value, str) else value).hexdigest()


def hmac_hex(key: str, value: str | bytes) -> str:
    raw = value.encode("utf-8") if isinstance(value, str) else value
    return hmac.new(bytes.fromhex(key), raw, sha256).hexdigest()


def manifest_digest(manifest: Mapping[str, Any]) -> str:
    return sha256_hex(canonical_json(dict(manifest)))


def source_hashes(root: Path) -> dict[str, str]:
    """Hash V4 and every common source module that can affect its outcome."""
    from evoaudit_mr.llm.qwen_track_v1_protocol import source_hashes as common_source_hashes

    hashes = dict(common_source_hashes(root))
    for relative in (
        "src/evoaudit_mr/llm/qwen_track_v4_protocol.py",
        "src/evoaudit_mr/runners/qwen_track_v4.py",
    ):
        path = root / relative
        if not path.exists():
            raise QwenTrackV4ProtocolError(f"V4 source is missing: {relative}")
        hashes[relative] = sha256_hex(path.read_bytes())
    return hashes


def validate_source_lock(manifest: Mapping[str, Any], *, root: Path) -> None:
    expected = manifest.get("source_hashes")
    if not isinstance(expected, Mapping) or dict(expected) != source_hashes(root):
        raise QwenTrackV4ProtocolError("V4 sources differ from the frozen manifest.")


def write_hidden_commitment(
    output: Path,
    *,
    key: str,
    hidden_config: Mapping[str, Any],
    hidden_source: str,
    environment_contracts: Mapping[str, Any],
) -> Path:
    path = output / "HIDDEN_COMMITMENT.json"
    if path.exists():
        raise FileExistsError("V4 hidden commitment already exists.")
    payload = {
        "protocol_version": PROTOCOL_VERSION,
        "seed_commitment": sha256_hex(key),
        "hidden_config_commitment": hmac_hex(key, canonical_json(dict(hidden_config))),
        "generator_source_hash": sha256_hex(hidden_source),
        "environment_contract_hash": sha256_hex(canonical_json(dict(environment_contracts))),
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def validate_hidden_reveal(
    commitment: Mapping[str, Any],
    *,
    key: str,
    hidden_config: Mapping[str, Any],
    hidden_source: str,
    environment_contracts: Mapping[str, Any],
) -> None:
    expected = {
        "protocol_version": PROTOCOL_VERSION,
        "seed_commitment": sha256_hex(key),
        "hidden_config_commitment": hmac_hex(key, canonical_json(dict(hidden_config))),
        "generator_source_hash": sha256_hex(hidden_source),
        "environment_contract_hash": sha256_hex(canonical_json(dict(environment_contracts))),
    }
    if any(commitment.get(name) != value for name, value in expected.items()):
        raise QwenTrackV4ProtocolError("Offline V4 hidden reveal does not match its commitment.")


def _as_tuple(raw: object, *, name: str) -> tuple[str, ...]:
    if not isinstance(raw, list) or not raw or any(not isinstance(item, str) or not item for item in raw):
        raise QwenTrackV4ProtocolError(f"{name} must be a non-empty string list.")
    if len(set(raw)) != len(raw):
        raise QwenTrackV4ProtocolError(f"{name} must not contain duplicates.")
    return tuple(raw)


def environments(manifest: Mapping[str, Any]) -> tuple[str, ...]:
    values = _as_tuple(manifest.get("environments"), name="environments")
    if set(values) != {"AliasTool", "PermissionPath"}:
        raise QwenTrackV4ProtocolError("V4 requires AliasTool and PermissionPath exactly.")
    return values


def family_ids(manifest: Mapping[str, Any]) -> tuple[str, ...]:
    values = _as_tuple(manifest.get("family_ids"), name="family_ids")
    if len(values) != 8:
        raise QwenTrackV4ProtocolError("V4 requires eight public failure families.")
    if int(manifest.get("rounds", 0)) != len(values):
        raise QwenTrackV4ProtocolError("rounds must equal the number of V4 failure families.")
    return values


def scenario_rows(manifest: Mapping[str, Any]) -> tuple[dict[str, object], ...]:
    """Create a fixed 2 x 5 x 8 public schedule before any model call."""
    envs, families = environments(manifest), family_ids(manifest)
    seeds_raw = manifest.get("trajectory_seeds")
    if not isinstance(seeds_raw, list) or len(seeds_raw) != 5:
        raise QwenTrackV4ProtocolError("V4 requires five trajectory seeds.")
    seeds = tuple(int(seed) for seed in seeds_raw)
    if len(set(seeds)) != len(seeds):
        raise QwenTrackV4ProtocolError("trajectory_seeds must be distinct.")
    rotations, definitions, state_bank = manifest.get("family_rotations"), manifest.get("public_failure_families"), manifest.get("parent_state_bank")
    if not isinstance(rotations, Mapping) or not isinstance(definitions, Mapping) or not isinstance(state_bank, Mapping):
        raise QwenTrackV4ProtocolError("V4 manifest lacks rotations, family definitions, or parent state bank.")

    rows: list[dict[str, object]] = []
    for environment in envs:
        env_definitions, env_states = definitions.get(environment), state_bank.get(environment)
        if not isinstance(env_definitions, Mapping) or set(env_definitions) != set(families):
            raise QwenTrackV4ProtocolError(f"{environment} must define every V4 family exactly once.")
        if not isinstance(env_states, Mapping) or len(env_states) < 4:
            raise QwenTrackV4ProtocolError(f"{environment} requires at least four public parent states.")
        for seed in seeds:
            order = rotations.get(str(seed), rotations.get(seed))
            if not isinstance(order, list) or tuple(order) not in {
                tuple(families[index:] + families[:index]) for index in range(len(families))
            }:
                raise QwenTrackV4ProtocolError(f"Seed {seed} must use a cyclic V4 family rotation.")
            for round_index, family_id in enumerate(order, start=1):
                definition = env_definitions[family_id]
                if not isinstance(definition, Mapping):
                    raise QwenTrackV4ProtocolError(f"Malformed public family {environment}/{family_id}.")
                parent_state = definition.get("parent_state")
                if not isinstance(parent_state, str) or parent_state not in env_states:
                    raise QwenTrackV4ProtocolError(f"{environment}/{family_id} references an unknown parent state.")
                profile, name = definition.get("profile"), definition.get("name")
                if not isinstance(profile, str) or not isinstance(name, str):
                    raise QwenTrackV4ProtocolError(f"{environment}/{family_id} lacks a public profile or name.")
                rows.append(
                    {
                        "slot_id": f"qwen-v4-{environment.lower()}-{seed:03d}-{round_index:02d}",
                        "environment": environment,
                        "trajectory_seed": seed,
                        "round_index": round_index,
                        "family_id": family_id,
                        "failure_family": name,
                        "parent_state": parent_state,
                        "visible_profile": profile,
                        "task_modifier": str(definition.get("task_modifier", "none")),
                        "public_context_note": str(definition.get("public_context_note", "")),
                    }
                )
    expected = len(envs) * len(seeds) * len(families)
    if len(rows) != expected:
        raise QwenTrackV4ProtocolError("V4 schedule has an unexpected slot count.")
    for environment in envs:
        subset = [row for row in rows if row["environment"] == environment]
        if any(sum(row["family_id"] == family for row in subset) != len(seeds) for family in families):
            raise QwenTrackV4ProtocolError("Each public family must occur once per trajectory and environment.")
    return tuple(rows)


def public_parent(manifest: Mapping[str, Any], scenario: Mapping[str, object]) -> Harness:
    """Materialize a public parent snapshot without using an outcome or label."""
    environment, state = str(scenario["environment"]), str(scenario["parent_state"])
    bank = manifest.get("parent_state_bank")
    if not isinstance(bank, Mapping) or not isinstance(bank.get(environment), Mapping):
        raise QwenTrackV4ProtocolError("Missing parent-state bank for scenario environment.")
    raw = bank[environment].get(state)
    if not isinstance(raw, Mapping) or not isinstance(raw.get("typed_policy"), Mapping):
        raise QwenTrackV4ProtocolError("Malformed public parent-state entry.")
    try:
        policy = validate_typed_policy(raw["typed_policy"], environment=environment)
    except V3IRValidationError as exc:
        raise QwenTrackV4ProtocolError(f"Invalid public parent policy: {exc}") from exc
    return Harness(adapter_name=f"typed_{environment.lower()}_policy", typed_policy=policy)


def public_parent_state_report(manifest: Mapping[str, Any]) -> dict[str, object]:
    """Return public schedule coverage used in the A1 readiness seal."""
    rows = scenario_rows(manifest)
    coverage = Counter(f"{row['environment']}:{row['parent_state']}" for row in rows)
    for row in rows:
        public_parent(manifest, row)
    return {
        "logical_slots": len(rows),
        "family_counts": dict(sorted(Counter(f"{row['environment']}:{row['family_id']}" for row in rows).items())),
        "parent_state_counts": dict(sorted(coverage.items())),
        "trajectory_clusters": len({(row["environment"], row["trajectory_seed"]) for row in rows}),
    }


def classify_proposal_failure(exc: Exception) -> str:
    """Keep API failures separate from received-but-invalid model completions."""
    if isinstance(exc, LLMClientError):
        return "api_transport_failed"
    if isinstance(exc, V3ProposalCompilationError):
        return "invalid_policy_combination"
    if isinstance(exc, (V3IRValidationError, ValueError)):
        return "schema_invalid"
    return "unexpected_runner_error"


def _thresholds(manifest: Mapping[str, Any], gate: str) -> Mapping[str, Any]:
    gates = manifest.get("gates")
    if not isinstance(gates, Mapping) or not isinstance(gates.get(gate), Mapping):
        raise QwenTrackV4ProtocolError(f"Manifest lacks gate {gate} thresholds.")
    return gates[gate]


def evaluate_gate_a3(manifest: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]) -> dict[str, object]:
    """Evaluate public-only contract compatibility before formal slots are frozen."""
    thresholds, envs = _thresholds(manifest, "A3"), environments(manifest)
    expected = int(thresholds["cases"])
    if len(rows) != expected:
        raise QwenTrackV4ProtocolError(f"A3 requires exactly {expected} one-shot cases.")
    passed_rows = [row for row in rows if row.get("status") == "passed"]
    per_environment = {
        env: [row for row in passed_rows if row.get("environment") == env] for env in envs
    }
    signatures = {
        env: {str(row.get("typed_policy_delta_signature")) for row in per_environment[env] if row.get("typed_policy_delta_signature")}
        for env in envs
    }
    statuses = Counter(str(row.get("status", "unknown")) for row in rows)
    criteria = {
        "materialized_total": len(passed_rows) >= int(thresholds["min_materialized_total"]),
        "materialized_per_environment": all(len(per_environment[env]) >= int(thresholds["min_materialized_per_environment"]) for env in envs),
        "delta_signatures_per_environment": all(len(signatures[env]) >= int(thresholds["min_delta_signatures_per_environment"]) for env in envs),
    }
    return {
        "gate": "A3",
        "criteria": criteria,
        "passed": all(criteria.values()),
        "counts": {"cases": len(rows), "materialized": len(passed_rows), "status": dict(sorted(statuses.items()))},
        "by_environment": {env: {"materialized": len(per_environment[env]), "delta_signatures": len(signatures[env])} for env in envs},
    }


def _unique_by_slot(rows: Sequence[Mapping[str, Any]], *, name: str) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        slot = row.get("slot_id")
        if not isinstance(slot, str) or not slot or slot in result:
            raise QwenTrackV4ProtocolError(f"{name} must have one non-empty entry per slot.")
        result[slot] = row
    return result


def evaluate_gate_b(
    manifest: Mapping[str, Any],
    ledger: Sequence[Mapping[str, Any]],
    canonical_labels: Sequence[Mapping[str, Any]],
    canonical_decisions: Sequence[Mapping[str, Any]],
    method_parent_labels: Sequence[Mapping[str, Any]],
) -> dict[str, object]:
    """Evaluate candidate sufficiency without reporting performance claims."""
    thresholds, envs = _thresholds(manifest, "B"), environments(manifest)
    executable = [row for row in ledger if row.get("proposal_status") == "executable"]
    label_by_slot = _unique_by_slot(canonical_labels, name="canonical labels")
    executable_slots = {str(row["slot_id"]) for row in executable}
    if set(label_by_slot) != executable_slots:
        raise QwenTrackV4ProtocolError("Canonical labels must exactly cover executable ledger entries.")
    try:
        units = validate_label_cardinalities(ledger, canonical_labels, method_parent_labels, dynamic_methods=DYNAMIC_METHODS).to_dict()
    except ValueError as exc:
        raise QwenTrackV4ProtocolError(str(exc)) from exc
    direct_rows = _unique_by_slot(
        [row for row in canonical_decisions if row.get("method") == "direct_commit" and row.get("proposal_status") == "executable"],
        name="canonical Direct decisions",
    )
    if set(direct_rows) != executable_slots:
        raise QwenTrackV4ProtocolError("Canonical Direct decisions must cover executable candidates exactly.")
    per_environment: dict[str, dict[str, int]] = {}
    for env in envs:
        subset = [label for label in canonical_labels if label.get("environment") == env]
        per_environment[env] = {
            "executable": len(subset),
            "reliable": sum(bool(label.get("reliable")) for label in subset),
            "unreliable": sum(not bool(label.get("reliable")) for label in subset),
            "delta_signatures": len({str(row.get("typed_policy_delta_signature")) for row in executable if row.get("environment") == env and row.get("typed_policy_delta_signature")}),
        }
    eligible_bad = [
        label for label in canonical_labels
        if not bool(label.get("reliable")) and bool(direct_rows[str(label["slot_id"])].get("eligible"))
    ]
    method_parent_eligible_bad = [
        label for label in method_parent_labels if not bool(label.get("reliable")) and bool(label.get("eligible"))
    ]
    baseline_false_accepts = {
        method: any(
            label.get("method") == method and bool(label.get("committed")) and not bool(label.get("reliable"))
            for label in method_parent_labels
        )
        for method in ("rsea_fixed_validation", "fixed_random_audit")
    }
    criteria = {
        "executable_total": len(executable) >= int(thresholds["min_executable_total"]),
        "executable_per_environment": all(per_environment[env]["executable"] >= int(thresholds["min_executable_per_environment"]) for env in envs),
        "reliable_per_environment": all(per_environment[env]["reliable"] >= int(thresholds["min_reliable_per_environment"]) for env in envs),
        "unreliable_per_environment": all(per_environment[env]["unreliable"] >= int(thresholds["min_unreliable_per_environment"]) for env in envs),
        "delta_signatures_per_environment": all(per_environment[env]["delta_signatures"] >= int(thresholds["min_delta_signatures_per_environment"]) for env in envs),
        "canonical_eligible_unreliable": len(eligible_bad) >= int(thresholds["min_canonical_eligible_unreliable"]),
        "method_parent_eligible_unreliable": len(method_parent_eligible_bad) >= int(thresholds["min_method_parent_eligible_unreliable"]),
        "baseline_false_accepts": all(baseline_false_accepts.values()),
    }
    return {
        "gate": "B",
        "criteria": criteria,
        "passed": all(criteria.values()),
        "units": units,
        "by_environment": per_environment,
        "counts": {
            "executable": len(executable),
            "canonical_eligible_unreliable": len(eligible_bad),
            "method_parent_eligible_unreliable": len(method_parent_eligible_bad),
        },
        "baseline_false_accepts": baseline_false_accepts,
    }


def evaluate_gate_p(manifest: Mapping[str, Any], online_decisions: Sequence[Mapping[str, Any]]) -> dict[str, object]:
    """Require an actual Direct--EvoAudit intervention before terminal comparison."""
    thresholds, envs = _thresholds(manifest, "P"), environments(manifest)
    by_event: dict[tuple[str, str, int], dict[str, Mapping[str, Any]]] = defaultdict(dict)
    for row in online_decisions:
        if row.get("proposal_status") != "executable" or row.get("method") not in {"direct_commit", "evoaudit_mr"}:
            continue
        key = (str(row.get("slot_id")), str(row.get("environment")), int(row.get("trajectory_seed")))
        method = str(row["method"])
        if method in by_event[key]:
            raise QwenTrackV4ProtocolError("Persistent decision events must be unique per method and slot.")
        by_event[key][method] = row
    complete = {key: value for key, value in by_event.items() if set(value) == {"direct_commit", "evoaudit_mr"}}
    if len(complete) != len(by_event):
        raise QwenTrackV4ProtocolError("Every executable persistent event must contain Direct and EvoAudit decisions.")
    divergent = [
        (key, rows) for key, rows in complete.items()
        if rows["direct_commit"].get("decision") != rows["evoaudit_mr"].get("decision")
    ]
    per_environment = {env: sum(key[1] == env for key, _ in divergent) for env in envs}
    clusters = {(key[1], key[2]) for key, _ in divergent}
    criteria = {
        "divergent_events": len(divergent) >= int(thresholds["min_direct_evo_divergent_events"]),
        "divergent_trajectory_clusters": len(clusters) >= int(thresholds["min_divergent_trajectory_clusters"]),
        "divergent_events_per_environment": all(per_environment[env] >= int(thresholds["min_divergent_events_per_environment"]) for env in envs),
    }
    return {
        "gate": "P",
        "criteria": criteria,
        "passed": all(criteria.values()),
        "counts": {
            "paired_executable_method_parent_events": len(complete),
            "direct_evo_divergent_events": len(divergent),
            "divergent_trajectory_clusters": len(clusters),
            "by_environment": per_environment,
        },
    }


ONLINE_ARTIFACTS = (
    "api_attempts.jsonl",
    "candidate_ledger_online.jsonl",
    "canonical_decisions.jsonl",
    "online_decisions.jsonl",
    "static_snapshots.jsonl",
    "ONLINE_INPUT_SEAL.json",
)


def _hash_paths(root: Path, paths: Sequence[str]) -> str:
    hasher = sha256()
    for relative in paths:
        path = root / relative
        if not path.exists():
            raise QwenTrackV4ProtocolError(f"Missing locked online artifact: {relative}.")
        files = sorted(item for item in path.rglob("*") if item.is_file()) if path.is_dir() else [path]
        for item in files:
            hasher.update(item.relative_to(root).as_posix().encode("utf-8"))
            hasher.update(item.read_bytes())
    return hasher.hexdigest()


def write_online_phase_lock(
    output: Path,
    *,
    manifest_hash: str,
    logical_slots: int,
    dynamic_decisions: int,
    static_measurements: int,
    trajectory_hashes: Mapping[str, str],
) -> Path:
    path = output / "ONLINE_PHASE_LOCK.json"
    if path.exists():
        raise FileExistsError("V4 online phase is already locked.")
    payload = {
        "protocol_version": PROTOCOL_VERSION,
        "phase": "locked",
        "manifest_hash": manifest_hash,
        "logical_slots": logical_slots,
        "dynamic_decisions": dynamic_decisions,
        "static_measurements": static_measurements,
        "online_artifact_hash": _hash_paths(output, ONLINE_ARTIFACTS),
        "trajectory_hashes": dict(trajectory_hashes),
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def validate_online_phase_lock(
    output: Path,
    *,
    manifest_hash: str,
    logical_slots: int,
    dynamic_decisions: int,
    static_measurements: int,
) -> Mapping[str, Any]:
    path = output / "ONLINE_PHASE_LOCK.json"
    if not path.exists():
        raise QwenTrackV4ProtocolError("Offline V4 evaluation requires ONLINE_PHASE_LOCK.json.")
    payload = json.loads(path.read_text(encoding="utf-8"))
    expected = {
        "protocol_version": PROTOCOL_VERSION,
        "phase": "locked",
        "manifest_hash": manifest_hash,
        "logical_slots": logical_slots,
        "dynamic_decisions": dynamic_decisions,
        "static_measurements": static_measurements,
    }
    if any(payload.get(name) != value for name, value in expected.items()):
        raise QwenTrackV4ProtocolError("V4 online phase lock does not match frozen inputs.")
    if payload.get("online_artifact_hash") != _hash_paths(output, ONLINE_ARTIFACTS):
        raise QwenTrackV4ProtocolError("V4 online artifacts changed after phase lock.")
    return payload


def seal_artifacts(output: Path, *, manifest_hash: str) -> Path:
    required = (
        "COMPILER_ACCOUNTING_READINESS_SEAL.json",
        "QWEN_A3_INPUT_SEAL.json",
        "QWEN_A3_REPORT.json",
        "QWEN_FREEZE.json",
        "HIDDEN_COMMITMENT.json",
        "ONLINE_INPUT_SEAL.json",
        "ONLINE_PHASE_LOCK.json",
        "reports",
    )
    if any(not (output / item).exists() for item in required):
        raise QwenTrackV4ProtocolError("Final V4 seal requires every protocol phase.")
    path = output / "QWEN_TRACK_V4_SEAL.json"
    if path.exists():
        raise FileExistsError("V4 final seal already exists.")
    files = {
        item.relative_to(output).as_posix(): sha256_hex(item.read_bytes())
        for item in sorted(output.rglob("*"))
        if item.is_file() and item.name != path.name
    }
    path.write_text(
        json.dumps({"protocol_version": PROTOCOL_VERSION, "manifest_hash": manifest_hash, "artifact_file_hashes": files}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path
