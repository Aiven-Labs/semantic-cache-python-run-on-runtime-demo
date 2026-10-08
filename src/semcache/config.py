import os

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .tunables import Tunables, load_tunables


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SEMCACHE_", populate_by_name=True)

    # Aiven Runtime injects VALKEY_URL for the integrated Valkey service. Never log it.
    valkey_url: str = Field(
        "valkey://localhost:6379",
        validation_alias=AliasChoices("VALKEY_URL", "SEMCACHE_VALKEY_URL"),
    )
    github_token: str | None = Field(
        None, validation_alias=AliasChoices("GITHUB_TOKEN", "SEMCACHE_GITHUB_TOKEN")
    )

    # Any OpenAI-compatible embeddings server (e.g. OMLX). All required, no defaults:
    # SEMCACHE_EMBED_BASE_URL, SEMCACHE_EMBED_API_KEY, SEMCACHE_EMBED_MODEL, SEMCACHE_EMBED_DIM
    embed_base_url: str
    embed_api_key: str
    embed_model: str
    embed_dim: int  # must match the embedding model's output size

    # Chat endpoint. Required, no defaults. Point these at an OpenAI-compatible gateway such as
    # the Aiven AI gateway, which can route one model name to a hosted provider (your API key) and
    # another to a local server. WHICH model answers is chosen in settings.toml by router distance.
    llm_base_url: str  # SEMCACHE_LLM_BASE_URL
    llm_api_key: str  # SEMCACHE_LLM_API_KEY

    # Jev classifier (TypeSafe AI). Optional: without it the settings.toml classifier runs.
    typesafe_api_key: str | None = Field(
        None, validation_alias=AliasChoices("TYPESAFE_API_KEY", "SEMCACHE_TYPESAFE_API_KEY")
    )

    # Seeding SEED_OWNERS runs as a Temporal workflow. Unset = no seeding. The api key is only
    # for Temporal Cloud (it also turns TLS on); keep it in fnox and never log it.
    temporal_address: str | None = Field(
        None, validation_alias=AliasChoices("SEMCACHE_TEMPORAL_ADDRESS", "TEMPORAL_ADDRESS")
    )
    temporal_namespace: str = Field(
        "default",
        validation_alias=AliasChoices("SEMCACHE_TEMPORAL_NAMESPACE", "TEMPORAL_NAMESPACE"),
    )
    temporal_api_key: str | None = Field(
        None, validation_alias=AliasChoices("SEMCACHE_TEMPORAL_API_KEY", "TEMPORAL_API_KEY")
    )

    # Editing models and prices on /settings is off unless this is set (the app has no logins).
    # Keep it in fnox; never log it.
    admin_token: str | None = Field(
        None, validation_alias=AliasChoices("SEMCACHE_ADMIN_TOKEN", "ADMIN_TOKEN")
    )

    # Index names. The tunable numbers (distances, TTLs, prices) live in settings.toml.
    cache_index: str = "idx:crawlcache"
    cache_prefix: str = "crawlcache:"

    chat_cache_index: str = "idx:chatcache"
    chat_cache_prefix: str = "chatcache:"

    catalog_index: str = "idx:catalog"
    catalog_prefix: str = "catalog:"

    tunables: Tunables = Field(
        default_factory=lambda: load_tunables(
            os.environ.get("SEMCACHE_SETTINGS_FILE", "settings.toml")
        )
    )


settings = Settings()
tunables = settings.tunables
