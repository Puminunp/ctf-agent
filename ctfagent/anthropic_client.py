"""Direct Anthropic Messages API client, with the same interface as GatewayClient.

The agent keeps an OpenAI-chat-shaped history (system / user / assistant / tool dicts). This adapter
translates that to the Anthropic Messages API on every call and the response back again, so the agent
loop, the trace and the controller are all unchanged -- only the transport differs.

The raw Anthropic content blocks (text, thinking, tool_use) are stashed on the assistant message under
`_anthropic_content` and replayed verbatim on the next call. That is required for extended thinking with
tool use: Anthropic rejects a follow-up request that drops the thinking block preceding a tool_use.

`temperature` is never sent -- Opus 4.8 (and every current model from 2026-10-21) returns a 400 for it.
"""

from __future__ import annotations

import json
import time

from .llm import LLMError, LLMResponse, ToolCall


def _tools_to_anthropic(tools: list[dict]) -> list[dict]:
    """OpenAI function specs -> Anthropic tool specs."""
    out = []
    for t in tools:
        fn = t.get("function", t)
        out.append({
            "name": fn["name"],
            "description": fn.get("description", ""),
            "input_schema": fn.get("parameters") or {"type": "object", "properties": {}},
        })
    return out


def _append_user(msgs: list[dict], blocks: list[dict]) -> None:
    """Add blocks to the trailing user message, or open a new one. Coalescing consecutive user turns
    (tool results, then any nudge text) keeps the strict user/assistant alternation Anthropic wants."""
    if not blocks:
        return
    if msgs and msgs[-1]["role"] == "user":
        msgs[-1]["content"].extend(blocks)
    else:
        msgs.append({"role": "user", "content": list(blocks)})


def _messages_to_anthropic(messages: list[dict]) -> tuple[str, list[dict]]:
    """OpenAI-shaped history -> (system string, Anthropic messages)."""
    system_parts: list[str] = []
    out: list[dict] = []
    for m in messages:
        role = m.get("role")
        if role == "system":
            if m.get("content"):
                system_parts.append(m["content"])
        elif role == "user":
            if m.get("content"):
                _append_user(out, [{"type": "text", "text": m["content"]}])
        elif role == "assistant":
            raw = m.get("_anthropic_content")
            if raw:                       # replay the original blocks (keeps thinking signatures intact)
                out.append({"role": "assistant", "content": raw})
                continue
            blocks: list[dict] = []
            if m.get("content"):
                blocks.append({"type": "text", "text": m["content"]})
            for tc in m.get("tool_calls") or []:
                fn = tc["function"]
                blocks.append({"type": "tool_use", "id": tc["id"], "name": fn["name"],
                               "input": json.loads(fn.get("arguments") or "{}")})
            if blocks:
                out.append({"role": "assistant", "content": blocks})
        elif role == "tool":
            _append_user(out, [{"type": "tool_result",
                                "tool_use_id": m.get("tool_call_id"),
                                "content": m.get("content") or ""}])
    return "\n\n".join(system_parts), out


def _block_dump(block):
    """A content block as a plain dict the API will accept back on the next request."""
    if hasattr(block, "model_dump"):
        return block.model_dump(exclude_none=True)
    return block


def parse_anthropic(resp, latency_s: float) -> LLMResponse:
    text_parts: list[str] = []
    calls: list[ToolCall] = []
    raw_blocks: list[dict] = []
    for b in resp.content:
        raw_blocks.append(_block_dump(b))
        bt = getattr(b, "type", None)
        if bt == "text":
            text_parts.append(b.text)
        elif bt == "tool_use":
            calls.append(ToolCall(id=b.id, name=b.name, arguments_raw=json.dumps(b.input)))
    text = "".join(text_parts) or None
    stop = getattr(resp, "stop_reason", None)
    if stop == "refusal":
        det = getattr(resp, "stop_details", None)
        cat = getattr(det, "category", None) if det else None
        text = f"[refusal: {cat}] {text or ''}".strip()
    if not raw_blocks:                    # never replay an empty assistant turn
        raw_blocks = [{"type": "text", "text": text or "(no content)"}]
    usage = getattr(resp, "usage", None)
    assistant_message = {"role": "assistant", "content": text, "_anthropic_content": raw_blocks}
    return LLMResponse(
        content=text, tool_calls=calls, assistant_message=assistant_message,
        input_tokens=getattr(usage, "input_tokens", None) if usage else None,
        output_tokens=getattr(usage, "output_tokens", None) if usage else None,
        finish_reason=stop, latency_s=latency_s,
    )


class AnthropicClient:
    """Calls the Anthropic Messages API directly. Same `.complete(messages, tools)` contract as
    GatewayClient, so run_htb.py can swap it in by config.provider == 'anthropic'."""

    def __init__(self, api_key: str, model: str, max_tokens: int = 16000, timeout_s: float = 600.0,
                 retries: int = 2, effort: str = "high", thinking: bool = True):
        if not api_key or not model:
            raise LLMError("api_key and model are both required")
        try:
            import anthropic
        except ImportError as e:
            raise LLMError("the 'anthropic' package is not installed (pip install anthropic)") from e
        self._anthropic = anthropic
        self._client = anthropic.Anthropic(api_key=api_key, max_retries=retries, timeout=timeout_s)
        self.model = model
        self.max_tokens = max_tokens
        self.effort = effort
        self.thinking = thinking

    def _create(self, kwargs: dict):
        """Call the SDK, dropping an optional param the installed SDK/model doesn't accept, then retry."""
        while True:
            try:
                return self._client.messages.create(**kwargs)
            except TypeError as e:
                msg = str(e)
                for k in ("output_config", "thinking", "speed"):
                    if k in kwargs and k in msg:
                        kwargs.pop(k)
                        break
                else:
                    raise LLMError(f"anthropic SDK rejected the request shape: {msg[:300]}") from None

    def complete(self, messages: list[dict], tools: list[dict]) -> LLMResponse:
        system, msgs = _messages_to_anthropic(messages)
        kwargs: dict = {"model": self.model, "max_tokens": self.max_tokens, "messages": msgs}
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = _tools_to_anthropic(tools)
        if self.thinking:
            kwargs["thinking"] = {"type": "adaptive"}
        if self.effort:
            kwargs["output_config"] = {"effort": self.effort}
        t0 = time.monotonic()
        try:
            resp = self._create(kwargs)
        except self._anthropic.APIStatusError as e:   # 4xx/5xx; keep the body, like the gateway 400 fix
            detail = getattr(e, "message", "") or str(e)
            raise LLMError(f"anthropic call failed: HTTP {e.status_code}: {detail[:500]}") from None
        except self._anthropic.APIError as e:          # connection/timeout/other
            raise LLMError(f"anthropic call failed: {type(e).__name__}: {str(e)[:300]}") from None
        return parse_anthropic(resp, time.monotonic() - t0)
