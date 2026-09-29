from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from evoaudit_mr.llm.client import Completion
from evoaudit_mr.llm.qwen_track_v4_protocol import source_hashes
from evoaudit_mr.runners.qwen_track_v4 import prepare_a3, run_a1, run_a3, run_freeze, run_offline, run_online


class FakeV4QwenClient:
    def complete(self, messages):
        user = json.loads(messages[-1]["content"])
        environment, parent = user["environment"], user["parent_policy"]
        if environment == "AliasTool":
            if parent["tool_selector"] != "declared_interface":
                delta = [{"field": "tool_selector", "value": "declared_interface"}]
            elif parent["parameter_binding"] != "declared_parameter":
                delta = [{"field": "parameter_binding", "value": "declared_parameter"}]
            else:
                delta = [{"field": "answer_selector", "value": "declared_availability_field"}]
        elif parent["execution_timing"] == "deny_all":
            delta = [{"field": "execution_timing", "value": "after_required_checks"}]
        elif parent["authorization_check"] != "explicit_authorization":
            delta = [{"field": "authorization_check", "value": "explicit_authorization"}]
        elif parent["tenant_check"] != "required":
            delta = [{"field": "tenant_check", "value": "required"}]
        elif parent["confirmation_check"] != "irreversible_only":
            delta = [{"field": "confirmation_check", "value": "irreversible_only"}]
        else:
            delta = [{"field": "audit_logging", "value": "required"}]
        content = json.dumps(
            {
                "claimed_target": "Repair the visible public policy mismatch.",
                "policy_delta": delta,
                "natural_language_instruction": "Apply exactly the public typed assignment.",
                "rationale": "The visible traces identify the current policy mismatch.",
                "evidence_trace_ids": [trace["trace_id"] for trace in user["visible_traces"]],
            }
        )
        return Completion(content, "fake-qwen-v4", {"total_tokens": 24}, {"model": "fake-qwen-v4", "usage": {"total_tokens": 24}})


class QwenTrackV4RunnerTests(unittest.TestCase):
    def test_full_mock_v4_protocol_writes_80_slot_phase_lock_and_final_seal(self) -> None:
        root = Path(__file__).resolve().parents[1]
        manifest = json.loads((root / "configs" / "qwen_track_v4_manifest_draft.json").read_text(encoding="utf-8"))
        manifest["source_hashes"] = source_hashes(root)
        with tempfile.TemporaryDirectory() as directory:
            manifest_path = Path(directory) / "manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            output, fake = Path(directory) / "out", FakeV4QwenClient()
            run_a1(manifest_path, root / "configs" / "qwen_track_v4_model.json", output)
            prepare_a3(manifest_path, root / "configs" / "qwen_track_v4_model.json", root / "configs" / "qwen_track_v4_offline.json", output)
            a3 = json.loads(run_a3(manifest_path, root / "configs" / "qwen_track_v4_model.json", output, client=fake).read_text(encoding="utf-8"))
            self.assertTrue(a3["passed"])
            run_freeze(manifest_path, root / "configs" / "qwen_track_v4_model.json", output)
            run_online(manifest_path, root / "configs" / "qwen_track_v4_model.json", output, client=fake)
            lock = json.loads((output / "ONLINE_PHASE_LOCK.json").read_text(encoding="utf-8"))
            self.assertEqual((80, 320, 80), (lock["logical_slots"], lock["dynamic_decisions"], lock["static_measurements"]))
            run_offline(manifest_path, root / "configs" / "qwen_track_v4_offline.json", output)
            self.assertTrue((output / "QWEN_TRACK_V4_SEAL.json").exists())
            status = json.loads((output / "reports" / "final_analysis_status.json").read_text(encoding="utf-8"))
            self.assertEqual(10, status["trajectory_clusters"])
            self.assertEqual(50, status["terminal_method_records"])


if __name__ == "__main__":
    unittest.main()
