import dataclasses
import datetime as dt
import html
import json
import logging
import re
import ssl
import threading
import time
from difflib import SequenceMatcher

import httpx
import truststore
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import DEMO_MODE, INGEST_INTERVAL_HOURS
from app.connectors import urbtix
from app.db import SessionLocal
from app.models import Event, Feedback, IngestRun, InterestProfile, LlmCallLog
from app.ranking import ensure_embeddings, stage1_filter, stage2_rerank
from app.schemas import IngestSummary
from app.system_log import log_event
from app.venue_llm import extract_venues

# Conditional so this same file works unmodified in the public demo repo,
# which physically doesn't contain art_mate.py/hktdc.py/expo_king.py/
# ticketmaster.py/predicthq.py/eventbrite.py at all (see
# deploy/export-public-repo.ps1) -- their venue/data-reuse licensing is a
# different situation from urbtix's data.gov.hk open data (confirmed
# directly against data.gov.hk's own Terms of Use), and the demo
# deployment shouldn't even carry the code for scraping the others,
# regardless of whether it's actually invoked at runtime. DEMO_MODE is
# always true wherever those modules are genuinely absent, so this branch
# is never taken there.
if not DEMO_MODE:
    from app.connectors import art_mate, eventbrite, expo_king, hktdc, predicthq, ticketmaster

logger = logging.getLogger(__name__)

# Same AVG-interception workaround as every other connector making real
# HTTPS calls in this app (see art_mate.py) -- needed here too since this
# fetches whatever arbitrary domain an event's own source_url points at.
_VENUE_FETCH_SSL_CTX = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
_VENUE_FETCH_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
}

# A full-catalog rerank (see rerank_all) is now several sequential LLM
# calls and can take a minute or more -- run at most one at a time so an
# interest-save and a Refresh click seconds apart don't race each other or
# double-spend LLM calls on the same work.
_rerank_lock = threading.Lock()


@dataclasses.dataclass
class _RerankStatus:
    """In-memory only, deliberately -- a rerank in flight is tied to this
    process; a restart genuinely does kill it, so "in_progress" surviving a
    restart would be a lie, not a feature. Answers the question debugging
    this app kept coming back to: is a rerank running *right now*, and for
    how long has it been going -- previously only answerable by polling
    /api/insights and counting LlmCallLog rows by hand."""

    in_progress: bool = False
    trigger: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    last_result: str | None = None  # "ok" | "error" | "skipped" | None
    skip_reason: str | None = None  # "not_due" when last_result == "skipped"
    quota_exhausted: bool = False  # any batch this round failed on the daily LLM cap specifically
    batches_done: int = 0
    batches_total: int | None = None


_rerank_status = _RerankStatus()
_rerank_status_lock = threading.Lock()


def get_rerank_status() -> dict:
    with _rerank_status_lock:
        return dataclasses.asdict(_rerank_status)


def _set_rerank_status(**kwargs) -> None:
    with _rerank_status_lock:
        for key, value in kwargs.items():
            setattr(_rerank_status, key, value)

# urbtix and hktdc are free/keyless and always return real Hong Kong events,
# so real data is always available — mock (fake example.com demo data) is retired.
# art_mate and expo_king are deliberately last: both are supplementary
# scrapes added to close a real coverage gap (major conventions ticketed
# outside urbtix/hktdc entirely, e.g. Ani-Com & Games Hong Kong), and they
# genuinely overlap with the official sources above for some events (Book
# Fair, HKTDC's own fairs) -- processing order plus _find_cross_source_duplicate
# below means the official source's richer listing always wins that slot,
# and the new sources only fill in gaps the official ones don't cover.
# DEMO_MODE (config.py) restricts this to urbtix only -- data.gov.hk's open
# data feed is the one source with an explicit, written license for both
# commercial and non-commercial reuse (confirmed directly against
# data.gov.hk's own Terms of Use), unlike hktdc.com/art-mate.net/
# expoking.com.hk. This keeps the demo deployment's database from ever
# containing non-urbtix rows in the first place -- a physical guarantee,
# not a runtime filter someone could forget on a future endpoint.
def _build_connectors(demo_mode: bool) -> list:
    if demo_mode:
        return [urbtix]
    return [urbtix, hktdc, ticketmaster, predicthq, eventbrite, art_mate, expo_king]


CONNECTORS = _build_connectors(DEMO_MODE)

