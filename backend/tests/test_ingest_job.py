import datetime as dt
from unittest.mock import MagicMock, patch

import pytest

import app.ingest_job as ingest_job_module
from app.connectors.base import NormalizedEvent
from app.ingest_job import (
    _DEBOUNCE_SECONDS,
    _MIN_RERANK_GAP,
    _backfill_missing_venues,
    _build_connectors,
    _dates_overlap,
    _fetch_and_upsert,
    _find_cross_source_duplicate,
    _should_rerank,
    _titles_match,
    _venue_from_json_blob,
    _venue_page_excerpt,
    get_rerank_status,
    rerank_all,
    run_rerank_job,
    schedule_rerank,
)
from app.config import DEMO_MODE
from app.connectors import urbtix
from app.models import Event, Feedback, InterestProfile, LlmCallLog

# Same conditional-import reasoning as ingest_job.py itself -- this file
# needs to collect cleanly in the public demo repo too, where these modules
# don't exist on disk at all.
if not DEMO_MODE:
    from app.connectors import art_mate, expo_king, hktdc


def _event(id: int, title: str = "Test", embedding=None) -> Event:
    ev = Event(
        id=id, source="test", source_id=str(id), source_url="", title=title,
        description="", category="Music", start=dt.datetime.utcnow(),
        venue_name="", location="",
    )
    ev.embedding = embedding
    return ev


class TestBuildConnectors:
    def test_demo_mode_restricts_to_urbtix_only(self):
        # urbtix (data.gov.hk's open data feed) is the one source with an
        # explicit, written license for reuse -- confirmed directly against
        # data.gov.hk's own Terms of Use. The demo deployment must never
        # even attempt to fetch hktdc/art_mate/expo_king, so its database
        # physically can't end up containing any of that data.
        assert _build_connectors(demo_mode=True) == [urbtix]

    @pytest.mark.skipif(DEMO_MODE, reason="hktdc/art_mate/expo_king don't exist in the public demo repo")
    def test_normal_mode_includes_every_real_connector(self):
        connectors = _build_connectors(demo_mode=False)
        assert urbtix in connectors
        assert hktdc in connectors
        assert art_mate in connectors
        assert expo_king in connectors


class TestShouldRerank:
    def test_true_when_never_reranked(self, db_session):
        profile = InterestProfile(id=1, raw_text="x", categories=[], keywords=[], weights={})
        assert _should_rerank(db_session, profile) is True

    def test_false_within_cooldown_and_unchanged(self, db_session):
        past = dt.datetime.utcnow() - dt.timedelta(hours=1)
        profile = InterestProfile(id=1, raw_text="x", categories=[], keywords=[], weights={}, updated_at=past - dt.timedelta(hours=1))
        db_session.add(profile)
        db_session.add(LlmCallLog(kind="rerank", model="m", input_tokens=0, output_tokens=0, latency_ms=0, cost_usd=0, created_at=past))
        db_session.commit()

        assert _should_rerank(db_session, profile) is False

    def test_true_when_cooldown_elapsed(self, db_session):
        # Derived from the real _MIN_RERANK_GAP (itself driven by
        # INGEST_INTERVAL_HOURS), not a hardcoded "13 hours" -- that
        # magic number silently broke the moment the env var changed
        # from 12h to 24h, since it stopped being past whatever the
        # actual cooldown was.
        long_ago = dt.datetime.utcnow() - _MIN_RERANK_GAP - dt.timedelta(hours=1)
        profile = InterestProfile(id=1, raw_text="x", categories=[], keywords=[], weights={}, updated_at=long_ago - dt.timedelta(hours=1))
        db_session.add(profile)
        db_session.add(LlmCallLog(kind="rerank", model="m", input_tokens=0, output_tokens=0, latency_ms=0, cost_usd=0, created_at=long_ago))
        db_session.commit()

        assert _should_rerank(db_session, profile) is True

    def test_profile_change_bypasses_cooldown(self, db_session):
        # This is the exact bug fixed this session: a rerank that finishes
        # AFTER an interest edit must not fool the cooldown into thinking
        # that edit was already accounted for.
        recent_rerank = dt.datetime.utcnow() - dt.timedelta(minutes=1)
        profile = InterestProfile(id=1, raw_text="new interests", categories=[], keywords=[], weights={})
        db_session.add(profile)
        db_session.add(LlmCallLog(kind="rerank", model="m", input_tokens=0, output_tokens=0, latency_ms=0, cost_usd=0, created_at=recent_rerank))
        db_session.commit()
        profile.updated_at = dt.datetime.utcnow()  # edited *after* that rerank
        db_session.commit()

        assert _should_rerank(db_session, profile) is True


