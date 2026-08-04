import datetime as dt
import json
import logging
import time

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import DEEPSEEK_API_KEY, OPENAI_API_KEY
from app.llm_client import get_llm, invoke_with_rotation, is_quota_exhausted, last_model_used, last_provider_used
from app.llm_logging import log_call
from app.models import AskLog, Event, InterestProfile
from app.ranking import ensure_embeddings, stage1_filter

logger = logging.getLogger(__name__)

# Same reasoning as RERANK_BATCH_SIZE (see ranking.py): chatanywhere.tech's
# free tier hard-caps prompt tokens at 4096. Sending 40 compact event
# records plus the question and interest profile stays comfortably under
# that, without needing the full candidate pool -- a one-off question
# doesn't need to see every event, just the ones already worth showing.
#
# RE-CONFIRMED 2026-07-26 after this got bumped to 80 (same "is the cap
# still there" assumption as RERANK_BATCH_SIZE, not re-tested before being
# raised): force-tested ask()'s real payload shape with 80 real live
# events -- failed outright with the same 403 "prompt tokens ... limited
# to 4096" error. Hadn't actually triggered yet in production purely
# because the catalog only had ~29 scored events at the time, keeping the
# real candidate count under the danger threshold by chance, not because
# 80 was actually safe. Reverted to the proven value.
ASK_MAX_CANDIDATES = 40

# Reserved out of the budget above for events that haven't been through a
# stage-2 rerank yet at all. Without this, a just-ingested event is
# invisible to ask() until the next scheduled/triggered rerank (up to 12h
# away) purely because `scored` (below) is non-empty once *any* event has
# a score -- a real gap found live: a brand-new connector's event asked
# about immediately after ingest got "no such event" even though it was
# already in the catalog. Small on purpose: these are ranked by stage1
# (keyword+semantic) only, cheaper/less precise than a real LLM score.
_ASK_UNSCORED_SLOTS = 10


class _AskResult(BaseModel):
    answer: str
    # event_ids the answer explicitly names -- lets the frontend render a
    # real clickable link to that event's own card instead of the answer
    # being a dead end of plain prose. Validated against the actual
    # candidate set below rather than trusted outright, since a structured
    # field like this is exactly where a model can hallucinate an id that
    # was never in what it was shown.
    referenced_event_ids: list[int] = []


def _log_ask(db: Session, query: str, answer: str, quota_exhausted: bool, referenced_events: list[dict] | None = None) -> None:
    db.add(AskLog(query=query, answer=answer, quota_exhausted=quota_exhausted, referenced_events=referenced_events or []))
    db.commit()


