from __future__ import annotations

import unittest
from dataclasses import replace

from evoaudit_mr.audits.router import UnsupportedScopeError, route_probes
from evoaudit_mr.patches import PatchCatalogue


class RouterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.events = PatchCatalogue("configs/prototype_candidates.json").events(evolve_tasks=8, heldout_tasks=6)

    def test_router_has_two_probes_per_bucket(self) -> None:
        event = self.events[0]
        suite = route_probes(event.patch, environment="AliasTool", budget_pairs=6, seed=0)
        self.assertEqual(6, len(suite.probes))
        self.assertEqual(2, len(suite.bucket("target")))
        self.assertEqual(2, len(suite.bucket("replay")))
        self.assertEqual(2, len(suite.bucket("safety")))
        self.assertEqual({"tool_alias", "field_rename_and_reorder"}, {probe.mr_id for probe in suite.bucket("target")})

    def test_unsupported_patch_type_is_rejected(self) -> None:
        patch = self.events[0].patch
        unsupported = type(patch)(
            patch_id=patch.patch_id,
            patch_type="workflow",
            claimed_target=patch.claimed_target,
            claimed_scope=patch.claimed_scope,
            diff=patch.diff,
            candidate_adapter=patch.candidate_adapter,
        )
        with self.assertRaises(UnsupportedScopeError):
            route_probes(unsupported, environment="AliasTool", budget_pairs=6, seed=0)

    def test_patch_id_does_not_change_probe_semantics(self) -> None:
        patch = self.events[2].patch
        renamed = replace(patch, patch_id="arbitrary-renamed-id")
        original = route_probes(patch, environment="AliasTool", budget_pairs=6, seed=0)
        changed = route_probes(renamed, environment="AliasTool", budget_pairs=6, seed=0)
        original_semantics = [(p.bucket, p.mr_id, p.task.profile) for p in original.probes]
        changed_semantics = [(p.bucket, p.mr_id, p.task.profile) for p in changed.probes]
        self.assertEqual(original_semantics, changed_semantics)
