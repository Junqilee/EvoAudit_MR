from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from evoaudit_mr.llm.config import load_config
from evoaudit_mr.llm.client import Completion
from evoaudit_mr.llm.qwen_track_v1_protocol import source_hashes
from evoaudit_mr.runners.qwen_track_v1 import prepare_a2, run_a1, run_a2, run_freeze, run_offline, run_online, scenario_rows, visible_tasks


class FakeQwenClient:
    def complete(self, messages):
        user = json.loads(messages[-1]["content"]); environment = user["environment"]
        delta = ([{"field": "tool_selector", "value": "declared_interface"}, {"field": "parameter_binding", "value": "declared_parameter"}, {"field": "answer_selector", "value": "declared_availability_field"}]
                 if environment == "AliasTool" else [{"field": "execution_timing", "value": "after_required_checks"}])
        content = json.dumps({"claimed_target": "Repair the visible public contract.", "policy_delta": delta, "natural_language_instruction": "Apply the listed public assignments.", "rationale": "Visible traces provide the facts.", "evidence_trace_ids": [item["trace_id"] for item in user["visible_traces"]]})
        return Completion(content, "fake-qwen", {"total_tokens": 20}, {"model": "fake-qwen", "usage": {"total_tokens": 20}})


class QwenTrackPreApiTests(unittest.TestCase):
    def test_counterbalanced_schedule_has_60_slots_and_new_public_family(self) -> None:
        root = Path(__file__).resolve().parents[1]
        manifest = json.loads((root / "configs" / "qwen_track_v1_manifest.json").read_text(encoding="utf-8"))
        rows = scenario_rows(manifest)
        self.assertEqual(60, len(rows))
        self.assertEqual(5, sum(row["family_id"] == "F" and row["environment"] == "AliasTool" for row in rows))
        public_tasks = visible_tasks(next(row for row in rows if row["environment"] == "AliasTool" and row["family_id"] == "F"), count=2)
        self.assertTrue(all(len(task.declared_tools) == 3 and "raw_inventory" not in task.declared_tools for task in public_tasks))

    def test_a1_uses_typed_policy_config_and_writes_no_api_artifact(self) -> None:
        root = Path(__file__).resolve().parents[1]
        manifest = json.loads((root / "configs" / "qwen_track_v1_manifest.json").read_text(encoding="utf-8"))
        manifest["source_hashes"] = source_hashes(root)
        with tempfile.TemporaryDirectory() as directory:
            manifest_path = Path(directory) / "manifest.json"; manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            output = Path(directory) / "out"
            result = run_a1(manifest_path, root / "configs" / "qwen_track_v1_model.json", output)
            seal = json.loads(result.read_text(encoding="utf-8"))
            self.assertEqual("A1", seal["gate"])
            self.assertFalse((output / "api_attempts.jsonl").exists())
            self.assertEqual(60, seal["readiness"]["counterbalanced_family_readiness"]["schedule_slots"])

    def test_a2_uses_six_one_shot_logical_cases_after_a1(self) -> None:
        root = Path(__file__).resolve().parents[1]
        manifest = json.loads((root / "configs" / "qwen_track_v1_manifest.json").read_text(encoding="utf-8")); manifest["source_hashes"] = source_hashes(root)
        with tempfile.TemporaryDirectory() as directory:
            path, output = Path(directory) / "manifest.json", Path(directory) / "out"; path.write_text(json.dumps(manifest), encoding="utf-8")
            run_a1(path, root / "configs" / "qwen_track_v1_model.json", output)
            prepare_a2(path, root / "configs" / "qwen_track_v1_model.json", root / "configs" / "qwen_track_v1_offline.json", output)
            report = json.loads(run_a2(path, root / "configs" / "qwen_track_v1_model.json", output, client=FakeQwenClient()).read_text(encoding="utf-8"))
            self.assertTrue(report["passed"])
            self.assertEqual(6, len((output / "api_attempts.jsonl").read_text(encoding="utf-8").splitlines()))

    def test_full_mock_protocol_preserves_qwen_track_units(self) -> None:
        root = Path(__file__).resolve().parents[1]
        manifest = json.loads((root / "configs" / "qwen_track_v1_manifest.json").read_text(encoding="utf-8")); manifest["source_hashes"] = source_hashes(root)
        with tempfile.TemporaryDirectory() as directory:
            path, output = Path(directory) / "manifest.json", Path(directory) / "out"; path.write_text(json.dumps(manifest), encoding="utf-8")
            fake = FakeQwenClient(); run_a1(path, root / "configs" / "qwen_track_v1_model.json", output); prepare_a2(path, root / "configs" / "qwen_track_v1_model.json", root / "configs" / "qwen_track_v1_offline.json", output); run_a2(path, root / "configs" / "qwen_track_v1_model.json", output, client=fake); run_freeze(path, root / "configs" / "qwen_track_v1_model.json", output); run_online(path, root / "configs" / "qwen_track_v1_model.json", output, client=fake)
            lock = json.loads((output / "ONLINE_PHASE_LOCK.json").read_text(encoding="utf-8")); self.assertEqual((60, 240, 60), (lock["logical_slots"], lock["dynamic_decisions"], lock["static_measurements"]))
            run_offline(path, root / "configs" / "qwen_track_v1_offline.json", output); self.assertTrue((output / "QWEN_TRACK_V1_SEAL.json").exists())

    def test_model_config_uses_v3b_typed_ir(self) -> None:
        root = Path(__file__).resolve().parents[1]
        self.assertEqual("typed-policy-ir-v3b", load_config(root / "configs" / "qwen_track_v1_model.json").proposal_schema_version)


if __name__ == "__main__": unittest.main()