# Cross-source duplicate detection: two different connectors describing the
# same real-world event won't share a (source, source_id) key (each source
# has its own ids), so the ordinary upsert-by-key logic below can't catch
# it -- without this, "第35屆書展" from expo_king and "HKTDC Hong Kong Book
# Fair 2026" from hktdc would become two separate rows for the same fair.
# Title similarity + overlapping dates is a cheap, good-enough signal.
def _normalize_title(title: str) -> str:
    # Collapses whitespace/punctuation so e.g. "第35屆書展" and "香港書展
    # 2026" compare on their actual word content, not incidental formatting
    # differences between sources.
    return re.sub(r"[\s\W_]+", "", title, flags=re.UNICODE).lower()


def _titles_match(a: str, b: str, threshold: float = 0.6) -> bool:
    a_n, b_n = _normalize_title(a), _normalize_title(b)
    # Below this length a match is more likely coincidence than a real
    # duplicate (e.g. a short generic word both titles happen to contain)
    # -- better to risk an occasional real duplicate than wrongly drop a
    # genuinely distinct short-titled event.
    if len(a_n) < 4 or len(b_n) < 4:
        return False
    if a_n in b_n or b_n in a_n:
        return True
    return SequenceMatcher(None, a_n, b_n).ratio() >= threshold


def _dates_overlap(a_start: dt.datetime, a_end: dt.datetime | None, b_start: dt.datetime, b_end: dt.datetime | None) -> bool:
    a_end = a_end or a_start
    b_end = b_end or b_start
    return a_start <= b_end and b_start <= a_end


def _find_cross_source_duplicate(ne, existing_events: list[Event]) -> Event | None:
    # Checks every combination of title/title_native on both sides, not
    # just title-to-title -- art_mate/expo_king are Chinese-only (their
    # "title" field IS the Chinese text, no separate title_native), while
    # urbtix sets title_native only for genuinely bilingual events. Without
    # cross-checking, a Chinese-only supplementary listing could never match
    # a bilingual urbtix event even when they're obviously the same thing.
    # (Still can't bridge hktdc specifically, which never sets title_native
    # at all -- an English-only title has nothing in a Chinese-titled
    # candidate to compare against. Known limitation, not solved here.)
    ne_titles = [t for t in (ne.title, ne.title_native) if t]
    for existing in existing_events:
        if not _dates_overlap(ne.start, ne.end, existing.start, existing.end):
            continue
        existing_titles = [t for t in (existing.title, existing.title_native) if t]
        if any(_titles_match(a, b) for a in ne_titles for b in existing_titles):
            return existing
    return None

# The LLM rerank is the one costly step here (event fetch/upsert is free) --
# capped to roughly the same cadence as the scheduled ingest itself (default
# 12h = twice a day) regardless of what TRIGGERED this run, so the "Refresh"
# button (clickable by anyone on the public site, unlimited times) can't
# spend unlimited calls against the shared 200/day quota. A genuine interest
# change always reranks immediately regardless of cooldown, since that's
# exactly when a fresh rerank is the point of clicking Refresh.
_MIN_RERANK_GAP = dt.timedelta(hours=INGEST_INTERVAL_HOURS) if INGEST_INTERVAL_HOURS > 0 else dt.timedelta(hours=12)


def _should_rerank(db: Session, profile: InterestProfile) -> bool:
    last = db.scalar(
        select(LlmCallLog).where(LlmCallLog.kind == "rerank").order_by(LlmCallLog.created_at.desc())
    )
    if last is None:
        return True
    if profile.updated_at > last.created_at:
        return True  # interests changed since the last rerank -- always honor that
    return dt.datetime.utcnow() - last.created_at >= _MIN_RERANK_GAP


# Bounds LLM request count directly: only the top-N events by stage1 score
# (keyword + semantic similarity, both free) get sent to the paid stage-2
# LLM call at all. At RERANK_BATCH_SIZE=35 this is 6 batches for a full
# 200-candidate rerank (was 8 at the previous batch size of 25). Events
# ranked below this cutoff
# have their score explicitly cleared (see rerank_all) rather than left
# alone -- showing no match is honest; leaving a stale score from when they
# WERE in the top-N is the exact "match score is wrong" bug this app
# already fixed once. The tradeoff: an event stage 1 badly underscores
# (no keyword overlap, mediocre embedding similarity) never gets the LLM's
# chance to recognize it as a real match anyway.
STAGE2_MAX_CANDIDATES = 200


