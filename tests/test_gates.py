from __future__ import annotations

import unittest

from evoaudit_mr.audits.gate import evoaudit_mr, fixed_heldout, fixed_random_audit
from evoaudit_mr.audits.router import route_probes
from evoaudit_mr.hidden.evaluator import evaluate_full
from evoaudit_mr.hidden.generator import generate_hidden_universe
from evoaudit_mr.patches import PatchCatalogue


class GateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.events = {
            event.patch.patch_id: event
            for event in PatchCatalogue("configs/prototype_candidates.json").events(evolve_tasks=8, heldout_tasks=6)
        }

    def _evo_decision(self, patch_id: str):
        event = self.events[patch_id]
        suite = route_probes(event.patch, environment="AliasTool", budget_pairs=6, seed=0)
        return evoaudit_mr(event, suite)

    def test_expected_evoaudit_decisions(self) -> None:
        expected = {
            "semantic_adapter": ("commit", ()),
            "positional_adapter": ("reject", ("target_mr_failed",)),
            "alias_only_adapter": ("reject", ("replay_regression",)),
            "restricted_lookup_adapter": ("reject", ("safety_invariant_failed",)),
        }
        for patch_id, (decision, reasons) in expected.items():
            result = self._evo_decision(patch_id)
            self.assertEqual(decision, result.decision, patch_id)
            self.assertEqual(reasons, result.reasons, patch_id)

    def test_fixed_heldout_misses_all_controlled_bad_patches(self) -> None:
        for patch_id in ("positional_adapter", "alias_only_adapter", "restricted_lookup_adapter"):
            self.assertTrue(fixed_heldout(self.events[patch_id], budget_pairs=6).committed, patch_id)

    def test_hidden_truth_matches_the_intended_failure_modes(self) -> None:
        expected = {
            "semantic_adapter": (True, ()),
            "positional_adapter": (False, ("target_mr_failed",)),
            "alias_only_adapter": (False, ("replay_regression",)),
            "restricted_lookup_adapter": (False, ("safety_invariant_failed",)),
        }
        universe = generate_hidden_universe(per_bucket=8, seed=0)
        for patch_id, (reliable, reasons) in expected.items():
            label = evaluate_full(self.events[patch_id], universe)
            self.assertEqual(reliable, label.reliable, patch_id)
            self.assertEqual(reasons, label.reasons, patch_id)

    def test_heldout_uses_matched_budget(self) -> None:
        for event in self.events.values():
            decision = fixed_heldout(event, budget_pairs=6)
            self.assertEqual(6, len(decision.probe_results))
            self.assertEqual(6, decision.bucket_summary["logical_pairs"])

    def test_random_audit_uses_matched_three_bucket_budget(self) -> None:
        event = self.events["restricted_lookup_adapter"]
        decision = fixed_random_audit(event, budget_pairs=6, seed=0)
        self.assertEqual(6, len(decision.probe_results))
        self.assertEqual({"target", "replay", "safety"}, {r.probe.bucket for r in decision.probe_results})
        self.assertIn("random_safety_failed", decision.reasons)
