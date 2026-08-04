import logging
import re
import time

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import DEEPSEEK_API_KEY, OPENAI_API_KEY
from app.llm_client import get_llm, last_model_used, last_provider_used
from app.llm_logging import log_call

logger = logging.getLogger(__name__)


class ParsedInterests(BaseModel):
    categories: list[str]
    keywords: list[str]


def _naive_parse(raw_text: str) -> ParsedInterests:
    parts = [p.strip() for p in re.split(r"[,;\n]| and ", raw_text) if p.strip()]
    return ParsedInterests(categories=parts, keywords=parts)


def parse_interests(raw_text: str, db: Session | None = None) -> ParsedInterests:
    """Turn free-text interests into broad categories + specific keywords.

    Falls back to naive comma/word splitting when no OpenAI key is
    configured, or when the LLM call fails for any reason (rate limit,
    network, auth) — so the app degrades instead of erroring.
    """
    if not OPENAI_API_KEY and not DEEPSEEK_API_KEY:
        return _naive_parse(raw_text)

    prompt = (
        "A user described the kinds of events they're interested in, in their "
        "own words (any language). Extract:\n"
        "1. `categories` — broad event categories that fit (e.g. Music, Sports, "
        "Tech Conference, Art & Culture, Food & Drink, Comedy, Film).\n"
        "2. `keywords` — specific terms that indicate a strong match: artist or "
        "team names, genres, topics, franchises.\n\n"
        "Always respond in English, even if the user's interests are written in "
        "another language. Event listings this is matched against are keyed in "
        "English, so non-English output here would silently fail to match "
        "anything. For a public figure, group, or franchise name, this is NOT "
        "the same as literal translation or transliteration — use the actual "
        "English/stage name people would search for, from your own knowledge, "
        "not a character-by-character rendering. For example, the Cantonese "
        "name 古天樂 refers to a Hong Kong actor commonly known in English as "
        "\"Louis Koo\" — output \"Louis Koo\", not a transliteration of the "
        "characters. If you're genuinely unsure of a name's English form, keep "
        "the original as given rather than guessing wrong.\n\n"
        f"User's interests: {raw_text}"
    )

    start = time.perf_counter()
    try:
        result = get_llm().with_structured_output(ParsedInterests, include_raw=True).invoke(
            [{"role": "user", "content": prompt}]
        )
    except Exception:
        logger.warning("parse_interests: LLM call failed, falling back to naive parsing", exc_info=True)
        return _naive_parse(raw_text)
    latency_ms = int((time.perf_counter() - start) * 1000)

    usage = getattr(result["raw"], "usage_metadata", None) or {}
    log_call(
        db,
        kind="interest_parse",
        model=last_model_used(),
        input_tokens=usage.get("input_tokens", 0),
        output_tokens=usage.get("output_tokens", 0),
        latency_ms=latency_ms,
        provider=last_provider_used(),
    )
    return result["parsed"]