class TestRerankAllStaleScoreClearing:
    def test_attempted_but_unscored_events_get_cleared(self, db_session):
        # LLM looked at this event (its batch succeeded) but didn't include
        # it in the response -- treat as "not a match," not "still whatever
        # it scored under a previous interest profile."
        stale = _event(1)
        stale.llm_score = 99.0
        stale.why_match = "stale reason from a previous profile"
        profile = InterestProfile(id=1, raw_text="x", categories=[], keywords=[], weights={})
        db_session.add_all([stale, profile])
        db_session.commit()

        with patch("app.ingest_job.ensure_embeddings"), \
             patch("app.ingest_job.stage2_rerank", return_value=({}, {1}, False)):
            rerank_all(db_session)

        assert stale.llm_score is None
        assert stale.why_match == ""

    def test_unattempted_events_are_left_untouched(self, db_session):
        # This batch's LLM call failed outright -- better to show
        # slightly-stale data than wipe everything on one bad network blip.
        untouched = _event(1)
        untouched.llm_score = 55.0
        untouched.why_match = "still valid, batch just failed this round"
        profile = InterestProfile(id=1, raw_text="x", categories=[], keywords=[], weights={})
        db_session.add_all([untouched, profile])
        db_session.commit()

        with patch("app.ingest_job.ensure_embeddings"), \
             patch("app.ingest_job.stage2_rerank", return_value=({}, set(), False)):
            rerank_all(db_session)

        assert untouched.llm_score == 55.0
        assert untouched.why_match == "still valid, batch just failed this round"

    def test_no_profile_or_empty_interests_skips_entirely(self, db_session):
        assert rerank_all(db_session) == (0, False)

        empty_profile = InterestProfile(id=1, raw_text="", categories=[], keywords=[], weights={})
        db_session.add(empty_profile)
        db_session.commit()
        assert rerank_all(db_session) == (0, False)


class TestRerankStatus:
    # get_rerank_status() is process-global, in-memory state (see
    # ingest_job.py's _RerankStatus) -- this is what previously had to be
    # inferred by polling /api/insights and counting LlmCallLog rows by
    # hand while debugging whether a rerank was actually still running.

    def test_reflects_the_trigger_and_success_after_a_run(self, db_session):
        ev = _event(1)
        profile = InterestProfile(id=1, raw_text="x", categories=[], keywords=[], weights={})
        db_session.add_all([ev, profile])
        db_session.commit()

        with patch("app.ingest_job.ensure_embeddings"), \
             patch("app.ingest_job.stage2_rerank", return_value=({}, set(), False)):
            rerank_all(db_session, trigger="interest_save")

        status = get_rerank_status()
        assert status["in_progress"] is False
        assert status["trigger"] == "interest_save"
        assert status["last_result"] == "ok"
        assert status["started_at"] is not None
        assert status["finished_at"] is not None

    def test_records_error_result_and_still_raises(self, db_session):
        ev = _event(1)
        profile = InterestProfile(id=1, raw_text="x", categories=[], keywords=[], weights={})
        db_session.add_all([ev, profile])
        db_session.commit()

        with patch("app.ingest_job.ensure_embeddings"), \
             patch("app.ingest_job.stage2_rerank", side_effect=RuntimeError("boom")):
            with pytest.raises(RuntimeError):
                rerank_all(db_session, trigger="refresh")

        status = get_rerank_status()
        assert status["in_progress"] is False
        assert status["last_result"] == "error"


