"""Valkey cache for repo file listings and file reads, so repeat tool calls are free."""

import hashlib
import json
from collections.abc import Callable

from .github import clean


class RepoCache:
    def __init__(self, client, ttl: int, prefix: str = "repocache:"):
        self.r, self.ttl, self.prefix = client, ttl, prefix

    def _key(self, kind: str, repo: str, path: str) -> str:
        path = clean(repo, path)
        digest = hashlib.sha256(f"{repo.lower()}|{path}".encode()).hexdigest()[:24]
        return f"{self.prefix}{kind}:{digest}"

    def peek(self, kind: str, repo: str, path: str = ""):
        """What is cached, or None. Never fetches: this is how a page reads only the cache."""
        raw = self.r.get(self._key(kind, repo, path))
        return None if raw is None else json.loads(raw)

    def forget(self, kind: str, repo: str, path: str = "") -> None:
        self.r.delete(self._key(kind, repo, path))

    def put(self, kind: str, repo: str, path: str, value, ttl: int | None = None) -> None:
        self.r.setex(self._key(kind, repo, path), ttl or self.ttl, json.dumps(value))

    def get(
        self, kind: str, repo: str, path: str, fetch: Callable[[], object], ttl: int | None = None
    ):
        """Cached value, else `fetch()` stored and returned. Errors are never cached."""
        key = self._key(kind, repo, path)  # validates input before it reaches a key or a URL
        raw = self.r.get(key)
        if raw is not None:
            return json.loads(raw)
        value = fetch()
        self.r.setex(key, ttl or self.ttl, json.dumps(value))
        return value
