from functools import lru_cache
from typing import Protocol

import numpy as np
from langchain_openai import OpenAIEmbeddings


class Embedder(Protocol):
    def embed(self, text: str) -> np.ndarray: ...


class LangChainEmbedder:
    """LangChain embeddings against an OpenAI-compatible endpoint (OMLX)."""

    def __init__(self, model: str, base_url: str, api_key: str):
        self._emb = OpenAIEmbeddings(
            model=model,
            base_url=base_url,
            api_key=api_key,
            check_embedding_ctx_length=False,  # send raw text; non-OpenAI servers
        )
        self._cached = lru_cache(maxsize=512)(self._embed)

    def _embed(self, text: str) -> np.ndarray:
        return np.asarray(self._emb.embed_query(text), dtype=np.float32)

    def embed(self, text: str) -> np.ndarray:
        return self._cached(text)
