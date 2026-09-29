"""Small, local-only Ollama client for the LLM Proposal Pilot."""

from __future__ import annotations

from dataclasses import dataclass
import json
from time import perf_counter
from typing import Any, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


class OllamaClientError(RuntimeError):
    """The local Ollama service did not return a valid response."""


@dataclass(frozen=True)
class OllamaModelInfo:
    endpoint: str
    ollama_version: str
    model: str
    digest: str
    size_bytes: int | None
    modified_at: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "endpoint": self.endpoint,
            "ollama_version": self.ollama_version,
            "model": self.model,
            "digest": self.digest,
            "size_bytes": self.size_bytes,
            "modified_at": self.modified_at,
        }


@dataclass(frozen=True)
class OllamaCompletion:
    content: str
    model: str
    usage: Mapping[str, int]
    latency_seconds: float
    raw_response: Mapping[str, Any]


def validate_local_endpoint(endpoint: str) -> str:
    normalized = endpoint.rstrip("/")
    parsed = urlparse(normalized)
    if parsed.scheme != "http" or parsed.netloc not in {"127.0.0.1:11434", "localhost:11434"}:
        raise OllamaClientError("Ollama Pilot permits only http://127.0.0.1:11434 or http://localhost:11434.")
    return normalized


class OllamaClient:
    """Call the OpenAI-compatible endpoint while collecting local metadata."""

    def __init__(self, endpoint: str = "http://127.0.0.1:11434") -> None:
        self.endpoint = validate_local_endpoint(endpoint)

    def _get(self, path: str, *, timeout_seconds: float = 15) -> Mapping[str, Any]:
        try:
            with urlopen(f"{self.endpoint}{path}", timeout=timeout_seconds) as response:  # noqa: S310 - endpoint is loopback-only
                raw = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise OllamaClientError(f"Ollama returned HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')[:300]}") from exc
        except URLError as exc:
            raise OllamaClientError(f"Cannot connect to local Ollama: {exc.reason}") from exc
        if not isinstance(raw, Mapping):
            raise OllamaClientError("Ollama returned a non-object JSON response.")
        return raw

    def model_info(self, model: str) -> OllamaModelInfo:
        version_payload = self._get("/api/version")
        tags_payload = self._get("/api/tags")
        version = version_payload.get("version")
        models = tags_payload.get("models")
        if not isinstance(version, str) or not isinstance(models, list):
            raise OllamaClientError("Ollama metadata response is malformed.")
        selected = next((row for row in models if isinstance(row, Mapping) and row.get("name") == model), None)
        if selected is None:
            raise OllamaClientError(f"Ollama model {model!r} is not installed.")
        digest = selected.get("digest")
        if not isinstance(digest, str) or not digest:
            raise OllamaClientError("Ollama model metadata lacks a digest.")
        raw_size = selected.get("size")
        return OllamaModelInfo(
            endpoint=self.endpoint,
            ollama_version=version,
            model=model,
            digest=digest,
            size_bytes=raw_size if isinstance(raw_size, int) else None,
            modified_at=selected.get("modified_at") if isinstance(selected.get("modified_at"), str) else None,
        )

    def complete(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        model: str,
        temperature: float,
        top_p: float,
        seed: int,
        num_predict: int,
        timeout_seconds: int,
    ) -> OllamaCompletion:
        payload = {
            "model": model,
            "messages": [dict(message) for message in messages],
            "stream": False,
            "response_format": {"type": "json_object"},
            "options": {
                "temperature": temperature,
                "top_p": top_p,
                "seed": seed,
                "num_predict": num_predict,
            },
        }
        request = Request(
            f"{self.endpoint}/v1/chat/completions",
            data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        started = perf_counter()
        try:
            with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310 - endpoint is loopback-only
                raw = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise OllamaClientError(f"Ollama returned HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')[:300]}") from exc
        except URLError as exc:
            raise OllamaClientError(f"Cannot connect to local Ollama: {exc.reason}") from exc
        latency = perf_counter() - started
        if not isinstance(raw, Mapping):
            raise OllamaClientError("Ollama returned a non-object chat completion.")
        try:
            content = raw["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise OllamaClientError("Ollama response lacks choices[0].message.content.") from exc
        usage_raw = raw.get("usage", {})
        if not isinstance(content, str) or not isinstance(usage_raw, Mapping):
            raise OllamaClientError("Ollama response content or usage is malformed.")
        usage = {
            key: int(value)
            for key, value in usage_raw.items()
            if key in {"prompt_tokens", "completion_tokens", "total_tokens"} and isinstance(value, int)
        }
        returned_model = raw.get("model", model)
        if not isinstance(returned_model, str):
            raise OllamaClientError("Ollama response model is malformed.")
        return OllamaCompletion(
            content=content,
            model=returned_model,
            usage=usage,
            latency_seconds=latency,
            raw_response=dict(raw),
        )
