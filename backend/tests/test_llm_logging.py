import datetime as dt
from unittest.mock import MagicMock, patch

from app.llm_logging import HKT, fetch_shared_usage_today, hkt_today_start_utc


def test_boundary_is_exactly_midnight_in_hkt():
    boundary = hkt_today_start_utc()
    assert boundary.tzinfo is None  # naive, to compare against naive utcnow()-stamped rows
    as_hkt = boundary.replace(tzinfo=dt.timezone.utc).astimezone(HKT)
    assert (as_hkt.hour, as_hkt.minute, as_hkt.second, as_hkt.microsecond) == (0, 0, 0, 0)


def test_boundary_is_16_00_utc_and_within_the_last_24h():
    # HKT is UTC+8 with no DST, so HKT midnight is always 16:00 UTC (of the
    # same or previous UTC calendar day).
    boundary = hkt_today_start_utc()
    assert boundary.hour == 16
    now = dt.datetime.utcnow()
    assert boundary <= now
    assert now - boundary < dt.timedelta(hours=24)


def _fake_response(status_code: int, json_data=None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data if json_data is not None else []
    if status_code >= 400:
        resp.raise_for_status.side_effect = Exception(f"HTTP {status_code}")
    else:
        resp.raise_for_status.return_value = None
    return resp


class TestFetchSharedUsageToday:
    """ADDED 2026-09-12 alongside the llm_daily_summary migration -- proves
    the new one-row summary path is used when available, and that the
    original raw-row summing still works correctly as a fallback for a
    deployment that hasn't run 001_llm_daily_summary.sql yet."""

    def test_queries_the_correct_hkt_calendar_date(self):
        # FIXED 2026-09-12, found live: hkt_today_start_utc() returns a
        # naive-UTC instant (HKT midnight = 16:00 the PREVIOUS UTC calendar
        # day, always -- not just during some edge-case window), so its own
        # .date() is unconditionally one day behind the true HKT calendar
        # date. Querying with that value returned yesterday's summary row on
        # every single call, not just near a boundary. No time-mocking
        # needed: real `now` proves this deterministically either way.
        expected_day = dt.datetime.now(HKT).date().isoformat()
        with patch("app.llm_logging.SUPABASE_URL", "https://x.supabase.co"), \
             patch("app.llm_logging.SUPABASE_SERVICE_ROLE_KEY", "key"), \
             patch("app.llm_logging.httpx.get", return_value=_fake_response(200, [])) as mock_get:
            fetch_shared_usage_today()

        called_url = mock_get.call_args[0][0]
        called_params = mock_get.call_args[1]["params"]
        assert "llm_daily_summary" in called_url
        assert called_params["day"] == f"eq.{expected_day}"

    def test_uses_daily_summary_row_when_present(self):
        summary_row = {
            "total_calls": 42,
            "total_cost_usd": 1.2345,
            "calls_by_project": {"events": 30, "quant": 12},
        }
        with patch("app.llm_logging.SUPABASE_URL", "https://x.supabase.co"), \
             patch("app.llm_logging.SUPABASE_SERVICE_ROLE_KEY", "key"), \
             patch("app.llm_logging.httpx.get", return_value=_fake_response(200, [summary_row])) as mock_get:
            result = fetch_shared_usage_today()

        assert result == {"calls": 42, "cost_usd": 1.2345, "calls_by_project": {"events": 30, "quant": 12}}
        # exactly one call -- the summary row, never the raw llm_calls table
        assert mock_get.call_count == 1
        assert "llm_daily_summary" in mock_get.call_args[0][0]

    def test_no_row_yet_today_returns_zeros_without_falling_back(self):
        # the table exists but no insert has happened yet today (e.g. right
        # after HKT midnight) -- an empty result set, not a 404, so this must
        # NOT trigger the raw-row fallback.
        with patch("app.llm_logging.SUPABASE_URL", "https://x.supabase.co"), \
             patch("app.llm_logging.SUPABASE_SERVICE_ROLE_KEY", "key"), \
             patch("app.llm_logging.httpx.get", return_value=_fake_response(200, [])) as mock_get:
            result = fetch_shared_usage_today()

        assert result == {"calls": 0, "cost_usd": 0.0, "calls_by_project": {}}
        assert mock_get.call_count == 1

    def test_falls_back_to_raw_rows_when_summary_table_missing(self):
        # 404 on llm_daily_summary (migration not run yet) -- must fall back
        # to the original per-row summing against llm_calls, not just fail.
        # Round-number costs -- exact in binary floating point, so the sum
        # comparison below can use == rather than pytest.approx.
        raw_rows = [
            {"purpose": "events:ask", "cost_usd": 1.0, "created_at": "2026-09-12T01:00:00Z"},
            {"purpose": "events:ask", "cost_usd": 2.0, "created_at": "2026-09-12T02:00:00Z"},
            {"purpose": "quant:board_scan", "cost_usd": 5.0, "created_at": "2026-09-12T03:00:00Z"},
        ]
        responses = [_fake_response(404), _fake_response(200, raw_rows)]
        with patch("app.llm_logging.SUPABASE_URL", "https://x.supabase.co"), \
             patch("app.llm_logging.SUPABASE_SERVICE_ROLE_KEY", "key"), \
             patch("app.llm_logging.httpx.get", side_effect=responses) as mock_get:
            result = fetch_shared_usage_today()

        assert result == {
            "calls": 3,
            "cost_usd": 8.0,
            "calls_by_project": {"events": 2, "quant": 1},
        }
        assert mock_get.call_count == 2
        assert "llm_daily_summary" in mock_get.call_args_list[0][0][0]
        assert "llm_calls" in mock_get.call_args_list[1][0][0]

    def test_returns_empty_when_supabase_not_configured(self):
        with patch("app.llm_logging.SUPABASE_URL", ""), \
             patch("app.llm_logging.SUPABASE_SERVICE_ROLE_KEY", ""):
            result = fetch_shared_usage_today()
        assert result == {"calls": 0, "cost_usd": 0.0, "calls_by_project": {}}

    def test_fetch_is_metered(self):
        # the self-meter must see the summary read (and nothing else) --
        # cached reads never hit record(), so this proves the wiring point.
        from app import supabase_meter
        supabase_meter.reset()
        summary_row = {"total_calls": 3, "total_cost_usd": 0.5,
                       "calls_by_project": {"events": 3}}
        with patch("app.llm_logging.SUPABASE_URL", "https://x.supabase.co"), \
             patch("app.llm_logging.SUPABASE_SERVICE_ROLE_KEY", "key"), \
             patch("app.llm_logging.httpx.get",
                   return_value=_fake_response(200, [summary_row])):
            fetch_shared_usage_today()
        assert supabase_meter.snapshot() == {"GET llm_daily_summary": 1}
        supabase_meter.reset()
