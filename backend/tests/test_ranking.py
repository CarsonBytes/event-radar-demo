import datetime as dt
from unittest.mock import patch

from app.models import Event, Feedback, InterestProfile
from app.ranking import _batches, _feedback_context, apply_feedback, ensure_embeddings, persist_feedback_weights, stage1_filter, stage2_rerank


def _event(id: int, title: str, category: str = "Music", description: str = "", raw_score: float = 0.0) -> Event:
    return Event(
        id=id, source="test", source_id=str(id), source_url="", title=title,
        description=description, category=category, start=dt.datetime.utcnow(),
        venue_name="", location="", raw_score=raw_score,
    )


def _profile(
    raw_text: str,
    categories: list[str],
    keywords: list[str],
    weights: dict | None = None,
    excluded_keywords: list[str] | None = None,
) -> InterestProfile:
    return InterestProfile(
        id=1, raw_text=raw_text, categories=categories, keywords=keywords, weights=weights or {},
        excluded_keywords=excluded_keywords or [],
    )


class TestStage1Filter:
    def test_scores_by_keyword_overlap(self):
        events = [_event(1, "Erhu Music Concert", "Music"), _event(2, "Football Match", "Sports")]
        profile = _profile("erhu concerts", ["Music"], ["erhu"])

        result = stage1_filter(events, profile)

        assert result[0].id == 1  # the erhu match sorts first
        assert result[0].raw_score > result[1].raw_score

    def test_respects_custom_weights(self):
        events = [_event(1, "Erhu Concert")]
        # categories deliberately empty -- "Music" would itself be a second
        # matching term against this event's default category and muddy
        # what's actually being isolated here (just the weight override).
        profile = _profile("erhu", [], ["erhu"], weights={"erhu": 2.5})

        stage1_filter(events, profile)

        assert events[0].raw_score == 2.5  # weight overrides the 1.0 default

    def test_limit_truncates_but_none_returns_everything(self):
        events = [_event(i, f"Event {i}") for i in range(5)]
        profile = _profile("x", [], [])

        assert len(stage1_filter(list(events), profile, limit=2)) == 2
        assert len(stage1_filter(list(events), profile, limit=None)) == 5

    def test_semantic_similarity_boosts_score_even_without_keyword_overlap(self):
        # No literal keyword overlap at all -- only the embedding vectors
        # differ, isolating that this boost actually fires independent of
        # the keyword-overlap term.
        ev_similar = _event(1, "Guzheng Recital", "Music")
        ev_similar.embedding = [1.0, 0.0]
        ev_different = _event(2, "Football Match", "Sports")
        ev_different.embedding = [0.0, 1.0]
        profile = _profile("erhu", [], [])  # empty categories/keywords -- no keyword score possible
        profile.embedding = [1.0, 0.0]

        stage1_filter([ev_similar, ev_different], profile)

        assert ev_similar.raw_score > ev_different.raw_score
        assert ev_different.raw_score == 0.0  # orthogonal vectors -> cosine similarity 0

    def test_missing_embeddings_dont_crash_or_contribute(self):
        ev = _event(1, "Some Event")
        profile = _profile("x", [], [])
        # neither has .embedding set (stays None, the model default)

        stage1_filter([ev], profile)

        assert ev.raw_score == 0.0

    def test_excluded_event_sinks_below_every_non_excluded_event(self):
        excluded = _event(1, "Football Match", "Sports")
        neutral = _event(2, "Some Random Event")  # no keyword overlap either -- raw_score would be 0.0
        profile = _profile("music", [], ["music"], excluded_keywords=["sports"])

        stage1_filter([excluded, neutral], profile)

        assert excluded.raw_score < neutral.raw_score
        assert excluded.raw_score < 0

    def test_exclusion_overrides_an_otherwise_strong_keyword_match(self):
        # Explicitly matches BOTH a positive keyword and an excluded one --
        # exclusion wins, full stop, not a partial discount.
        ev = _event(1, "Live Football Concert Night", description="football and music together")
        profile = _profile("music", [], ["music"], weights={"music": 3.0}, excluded_keywords=["football"])

        stage1_filter([ev], profile)

        assert ev.raw_score < 0

    def test_no_exclusions_behaves_exactly_as_before(self):
        ev = _event(1, "Football Match", "Sports")
        profile = _profile("football", [], ["football"])  # excluded_keywords defaults to []

        stage1_filter([ev], profile)

        assert ev.raw_score == 1.0

    def test_short_keyword_does_not_match_inside_unrelated_words(self):
        # The bug this guards against: "ai" was matching as a plain
        # substring inside "fair", "hair", and "Kwai Tsing Theatre" --
        # scoring totally unrelated events as keyword matches.
        unrelated = _event(1, "HKTDC Book Fair 2026 at Kwai Tsing Theatre")
        genuine = _event(2, "AI in Healthcare Summit")
        profile = _profile("ai", [], ["ai"])

        stage1_filter([unrelated, genuine], profile)

        assert unrelated.raw_score == 0.0
        assert genuine.raw_score == 1.0

    def test_hyphenated_mention_still_matches(self):
        ev = _event(1, "HKTDC Smart Expo", description="AI-enabled business matching")
        profile = _profile("ai", [], ["ai"])

        stage1_filter([ev], profile)

        assert ev.raw_score == 1.0

    def test_cjk_keyword_matches_when_literally_present(self):
        # The bug this guards against: the ASCII-only tokenizer silently
        # dropped every CJK character, so tokenize("古天樂") == [] and a
        # pure-Chinese keyword could never match anything, no matter how
        # obviously it appeared in an event's text.
        ev = _event(1, "Cantonese Opera Gala", description="Guest star 古天樂 headlines this year's show")
        profile = _profile("古天樂", [], ["古天樂"])

        stage1_filter([ev], profile)

        assert ev.raw_score == 1.0

    def test_cjk_keyword_does_not_match_when_absent(self):
        # An English-only title/description genuinely doesn't contain the
        # Chinese name -- no amount of tokenizer fixing should conjure a
        # match out of text that isn't there (only stage2's LLM, which sees
        # the full profile text separately, can make that cross-lingual
        # leap).
        ev = _event(1, "AXA Presents Louis Koo My First Show")
        profile = _profile("古天樂", [], ["古天樂"])

        stage1_filter([ev], profile)

        assert ev.raw_score == 0.0

    def test_plural_event_text_still_matches_singular_keyword(self):
        ev = _event(1, "Weekend Concerts Series")
        profile = _profile("concert", [], ["concert"])

        stage1_filter([ev], profile)

        assert ev.raw_score == 1.0


