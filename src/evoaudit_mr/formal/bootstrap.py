"""Create a committed public manifest and its separate offline reveal file."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import secrets
from typing import Any
import argparse

from evoaudit_mr.formal import PROTOCOL_VERSION
from evoaudit_mr.formal.offline import hidden_generator_source
from evoaudit_mr.formal.protocol import canonical_json, hmac_hex, sha256_hex


def default_factor_split() -> dict[str, Any]:
    """Unseen semantic-factor tuples are committed before online execution."""
    return {
        "AliasTool": {
            "online": [
                ["inventory", "canonical", "primary_alias", "listed", "integer", "public"],
                ["inventory", "alias", "primary_alias", "listed", "integer", "public"],
            ],
            "hidden": [
                ["inventory", "alt_alias", "secondary_alias", "permuted", "unit_normalized", "public"],
            ],
        },
        "SwitchRule": {
            "online": [
                ["base_rule", "base", "route", "canonical", "correlated", "none"],
                ["new_rule", "new", "route", "canonical", "correlated", "none"],
            ],
            "hidden": [
                ["paraphrased_rule", "permuted", "route", "unseen", "permuted", "exception"],
            ],
        },
        "PermissionPath": {
            "online": [
                ["archive", "operator", "same_tenant", "confirmed", "irreversible", "logged"],
                ["update", "operator", "same_tenant", "na", "reversible", "logged"],
            ],
            "hidden": [
                ["delegated_archive", "delegated", "cross_relation", "confirmed", "irreversible", "logged"],
            ],
        },
    }


def validate_factor_split(split: dict[str, Any]) -> None:
    for environment, groups in split.items():
        online = {tuple(item) for item in groups["online"]}
        hidden = {tuple(item) for item in groups["hidden"]}
        if online.intersection(hidden):
            raise ValueError(f"Online/hidden factor tuple overlap in {environment}.")
        if not online or not hidden:
            raise ValueError(f"Both online and hidden factor tuples are required in {environment}.")


def _contracts(project_root: Path) -> dict[str, Any]:
    names = {
        "AliasTool": "aliastool_contract.json",
        "SwitchRule": "switchrule_contract.json",
        "PermissionPath": "permissionpath_contract.json",
    }
    return {
        environment: json.loads((project_root / "configs" / filename).read_text(encoding="utf-8"))
        for environment, filename in names.items()
    }


def create_protocol_files(
    project_root: str | Path,
    *,
    public_path: str | Path,
    offline_path: str | Path,
    hidden_master_seed: str | None = None,
) -> tuple[Path, Path]:
    """Write the public protocol and a separate non-public offline reveal.

    Tests may inject a fixed key. Normal CLI usage leaves it ``None`` and
    creates a new 256-bit key without printing it.
    """
    root = Path(project_root)
    key = hidden_master_seed or secrets.token_hex(32)
    if len(key) != 64:
        raise ValueError("hidden_master_seed must be 256-bit hexadecimal text.")
    split = default_factor_split()
    validate_factor_split(split)
    contracts = _contracts(root)
    hidden_config = {"per_bucket": 16, "oracle": "full_target_replay_safety_universe"}
    public = {
        "protocol_version": PROTOCOL_VERSION,
        "manifest_version": "formal-candidate-v1",
        "seed": 2027,
        "instances_per_mechanism": 6,
        "evolve_tasks_per_event": 12,
        "validation_tasks": 6,
        "audit_budget_pairs": 6,
        "methods": ["direct_commit", "fixed_heldout", "fixed_random_audit", "evoaudit_mr"],
        "analysis_seed_start": 1_000,
        "analysis_seed_count": 1_000,
        "environment_contracts": {
            "AliasTool": "configs/aliastool_contract.json",
            "SwitchRule": "configs/switchrule_contract.json",
            "PermissionPath": "configs/permissionpath_contract.json",
        },
        "hidden_commitments": {
            "seed_commitment": sha256_hex(key),
            "generator_source_hash": sha256_hex(hidden_generator_source()),
            "hidden_config_commitment": hmac_hex(key, canonical_json(hidden_config)),
            "factor_split_commitment": hmac_hex(key, canonical_json(split)),
            "environment_contract_hash": sha256_hex(canonical_json(contracts)),
        },
    }
    offline = {
        "protocol_version": PROTOCOL_VERSION,
        "hidden_master_seed": key,
        "hidden_config": hidden_config,
        "semantic_factor_split": split,
    }
    public_target, offline_target = Path(public_path), Path(offline_path)
    if public_target.exists() or offline_target.exists():
        raise FileExistsError("Refusing to overwrite an existing formal protocol file.")
    public_target.parent.mkdir(parents=True, exist_ok=True)
    offline_target.parent.mkdir(parents=True, exist_ok=True)
    public_target.write_text(json.dumps(public, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    offline_target.write_text(json.dumps(offline, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return public_target, offline_target


def create_multiround_manifest(
    formal_manifest_path: str | Path,
    *,
    output_path: str | Path,
    trajectory_seeds: tuple[int, ...] = tuple(range(1, 11)),
    rounds: int = 10,
) -> Path:
    """Derive a public multi-round manifest from an already committed protocol.

    The two experiments share the same hidden commitment and environment
    contracts, but have distinct manifest hashes for independent HMAC streams.
    """
    formal = json.loads(Path(formal_manifest_path).read_text(encoding="utf-8"))
    target = Path(output_path)
    if target.exists():
        raise FileExistsError("Refusing to overwrite an existing multi-round manifest.")
    manifest = {
        "protocol_version": PROTOCOL_VERSION,
        "manifest_version": "multiround-v1",
        "seed": formal["seed"],
        "rounds": rounds,
        "trajectory_seeds": list(trajectory_seeds),
        "audit_budget_pairs": formal["audit_budget_pairs"],
        "evolve_tasks_per_event": formal["evolve_tasks_per_event"],
        "environment_contracts": formal["environment_contracts"],
        "hidden_commitments": formal["hidden_commitments"],
        "methods": ["direct_commit", "rsea_fixed_validation", "fixed_random_audit", "evoaudit_mr"],
        "static_reference": True,
        "rsea_report_checkpoints": ["working@T", "frozen_best"],
        "final_hidden_tasks_per_bucket": 30,
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--public", required=True, help="Path for the public formal manifest.")
    parser.add_argument("--offline", required=True, help="Path for the private offline reveal file.")
    parser.add_argument("--multiround", required=True, help="Path for the public multi-round manifest.")
    args = parser.parse_args()
    public, _ = create_protocol_files(
        args.project_root,
        public_path=args.public,
        offline_path=args.offline,
    )
    create_multiround_manifest(public, output_path=args.multiround)


if __name__ == "__main__":
    main()
