"""Protocol locks and immutable artifacts for the Ollama Pilot v2."""

from __future__ import annotations

from hashlib import sha256
import hmac
import json
from pathlib import Path
from typing import Any, Mapping


PROTOCOL_VERSION = "ollama-llm-proposal-pilot-v2"


class OllamaPilotProtocolError(ValueError):
    """The Ollama Pilot run does not satisfy a frozen-protocol invariant."""


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_hex(value: str | bytes) -> str:
    return sha256(value.encode("utf-8") if isinstance(value, str) else value).hexdigest()


def hmac_hex(key: str, value: str | bytes) -> str:
    raw = value.encode("utf-8") if isinstance(value, str) else value
    return hmac.new(bytes.fromhex(key), raw, sha256).hexdigest()


def manifest_digest(manifest: Mapping[str, Any]) -> str:
    return sha256_hex(canonical_json(dict(manifest)))


def derived_hidden_seed(
    key: str,
    *,
    manifest_hash: str,
    environment: str,
    identity: str,
    bucket: str,
) -> int:
    message = "|".join((PROTOCOL_VERSION, manifest_hash, environment, identity, bucket))
    return int(hmac_hex(key, message)[:16], 16)


def source_hashes(root: Path) -> dict[str, str]:
    """Hash every online-critical source file named in the public manifest."""
    relative_paths = (
        "src/evoaudit_mr/llm/proposal.py",
        "src/evoaudit_mr/llm/compiler.py",
        "src/evoaudit_mr/llm/ollama.py",
        "src/evoaudit_mr/audits/gate.py",
        "src/evoaudit_mr/audits/random_audit.py",
        "src/evoaudit_mr/formal/audit.py",
        "src/evoaudit_mr/evolution/transforms.py",
        "src/evoaudit_mr/runners/ollama_pilot.py",
    )
    return {path: sha256_hex((root / path).read_bytes()) for path in relative_paths}


def validate_online_source_lock(manifest: Mapping[str, Any], *, root: Path) -> None:
    expected = manifest.get("online_source_hashes")
    if not isinstance(expected, Mapping):
        raise OllamaPilotProtocolError("Manifest lacks online_source_hashes.")
    actual = source_hashes(root)
    if dict(expected) != actual:
        raise OllamaPilotProtocolError("Online-critical source differs from the frozen public manifest.")


def _hash_tree(root: Path, directories: tuple[str, ...]) -> str:
    hasher = sha256()
    for directory in directories:
        base = root / directory
        if not base.exists():
            raise OllamaPilotProtocolError(f"Missing online artifact directory: {directory}.")
        for path in sorted(item for item in base.rglob("*") if item.is_file()):
            hasher.update(path.relative_to(root).as_posix().encode("utf-8"))
            hasher.update(path.read_bytes())
    return hasher.hexdigest()


def online_record_hash(root: Path) -> str:
    return _hash_tree(
        root,
        ("candidate_ledger", "candidate_level", "trajectories", "static", "certificates", "online_protocol"),
    )


def complete_online_phase(
    output_dir: str | Path,
    *,
    manifest_hash: str,
    candidate_slots: int,
    dynamic_decisions: int,
    static_measurements: int,
) -> Path:
    root = Path(output_dir)
    marker = root / "ONLINE_COMPLETE.json"
    if marker.exists():
        raise OllamaPilotProtocolError("ONLINE_COMPLETE already exists; online artifacts are immutable.")
    payload = {
        "protocol_version": PROTOCOL_VERSION,
        "manifest_hash": manifest_hash,
        "candidate_slots": candidate_slots,
        "dynamic_decisions": dynamic_decisions,
        "static_measurements": static_measurements,
        "online_record_hash": online_record_hash(root),
    }
    marker.write_text(canonical_json(payload) + "\n", encoding="utf-8")
    return marker


def require_online_phase(
    output_dir: str | Path,
    *,
    manifest_hash: str,
    candidate_slots: int,
    dynamic_decisions: int,
    static_measurements: int,
) -> Mapping[str, Any]:
    root = Path(output_dir)
    marker = root / "ONLINE_COMPLETE.json"
    if not marker.exists():
        raise OllamaPilotProtocolError("Offline phase requires ONLINE_COMPLETE.json.")
    payload = json.loads(marker.read_text(encoding="utf-8"))
    expected = {
        "protocol_version": PROTOCOL_VERSION,
        "manifest_hash": manifest_hash,
        "candidate_slots": candidate_slots,
        "dynamic_decisions": dynamic_decisions,
        "static_measurements": static_measurements,
    }
    if any(payload.get(key) != value for key, value in expected.items()):
        raise OllamaPilotProtocolError("ONLINE_COMPLETE does not match the frozen pilot protocol.")
    if payload.get("online_record_hash") != online_record_hash(root):
        raise OllamaPilotProtocolError("Online artifacts changed after the phase lock.")
    return payload


def validate_offline_commitments(
    manifest: Mapping[str, Any],
    offline: Mapping[str, Any],
    *,
    hidden_generator_source: str,
    environment_contracts: Mapping[str, Any],
) -> None:
    commitments = manifest.get("hidden_commitments")
    if not isinstance(commitments, Mapping):
        raise OllamaPilotProtocolError("Manifest lacks hidden commitments.")
    key = offline.get("hidden_master_seed")
    hidden_config = offline.get("hidden_config")
    factor_split = offline.get("semantic_factor_split")
    if not isinstance(key, str) or len(key) != 64:
        raise OllamaPilotProtocolError("Offline hidden_master_seed must be a 256-bit hex string.")
    if not isinstance(hidden_config, Mapping) or not isinstance(factor_split, Mapping):
        raise OllamaPilotProtocolError("Offline hidden reveal is malformed.")
    checks = {
        "seed_commitment": sha256_hex(key),
        "generator_source_hash": sha256_hex(hidden_generator_source),
        "hidden_config_commitment": hmac_hex(key, canonical_json(dict(hidden_config))),
        "factor_split_commitment": hmac_hex(key, canonical_json(dict(factor_split))),
        "environment_contract_hash": sha256_hex(canonical_json(dict(environment_contracts))),
    }
    if any(commitments.get(name) != value for name, value in checks.items()):
        raise OllamaPilotProtocolError("Offline reveal does not match the public hidden commitments.")


def seal_artifacts(output_dir: str | Path, *, manifest_hash: str) -> Path:
    root = Path(output_dir)
    required = ("ONLINE_COMPLETE.json", "offline_hidden", "reports")
    if any(not (root / name).exists() for name in required):
        raise OllamaPilotProtocolError("Pilot seal requires completed online, offline, and report artifacts.")
    output = root / "PILOT_SEAL.json"
    if output.exists():
        raise OllamaPilotProtocolError("PILOT_SEAL already exists and must not be overwritten.")
    files = {
        path.relative_to(root).as_posix(): sha256_hex(path.read_bytes())
        for path in sorted(item for item in root.rglob("*") if item.is_file() and item.name != "PILOT_SEAL.json")
    }
    payload = {
        "protocol_version": PROTOCOL_VERSION,
        "manifest_hash": manifest_hash,
        "artifact_file_hashes": files,
    }
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output
