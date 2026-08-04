import datetime as dt
import xml.etree.ElementTree as ET

import httpx

from app.connectors.base import NormalizedEvent

FEED_URL_TEMPLATE = "https://fs-open-1304240968.cos.ap-hongkong.myqcloud.com/prod/gprd/URBTIX_eventBatch_{date}.xml"

"""
Hong Kong's official (LCSD-run) ticketing agency — concerts, theatre,
dance, exhibitions at HK public venues. Free, keyless, daily-updated open
data feed: https://data.gov.hk/en-data/dataset/hk-lcsd-event-urbtix-event
"""


def fetch() -> list[NormalizedEvent]:
    date_str = dt.datetime.utcnow().strftime("%Y%m%d")
    url = FEED_URL_TEMPLATE.format(date=date_str)

    try:
        resp = httpx.get(url, timeout=20)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
    except (httpx.HTTPError, ET.ParseError):
        return []

    out = [_normalize(ev) for ev in root.findall(".//EVENT")]
    return [e for e in out if e is not None]


def _normalize(ev: ET.Element) -> NormalizedEvent | None:
    start = _parse_date(_text(ev, "ST_DATE"))
    if start is None:
        return None
    end = _parse_date(_text(ev, "ED_DATE"), end_of_day=True)

    category = _text(ev.find("CATEGORY/MAIN_CAT"), "EG")
    category_tc = _text(ev.find("CATEGORY/MAIN_CAT"), "TC")

    venue = _text(ev.find("LOCATION"), "VENUE_EG")
    venue_tc = _text(ev.find("LOCATION"), "VENUE_TC")
    if venue == "-":
        venue = ""
    if venue_tc == "-":
        venue_tc = ""
    region = _text(ev.find("LOCATION"), "REGION_EG")
    region_tc = _text(ev.find("LOCATION"), "REGION_TC")
    location = f"{region}, Hong Kong" if region else "Hong Kong"
    location_tc = f"{region_tc}，香港" if region_tc else "香港"

    description = _text(ev.find("PERFORMANCES/PERFORMANCE"), "REMARK_EG") or category

    title_en = _text(ev, "EVENT_EG") or "Untitled event"
    title_tc = _text(ev, "EVENT_TC")
    is_bilingual = bool(title_tc) and title_tc != title_en

    return NormalizedEvent(
        source="urbtix",
        source_id=_text(ev, "EVENT_CODE"),
        source_url=_text(ev, "REFERENCE_LINK"),
        title=title_en,
        title_native=title_tc if is_bilingual else None,
        native_lang="zh-Hant" if is_bilingual else None,
        description=description,
        category=category,
        category_native=category_tc if is_bilingual and category_tc != category else None,
        start=start,
        end=end,
        venue_name=venue,
        venue_name_native=venue_tc if is_bilingual and venue_tc and venue_tc != venue else None,
        location=location,
        location_native=location_tc if is_bilingual and location_tc != location else None,
    )


def _text(el: ET.Element | None, tag: str) -> str:
    if el is None:
        return ""
    child = el.find(tag)
    return (child.text or "").strip() if child is not None else ""


def _parse_date(s: str, end_of_day: bool = False) -> dt.datetime | None:
    if not s or len(s) != 8 or not s.isdigit():
        return None
    try:
        d = dt.datetime.strptime(s, "%Y%m%d")
    except ValueError:
        return None
    if end_of_day:
        d = d.replace(hour=23, minute=59, second=59)
    return d
