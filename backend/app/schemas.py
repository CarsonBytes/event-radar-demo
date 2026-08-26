import datetime as dt

from pydantic import BaseModel


class EventOut(BaseModel):
    id: int
    source: str
    source_url: str
    title: str
    title_native: str | None
    native_lang: str | None
    description: str
    category: str
    category_native: str | None
    start: dt.datetime
    end: dt.datetime | None
    venue_name: str
    venue_name_native: str | None
    location: str
    location_native: str | None
    image_url: str
    raw_score: float
    llm_score: float | None
    why_match: str
    status: str
    # When this row first entered the catalog -- powers the frontend's
    # "new since your last visit" badge (client-side, localStorage-based).
    created_at: dt.datetime
    user_signal: str | None = None
    saved: bool = False

    model_config = {"from_attributes": True}


class InterestProfileOut(BaseModel):
    raw_text: str
    categories: list[str]
    keywords: list[str]
    excluded_keywords: list[str] = []
    weights: dict[str, float]
    updated_at: dt.datetime

    model_config = {"from_attributes": True}


class InterestProfileIn(BaseModel):
    raw_text: str
    excluded_keywords: list[str] = []


class FeedbackIn(BaseModel):
    event_id: int
    signal: str  # "up" | "down" | "none" (un-vote)


class AskIn(BaseModel):
    query: str


class AskReferencedEvent(BaseModel):
    id: int
    title: str
    title_native: str | None = None


class AskOut(BaseModel):
    answer: str  # "" on failure -- see quota_exhausted for why
    quota_exhausted: bool = False
    referenced_events: list[AskReferencedEvent] = []


class AskHistoryItem(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    created_at: dt.datetime
    query: str
    answer: str  # "" if that attempt failed outright
    quota_exhausted: bool
    referenced_events: list[AskReferencedEvent] = []


class AskHistoryOut(BaseModel):
    items: list[AskHistoryItem]


class IngestSummary(BaseModel):
    fetched: int
    new: int
    updated: int
    ranked: int


class IngestRunOut(BaseModel):
    started_at: dt.datetime
    duration_ms: int
    fetched: int
    new: int
    updated: int
    ranked: int

    model_config = {"from_attributes": True}


class LlmCallOut(BaseModel):
    created_at: dt.datetime
    kind: str
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    cost_usd: float

    model_config = {"from_attributes": True}


class PrecisionStat(BaseModel):
    label: str
    up: int
    down: int
    rate: float | None  # None when there's no feedback yet


class InsightsOut(BaseModel):
    recent_ingest_runs: list[IngestRunOut]
    recent_llm_calls: list[LlmCallOut]
    llm_total_calls: int
    llm_total_cost_usd: float
    llm_avg_latency_ms: float
    llm_calls_today: int
    llm_cost_today_usd: float
    llm_daily_cap: int | None
    shared_calls_today: int
    shared_cost_today_usd: float
    shared_calls_by_project: dict[str, int]
    overall_precision: PrecisionStat
    precision_by_category: list[PrecisionStat]
