import datetime as dt

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (UniqueConstraint("source", "source_id", name="uq_event_source"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(32))
    source_id: Mapped[str] = mapped_column(String(128))
    source_url: Mapped[str] = mapped_column(String(1024), default="")

    title: Mapped[str] = mapped_column(String(512))
    title_native: Mapped[str | None] = mapped_column(String(512), nullable=True)
    native_lang: Mapped[str | None] = mapped_column(String(16), nullable=True)
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(128), default="")
    category_native: Mapped[str | None] = mapped_column(String(128), nullable=True)

    start: Mapped[dt.datetime] = mapped_column(DateTime)
    end: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)

    venue_name: Mapped[str] = mapped_column(String(256), default="")
    venue_name_native: Mapped[str | None] = mapped_column(String(256), nullable=True)
    location: Mapped[str] = mapped_column(String(256), default="")
    location_native: Mapped[str | None] = mapped_column(String(256), nullable=True)
    image_url: Mapped[str] = mapped_column(String(1024), default="")

    raw_score: Mapped[float] = mapped_column(Float, default=0.0)
    llm_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    why_match: Mapped[str] = mapped_column(Text, default="")
    # text-embedding-3-small vector (1536-dim), for semantic matching -- see
    # ranking.py's stage1_filter. Computed once per event and cached here
    # (see ingest_job.py::_ensure_embeddings), not recomputed every rerank.
    embedding: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # When llm_score was last set by an actual stage-2 LLM call, and which
    # InterestProfile.updated_at was active at the time -- lets rerank_all
    # skip re-scoring an event whose content, the profile, and recent
    # feedback are all unchanged since then, instead of re-asking the LLM
    # the same question it already answered. See ingest_job.py::_needs_rescore.
    scored_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    scored_profile_version: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime, default=dt.datetime.utcnow, onupdate=dt.datetime.utcnow
    )

    @property
    def status(self) -> str:
        now = dt.datetime.utcnow()
        end = self.end or self.start
        if now < self.start:
            # Events >90 days away are "far future" — they exist in the
            # catalog but shouldn't be branded "upcoming" (即將舉行) since
            # that reads as imminent. 90 days ≈ one quarter ahead, a
            # reasonable horizon for "you could actually plan to attend
            # this right now" vs. "it exists, check back later."
            if (self.start - now).days > 90:
                return "far_future"
            return "upcoming"
        if now <= end:
            return "ongoing"
        return "past"


class InterestProfile(Base):
    __tablename__ = "interest_profiles"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    raw_text: Mapped[str] = mapped_column(Text, default="")
    categories: Mapped[list] = mapped_column(JSON, default=list)
    keywords: Mapped[list] = mapped_column(JSON, default=list)
    # Literal terms, not LLM-parsed like categories/keywords above -- "not
    # interested in sports" doesn't need categorization, just a hard match.
    # See ranking.py::stage1_filter: any hit here sinks raw_score below
    # every non-excluded event, keeping it out of the LLM candidate pool
    # entirely rather than merely down-weighting it.
    excluded_keywords: Mapped[list] = mapped_column(JSON, default=list)
    weights: Mapped[dict] = mapped_column(JSON, default=dict)
    embedding: Mapped[list | None] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime, default=dt.datetime.utcnow, onupdate=dt.datetime.utcnow
    )


class Feedback(Base):
    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"))
    signal: Mapped[str] = mapped_column(String(8))  # "up" | "down"
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)


class SavedEvent(Base):
    """A personal shortlist, distinct from Feedback -- thumbs up/down is a
    *ranking* signal ("show me more like this"); saving is an *intent*
    signal ("I mean to go"). Conflating them would lose information: you
    might save something you're unsure matches your stated interests, or
    thumbs-up a whole genre without saving any specific instance of it."""

    __tablename__ = "saved_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), unique=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)


class IngestRun(Base):
    __tablename__ = "ingest_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    started_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    fetched: Mapped[int] = mapped_column(Integer, default=0)
    new: Mapped[int] = mapped_column(Integer, default=0)
    updated: Mapped[int] = mapped_column(Integer, default=0)
    ranked: Mapped[int] = mapped_column(Integer, default=0)


class LlmCallLog(Base):
    __tablename__ = "llm_call_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)
    kind: Mapped[str] = mapped_column(String(32))  # "interest_parse" | "rerank"
    model: Mapped[str] = mapped_column(String(64))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)


class SystemEvent(Base):
    """A unified, queryable activity/error timeline. LlmCallLog/IngestRun/
    Feedback each track their own slice, but debugging cross-cutting
    issues (e.g. "did the rerank triggered by this interest save actually
    finish, and did anything fail along the way") meant manually
    cross-referencing three or four endpoints by timestamp -- this is the
    single place that's actually meant to be read chronologically. See
    app/system_log.py::log_event. Frontend errors land here too (category
    "frontend"), via POST /api/debug/client-error -- previously invisible
    unless someone was watching the browser console live."""

    __tablename__ = "system_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)
    level: Mapped[str] = mapped_column(String(16))  # "info" | "warning" | "error"
    category: Mapped[str] = mapped_column(String(32))  # "rerank" | "ingest" | "interest" | "feedback" | "saved" | "frontend"
    message: Mapped[str] = mapped_column(Text)
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class AskLog(Base):
    """Full record of every ask -- the actual question and answer text, not
    just whether it succeeded (SystemEvent's "ask" category entries only
    note bool(answer), for the ops-level activity timeline). This is the
    durable record a retrospective or "what did I ask last time" lookup
    actually needs. A new table, not a column bolted onto SystemEvent's
    generic detail blob -- that timeline is short one-liners by convention,
    and mixing full conversational content into it would bloat every other
    category's view of it."""

    __tablename__ = "ask_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)
    query: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)  # "" when the ask failed outright
    quota_exhausted: Mapped[bool] = mapped_column(Boolean, default=False)
    # [{id, title, title_native}] for events the answer explicitly named --
    # a stable snapshot at ask-time, not a live foreign-key relationship, so
    # a history entry stays fully labeled/clickable even if an event's title
    # later changes or the event itself is deleted from the catalog.
    referenced_events: Mapped[list] = mapped_column(JSON, default=list)
