"""Immutable local-model freeze records for the Ollama LLM Proposal Pilot."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping

from evoaudit_mr.llm.compiler import compile_proposed_patch
from evoaudit_mr.llm.ollama import OllamaClient
from evoaudit_mr.llm.proposal import build_proposal_messages, parse_response_json, proposal_json_schema


FREEZE_VERSION = "ollama-pilot-freeze-v1"


def _canonical_hash(value: object) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")).hexdigest()


def freeze_ollama(
    public_protocol: Mapping[str, Any],
    *,
    output_path: str | Path,
    client: OllamaClient | None = None,
) -> Path:
    """Make exactly one local preflight call and write a non-overwritable record."""
    output = Path(output_path)
    if output.exists():
        raise FileExistsError("OLLAMA_FREEZE already exists and must not be overwritten.")
    config = public_protocol["ollama"]
    if not isinstance(config, Mapping):
        raise ValueError("Public protocol lacks an ollama configuration.")
    local_client = client or OllamaClient(str(config["endpoint"]))
    messages, trace_ids = build_proposal_messages(
        environment="AliasTool",
        parent_harness={"prompt_strategy": "inventory assistant", "tool_adapters": [], "workflow": "query_then_answer"},
        visible_traces=[
            {
                "trace_id": "ollama-preflight-001",
                "observation": "The declared lookup tool returns a stock field under an alias.",
                "outcome": "The current harness did not answer the inventory query.",
            }
        ],
        required_patch_type="tool_adapter",
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
    proposal = parse_response_json(
        completion.content,
        allowed_evidence_ids=trace_ids,
        required_patch_type="tool_adapter",
    )
    patch = compile_proposed_patch(
        proposal,
        environment="AliasTool",
        patch_id="ollama-preflight-candidate",
        parent_adapter="broken_adapter",
    )
    record = {
        "freeze_version": FREEZE_VERSION,
        "public_protocol_sha256": _canonical_hash(dict(public_protocol)),
        "model_info": info.to_dict(),
        "request_sha256": _canonical_hash(messages),
        "proposal_schema_sha256": _canonical_hash(proposal_json_schema()),
        "response_sha256": sha256(completion.content.encode("utf-8")).hexdigest(),
        "proposal_sha256": proposal.fingerprint,
        "compiled_patch_sha256": _canonical_hash(patch.to_dict()),
        "provider_reported_model": completion.model,
        "usage": dict(completion.usage),
        "latency_seconds": completion.latency_seconds,
        "one_call_policy": "One proposal per scenario slot; invalid and no-op proposals are recorded without retry.",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output
