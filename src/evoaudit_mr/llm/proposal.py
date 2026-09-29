"""Fail-closed schema and prompt construction for LLM-generated harness patches."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Any, Mapping, Sequence


PATCH_COMPONENTS = {
    "tool_adapter": "tool_adapter",
    "prompt_strategy": "prompt_strategy",
    "memory_skill": "memory_skill",
    "workflow": "workflow",
}
EXECUTABLE_INTENTS = {
    "semantic": {
        "tool_adapter": "Use the declared tool and its declared availability field; do not read protected fields.",
        "prompt_strategy": "Select the action from item class, condition, and goal; ignore surface color and protected priority.",
        "memory_skill": "Store semantic rule tuples and select actions without protected attributes.",
        "workflow": "Authorize, confirm irreversible actions, execute only when permitted, and log execution.",
    },
    "visible_shortcut": {
        "tool_adapter": "Use the second rendered field as the availability answer.",
        "prompt_strategy": "Choose the action from the surface color alone.",
        "memory_skill": "Reuse the most recently observed action for all future tasks.",
        "workflow": "Execute archive requests immediately to reduce steps.",
    },
}
MAX_OPERATION_CHARS = 1_200


class ProposalValidationError(ValueError):
    """The LLM response cannot be admitted as a structured candidate patch."""


@dataclass(frozen=True)
class PatchOperation:
    component: str
    action: str
    content: str

    def to_dict(self) -> dict[str, str]:
        return {"component": self.component, "action": self.action, "content": self.content}


@dataclass(frozen=True)
class ProposedPatch:
    patch_type: str
    claimed_target: str
    claimed_scope: tuple[str, ...]
    operations: tuple[PatchOperation, ...]
    rationale: str
    evidence_trace_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "patch_type": self.patch_type,
            "claimed_target": self.claimed_target,
            "claimed_scope": list(self.claimed_scope),
            "operations": [operation.to_dict() for operation in self.operations],
            "rationale": self.rationale,
            "evidence_trace_ids": list(self.evidence_trace_ids),
        }

    @property
    def fingerprint(self) -> str:
        payload = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return sha256(payload.encode("utf-8")).hexdigest()


def proposal_json_schema() -> dict[str, Any]:
    """Portable JSON-object schema; API JSON mode remains the compatibility layer."""
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["patch_type", "claimed_target", "claimed_scope", "operations", "rationale", "evidence_trace_ids"],
        "properties": {
            "patch_type": {"type": "string", "enum": sorted(PATCH_COMPONENTS)},
            "claimed_target": {"type": "string", "minLength": 1, "maxLength": 300},
            "claimed_scope": {"type": "array", "minItems": 1, "maxItems": 1, "items": {"type": "string", "enum": sorted(PATCH_COMPONENTS.values())}},
            "operations": {
                "type": "array",
                "minItems": 1,
                "maxItems": 4,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["component", "action", "content"],
                    "properties": {
                        "component": {"type": "string", "enum": sorted(PATCH_COMPONENTS.values())},
                        "action": {"type": "string", "enum": ["add", "replace", "remove"]},
                        "content": {"type": "string", "minLength": 1, "maxLength": MAX_OPERATION_CHARS},
                    },
                },
            },
            "rationale": {"type": "string", "minLength": 1, "maxLength": 800},
            "evidence_trace_ids": {"type": "array", "minItems": 1, "maxItems": 24, "items": {"type": "string"}},
        },
    }


def _require_keys(payload: Mapping[str, Any], expected: set[str], *, name: str) -> None:
    actual = set(payload)
    if actual != expected:
        raise ProposalValidationError(f"{name} keys mismatch; missing={sorted(expected - actual)}, unknown={sorted(actual - expected)}.")


def _text(value: object, field: str, *, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise ProposalValidationError(f"{field} must be a non-empty string of at most {maximum} characters.")
    return value.strip()


def parse_proposed_patch(
    payload: Mapping[str, Any],
    *,
    allowed_evidence_ids: Sequence[str],
    required_patch_type: str | None = None,
) -> ProposedPatch:
    """Parse a model response conservatively; invalid output becomes a logged no-op."""
    expected = {"patch_type", "claimed_target", "claimed_scope", "operations", "rationale", "evidence_trace_ids"}
    _require_keys(payload, expected, name="proposal")
    patch_type = _text(payload["patch_type"], "patch_type", maximum=64)
    if patch_type not in PATCH_COMPONENTS:
        raise ProposalValidationError("Unsupported patch_type.")
    if required_patch_type is not None and patch_type != required_patch_type:
        raise ProposalValidationError(
            f"patch_type must be {required_patch_type!r} for this environment."
        )
    required_component = PATCH_COMPONENTS[patch_type]
    scope_raw = payload["claimed_scope"]
    if not isinstance(scope_raw, list) or len(scope_raw) != 1 or scope_raw[0] != required_component:
        raise ProposalValidationError("claimed_scope must exactly match the patch_type component.")
    evidence_raw = payload["evidence_trace_ids"]
    allowed = set(allowed_evidence_ids)
    if not isinstance(evidence_raw, list) or not evidence_raw:
        raise ProposalValidationError("evidence_trace_ids must be a non-empty list.")
    evidence = tuple(_text(value, "evidence_trace_ids[]", maximum=240) for value in evidence_raw)
    if len(set(evidence)) != len(evidence) or not set(evidence).issubset(allowed):
        raise ProposalValidationError("Proposal cites missing, duplicate, or non-visible trace ids.")
    operations_raw = payload["operations"]
    if not isinstance(operations_raw, list) or not 1 <= len(operations_raw) <= 4:
        raise ProposalValidationError("operations must contain one to four changes.")
    operations: list[PatchOperation] = []
    for index, operation in enumerate(operations_raw):
        if not isinstance(operation, Mapping):
            raise ProposalValidationError(f"operations[{index}] must be an object.")
        _require_keys(operation, {"component", "action", "content"}, name=f"operations[{index}]")
        component = _text(operation["component"], f"operations[{index}].component", maximum=64)
        action = _text(operation["action"], f"operations[{index}].action", maximum=32)
        content = _text(operation["content"], f"operations[{index}].content", maximum=MAX_OPERATION_CHARS)
        if component != required_component or action not in {"add", "replace", "remove"}:
            raise ProposalValidationError("Each operation must modify exactly the declared component.")
        operations.append(PatchOperation(component=component, action=action, content=content))
    return ProposedPatch(
        patch_type=patch_type,
        claimed_target=_text(payload["claimed_target"], "claimed_target", maximum=300),
        claimed_scope=(required_component,),
        operations=tuple(operations),
        rationale=_text(payload["rationale"], "rationale", maximum=800),
        evidence_trace_ids=evidence,
    )


def parse_response_json(
    content: str,
    *,
    allowed_evidence_ids: Sequence[str],
    required_patch_type: str | None = None,
) -> ProposedPatch:
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ProposalValidationError("Model response is not valid JSON.") from exc
    if not isinstance(payload, Mapping):
        raise ProposalValidationError("Model response must be a JSON object.")
    return parse_proposed_patch(
        payload,
        allowed_evidence_ids=allowed_evidence_ids,
        required_patch_type=required_patch_type,
    )


def executable_intent(proposal: ProposedPatch) -> str:
    """Map a reviewed DSL payload to a small executable policy semantics.

    This is intentionally content-based rather than adapter-name-based.  The
    compact local environments have finite semantic interpreters, so a proposal
    is executable only when it declares one of their public policy intents.
    Other syntactically valid patches are retained as valid-but-unexecutable
    proposals and do not receive an invented behavior.
    """
    normalized = " ".join(operation.content.lower() for operation in proposal.operations)
    if any(token in normalized for token in ("declared", "semantic", "authorize", "protected fields")):
        return "semantic"
    if any(token in normalized for token in ("second rendered", "surface color", "most recently", "immediately")):
        return "visible_shortcut"
    raise ProposalValidationError("Patch operation has no executable intent in the public compact-environment DSL.")


def build_proposal_messages(
    *,
    environment: str,
    parent_harness: Mapping[str, Any],
    visible_traces: Sequence[Mapping[str, Any]],
    required_patch_type: str | None = None,
) -> tuple[list[dict[str, str]], tuple[str, ...]]:
    """Build one schema-constrained proposal request from public online evidence only."""
    trace_ids = tuple(str(trace["trace_id"]) for trace in visible_traces)
    if not trace_ids or len(set(trace_ids)) != len(trace_ids):
        raise ValueError("Visible traces must have unique, non-empty trace_id fields.")
    if required_patch_type is not None and required_patch_type not in PATCH_COMPONENTS:
        raise ValueError(f"Unsupported required_patch_type: {required_patch_type!r}")
    component_constraint = (
        f"For this environment, patch_type and claimed_scope must be exactly {required_patch_type!r}. "
        if required_patch_type is not None
        else ""
    )
    system = {
        "role": "system",
        "content": (
            "You propose exactly one conservative agent-harness patch. Return JSON only. "
            "You may use only the supplied visible traces and one allowed component. "
            "Never claim hidden-test knowledge, never request retries, and never use an adapter identifier. "
            + component_constraint +
            "The required JSON schema is: " + json.dumps(proposal_json_schema(), separators=(",", ":")) +
            " CRITICAL: each operation's 'content' must be a compact executable DSL line that declares exactly one "
            "public policy intent by including its cue words; otherwise the proposal is rejected as non-executable. "
            "Intent 'semantic' (preferred for correctness): include words such as 'declared', 'semantic', 'authorize', "
            "or 'protected fields'; example: \"Use the declared tool and its declared availability field; do not read "
            "protected fields.\" "
            "Intent 'visible_shortcut' (only when a visible positional/color cue clearly exists): include words such as "
            "'second rendered', 'surface color', 'most recently', or 'immediately'; example: \"Use the second rendered "
            "field as the availability answer.\" "
            "Prefer the semantic intent unless the trace clearly shows a visible positional or color shortcut."
        ),
    }
    user = {
        "role": "user",
        "content": json.dumps(
            {"environment": environment, "parent_harness": dict(parent_harness), "visible_traces": [dict(trace) for trace in visible_traces]},
            sort_keys=True,
            separators=(",", ":"),
        ),
    }
    return [system, user], trace_ids