# New feedback forcing a re-ask of the *entire* candidate pool (see
# _needs_rescore's third condition) is deliberate -- but doing that on
# literally every single vote, with no minimum gap, meant every rerank
# trigger (scheduled, interest_save, refresh) redid the whole ~200-event,
# ~8-batch pass regardless of how recently it had just been redone.
# Confirmed live: every completed rerank in the logs showed
# skipped_fresh=0, no matter the trigger. A vote still gets reflected --
# just not faster than once per this window; a vote a few minutes after a
# full rescore waits for the next trigger past this gap rather than
# forcing an immediate repeat of the same full pass. Shorter than
# _MIN_RERANK_GAP (12h, the *scheduled* cadence) since feedback freshness
# still matters more than that, just not on every click.
_MIN_FEEDBACK_RESCORE_GAP = dt.timedelta(hours=1)


def _needs_rescore(
    ev: Event, profile_version: dt.datetime, latest_feedback_at: dt.datetime | None,
    now: dt.datetime | None = None,
) -> bool:
    """True if `ev` should actually be sent to the LLM this round, vs.
    reusing the score it already has. Re-scores if: never scored (or its
    content changed since it was -- see _fetch_and_upsert, which clears
    scored_at directly at the point a content change is detected, rather
    than this function trying to infer it from Event.updated_at: that
    column's onupdate fires on ANY column write to the row, including the
    scored_at/llm_score write itself, so comparing it against scored_at
    would almost always -- by microseconds -- look "changed" even when
    nothing about the event's content actually was); the interest profile
    changed since it was last scored; or feedback has been submitted (on
    *any* event) since it was last scored AND at least _MIN_FEEDBACK_RESCORE_GAP
    has passed since this event's own last score, since stage2_rerank's
    prompt includes a feedback summary that could then read differently.
    Conservative by design -- any of these being true forces a real
    re-ask rather than trusting a possibly-stale cache."""
    if ev.llm_score is None or ev.scored_at is None:
        return True
    if ev.scored_profile_version != profile_version:
        return True
    if latest_feedback_at is not None and latest_feedback_at > ev.scored_at:
        now = now or dt.datetime.utcnow()
        if now - ev.scored_at >= _MIN_FEEDBACK_RESCORE_GAP:
            return True
    return False


def _fetch_and_upsert(db: Session) -> tuple[int, int, int, int]:
    """Pull every connector and upsert into Event. No LLM cost -- this alone
    is always safe to run synchronously in an HTTP request. Returns
    (fetched, new, updated, duplicates_skipped) -- the last one counts
    events that matched an existing row from a *different* source by title
    + overlapping dates (see _find_cross_source_duplicate) and were
    deliberately not inserted as a second row for the same real event."""
    fetched = new = updated = duplicates = 0

    db.execute(Event.__table__.delete().where(Event.source == "mock"))

    # Loaded once and appended to as new rows are added, so an art_mate
    # event and an expo_king event describing the same fair -- both new
    # this same run -- dedupe against each other too, not just against
    # what was already in the DB before this run started.
    existing_events = list(db.scalars(select(Event)).all())

    for connector in CONNECTORS:
        for ne in connector.fetch():
            fetched += 1
            existing = db.scalar(
                select(Event).where(Event.source == ne.source, Event.source_id == ne.source_id)
            )
            if existing is None:
                duplicate = _find_cross_source_duplicate(ne, existing_events)
                if duplicate is not None:
                    duplicates += 1
                    continue
                new_event = Event(
                    source=ne.source,
                    source_id=ne.source_id,
                    source_url=ne.source_url,
                    title=ne.title,
                    title_native=ne.title_native,
                    native_lang=ne.native_lang,
                    description=ne.description,
                    category=ne.category,
                    category_native=ne.category_native,
                    start=ne.start,
                    end=ne.end,
                    venue_name=ne.venue_name,
                    venue_name_native=ne.venue_name_native,
                    location=ne.location,
                    location_native=ne.location_native,
                    image_url=ne.image_url,
                )
                db.add(new_event)
                existing_events.append(new_event)
                new += 1
            else:
                # Invalidate the cached embedding AND llm_score if the text
                # either was actually computed from changed -- otherwise
                # ensure_embeddings (ranking.py) has no way to know the
                # embedding is stale, and _needs_rescore (above) has no way
                # to know the score is stale, since both would otherwise
                # keep being treated as still-valid against text that no
                # longer exists.
                if existing.title != ne.title or existing.description != ne.description or existing.category != ne.category:
                    existing.embedding = None
                    existing.llm_score = None
                    existing.why_match = ""
                    existing.scored_at = None
                    existing.scored_profile_version = None
                existing.title = ne.title
                existing.title_native = ne.title_native
                existing.native_lang = ne.native_lang
                existing.description = ne.description
                existing.category = ne.category
                existing.category_native = ne.category_native
                existing.start = ne.start
                existing.end = ne.end
                # `or existing.venue_name`, not a plain overwrite: art_mate
                # and expo_king fetch venue via a *separate* per-event
                # request (see their connectors) that can transiently fail
                # independently of the listing fetch that succeeded -- an
                # unconditional overwrite would silently blank out an
                # already-correct venue back to "Venue TBA" on nothing more
                # than one bad network blip on a later ingest cycle. Other
                # connectors get venue_name from the same single request as
                # everything else, so an empty value from them is a
                # consistent "source says no venue," not a partial failure
                # -- keeping the old value in that case is still correct,
                # just never actually triggered for them in practice.
                existing.venue_name = ne.venue_name or existing.venue_name
                existing.venue_name_native = ne.venue_name_native or existing.venue_name_native
                existing.location = ne.location
                existing.location_native = ne.location_native
                existing.image_url = ne.image_url
                updated += 1
    db.commit()
    return fetched, new, updated, duplicates


