from __future__ import annotations

import json
from pathlib import Path
import unittest

from evoaudit_mr.llm.client import LLMClientError
from evoaudit_mr.llm.qwen_track_v4_protocol import (
    classify_proposal_failure,
    evaluate_gate_a3,
    evaluate_gate_b,
    evaluate_gate_p,
    public_parent,
    public_parent_state_report,
    scenario_rows,
)
from evoaudit_mr.llm.v3_ir import V3IRValidationError


class QwenTrackV4ProtocolTests(unittest.TestCase):
    def manifest(self) -> dict:
        root = Path(__file__).resolve().parents[1]
        return json.loads((root / "configs" / "qwen_track_v4_manifest_draft.json").read_text(encoding="utf-8"))

    def test_schedule_has_80_slots_and_balanced_parent_states(self) -> None:
        manifest = self.manifest()
        rows = scenario_rows(manifest)
        self.assertEqual(80, len(rows))
        report = public_parent_state_report(manifest)
        self.assertEqual(10, report["trajectory_clusters"])
        self.assertTrue(all(value == 5 for value in report["family_counts"].values()))
        self.assertTrue(all(public_parent(manifest, row).typed_policy for row in rows))

    def test_failure_taxonomy_separates_received_content_from_transport(self) -> None:
        self.assertEqual("api_transport_failed", classify_proposal_failure(LLMClientError("HTTP 429")))
        self.assertEqual("schema_invalid", classify_proposal_failure(V3IRValidationError("invalid JSON")))
        self.assertEqual("unexpected_runner_error", classify_proposal_failure(RuntimeError("boom")))

    def test_a3_requires_both_environment_coverage_and_delta_diversity(self) -> None:
        manifest = self.manifest()
        rows = []
        for environment in ("AliasTool", "PermissionPath"):
            for index in range(8):
                rows.append({"environment": environment, "status": "passed", "typed_policy_delta_signature": f"{environment}-{index % 3}"})
        report = evaluate_gate_a3(manifest, rows)
        self.assertTrue(report["passed"])
        rows[-1]["status"] = "schema_invalid"
        rows[-2]["status"] = "schema_invalid"
        rows[-3]["status"] = "schema_invalid"
        rows[-4]["status"] = "schema_invalid"
        self.assertFalse(evaluate_gate_a3(manifest, rows)["passed"])

    def test_b_and_p_require_candidate_mix_and_real_method_divergence(self) -> None:
        manifest = self.manifest()
        ledger, labels, canonical, parents, online = [], [], [], [], []
        slots = []
        for environment in ("AliasTool", "PermissionPath"):
            for index in range(24):
                slot = f"{environment}-{index}"
                slots.append((slot, environment, index))
                reliable = index < 12
                ledger.append({"slot_id": slot, "environment": environment, "trajectory_seed": 300 + (index % 5), "proposal_status": "executable", "typed_policy_delta_signature": f"{environment}-sig-{index % 3}"})
                labels.append({"event_id": f"canonical-{slot}", "slot_id": slot, "environment": environment, "reliable": reliable})
                for method in ("direct_commit", "rsea_fixed_validation", "fixed_random_audit", "evoaudit_mr"):
                    canonical.append({"slot_id": slot, "method": method, "proposal_status": "executable", "eligible": not reliable})
                    committed = reliable or method in {"rsea_fixed_validation", "fixed_random_audit"}
                    parents.append({"event_id": f"persistent-{method}-{slot}", "slot_id": slot, "method": method, "reliable": reliable, "eligible": not reliable, "committed": committed})
                    online.append({"slot_id": slot, "environment": environment, "trajectory_seed": 300 + (index % 5), "method": method, "proposal_status": "executable", "decision": "commit" if committed else "reject"})
        gate_b = evaluate_gate_b(manifest, ledger, labels, canonical, parents)
        self.assertTrue(gate_b["passed"])
        divergent_slots = {f"{environment}-{index}" for environment in ("AliasTool", "PermissionPath") for index in range(3)}
        for row in online:
            if row["method"] == "evoaudit_mr" and row["slot_id"] in divergent_slots:
                row["decision"] = "reject"
        gate_p = evaluate_gate_p(manifest, online)
        self.assertTrue(gate_p["passed"])


if __name__ == "__main__":
    unittest.main()
