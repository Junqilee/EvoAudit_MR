from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from evoaudit_mr.llm.ollama import OllamaCompletion, OllamaModelInfo
from evoaudit_mr.llm.ollama_pilot_protocol import source_hashes
from evoaudit_mr.runners.ollama_pilot import run_freeze, run_offline, run_online


class FakeOllamaClient:
    def __init__(self) -> None:
        self.calls = 0

    def model_info(self, model: str) -> OllamaModelInfo:
        return OllamaModelInfo(
            endpoint="http://127.0.0.1:11434",
            ollama_version="test-ollama-1",
            model=model,
            digest="test-digest-qwen25-7b",
            size_bytes=1,
            modified_at="2026-08-13T00:00:00Z",
        )

    def complete(self, messages, *, model, temperature, top_p, seed, num_predict, timeout_seconds) -> OllamaCompletion:
        del model, temperature, top_p, seed, num_predict, timeout_seconds
        self.calls += 1
        user_payload = json.loads(messages[-1]["content"])
        environment = user_payload["environment"]
        if environment == "AliasTool":
            payload = {
                "patch_type": "tool_adapter",
                "claimed_target": "read the declared stock field",
                "claimed_scope": ["tool_adapter"],
                "operations": [{"component": "tool_adapter", "action": "replace", "content": "Use the declared tool and its declared availability field; do not read protected fields."}],
                "rationale": "The visible trace uses a declared schema alias.",
                "evidence_trace_ids": [trace["trace_id"] for trace in user_payload["visible_traces"]],
            }
        else:
            payload = {
                "patch_type": "workflow",
                "claimed_target": "preserve the authorization chain",
                "claimed_scope": ["workflow"],
                "operations": [{"component": "workflow", "action": "replace", "content": "Authorize, confirm irreversible actions, execute only when permitted, and log execution."}],
                "rationale": "The visible trace requires an authorized workflow.",
                "evidence_trace_ids": [trace["trace_id"] for trace in user_payload["visible_traces"]],
            }
        return OllamaCompletion(
            content=json.dumps(payload),
            model="qwen2.5:7b",
            usage={"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
            latency_seconds=0.01,
            raw_response={},
        )


class OllamaPilotTests(unittest.TestCase):
    def _manifest(self) -> dict[str, object]:
        root = Path(__file__).resolve().parents[1]
        manifest = json.loads((root / "configs" / "ollama_pilot_v2_manifest.json").read_text(encoding="utf-8"))
        manifest["online_source_hashes"] = source_hashes(root)
        return manifest

    def test_full_mock_protocol_has_expected_units_and_phase_lock(self) -> None:
        root = Path(__file__).resolve().parents[1]
        offline = root / "configs" / "ollama_pilot_v2_offline.json"
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            manifest_path = temp / "manifest.json"
            manifest_path.write_text(json.dumps(self._manifest(), indent=2), encoding="utf-8")
            output = temp / "artifacts"
            client = FakeOllamaClient()
            run_freeze(manifest_path, output, client=client)
            run_online(manifest_path, output, client=client)
            marker = json.loads((output / "ONLINE_COMPLETE.json").read_text(encoding="utf-8"))
            self.assertEqual(30, marker["candidate_slots"])
            self.assertEqual(120, marker["dynamic_decisions"])
            self.assertEqual(30, marker["static_measurements"])
            self.assertEqual(31, client.calls)  # one freeze call + one proposal per slot
            self.assertEqual(30, len((output / "candidate_ledger" / "candidate_ledger_online.jsonl").read_text(encoding="utf-8").splitlines()))
            self.assertEqual(120, len((output / "candidate_level" / "decisions.jsonl").read_text(encoding="utf-8").splitlines()))
            dynamic_records = sum(
                len(path.read_text(encoding="utf-8").splitlines())
                for method in ("direct_commit", "rsea_fixed_validation", "fixed_random_audit", "evoaudit_mr")
                for path in (output / "trajectories" / method).glob("*.jsonl")
            )
            self.assertEqual(120, dynamic_records)
            run_offline(manifest_path, offline, output)
            self.assertTrue((output / "reports" / "pilot_report.md").exists())
            self.assertEqual(120, len((output / "offline_hidden" / "trajectory_labels.jsonl").read_text(encoding="utf-8").splitlines()))

    def test_online_rejects_changed_source_after_freeze(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            manifest = self._manifest()
            manifest["online_source_hashes"] = {"unexpected": "hash"}
            manifest_path = temp / "manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(Exception):
                run_freeze(manifest_path, temp / "artifacts", client=FakeOllamaClient())


if __name__ == "__main__":
    unittest.main()
