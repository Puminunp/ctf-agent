"""Model client for an OpenAI-compatible chat endpoint (the Duke AI Gateway / LiteLLM).

Standard library only. The token never appears in exceptions or logs.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field


class LLMError(Exception):
    """The model could not be reached or returned something unusable."""


@dataclass
class ToolCall:
    id: str
    name: str
    arguments_raw: str


@dataclass
class LLMResponse:
    content: str | None
    tool_calls: list[ToolCall]
    assistant_message: dict          # the message to append to the history, as sent back to the API
    input_tokens: int | None = None  # None when the gateway reports no usage
    output_tokens: int | None = None
    finish_reason: str | None = None
    latency_s: float = 0.0


class GatewayClient:
    RETRY_STATUS = {429, 500, 502, 503, 504}

    def __init__(self, base_url: str, token: str, model: str, temperature: float = 0.0,
                 timeout_s: float = 120.0, retries: int = 2, sleep=time.sleep,
                 backoff_cap_s: float = 8.0, honor_retry_after: bool = False, retry_budget_s: float = 1e9):
        if not base_url or not token or not model:
            raise LLMError("base_url, token and model are all required")
        self.url = base_url.rstrip("/") + "/chat/completions"
        self._token = token
        self.model = model
        self.temperature = temperature
        self.timeout_s = timeout_s
        self.retries = retries
        self._sleep = sleep
        self.backoff_cap_s = backoff_cap_s
        self.honor_retry_after = honor_retry_after
        self.retry_budget_s = retry_budget_s

    def _wait_time(self, attempt: int, retry_after: str | None) -> float:
        wait = min(2 ** attempt, self.backoff_cap_s)
        if self.honor_retry_after and retry_after:
            try:
                wait = max(wait, min(float(retry_after), self.backoff_cap_s))
            except ValueError:
                pass
        return wait

    def complete(self, messages: list[dict], tools: list[dict]) -> LLMResponse:
        body = json.dumps({
            "model": self.model, "messages": messages, "tools": tools,
            "tool_choice": "auto", "temperature": self.temperature,
        }).encode()
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {self._token}"}
        problem, retry_after, waited = "unknown", None, 0.0
        for attempt in range(self.retries + 1):
            t0 = time.monotonic()
            retry_after = None
            try:
                req = urllib.request.Request(self.url, data=body, headers=headers, method="POST")
                with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
                return parse_response(payload, time.monotonic() - t0)
            except urllib.error.HTTPError as e:
                problem = f"HTTP {e.code}"
                retry_after = e.headers.get("Retry-After") if e.headers else None
                if e.code not in self.RETRY_STATUS:
                    break
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                problem = f"connection problem ({type(e).__name__})"
            except (ValueError, KeyError) as e:
                raise LLMError(f"unreadable gateway response ({type(e).__name__})") from None
            if attempt < self.retries:
                wait = self._wait_time(attempt, retry_after)
                if waited + wait > self.retry_budget_s:
                    break
                self._sleep(wait)
                waited += wait
        raise LLMError(f"gateway call failed: {problem}")


def parse_response(payload: dict, latency_s: float) -> LLMResponse:
    try:
        choice = payload["choices"][0]
        msg = choice["message"]
    except (KeyError, IndexError, TypeError):
        raise LLMError("gateway response has no choices[0].message") from None
    calls: list[ToolCall] = []
    for tc in msg.get("tool_calls") or []:
        try:
            calls.append(ToolCall(id=str(tc["id"]), name=tc["function"]["name"],
                                  arguments_raw=tc["function"].get("arguments") or "{}"))
        except (KeyError, TypeError):
            raise LLMError("malformed tool call in gateway response") from None
    usage = payload.get("usage") or {}
    history_msg = {"role": "assistant", "content": msg.get("content")}
    if msg.get("tool_calls"):
        history_msg["tool_calls"] = msg["tool_calls"]
    return LLMResponse(
        content=msg.get("content"), tool_calls=calls, assistant_message=history_msg,
        input_tokens=usage.get("prompt_tokens"), output_tokens=usage.get("completion_tokens"),
        finish_reason=choice.get("finish_reason"), latency_s=latency_s,
    )


@dataclass
class ScriptedLLM:
    """Deterministic stand-in for tests: returns the queued responses in order."""
    responses: list[LLMResponse] = field(default_factory=list)
    calls: int = 0

    def complete(self, messages: list[dict], tools: list[dict]) -> LLMResponse:
        if self.calls >= len(self.responses):
            raise LLMError("scripted LLM ran out of responses")
        r = self.responses[self.calls]
        self.calls += 1
        return r
