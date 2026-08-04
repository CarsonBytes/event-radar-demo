import datetime as dt
from dataclasses import dataclass


@dataclass
class NormalizedEvent:
    source: str
    source_id: str
    source_url: str
    title: str
    description: str
    category: str
    start: dt.datetime
    end: dt.datetime | None
    venue_name: str
    location: str
    image_url: str = ""
    title_native: str | None = None
    native_lang: str | None = None
    # Native-language versions of category/venue/location -- same native_lang
    # as title_native above (one source language per event, not per-field).
    # Only urbtix's feed actually carries these; other connectors leave them
    # unset and the frontend falls back to the English fields regardless of
    # the user's selected display language.
    category_native: str | None = None
    venue_name_native: str | None = None
    location_native: str | None = None
