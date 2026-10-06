import hashlib
import re
import time
from dataclasses import dataclass

import valkey

from .embed import Embedder

_TAG_ESCAPE = re.compile(r"([^A-Za-z0-9_])")


def _escape_tag(value: str) -> str:
    return _TAG_ESCAPE.sub(r"\\\1", value)


@dataclass
class Hit:
    response: str
    distance: float
    original_prompt: str
    meta: str = ""  # free-form JSON stored with the entry (e.g. what generating it cost)


class SemanticCache:
    """Vector cache over Valkey hashes, queried with FT.SEARCH.

    Every entry carries a `tenant` TAG so one index serves all customers and
    KNN is pre-filtered per tenant (hybrid search: tag filter + vector).
    """

    def __init__(
        self,
        client: valkey.Valkey,
        embedder: Embedder,
        *,
        index_name: str,
        prefix: str,
        dim: int,
        max_distance: float,
        ttl_seconds: int,
    ):
        self.r = client
        self.embedder = embedder
        self.index = index_name
        self.prefix = prefix
        self.dim = dim
        self.max_distance = max_distance
        self.ttl = ttl_seconds

    def ensure_index(self) -> None:
        try:
            self.r.execute_command("FT.INFO", self.index)
            return
        except valkey.ResponseError:
            pass
        self.r.execute_command(
            "FT.CREATE", self.index, "ON", "HASH", "PREFIX", "1", self.prefix,
            "SCHEMA",
            "tenant", "TAG",
            "embedding", "VECTOR", "HNSW", "6",
            "TYPE", "FLOAT32", "DIM", str(self.dim), "DISTANCE_METRIC", "COSINE",
        )  # fmt: skip

    def lookup(self, tenant: str, prompt: str) -> Hit | None:
        vec = self.embedder.embed(prompt).tobytes()
        query = f"@tenant:{{{_escape_tag(tenant)}}}=>[KNN 1 @embedding $vec AS distance]"
        res = self.r.execute_command(
            "FT.SEARCH", self.index, query,
            "PARAMS", "2", "vec", vec,
            "RETURN", "4", "distance", "response", "prompt", "meta",
            "DIALECT", "2",
        )  # fmt: skip
        if not res or res[0] == 0:
            return None
        fields = _to_dict(res[2])
        distance = float(fields["distance"])
        if distance > self.max_distance:
            return None
        return Hit(fields["response"], distance, fields["prompt"], fields.get("meta", ""))

    def store(self, tenant: str, prompt: str, response: str, meta: str = "") -> None:
        digest = hashlib.sha256(f"{tenant}:{prompt}".encode()).hexdigest()[:24]
        key = f"{self.prefix}{digest}"
        self.r.hset(
            key,
            mapping={
                "tenant": tenant,
                "prompt": prompt,
                "response": response,
                "meta": meta,
                "created": int(time.time()),
                "embedding": self.embedder.embed(prompt).tobytes(),
            },
        )
        self.r.expire(key, self.ttl)


def _to_dict(flat: list) -> dict[str, str]:
    out = {}
    for k, v in zip(flat[::2], flat[1::2], strict=True):
        out[k.decode() if isinstance(k, bytes) else k] = v.decode() if isinstance(v, bytes) else v
    return out