# art_mate/expo_king: their listing pages never carry a venue field at all
# (see each connector's own comments). hktdc: venue there is a *heuristic*
# parsed from a "(VENUE)" suffix on the title string (_VENUE_RE), not a
# real structured field -- confirmed live the raw HKTDC API response has no
# venue/location field whatsoever, so a title without that suffix (common
# for far_future listings HKTDC hasn't finalized/published a venue for
# yet) genuinely has nothing better to fall back to from that API alone.
# Every OTHER connector's venue is a real structured field from the same
# feed as the rest of that event's data, so an empty value there is a
# consistent "source says no venue," not a gap worth a page fetch over.
# Capped regardless of how many qualify, since this runs unattended every
# ingest cycle.
# 8, not something bigger: confirmed live each event's trimmed excerpt (see
# _venue_page_excerpt) runs ~400-450 real tokens on its own -- a naive first
# attempt at this that also included every *past* blank-venue row (mostly
# stale art_mate events long since dropped off that connector's live
# listing, so never revisited/fixed by the connector's own retry -- see
# ingest_job's upsert not overwriting a real venue back to "", the flip
# side of the same coin) pulled in ~20 candidates and blew straight through
# chatanywhere's 4096-token cap, attempted=0. Filtering to non-past status
# below cuts real candidates down to single digits already; this caps it
# further regardless.
_VENUE_BACKFILL_SOURCES = ("art_mate", "expo_king", "hktdc")
_VENUE_BACKFILL_MAX_CANDIDATES = 8

_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")
# Precise labels first -- a real "venue:"/"location:" statement. Broader
# type hints (a well-known venue TYPE rather than an explicit label) only
# apply if no precise label exists anywhere, since they're prone to
# matching an unrelated nav-menu mention (confirmed live: "中心" alone
# matched a "參展商中心" [exhibitor centre] nav link, nowhere near the real
# venue). A React/Next.js-style embedded JSON blob (confirmed live: a real
# event page had `"location":{"en":"HKCEC",...}` sitting inside a <script>
# tag) is checked too, and checked FIRST -- it's the most reliable signal
# of all when present, an explicit structured field rather than free text.
_VENUE_JSON_HINT_RE = re.compile(r'"location"\s*:\s*(\{[^}]{0,200}\})', re.IGNORECASE)
_VENUE_LABEL_HINT_RE = re.compile("場地|地點")
_VENUE_TYPE_HINT_RE = re.compile("會展|中心|Hall|Centre|Center|Venue|AsiaWorld")
# A real "label: value" statement almost always has a colon right after the
# label (confirmed live: "地點 ： 香港會議展覽中心 1 號館"); a nav-menu item
# or unrelated category mention (confirmed live: "活動場地佈置", "婚禮場地
# 及戶外證婚") never does. Checked first regardless of document position --
# an early false positive shouldn't crowd out a real, colon-marked
# statement appearing later.
_COLON_AFTER_RE = re.compile(r"\A\s{0,3}[:：]")
_VENUE_EXCERPT_WINDOW = 90
_VENUE_EXCERPT_MAX_HINTS = 3
_VENUE_EXCERPT_MAX_CHARS = 400


