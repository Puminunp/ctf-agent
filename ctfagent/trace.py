"""JSONL event log for one attempt. Secrets are redacted and long values are capped."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

MAX_FIELD_CHARS = 20_000


class Trace:
    def __init__(self, path: str | Path | None, secrets: list[str] | None = None, clock=time.time):
        self.path = Path(path) if path else None
        self._secrets = [s for s in (secrets or []) if s and len(s) >= 8]
        self._clock = clock
        self.events: list[dict] = []      # kept in memory too, for tests and the summary
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text("", encoding="utf-8")

    def _clean(self, value: Any) -> Any:
        if isinstance(value, str):
            for s in self._secrets:
                value = value.replace(s, "[REDACTED]")
            if len(value) > MAX_FIELD_CHARS:
                value = value[:MAX_FIELD_CHARS] + f"[... {len(value) - MAX_FIELD_CHARS} chars cut]"
            return value
        if isinstance(value, dict):
            return {k: self._clean(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [self._clean(v) for v in value]
        return value

    def redact_everywhere(self, secret: str) -> None:
        """Remove a value from every event already written (used for a verified flag) and from future ones."""
        if not secret or len(secret) < 8:
            return
        self._secrets.append(secret)
        self.events = [self._clean(e) for e in self.events]
        if self.path:
            self.path.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in self.events),
                                 encoding="utf-8")

    def event(self, type_: str, **fields: Any) -> None:
        record = {"ts": round(self._clock(), 3), "type": type_, **self._clean(fields)}
        self.events.append(record)
        if self.path:
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
