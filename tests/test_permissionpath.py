from __future__ import annotations

import unittest

from evoaudit_mr.envs.permissionpath import make_task, run_episode


class PermissionPathTests(unittest.TestCase):
    def test_semantic_workflow_completes_a_valid_irreversible_operation(self) -> None:
        outcome = run_episode("semantic_workflow_adapter", make_task("archive_valid", 0))
        self.assertTrue(outcome.task_success)
        self.assertEqual((), outcome.safety_events)
        self.assertEqual(("identify", "authorize", "confirm", "execute", "log"), outcome.tool_calls)

    def test_fast_bypass_can_complete_a_visible_task_but_violates_safety(self) -> None:
        visible = run_episode("fast_bypass_workflow_adapter", make_task("archive_valid", 0))
        unsafe = run_episode("fast_bypass_workflow_adapter", make_task("unconfirmed", 1))
        self.assertTrue(visible.task_success)
        self.assertFalse(unsafe.task_success)
        self.assertIn("irreversible_execution_without_confirmation", unsafe.safety_events)
        self.assertIn("execution_without_audit_log", unsafe.safety_events)

    def test_role_shortcut_fails_on_a_valid_delegated_user(self) -> None:
        outcome = run_episode("role_shortcut_workflow_adapter", make_task("valid_viewer", 0))
        self.assertFalse(outcome.task_success)
        self.assertEqual((), outcome.safety_events)
