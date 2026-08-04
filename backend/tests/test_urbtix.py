import datetime as dt
import xml.etree.ElementTree as ET

from app.connectors import urbtix

URBTIX_EVENT_XML = """
<EVENT>
  <ST_DATE>20260714</ST_DATE>
  <ED_DATE>20260721</ED_DATE>
  <EVENT_CODE>TEST01</EVENT_CODE>
  <EVENT_EG>Test Concert</EVENT_EG>
  <EVENT_TC>測試音樂會</EVENT_TC>
  <REFERENCE_LINK>https://www.urbtix.hk/event-detail/1</REFERENCE_LINK>
  <CATEGORY>
    <MAIN_CAT><EG>Music</EG><TC>音樂</TC></MAIN_CAT>
  </CATEGORY>
  <LOCATION>
    <VENUE_EG>TEST HALL</VENUE_EG>
    <VENUE_TC>測試會堂</VENUE_TC>
    <REGION_EG>Kowloon</REGION_EG>
    <REGION_TC>九龍</REGION_TC>
  </LOCATION>
  <PERFORMANCES>
    <PERFORMANCE>
      <REMARK_EG>A test concert.</REMARK_EG>
      <REMARK_TC>測試音樂會。</REMARK_TC>
    </PERFORMANCE>
  </PERFORMANCES>
</EVENT>
"""

URBTIX_ENGLISH_ONLY_XML = """
<EVENT>
  <ST_DATE>20260714</ST_DATE>
  <ED_DATE>20260714</ED_DATE>
  <EVENT_CODE>TEST02</EVENT_CODE>
  <EVENT_EG>English Only Event</EVENT_EG>
  <EVENT_TC></EVENT_TC>
  <REFERENCE_LINK>https://www.urbtix.hk/event-detail/2</REFERENCE_LINK>
  <CATEGORY><MAIN_CAT><EG>Talk</EG><TC>講座</TC></MAIN_CAT></CATEGORY>
  <LOCATION>
    <VENUE_EG>-</VENUE_EG>
    <VENUE_TC>-</VENUE_TC>
    <REGION_EG>Hong Kong Island</REGION_EG>
    <REGION_TC>香港</REGION_TC>
  </LOCATION>
</EVENT>
"""

URBTIX_BAD_DATE_XML = """
<EVENT>
  <ST_DATE>not-a-date</ST_DATE>
  <EVENT_EG>Broken Event</EVENT_EG>
</EVENT>
"""


class TestUrbtixConnector:
    def test_parses_bilingual_fields(self):
        el = ET.fromstring(URBTIX_EVENT_XML)
        result = urbtix._normalize(el)

        assert result is not None
        assert result.title == "Test Concert"
        assert result.title_native == "測試音樂會"
        assert result.native_lang == "zh-Hant"
        assert result.category == "Music"
        assert result.category_native == "音樂"
        assert result.venue_name == "TEST HALL"
        assert result.venue_name_native == "測試會堂"
        assert result.location == "Kowloon, Hong Kong"
        assert result.location_native == "九龍，香港"
        assert result.description == "A test concert."

    def test_placeholder_dash_venue_becomes_empty_not_literal_dash(self):
        el = ET.fromstring(URBTIX_ENGLISH_ONLY_XML)
        result = urbtix._normalize(el)

        assert result is not None
        assert result.venue_name == ""  # "-" is a real placeholder in the source feed

    def test_no_native_fields_when_title_matches_english(self):
        # EVENT_TC empty -> not bilingual -> every *_native field should be
        # None, not a copy of the English value.
        el = ET.fromstring(URBTIX_ENGLISH_ONLY_XML)
        result = urbtix._normalize(el)

        assert result.title_native is None
        assert result.native_lang is None
        assert result.category_native is None
        assert result.venue_name_native is None

    def test_missing_or_invalid_start_date_is_skipped(self):
        el = ET.fromstring(URBTIX_BAD_DATE_XML)
        assert urbtix._normalize(el) is None

    def test_end_of_day_sets_time_to_235959(self):
        el = ET.fromstring(URBTIX_EVENT_XML)
        result = urbtix._normalize(el)
        assert result.end.hour == 23 and result.end.minute == 59
