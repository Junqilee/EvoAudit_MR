"""Simplified model-output contract for the independent V3b typed-policy track."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Any, Mapping, Sequence

from evoaudit_mr.llm.v3_ir import (
    MAX_TEXT,
    TypedAssignment,
    V3IRValidationError,
    V3ProposedPatch,
    _FIELDS,
    parse_v3_proposed_patch,
)


_PATCH_TYPE = {"AliasTool": "tool_adapter", "PermissionPath": "workflow"}


@dataclass(frozen=True)
class V3BProposedPatch:
    environment: str
    claimed_target: str
    policy_delta: tuple[TypedAssignment, ...]
    natural_language_instruction: str
    rationale: str
    evidence_trace_ids: tuple[str, ...]

    @property
    def patch_type(self) -> str:
        return _PATCH_TYPE[self.environment]

    @property
    def claimed_scope(self) -> tuple[str, ...]:
        return (self.patch_type,)

    def to_model_dict(self) -> dict[str, Any]:
        return {
            "claimed_target": self.claimed_target,
            "policy_delta": [assignment.to_dict() for assignment in self.policy_delta],
            "natural_language_instruction": self.natural_language_instruction,
            "rationale": self.rationale,
            "evidence_trace_ids": list(self.evidence_trace_ids),
        }

    def to_compiler_proposal(self) -> V3ProposedPatch:
        return V3ProposedPatch(
            patch_type=self.patch_type,
            claimed_target=self.claimed_target,
            claimed_scope=self.claimed_scope,
            policy_delta=self.policy_delta,
            natural_language_instruction=self.natural_language_instruction,
            rationale=self.rationale,
            evidence_trace_ids=self.evidence_trace_ids,
        )

    @property
    def fingerprint(self) -> str:
        payload = json.dumps(self.to_model_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return sha256(payload.encode("utf-8")).hexdigest()


def v3b_proposal_json_schema(environment: str) -> dict[str, Any]:
    if environment not in _FIELDS:
        raise ValueError(f"Unsupported V3b environment: {environment}")
    choices = []
    for field, values in _FIELDS[environment].items():
        choices.append(
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["field", "value"],
                "properties": {
                    "field": {"const": field},
                    "value": {"enum": list(values)},
                },
            }
        )
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["claimed_target", "policy_delta", "natural_language_instruction", "rationale", "evidence_trace_ids"],
        "properties": {
            "claimed_target": {"type": "string", "minLength": 1, "maxLength": 300},
            "policy_delta": {"type": "array", "minItems": 1, "maxItems": 3, "items": {"oneOf": choices}},
            "natural_language_instruction": {"type": "string", "minLength": 1, "maxLength": MAX_TEXT},
            "rationale": {"type": "string", "minLength": 1, "maxLength": MAX_TEXT},
            "evidence_trace_ids": {"type": "array", "minItems": 1, "maxItems": 24, "items": {"type": "string"}},
        },
    }


def parse_v3b_proposed_patch(payload: Mapping[str, Any], *, environment: str, allowed_evidence_ids: Sequence[str]) -> V3BProposedPatch:
    expected = {"claimed_target", "policy_delta", "natural_language_instruction", "rationale", "evidence_trace_ids"}
    if set(payload) != expected:
        missing, unknown = expected - set(payload), set(payload) - expected
        raise V3IRValidationError(f"V3b proposal keys mismatch; missing={sorted(missing)}, unknown={sorted(unknown)}.")
    # Reuse the V3 typed-delta validator after injecting system-owned fields.
    validated = parse_v3_proposed_patch(
        {
            "patch_type": _PATCH_TYPE[environment],
            "claimed_target": payload["claimed_target"],
            "claimed_scope": [_PATCH_TYPE[environment]],
            "policy_delta": payload["policy_delta"],
            "natural_language_instruction": payload["natural_language_instruction"],
            "rationale": payload["rationale"],
            "evidence_trace_ids": payload["evidence_trace_ids"],
        },
        environment=environment,
        allowed_evidence_ids=allowed_evidence_ids,
    )
    return V3BProposedPatch(
        environment=environment,
        claimed_target=validated.claimed_target,
        policy_delta=validated.policy_delta,
        natural_language_instruction=validated.natural_language_instruction,
        rationale=validated.rationale,
        evidence_trace_ids=validated.evidence_trace_ids,
    )


def parse_v3b_response_json(content: str, *, environment: str, allowed_evidence_ids: Sequence[str]) -> V3BProposedPatch:
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        raise V3IRValidationError("Model response is not valid JSON.") from exc
    if not isinstance(payload, Mapping):
        raise V3IRValidationError("Model response must be a JSON object.")
    return parse_v3b_proposed_patch(payload, environment=environment, allowed_evidence_ids=allowed_evidence_ids)


def build_v3b_proposal_messages(
    *,
    environment: str,
    parent_policy: Mapping[str, Any],
    visible_traces: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, str]], tuple[str, ...], dict[str, Any]]:
    trace_ids = tuple(str(trace.get("trace_id", "")) for trace in visible_traces)
    if not trace_ids or len(set(trace_ids)) != len(trace_ids) or any(not item for item in trace_ids):
        raise ValueError("Visible traces must have unique, non-empty trace IDs.")
    schema = v3b_proposal_json_schema(environment)
    system = {
        "role": "system",
        "content": (
            "Return exactly one JSON object conforming to the supplied schema. Use only visible traces. "
            "Propose the smallest public policy update that addresses the observed failure. "
            "Do not return patch_type or claimed_scope: the system determines them from the environment. "
            "Do not mention hidden evaluation, reliability labels, adapter identifiers, or retries. "
            "The schema is: " + json.dumps(schema, sort_keys=True, separators=(",", ":"))
        ),
    }
    user = {
        "role": "user",
        "content": json.dumps(
            {"environment": environment, "parent_policy": dict(parent_policy), "visible_traces": [dict(trace) for trace in visible_traces]},
            sort_keys=True,
            separators=(",", ":"),
        ),
    }
    return [system, user], trace_ids, schema
