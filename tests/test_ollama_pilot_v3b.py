from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from evoaudit_mr.llm.ollama import OllamaModelInfo
from evoaudit_mr.llm.ollama_native import NativeOllamaCompletion
from evoaudit_mr.llm.ollama_pilot_v3b_protocol import source_hashes
from evoaudit_mr.llm.v3_ir import V3IRValidationError
from evoaudit_mr.llm.v3b_ir import parse_v3b_proposed_patch
from evoaudit_mr.runners.ollama_pilot_v3b import prepare_a2, run_a2, run_freeze, run_offline, run_online, run_readiness


class FakeNativeOllama:
    def __init__(self) -> None: self.calls = 0

    def model_info(self, model: str) -> OllamaModelInfo:
        return OllamaModelInfo("http://127.0.0.1:11434", "test-native-ollama", model, "test-v3b-digest", 1, "2026-08-14T00:00:00Z")

    def complete(self, messages, *, schema, model, temperature, top_p, seed, num_predict, timeout_seconds) -> NativeOllamaCompletion:
        del schema, model, temperature, top_p, seed, num_predict, timeout_seconds
        self.calls += 1
        user = json.loads(messages[-1]["content"])
        environment = user["environment"]
        if environment == "AliasTool":
            delta = [{"field": "tool_selector", "value": "declared_interface"}, {"field": "parameter_binding", "value": "declared_parameter"}, {"field": "answer_selector", "value": "declared_availability_field"}]
        else:
            delta = [{"field": "execution_timing", "value": "after_required_checks"}]
        payload = {"claimed_target": "Repair the visible public contract.", "policy_delta": delta,
                   "natural_language_instruction": "Apply the listed public assignments.", "rationale": "The visible trace supports this change.",
                   "evidence_trace_ids": [trace["trace_id"] for trace in user["visible_traces"]]}
        content = json.dumps(payload)
        return NativeOllamaCompletion(content, "qwen2.5:7b", {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20}, 0.01, {"message": {"content": content}})


class OllamaPilotV3BTests(unittest.TestCase):
    def test_model_cannot_supply_system_owned_scope(self) -> None:
        payload = {"claimed_target": "fix", "policy_delta": [{"field": "tool_selector", "value": "declared_interface"}], "natural_language_instruction": "fix", "rationale": "visible", "evidence_trace_ids": ["trace"], "claimed_scope": ["tool_adapter"]}
        with self.assertRaises(V3IRValidationError):
            parse_v3b_proposed_patch(payload, environment="AliasTool", allowed_evidence_ids=("trace",))

    def test_full_mock_protocol_runs_a1_a2_then_30_shared_slots(self) -> None:
        root = Path(__file__).resolve().parents[1]
        manifest = json.loads((root / "configs" / "ollama_pilot_v3b_manifest.json").read_text(encoding="utf-8"))
        manifest["online_source_hashes"] = source_hashes(root)
        with tempfile.TemporaryDirectory() as directory:
            tmp, output = Path(directory), Path(directory) / "artifacts"
            manifest_path = tmp / "manifest.json"; manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            client = FakeNativeOllama()
            run_readiness(output)
            prepare_a2(manifest_path, output, client=client)
            a2 = json.loads(run_a2(manifest_path, output, client=client).read_text(encoding="utf-8"))
            self.assertTrue(a2["passed"])
            run_freeze(manifest_path, root / "configs" / "ollama_pilot_v3b_offline.json", output)
            run_online(manifest_path, output, client=client)
            lock = json.loads((output / "ONLINE_PHASE_LOCK.json").read_text(encoding="utf-8"))
            self.assertEqual((30, 120, 30), (lock["candidate_slots"], lock["dynamic_decisions"], lock["static_measurements"]))
            self.assertEqual(36, client.calls)
            self.assertEqual(30, len((output / "candidate_ledger_online.jsonl").read_text(encoding="utf-8").splitlines()))
            run_offline(manifest_path, root / "configs" / "ollama_pilot_v3b_offline.json", output)
            self.assertTrue((output / "PILOT_V3B_SEAL.json").exists())


if __name__ == "__main__": unittest.main()