def _venue_from_json_blob(html_text: str) -> str:
    """When the page embeds a real `"location":{"en":"...","tc":"...", ...}`
    blob (confirmed live: HKTDC's own event pages hydrate their frontend
    with exactly this), that's already structured, machine-parseable data
    -- no LLM judgment needed at all, and free/instant/100%-reliable versus
    a batched LLM call that can (and did, confirmed live) occasionally miss
    a real venue among several other candidates crammed into one prompt.
    Tried first, deterministically, before any event goes anywhere near the
    LLM fallback; `tc` (Chinese) preferred over `en` to match this app's
    existing native-language-first convention elsewhere (see EventCard's
    `preferNative`)."""
    m = _VENUE_JSON_HINT_RE.search(html_text)
    if not m:
        return ""
    try:
        parsed = json.loads(m.group(1))
    except (json.JSONDecodeError, ValueError):
        return ""
    if not isinstance(parsed, dict):
        return ""
    venue = parsed.get("tc") or parsed.get("en") or ""
    return venue.strip() if isinstance(venue, str) else ""


def _venue_page_excerpt(html_text: str) -> str:
    """Full page text (even after stripping tags) is far too big to hand
    an LLM per event -- confirmed 1,330 real tokens for one real event
    page, which alone is already close to a third of chatanywhere's
    4096-token free-tier cap, let alone batched across several events in
    one call. A venue mention -- when present at all -- reliably sits in a
    short cluster with the event's other logistics (date/price/ticketing),
    not spread across the page, so a window around a plausible hint keeps
    the useful signal at a fraction of the token cost.

    Deliberately searches the RAW html, not tag/script-stripped text --
    stripping <script> content up front (an earlier version of this
    function did) would have thrown away the JSON-blob case above before
    ever seeing it. Tags are only stripped from the small windows actually
    returned, not the whole document up front.

    Takes more than one hint occurrence, not just the first, and prioritizes
    colon-followed ones -- confirmed live on a real page that the first
    (and second, and third) "場地"/"地點" match was inside unrelated
    nav-menu boilerplate or an exhibitor-category description, with the
    event's own real, colon-marked venue statement only appearing later in
    the document. Handing the model a few candidate snippets, weighted
    toward the ones that actually look like a labeled statement rather
    than whichever text happened to come first, lets it pick the real one
    instead of a category link or nav item."""
    hints: list[tuple[int, int]] = [(m.start(), m.end()) for m in _VENUE_JSON_HINT_RE.finditer(html_text)]
    label_matches = [(m.start(), m.end()) for m in _VENUE_LABEL_HINT_RE.finditer(html_text)]
    colon_labels = [(s, e) for s, e in label_matches if _COLON_AFTER_RE.match(html_text[e:e + 6])]
    other_labels = [(s, e) for s, e in label_matches if (s, e) not in colon_labels]
    hints += colon_labels + other_labels
    if not hints:
        m = _VENUE_TYPE_HINT_RE.search(html_text)
        if m:
            hints.append((m.start(), m.end()))

    if not hints:
        return _clean_fragment(html_text)[:_VENUE_EXCERPT_MAX_CHARS]

    pieces = []
    total = 0
    for start, end in hints[:_VENUE_EXCERPT_MAX_HINTS]:
        window = html_text[max(0, start - _VENUE_EXCERPT_WINDOW):min(len(html_text), end + _VENUE_EXCERPT_WINDOW)]
        cleaned = _clean_fragment(window)
        if not cleaned:
            continue
        pieces.append(cleaned)
        total += len(cleaned)
        if total >= _VENUE_EXCERPT_MAX_CHARS:
            break
    return " ||| ".join(pieces)[:_VENUE_EXCERPT_MAX_CHARS]


def _clean_fragment(fragment: str) -> str:
    text = _TAG_RE.sub(" ", fragment)
    text = html.unescape(text)
    return _WHITESPACE_RE.sub(" ", text).strip()


