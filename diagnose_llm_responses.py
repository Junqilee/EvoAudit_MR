"""Diagnose the Qwen API call without writing any freeze record.

Usage (PowerShell):
  ./.venv/Scripts/python.exe diagnose_llm_responses.py `
      --config configs/llm_proposal_v1_qwen.json
  # Force a specific protocol to compare endpoints:
  ./.venv/Scripts/python.exe diagnose_llm_responses.py `
      --config configs/llm_proposal_v1_qwen.json --protocol chat_completions
  # Send a minimal hardcoded request to isolate auth/workspace vs payload:
  ./.venv/Scripts/python.exe diagnose_llm_responses.py `
      --config configs/llm_proposal_v1_qwen.json --minimal
  # Run controlled probes (key validity + wrong-key + chat path) to isolate the cause:
  ./.venv/Scripts/python.exe diagnose_llm_responses.py `
      --config configs/llm_proposal_v1_qwen.json --deep

It builds the exact request body the client would send, prints request + proxy
env vars, POSTs it, and dumps the raw status / headers / body so you can read
the REAL provider error instead of a bare "Bad Request".
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from evoaudit_mr.llm.client import OpenAICompatibleClient  # noqa: E402
from evoaudit_mr.llm.config import load_config  # noqa: E402
from evoaudit_mr.llm.freeze import preflight_context  # noqa: E402


def dump(label: str, resp) -> None:
    print(f"=== {label} ===")
    print("status:", getattr(resp, "status", "?"))


def post(url: str, payload: dict, auth_key: str, label: str, timeout: float = 30.0) -> None:
    """POST JSON and dump status/headers/body (module-level, used by CSV discovery)."""
    print(f"\n===== {label} =====")
    print("URL:", url)
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    request = Request(
        url,
        data=body,
        headers={"Authorization": f"Bearer {auth_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as resp:
            print("status:", resp.status)
            print("headers:")
            for k, v in resp.headers.items():
                print(f"  {k}: {v}")
            raw = resp.read().decode("utf-8", errors="replace")
            print("body (head):", raw[:600])
            _dump_content(raw)
    except HTTPError as exc:
        print("HTTPError status:", exc.code)
        print("headers:")
        for k, v in exc.headers.items():
            print(f"  {k}: {v}")
        raw = exc.read().decode("utf-8", errors="replace")
        print("body (head):", raw[:600])
        _dump_content(raw)
    except URLError as exc:
        print("URLError reason:", exc.reason)


def _dump_content(raw: str) -> None:
    """If the body is a chat completion, extract the FINAL assistant content so
    we can see what the model actually emitted (reasoning_content is verbose)."""
    try:
        data = json.loads(raw)
    except Exception:
        return
    if not isinstance(data, Mapping):
        return
    msg = data.get("choices", [{}])[0].get("message", {})
    content = msg.get("content") if isinstance(msg, Mapping) else None
    if isinstance(content, str) and content.strip():
        print(">>> FINAL CONTENT:", content[:6000])


def discover_models(base_url: str, api_key: str) -> int:
    """Use the authoritative API info from the aliyun CSV to find the real model."""
    # 1) List available models via the OpenAI-compatible /models endpoint.
    models_url = base_url.rstrip("/") + "/models"
    print("===== LIST MODELS: GET", models_url, "=====")
    req = Request(models_url, headers={"Authorization": f"Bearer {api_key}"}, method="GET")
    available: list[str] = []
    try:
        with urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
            print("status:", resp.status)
            objs = data.get("data", data if isinstance(data, list) else [])
            for m in objs:
                mid = m.get("id") if isinstance(m, dict) else m
                if isinstance(mid, str):
                    available.append(mid)
            print("models found:", available if available else "(none / unexpected shape)")
    except HTTPError as exc:
        print("HTTPError status:", exc.code, "| body:", exc.read().decode("utf-8", errors="replace")[:600])
    except URLError as exc:
        print("URLError reason:", exc.reason)

    # 2) Probe a set of candidate model names with a minimal chat request.
    candidates = [
        "qwen3.7-plus", "qwen-plus", "qwen-max", "qwen-turbo", "qwen-long",
        "qwen3-plus", "qwen3-max", "qwen2.5-plus", "qwen2.5-72b-instruct",
    ]
    if available:
        # Prefer whatever the endpoint itself reports.
        candidates = available[:12]
    for model in candidates:
        post(
            base_url.rstrip("/") + "/chat/completions",
            {"model": model, "messages": [{"role": "user", "content": "Say hi in one word."}]},
            api_key,
            f"PROBE MODEL: {model}",
            timeout=20.0,
        )
    return 0


def parse_aliyun_csv(path: str) -> dict[str, str]:
    info: dict[str, str] = {}
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        for row in csv.reader(fh):
            if len(row) >= 2:
                info[row[0].strip()] = row[1].strip()
    return info


def replay_freeze(base_url: str, api_key: str, config_path: str) -> int:
    """Reproduce the EXACT freeze payload and bisect which field triggers the 400."""
    from evoaudit_mr.llm.config import load_config  # noqa: F401 (local import)
    from evoaudit_mr.llm.client import OpenAICompatibleClient
    from evoaudit_mr.llm.freeze import preflight_context

    cfg = load_config(config_path)
    cli = OpenAICompatibleClient(cfg)
    messages, _ = preflight_context()
    exact = cli.request_payload(messages)
    chat_url = base_url.rstrip("/") + "/chat/completions"

    print("\n##### EXACT freeze payload (what freeze_model actually sends) #####")
    post(chat_url, exact, api_key, "EXACT", timeout=float(cfg.timeout_seconds))
    # Bisect: drop response_format (JSON mode is often unsupported on reasoning models).
    v1 = {k: v for k, v in exact.items() if k != "response_format"}
    post(chat_url, v1, api_key, "VARIANT: drop response_format", timeout=float(cfg.timeout_seconds))
    # Bisect: drop the system message.
    v2 = dict(v1)
    v2["messages"] = [m for m in exact["messages"] if m.get("role") != "system"]
    post(chat_url, v2, api_key, "VARIANT: drop system message", timeout=float(cfg.timeout_seconds))
    # Bisect: drop temperature (reasoning models sometimes reject non-default temperature).
    v3 = {k: v for k, v in exact.items() if k != "temperature"}
    post(chat_url, v3, api_key, "VARIANT: drop temperature", timeout=float(cfg.timeout_seconds))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnose Qwen API call.")
    parser.add_argument("--config", required=True, help="Path to the LLM proposal config JSON.")
    parser.add_argument("--protocol", default=None, help="Override api_protocol (responses|chat_completions).")
    parser.add_argument("--minimal", action="store_true", help="Send a tiny hardcoded request to isolate auth/workspace vs payload.")
    parser.add_argument("--deep", action="store_true", help="Run controlled probes to isolate auth vs endpoint/path.")
    parser.add_argument("--from-csv", default=None, help="Path to aliyun-apiKey CSV; uses its apiKey + openAiCompatible as authoritative.")
    parser.add_argument("--replay", action="store_true", help="With --from-csv: replay the exact freeze payload and bisect fields.")
    args = parser.parse_args()

    if args.replay:
        # Reproduce the EXACT freeze request. When --from-csv is given we use the
        # authoritative CSV key; otherwise we use the env var that freeze_model
        # itself reads, so we can confirm whether the shell env key is the cause.
        if args.from_csv:
            info = parse_aliyun_csv(args.from_csv)
            base = info.get("openAiCompatible") or info.get("dashScope")
            key = info.get("apiKey")
            if not base or not key:
                print("[ERROR] CSV missing openAiCompatible/dashScope or apiKey.")
                return 2
            print("=== CSV API INFO ===")
            for k in ("apiHost", "openAiCompatible", "dashScope", "workspaceName", "workspaceId"):
                if k in info:
                    print(f"  {k}: {info[k]}")
        else:
            cfg_tmp = load_config(args.config)
            base = cfg_tmp.base_url
            key = os.environ.get(cfg_tmp.api_key_env, "").strip()
            if not key:
                print(f"[ERROR] Environment variable {cfg_tmp.api_key_env} is not set.")
                return 2
            print(f"=== USING ENV VAR: {cfg_tmp.api_key_env} (what freeze_model actually reads) ===")
        return replay_freeze(base, key, args.config)

    if args.from_csv:
        info = parse_aliyun_csv(args.from_csv)
        base = info.get("openAiCompatible") or info.get("dashScope")
        key = info.get("apiKey")
        if not base or not key:
            print("[ERROR] CSV missing openAiCompatible/dashScope or apiKey.")
            return 2
        print("=== CSV API INFO ===")
        for k in ("apiHost", "openAiCompatible", "dashScope", "workspaceName", "workspaceId"):
            if k in info:
                print(f"  {k}: {info[k]}")
        return discover_models(base, key)

    config = load_config(args.config)
    if args.protocol:
        config = config.from_mapping({**config.to_dict(), "api_protocol": args.protocol})
    client = OpenAICompatibleClient(config)

    key = os.environ.get(config.api_key_env, "").strip()
    if not key:
        print(f"[ERROR] Environment variable {config.api_key_env} is not set.")
        return 2

    def post(url: str, payload: dict, auth_key: str, label: str, timeout: float = float(config.timeout_seconds)) -> None:
        print(f"\n===== {label} =====")
        print("URL:", url)
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        request = Request(
            url,
            data=body,
            headers={"Authorization": f"Bearer {auth_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=timeout) as resp:
                print("status:", resp.status)
                print("headers:")
                for k, v in resp.headers.items():
                    print(f"  {k}: {v}")
                print("body:", resp.read().decode("utf-8", errors="replace")[:1500])
        except HTTPError as exc:
            print("HTTPError status:", exc.code)
            print("headers:")
            for k, v in exc.headers.items():
                print(f"  {k}: {v}")
            print("body:", exc.read().decode("utf-8", errors="replace")[:1500])
        except URLError as exc:
            print("URLError reason:", exc.reason)

    print("=== PROXY ENV VARS (relevant to outbound HTTPS) ===")
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "NO_PROXY", "no_proxy"):
        val = os.environ.get(name)
        if val:
            print(f"  {name}={val}")
    if not any(os.environ.get(n) for n in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy")):
        print("  (none set)")

    if args.deep:
        # Probe A: canonical DashScope endpoint with the SAME key -> is the key valid at all?
        post(
            "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
            {"model": "qwen-turbo", "messages": [{"role": "user", "content": "Say hi in one word."}]},
            key,
            "PROBE A: key validity via canonical DashScope (model=qwen-turbo)",
        )
        # Probe B: configured maas endpoint with a deliberately WRONG key.
        # If the error changes (e.g. becomes 401 JSON) -> an auth filter is active and the REAL key is suspect.
        # If it stays identical bare 400 -> the gateway rejects before/regardless of key -> endpoint/path problem.
        post(
            client._response_url(),
            {"model": config.model, "input": "Say hi in one word."},
            "WRONGKEY_FOR_PROBE_B_123456",
            "PROBE B: configured maas endpoint with a WRONG key (discriminate auth vs path)",
        )
        # Probe C: configured maas endpoint but pointing at chat/completions (no /responses path).
        post(
            config.base_url + "/chat/completions",
            {"model": config.model, "messages": [{"role": "user", "content": "Say hi in one word."}]},
            key,
            "PROBE C: configured maas endpoint /chat/completions (correct key)",
        )
        return 0

    if args.minimal:
        # Hardcoded minimal valid request, independent of preflight_context.
        if config.api_protocol == "responses":
            payload = {"model": config.model, "input": "Say hi in one word."}
        else:
            payload = {"model": config.model, "messages": [{"role": "user", "content": "Say hi in one word."}]}
    else:
        messages, _ = preflight_context()
        payload = client.request_payload(messages)

    post(client._response_url(), payload, key, "CONFIGURED REQUEST")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
