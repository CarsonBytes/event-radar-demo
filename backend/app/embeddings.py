"""Text embeddings for semantic (not just literal-keyword) interest
matching -- see ranking.py's stage1_filter, which blends this with the
existing keyword-overlap score. Reuses the same shared chatanywhere.tech
key/quota as chat completions (see llm_client.py) and the same truststore
SSL workaround (this machine's AVG intercepts HTTPS)."""

import logging
import math

from openai import OpenAI

from app.config import OPENAI_BASE_URL
from app.llm_client import _HTTP_CLIENT, _current_chatanywhere_key, invoke_with_rotation

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = "text-embedding-3-small"


def _build_client() -> OpenAI | None:
    # Rebuilt each call (not cached as a module-level singleton like
    # before) -- same reasoning as get_llm(): a permanently-cached client
    # would stay bound to whichever key was active the first time this ran,
    # even after invoke_with_rotation below has since moved on to the
    # fallback key for chat completions. Cheap to rebuild; _HTTP_CLIENT (the
    # actual connection pool) is still shared/reused.
    key = _current_chatanywhere_key()
    if not key:
        return None
    kwargs: dict = {"api_key": key, "http_client": _HTTP_CLIENT}
    if OPENAI_BASE_URL:
        kwargs["base_url"] = OPENAI_BASE_URL
    return OpenAI(**kwargs)


def embed_batch(texts: list[str]) -> list[list[float]] | None:
    """One request embeds the whole batch -- unlike chat completions, the
    embeddings endpoint takes an array input, so this stays cheap against
    the shared 200/day *request* quota regardless of how many texts are in
    it. Returns None (not a list of Nones) on any failure -- best-effort,
    semantic matching degrading to keyword-only must never break ranking."""
    if not texts:
        return None
    try:
        response = invoke_with_rotation(lambda: _call_embeddings(texts))
        return [item.embedding for item in response.data]
    except Exception:
        logger.warning("embed_batch failed, semantic matching degrades to keyword-only this round", exc_info=True)
        return None


def _call_embeddings(texts: list[str]):
    client = _build_client()
    if client is None:
        raise RuntimeError("no chatanywhere key configured")
    return client.embeddings.create(model=EMBEDDING_MODEL, input=texts)


def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)
