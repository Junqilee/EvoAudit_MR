"""Immutable-artifact protocol for the independent structured-output V3b track."""

from __future__ import annotations

from hashlib import sha256
import hmac
import json
from pathlib import Path
from typing import Any, Mapping


PROTOCOL_VERSION = "ollama-llm-proposal-pilot-v3b"


class OllamaPilotV3BProtocolError(ValueError):
    """A V3b run violates a pre-registered protocol invariant."""


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
    """All sources that affect public decoding, compilation, or online decisions."""
    paths = (
        "src/evoaudit_mr/types.py",
        "src/evoaudit_mr/harness.py",
        "src/evoaudit_mr/evaluation.py",
        "src/evoaudit_mr/envs/aliastool.py",
        "src/evoaudit_mr/envs/permissionpath.py",
        "src/evoaudit_mr/evolution/transforms.py",
        "src/evoaudit_mr/llm/ollama.py",
        "src/evoaudit_mr/llm/ollama_native.py",
        "src/evoaudit_mr/llm/v3_ir.py",
        "src/evoaudit_mr/llm/v3_compiler.py",
        "src/evoaudit_mr/llm/v3_executor.py",
        "src/evoaudit_mr/llm/v3b_ir.py",
        "src/evoaudit_mr/llm/ollama_pilot_v3b_protocol.py",
        "src/evoaudit_mr/audits/gate.py",
        "src/evoaudit_mr/audits/random_audit.py",
        "src/evoaudit_mr/formal/audit.py",
        "src/evoaudit_mr/formal/catalogue.py",
        "src/evoaudit_mr/runners/ollama_pilot_v3.py",
        "src/evoaudit_mr/runners/ollama_pilot_v3b.py",
    )
    return {path: sha256_hex((root / path).read_bytes()) for path in paths}


def validate_online_source_lock(manifest: Mapping[str, Any], *, root: Path) -> None:
    expected = manifest.get("online_source_hashes")
    if not isinstance(expected, Mapping) or dict(expected) != source_hashes(root):
        raise OllamaPilotV3BProtocolError("Online-critical sources differ from the frozen V3b manifest.")


def derived_hidden_seed(key: str, *, manifest_hash: str, environment: str, identity: str, bucket: str) -> int:
    message = "|".join((PROTOCOL_VERSION, manifest_hash, environment, identity, bucket))
    return int(hmac_hex(key, message)[:16], 16)


def write_hidden_commitment(output: Path, *, key: str, hidden_config: Mapping[str, Any], hidden_source: str, environment_contracts: Mapping[str, Any]) -> Path:
    path = output / "HIDDEN_COMMITMENT.json"
    if path.exists():
        raise FileExistsError("HIDDEN_COMMITMENT already exists.")
    payload = {
        "protocol_version": PROTOCOL_VERSION,
        "seed_commitment": sha256_hex(key),
        "hidden_config_commitment": hmac_hex(key, canonical_json(dict(hidden_config))),
        "generator_source_hash": sha256_hex(hidden_source),
        "environment_contract_hash": sha256_hex(canonical_json(dict(environment_contracts))),
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def validate_hidden_reveal(commitment: Mapping[str, Any], *, key: str, hidden_config: Mapping[str, Any], hidden_source: str, environment_contracts: Mapping[str, Any]) -> None:
    expected = {
        "seed_commitment": sha256_hex(key),
        "hidden_config_commitment": hmac_hex(key, canonical_json(dict(hidden_config))),
        "generator_source_hash": sha256_hex(hidden_source),
        "environment_contract_hash": sha256_hex(canonical_json(dict(environment_contracts))),
    }
    if any(commitment.get(name) != value for name, value in expected.items()):
        raise OllamaPilotV3BProtocolError("Offline hidden reveal does not match HIDDEN_COMMITMENT.")


ONLINE_ARTIFACTS = (
    "candidate_ledger_online.jsonl",
    "canonical_decisions.jsonl",
    "online_decisions.jsonl",
    "static_snapshots.jsonl",
    "ONLINE_INPUT_SEAL.json",
)


def _hash_paths(root: Path, paths: tuple[str, ...]) -> str:
    hasher = sha256()
    for relative in paths:
        path = root / relative
        if not path.exists():
            raise OllamaPilotV3BProtocolError(f"Missing locked online artifact: {relative}.")
        files = sorted(item for item in path.rglob("*") if item.is_file()) if path.is_dir() else [path]
        for item in files:
            hasher.update(item.relative_to(root).as_posix().encode("utf-8"))
            hasher.update(item.read_bytes())
    return hasher.hexdigest()


def write_online_phase_lock(output: Path, *, manifest_hash: str, candidate_slots: int, dynamic_decisions: int, static_measurements: int, trajectory_hashes: Mapping[str, str]) -> Path:
    path = output / "ONLINE_PHASE_LOCK.json"
    if path.exists():
        raise FileExistsError("ONLINE_PHASE_LOCK already exists and must not be overwritten.")
    payload = {
        "protocol_version": PROTOCOL_VERSION, "phase": "locked", "manifest_hash": manifest_hash,
        "candidate_slots": candidate_slots, "dynamic_decisions": dynamic_decisions,
        "static_measurements": static_measurements, "online_artifact_hash": _hash_paths(output, ONLINE_ARTIFACTS),
        "trajectory_hashes": dict(trajectory_hashes),
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def validate_online_phase_lock(output: Path, *, manifest_hash: str, candidate_slots: int, dynamic_decisions: int, static_measurements: int) -> Mapping[str, Any]:
    path = output / "ONLINE_PHASE_LOCK.json"
    if not path.exists():
        raise OllamaPilotV3BProtocolError("Offline phase requires ONLINE_PHASE_LOCK.json.")
    payload = json.loads(path.read_text(encoding="utf-8"))
    expected = {"protocol_version": PROTOCOL_VERSION, "phase": "locked", "manifest_hash": manifest_hash,
                "candidate_slots": candidate_slots, "dynamic_decisions": dynamic_decisions, "static_measurements": static_measurements}
    if any(payload.get(name) != value for name, value in expected.items()):
        raise OllamaPilotV3BProtocolError("ONLINE_PHASE_LOCK does not match the frozen V3b protocol.")
    if payload.get("online_artifact_hash") != _hash_paths(output, ONLINE_ARTIFACTS):
        raise OllamaPilotV3BProtocolError("Online artifacts changed after phase lock.")
    return payload


def seal_artifacts(output: Path, *, manifest_hash: str) -> Path:
    required = ("COMPILER_READINESS_SEAL.json", "SCHEMA_COMPATIBILITY_INPUT_SEAL.json", "SCHEMA_COMPATIBILITY_REPORT.json", "OLLAMA_FREEZE.json", "HIDDEN_COMMITMENT.json", "ONLINE_INPUT_SEAL.json", "ONLINE_PHASE_LOCK.json", "reports")
    if any(not (output / name).exists() for name in required):
        raise OllamaPilotV3BProtocolError("Final V3b seal requires readiness, compatibility, online, and offline artifacts.")
    path = output / "PILOT_V3B_SEAL.json"
    if path.exists():
        raise FileExistsError("PILOT_V3B_SEAL already exists and must not be overwritten.")
    files = {item.relative_to(output).as_posix(): sha256_hex(item.read_bytes()) for item in sorted(item for item in output.rglob("*") if item.is_file() and item.name != path.name)}
    path.write_text(json.dumps({"protocol_version": PROTOCOL_VERSION, "manifest_hash": manifest_hash, "artifact_file_hashes": files}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path
