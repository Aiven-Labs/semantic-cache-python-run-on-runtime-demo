import hashlib
import re

import numpy as np
import valkey

from .cache import _to_dict

FIELDS = [
    "name", "description", "url", "stars", "services", "closest", "novelty",
    "buildable", "query", "source", "language", "license", "pushed", "topics",
    "compose_path", "app_services", "image_apps", "response", "tier",
]  # fmt: skip

_TAG_ESCAPE = re.compile(r"([^A-Za-z0-9_])")


def _esc(v: str) -> str:
    return _TAG_ESCAPE.sub(r"\\\1", v)


def embed_text(name: str, description: str, tags: list[str], services: list[str]) -> str:
    uses = ", ".join(services) or "no data service"
    return f"{name}. {description}. Topics: {', '.join(tags)}. Uses: {uses}"


class Catalog:
    """One vector index holding both existing templates (kind=template) and
    discovered repos (kind=candidate). Hybrid queries filter by kind and Aiven services,
    then KNN-rank on the embedding."""

    def __init__(self, client: valkey.Valkey, *, index: str, prefix: str, dim: int):
        self.r, self.index, self.prefix, self.dim = client, index, prefix, dim

    def ensure_index(self) -> None:
        try:
            self.r.execute_command("FT.INFO", self.index)
            return
        except valkey.ResponseError:
            pass
        self.r.execute_command(
            "FT.CREATE", self.index, "ON", "HASH", "PREFIX", "1", self.prefix,
            "SCHEMA",
            "kind", "TAG",
            "services", "TAG",
            "embedding", "VECTOR", "HNSW", "6",
            "TYPE", "FLOAT32", "DIM", str(self.dim), "DISTANCE_METRIC", "COSINE",
        )  # fmt: skip

    def key(self, kind: str, ident: str) -> str:
        return f"{self.prefix}{kind}:{hashlib.sha256(ident.encode()).hexdigest()[:20]}"

    def exists(self, kind: str, ident: str) -> bool:
        return bool(self.r.exists(self.key(kind, ident)))

    def upsert(self, kind: str, ident: str, vec: np.ndarray, fields: dict) -> None:
        services = fields.get("services") or ["none"]
        self.r.hset(
            self.key(kind, ident),
            mapping={
                **{k: str(v) for k, v in fields.items() if k != "services"},
                "kind": kind,
                "services": ",".join(services),
                "embedding": vec.astype(np.float32).tobytes(),
            },
        )

    def search(
        self, vec: np.ndarray, kind: str, services: list[str] | None = None, k: int = 10
    ) -> list[dict]:
        filt = f"@kind:{{{kind}}}"
        if services:
            filt += " @services:{" + "|".join(_esc(s) for s in services) + "}"
        fields = ["distance", *FIELDS]
        res = self.r.execute_command(
            "FT.SEARCH", self.index, f"({filt})=>[KNN {k} @embedding $vec AS distance]",
            "PARAMS", "2", "vec", vec.astype(np.float32).tobytes(),
            "RETURN", str(len(fields)), *fields,
            "DIALECT", "2",
        )  # fmt: skip
        out = []
        for i in range(1, len(res), 2):
            row = _to_dict(res[i + 1])
            row["distance"] = float(row["distance"])
            out.append(row)
        return sorted(out, key=lambda r: r["distance"])

    def browse(self, kind: str, limit: int = 200, offset: int = 0) -> list[dict]:
        """One page of what is stored for `kind`, no embedding needed."""
        res = self.r.execute_command(
            "FT.SEARCH", self.index, f"@kind:{{{kind}}}",
            "RETURN", str(len(FIELDS)), *FIELDS,
            "LIMIT", str(offset), str(limit),
        )  # fmt: skip
        return [_to_dict(res[i + 1]) for i in range(1, len(res), 2)]

    def list_all(self, kind: str, page: int = 200, max_rows: int = 5000) -> list[dict]:
        """Every document of `kind`, paged so growth past one page never truncates the list."""
        rows: list[dict] = []
        while len(rows) < max_rows:
            batch = self.browse(kind, page, len(rows))
            rows += batch
            if len(batch) < page:
                break
        return rows

    def get(self, kind: str, ident: str) -> dict | None:
        """One stored document by its id (e.g. 'owner/name'), or None."""
        raw = self.r.hgetall(self.key(kind, ident))
        if not raw:
            return None
        return {
            (k.decode() if isinstance(k, bytes) else k): (v.decode() if isinstance(v, bytes) else v)
            for k, v in raw.items()
            if k not in (b"embedding", "embedding")
        }

    def vector(self, kind: str, ident: str):
        """The stored embedding for one document, or None."""
        raw = self.r.hget(self.key(kind, ident), "embedding")
        return None if raw is None else np.frombuffer(raw, dtype=np.float32)

    def route_stats(self, route: str) -> tuple[int, float, float]:
        """(samples, mean, std) of how close a route's questions land to each other."""
        raw = self.r.hgetall(f"stats:{self.prefix}{route}")
        if not raw:
            return 0, 0.0, 0.0
        f = {(k.decode() if isinstance(k, bytes) else k): float(v) for k, v in raw.items()}
        n = int(f.get("n", 0))
        return n, f.get("mean", 0.0), (f.get("m2", 0.0) / n) ** 0.5 if n > 1 else 0.0

    def add_route_sample(self, route: str, distance: float) -> None:
        """Welford's running mean/variance, so no distance list is kept."""
        key = f"stats:{self.prefix}{route}"  # outside the index prefix: never indexed as a doc
        n, mean, std = self.route_stats(route)
        m2 = (std**2) * n
        n += 1
        delta = distance - mean
        mean += delta / n
        m2 += delta * (distance - mean)
        self.r.hset(key, mapping={"n": n, "mean": mean, "m2": m2})

    def nearest_template(self, vec: np.ndarray) -> tuple[str, float] | None:
        hits = self.search(vec, "template", k=1)
        return (hits[0]["name"], hits[0]["distance"]) if hits else None