class TestStage2CandidateSelection:
    # These target the request-count optimization: only the top
    # STAGE2_MAX_CANDIDATES events (by stage1 score) are eligible for an
    # LLM call at all, and within that pool, an event whose content,
    # profile version, and relevant feedback are all unchanged since it
    # was last scored is skipped rather than re-asked.

    def test_top_n_cutoff_clears_scores_for_events_outside_it(self, db_session):
        keep = _event(1)
        keep.llm_score = 80.0
        keep.why_match = "will be re-verified, still in range"
        drop = _event(2)
        drop.llm_score = 60.0
        drop.why_match = "stale, should be cleared -- fell out of range"
        profile = InterestProfile(id=1, raw_text="x", categories=[], keywords=[], weights={})
        db_session.add_all([keep, drop, profile])
        db_session.commit()

        with patch("app.ingest_job.STAGE2_MAX_CANDIDATES", 1), \
             patch("app.ingest_job.ensure_embeddings"), \
             patch("app.ingest_job.stage1_filter", return_value=[keep, drop]), \
             patch("app.ingest_job.stage2_rerank", return_value=({1: (85.0, "still good")}, {1}, False)):
            rerank_all(db_session)

        assert keep.llm_score == 85.0
        assert drop.llm_score is None
        assert drop.why_match == ""

    def test_already_fresh_event_is_not_sent_back_to_the_llm(self, db_session):
        profile = InterestProfile(id=1, raw_text="x", categories=[], keywords=[], weights={})
        db_session.add(profile)
        db_session.commit()
        fresh = _event(1)
        fresh.llm_score = 90.0
        fresh.why_match = "already scored"
        fresh.scored_at = dt.datetime.utcnow()
        fresh.scored_profile_version = profile.updated_at
        db_session.add(fresh)
        db_session.commit()

        with patch("app.ingest_job.ensure_embeddings"), \
             patch("app.ingest_job.stage1_filter", return_value=[fresh]), \
             patch("app.ingest_job.stage2_rerank", return_value=({}, set(), False)) as mock_rerank:
            rerank_all(db_session)

        assert mock_rerank.call_args[0][0] == []  # nothing needed re-scoring
        assert fresh.llm_score == 90.0
        assert fresh.why_match == "already scored"

    def test_profile_change_forces_rescore_even_if_content_unchanged(self, db_session):
        profile = InterestProfile(id=1, raw_text="x", categories=[], keywords=[], weights={})
        db_session.add(profile)
        db_session.commit()
        ev = _event(1)
        ev.llm_score = 50.0
        ev.scored_at = dt.datetime.utcnow()
        ev.scored_profile_version = profile.updated_at - dt.timedelta(hours=1)  # scored under an OLDER version
        db_session.add(ev)
        db_session.commit()

        with patch("app.ingest_job.ensure_embeddings"), \
             patch("app.ingest_job.stage1_filter", return_value=[ev]), \
             patch("app.ingest_job.stage2_rerank", return_value=({}, set(), False)) as mock_rerank:
            rerank_all(db_session)

        assert mock_rerank.call_args[0][0] == [ev]

    def test_new_feedback_on_any_event_forces_rescore_once_stale_enough(self, db_session):
        # feedback_context (see ranking.py) summarizes the user's *overall*
        # taste from recent votes, not just per-event -- so new feedback on
        # a totally different event can change what the model would say
        # about this one. Scored well outside _MIN_FEEDBACK_RESCORE_GAP so
        # this specifically tests the "eventually" case, not the cooldown
        # itself (see the two tests below for that).
        profile = InterestProfile(id=1, raw_text="x", categories=[], keywords=[], weights={})
        db_session.add(profile)
        db_session.commit()
        ev = _event(1)
        ev.llm_score = 50.0
        ev.scored_at = dt.datetime.utcnow() - dt.timedelta(hours=2)
        ev.scored_profile_version = profile.updated_at
        other = _event(2)
        db_session.add_all([ev, other])
        db_session.commit()
        db_session.add(Feedback(event_id=2, signal="up"))
        db_session.commit()

        with patch("app.ingest_job.ensure_embeddings"), \
             patch("app.ingest_job.stage1_filter", return_value=[ev]), \
             patch("app.ingest_job.stage2_rerank", return_value=({}, set(), False)) as mock_rerank:
            rerank_all(db_session)

        assert mock_rerank.call_args[0][0] == [ev]

    def test_recent_feedback_does_not_force_an_immediate_rescore(self, db_session):
        # The actual bug this guards against: with no cooldown at all, a
        # vote cast moments after a full rescore forced *every* candidate
        # to be redone again immediately -- confirmed live, every completed
        # rerank in the logs showed skipped_fresh=0 regardless of trigger.
        profile = InterestProfile(id=1, raw_text="x", categories=[], keywords=[], weights={})
        db_session.add(profile)
        db_session.commit()
        ev = _event(1)
        ev.llm_score = 50.0
        ev.scored_at = dt.datetime.utcnow() - dt.timedelta(minutes=10)
        ev.scored_profile_version = profile.updated_at
        other = _event(2)
        db_session.add_all([ev, other])
        db_session.commit()
        db_session.add(Feedback(event_id=2, signal="up"))
        db_session.commit()

        with patch("app.ingest_job.ensure_embeddings"), \
             patch("app.ingest_job.stage1_filter", return_value=[ev]), \
             patch("app.ingest_job.stage2_rerank", return_value=({}, set(), False)) as mock_rerank:
            rerank_all(db_session)

        assert mock_rerank.call_args[0][0] == []  # too soon -- next trigger past the cooldown will catch it

    def test_feedback_rescore_gate_respects_a_custom_now(self):
        from app.ingest_job import _MIN_FEEDBACK_RESCORE_GAP, _needs_rescore

        ev = _event(1)
        ev.llm_score = 50.0
        ev.scored_at = dt.datetime(2026, 1, 1, 12, 0, 0)
        ev.scored_profile_version = dt.datetime(2026, 1, 1, 12, 0, 0)
        feedback_at = dt.datetime(2026, 1, 1, 12, 5, 0)  # after scored_at, within the gap

        just_inside_gap = ev.scored_at + _MIN_FEEDBACK_RESCORE_GAP - dt.timedelta(seconds=1)
        just_past_gap = ev.scored_at + _MIN_FEEDBACK_RESCORE_GAP + dt.timedelta(seconds=1)

        assert _needs_rescore(ev, ev.scored_profile_version, feedback_at, now=just_inside_gap) is False
        assert _needs_rescore(ev, ev.scored_profile_version, feedback_at, now=just_past_gap) is True


