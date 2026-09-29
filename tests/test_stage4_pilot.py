from __future__ import annotations

import csv
from pathlib import Path
import tempfile
import unittest

from evoaudit_mr.pilot import build_pilot_events
from evoaudit_mr.runners.stage4_pilot import run


class Stage4PilotTests(unittest.TestCase):
    def test_catalogue_has_balanced_candidate_events_and_disjoint_splits(self) -> None:
        events = build_pilot_events(
            repetitions=3,
            evolve_tasks=12,
            heldout_tasks=6,
            evolve_seed=101,
            heldout_seed=211,
        )
        self.assertEqual(36, len(events))
        self.assertEqual(12, sum(event.environment == "AliasTool" for event in events))
        self.assertEqual(12, sum(event.environment == "SwitchRule" for event in events))
        self.assertEqual(12, sum(event.environment == "PermissionPath" for event in events))
        for event in events:
            self.assertTrue(
                {task.task_id for task in event.visible_tasks}.isdisjoint(
                    {task.task_id for task in event.heldout_tasks}
                )
            )

    def test_pilot_reports_the_preregistered_selection_metrics(self) -> None:
        root = Path(__file__).resolve().parents[1]
        manifest = root / "configs" / "stage4_pilot_manifest.json"
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "pilot"
            run(manifest, output)
            with (output / "main_results.csv").open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            overall = {row["method"]: row for row in rows if row["environment"] == "Overall"}
            self.assertEqual("0.750", overall["fixed_heldout"]["far"])
            self.assertEqual("1.000", overall["fixed_heldout"]["uur"])
            self.assertEqual("0.000", overall["evoaudit_mr"]["far"])
            self.assertEqual("1.000", overall["evoaudit_mr"]["uur"])
            self.assertEqual("0.0", overall["direct_commit"]["mean_audit_tool_calls"])
            permission = {row["method"]: row for row in rows if row["environment"] == "PermissionPath"}
            self.assertEqual("0.000", permission["evoaudit_mr"]["far"])
            self.assertEqual("1.000", permission["evoaudit_mr"]["uur"])
            self.assertIn("SwitchRule", (output / "pilot_cases.md").read_text(encoding="utf-8"))
            self.assertIn("PermissionPath", (output / "pilot_cases.md").read_text(encoding="utf-8"))
