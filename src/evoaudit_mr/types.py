"""Typed, replayable records shared by the prototype components."""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import json
from typing import Any, Mapping


def stable_hash(payload: Mapping[str, Any]) -> str:
    """Hash a JSON-compatible payload independently of machine-local metadata."""
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return sha256(encoded.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class Harness:
    """A frozen-model agent harness with independently patchable components.

    ``adapter_name`` remains the executable policy selector for the compact
    environments.  The component fields make formal multi-round state changes
    explicit and replayable rather than overwriting an opaque single string.
    """

    adapter_name: str
    prompt_strategy: str = "inventory assistant"
    memory_skills: tuple[str, ...] = ()
    workflow: str = "query_then_answer"
    prompt_rules: tuple[str, ...] = ()
    tool_adapters: tuple[str, ...] = ()
    workflow_steps: tuple[str, ...] = ()
    # V3 keeps a structured policy state rather than encoding policy semantics
    # in an opaque adapter identifier.  Older experiments leave this empty and
    # therefore retain their original execution path.
    typed_policy: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "adapter_name": self.adapter_name,
            "prompt_strategy": self.prompt_strategy,
            "memory_skills": list(self.memory_skills),
            "workflow": self.workflow,
            "prompt_rules": list(self.prompt_rules),
            "tool_adapters": list(self.tool_adapters),
            "workflow_steps": list(self.workflow_steps),
            "typed_policy": dict(self.typed_policy),
        }

    @property
    def fingerprint(self) -> str:
        return stable_hash(self.to_dict())


@dataclass(frozen=True)
class Patch:
    patch_id: str
    patch_type: str
    claimed_target: str
    claimed_scope: tuple[str, ...]
    diff: Mapping[str, Any]
    candidate_adapter: str
    evidence_trace_ids: tuple[str, ...] = ()
    rationale: str = "controlled prototype patch"

    def to_dict(self) -> dict[str, Any]:
        return {
            "patch_id": self.patch_id,
            "type": self.patch_type,
            "claimed_target": self.claimed_target,
            "claimed_scope": list(self.claimed_scope),
            "diff": dict(self.diff),
            "candidate_adapter": self.candidate_adapter,
            "evidence_trace_ids": list(self.evidence_trace_ids),
            "rationale": self.rationale,
        }


@dataclass(frozen=True)
class AliasToolTask:
    """A semantic inventory task plus one rendered public-tool presentation."""

    task_id: str
    profile: str
    sku: str
    requested_units: int
    available_units: int
    supplier_cost: int
    tool_name: str
    parameter_name: str
    available_field: str
    protected_field: str
    distractor_field: str
    distractor_value: int
    field_order: tuple[str, ...]
    declared_tools: tuple[str, ...]
    tool_registry: tuple[str, ...]
    tags: tuple[str, ...] = ()

    @property
    def expected_answer(self) -> str:
        return "available" if self.available_units >= self.requested_units else "unavailable"

    def public_record(self) -> dict[str, Any]:
        values = {
            self.parameter_name: self.sku,
            self.available_field: self.available_units,
            self.protected_field: self.supplier_cost,
            self.distractor_field: self.distractor_value,
        }
        return {field: values[field] for field in self.field_order}

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "profile": self.profile,
            "sku": self.sku,
            "requested_units": self.requested_units,
            "available_units": self.available_units,
            "supplier_cost": self.supplier_cost,
            "tool_name": self.tool_name,
            "parameter_name": self.parameter_name,
            "available_field": self.available_field,
            "protected_field": self.protected_field,
            "distractor_field": self.distractor_field,
            "distractor_value": self.distractor_value,
            "field_order": list(self.field_order),
            "declared_tools": list(self.declared_tools),
            "tool_registry": list(self.tool_registry),
            "tags": list(self.tags),
        }


@dataclass(frozen=True)
class SwitchRuleTask:
    """A natural-language-style rule task with semantic and spurious attributes."""

    task_id: str
    profile: str
    item_class: str
    condition: str
    goal: str
    color: str
    expected_action: str
    protected_attribute: str
    sensitive_priority: int
    prohibited_actions: tuple[str, ...]
    tags: tuple[str, ...] = ()

    def public_state(self) -> dict[str, Any]:
        return {
            "item_class": self.item_class,
            "condition": self.condition,
            "goal": self.goal,
            "color": self.color,
            self.protected_attribute: self.sensitive_priority,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "profile": self.profile,
            "item_class": self.item_class,
            "condition": self.condition,
            "goal": self.goal,
            "color": self.color,
            "expected_action": self.expected_action,
            "protected_attribute": self.protected_attribute,
            "sensitive_priority": self.sensitive_priority,
            "prohibited_actions": list(self.prohibited_actions),
            "tags": list(self.tags),
        }


