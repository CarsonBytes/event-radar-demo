import json
import logging
import time
from typing import Callable

from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import DEEPSEEK_API_KEY, OPENAI_API_KEY
from app.embeddings import cosine_similarity, embed_batch
from app.llm_client import get_llm, invoke_with_rotation, is_quota_exhausted, last_model_used, last_provider_used
from app.llm_logging import log_call
from app.models import Event, Feedback, InterestProfile
from app.system_log import log_event
from app.text_match import term_matches

logger = logging.getLogger(__name__)

# Cosine similarity for genuinely-related-but-not-keyword-matching text
# with text-embedding-3-small typically lands ~0.15-0.45, not the 0.8+
# people expect from "similarity" -- this scale keeps a real match
# (~0.3-0.5) comparably influential to one literal keyword hit (weight
# 1.0-1.15 by default), without letting a merely-topically-adjacent event
# outscore several genuine keyword matches. A starting heuristic, not a
# tuned constant -- there's no labeled data yet to calibrate it against.
SEMANTIC_WEIGHT = 3.0

# Conservative, same reasoning as RERANK_BATCH_SIZE: chatanywhere.tech's
# free tier hard-caps request *and* prompt-token size, and this hasn't been
# measured separately for the embeddings endpoint the way chat completions
# was -- staying well under the chat-completions ceiling (25 events @
# ~2900 tokens) rather than assuming a shorter embed-only payload gets more
# headroom.
EMBED_BATCH_SIZE = 40
EMBED_TEXT_TRUNCATE = 300


def _embed_text(ev: Event) -> str:
    return f"{ev.title} {ev.description[:EMBED_TEXT_TRUNCATE]} {ev.category}"


def ensure_embeddings(db: Session, events: list[Event], profile: InterestProfile) -> None:
    """Backfills .embedding for any event that doesn't have one yet (new
    since the last rerank -- existing ones are cached, never recomputed)
    plus the profile's own embedding (recomputed every call: interests
    change far less often than reranks run, and it's one cheap extra
    request, not worth trying to cache-and-invalidate). Best-effort --
    embed_batch() returning None just means this round scores on keyword
    overlap alone, same as before this existed."""
    pending = [ev for ev in events if ev.embedding is None]
    for i in range(0, len(pending), EMBED_BATCH_SIZE):
        batch = pending[i : i + EMBED_BATCH_SIZE]
        vectors = embed_batch([_embed_text(ev) for ev in batch])
        if vectors is None:
            continue
        for ev, vec in zip(batch, vectors):
            ev.embedding = vec
    if pending:
        db.commit()

    if profile.raw_text.strip():
        profile_vectors = embed_batch([profile.raw_text])
        if profile_vectors:
            profile.embedding = profile_vectors[0]
            db.commit()


# Sinks an excluded event's raw_score below every non-excluded event
# (which score 0 or positive), so it falls out of STAGE2_MAX_CANDIDATES
# entirely rather than merely being deprioritized -- "not interested in
# sports" should mean sports events stop competing for LLM attention, not
# just rank slightly lower.
EXCLUDED_SCORE = -1000.0


def stage1_filter(events: list[Event], profile: InterestProfile, limit: int | None = None) -> list[Event]:
    """Keyword/category overlap plus a semantic-similarity boost (see
    ensure_embeddings/SEMANTIC_WEIGHT above -- catches real matches that
    share no literal words, e.g. "jazz" vs. "improvised music night"),
    sorted highest-first. This is also the cutoff that actually bounds LLM
    cost now: ingest_job.rerank_all only sends the top STAGE2_MAX_CANDIDATES
    of this ordering to stage 2, on the assumption that an event scoring
    ~0 here (no keyword overlap, no semantic similarity at all) is not
    worth an LLM call to double-check. `limit` here is a separate, optional
    hard cutoff for callers that want a smaller slice than that."""
    terms = {t.lower() for t in [*profile.categories, *profile.keywords] if t.strip()}
    excluded = {t.lower() for t in (profile.excluded_keywords or []) if t.strip()}
    weights = profile.weights or {}

    for ev in events:
        haystack = f"{ev.title} {ev.description} {ev.category}"
        if any(term_matches(term, haystack) for term in excluded):
            ev.raw_score = EXCLUDED_SCORE
            continue
        keyword_score = sum(weights.get(term, 1.0) for term in terms if term_matches(term, haystack))
        semantic_score = 0.0
        if ev.embedding and profile.embedding:
            semantic_score = cosine_similarity(ev.embedding, profile.embedding) * SEMANTIC_WEIGHT
        ev.raw_score = keyword_score + semantic_score

    events.sort(key=lambda e: e.raw_score, reverse=True)
    return events[:limit] if limit is not None else events


