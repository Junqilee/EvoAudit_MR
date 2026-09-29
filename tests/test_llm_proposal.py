from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from urllib.request import Request

from evoaudit_mr.llm.client import OpenAICompatibleClient
from evoaudit_mr.llm.compiler import compile_proposed_patch
from evoaudit_mr.llm.config import LLMConfigError, LLMProposalConfig
from evoaudit_mr.llm.freeze import freeze_model
from evoaudit_mr.llm.proposal import ProposalValidationError, parse_proposed_patch


def config() -> LLMProposalConfig:
    return LLMProposalConfig.from_mapping(
        {
            "config_version": "llm-proposal-config-v2",
            "run_id": "test",
            "provider": "qwen",
            "api_protocol": "chat_completions",
            "base_url": "https://example.test/v1",
            "api_key_env": "EVOAUDIT_TEST_API_KEY",
            "model": "example-model",
            "temperature": 0.0,
            "top_p": 1.0,
            "max_tokens": 256,
            "timeout_seconds": 10,
            "response_format": "json_object",
            "proposal_schema_version": "llm-patch-dsl-v1",
            "proposals_per_context": 1,
            "invalid_policy": "record_and_continue_without_retry",
        }
    )


def valid_payload() -> dict[str, object]:
    return {
        "patch_type": "tool_adapter",
        "claimed_target": "read the declared stock field",
        "claimed_scope": ["tool_adapter"],
        "operations": [{"component": "tool_adapter", "action": "add", "content": "Map the declared stock alias to availability."}],
        "rationale": "The visible trace shows an alias mismatch.",
        "evidence_trace_ids": ["preflight-trace-001"],
    }


class LLMProposalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.previous_key = os.environ.get("EVOAUDIT_TEST_API_KEY")
        os.environ["EVOAUDIT_TEST_API_KEY"] = "test-secret-not-written"

    def tearDown(self) -> None:
        if self.previous_key is None:
            os.environ.pop("EVOAUDIT_TEST_API_KEY", None)
        else:
            os.environ["EVOAUDIT_TEST_API_KEY"] = self.previous_key

    def test_config_rejects_embedded_api_key(self) -> None:
        raw = config().to_dict() | {"api_key": "not-allowed"}
        with self.assertRaises(LLMConfigError):
            LLMProposalConfig.from_mapping(raw)

    def test_client_uses_openai_compatible_payload_without_leaking_key(self) -> None:
        captured: dict[str, object] = {}

        def transport(request: Request, timeout: float):
            captured["url"] = request.full_url
            captured["body"] = json.loads(request.data.decode("utf-8"))
            captured["auth"] = request.headers["Authorization"]
            captured["timeout"] = timeout
            return {"model": "example-model-2026", "usage": {"total_tokens": 12}, "choices": [{"message": {"content": json.dumps(valid_payload())}}]}

        response = OpenAICompatibleClient(config(), transport=transport).complete([{"role": "user", "content": "test"}])
        self.assertEqual("https://example.test/v1/chat/completions", captured["url"])
        self.assertEqual("json_object", captured["body"]["response_format"]["type"])
        self.assertEqual("Bearer test-secret-not-written", captured["auth"])
        self.assertEqual("example-model-2026", response.model)

    def test_responses_api_uses_input_and_extracts_output_text(self) -> None:
        captured: dict[str, object] = {}

        def transport(request: Request, timeout: float):
            del timeout
            captured["url"] = request.full_url
            captured["body"] = json.loads(request.data.decode("utf-8"))
            return {
                "model": "qwen3.7-plus",
                "usage": {"total_tokens": 17},
                "output": [
                    {"type": "reasoning", "summary": []},
                    {"type": "message", "content": [{"type": "output_text", "text": json.dumps(valid_payload())}]},
                ],
            }

        responses_config = LLMProposalConfig.from_mapping(config().to_dict() | {"api_protocol": "responses"})
        response = OpenAICompatibleClient(responses_config, transport=transport).complete([{"role": "user", "content": "Return JSON."}])
        self.assertEqual("https://example.test/v1/responses", captured["url"])
        self.assertIn("input", captured["body"])
        self.assertNotIn("response_format", captured["body"])
        self.assertEqual(256, captured["body"]["max_output_tokens"])
        self.assertFalse(captured["body"]["store"])
        self.assertEqual(json.dumps(valid_payload()), response.content)

    def test_parser_fails_closed_on_non_visible_evidence(self) -> None:
        invalid = valid_payload() | {"evidence_trace_ids": ["not-visible"]}
        with self.assertRaises(ProposalValidationError):
            parse_proposed_patch(invalid, allowed_evidence_ids=("preflight-trace-001",))

    def test_compiler_uses_operation_content_not_a_model_chosen_adapter(self) -> None:
        proposal = parse_proposed_patch(valid_payload(), allowed_evidence_ids=("preflight-trace-001",))
        patch = compile_proposed_patch(
            proposal,
            environment="AliasTool",
            patch_id="llm-test-001",
            parent_adapter="broken_adapter",
        )
        self.assertEqual("llm_semantic_adapter", patch.candidate_adapter)
        self.assertEqual("semantic", patch.diff["actual_diff_features"]["compiled_intent"])

    def test_freeze_writes_hashes_not_a_key_or_raw_content(self) -> None:
        def transport(request: Request, timeout: float):
            del request, timeout
            return {"model": "example-model-2026", "usage": {"total_tokens": 12}, "choices": [{"message": {"content": json.dumps(valid_payload())}}]}

        class TestClient(OpenAICompatibleClient):
            def __init__(self, config: LLMProposalConfig):
                super().__init__(config, transport=transport)

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "LLM_FREEZE.json"
            freeze_model(config(), output_path=output, client_factory=TestClient)
            text = output.read_text(encoding="utf-8")
            self.assertIn("proposal_sha256", text)
            self.assertIn("compiled_patch_sha256", text)
            self.assertNotIn("test-secret-not-written", text)
            self.assertNotIn("Map the declared stock alias", text)
            with self.assertRaises(FileExistsError):
                freeze_model(config(), output_path=output, client_factory=TestClient)


if __name__ == "__main__":
    unittest.main()