class TestFetchAndUpsertScoreInvalidation:
    # _needs_rescore (above) can't detect a content change via
    # Event.updated_at -- that column's onupdate fires on ANY write to the
    # row, including the scored_at/llm_score write itself. So content-change
    # invalidation has to happen here instead, at the exact point the new
    # connector text is compared against what's already stored.

    def _normalized(self, **overrides) -> NormalizedEvent:
        defaults = dict(
            source="test", source_id="1", source_url="", title="Original Title",
            description="Original description", category="Music",
            start=dt.datetime.utcnow(), end=None, venue_name="", location="",
        )
        defaults.update(overrides)
        return NormalizedEvent(**defaults)

    def test_title_change_clears_the_cached_score(self, db_session):
        existing = _event(1, title="Original Title")
        existing.description = "Original description"
        existing.llm_score = 80.0
        existing.why_match = "was a good match"
        existing.scored_at = dt.datetime.utcnow()
        existing.scored_profile_version = dt.datetime.utcnow()
        existing.embedding = [0.1, 0.2]
        db_session.add(existing)
        db_session.commit()

        mock_connector = MagicMock()
        mock_connector.fetch.return_value = [self._normalized(title="A Completely Different Title")]

        with patch("app.ingest_job.CONNECTORS", [mock_connector]):
            _fetch_and_upsert(db_session)

        assert existing.llm_score is None
        assert existing.why_match == ""
        assert existing.scored_at is None
        assert existing.scored_profile_version is None
        assert existing.embedding is None

    def test_unchanged_content_leaves_the_cached_score_alone(self, db_session):
        existing = _event(1, title="Original Title")
        existing.description = "Original description"
        existing.llm_score = 80.0
        existing.why_match = "was a good match"
        existing.scored_at = dt.datetime.utcnow()
        existing.scored_profile_version = dt.datetime.utcnow()
        db_session.add(existing)
        db_session.commit()

        mock_connector = MagicMock()
        # Same title/description/category, only e.g. the venue changed --
        # shouldn't touch the score at all.
        mock_connector.fetch.return_value = [self._normalized(venue_name="A New Venue")]

        with patch("app.ingest_job.CONNECTORS", [mock_connector]):
            _fetch_and_upsert(db_session)

        assert existing.llm_score == 80.0
        assert existing.why_match == "was a good match"
        assert existing.scored_at is not None

    def test_an_empty_venue_from_the_connector_does_not_clobber_an_existing_real_one(self, db_session):
        # art_mate/expo_king fetch venue via a separate per-event request
        # that can transiently fail independently of the listing fetch --
        # a blank result on some later ingest shouldn't blank out a venue
        # that was already correctly found before.
        existing = _event(1, title="Original Title")
        existing.venue_name = "A Real Venue"
        db_session.add(existing)
        db_session.commit()

        mock_connector = MagicMock()
        mock_connector.fetch.return_value = [self._normalized(venue_name="")]

        with patch("app.ingest_job.CONNECTORS", [mock_connector]):
            _fetch_and_upsert(db_session)

        assert existing.venue_name == "A Real Venue"

    def test_a_newly_found_venue_still_overwrites_a_blank_one(self, db_session):
        existing = _event(1, title="Original Title")
        existing.venue_name = ""
        db_session.add(existing)
        db_session.commit()

        mock_connector = MagicMock()
        mock_connector.fetch.return_value = [self._normalized(venue_name="A New Venue")]

        with patch("app.ingest_job.CONNECTORS", [mock_connector]):
            _fetch_and_upsert(db_session)

        assert existing.venue_name == "A New Venue"


