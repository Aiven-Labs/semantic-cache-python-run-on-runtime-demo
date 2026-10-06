"""Estimated spend and savings, from the prices in settings.toml."""

from .tunables import ModelPrice

STAT_KEY = "stats:cost"


class Pricing:
    def __init__(self, models: dict[str, ModelPrice]):
        self.models = models

    def known(self, model: str) -> bool:
        return model in self.models

    def output_price(self, model: str) -> float | None:
        p = self.models.get(model)
        return p.output_per_mtok if p else None

    def pricier(self, a: str, b: str) -> bool:
        """True when `a` is known to cost more per output token than `b`."""
        pa, pb = self.output_price(a), self.output_price(b)
        return pa is not None and pb is not None and pa > pb

    def cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        """USD for one call. Unpriced models count as 0 (the UI says 'no price set')."""
        p = self.models.get(model)
        if not p:
            return 0.0
        return (input_tokens * p.input_per_mtok + output_tokens * p.output_per_mtok) / 1_000_000


def routing_saving_total(pricing: Pricing, baseline: str, parts: list[tuple[str, int, int]]):
    """Saved versus running every token on `baseline`. `parts` is (model, tokens_in, tokens_out)
    for each model that did work (e.g. a cheap planner plus the answering model)."""
    if not pricing.known(baseline) or not all(pricing.known(m) for m, _, _ in parts):
        return 0.0
    spent = sum(pricing.cost(m, tin, tout) for m, tin, tout in parts)
    would = pricing.cost(baseline, sum(t for _, t, _ in parts), sum(t for _, _, t in parts))
    return max(0.0, would - spent)


def routing_saving(pricing: Pricing, baseline: str, model: str, tin: int, tout: int):
    """What choosing `model` saved versus sending the same tokens to the baseline (last tier)."""
    return routing_saving_total(pricing, baseline, [(model, tin, tout)])


class CostStats:
    """Running totals in one Valkey hash, shared across restarts and app instances."""

    def __init__(self, client):
        self.r = client

    def record(self, spent: float, saved_cache: float, saved_routing: float, cache_hit: bool):
        pipe = self.r.pipeline()
        pipe.hincrbyfloat(STAT_KEY, "spent_usd", spent)
        pipe.hincrbyfloat(STAT_KEY, "saved_cache_usd", saved_cache)
        pipe.hincrbyfloat(STAT_KEY, "saved_routing_usd", saved_routing)
        pipe.hincrby(STAT_KEY, "requests", 1)
        pipe.hincrby(STAT_KEY, "cache_hits", 1 if cache_hit else 0)
        pipe.execute()

    def totals(self) -> dict:
        raw = self.r.hgetall(STAT_KEY)
        get = lambda k: raw.get(k) or raw.get(k.encode()) or b"0"  # noqa: E731
        num = lambda v: float(v.decode() if isinstance(v, bytes) else v)  # noqa: E731
        return {
            "spent_usd": num(get("spent_usd")),
            "saved_cache_usd": num(get("saved_cache_usd")),
            "saved_routing_usd": num(get("saved_routing_usd")),
            "requests": int(num(get("requests"))),
            "cache_hits": int(num(get("cache_hits"))),
        }