def ask(db: Session, query: str) -> tuple[str, bool, list[dict]]:
    """One real-time LLM call answering a free-text question against the
    user's current event catalog. Returns (answer, quota_exhausted,
    referenced_events) -- `answer` is "" on any failure, with
    `quota_exhausted` distinguishing "today's shared quota ran out" from a
    genuine error so the caller can show the right message.
    `referenced_events` is a list of {id, title, title_native} for events
    the answer explicitly named, in the order the model listed them --
    lets the caller render actual links to those events' cards. Every
    attempt is persisted to AskLog regardless of outcome, for later
    lookup/retrospectives (see GET /api/ask/history).

    Deliberately reuses whatever's already scored (Event.llm_score) rather
    than re-running stage1/stage2 for this one question -- that's a
    several-batch, several-request pipeline; this is meant to be one cheap
    call answering "what about this weekend" without paying for a full
    rerank just to answer it. Falls back entirely to stage1_filter's
    ordering when nothing has been scored yet at all (e.g. interests were
    never saved); otherwise still reserves a few slots (see
    _ASK_UNSCORED_SLOTS) for stage1-ranked not-yet-scored events, so a
    just-ingested event isn't invisible until the next rerank happens to
    run.

    Candidates exclude past events before ranking/truncating -- previously
    a past event that scored highly back when it was upcoming/ongoing (its
    score is never cleared just because time passed) could still land in
    the top ASK_MAX_CANDIDATES, and got recommended for a forward-looking
    question like "what's on this weekend" since nothing here ever told the
    model today's actual date to check that against."""
    if not OPENAI_API_KEY and not DEEPSEEK_API_KEY:
        _log_ask(db, query, "", False)
        return "", False, []

    profile = db.get(InterestProfile, 1)
    if profile is None:
        profile = InterestProfile(id=1, raw_text="", categories=[], keywords=[], excluded_keywords=[], weights={})

    all_events = [ev for ev in db.scalars(select(Event)).all() if ev.status != "past"]
    scored = [ev for ev in all_events if ev.llm_score is not None]
    unscored = [ev for ev in all_events if ev.llm_score is None]
    if scored:
        scored_budget = ASK_MAX_CANDIDATES - (_ASK_UNSCORED_SLOTS if unscored else 0)
        candidates = sorted(scored, key=lambda ev: ev.llm_score, reverse=True)[:scored_budget]
        if unscored:
            # stage1_filter's keyword matching needs a literal overlap
            # between an event's (often single-language) text and the
            # profile's own keyword language -- a Chinese-only-titled
            # event against English interest keywords scores 0 there no
            # matter how relevant it is. ensure_embeddings is what gives
            # semantic (cross-lingual-ish) matching a chance instead; a
            # never-reranked event otherwise has no embedding yet either,
            # so it would score 0 on *both* signals and never earn its
            # reserved slot. Only computes for events that don't already
            # have one cached (see ensure_embeddings), so repeat asks
            # against the same catalog are cheap.
            ensure_embeddings(db, unscored, profile)
            candidates += stage1_filter(unscored, profile)[:_ASK_UNSCORED_SLOTS]
    else:
        ensure_embeddings(db, all_events, profile)
        candidates = stage1_filter(all_events, profile)[:ASK_MAX_CANDIDATES]
    candidates_by_id = {ev.id: ev for ev in candidates}

    payload = [
        {
            "id": ev.id,
            "title": ev.title,
            "category": ev.category,
            "status": ev.status,  # "upcoming" | "ongoing" -- past already excluded above
            "start": ev.start.date().isoformat(),
            "end": ev.end.date().isoformat() if ev.end else None,
            "venue": ev.venue_name,
            "match_score": ev.llm_score,
        }
        for ev in candidates
    ]

    today = dt.datetime.utcnow().date()
    prompt = (
        f"Today's date is {today.isoformat()} ({today.strftime('%A')}).\n"
        f"The user's stated interests: \"{profile.raw_text}\"\n"
        f"The user is asking: \"{query}\"\n\n"
        "Their current candidate events (already ranked by fit to their stated "
        "interests; match_score is 0-100, or null if not yet scored; status is "
        "\"upcoming\" or \"ongoing\" -- events that have already ended are not "
        "included at all):\n"
        f"{json.dumps(payload, separators=(',', ':'))}\n\n"
        "Answer conversationally in 2-4 sentences, in the SAME language they "
        "asked in (translate/transliterate event titles only if it reads "
        "naturally, don't force it). Use today's date above to reason about "
        "relative time references (\"this weekend\", \"next week\", etc.) -- "
        "don't recommend anything whose dates don't actually fit what they "
        "asked for. Reference specific events by name when relevant. If "
        "nothing in the list actually satisfies their question, say so "
        "plainly and explain concretely why (wrong dates, not actually "
        "free/outdoor/whatever they asked for) rather than force-fitting a "
        "weak match just to seem helpful. Also return the event_id of every "
        "event you explicitly named in your answer, in referenced_event_ids "
        "(empty list if you didn't name any)."
    )

    start = time.perf_counter()
    try:
        result = invoke_with_rotation(
            lambda: get_llm().with_structured_output(_AskResult, include_raw=True).invoke(
                [{"role": "user", "content": prompt}]
            )
        )
    except Exception as exc:
        quota_exhausted = is_quota_exhausted(exc)
        logger.warning("ask: LLM call failed", exc_info=True)
        _log_ask(db, query, "", quota_exhausted)
        return "", quota_exhausted, []
    latency_ms = int((time.perf_counter() - start) * 1000)

    usage = getattr(result["raw"], "usage_metadata", None) or {}
    log_call(
        db,
        kind="ask",
        model=last_model_used(),
        input_tokens=usage.get("input_tokens", 0),
        output_tokens=usage.get("output_tokens", 0),
        latency_ms=latency_ms,
        provider=last_provider_used(),
    )
    parsed = result["parsed"]
    answer = parsed.answer
    # Only ids actually in the candidate set are trustworthy -- see _AskResult.
    referenced_events = [
        {"id": ev.id, "title": ev.title, "title_native": ev.title_native}
        for eid in parsed.referenced_event_ids
        if (ev := candidates_by_id.get(eid)) is not None
    ]
    _log_ask(db, query, answer, False, referenced_events)
    return answer, False, referenced_events
