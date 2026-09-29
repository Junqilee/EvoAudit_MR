from __future__ import annotations

import unittest

from evoaudit_mr.envs.aliastool import AuditedRecord, make_task, run_episode


class AliasToolTests(unittest.TestCase):
    def test_semantic_adapter_preserves_semantics_across_presentations(self) -> None:
        for index, profile in enumerate(("canonical", "alias", "reordered", "alias_reordered")):
            outcome = run_episode("semantic_adapter", make_task(profile, index))
            self.assertTrue(outcome.task_success, profile)
            self.assertEqual((), outcome.safety_events)

    def test_positional_adapter_breaks_when_field_order_changes(self) -> None:
        canonical = run_episode("positional_adapter", make_task("canonical", 0))
        reordered = run_episode("positional_adapter", make_task("reordered", 0))
        self.assertTrue(canonical.task_success)
        self.assertFalse(reordered.task_success)

    def test_shortcut_can_succeed_but_is_unsafe(self) -> None:
        outcome = run_episode("restricted_lookup_adapter", make_task("canonical", 0))
        self.assertTrue(outcome.task_success)
        self.assertTrue(any(event.startswith("undeclared_tool") for event in outcome.safety_events))
        self.assertTrue(any(event.startswith("protected_field") for event in outcome.safety_events))

    def test_audited_record_tracks_actual_field_access(self) -> None:
        record = AuditedRecord({"available_units": 7, "supplier_cost": 3})
        self.assertEqual(7, record["available_units"])
        self.assertEqual(["available_units"], record.access_log)

    def test_alias_quantity_field_is_integer_not_boolean(self) -> None:
        task = make_task("alias", 0)
        self.assertEqual("stock_count", task.available_field)
        self.assertIsInstance(task.public_record()["stock_count"], int)
