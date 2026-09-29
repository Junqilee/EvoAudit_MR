"""Native Ollama `/api/chat` client with schema-constrained local decoding."""

from __future__ import annotations

from dataclasses import dataclass
import json
from time import perf_counter
from typing import Any, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from evoaudit_mr.llm.ollama import OllamaClientError, OllamaModelInfo, validate_local_endpoint


@dataclass(frozen=True)
class NativeOllamaCompletion:
    content: str
    model: str
    usage: Mapping[str, int]
    latency_seconds: float
    raw_response: Mapping[str, Any]


class NativeOllamaClient:
    """Use the native endpoint so Ollama receives the per-environment schema in ``format``."""

    def __init__(self, endpoint: str = "http://127.0.0.1:11434") -> None:
        self.endpoint = validate_local_endpoint(endpoint)

    def _get(self, path: str, *, timeout_seconds: float = 15) -> Mapping[str, Any]:
        try:
            with urlopen(f"{self.endpoint}{path}", timeout=timeout_seconds) as response:  # noqa: S310 - loopback validated
                raw = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise OllamaClientError(f"Ollama returned HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')[:300]}") from exc
        except URLError as exc:
            raise OllamaClientError(f"Cannot connect to local Ollama: {exc.reason}") from exc
        if not isinstance(raw, Mapping):
            raise OllamaClientError("Ollama metadata response is malformed.")
        return raw

    def model_info(self, model: str) -> OllamaModelInfo:
        version_payload = self._get("/api/version")
        tags_payload = self._get("/api/tags")
        version = version_payload.get("version")
        models = tags_payload.get("models")
        if not isinstance(version, str) or not isinstance(models, list):
            raise OllamaClientError("Ollama metadata response is malformed.")
        selected = next((item for item in models if isinstance(item, Mapping) and item.get("name") == model), None)
        if selected is None:
            raise OllamaClientError(f"Ollama model {model!r} is not installed.")
        digest = selected.get("digest")
        if not isinstance(digest, str) or not digest:
            raise OllamaClientError("Ollama model metadata lacks a digest.")
        return OllamaModelInfo(
            endpoint=self.endpoint,
            ollama_version=version,
            model=model,
            digest=digest,
            size_bytes=selected.get("size") if isinstance(selected.get("size"), int) else None,
            modified_at=selected.get("modified_at") if isinstance(selected.get("modified_at"), str) else None,
        )

    def complete(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        schema: Mapping[str, Any],
        model: str,
        temperature: float,
        top_p: float,
        seed: int,
        num_predict: int,
        timeout_seconds: int,
    ) -> NativeOllamaCompletion:
        payload = {
            "model": model,
            "messages": [dict(message) for message in messages],
            "format": dict(schema),
            "stream": False,
            "options": {
                "temperature": temperature,
                "top_p": top_p,
                "seed": seed,
                "num_predict": num_predict,
            },
        }
        request = Request(
            f"{self.endpoint}/api/chat",
            data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        started = perf_counter()
        try:
            with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310 - loopback validated
                raw = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise OllamaClientError(f"Ollama returned HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')[:300]}") from exc
        except URLError as exc:
            raise OllamaClientError(f"Cannot connect to local Ollama: {exc.reason}") from exc
        if not isinstance(raw, Mapping):
            raise OllamaClientError("Ollama returned a non-object native chat response.")
        message = raw.get("message")
        content = message.get("content") if isinstance(message, Mapping) else None
        if not isinstance(content, str):
            raise OllamaClientError("Ollama native response lacks message.content.")
        returned_model = raw.get("model", model)
        if not isinstance(returned_model, str):
            raise OllamaClientError("Ollama native response model is malformed.")
        usage = {
            "prompt_tokens": int(raw.get("prompt_eval_count", 0)),
            "completion_tokens": int(raw.get("eval_count", 0)),
            "total_tokens": int(raw.get("prompt_eval_count", 0)) + int(raw.get("eval_count", 0)),
        }
        return NativeOllamaCompletion(
            content=content,
            model=returned_model,
            usage=usage,
            latency_seconds=perf_counter() - started,
            raw_response=dict(raw),
        )