def test_batches_chunks_evenly_and_handles_remainder():
    items = list(range(7))
    chunks = list(_batches(items, 3))
    assert chunks == [[0, 1, 2], [3, 4, 5], [6]]


def test_batches_empty_input():
    assert list(_batches([], 5)) == []


class TestStage2Rerank:
    def test_no_api_key_returns_empty_without_calling_llm(self):
        events = [_event(1, "Test")]
        profile = _profile("x", [], [])
        with patch("app.ranking.OPENAI_API_KEY", ""), patch("app.ranking.DEEPSEEK_API_KEY", ""), \
             patch("app.ranking.get_llm") as mock_llm:
            scores, attempted, quota_exhausted = stage2_rerank(events, profile, db=None)
        assert scores == {}
        assert attempted == set()
        assert quota_exhausted is False
        mock_llm.assert_not_called()

    def test_batch_failure_leaves_that_batch_unattempted(self):
        # This is the exact distinction ingest_job.rerank_all relies on to
        # decide "clear the stale score" vs. "leave it alone" -- a batch
        # whose call raised must never show up in `attempted`.
        events = [_event(1, "Test")]
        profile = _profile("x", [], [])
        with patch("app.ranking.OPENAI_API_KEY", "fake-key"), \
             patch("app.ranking.get_llm") as mock_llm:
            mock_llm.return_value.with_structured_output.return_value.invoke.side_effect = RuntimeError("boom")
            scores, attempted, quota_exhausted = stage2_rerank(events, profile, db=None)
        assert scores == {}
        assert attempted == set()
        assert quota_exhausted is False

    def test_successful_batch_marks_events_attempted(self):
        events = [_event(1, "Test")]
        profile = _profile("x", [], [])

        class FakeItem:
            event_id = 1
            llm_score = 77
            why_match = "because"

        class FakeParsed:
            rankings = [FakeItem()]

        with patch("app.ranking.OPENAI_API_KEY", "fake-key"), \
             patch("app.ranking.get_llm") as mock_llm, \
             patch("app.ranking.log_call"):
            mock_llm.return_value.with_structured_output.return_value.invoke.return_value = {
                "parsed": FakeParsed(), "raw": type("R", (), {"usage_metadata": {}})(),
            }
            scores, attempted, quota_exhausted = stage2_rerank(events, profile, db=None)

        assert attempted == {1}
        assert scores[1] == (77.0, "because")
        assert quota_exhausted is False

    def test_rate_limit_error_sets_quota_exhausted(self):
        events = [_event(1, "Test")]
        profile = _profile("x", [], [])
        with patch("app.ranking.OPENAI_API_KEY", "fake-key"), \
             patch("app.ranking.get_llm") as mock_llm:
            mock_llm.return_value.with_structured_output.return_value.invoke.side_effect = RuntimeError(
                "Error code: 429 - free account is limited to 200 requests per day"
            )
            scores, attempted, quota_exhausted = stage2_rerank(events, profile, db=None)
        assert quota_exhausted is True

    def test_unrelated_failure_does_not_set_quota_exhausted(self):
        events = [_event(1, "Test")]
        profile = _profile("x", [], [])
        with patch("app.ranking.OPENAI_API_KEY", "fake-key"), \
             patch("app.ranking.get_llm") as mock_llm:
            mock_llm.return_value.with_structured_output.return_value.invoke.side_effect = ConnectionError("timed out")
            scores, attempted, quota_exhausted = stage2_rerank(events, profile, db=None)
        assert quota_exhausted is False

    def test_on_batch_done_fires_once_per_batch_with_totals(self):
        # 5 events at batch size 2 (patched down from the real 25) -> 3 batches.
        events = [_event(i, f"Test {i}") for i in range(5)]
        profile = _profile("x", [], [])
        calls = []

        class FakeItem:
            event_id = 0
            llm_score = 50
            why_match = "ok"

        class FakeParsed:
            rankings = [FakeItem()]

        with patch("app.ranking.OPENAI_API_KEY", "fake-key"), \
             patch("app.ranking.RERANK_BATCH_SIZE", 2), \
             patch("app.ranking.get_llm") as mock_llm, \
             patch("app.ranking.log_call"):
            mock_llm.return_value.with_structured_output.return_value.invoke.return_value = {
                "parsed": FakeParsed(), "raw": type("R", (), {"usage_metadata": {}})(),
            }
            stage2_rerank(events, profile, db=None, on_batch_done=lambda done, total: calls.append((done, total)))

        assert calls == [(1, 3), (2, 3), (3, 3)]


