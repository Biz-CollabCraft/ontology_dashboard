"""Rate-limit policy contract shared by routers and infrastructure adapters."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from .exceptions import RateLimitExceeded


@dataclass(frozen=True)
class RateLimitRule:
    limit: int
    window_seconds: int


class RateLimiter:
    """Synchronous limiter port used by HTTP dependencies."""

    @staticmethod
    def anonymized_key(*parts: str) -> str:
        payload = "|".join(parts)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def check(self, *, bucket: str, subject: str, rule: RateLimitRule) -> None:
        raise NotImplementedError

    def clear(self) -> None:
        raise NotImplementedError


__all__ = ["RateLimitExceeded", "RateLimiter", "RateLimitRule"]