@dataclass(frozen=True)
class PermissionPathTask:
    """A service workflow task with independently verified action constraints."""

    task_id: str
    profile: str
    operation: str
    user_role: str
    authorized: bool
    confirmed: bool
    tenant_match: bool
    irreversible: bool
    tags: tuple[str, ...] = ()

    @property
    def execution_permitted(self) -> bool:
        return self.authorized and self.tenant_match and (not self.irreversible or self.confirmed)

    @property
    def expected_answer(self) -> str:
        return "executed" if self.execution_permitted else "denied"

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "profile": self.profile,
            "operation": self.operation,
            "user_role": self.user_role,
            "authorized": self.authorized,
            "confirmed": self.confirmed,
            "tenant_match": self.tenant_match,
            "irreversible": self.irreversible,
            "tags": list(self.tags),
        }


AgentTask = AliasToolTask | SwitchRuleTask | PermissionPathTask


@dataclass(frozen=True)
class EpisodeOutcome:
    task_id: str
    task_success: bool
    answer: str | None
    tool_calls: tuple[str, ...]
    fields_read: tuple[str, ...]
    safety_events: tuple[str, ...]
    error: str | None = None

    @property
    def cost(self) -> dict[str, int]:
        return {"tool_calls": len(self.tool_calls), "paired_rollouts": 1}

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "task_success": self.task_success,
            "answer": self.answer,
            "tool_calls": list(self.tool_calls),
            "fields_read": list(self.fields_read),
            "safety_events": list(self.safety_events),
            "error": self.error,
            "cost": self.cost,
        }


@dataclass(frozen=True)
class Probe:
    probe_id: str
    bucket: str
    mr_id: str
    task: AgentTask

    def to_dict(self) -> dict[str, Any]:
        return {
            "probe_id": self.probe_id,
            "bucket": self.bucket,
            "mr_id": self.mr_id,
            "task": self.task.to_dict(),
        }


@dataclass(frozen=True)
class AuditSuite:
    probes: tuple[Probe, ...]
    budget_pairs: int
    source: str

    def bucket(self, name: str) -> tuple[Probe, ...]:
        return tuple(probe for probe in self.probes if probe.bucket == name)

    def to_dict(self) -> dict[str, Any]:
        return {
            "budget_pairs": self.budget_pairs,
            "source": self.source,
            "probes": [probe.to_dict() for probe in self.probes],
        }


@dataclass(frozen=True)
class CandidateEvent:
    event_id: str
    parent: Harness
    patch: Patch
    visible_tasks: tuple[AgentTask, ...]
    heldout_tasks: tuple[AgentTask, ...]
    environment: str = "AliasTool"

    @property
    def candidate(self) -> Harness:
        typed_policy = self.patch.diff.get("typed_policy_after", self.parent.typed_policy)
        if not isinstance(typed_policy, Mapping):
            typed_policy = self.parent.typed_policy
        return Harness(
            adapter_name=self.patch.candidate_adapter,
            prompt_strategy=self.parent.prompt_strategy,
            memory_skills=self.parent.memory_skills,
            workflow=self.parent.workflow,
            prompt_rules=self.parent.prompt_rules,
            tool_adapters=self.parent.tool_adapters,
            workflow_steps=self.parent.workflow_steps,
            typed_policy=dict(typed_policy),
        )


@dataclass(frozen=True)
class ProbeResult:
    probe: Probe
    parent: EpisodeOutcome
    candidate: EpisodeOutcome

    @property
    def success_delta(self) -> int:
        return int(self.candidate.task_success) - int(self.parent.task_success)

    def to_dict(self) -> dict[str, Any]:
        return {
            "probe": self.probe.to_dict(),
            "parent": self.parent.to_dict(),
            "candidate": self.candidate.to_dict(),
            "success_delta": self.success_delta,
        }


@dataclass(frozen=True)
class GateDecision:
    method: str
    event_id: str
    decision: str
    reasons: tuple[str, ...]
    probe_results: tuple[ProbeResult, ...] = ()
    bucket_summary: Mapping[str, Any] = field(default_factory=dict)

    @property
    def committed(self) -> bool:
        return self.decision == "commit"
