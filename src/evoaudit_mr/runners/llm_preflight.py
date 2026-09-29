"""Validate or freeze a Qwen/DeepSeek LLM proposal configuration."""

from __future__ import annotations

import argparse
import csv
import os
from pathlib import Path

from evoaudit_mr.llm.config import load_config
from evoaudit_mr.llm.freeze import freeze_model


def _read_api_key_from_csv(csv_path: str) -> str:
    """Extract the workspace apiKey from the aliyun-apiKey CSV (field,value rows)."""
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as fh:
        for row in csv.reader(fh):
            if len(row) >= 2 and row[0].strip() == "apiKey":
                key = row[1].strip()
                if key:
                    return key
    raise SystemExit(f"[ERROR] apiKey field not found in {csv_path}.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, help="Public JSON config containing no API key.")
    parser.add_argument("--mode", required=True, choices=("validate", "freeze"))
    parser.add_argument("--output", help="Required in freeze mode; a new immutable LLM_FREEZE.json path.")
    parser.add_argument(
        "--csv",
        default=None,
        help="Optional aliyun-apiKey CSV; its apiKey is injected into the configured env var (overrides the shell env).",
    )
    args = parser.parse_args()
    config = load_config(args.config)
    if args.csv:
        os.environ[config.api_key_env] = _read_api_key_from_csv(args.csv)
    if args.mode == "validate":
        print(f"valid provider={config.provider} model={config.model} config_sha256={config.fingerprint}")
        return
    if not args.output:
        parser.error("--output is required in freeze mode.")
    path = freeze_model(config, output_path=Path(args.output))
    print(path)


if __name__ == "__main__":
    main()
