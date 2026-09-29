"""Seal the independently run OOD challenge without exposing its HMAC key."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path


SEAL_VERSION = "ood-challenge-seal-v1"


def _sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _tree_manifest(directory: Path) -> list[dict[str, object]]:
    if not directory.exists():
        raise FileNotFoundError(directory)
    return [
        {
            "path": path.relative_to(directory).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": _sha256(path),
        }
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    ]


def run(*, project_root: str | Path, challenge_dir: str | Path, output_path: str | Path) -> Path:
    """Write a one-time content manifest for a completed OOD challenge."""
    root, challenge, output = Path(project_root), Path(challenge_dir), Path(output_path)
    if output.exists():
        raise FileExistsError("OOD challenge seal already exists and must not be overwritten.")
    public_manifest = root / "configs" / "ood_challenge_v1_manifest.json"
    lock = challenge / "ONLINE_COMPLETE.json"
    if not public_manifest.exists() or not lock.exists():
        raise FileNotFoundError("Expected public OOD manifest and online-phase lock.")
    payload = {
        "seal_version": SEAL_VERSION,
        "challenge_path": str(challenge),
        "files": _tree_manifest(challenge),
        "public_manifest": {
            "path": public_manifest.relative_to(root).as_posix(),
            "sha256": _sha256(public_manifest),
        },
        "online_lock_sha256": _sha256(lock),
        "offline_key_policy": "The offline HMAC key is excluded; the public manifest records its SHA-256 commitment.",
        "statistical_unit": "24 unseen mechanism families, each with 3 parameter instances (72 events total).",
        "analysis_policy": "This challenge is frozen after offline reveal and must not be used to tune the MR library.",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--challenge-dir", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    run(project_root=args.project_root, challenge_dir=args.challenge_dir, output_path=args.output)


if __name__ == "__main__":
    main()