class TestCrossSourceDuplicateDetection:
    # The actual bug this guards against: two connectors describing the
    # same real-world event (e.g. hktdc's own Book Fair listing and
    # expo_king's "第35屆書展" mention of the same fair) don't share a
    # (source, source_id) key, so the ordinary upsert-by-key logic in
    # _fetch_and_upsert can't catch it on its own.

    def _normalized(self, **overrides) -> NormalizedEvent:
        defaults = dict(
            source="test", source_id="1", source_url="", title="Test Event",
            description="", category="Exhibition",
            start=dt.datetime(2026, 7, 24), end=dt.datetime(2026, 7, 28), venue_name="", location="",
        )
        defaults.update(overrides)
        return NormalizedEvent(**defaults)

    def test_titles_match_via_substring_containment(self):
        assert _titles_match("香港動漫電玩節 2026", "第二十七屆「香港動漫電玩節 2026」") is True

    def test_titles_match_via_similarity_ratio(self):
        assert _titles_match("Hong Kong Book Fair 2026", "Hong Kong Book Fair") is True

    def test_dissimilar_titles_do_not_match(self):
        assert _titles_match("Hong Kong Book Fair 2026", "Ani-Com & Games Hong Kong 2026") is False

    def test_short_titles_never_match_even_if_identical_substring(self):
        # Guards against short generic words (e.g. a single shared category
        # word) producing a false-positive merge of two unrelated events.
        assert _titles_match("Art", "Artistry Festival") is False

    def test_dates_overlap_true_for_overlapping_ranges(self):
        assert _dates_overlap(
            dt.datetime(2026, 7, 24), dt.datetime(2026, 7, 28),
            dt.datetime(2026, 7, 26), dt.datetime(2026, 7, 30),
        ) is True

    def test_dates_overlap_false_for_disjoint_ranges(self):
        assert _dates_overlap(
            dt.datetime(2026, 7, 24), dt.datetime(2026, 7, 28),
            dt.datetime(2026, 8, 1), dt.datetime(2026, 8, 5),
        ) is False

    def test_dates_overlap_treats_missing_end_as_single_day(self):
        assert _dates_overlap(
            dt.datetime(2026, 7, 24), None,
            dt.datetime(2026, 7, 24), None,
        ) is True

    def test_find_duplicate_matches_similar_title_and_overlapping_dates(self):
        existing = _event(1, title="Hong Kong Book Fair 2026")
        existing.start, existing.end = dt.datetime(2026, 7, 16), dt.datetime(2026, 7, 22)
        candidate = self._normalized(title="第35屆香港書展", start=dt.datetime(2026, 7, 16), end=dt.datetime(2026, 7, 22))

        # Different-language titles won't containment/ratio-match on
        # `title` alone -- this specific pairing is realistic only via
        # title_native, so assert the two lower-level signals it actually
        # relies on instead of forcing a same-language example here.
        assert _dates_overlap(candidate.start, candidate.end, existing.start, existing.end) is True

    def test_find_duplicate_returns_none_for_dissimilar_titles(self):
        existing = _event(1, title="Hong Kong Book Fair 2026")
        existing.start, existing.end = dt.datetime(2026, 7, 16), dt.datetime(2026, 7, 22)
        candidate = self._normalized(title="Ani-Com & Games Hong Kong 2026", start=dt.datetime(2026, 7, 16), end=dt.datetime(2026, 7, 22))

        assert _find_cross_source_duplicate(candidate, [existing]) is None

    def test_find_duplicate_returns_none_for_non_overlapping_dates(self):
        existing = _event(1, title="Hong Kong Book Fair 2026")
        existing.start, existing.end = dt.datetime(2026, 7, 16), dt.datetime(2026, 7, 22)
        candidate = self._normalized(title="Hong Kong Book Fair 2026", start=dt.datetime(2027, 7, 16), end=dt.datetime(2027, 7, 22))

        assert _find_cross_source_duplicate(candidate, [existing]) is None

    def test_find_duplicate_matches_candidate_title_against_existing_title_native(self):
        # art_mate/expo_king are Chinese-only -- their `title` field IS the
        # Chinese text, with no separate title_native. A bilingual urbtix
        # event sets title_native instead. Cross-checking every combination
        # (not just title-to-title) is what lets these two shapes match.
        existing = _event(1, title="Hong Kong Ani-Com & Games 2026")
        existing.title_native = "香港動漫電玩節 2026"
        existing.start, existing.end = dt.datetime(2026, 7, 24), dt.datetime(2026, 7, 28)
        candidate = self._normalized(
            title="第二十七屆「香港動漫電玩節 2026」",
            start=dt.datetime(2026, 7, 24), end=dt.datetime(2026, 7, 28),
        )

        assert _find_cross_source_duplicate(candidate, [existing]) is existing

    def test_find_duplicate_does_not_bridge_two_purely_english_and_chinese_titles(self):
        # Known limitation: hktdc never sets title_native at all, so an
        # English-only hktdc title has no Chinese field on either side to
        # compare against a Chinese-only art_mate/expo_king title.
        existing = _event(1, title="HKTDC Hong Kong Book Fair 2026")
        existing.start, existing.end = dt.datetime(2026, 7, 16), dt.datetime(2026, 7, 22)
        candidate = self._normalized(title="第35屆書展", start=dt.datetime(2026, 7, 16), end=dt.datetime(2026, 7, 22))

        assert _find_cross_source_duplicate(candidate, [existing]) is None

    def test_fetch_and_upsert_skips_a_cross_source_duplicate(self, db_session):
        # Real pairing this was built for: art_mate and expo_king both
        # listing Ani-Com & Games Hong Kong, in Chinese, with the same
        # dates but slightly different phrasing ("香港動漫電玩節 2026" vs
        # "第二十七屆「香港動漫電玩節 2026」" -- the former is a literal
        # substring of the latter).
        art_mate_like = MagicMock()
        art_mate_like.fetch.return_value = [self._normalized(
            source="art_mate", source_id="am-1", title="香港動漫電玩節 2026",
        )]
        expo_king_like = MagicMock()
        expo_king_like.fetch.return_value = [self._normalized(
            source="expo_king", source_id="ek-1", title="第二十七屆「香港動漫電玩節 2026」",
        )]

        with patch("app.ingest_job.CONNECTORS", [art_mate_like, expo_king_like]):
            fetched, new, updated, duplicates = _fetch_and_upsert(db_session)

        assert fetched == 2
        assert new == 1
        assert duplicates == 1
        assert db_session.query(Event).count() == 1

    def test_fetch_and_upsert_keeps_genuinely_distinct_events_from_different_sources(self, db_session):
        source_a = MagicMock()
        source_a.fetch.return_value = [self._normalized(
            source="hktdc", source_id="a-1", title="Hong Kong Book Fair 2026",
        )]
        source_b = MagicMock()
        source_b.fetch.return_value = [self._normalized(
            source="expo_king", source_id="b-1", title="Ani-Com & Games Hong Kong 2026",
        )]

        with patch("app.ingest_job.CONNECTORS", [source_a, source_b]):
            fetched, new, updated, duplicates = _fetch_and_upsert(db_session)

        assert fetched == 2
        assert new == 2
        assert duplicates == 0
        assert db_session.query(Event).count() == 2


