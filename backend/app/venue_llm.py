import json
import logging
import time

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.llm_client import get_llm, invoke_with_rotation, last_model_used, last_provider_used
from app.llm_logging import log_call

logger = logging.getLogger(__name__)


class _VenueItem(BaseModel):
    event_id: int
    venue: str | None


class _VenueBatch(BaseModel):
    results: list[_VenueItem]


def extract_venues(db: Session | None, pages: dict[int, str]) -> dict[int, str]:
    """Best-effort LLM fallback for events whose deterministic connector-
    level venue scraping (art_mate.py/expo_king.py's own regexes) found
    nothing. Those regexes are inherently fragile against free-text
    descriptions -- confirmed live: a naive "場地" (venue) label match on
    one real ExpoKing event actually matched inside "售票地點" (ticket
    SALES location, a wholly different field), and simply widening the
    regex to also catch "地點" would repeat the same mistake elsewhere.
    Reading the actual page text and asking a model "is a venue explicitly
    named here" sidesteps guessing at every site's exact markup shape.

    `pages` maps Event.id -> a short, pre-trimmed text excerpt of whatever
    page was fetched for that event (see ingest_job._venue_page_excerpt --
    NOT the raw HTML, which would blow the chatanywhere free-tier's
    4096-prompt-token cap after only 3-4 events). One call covers every
    event in `pages` regardless of count, not one call each.

    Returns {event_id: venue} only for events the model found an
    explicitly-stated venue for. Missing/failed extraction is silently
    absent from the result, same "leave it blank rather than guess" bar
    as before this fallback existed -- never asked or allowed to infer a
    venue from the event's title, category, or typical venue for that
    kind of event."""
    if not pages:
        return {}

    payload = [{"event_id": eid, "text": text} for eid, text in pages.items()]
    prompt = (
        "For each event below, extract its real-world physical venue name "
        "if -- and only if -- the accompanying text explicitly states one. "
        "Never guess or infer a venue from the event's title, category, or "
        "what kind of venue that type of event usually happens at. Some of "
        "this text is unrelated site navigation/boilerplate along with the "
        "real event details -- ignore anything that isn't clearly about "
        "this specific event. Set venue to null for any event with no "
        "explicit venue in its text.\n\n"
        f"Events:\n{json.dumps(payload, separators=(',', ':'), ensure_ascii=False)}"
    )

    start = time.perf_counter()
    try:
        result = invoke_with_rotation(
            lambda: get_llm().with_structured_output(_VenueBatch, include_raw=True).invoke(
                [{"role": "user", "content": prompt}]
            )
        )
    except Exception:
        logger.warning("venue_llm: extraction batch failed, leaving these events' venues blank", exc_info=True)
        return {}
    latency_ms = int((time.perf_counter() - start) * 1000)

    usage = getattr(result["raw"], "usage_metadata", None) or {}
    log_call(
        db,
        kind="venue_extract",
        model=last_model_used(),
        input_tokens=usage.get("input_tokens", 0),
        output_tokens=usage.get("output_tokens", 0),
        latency_ms=latency_ms,
        provider=last_provider_used(),
    )

    parsed: _VenueBatch = result["parsed"]
    known_ids = set(pages)
    # id guard: a structured field like this is exactly where a model can
    # hallucinate an id it was never given (same reasoning as ask.py's
    # referenced_event_ids validation).
    return {
        item.event_id: item.venue.strip()
        for item in parsed.results
        if item.venue and item.venue.strip() and item.event_id in known_ids
    }
