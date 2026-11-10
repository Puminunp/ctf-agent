"""Flag verification. Lives in the trusted controller; the solver only ever sees True/False text.

HashVerifier is a local stand-in. If the instructor supplies a private verifier, wrap it in the
same one-method interface and pass it to the controller instead.
"""

from __future__ import annotations

import hashlib
import hmac
from typing import Protocol


class Verifier(Protocol):
    def verify(self, candidate: str) -> bool: ...


class HashVerifier:
    def __init__(self, expected_flag: str):
        self._digest = hashlib.sha256(expected_flag.strip().encode()).digest()

    def verify(self, candidate: str) -> bool:
        cand = hashlib.sha256(candidate.strip().encode()).digest()
        return hmac.compare_digest(cand, self._digest)