def _backfill_missing_venues(db: Session) -> int:
    """LLM fallback for events whose own connector came up with no venue --
    art_mate/expo_king's own deterministic scraping (see venue_llm.
    extract_venues for why a plain label regex isn't reliable enough on its
    own: a real event's venue was missed because a naive match landed on
    "售票地點" [ticket SALES location, a different field] instead), or
    hktdc's title-suffix heuristic finding nothing to parse. Reuses each
    event's own `source_url` as the page to re-check -- for art_mate/
    expo_king that's either the connector's own detail page or, when the
    connector found an external booking link, the organizer's own (often
    more complete) event page; for hktdc it's that event's own dedicated
    landing page, sometimes richer than the directory listing it came
    from."""
    # Event.status is a computed Python property (models.py), not a DB
    # column -- can't filter it in SQL, so pull the (already small,
    # source-scoped) blank set and filter/cap in Python instead. A past
    # event isn't shown anywhere in the UI regardless of venue, so it's
    # not worth a page fetch + LLM tokens either.
    blank = db.scalars(
        select(Event).where(Event.source.in_(_VENUE_BACKFILL_SOURCES), Event.venue_name == "", Event.source_url != "")
    ).all()
    candidates = [ev for ev in blank if ev.status != "past"][:_VENUE_BACKFILL_MAX_CANDIDATES]
    if not candidates:
        return 0

    found_count = 0
    pages: dict[int, str] = {}
    try:
        # follow_redirects=True, unlike the other connectors -- confirmed
        # live this actually matters here: hktdc.com's own event page
        # redirected (301) to a canonical URL, and without this the fetch
        # just got a tiny redirect stub instead of the real page, silently
        # missing a real JSON venue blob that was right there on the other
        # end. The other connectors' URLs are fixed, already-canonical API
        # endpoints; this one fetches whatever arbitrary `source_url` an
        # event happens to have, which is far more likely to redirect.
        with httpx.Client(
            timeout=20, headers=_VENUE_FETCH_HEADERS, verify=_VENUE_FETCH_SSL_CTX, follow_redirects=True
        ) as client:
            for ev in candidates:
                try:
                    resp = client.get(ev.source_url)
                    resp.raise_for_status()
                except httpx.HTTPError:
                    continue
                # Deterministic parse first -- free, instant, no LLM
                # judgment (and no risk of one candidate getting lost
                # among several others in a batched call, which happened
                # live: a real HKCEC JSON blob was present but the LLM
                # still returned null for that one item in a 7-candidate
                # batch). Only what this can't resolve goes to the LLM.
                json_venue = _venue_from_json_blob(resp.text)
                if json_venue:
                    ev.venue_name = json_venue
                    found_count += 1
                else:
                    pages[ev.id] = _venue_page_excerpt(resp.text)
    except Exception:
        logger.warning("venue backfill: page-fetch pass failed, skipping this cycle", exc_info=True)
        db.commit()  # keep whatever the JSON pass already resolved before the failure
        return found_count

    if pages:
        found = extract_venues(db, pages)
        for event_id, venue in found.items():
            ev = db.get(Event, event_id)
            if ev is not None:
                ev.venue_name = venue
        found_count += len(found)

    db.commit()
    return found_count