class _RankingItem(BaseModel):
    event_id: int
    llm_score: int
    why_match: str


class _RankingResult(BaseModel):
    rankings: list[_RankingItem]


# A top-N shortlist (see STAGE2_MAX_CANDIDATES in ingest_job.py) is back,
# after briefly scoring every event -- that full-coverage version existed
# to fix "match score is wrong": events outside the old top-25 cut never
# got scored, and worse, kept whatever score a *previous* interest profile
# had left on them since nothing ever cleared it. The fix that matters is
# clearing the score for anything outside the shortlist (rerank_all does
# this explicitly), not scoring literally everything -- an event stage 1
# scores ~0 (no keyword overlap, no semantic similarity at all) isn't worth
# an LLM call to double-check. Batched instead of one giant call so the
# payload/output stays a reasonable size per request.
#
# 25, not something bigger: chatanywhere.tech's FREE tier hard-caps prompt
# tokens at 4096 regardless of the underlying model's real context window --
# confirmed live 2026-07-18 (a batch of 50 events, ~6800 prompt tokens, got a
# 403 PermissionDeniedError: "prompt tokens for free accounts is limited to
# 4096"). Measured cost is ~380 fixed + ~100/event, so 25 events (~2900
# tokens) lands with real margin; this is also the exact size the original
# (pre-full-coverage) code already used, which is presumably why it never
# hit this ceiling before.
#
# RE-CONFIRMED 2026-07-26 after this got bumped to 200 (a "single-batch
# rerank" attempt, presumably on an assumption the cap had been lifted,
# without re-testing against a real call first -- the comment above was
# even left describing the exact failure this reintroduced). Tested the
# real stage2_rerank() directly against 200 real live events: the whole
# batch failed outright with the identical 403 "prompt tokens ... limited
# to 4096" error, attempted=0/scores=0 -- the *entire* candidate pool would
# silently go unscored the next time a rerank actually reached this size.
# The provider's limit has not changed; reverted back to the proven value.
#
# RAISED 25 -> 35 on 2026-07-28 after binary-searching the real boundary
# live (single-batch calls against real production candidates, no mocking):
# 35 events = 3697 real prompt tokens (succeeded), 38 = 3950 (succeeded),
# 40 = 4136 (succeeded -- oddly *above* the documented 4096, so whatever
# chatanywhere's internal check actually counts isn't exactly this
# response's usage.prompt_tokens), 45 failed outright with the same 403.
# The real edge sits somewhere in 40-45, with no visible slack beyond
# that -- 40 is too close to risk in production, since event descriptions
# vary in length and a wordier batch could tip over unpredictably. 35
# keeps ~400 tokens (~10%) of real margin, cutting a full 200-candidate
# rerank from 8 batches to 6.
RERANK_BATCH_SIZE = 35


def _batches(items: list[Event], size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]


# Previously, feedback only nudged a crude keyword-overlap weight
# (apply_feedback, stage1's raw_score) -- the LLM rerank never saw it, so
# your actual votes never changed what the model itself judged as a good
# fit. A short few-shot summary of real recent votes, computed once and
# reused across every batch in a rerank pass (feedback doesn't change
# mid-pass, no need to requery it per-batch).
_FEEDBACK_EXAMPLES_PER_SIGN = 8
_FEEDBACK_LOOKBACK_ROWS = 60  # over-fetch to survive de-duping repeat votes on the same event


