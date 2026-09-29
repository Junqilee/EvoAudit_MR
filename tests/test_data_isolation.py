from __future__ import annotations

import unittest

from evoaudit_mr.patches import PatchCatalogue


class DataIsolationTests(unittest.TestCase):
    def test_evolve_and_heldout_share_distribution_but_not_instances(self) -> None:
        profiles = ("canonical", "alias", "reordered", "alias_reordered")
        event = PatchCatalogue("configs/prototype_candidates.json", seed=0).events(
            evolve_tasks=8,
            heldout_tasks=8,
            base_profiles=profiles,
            evolve_seed=11,
            heldout_seed=29,
        )[0]
        self.assertEqual(set(profiles), {task.profile for task in event.visible_tasks})
        self.assertEqual(set(profiles), {task.profile for task in event.heldout_tasks})
        self.assertTrue(
            {task.task_id for task in event.visible_tasks}.isdisjoint(
                {task.task_id for task in event.heldout_tasks}
            )
        )
        self.assertNotEqual(
            [task.sku for task in event.visible_tasks],
            [task.sku for task in event.heldout_tasks],
        )
