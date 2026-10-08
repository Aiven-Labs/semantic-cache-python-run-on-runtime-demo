"""The settings file (settings.toml): typed, validated, no environment or secrets involved."""

import tomllib
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")  # a typo in settings.toml is an error, not ignored


class CacheCfg(_Strict):
    crawl_max_distance: float = Field(ge=0, le=2)
    crawl_ttl_seconds: int = Field(ge=1)
    answer_max_distance: float = Field(ge=0, le=2)
    answer_ttl_seconds: int = Field(ge=1)


class ModelsCfg(_Strict):
    hit: str = Field(min_length=1)  # cheapest: answers from what is already cached
    classifier: str = Field(min_length=1)  # mid tier: says what an unmatched message wants
    miss: str = Field(min_length=1)  # expensive: live GitHub data or real reasoning


class JevCfg(_Strict):
    """Jev (TypeSafe AI) classifies unmatched messages when TYPESAFE_API_KEY is set."""

    model: str = Field(min_length=1)
    min_confidence: float = Field(ge=0, le=1)  # below this, treat the classifier as unavailable


class CoverageCfg(_Strict):
    """When does the cache 'cover' a search topic, so a fresh GitHub search would add little?"""

    index_hit_distance: float = Field(ge=0, le=2)  # a repo this close to the topic counts
    index_hit_min: int = Field(ge=1)  # ...and this many of them make it a hit


class VoteCfg(_Strict):
    """Distance-free routing: nearest earlier questions vote; each route's cutoff is learned."""

    k: int = Field(ge=1)  # how many earlier questions vote
    min_share: float = Field(ge=0, le=1)  # the winning route needs this share of the vote
    min_samples: int = Field(ge=1)  # a route is trusted after this many question pairs
    spread: float = Field(ge=0)  # standard deviations past a route's mean spacing still match


class RoutingCfg(_Strict):
    vote: VoteCfg
    models: ModelsCfg
    jev: JevCfg
    coverage: CoverageCfg
    always_expensive: list[str]  # routes that need reasoning, never retrieval (e.g. analysis)
    pin: dict[str, str]  # route name -> model, overriding the distance table (may be empty)
    # Short messages in an ongoing chat ("so Dify uses vite?") match no example on their own.
    # When nothing matches, they inherit the previous tool route and use this model instead.
    followup_max_words: int = Field(ge=0)
    followup_model: str = Field(min_length=1)


class ChatCfg(_Strict):
    history_turns: int = Field(ge=0)
    conversation_ttl_seconds: int = Field(ge=1)
    max_tool_steps: int = Field(ge=0)


class SearchCfg(_Strict):
    results_per_query: int = Field(ge=1, le=100)


class ModelPrice(_Strict):
    input_per_mtok: float = Field(ge=0)
    output_per_mtok: float = Field(ge=0)


class GithubCfg(_Strict):
    repo_cache_ttl_seconds: int = Field(ge=1)  # repo file listings and file reads
    detail_ttl_seconds: int = Field(
        ge=1
    )  # the Compose file saved at search time, for details pages


class CostCfg(_Strict):
    models: dict[str, ModelPrice]


class Tunables(_Strict):
    cache: CacheCfg
    routing: RoutingCfg
    chat: ChatCfg
    search: SearchCfg
    github: GithubCfg
    cost: CostCfg


def load_tunables(path: str | Path) -> Tunables:
    p = Path(path)
    if not p.is_file():
        raise RuntimeError(f"settings file not found: {p} (set SEMCACHE_SETTINGS_FILE)")
    with p.open("rb") as f:
        return Tunables.model_validate(tomllib.load(f))