def rerank_all(db: Session, trigger: str = "unknown") -> tuple[int, bool]:
    """Scores the top STAGE2_MAX_CANDIDATES events (by stage1_filter's cheap
    keyword+semantic ordering) against the current interest profile, skips
    re-asking the LLM about any of those that haven't actually changed since
    they were last scored (see _needs_rescore), and persists. Two different
    ways an event's score gets cleared to None -- both exist to prevent a
    stale score/rationale from a *previous* interest profile ever lingering
    (that mismatch was the original "match score is wrong" bug):
      - the LLM looked at it this round and didn't return a score, or
      - it fell out of the top-N cutoff and so wasn't sent at all.
    Events in a batch whose LLM call failed outright are left untouched
    (better to show slightly-stale data than wipe everything on one bad
    network blip). Can take a minute or more for a large catalog -- callers
    over HTTP should run this via BackgroundTasks, not inline.

    Returns (ranked_count, changed_during_run). The whole pass is several
    sequential LLM calls, so it's no longer safe to assume the profile is
    unchanged from start to finish -- if someone edits interests again while
    this is still mid-flight, `changed_during_run` is True and every score
    just written is already stale for the *new* profile (see run_rerank_job,
    which uses this to run a catch-up pass automatically).

    `trigger` is purely for observability (get_rerank_status / system
    events) -- e.g. "interest_save", "refresh", "scheduled", or a
    "..._catchup" suffix -- it has no effect on ranking behavior."""
    profile = db.get(InterestProfile, 1)
    if profile is None or not profile.raw_text:
        return 0, False
    profile_version = profile.updated_at

    _set_rerank_status(
        in_progress=True, trigger=trigger, started_at=dt.datetime.utcnow().isoformat(), finished_at=None,
        last_result=None, skip_reason=None, quota_exhausted=False, batches_done=0, batches_total=None,
    )
    log_event(db, "rerank", f"rerank started (trigger={trigger})")

    try:
        all_events = list(db.scalars(select(Event)).all())
        ensure_embeddings(db, all_events, profile)
        sorted_events = stage1_filter(all_events, profile)

        candidates = sorted_events[:STAGE2_MAX_CANDIDATES]
        candidate_ids = {ev.id for ev in candidates}
        latest_feedback_at = db.scalar(select(func.max(Feedback.created_at)))
        to_rescore = [ev for ev in candidates if _needs_rescore(ev, profile_version, latest_feedback_at)]

        scores, attempted, quota_exhausted = stage2_rerank(
            to_rescore, profile, db,
            on_batch_done=lambda done, total: _set_rerank_status(batches_done=done, batches_total=total),
        )

        scored_now = dt.datetime.utcnow()
        for ev in to_rescore:
            if ev.id in scores:
                ev.llm_score, ev.why_match = scores[ev.id]
                ev.scored_at = scored_now
                ev.scored_profile_version = profile_version
            elif ev.id in attempted:
                # An authoritative "not a match" from the LLM -- still
                # worth recording scored_at/version so this isn't re-asked
                # next round for no reason other than having no score.
                ev.llm_score = None
                ev.why_match = ""
                ev.scored_at = scored_now
                ev.scored_profile_version = profile_version
            # else: this batch's call failed outright -- leave everything
            # untouched, same as before (a transient network blip shouldn't
            # wipe a previously-good score).

        # Fell out of the top-N cutoff this round -- no longer a verified
        # score, so clear it rather than leave a stale one from when it WAS
        # in range.
        for ev in sorted_events:
            if ev.id not in candidate_ids and ev.llm_score is not None:
                ev.llm_score = None
                ev.why_match = ""
                ev.scored_at = None
                ev.scored_profile_version = None

        ranked = sum(1 for ev in candidates if ev.llm_score is not None)
        db.commit()

        db.refresh(profile)
        changed_during_run = profile.updated_at != profile_version
        log_event(
            db,
            "rerank",
            f"rerank finished (trigger={trigger}): ranked={ranked} rescored={len(to_rescore)} "
            f"skipped_fresh={len(candidates) - len(to_rescore)} attempted={len(attempted)}",
            detail={
                "trigger": trigger,
                "ranked": ranked,
                "candidates": len(candidates),
                "rescored": len(to_rescore),
                "skipped_fresh": len(candidates) - len(to_rescore),
                "attempted": len(attempted),
                "changed_during_run": changed_during_run,
                "quota_exhausted": quota_exhausted,
            },
        )
        _set_rerank_status(
            in_progress=False, finished_at=dt.datetime.utcnow().isoformat(), last_result="ok",
            quota_exhausted=quota_exhausted,
        )
        return ranked, changed_during_run
    except Exception as exc:
        log_event(db, "rerank", f"rerank failed (trigger={trigger}): {exc}", level="error", detail={"trigger": trigger})
        _set_rerank_status(in_progress=False, finished_at=dt.datetime.utcnow().isoformat(), last_result="error")
        raise


def maybe_rerank(db: Session, trigger: str = "unknown") -> tuple[int, bool]:
    """rerank_all(), but only if due (see _should_rerank) -- the throttle
    that keeps the public Refresh button and every interest save from each
    spending a full-catalog rerank's worth of LLM calls."""
    profile = db.get(InterestProfile, 1)
    if profile is None or not profile.raw_text:
        return 0, False
    if not _should_rerank(db, profile):
        logger.info("skipping rerank: last one was within %s and interests haven't changed", _MIN_RERANK_GAP)
        log_event(db, "rerank", f"rerank skipped, not due yet (trigger={trigger})", detail={"trigger": trigger})
        _set_rerank_status(
            in_progress=False, trigger=trigger, finished_at=dt.datetime.utcnow().isoformat(),
            last_result="skipped", skip_reason="not_due",
        )
        return 0, False
    return rerank_all(db, trigger=trigger)


def run_ingest(db: Session, trigger: str = "scheduled") -> IngestSummary:
    """Fetch from all connectors, upsert, and rerank if due. Used by the
    automatic scheduled job, where running rerank inline is fine (it's
    already a background thread, no HTTP timeout to worry about)."""
    started_at = dt.datetime.utcnow()
    start_perf = time.perf_counter()

    fetched, new, updated, duplicates = _fetch_and_upsert(db)
    # Only ever runs here (the scheduled background path), not the
    # synchronous /api/ingest handler -- same reasoning as rerank being
    # excluded from that endpoint (routers/ingest.py), an LLM call has no
    # place adding latency/cost to a manual "Refresh" click's HTTP response.
    _backfill_missing_venues(db)
    ranked, _ = maybe_rerank(db, trigger=trigger)

    duration_ms = int((time.perf_counter() - start_perf) * 1000)
    db.add(
        IngestRun(
            started_at=started_at,
            duration_ms=duration_ms,
            fetched=fetched,
            new=new,
            updated=updated,
            ranked=ranked,
        )
    )
    db.commit()
    log_event(
        db,
        "ingest",
        f"ingest run finished (trigger={trigger}): fetched={fetched} new={new} updated={updated} ranked={ranked} duplicates_skipped={duplicates}",
        detail={
            "trigger": trigger, "fetched": fetched, "new": new, "updated": updated, "ranked": ranked,
            "duplicates_skipped": duplicates, "duration_ms": duration_ms,
        },
    )

    return IngestSummary(fetched=fetched, new=new, updated=updated, ranked=ranked)


