"""Local model freeze for the typed-policy Ollama Pilot v3."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping

from evoaudit_mr.llm.ollama import OllamaClient
from evoaudit_mr.llm.v3_compiler import materialize_v3_patch
from evoaudit_mr.llm.v3_ir import (
    build_v3_proposal_messages,
    initial_typed_policy,
    parse_v3_response_json,
    v3_proposal_json_schema,
)
from evoaudit_mr.types import Harness


FREEZE_VERSION = "ollama-pilot-v3-freeze-v1"


def _hash(value: object) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")).hexdigest()


def freeze_ollama_v3(protocol: Mapping[str, Any], *, output_path: Path, client: OllamaClient | None = None) -> Path:
    if output_path.exists():
        raise FileExistsError("OLLAMA_FREEZE already exists and must not be overwritten.")
    config = protocol["ollama"]
    if not isinstance(config, Mapping):
        raise ValueError("V3 protocol lacks local Ollama configuration.")
    local_client = client or OllamaClient(str(config["endpoint"]))
    parent_policy = initial_typed_policy("AliasTool")
    messages, trace_ids = build_v3_proposal_messages(
        environment="AliasTool",
        parent_policy=parent_policy,
        visible_traces=[
            {
                "trace_id": "v3-preflight-001",
                "observation": "The declared interface returns stock using an alias field.",
                "outcome": "The current policy did not answer the request.",
            }
        ],
    )
    info = local_client.model_info(str(config["model"]))
    completion = local_client.complete(
        messages,
        model=str(config["model"]),
        temperature=float(config["temperature"]),
        top_p=float(config["top_p"]),
        seed=int(config["seed"]),
        num_predict=int(config["num_predict"]),
        timeout_seconds=int(config["timeout_seconds"]),
    )
    proposal = parse_v3_response_json(completion.content, environment="AliasTool", allowed_evidence_ids=trace_ids)
    patch = materialize_v3_patch(
        proposal,
        environment="AliasTool",
        patch_id="v3-ollama-preflight",
        parent=Harness(adapter_name="typed_aliastool_policy", typed_policy=parent_policy),
    )
    payload = {
        "freeze_version": FREEZE_VERSION,
        "public_protocol_sha256": _hash(dict(protocol)),
        "model_info": info.to_dict(),
        "request_sha256": _hash(messages),
        "proposal_schema_sha256": _hash(v3_proposal_json_schema("AliasTool")),
        "response_sha256": sha256(completion.content.encode("utf-8")).hexdigest(),
        "proposal_sha256": proposal.fingerprint,
        "compiled_patch_sha256": _hash(patch.to_dict()),
        "provider_reported_model": completion.model,
        "usage": dict(completion.usage),
        "latency_seconds": completion.latency_seconds,
        "one_call_policy": "One proposal per scenario slot; invalid and no-op proposals are recorded without retry.",
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output_path
