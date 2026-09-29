from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from evoaudit_mr.llm.ollama import OllamaCompletion, OllamaModelInfo
from evoaudit_mr.llm.ollama_pilot_v3_protocol import source_hashes
from evoaudit_mr.llm.v3_compiler import materialize_v3_patch
from evoaudit_mr.llm.v3_ir import V3IRValidationError, initial_typed_policy, parse_v3_proposed_patch
from evoaudit_mr.runners.ollama_pilot_v3 import run_freeze, run_offline, run_online, run_readiness
from evoaudit_mr.types import Harness


class FakeV3OllamaClient:
    def __init__(self) -> None:
        self.calls = 0

    def model_info(self, model: str) -> OllamaModelInfo:
        return OllamaModelInfo("http://127.0.0.1:11434", "test-ollama-v3", model, "test-v3-digest", 1, "2026-08-14T00:00:00Z")

    def complete(self, messages, *, model, temperature, top_p, seed, num_predict, timeout_seconds) -> OllamaCompletion:
        del model, temperature, top_p, seed, num_predict, timeout_seconds
        self.calls += 1
        user = json.loads(messages[-1]["content"])
        environment = user["environment"]
        if environment == "AliasTool":
            delta = [
                {"field": "tool_selector", "value": "declared_interface"},
                {"field": "parameter_binding", "value": "declared_parameter"},
                {"field": "answer_selector", "value": "declared_availability_field"},
            ]
            patch_type = "tool_adapter"
        else:
            delta = [{"field": "execution_timing", "value": "after_required_checks"}]
            patch_type = "workflow"
        payload = {
            "patch_type": patch_type,
            "claimed_target": "Repair the visible contract mismatch.",
            "claimed_scope": [patch_type],
            "policy_delta": delta,
            "natural_language_instruction": "Apply the listed public policy assignments.",
            "rationale": "The visible traces identify the required public checks.",
            "evidence_trace_ids": [item["trace_id"] for item in user["visible_traces"]],
        }
        return OllamaCompletion(json.dumps(payload), "qwen2.5:7b", {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20}, 0.01, {})


class OllamaPilotV3Tests(unittest.TestCase):
    def test_typed_ir_rejects_duplicate_assignment(self) -> None:
        payload = {
            "patch_type": "tool_adapter",
            "claimed_target": "Repair the declared interface.",
            "claimed_scope": ["tool_adapter"],
            "policy_delta": [
                {"field": "tool_selector", "value": "declared_interface"},
                {"field": "tool_selector", "value": "fixed_lookup_inventory"},
            ],
            "natural_language_instruction": "Use the public interface.",
            "rationale": "The visible trace declares it.",
            "evidence_trace_ids": ["visible-1"],
        }
        with self.assertRaises(V3IRValidationError):
            parse_v3_proposed_patch(payload, environment="AliasTool", allowed_evidence_ids=("visible-1",))

    def test_typed_policy_is_parent_compositional(self) -> None:
        proposal = parse_v3_proposed_patch(
            {
                "patch_type": "workflow",
                "claimed_target": "Complete a visible authorized request.",
                "claimed_scope": ["workflow"],
                "policy_delta": [{"field": "execution_timing", "value": "after_required_checks"}],
                "natural_language_instruction": "Enable execution after the configured checks.",
                "rationale": "The visible request has the necessary public facts.",
                "evidence_trace_ids": ["visible-1"],
            },
            environment="PermissionPath",
            allowed_evidence_ids=("visible-1",),
        )
        parent = Harness(adapter_name="typed_permissionpath_policy", typed_policy=initial_typed_policy("PermissionPath"))
        patch = materialize_v3_patch(proposal, environment="PermissionPath", patch_id="test-v3", parent=parent)
        self.assertEqual("deny_all", patch.diff["typed_policy_before"]["execution_timing"])
        self.assertEqual("after_required_checks", patch.diff["typed_policy_after"]["execution_timing"])

    def test_full_mock_protocol_preserves_v3_units(self) -> None:
        root = Path(__file__).resolve().parents[1]
        manifest = json.loads((root / "configs" / "ollama_pilot_v3_manifest.json").read_text(encoding="utf-8"))
        manifest["online_source_hashes"] = source_hashes(root)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "artifacts"
            manifest_path = Path(directory) / "manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            client = FakeV3OllamaClient()
            run_readiness(output)
            run_freeze(manifest_path, root / "configs" / "ollama_pilot_v3_offline.json", output, client=client)
            run_online(manifest_path, output, client=client)
            lock = json.loads((output / "ONLINE_PHASE_LOCK.json").read_text(encoding="utf-8"))
            self.assertEqual(30, lock["candidate_slots"])
            self.assertEqual(120, lock["dynamic_decisions"])
            self.assertEqual(30, lock["static_measurements"])
            self.assertEqual(31, client.calls)
            self.assertEqual(30, len((output / "candidate_ledger_online.jsonl").read_text(encoding="utf-8").splitlines()))
            self.assertEqual(120, len((output / "online_decisions.jsonl").read_text(encoding="utf-8").splitlines()))
            run_offline(manifest_path, root / "configs" / "ollama_pilot_v3_offline.json", output)
            self.assertTrue((output / "reports" / "pilot_v3_report.md").exists())


if __name__ == "__main__":
    unittest.main()