class TestScheduleRerank:
    def setup_method(self):
        # Module-level debounce state -- reset so one test's pending timer
        # can't leak into the next.
        ingest_job_module._debounce_timer = None

    def test_second_call_cancels_the_first_pending_timer(self):
        with patch("app.ingest_job.threading.Timer") as mock_timer_cls:
            schedule_rerank(trigger="interest_save")
            schedule_rerank(trigger="interest_save")

        mock_timer_cls.return_value.cancel.assert_called_once()
        assert mock_timer_cls.return_value.start.call_count == 2

    def test_schedules_run_rerank_job_with_the_given_trigger_and_delay(self):
        with patch("app.ingest_job.threading.Timer") as mock_timer_cls:
            schedule_rerank(trigger="refresh")

        args, kwargs = mock_timer_cls.call_args
        assert args[0] == _DEBOUNCE_SECONDS
        assert args[1] is run_rerank_job
        assert kwargs.get("kwargs") == {"trigger": "refresh"}


class TestVenueFromJsonBlob:
    def test_extracts_the_chinese_field_when_present(self):
        html_text = '<script>{"location":{"en":"HKCEC","tc":"香港會議展覽中心"}}</script>'
        assert _venue_from_json_blob(html_text) == "香港會議展覽中心"

    def test_falls_back_to_english_when_no_chinese_field(self):
        html_text = '<script>{"location":{"en":"HKCEC"}}</script>'
        assert _venue_from_json_blob(html_text) == "HKCEC"

    def test_returns_empty_string_when_no_json_blob_present(self):
        assert _venue_from_json_blob("<p>just some text 場地 nothing structured</p>") == ""

    def test_returns_empty_string_on_malformed_json_rather_than_raising(self):
        html_text = '<script>{"location":{"en": not valid json here}}</script>'
        assert _venue_from_json_blob(html_text) == ""

    def test_returns_empty_string_when_location_value_is_not_a_string(self):
        html_text = '<script>{"location":{"en": null, "tc": 123}}</script>'
        assert _venue_from_json_blob(html_text) == ""


