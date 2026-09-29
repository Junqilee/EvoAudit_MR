"""Small OpenAI-compatible client implemented with the Python standard library."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from typing import Any, Callable, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from evoaudit_mr.llm.config import LLMProposalConfig


class LLMClientError(RuntimeError):
    """An API request failed without exposing an API key."""


class LLMResponseFormatError(LLMClientError):
    """The provider response is not a valid OpenAI chat-completion payload."""


@dataclass(frozen=True)
class Completion:
    content: str
    model: str
    usage: Mapping[str, Any]
    raw_response: Mapping[str, Any]


Transport = Callable[[Request, float], Mapping[str, Any]]


def read_api_key(env_name: str) -> str:
    key = os.environ.get(env_name, "").strip()
    if not key or key.startswith("<") or key.upper().startswith("FILL_"):
        raise LLMClientError(f"Environment variable {env_name} is unset or still a placeholder.")
    return key


def _default_transport(request: Request, timeout_seconds: float) -> Mapping[str, Any]:
    try:
        with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310 - URL validated in config
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:500]
        raise LLMClientError(f"Provider returned HTTP {exc.code}: {body}") from exc
    except URLError as exc:
        raise LLMClientError(f"Provider connection failed: {exc.reason}") from exc
    except TimeoutError as exc:
        raise LLMClientError("Provider request timed out.") from exc
    if not isinstance(payload, Mapping):
        raise LLMResponseFormatError("Provider returned a non-object JSON payload.")
    return payload


class OpenAICompatibleClient:
    """A deterministic request builder for Qwen and DeepSeek-compatible APIs."""

    def __init__(self, config: LLMProposalConfig, *, transport: Transport = _default_transport) -> None:
        self.config = config
        self._transport = transport

    def request_payload(self, messages: Sequence[Mapping[str, str]]) -> dict[str, Any]:
        """Build the provider-specific body from the same public messages."""
        if self.config.api_protocol == "responses":
            # Qwen Token Plan exposes qwen3.7-plus through Responses API.
            # The provider does not document response_format here, so JSON is
            # requested in the prompt and validated locally by proposal.py.
            #
            # Aliyun's Responses gateway validates `input` strictly: a system
            # prompt must be placed in the top-level `instructions` field, and
            # every message `content` must be a structured input-part array
            # ({"type": "input_text"}) rather than a bare string. Sending a
            # bare string or role:"system" inside `input` returns HTTP 400 with
            # a body-less "Bad Request", which is exactly the failure we saw.
            instructions: str | None = None
            input_items: list[dict[str, Any]] = []
            for message in messages:
                role = str(message.get("role", "user"))
                raw_content = message.get("content", "")
                if isinstance(raw_content, str):
                    content: Any = [{"type": "input_text", "text": raw_content}]
                else:
                    content = raw_content
                if role == "system":
                    if isinstance(raw_content, str):
                        instructions = raw_content
                    continue
                input_items.append({"role": role, "content": content})
            payload: dict[str, Any] = {
                "model": self.config.model,
                "input": input_items,
                "temperature": self.config.temperature,
                "top_p": self.config.top_p,
                "max_output_tokens": self.config.max_tokens,
                "stream": False,
                "store": False,
            }
            if instructions is not None:
                payload["instructions"] = instructions
            return payload
        return {
            "model": self.config.model,
            "messages": [dict(message) for message in messages],
            "temperature": self.config.temperature,
            "top_p": self.config.top_p,
            "max_tokens": self.config.max_tokens,
            "stream": False,
            "response_format": {"type": self.config.response_format},
        }

    def _response_url(self) -> str:
        suffix = "/responses" if self.config.api_protocol == "responses" else "/chat/completions"
        return f"{self.config.base_url}{suffix}"

    @staticmethod
    def _responses_output_text(raw: Mapping[str, Any]) -> str:
        """Extract output_text blocks from an OpenAI Responses-compatible body."""
        output = raw.get("output")
        if not isinstance(output, list):
            raise LLMResponseFormatError("Responses payload lacks an output array.")
        fragments: list[str] = []
        for item in output:
            if not isinstance(item, Mapping) or item.get("type") != "message":
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if isinstance(part, Mapping) and part.get("type") == "output_text" and isinstance(part.get("text"), str):
                    fragments.append(part["text"])
        text = "".join(fragments).strip()
        if not text:
            raise LLMResponseFormatError("Responses payload lacks a non-empty output_text message.")
        return text

    def complete(self, messages: Sequence[Mapping[str, str]]) -> Completion:
        key = read_api_key(self.config.api_key_env)
        payload = self.request_payload(messages)
        request = Request(
            self._response_url(),
            data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            method="POST",
        )
        raw = self._transport(request, float(self.config.timeout_seconds))
        if self.config.api_protocol == "responses":
            content = self._responses_output_text(raw)
        else:
            try:
                choices = raw["choices"]
                first = choices[0]
                content = first["message"]["content"]
            except (KeyError, IndexError, TypeError) as exc:
                raise LLMResponseFormatError("Provider response lacks choices[0].message.content.") from exc
        if not isinstance(content, str) or not content.strip():
            raise LLMResponseFormatError("Provider response content is empty or not text.")
        model = raw.get("model", self.config.model)
        usage = raw.get("usage", {})
        if not isinstance(model, str) or not isinstance(usage, Mapping):
            raise LLMResponseFormatError("Provider response has malformed model or usage fields.")
        return Completion(content=content, model=model, usage=dict(usage), raw_response=dict(raw))
