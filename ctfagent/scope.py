"""Best-effort screening of commands for out-of-scope network targets.

This is a tripwire, not the control. The real control is the network the solver runs on
(see README, "Controls"). A hit here ends the attempt as a scope_violation and keeps the trace.
"""

from __future__ import annotations

import re

LOOPBACK = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}

_URL = re.compile(r"\b([a-zA-Z][a-zA-Z0-9+.-]*)://(?:[^/\s@'\"]+@)?(\[[^\]]+\]|[^/\s:'\"?#]+)")
_NET_TOOL = re.compile(r"\b(?:curl|wget|nc|ncat|netcat|telnet|ssh|scp|ping|nmap|socat)\b")
_IPV4 = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")
_PWN_REMOTE = re.compile(r"\bremote\(\s*['\"]([^'\"]+)['\"]")


def _norm(host: str) -> str:
    return host.strip("[]").lower()


def find_violations(command: str, allowed_hosts: set[str] | frozenset[str]) -> list[str]:
    allowed = {_norm(h) for h in allowed_hosts} | LOOPBACK
    found: list[str] = []

    def check(host: str) -> None:
        h = _norm(host)
        if not h or "$" in h or "{" in h or "`" in h:   # unresolved shell variable: cannot judge
            return
        if h not in allowed:
            found.append(h)

    for scheme, host in _URL.findall(command):
        if scheme.lower() != "file":
            check(host)
    for m in _PWN_REMOTE.finditer(command):
        check(m.group(1))
    for segment in re.split(r"[;|&\n]", command):
        if _NET_TOOL.search(segment):
            for tok in segment.split():
                tok = tok.rsplit("@", 1)[-1]
                if _IPV4.match(tok):
                    check(tok)
    return sorted(set(found))
