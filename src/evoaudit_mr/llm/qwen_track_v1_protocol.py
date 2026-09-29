"""Immutable artifacts and phase boundaries for the independent Qwen Track."""

from __future__ import annotations

from hashlib import sha256
import hmac
import json
from pathlib import Path
from typing import Any, Mapping


PROTOCOL_VERSION = "qwen-llm-proposal-track-v1"


class QwenTrackProtocolError(ValueError):
    """A Qwen Track run violates a frozen protocol invariant."""


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
    paths = (
        "src/evoaudit_mr/types.py", "src/evoaudit_mr/harness.py", "src/evoaudit_mr/evaluation.py",
        "src/evoaudit_mr/envs/aliastool.py", "src/evoaudit_mr/envs/permissionpath.py",
        "src/evoaudit_mr/evolution/transforms.py", "src/evoaudit_mr/llm/client.py",
        "src/evoaudit_mr/llm/config.py", "src/evoaudit_mr/llm/v3_ir.py",
        "src/evoaudit_mr/llm/v3b_ir.py", "src/evoaudit_mr/llm/v3_compiler.py",
        "src/evoaudit_mr/llm/v3_executor.py", "src/evoaudit_mr/llm/proposal_track_accounting.py",
        "src/evoaudit_mr/llm/qwen_track_v1_protocol.py", "src/evoaudit_mr/llm/qwen_track_v1_offline.py",
        "src/evoaudit_mr/audits/gate.py", "src/evoaudit_mr/audits/random_audit.py",
        "src/evoaudit_mr/formal/audit.py", "src/evoaudit_mr/formal/catalogue.py",
        "src/evoaudit_mr/runners/ollama_pilot_v3.py", "src/evoaudit_mr/runners/qwen_track_v1.py",
    )
    return {path: sha256_hex((root / path).read_bytes()) for path in paths}


def validate_source_lock(manifest: Mapping[str, Any], *, root: Path) -> None:
    expected = manifest.get("source_hashes")
    if not isinstance(expected, Mapping) or dict(expected) != source_hashes(root):
        raise QwenTrackProtocolError("Qwen Track sources differ from the frozen manifest.")


def derived_hidden_seed(key: str, *, manifest_hash: str, environment: str, identity: str, bucket: str) -> int:
    message = "|".join((PROTOCOL_VERSION, manifest_hash, environment, identity, bucket))
    return int(hmac_hex(key, message)[:16], 16)


def write_hidden_commitment(output: Path, *, key: str, hidden_config: Mapping[str, Any], hidden_source: str, environment_contracts: Mapping[str, Any]) -> Path:
    path = output / "HIDDEN_COMMITMENT.json"
    if path.exists(): raise FileExistsError("HIDDEN_COMMITMENT already exists.")
    payload = {"protocol_version": PROTOCOL_VERSION, "seed_commitment": sha256_hex(key),
        "hidden_config_commitment": hmac_hex(key, canonical_json(dict(hidden_config))),
        "generator_source_hash": sha256_hex(hidden_source), "environment_contract_hash": sha256_hex(canonical_json(dict(environment_contracts)))}
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def validate_hidden_reveal(commitment: Mapping[str, Any], *, key: str, hidden_config: Mapping[str, Any], hidden_source: str, environment_contracts: Mapping[str, Any]) -> None:
    expected = {"seed_commitment": sha256_hex(key), "hidden_config_commitment": hmac_hex(key, canonical_json(dict(hidden_config))),
        "generator_source_hash": sha256_hex(hidden_source), "environment_contract_hash": sha256_hex(canonical_json(dict(environment_contracts)))}
    if any(commitment.get(name) != value for name, value in expected.items()):
        raise QwenTrackProtocolError("Offline hidden reveal does not match HIDDEN_COMMITMENT.")


ONLINE_ARTIFACTS = ("api_attempts.jsonl", "candidate_ledger_online.jsonl", "canonical_decisions.jsonl", "online_decisions.jsonl", "static_snapshots.jsonl", "ONLINE_INPUT_SEAL.json")


def _hash_paths(root: Path, paths: tuple[str, ...]) -> str:
    hasher = sha256()
    for relative in paths:
        path = root / relative
        if not path.exists(): raise QwenTrackProtocolError(f"Missing locked online artifact: {relative}.")
        files = sorted(item for item in path.rglob("*") if item.is_file()) if path.is_dir() else [path]
        for item in files:
            hasher.update(item.relative_to(root).as_posix().encode("utf-8")); hasher.update(item.read_bytes())
    return hasher.hexdigest()


def write_online_phase_lock(output: Path, *, manifest_hash: str, logical_slots: int, dynamic_decisions: int, static_measurements: int, trajectory_hashes: Mapping[str, str]) -> Path:
    path = output / "ONLINE_PHASE_LOCK.json"
    if path.exists(): raise FileExistsError("ONLINE_PHASE_LOCK already exists.")
    payload = {"protocol_version": PROTOCOL_VERSION, "phase": "locked", "manifest_hash": manifest_hash,
        "logical_slots": logical_slots, "dynamic_decisions": dynamic_decisions, "static_measurements": static_measurements,
        "online_artifact_hash": _hash_paths(output, ONLINE_ARTIFACTS), "trajectory_hashes": dict(trajectory_hashes)}
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def validate_online_phase_lock(output: Path, *, manifest_hash: str, logical_slots: int, dynamic_decisions: int, static_measurements: int) -> Mapping[str, Any]:
    path = output / "ONLINE_PHASE_LOCK.json"
    if not path.exists(): raise QwenTrackProtocolError("Offline phase requires ONLINE_PHASE_LOCK.json.")
    payload = json.loads(path.read_text(encoding="utf-8"))
    expected = {"protocol_version": PROTOCOL_VERSION, "phase": "locked", "manifest_hash": manifest_hash,
        "logical_slots": logical_slots, "dynamic_decisions": dynamic_decisions, "static_measurements": static_measurements}
    if any(payload.get(key) != value for key, value in expected.items()): raise QwenTrackProtocolError("ONLINE_PHASE_LOCK does not match Qwen Track inputs.")
    if payload.get("online_artifact_hash") != _hash_paths(output, ONLINE_ARTIFACTS): raise QwenTrackProtocolError("Online artifacts changed after lock.")
    return payload


def seal_artifacts(output: Path, *, manifest_hash: str) -> Path:
    required = ("COMPILER_ACCOUNTING_READINESS_SEAL.json", "QWEN_A2_INPUT_SEAL.json", "QWEN_A2_REPORT.json", "QWEN_FREEZE.json", "HIDDEN_COMMITMENT.json", "ONLINE_INPUT_SEAL.json", "ONLINE_PHASE_LOCK.json", "reports")
    if any(not (output / item).exists() for item in required): raise QwenTrackProtocolError("Final Qwen seal requires all protocol phases.")
    path = output / "QWEN_TRACK_V1_SEAL.json"
    if path.exists(): raise FileExistsError("QWEN_TRACK_V1_SEAL already exists.")
    files = {item.relative_to(output).as_posix(): sha256_hex(item.read_bytes()) for item in sorted(output.rglob("*")) if item.is_file() and item.name != path.name}
    path.write_text(json.dumps({"protocol_version": PROTOCOL_VERSION, "manifest_hash": manifest_hash, "artifact_file_hashes": files}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path
