"""Record a one-time, secret-free API preflight before an LLM Track is sealed."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Callable, Mapping

from evoaudit_mr.llm.client import OpenAICompatibleClient
from evoaudit_mr.llm.compiler import compile_proposed_patch
from evoaudit_mr.llm.config import LLMProposalConfig
from evoaudit_mr.llm.proposal import ProposalValidationError, build_proposal_messages, parse_response_json, proposal_json_schema


FREEZE_VERSION = "llm-proposal-freeze-v1"


def _hash_json(value: Mapping[str, Any]) -> str:
    return sha256(json.dumps(dict(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")).hexdigest()


def preflight_context() -> tuple[list[dict[str, str]], tuple[str, ...]]:
    """A tiny public context that validates the production JSON proposal path."""
    return build_proposal_messages(
        environment="AliasTool",
        parent_harness={"prompt_strategy": "inventory assistant", "tool_adapters": [], "workflow": "query_then_answer"},
        visible_traces=[
            {
                "trace_id": "preflight-trace-001",
                "observation": "The declared lookup tool returns a stock field under an alias.",
                "outcome": "The current harness did not answer the inventory query.",
            }
        ],
    )


def freeze_model(
    config: LLMProposalConfig,
    *,
    output_path: str | Path,
    client_factory: Callable[[LLMProposalConfig], OpenAICompatibleClient] = OpenAICompatibleClient,
) -> Path:
    """Call one schema probe and write an immutable public freeze record.

    The API key remains in the process environment. The record stores request
    settings, deployment response model, token accounting, and content hashes;
    it intentionally omits the secret header and raw response text.
    """
    output = Path(output_path)
    if output.exists():
        raise FileExistsError("LLM freeze record already exists and must not be overwritten.")
    messages, trace_ids = preflight_context()
    client = client_factory(config)
    completion = client.complete(messages)
    try:
        proposed = parse_response_json(completion.content, allowed_evidence_ids=trace_ids)
        compiled_patch = compile_proposed_patch(
            proposed,
            environment="AliasTool",
            patch_id="llm-preflight-candidate",
            parent_adapter="broken_adapter",
        )
    except (ProposalValidationError, ValueError) as exc:
        raise ValueError(f"model response failed the executable proposal contract: {exc}") from exc
    request_payload = client.request_payload(messages)
    record = {
        "freeze_version": FREEZE_VERSION,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "public_config": config.to_dict(),
        "public_config_sha256": config.fingerprint,
        "proposal_schema_sha256": _hash_json(proposal_json_schema()),
        "preflight_request_sha256": _hash_json(request_payload),
        "provider_reported_model": completion.model,
        "usage": dict(completion.usage),
        "proposal_sha256": proposed.fingerprint,
        "compiled_patch_sha256": _hash_json(compiled_patch.to_dict()),
        "api_key_policy": "API key is read only from the configured environment variable and is not stored in this record.",
        "retry_policy": config.invalid_policy,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output
