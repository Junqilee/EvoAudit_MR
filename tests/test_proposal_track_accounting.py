from __future__ import annotations

import unittest

from evoaudit_mr.llm.proposal_track_accounting import ProposalTrackAccountingError, validate_label_cardinalities


def _ledger() -> list[dict[str, object]]:
    return [
        {"slot_id": "s1", "environment": "AliasTool", "trajectory_seed": 11, "proposal_status": "executable"},
        {"slot_id": "s2", "environment": "PermissionPath", "trajectory_seed": 11, "proposal_status": "executable"},
        {"slot_id": "s3", "environment": "AliasTool", "trajectory_seed": 12, "proposal_status": "behavioral_noop"},
    ]


def _canonical() -> list[dict[str, object]]:
    return [{"event_id": "canonical-s1", "slot_id": "s1"}, {"event_id": "canonical-s2", "slot_id": "s2"}]


def _method_labels() -> list[dict[str, object]]:
    methods = ("direct", "rsea")
    return [{"event_id": f"persistent-{method}-{slot}", "method": method, "slot_id": slot} for slot in ("s1", "s2") for method in methods]


class ProposalTrackAccountingTests(unittest.TestCase):
    def test_reports_three_explicit_statistical_units(self) -> None:
        units = validate_label_cardinalities(_ledger(), _canonical(), _method_labels(), dynamic_methods=("direct", "rsea"))
        self.assertEqual({"unique_canonical_candidates": 2, "method_parent_decision_events": 4, "trajectories": 3}, units.to_dict())

    def test_duplicate_canonical_event_id_fails_closed(self) -> None:
        labels = _canonical()
        labels[1] = {"event_id": "canonical-s1", "slot_id": "s2"}
        with self.assertRaisesRegex(ProposalTrackAccountingError, "duplicate event_id"):
            validate_label_cardinalities(_ledger(), labels, _method_labels(), dynamic_methods=("direct", "rsea"))

    def test_missing_method_parent_label_fails_closed(self) -> None:
        with self.assertRaisesRegex(ProposalTrackAccountingError, "executable candidates × dynamic methods"):
            validate_label_cardinalities(_ledger(), _canonical(), _method_labels()[:-1], dynamic_methods=("direct", "rsea"))


if __name__ == "__main__":
    unittest.main()