def _feedback_context(db: Session | None) -> str:
    if db is None:
        return ""
    rows = db.execute(
        select(Feedback.event_id, Feedback.signal, Event.title)
        .join(Event, Feedback.event_id == Event.id)
        .order_by(Feedback.created_at.desc())
        .limit(_FEEDBACK_LOOKBACK_ROWS)
    ).all()

    latest_signal: dict[int, str] = {}
    titles: dict[int, str] = {}
    order: list[int] = []
    for event_id, signal, title in rows:
        if event_id in latest_signal:
            continue  # already saw this event's most recent vote (rows are newest-first)
        latest_signal[event_id] = signal
        titles[event_id] = title
        order.append(event_id)

    liked = [titles[eid] for eid in order if latest_signal[eid] == "up"][:_FEEDBACK_EXAMPLES_PER_SIGN]
    disliked = [titles[eid] for eid in order if latest_signal[eid] == "down"][:_FEEDBACK_EXAMPLES_PER_SIGN]
    if not liked and not disliked:
        return ""

    parts = ["\nThis user's actual past feedback on other events (weight this as real signal about their taste, not just the stated interests above):"]
    if liked:
        parts.append("Liked (👍): " + "; ".join(liked))
    if disliked:
        parts.append("Disliked (👎): " + "; ".join(disliked))
    return "\n".join(parts)


def stage2_rerank(
    candidates: list[Event],
    profile: InterestProfile,
    db: Session | None = None,
    on_batch_done: Callable[[int, int], None] | None = None,
) -> tuple[dict[int, tuple[float, str]], set[int], bool]:
    """The LLM scores every candidate and writes a one-sentence match
    explanation, in batches of RERANK_BATCH_SIZE.

    Returns (scores, attempted, quota_exhausted): `attempted` is every
    event_id from a batch whose LLM call actually completed (even if that
    batch's response omitted some ids) -- the caller uses this to
    distinguish "the LLM looked at this and it's not in `scores`" (clear
    the score) from "this batch's call failed entirely" (leave whatever
    score was already there alone, rather than wiping it on a transient
    failure). `quota_exhausted` is True if any batch failed specifically
    because the shared LLM key's daily request cap was hit -- surfaced so
    callers (and eventually the UI) can tell "the app is broken" apart from
    "today's free quota ran out, try again tomorrow."

    `on_batch_done(completed_count, total_count)`, if given, fires after
    every batch (success or failure) -- lets a caller show live progress
    without this function needing to know anything about how that's
    displayed."""
    if not OPENAI_API_KEY and not DEEPSEEK_API_KEY:
        return {}, set(), False

    scores: dict[int, tuple[float, str]] = {}
    attempted: set[int] = set()
    quota_exhausted = False
    feedback_context = _feedback_context(db)
    batches = list(_batches(candidates, RERANK_BATCH_SIZE))
    total_batches = len(batches)

    for batch_num, batch in enumerate(batches, start=1):
        batch_ids = {ev.id for ev in batch}
        payload = [
            {
                "event_id": ev.id,
                "title": ev.title,
                "category": ev.category,
                "description": ev.description[:220],
                "start": ev.start.isoformat(),
                "venue": ev.venue_name,
                "location": ev.location,
            }
            for ev in batch
        ]

        prompt = (
            "The user's stated interests: "
            f"\"{profile.raw_text}\"\n"
            f"Parsed categories: {profile.categories}\n"
            f"Parsed keywords: {profile.keywords}\n"
            + (f"Explicitly NOT interested in: {profile.excluded_keywords}\n" if profile.excluded_keywords else "")
            + f"{feedback_context}\n\n"
            "Score how well each of the following events matches this specific "
            "user's interests, from 0 (no fit) to 100 (excellent fit). Treat every "
            "interest listed above as equally important -- it's a flat, unordered "
            "list, not ranked by priority. Don't invent an emphasis or priority "
            "between listed interests that isn't actually stated or evidenced by "
            "their real feedback above; if an event clearly matches any ONE of "
            "their explicitly named interests (a specific artist, team, or "
            "keyword they listed), that alone earns a high score regardless of "
            "how many of their OTHER interests it also happens to match. An event "
            "matching something they're explicitly NOT interested in should score "
            "low regardless of any other overlap. Write a "
            "one-sentence, specific reason referencing the event and the user's "
            "stated interest — not a generic blurb, and not vague even for a "
            "low/zero score (say concretely why it doesn't fit, without "
            "fabricating a reason that isn't actually grounded in the interests "
            "or feedback given above). Return a ranking for EVERY event_id "
            "given, including clear non-matches.\n\n"
            # Compact, not indent=2 -- the model doesn't need pretty-printing
            # to parse structured input, and the extra whitespace is pure
            # wasted input tokens (measured ~17% smaller payload compact).
            f"Events:\n{json.dumps(payload, separators=(',', ':'))}"
        )

        start = time.perf_counter()
        try:
            result = invoke_with_rotation(
                lambda: get_llm().with_structured_output(_RankingResult, include_raw=True).invoke(
                    [{"role": "user", "content": prompt}]
                )
            )
        except Exception as exc:
            batch_quota_exhausted = is_quota_exhausted(exc)
            quota_exhausted = quota_exhausted or batch_quota_exhausted
            logger.warning(
                "stage2_rerank: batch LLM call failed, leaving these %d events' scores untouched",
                len(batch), exc_info=True,
            )
            log_event(
                db,
                "rerank",
                f"batch {batch_num}/{total_batches} failed: {exc}",
                level="error",
                detail={"error_type": type(exc).__name__, "quota_exhausted": batch_quota_exhausted},
            )
            if on_batch_done:
                on_batch_done(batch_num, total_batches)
            continue
        latency_ms = int((time.perf_counter() - start) * 1000)
        attempted |= batch_ids

        usage = getattr(result["raw"], "usage_metadata", None) or {}
        log_call(
            db,
            kind="rerank",
            model=last_model_used(),
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            latency_ms=latency_ms,
            provider=last_provider_used(),
        )
        for item in result["parsed"].rankings:
            scores[item.event_id] = (float(item.llm_score), item.why_match)

        if on_batch_done:
            on_batch_done(batch_num, total_batches)

    return scores, attempted, quota_exhausted