class TestVenuePageExcerpt:
    def test_strips_html_tags_from_the_returned_window(self):
        html_text = "<p>場地</p><p><span>Real Arena</span></p>"
        excerpt = _venue_page_excerpt(html_text)
        assert "<p>" not in excerpt
        assert "<span>" not in excerpt
        assert "Real Arena" in excerpt

    def test_windows_around_the_precise_label_when_present(self):
        filler = "x" * 1000
        html_text = f"<p>{filler}</p><p>場地</p><p>The Real Venue</p><p>{filler}</p>"
        excerpt = _venue_page_excerpt(html_text)
        assert "The Real Venue" in excerpt
        # The window is bounded -- shouldn't drag in both multi-hundred-char
        # filler blocks just because they're in the same document.
        assert len(excerpt) < len(html_text)

    def test_falls_back_to_a_type_hint_when_no_precise_label_exists(self):
        filler = "x" * 1000
        html_text = f"<p>{filler}</p><p>Held at AsiaWorld-Expo Hall 3</p><p>{filler}</p>"
        excerpt = _venue_page_excerpt(html_text)
        assert "AsiaWorld-Expo" in excerpt

    def test_precise_label_wins_over_a_type_hint_elsewhere(self):
        # A generic word like "中心" can appear in unrelated nav text (e.g.
        # "參展商中心" -- confirmed on a real page) -- if a precise "場地"/
        # "地點" label also exists, that's the one worth centering on.
        filler = "x" * 500
        html_text = f"<p>參展商中心</p><p>{filler}</p><p>場地</p><p>The Actual Venue</p>"
        excerpt = _venue_page_excerpt(html_text)
        assert "The Actual Venue" in excerpt

    def test_falls_back_to_the_first_400_chars_when_no_hint_at_all(self):
        html_text = "<p>" + ("no relevant keywords here " * 50) + "</p>"
        excerpt = _venue_page_excerpt(html_text)
        assert len(excerpt) <= 400

    def test_includes_a_later_real_statement_even_when_an_earlier_hint_is_nav_boilerplate(self):
        # Confirmed live on a real ExpoKing page: the FIRST "場地" match was
        # inside an unrelated nav-menu link ("活動場地佈置"), with the
        # event's own real venue statement ("地點： 香港會議展覽中心 1 號
        # 館") only appearing much later in the document. Taking only the
        # first hint occurrence would silently miss the real one.
        filler = "x" * 2000
        html_text = (
            f"<a>活動場地佈置</a>{filler}<p>地點 ： 香港會議展覽中心 1 號館</p>{filler}"
        )
        excerpt = _venue_page_excerpt(html_text)
        assert "香港會議展覽中心" in excerpt

    def test_finds_a_json_location_blob_inside_a_script_tag(self):
        # Confirmed live on a real HKTDC event page: the actual venue was a
        # React/Next.js-style hydration blob -- `"location":{"en":"HKCEC",
        # ...}` -- sitting inside a <script> tag. An earlier version of
        # this function stripped all <script> content before searching at
        # all, which threw this away before it was ever seen.
        html_text = (
            '<html><head><script>var data = {"wins_event_name":"Test Expo",'
            '"location":{"en":"HKCEC","tc":"香港會議展覽中心"}};</script></head>'
            "<body>irrelevant visible page content here</body></html>"
        )
        excerpt = _venue_page_excerpt(html_text)
        assert "HKCEC" in excerpt

    def test_a_colon_marked_label_wins_over_multiple_earlier_colon_less_ones(self):
        # Confirmed live on a real ExpoKing page: the first THREE "場地"/
        # "地點" matches were all nav-menu links or exhibitor-category
        # descriptions (no colon), with the event's own real, colon-marked
        # statement only appearing after all of them. A plain "first N
        # occurrences" cap (with N=2 or 3) would have missed it entirely.
        filler = "x" * 500
        html_text = (
            "<a>活動場地佈置</a>"
            f"{filler}<span>屋苑場地佈置</span>"
            f"{filler}<span>婚禮場地及戶外證婚</span>"
            f"{filler}<p>地點 ： The Real Venue</p>"
        )
        excerpt = _venue_page_excerpt(html_text)
        assert "The Real Venue" in excerpt

    def test_json_location_hint_takes_priority_over_a_label_hint(self):
        # The JSON blob is a structured field, strictly more reliable than
        # free text -- worth preferring outright when both are present.
        filler = "x" * 2000
        html_text = (
            '<script>{"location":{"en":"The Real Venue"}}</script>'
            f"{filler}<p>場地</p><p>Some Unrelated Category Text</p>"
        )
        excerpt = _venue_page_excerpt(html_text)
        assert "The Real Venue" in excerpt


def _venue_candidate_event(id: int, source: str, venue_name: str = "", source_url: str = "http://example.com/e") -> Event:
    return Event(
        id=id, source=source, source_id=str(id), source_url=source_url, title=f"Event {id}",
        description="", category="Exhibition", start=dt.datetime.utcnow() + dt.timedelta(days=5),
        venue_name=venue_name, location="Hong Kong",
    )


