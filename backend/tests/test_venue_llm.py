from unittest.mock import patch

from app.venue_llm import extract_venues


class _FakeItem:
    def __init__(self, event_id, venue):
        self.event_id = event_id
        self.venue = venue


class _FakeParsed:
    def __init__(self, results):
        self.results = results


class TestExtractVenues:
    def test_returns_empty_dict_for_no_pages(self):
        assert extract_venues(None, {}) == {}

    def test_extracts_a_real_venue(self):
        with patch("app.venue_llm.get_llm") as mock_llm, patch("app.venue_llm.log_call"):
            mock_llm.return_value.with_structured_output.return_value.invoke.return_value = {
                "parsed": _FakeParsed([_FakeItem(1, "AsiaWorld-Expo")]),
                "raw": type("R", (), {"usage_metadata": {}})(),
            }
            result = extract_venues(None, {1: "some page text"})
        assert result == {1: "AsiaWorld-Expo"}

    def test_null_venue_is_omitted_not_kept_as_none(self):
        with patch("app.venue_llm.get_llm") as mock_llm, patch("app.venue_llm.log_call"):
            mock_llm.return_value.with_structured_output.return_value.invoke.return_value = {
                "parsed": _FakeParsed([_FakeItem(1, None)]),
                "raw": type("R", (), {"usage_metadata": {}})(),
            }
            result = extract_venues(None, {1: "some page text"})
        assert result == {}

    def test_blank_venue_string_is_also_omitted(self):
        with patch("app.venue_llm.get_llm") as mock_llm, patch("app.venue_llm.log_call"):
            mock_llm.return_value.with_structured_output.return_value.invoke.return_value = {
                "parsed": _FakeParsed([_FakeItem(1, "   ")]),
                "raw": type("R", (), {"usage_metadata": {}})(),
            }
            result = extract_venues(None, {1: "some page text"})
        assert result == {}

    def test_a_hallucinated_event_id_not_in_the_input_is_dropped(self):
        # Same guard as ask.py's referenced_event_ids -- a structured field
        # like this is exactly where a model can invent an id it was never
        # given.
        with patch("app.venue_llm.get_llm") as mock_llm, patch("app.venue_llm.log_call"):
            mock_llm.return_value.with_structured_output.return_value.invoke.return_value = {
                "parsed": _FakeParsed([_FakeItem(1, "Real Venue"), _FakeItem(999, "Made Up Venue")]),
                "raw": type("R", (), {"usage_metadata": {}})(),
            }
            result = extract_venues(None, {1: "some page text"})
        assert result == {1: "Real Venue"}

    def test_llm_failure_returns_empty_dict_rather_than_raising(self):
        with patch("app.venue_llm.get_llm") as mock_llm:
            mock_llm.return_value.with_structured_output.return_value.invoke.side_effect = RuntimeError("boom")
            result = extract_venues(None, {1: "some page text"})
        assert result == {}
