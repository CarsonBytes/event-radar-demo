import datetime as dt

from app.llm_logging import HKT, hkt_today_start_utc


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
