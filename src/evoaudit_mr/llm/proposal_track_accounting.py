"""Cardinality invariants for independently sealed LLM-proposal tracks.

These helpers deliberately operate on serialised records rather than a
particular proposal IR.  A future Qwen/DeepSeek track must label each
executable canonical candidate once, then label the same candidate once for
each dynamic method under that method's current parent.  This prevents a
canonical label from being accidentally replicated by method-level decisions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence


class ProposalTrackAccountingError(AssertionError):
    """A label table does not match its sealed candidate ledger."""


@dataclass(frozen=True)
class ProposalTrackUnits:
    """Explicit statistical units reported by Gate B and final analysis."""

    unique_canonical_candidates: int
    method_parent_decision_events: int
    trajectories: int

    def to_dict(self) -> dict[str, int]:
        return {
            "unique_canonical_candidates": self.unique_canonical_candidates,
            "method_parent_decision_events": self.method_parent_decision_events,
            "trajectories": self.trajectories,
        }


def _required_text(row: Mapping[str, Any], field: str, *, table: str) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not value:
        raise ProposalTrackAccountingError(f"{table} record lacks non-empty {field!r}.")
    return value


def _unique_by(rows: Iterable[Mapping[str, Any]], field: str, *, table: str) -> dict[str, Mapping[str, Any]]:
    indexed: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        key = _required_text(row, field, table=table)
        if key in indexed:
            raise ProposalTrackAccountingError(f"{table} contains duplicate {field}={key!r}.")
        indexed[key] = row
    return indexed


def _executable_ledger(ledger: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    executable = [row for row in ledger if row.get("proposal_status") == "executable"]
    return _unique_by(executable, "slot_id", table="executable candidate ledger")


def validate_label_cardinalities(
    ledger: Sequence[Mapping[str, Any]],
    canonical_labels: Sequence[Mapping[str, Any]],
    method_parent_labels: Sequence[Mapping[str, Any]],
    *,
    dynamic_methods: Sequence[str],
) -> ProposalTrackUnits:
    """Validate pre-registered candidate, method-parent, and trajectory units.

    ``method_parent_labels`` must contain a row even when re-materializing a
    canonical patch on a later method parent fails.  Such a row is an explicit
    fail-closed label/decision event (rather than a silent omission), so the
    product cardinality stays meaningful.
    """
    methods = tuple(dynamic_methods)
    if not methods or len(set(methods)) != len(methods):
        raise ProposalTrackAccountingError("dynamic_methods must be non-empty and unique.")
    candidates = _executable_ledger(ledger)
    candidate_slots = set(candidates)

    canonical_by_event = _unique_by(canonical_labels, "event_id", table="canonical labels")
    canonical_by_slot = _unique_by(canonical_labels, "slot_id", table="canonical labels")
    if set(canonical_by_slot) != candidate_slots:
        missing = sorted(candidate_slots - set(canonical_by_slot))
        extra = sorted(set(canonical_by_slot) - candidate_slots)
        raise ProposalTrackAccountingError(f"canonical labels must equal executable candidates; missing={missing}, extra={extra}.")
    if len(canonical_by_event) != len(candidates):
        raise ProposalTrackAccountingError("unique canonical labels must equal executable candidates.")

    method_event_ids = _unique_by(method_parent_labels, "event_id", table="method-parent labels")
    method_slot_method: set[tuple[str, str]] = set()
    for row in method_parent_labels:
        slot = _required_text(row, "slot_id", table="method-parent labels")
        method = _required_text(row, "method", table="method-parent labels")
        pair = (slot, method)
        if pair in method_slot_method:
            raise ProposalTrackAccountingError(f"method-parent labels contain duplicate slot/method pair {pair!r}.")
        method_slot_method.add(pair)
    expected_pairs = {(slot, method) for slot in candidate_slots for method in methods}
    if method_slot_method != expected_pairs:
        missing = sorted(expected_pairs - method_slot_method)
        extra = sorted(method_slot_method - expected_pairs)
        raise ProposalTrackAccountingError(f"method-parent labels must equal executable candidates × dynamic methods; missing={missing}, extra={extra}.")
    if len(method_event_ids) != len(expected_pairs):
        raise ProposalTrackAccountingError("method-parent event IDs must be unique and complete.")

    trajectories: set[tuple[str, int]] = set()
    for row in ledger:
        environment = _required_text(row, "environment", table="candidate ledger")
        seed = row.get("trajectory_seed")
        if not isinstance(seed, int):
            raise ProposalTrackAccountingError("candidate ledger record lacks integer trajectory_seed.")
        trajectories.add((environment, seed))
    return ProposalTrackUnits(
        unique_canonical_candidates=len(candidates),
        method_parent_decision_events=len(expected_pairs),
        trajectories=len(trajectories),
    )
