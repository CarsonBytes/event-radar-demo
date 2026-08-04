import datetime as dt
from unittest.mock import patch

from app.ask import ASK_MAX_CANDIDATES, ask
from app.models import AskLog, Event, InterestProfile


def _event(
    id: int, title: str = "Test", llm_score: float | None = None,
    start: dt.datetime | None = None, end: dt.datetime | None = None,
    title_native: str | None = None,
) -> Event:
    # Defaults an hour into the future, not "now" -- Event.status computes
    # against the real clock at read time, so a zero-duration event
    # timestamped exactly "now" is already past by the time a test actually
    # checks it, which would make every existing-fixture event silently
    # invisible to ask() once it started filtering out past events.
    return Event(
        id=id, source="test", source_id=str(id), source_url="", title=title, title_native=title_native,
        description="", category="Music",
        start=start or dt.datetime.utcnow() + dt.timedelta(hours=1), end=end,
        venue_name="", location="", llm_score=llm_score,
    )


class _FakeRaw:
    def __init__(self, usage: dict | None = None):
        self.usage_metadata = usage or {}


class _FakeParsed:
    def __init__(self, answer: str, referenced_event_ids: list[int] | None = None):
        self.answer = answer
        self.referenced_event_ids = referenced_event_ids or []


def _fake_result(answer: str, referenced_event_ids: list[int] | None = None, usage: dict | None = None) -> dict:
    return {"parsed": _FakeParsed(answer, referenced_event_ids), "raw": _FakeRaw(usage)}


# ensure_embeddings is real network I/O (the embeddings API) -- patched out
# in every test the same way test_ingest_job.py patches it for rerank_all,
# since ask() now calls it too (see app/ask.py: a not-yet-scored event has
# no embedding yet either, so without this its stage1 semantic score would
# always be 0 regardless of relevance).
_NO_EMBEDDINGS = patch("app.ask.ensure_embeddings")


