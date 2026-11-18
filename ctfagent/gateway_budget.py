"""Read the Duke gateway key's REAL spend from LiteLLM, so a run can stop on the gateway's own numbers
instead of only our token-based estimate.

LiteLLM tracks cumulative spend per key and enforces the key's ``max_budget`` server-side (once exceeded
it rejects calls), so this is a second, authoritative view of cost on top of the per-attempt estimate in
`config.Pricing`. It also reflects spend across *every* machine using the same key — which matters for a
team key shared between two laptops. Standard library only; the token is only ever sent in the header.
"""

from __future__ import annotations

import json
import urllib.request


def _root(base_url: str) -> str:
    """The gateway origin without the OpenAI-style ``/v1`` suffix (/key/info lives at the root)."""
    root = base_url.rstrip("/")
    return root[:-3].rstrip("/") if root.endswith("/v1") else root


def key_info(base_url: str, token: str, timeout_s: float = 20.0) -> dict:
    """Return LiteLLM's info for the calling key (has 'spend', 'max_budget', 'budget_duration', ...).

    Raises on any transport/HTTP/parse problem so the caller can fall back to the estimate.
    """
    req = urllib.request.Request(_root(base_url) + "/key/info",
                                 headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data.get("info", data) if isinstance(data, dict) else {}


def budget_remaining(info: dict):
    """Dollars left on the key, or None when the key has no max_budget set (so nothing to enforce)."""
    mb = info.get("max_budget")
    if mb is None:
        return None
    try:
        return max(0.0, float(mb) - float(info.get("spend") or 0.0))
    except (TypeError, ValueError):
        return None