def apply_feedback(profile: InterestProfile, event: Event, signal: str) -> None:
    """Nudge category/keyword weights based on a thumbs up/down on one event."""
    delta = 0.15 if signal == "up" else -0.15
    terms = {event.category.lower(), *[w.lower() for w in event.title.split() if len(w) > 3]}

    weights = dict(profile.weights or {})
    for term in terms:
        if not term:
            continue
        weights[term] = max(0.1, min(3.0, weights.get(term, 1.0) + delta))
    profile.weights = weights


def persist_feedback_weights(db: Session, profile_id: int, weights: dict) -> None:
    """Writes `weights` via a raw UPDATE, deliberately bypassing the ORM's
    onupdate=utcnow on InterestProfile.updated_at. That column is what
    ingest_job.py's _needs_rescore compares as "did the user's stated
    interests change" (scored_profile_version) -- a feedback-driven weight
    nudge isn't that; "feedback changed" is already tracked correctly and
    separately via the Feedback table's own timestamp. Writing this through
    the ORM as a normal attribute assignment (`profile.weights = weights`)
    would otherwise silently re-bump updated_at on every single vote,
    invalidating the entire scored candidate pool's cache for the next
    rerank -- confirmed live (a single vote moved `updated_at`
    immediately), the same onupdate-fires-on-any-write trap already found
    and fixed for Event.updated_at. Caller is expected to compute `weights`
    via apply_feedback() against a transient (never db.add'ed) copy of the
    profile first, not the session-tracked object, so nothing queues up an
    ORM-level write that would undo this at the next commit().

    Core-level update() still evaluates a column's onupdate default for any
    column not explicitly named in .values() -- so weights=weights alone
    isn't enough, updated_at must be pinned to its own current value to
    suppress the default."""
    db.execute(
        update(InterestProfile)
        .where(InterestProfile.id == profile_id)
        .values(weights=weights, updated_at=InterestProfile.updated_at)
    )