class TestFeedbackContext:
    def test_empty_when_no_feedback(self, db_session):
        assert _feedback_context(db_session) == ""

    def test_none_db_returns_empty(self):
        assert _feedback_context(None) == ""

    def test_dedupes_to_latest_vote_per_event(self, db_session):
        ev = _event(1, "Erhu Concert")
        db_session.add(ev)
        db_session.commit()
        # vote up, then change your mind to down -- only the LATEST should count
        db_session.add(Feedback(event_id=1, signal="up", created_at=dt.datetime.utcnow() - dt.timedelta(minutes=5)))
        db_session.add(Feedback(event_id=1, signal="down", created_at=dt.datetime.utcnow()))
        db_session.commit()

        result = _feedback_context(db_session)

        assert "Disliked" in result
        assert "Liked" not in result
        assert "Erhu Concert" in result


class TestEnsureEmbeddings:
    def test_only_embeds_events_missing_a_vector(self, db_session):
        already = _event(1, "Already Embedded")
        already.embedding = [0.1, 0.2]
        pending = _event(2, "Needs Embedding")
        profile = _profile("x", [], [])

        with patch("app.ranking.embed_batch") as mock_embed:
            mock_embed.return_value = [[0.5, 0.6]]
            ensure_embeddings(db_session, [already, pending], profile)

        # only the pending event's text should have been sent for embedding
        mock_embed.assert_any_call([f"{pending.title}  {pending.category}"])
        assert already.embedding == [0.1, 0.2]  # untouched
        assert pending.embedding == [0.5, 0.6]

    def test_embed_failure_leaves_events_without_embeddings(self, db_session):
        ev = _event(1, "Test")
        profile = _profile("x", [], [])
        with patch("app.ranking.embed_batch", return_value=None):
            ensure_embeddings(db_session, [ev], profile)
        assert ev.embedding is None


class TestPersistFeedbackWeights:
    # Real bug this guards against: writing feedback-driven weight nudges
    # through the ORM as a normal attribute assignment silently re-bumped
    # InterestProfile.updated_at on every single vote (onupdate=utcnow
    # fires on any write to the row, not just meaningful ones) --
    # confirmed live, a single vote moved `updated_at` immediately. That
    # column is what ingest_job.py's _needs_rescore treats as "the user's
    # stated interests changed," so every vote was invalidating the
    # entire scored candidate pool's cache for the next rerank.

    def test_updates_weights_without_bumping_updated_at(self, db_session):
        original_updated_at = dt.datetime(2026, 1, 1, 12, 0, 0)
        profile = _profile("x", [], [], weights={"music": 1.0})
        profile.updated_at = original_updated_at
        db_session.add(profile)
        db_session.commit()

        persist_feedback_weights(db_session, profile.id, {"music": 1.15})
        db_session.commit()
        db_session.refresh(profile)

        assert profile.weights == {"music": 1.15}
        assert profile.updated_at == original_updated_at

    def test_apply_feedback_on_a_transient_copy_does_not_touch_the_session_tracked_profile(self, db_session):
        # Documents the actual call pattern routers/feedback.py uses: run
        # apply_feedback against a throwaway copy, only ever persist the
        # result via persist_feedback_weights -- never assign .weights on
        # the real session-tracked object, which would queue an ORM-level
        # write that bumps updated_at at the next commit() regardless of
        # the raw UPDATE above.
        original_updated_at = dt.datetime(2026, 1, 1, 12, 0, 0)
        profile = _profile("x", [], [], weights={})
        profile.updated_at = original_updated_at
        db_session.add(profile)
        db_session.commit()

        ev = _event(1, "Some Concert", category="Music")
        scratch = InterestProfile(weights=dict(profile.weights or {}))
        apply_feedback(scratch, ev, "up")
        persist_feedback_weights(db_session, profile.id, scratch.weights)
        db_session.commit()
        db_session.refresh(profile)

        assert profile.weights == scratch.weights
        assert profile.updated_at == original_updated_at
