"""Canonical manifests, phase locks, and offline-only hidden commitments."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import hmac
import json
from pathlib import Path
from typing import Any, Mapping

from evoaudit_mr.formal import PROTOCOL_VERSION


class ProtocolError(ValueError):
    """Raised when a formal run does not satisfy a frozen-protocol invariant."""


def canonical_json(payload: Mapping[str, Any] | list[Any]) -> str:
    """Serialize a JSON-compatible payload deterministically."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_hex(value: str | bytes) -> str:
    encoded = value.encode("utf-8") if isinstance(value, str) else value
    return sha256(encoded).hexdigest()


def manifest_digest(manifest: Mapping[str, Any]) -> str:
    return sha256_hex(canonical_json(dict(manifest)))


def hmac_hex(key: str, value: str | bytes) -> str:
    encoded = value.encode("utf-8") if isinstance(value, str) else value
    return hmac.new(bytes.fromhex(key), encoded, sha256).hexdigest()


def hidden_seed(
    key: str,
    *,
    manifest_hash: str,
    environment: str,
    event_or_trajectory_id: str,
    bucket: str,
) -> int:
    """Derive a deterministic offline seed without exposing the master key."""
    message = "|".join(
        (PROTOCOL_VERSION, manifest_hash, environment, event_or_trajectory_id, bucket)
    )
    return int(hmac_hex(key, message)[:16], 16)


@dataclass(frozen=True)
class HiddenCommitment:
    """Public commitments that are checked before offline labels are generated."""

    seed_commitment: str
    generator_source_hash: str
    hidden_config_commitment: str
    factor_split_commitment: str
    environment_contract_hash: str

    @classmethod
    def from_manifest(cls, manifest: Mapping[str, Any]) -> "HiddenCommitment":
        raw = manifest.get("hidden_commitments")
        if not isinstance(raw, Mapping):
            raise ProtocolError("Public manifest is missing hidden_commitments.")
        required = (
            "seed_commitment",
            "generator_source_hash",
            "hidden_config_commitment",
            "factor_split_commitment",
            "environment_contract_hash",
        )
        missing = [key for key in required if not isinstance(raw.get(key), str)]
        if missing:
            raise ProtocolError(f"Malformed hidden commitments: {', '.join(missing)}")
        return cls(**{key: str(raw[key]) for key in required})


def validate_offline_reveal(
    manifest: Mapping[str, Any],
    offline: Mapping[str, Any],
    *,
    generator_source: str,
    environment_contracts: Mapping[str, Any],
) -> None:
    """Verify that the offline hidden protocol matches the online commitment."""
    commitment = HiddenCommitment.from_manifest(manifest)
    key = offline.get("hidden_master_seed")
    hidden_config = offline.get("hidden_config")
    factor_split = offline.get("semantic_factor_split")
    if not isinstance(key, str) or len(key) != 64:
        raise ProtocolError("Offline hidden_master_seed must be a 256-bit hex string.")
    if not isinstance(hidden_config, Mapping) or not isinstance(factor_split, Mapping):
        raise ProtocolError("Offline reveal lacks hidden_config or semantic_factor_split.")
    if sha256_hex(key) != commitment.seed_commitment:
        raise ProtocolError("Offline hidden seed does not match the public commitment.")
    if sha256_hex(generator_source) != commitment.generator_source_hash:
        raise ProtocolError("Hidden generator source differs from its public commitment.")
    if hmac_hex(key, canonical_json(dict(hidden_config))) != commitment.hidden_config_commitment:
        raise ProtocolError("Hidden config does not match its public commitment.")
    if hmac_hex(key, canonical_json(dict(factor_split))) != commitment.factor_split_commitment:
        raise ProtocolError("Factor split does not match its public commitment.")
    if sha256_hex(canonical_json(dict(environment_contracts))) != commitment.environment_contract_hash:
        raise ProtocolError("Environment contracts differ from their public commitment.")


def phase_marker_path(output_dir: str | Path) -> Path:
    return Path(output_dir) / "ONLINE_COMPLETE.json"


def complete_online_phase(
    output_dir: str | Path,
    *,
    manifest_hash: str,
    event_count: int,
    online_record_hash: str,
    protocol_version: str = PROTOCOL_VERSION,
) -> Path:
    """Seal online decisions before the offline command may access hidden labels."""
    marker = phase_marker_path(output_dir)
    if marker.exists():
        raise ProtocolError("ONLINE_COMPLETE already exists; formal online output is immutable.")
    marker.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "protocol_version": protocol_version,
        "manifest_hash": manifest_hash,
        "event_count": event_count,
        "online_record_hash": online_record_hash,
    }
    marker.write_text(canonical_json(payload) + "\n", encoding="utf-8")
    return marker


def require_online_complete(
    output_dir: str | Path,
    *,
    expected_manifest_hash: str,
    expected_event_count: int,
    protocol_version: str = PROTOCOL_VERSION,
) -> Mapping[str, Any]:
    marker = phase_marker_path(output_dir)
    if not marker.exists():
        raise ProtocolError("Offline phase requires an ONLINE_COMPLETE marker.")
    payload = json.loads(marker.read_text(encoding="utf-8"))
    if payload.get("protocol_version") != protocol_version:
        raise ProtocolError("ONLINE_COMPLETE protocol version mismatch.")
    if payload.get("manifest_hash") != expected_manifest_hash:
        raise ProtocolError("ONLINE_COMPLETE manifest hash mismatch.")
    if payload.get("event_count") != expected_event_count:
        raise ProtocolError("ONLINE_COMPLETE event count mismatch.")
    if not isinstance(payload.get("online_record_hash"), str):
        raise ProtocolError("ONLINE_COMPLETE lacks online_record_hash.")
    return payload


def load_json(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ProtocolError(f"Expected JSON object at {path}.")
    return payload