class TestAsk:
    def test_no_api_key_returns_empty_without_calling_llm(self, db_session):
        with patch("app.ask.OPENAI_API_KEY", ""), patch("app.ask.DEEPSEEK_API_KEY", ""), \
             patch("app.ask.get_llm") as mock_llm:
            answer, quota_exhausted, referenced = ask(db_session, "anything this weekend?")

        assert answer == ""
        assert quota_exhausted is False
        assert referenced == []
        mock_llm.assert_not_called()

    def test_empty_catalog_still_answers(self, db_session):
        profile = InterestProfile(id=1, raw_text="music", categories=[], keywords=["music"], weights={})
        db_session.add(profile)
        db_session.commit()

        with patch("app.ask.OPENAI_API_KEY", "fake-key"), \
             patch("app.ask.get_llm") as mock_llm, \
             patch("app.ask.log_call"), _NO_EMBEDDINGS:
            mock_llm.return_value.with_structured_output.return_value.invoke.return_value = _fake_result(
                "Nothing's on right now."
            )
            answer, quota_exhausted, referenced = ask(db_session, "anything today?")

        assert answer == "Nothing's on right now."
        assert quota_exhausted is False
        assert referenced == []

    def test_prefers_already_scored_events_over_stage1_ordering(self, db_session):
        # A low stage1-relevant event that's already been LLM-scored highly
        # should still be sent as a candidate ahead of an unscored one --
        # ask() shouldn't need a fresh ranking pass to answer a question.
        profile = InterestProfile(id=1, raw_text="x", categories=[], keywords=[], weights={})
        scored = _event(1, "Scored Event", llm_score=90.0)
        unscored = _event(2, "Unscored Event", llm_score=None)
        db_session.add_all([profile, scored, unscored])
        db_session.commit()

        captured_prompt = {}

        def fake_invoke(messages):
            captured_prompt["content"] = messages[0]["content"]
            return _fake_result("ok")

        with patch("app.ask.OPENAI_API_KEY", "fake-key"), \
             patch("app.ask.get_llm") as mock_llm, \
             patch("app.ask.log_call"), _NO_EMBEDDINGS:
            mock_llm.return_value.with_structured_output.return_value.invoke.side_effect = fake_invoke
            ask(db_session, "what's good?")

        # Both appear -- scored events don't need a fresh ranking pass, but
        # a not-yet-scored event still gets a reserved slot (see
        # test_unscored_events_get_a_reserved_slot below for why).
        assert "Scored Event" in captured_prompt["content"]
        assert "Unscored Event" in captured_prompt["content"]

    def test_unscored_events_get_a_reserved_slot(self, db_session):
        # Real bug this guards against: a just-ingested event with no
        # llm_score yet was completely invisible to ask() as long as *any*
        # other event already had a score -- found live when a brand-new
        # connector's event, asked about immediately after ingest, got "no
        # such event" despite already being in the catalog.
        profile = InterestProfile(id=1, raw_text="x", categories=[], keywords=[], weights={})
        scored = _event(1, "Old Scored Event", llm_score=50.0)
        fresh = _event(2, "Brand New Event", llm_score=None)
        db_session.add_all([profile, scored, fresh])
        db_session.commit()

        captured_prompt = {}

        def fake_invoke(messages):
            captured_prompt["content"] = messages[0]["content"]
            return _fake_result("ok")

        with patch("app.ask.OPENAI_API_KEY", "fake-key"), \
             patch("app.ask.get_llm") as mock_llm, \
             patch("app.ask.log_call"), _NO_EMBEDDINGS:
            mock_llm.return_value.with_structured_output.return_value.invoke.side_effect = fake_invoke
            ask(db_session, "anything new?")

        assert "Brand New Event" in captured_prompt["content"]

    def test_falls_back_to_stage1_when_nothing_scored_yet(self, db_session):
        profile = InterestProfile(id=1, raw_text="jazz", categories=[], keywords=["jazz"], weights={})
        ev = _event(1, "Jazz Night")
        db_session.add_all([profile, ev])
        db_session.commit()

        captured_prompt = {}

        def fake_invoke(messages):
            captured_prompt["content"] = messages[0]["content"]
            return _fake_result("ok")

        with patch("app.ask.OPENAI_API_KEY", "fake-key"), \
             patch("app.ask.get_llm") as mock_llm, \
             patch("app.ask.log_call"), _NO_EMBEDDINGS:
            mock_llm.return_value.with_structured_output.return_value.invoke.side_effect = fake_invoke
            ask(db_session, "any jazz?")

        assert "Jazz Night" in captured_prompt["content"]

    def test_candidates_capped_at_ask_max_candidates(self, db_session):
        profile = InterestProfile(id=1, raw_text="x", categories=[], keywords=[], weights={})
        events = [_event(i, f"Event {i}", llm_score=float(i)) for i in range(ASK_MAX_CANDIDATES + 10)]
        db_session.add_all([profile, *events])
        db_session.commit()

        captured_prompt = {}

        def fake_invoke(messages):
            captured_prompt["content"] = messages[0]["content"]
            return _fake_result("ok")

        with patch("app.ask.OPENAI_API_KEY", "fake-key"), \
             patch("app.ask.get_llm") as mock_llm, \
             patch("app.ask.log_call"), _NO_EMBEDDINGS:
            mock_llm.return_value.with_structured_output.return_value.invoke.side_effect = fake_invoke
            ask(db_session, "anything?")

        # Highest-scored (Event 45..54, the top ASK_MAX_CANDIDATES) should be
        # included; the lowest-scored (Event 0) should have been cut.
        assert "Event 0," not in captured_prompt["content"] and '"Event 0"' not in captured_prompt["content"]

    def test_rate_limit_error_sets_quota_exhausted(self, db_session):
        profile = InterestProfile(id=1, raw_text="x", categories=[], keywords=[], weights={})
        db_session.add(profile)
        db_session.commit()

        with patch("app.ask.OPENAI_API_KEY", "fake-key"), \
             patch("app.ask.get_llm") as mock_llm, _NO_EMBEDDINGS:
            mock_llm.return_value.with_structured_output.return_value.invoke.side_effect = RuntimeError(
                "Error code: 429 - free account is limited to 200 requests per day"
            )
            answer, quota_exhausted, referenced = ask(db_session, "anything?")

        assert answer == ""
        assert quota_exhausted is True
        assert referenced == []

    def test_unrelated_failure_does_not_set_quota_exhausted(self, db_session):
        profile = InterestProfile(id=1, raw_text="x", categories=[], keywords=[], weights={})
        db_session.add(profile)
        db_session.commit()

        with patch("app.ask.OPENAI_API_KEY", "fake-key"), \
             patch("app.ask.get_llm") as mock_llm, _NO_EMBEDDINGS:
            mock_llm.return_value.with_structured_output.return_value.invoke.side_effect = ConnectionError("timed out")
            answer, quota_exhausted, referenced = ask(db_session, "anything?")

        assert answer == ""
        assert quota_exhausted is False
        assert referenced == []

    def test_past_events_excluded_from_candidates(self, db_session):
        # The actual bug this guards against: a past event that scored
        # highly back when it was upcoming/ongoing must never be offered to
        # the LLM as a candidate for a forward-looking question -- its score
        # is never cleared just because time passed.
        profile = InterestProfile(id=1, raw_text="x", categories=[], keywords=[], weights={})
        past = _event(
            1, "Long Gone Concert", llm_score=95.0,
            start=dt.datetime.utcnow() - dt.timedelta(days=10),
            end=dt.datetime.utcnow() - dt.timedelta(days=9),
        )
        upcoming = _event(2, "This Weekend Fest", llm_score=50.0)
        db_session.add_all([profile, past, upcoming])
        db_session.commit()

        captured_prompt = {}

        def fake_invoke(messages):
            captured_prompt["content"] = messages[0]["content"]
            return _fake_result("ok")

        with patch("app.ask.OPENAI_API_KEY", "fake-key"), \
             patch("app.ask.get_llm") as mock_llm, \
             patch("app.ask.log_call"), _NO_EMBEDDINGS:
            mock_llm.return_value.with_structured_output.return_value.invoke.side_effect = fake_invoke
            ask(db_session, "what's on this weekend?")

        assert "Long Gone Concert" not in captured_prompt["content"]
        assert "This Weekend Fest" in captured_prompt["content"]

    def test_todays_date_stated_in_prompt(self, db_session):
        profile = InterestProfile(id=1, raw_text="x", categories=[], keywords=[], weights={})
        ev = _event(1, "Some Event", llm_score=50.0)
        db_session.add_all([profile, ev])
        db_session.commit()

        captured_prompt = {}

        def fake_invoke(messages):
            captured_prompt["content"] = messages[0]["content"]
            return _fake_result("ok")

        with patch("app.ask.OPENAI_API_KEY", "fake-key"), \
             patch("app.ask.get_llm") as mock_llm, \
             patch("app.ask.log_call"), _NO_EMBEDDINGS:
            mock_llm.return_value.with_structured_output.return_value.invoke.side_effect = fake_invoke
            ask(db_session, "what's on this weekend?")

        today_iso = dt.datetime.utcnow().date().isoformat()
        assert today_iso in captured_prompt["content"]
        assert "Today's date is" in captured_prompt["content"]

    def test_successful_ask_is_logged_to_ask_log(self, db_session):
        profile = InterestProfile(id=1, raw_text="x", categories=[], keywords=[], weights={})
        db_session.add(profile)
        db_session.commit()

        with patch("app.ask.OPENAI_API_KEY", "fake-key"), \
             patch("app.ask.get_llm") as mock_llm, \
             patch("app.ask.log_call"), _NO_EMBEDDINGS:
            mock_llm.return_value.with_structured_output.return_value.invoke.return_value = _fake_result(
                "Try the jazz night."
            )
            ask(db_session, "any jazz this weekend?")

        rows = db_session.query(AskLog).all()
        assert len(rows) == 1
        assert rows[0].query == "any jazz this weekend?"
        assert rows[0].answer == "Try the jazz night."
        assert rows[0].quota_exhausted is False
        assert rows[0].referenced_events == []

    def test_failed_ask_is_logged_with_empty_answer(self, db_session):
        profile = InterestProfile(id=1, raw_text="x", categories=[], keywords=[], weights={})
        db_session.add(profile)
        db_session.commit()

        with patch("app.ask.OPENAI_API_KEY", "fake-key"), \
             patch("app.ask.get_llm") as mock_llm, _NO_EMBEDDINGS:
            mock_llm.return_value.with_structured_output.return_value.invoke.side_effect = RuntimeError(
                "Error code: 429 - free account is limited to 200 requests per day"
            )
            ask(db_session, "anything?")

        rows = db_session.query(AskLog).all()
        assert len(rows) == 1
        assert rows[0].answer == ""
        assert rows[0].quota_exhausted is True

    def test_referenced_event_ids_resolved_to_titles(self, db_session):
        profile = InterestProfile(id=1, raw_text="x", categories=[], keywords=[], weights={})
        ev = _event(1, "Jazz Night", llm_score=90.0, title_native="爵士夜")
        db_session.add_all([profile, ev])
        db_session.commit()

        with patch("app.ask.OPENAI_API_KEY", "fake-key"), \
             patch("app.ask.get_llm") as mock_llm, \
             patch("app.ask.log_call"), _NO_EMBEDDINGS:
            mock_llm.return_value.with_structured_output.return_value.invoke.return_value = _fake_result(
                "Try Jazz Night.", referenced_event_ids=[1]
            )
            answer, quota_exhausted, referenced = ask(db_session, "any jazz?")

        assert referenced == [{"id": 1, "title": "Jazz Night", "title_native": "爵士夜"}]
        rows = db_session.query(AskLog).all()
        assert rows[0].referenced_events == [{"id": 1, "title": "Jazz Night", "title_native": "爵士夜"}]

    def test_hallucinated_referenced_id_is_dropped(self, db_session):
        # The model can name an id that was never in what it was shown --
        # only ids that are actually in the candidate set should ever be
        # trusted as a real, clickable reference.
        profile = InterestProfile(id=1, raw_text="x", categories=[], keywords=[], weights={})
        ev = _event(1, "Jazz Night", llm_score=90.0)
        db_session.add_all([profile, ev])
        db_session.commit()

        with patch("app.ask.OPENAI_API_KEY", "fake-key"), \
             patch("app.ask.get_llm") as mock_llm, \
             patch("app.ask.log_call"), _NO_EMBEDDINGS:
            mock_llm.return_value.with_structured_output.return_value.invoke.return_value = _fake_result(
                "Try Jazz Night.", referenced_event_ids=[1, 999]
            )
            answer, quota_exhausted, referenced = ask(db_session, "any jazz?")

        assert referenced == [{"id": 1, "title": "Jazz Night", "title_native": None}]