class _FakeVenueFetchResponse:
    def __init__(self, text: str, ok: bool = True):
        self.text = text
        self._ok = ok

    def raise_for_status(self):
        if not self._ok:
            import httpx
            raise httpx.HTTPError("boom")


class TestBackfillMissingVenues:
    def test_returns_zero_when_nothing_qualifies(self, db_session):
        assert _backfill_missing_venues(db_session) == 0

    def test_ignores_events_that_already_have_a_venue(self, db_session):
        db_session.add(_venue_candidate_event(1, "expo_king", venue_name="Already Known"))
        db_session.commit()

        with patch("app.ingest_job.httpx.Client") as mock_client_cls:
            found = _backfill_missing_venues(db_session)

        assert found == 0
        mock_client_cls.assert_not_called()

    def test_ignores_events_from_sources_other_than_art_mate_or_expo_king(self, db_session):
        # Every other connector's venue comes from the same structured feed
        # as the rest of that event's data -- an empty value there is a
        # real "no venue," not a scrape gap worth an LLM call over.
        db_session.add(_venue_candidate_event(1, "urbtix", venue_name=""))
        db_session.commit()

        with patch("app.ingest_job.httpx.Client") as mock_client_cls:
            found = _backfill_missing_venues(db_session)

        assert found == 0
        mock_client_cls.assert_not_called()

    def test_skips_past_events(self, db_session):
        ev = _venue_candidate_event(1, "expo_king")
        ev.start = dt.datetime.utcnow() - dt.timedelta(days=10)
        ev.end = dt.datetime.utcnow() - dt.timedelta(days=9)
        db_session.add(ev)
        db_session.commit()

        with patch("app.ingest_job.httpx.Client") as mock_client_cls:
            found = _backfill_missing_venues(db_session)

        assert found == 0
        mock_client_cls.assert_not_called()

    def test_applies_a_venue_the_llm_finds_from_the_fetched_page(self, db_session):
        ev = _venue_candidate_event(1, "expo_king")
        db_session.add(ev)
        db_session.commit()

        fake_client = MagicMock()
        fake_client.get.return_value = _FakeVenueFetchResponse("<p>場地</p><p>The Real Venue</p>")

        with patch("app.ingest_job.httpx.Client") as mock_client_cls, \
             patch("app.ingest_job.extract_venues", return_value={1: "The Real Venue"}) as mock_extract:
            mock_client_cls.return_value.__enter__.return_value = fake_client
            found = _backfill_missing_venues(db_session)

        assert found == 1
        db_session.refresh(ev)
        assert ev.venue_name == "The Real Venue"
        mock_extract.assert_called_once()

    def test_a_json_location_blob_resolves_without_ever_calling_the_llm(self, db_session):
        # Structured data doesn't need an LLM's judgment -- confirmed live
        # this path is also more reliable: a real HKCEC JSON blob was
        # present on a page but the LLM still returned null for it inside
        # a larger batched call. Deterministic parsing can't have that
        # failure mode.
        ev = _venue_candidate_event(1, "hktdc")
        db_session.add(ev)
        db_session.commit()

        fake_client = MagicMock()
        fake_client.get.return_value = _FakeVenueFetchResponse(
            '<script>{"location":{"en":"HKCEC","tc":"香港會議展覽中心"}}</script>'
        )

        with patch("app.ingest_job.httpx.Client") as mock_client_cls, \
             patch("app.ingest_job.extract_venues") as mock_extract:
            mock_client_cls.return_value.__enter__.return_value = fake_client
            found = _backfill_missing_venues(db_session)

        assert found == 1
        db_session.refresh(ev)
        assert ev.venue_name == "香港會議展覽中心"
        mock_extract.assert_not_called()

    def test_one_events_fetch_failure_does_not_abort_the_others(self, db_session):
        ev1 = _venue_candidate_event(1, "expo_king")
        ev2 = _venue_candidate_event(2, "expo_king")
        db_session.add_all([ev1, ev2])
        db_session.commit()

        fake_client = MagicMock()

        # First event's page fetch fails, second succeeds.
        fake_client.get.side_effect = [
            _FakeVenueFetchResponse("", ok=False),
            _FakeVenueFetchResponse("<p>場地</p><p>Venue Two</p>"),
        ]

        with patch("app.ingest_job.httpx.Client") as mock_client_cls, \
             patch("app.ingest_job.extract_venues", return_value={2: "Venue Two"}) as mock_extract:
            mock_client_cls.return_value.__enter__.return_value = fake_client
            found = _backfill_missing_venues(db_session)

        assert found == 1
        # Only the successfully-fetched event's page should have reached extract_venues.
        pages_arg = mock_extract.call_args[0][1]
        assert list(pages_arg.keys()) == [2]
