"""Public, reproducible configuration for an API-backed proposal model."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse


CONFIG_VERSION = "llm-proposal-config-v2"
SUPPORTED_PROVIDERS = frozenset({"qwen", "deepseek"})
SUPPORTED_API_PROTOCOLS = frozenset({"chat_completions", "responses"})


class LLMConfigError(ValueError):
    """A public proposal-model configuration is malformed or unsafe."""


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(dict(value), sort_keys=True, ensure_ascii=True, separators=(",", ":"))


@dataclass(frozen=True)
class LLMProposalConfig:
    """All model-call settings except the secret API key itself.

    The source config is intended to be included with experiment artifacts.  A
    key is referred to only by its environment-variable name and is never a
    field of this dataclass or a generated freeze record.
    """

    config_version: str
    run_id: str
    provider: str
    api_protocol: str
    base_url: str
    api_key_env: str
    model: str
    temperature: float
    top_p: float
    max_tokens: int
    timeout_seconds: int
    response_format: str
    proposal_schema_version: str
    proposals_per_context: int
    invalid_policy: str

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "LLMProposalConfig":
        if "api_key" in raw or "key" in raw:
            raise LLMConfigError("API keys must never be stored in a public LLM config.")
        expected = {
            "config_version",
            "run_id",
            "provider",
            "api_protocol",
            "base_url",
            "api_key_env",
            "model",
            "temperature",
            "top_p",
            "max_tokens",
            "timeout_seconds",
            "response_format",
            "proposal_schema_version",
            "proposals_per_context",
            "invalid_policy",
        }
        missing, unknown = expected - set(raw), set(raw) - expected
        if missing or unknown:
            raise LLMConfigError(f"Config keys must match the v1 schema; missing={sorted(missing)}, unknown={sorted(unknown)}.")
        config = cls(
            config_version=str(raw["config_version"]),
            run_id=str(raw["run_id"]),
            provider=str(raw["provider"]),
            api_protocol=str(raw["api_protocol"]),
            base_url=str(raw["base_url"]).rstrip("/"),
            api_key_env=str(raw["api_key_env"]),
            model=str(raw["model"]),
            temperature=float(raw["temperature"]),
            top_p=float(raw["top_p"]),
            max_tokens=int(raw["max_tokens"]),
            timeout_seconds=int(raw["timeout_seconds"]),
            response_format=str(raw["response_format"]),
            proposal_schema_version=str(raw["proposal_schema_version"]),
            proposals_per_context=int(raw["proposals_per_context"]),
            invalid_policy=str(raw["invalid_policy"]),
        )
        config.validate()
        return config

    def validate(self) -> None:
        if self.config_version != CONFIG_VERSION:
            raise LLMConfigError(f"Expected {CONFIG_VERSION!r}, got {self.config_version!r}.")
        if self.provider not in SUPPORTED_PROVIDERS:
            raise LLMConfigError(f"Unsupported provider {self.provider!r}.")
        if self.api_protocol not in SUPPORTED_API_PROTOCOLS:
            raise LLMConfigError(f"Unsupported api_protocol {self.api_protocol!r}.")
        parsed = urlparse(self.base_url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise LLMConfigError("base_url must be an HTTPS endpoint.")
        if not self.api_key_env or not self.api_key_env.replace("_", "").isalnum():
            raise LLMConfigError("api_key_env must be an environment-variable identifier.")
        if not self.model or self.max_tokens < 64 or self.timeout_seconds < 5:
            raise LLMConfigError("model, max_tokens, and timeout_seconds are invalid.")
        if not 0.0 <= self.temperature <= 2.0 or not 0.0 < self.top_p <= 1.0:
            raise LLMConfigError("temperature or top_p are outside supported bounds.")
        if self.response_format != "json_object":
            raise LLMConfigError("v1 requires response_format='json_object'.")
        if self.proposal_schema_version not in {"llm-patch-dsl-v1", "typed-policy-ir-v3b"}:
            raise LLMConfigError("Unsupported proposal schema version.")
        if self.proposals_per_context != 1:
            raise LLMConfigError("One proposal per context is required: retries are not permitted.")
        if self.invalid_policy != "record_and_continue_without_retry":
            raise LLMConfigError("Invalid proposals must be recorded without retry.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "config_version": self.config_version,
            "run_id": self.run_id,
            "provider": self.provider,
            "api_protocol": self.api_protocol,
            "base_url": self.base_url,
            "api_key_env": self.api_key_env,
            "model": self.model,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "max_tokens": self.max_tokens,
            "timeout_seconds": self.timeout_seconds,
            "response_format": self.response_format,
            "proposal_schema_version": self.proposal_schema_version,
            "proposals_per_context": self.proposals_per_context,
            "invalid_policy": self.invalid_policy,
        }

    @property
    def fingerprint(self) -> str:
        return sha256(_canonical_json(self.to_dict()).encode("utf-8")).hexdigest()


def load_config(path: str | Path) -> LLMProposalConfig:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, Mapping):
        raise LLMConfigError("LLM config must be a JSON object.")
    return LLMProposalConfig.from_mapping(data)