def run_ingest_job() -> None:
    """Entry point for the background scheduler — owns its own DB session
    since it doesn't run inside a request."""
    db = SessionLocal()
    try:
        summary = run_ingest(db, trigger="scheduled")
        logger.info("scheduled ingest: %s", summary)
    except Exception:
        logger.exception("scheduled ingest failed")
        log_event(db, "ingest", "scheduled ingest failed", level="error")
    finally:
        db.close()


_MAX_CATCHUP_PASSES = 2  # bounds a burst of rapid interest edits, doesn't chase forever


def run_rerank_job(trigger: str = "unknown") -> None:
    """Background-task entry point for HTTP-triggered reranks (interest
    save, manual Refresh) -- owns its own DB session since it runs after the
    request's own session has already closed. Non-blocking: if a rerank is
    already in progress, this one just skips rather than queuing up (the
    in-progress one's own catch-up loop, below, is what actually handles a
    same-time interest edit -- see rerank_all's changed_during_run)."""
    if not _rerank_lock.acquire(blocking=False):
        logger.info("rerank already in progress, skipping this trigger")
        db = SessionLocal()
        try:
            log_event(db, "rerank", f"trigger '{trigger}' skipped -- a rerank is already in progress", detail={"trigger": trigger})
        finally:
            db.close()
        return
    try:
        db = SessionLocal()
        try:
            ranked, changed_during_run = maybe_rerank(db, trigger=trigger)
            logger.info("background rerank: ranked=%d", ranked)
        except Exception:
            logger.exception("background rerank failed")
            log_event(db, "rerank", f"background rerank failed (trigger={trigger})", level="error", detail={"trigger": trigger})
            changed_during_run = False
        finally:
            db.close()

        # A full rerank is several sequential LLM calls and can take a
        # minute-plus -- if interests were edited again before it finished,
        # everything just scored is already stale for the newer profile.
        # Run again immediately (bypassing the throttle -- we KNOW this is
        # needed) rather than silently leaving stale scores on screen until
        # some future trigger happens to fire.
        for attempt in range(1, _MAX_CATCHUP_PASSES + 1):
            if not changed_during_run:
                break
            db = SessionLocal()
            try:
                ranked, changed_during_run = rerank_all(db, trigger=f"{trigger}_catchup")
                logger.info("background rerank (catch-up #%d): ranked=%d", attempt, ranked)
            except Exception:
                logger.exception("background rerank catch-up failed")
                log_event(db, "rerank", f"background rerank catch-up #{attempt} failed (trigger={trigger})", level="error")
                break
            finally:
                db.close()
    finally:
        _rerank_lock.release()


# Debounces run_rerank_job so a burst of rapid triggers (add a tag, save,
# notice a typo, remove it, save again, all within a few seconds) collapses
# into one rerank instead of one per click -- previously each save's
# BackgroundTasks.add_task fired independently, and if the first was still
# running when the second landed, run_rerank_job's own catch-up-pass logic
# (above) would re-run the ENTIRE batch sequence again to account for it.
# Observed live: two back-to-back interest saves produced 3 full 11-batch
# reranks (~33 LLM requests) for what was really one intended change.
#
# A plain threading.Timer, not FastAPI's BackgroundTasks -- BackgroundTasks
# is scoped to a single request and can't be reached from a *later*
# request to cancel it, which is exactly what debouncing needs.
_DEBOUNCE_SECONDS = 8.0
_debounce_timer: threading.Timer | None = None
_debounce_timer_lock = threading.Lock()


def schedule_rerank(trigger: str = "unknown") -> None:
    global _debounce_timer
    with _debounce_timer_lock:
        if _debounce_timer is not None:
            _debounce_timer.cancel()
        _debounce_timer = threading.Timer(_DEBOUNCE_SECONDS, run_rerank_job, kwargs={"trigger": trigger})
        _debounce_timer.daemon = True
        _debounce_timer.start()
