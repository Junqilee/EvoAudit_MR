"""Create an immutable-content manifest for the sealed Stage-4 experiment.

The seal records hashes of the original formal and multi-round artifacts plus
their public configuration.  It intentionally does not copy or expose the
offline HMAC key; the public seed commitment already binds that key.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path


SEAL_VERSION = "stage4-seal-v1"


def _sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _tree_manifest(directory: Path) -> list[dict[str, object]]:
    if not directory.exists():
        raise FileNotFoundError(directory)
    files = [path for path in sorted(directory.rglob("*")) if path.is_file()]
    return [
        {
            "path": path.relative_to(directory).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": _sha256(path),
        }
        for path in files
    ]


def run(
    *,
    project_root: str | Path,
    formal_dir: str | Path,
    multiround_dir: str | Path,
    corrected_results_dir: str | Path,
    output_path: str | Path,
) -> Path:
    """Write the immutable Stage-4 artifact manifest once and never overwrite it."""
    root = Path(project_root)
    formal = Path(formal_dir)
    multiround = Path(multiround_dir)
    corrected = Path(corrected_results_dir)
    output = Path(output_path)
    if output.exists():
        raise FileExistsError("Stage-4 seal already exists and must not be overwritten.")
    public_configs = [
        root / "configs" / "formal_v1_manifest.json",
        root / "configs" / "multiround_v1_manifest.json",
        root / "configs" / "aliastool_contract.json",
        root / "configs" / "switchrule_contract.json",
        root / "configs" / "permissionpath_contract.json",
    ]
    payload = {
        "seal_version": SEAL_VERSION,
        "sealed_runs": {
            "formal_candidate": {"path": str(formal), "files": _tree_manifest(formal)},
            "multiround": {"path": str(multiround), "files": _tree_manifest(multiround)},
        },
        "public_config_hashes": {
            path.relative_to(root).as_posix(): _sha256(path) for path in public_configs
        },
        "corrected_results_layer": {
            "path": str(corrected),
            "files": _tree_manifest(corrected),
            "note": "Analysis-only correction; it is not part of the sealed online/offline record.",
        },
        "offline_key_policy": "The offline key is not stored here. Its public SHA-256 commitment is in formal_v1_manifest.json.",
        "statistical_units": {
            "candidate": "30 mechanism clusters, each with 6 parameter instances (180 events total)",
            "multiround": "30 shared (environment, seed) scenarios; 120 method trajectories; 1200 round records",
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--formal-dir", required=True)
    parser.add_argument("--multiround-dir", required=True)
    parser.add_argument("--corrected-results-dir", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    run(
        project_root=args.project_root,
        formal_dir=args.formal_dir,
        multiround_dir=args.multiround_dir,
        corrected_results_dir=args.corrected_results_dir,
        output_path=args.output,
    )


if __name__ == "__main__":
    main()
