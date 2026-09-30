"""Tests for the generic CSS-selector HTML parser."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from bs4 import BeautifulSoup

from around_the_grounds.models import Venue, Event
from around_the_grounds.parsers.generic.html_selector import HtmlSelectorParser


def _make_venue(
    key: str = "union-hall",
    url: str = "https://www.unionhallny.com/calendar",
    parser_config: dict = None,
) -> Venue:
    return Venue(
        key=key,
        name="Union Hall",
        url=url,
        source_type="html",
        parser_config=parser_config
        or {
            "event_container": ".event-item",
            "title_selector": ".event-title",
            "date_selector": ".event-date",
            "time_selector": ".event-time",
            "date_format": "auto",
        },
    )


SIMPLE_HTML = """
<html><body>
  <div class="event-item">
    <span class="event-title">Jazz Trio</span>
    <span class="event-date">July 4, 2025</span>
    <span class="event-time">7:00 PM - 10:00 PM</span>
  </div>
  <div class="event-item">
    <span class="event-title">Rock Night</span>
    <span class="event-date">July 5, 2025</span>
    <span class="event-time">8:00 PM - 11:00 PM</span>
  </div>
</body></html>
"""

NO_EVENTS_HTML = """
<html><body>
  <div class="calendar-empty">No events this week.</div>
</body></html>
"""


class TestHtmlSelectorParser:
    """Tests for HtmlSelectorParser."""

    @pytest.mark.asyncio
    async def test_parse_returns_events(self) -> None:
        """Parser extracts events using CSS selectors."""
        venue = _make_venue()
        parser = HtmlSelectorParser(venue)

        with patch.object(
            parser, "fetch_page", return_value=BeautifulSoup(SIMPLE_HTML, "lxml")
        ):
            events = await parser.parse(MagicMock())

        assert len(events) == 2
        assert events[0].title == "Jazz Trio"
        assert events[0].venue_key == "union-hall"
        assert events[0].venue_name == "Union Hall"
        assert events[0].extraction_method == "html"

    @pytest.mark.asyncio
    async def test_parse_extracts_date(self) -> None:
        """Parser parses dates via dateutil auto mode."""
        venue = _make_venue()
        parser = HtmlSelectorParser(venue)

        with patch.object(
            parser, "fetch_page", return_value=BeautifulSoup(SIMPLE_HTML, "lxml")
        ):
            events = await parser.parse(MagicMock())

        from datetime import datetime

        assert events[0].date.year == 2025
        assert events[0].date.month == 7
        assert events[0].date.day == 4

    @pytest.mark.asyncio
    async def test_parse_extracts_time_range(self) -> None:
        """Parser parses start and end times from time selector."""
        venue = _make_venue()
        parser = HtmlSelectorParser(venue)

        with patch.object(
            parser, "fetch_page", return_value=BeautifulSoup(SIMPLE_HTML, "lxml")
        ):
            events = await parser.parse(MagicMock())

        assert events[0].start_time is not None
        assert events[0].start_time.hour == 19  # 7 PM
        assert events[0].start_time.minute == 0
        assert events[0].end_time is not None
        assert events[0].end_time.hour == 22  # 10 PM

    @pytest.mark.asyncio
    async def test_parse_no_matching_containers(self) -> None:
        """Returns empty list when no containers match the selector."""
        venue = _make_venue()
        parser = HtmlSelectorParser(venue)

        with patch.object(
            parser, "fetch_page", return_value=BeautifulSoup(NO_EVENTS_HTML, "lxml")
        ):
            events = await parser.parse(MagicMock())

        assert events == []

    @pytest.mark.asyncio
    async def test_parse_skips_container_missing_title(self) -> None:
        """Containers without a title element are skipped."""
        html = """
        <html><body>
          <div class="event-item">
            <span class="event-date">July 4, 2025</span>
          </div>
        </body></html>
        """
        venue = _make_venue()
        parser = HtmlSelectorParser(venue)

        with patch.object(
            parser, "fetch_page", return_value=BeautifulSoup(html, "lxml")
        ):
            events = await parser.parse(MagicMock())

        assert events == []

    @pytest.mark.asyncio
    async def test_parse_skips_container_missing_date(self) -> None:
        """Containers without a date element are skipped."""
        html = """
        <html><body>
          <div class="event-item">
            <span class="event-title">Jazz Night</span>
          </div>
        </body></html>
        """
        venue = _make_venue()
        parser = HtmlSelectorParser(venue)

        with patch.object(
            parser, "fetch_page", return_value=BeautifulSoup(html, "lxml")
        ):
            events = await parser.parse(MagicMock())

        assert events == []

    @pytest.mark.asyncio
    async def test_parse_skips_unparseable_date(self) -> None:
        """Containers with unparseable dates are skipped."""
        html = """
        <html><body>
          <div class="event-item">
            <span class="event-title">Jazz Night</span>
            <span class="event-date">not-a-date</span>
          </div>
        </body></html>
        """
        venue = _make_venue(
            parser_config={
                "event_container": ".event-item",
                "title_selector": ".event-title",
                "date_selector": ".event-date",
                "date_format": "%Y-%m-%d",  # strict format — won't match "not-a-date"
            }
        )
        parser = HtmlSelectorParser(venue)

        with patch.object(
            parser, "fetch_page", return_value=BeautifulSoup(html, "lxml")
        ):
            events = await parser.parse(MagicMock())

        assert events == []

    @pytest.mark.asyncio
    async def test_parse_with_description_selector(self) -> None:
        """Description is extracted when description_selector is configured."""
        html = """
        <html><body>
          <div class="event-item">
            <span class="event-title">Jazz Trio</span>
            <span class="event-date">July 4, 2025</span>
            <span class="event-desc">Great live music</span>
          </div>
        </body></html>
        """
        venue = _make_venue(
            parser_config={
                "event_container": ".event-item",
                "title_selector": ".event-title",
                "date_selector": ".event-date",
                "description_selector": ".event-desc",
                "date_format": "auto",
            }
        )
        parser = HtmlSelectorParser(venue)

        with patch.object(
            parser, "fetch_page", return_value=BeautifulSoup(html, "lxml")
        ):
            events = await parser.parse(MagicMock())

        assert len(events) == 1
        assert events[0].description == "Great live music"

    @pytest.mark.asyncio
    async def test_parse_no_time_selector(self) -> None:
        """When no time_selector is configured, start_time and end_time are None."""
        venue = _make_venue(
            parser_config={
                "event_container": ".event-item",
                "title_selector": ".event-title",
                "date_selector": ".event-date",
                "date_format": "auto",
            }
        )
        parser = HtmlSelectorParser(venue)

        with patch.object(
            parser, "fetch_page", return_value=BeautifulSoup(SIMPLE_HTML, "lxml")
        ):
            events = await parser.parse(MagicMock())

        assert len(events) == 2
        assert events[0].start_time is None
        assert events[0].end_time is None

    def test_parse_date_auto_mode(self) -> None:
        """_parse_date returns datetime for fuzzy auto format."""
        venue = _make_venue()
        parser = HtmlSelectorParser(venue)

        result = parser._parse_date("July 4, 2025", "auto")
        assert result is not None
        assert result.month == 7
        assert result.day == 4
        assert result.year == 2025

    def test_parse_date_strptime_format(self) -> None:
        """_parse_date uses strptime when explicit format given."""
        venue = _make_venue()
        parser = HtmlSelectorParser(venue)

        result = parser._parse_date("2025-07-04", "%Y-%m-%d")
        assert result is not None
        assert result.year == 2025
        assert result.month == 7
        assert result.day == 4

    def test_parse_date_invalid_returns_none(self) -> None:
        """_parse_date returns None for text that can't be parsed."""
        venue = _make_venue()
        parser = HtmlSelectorParser(venue)

        result = parser._parse_date("not-a-date", "%Y-%m-%d")
        assert result is None

    def test_parse_date_empty_returns_none(self) -> None:
        """_parse_date returns None for empty string."""
        venue = _make_venue()
        parser = HtmlSelectorParser(venue)

        result = parser._parse_date("", "auto")
        assert result is None

    def test_parse_time_range_start_and_end(self) -> None:
        """_parse_time_range extracts both start and end times."""
        from datetime import datetime

        venue = _make_venue()
        parser = HtmlSelectorParser(venue)
        date = datetime(2025, 7, 4)

        start, end = parser._parse_time_range("7:00 PM - 10:00 PM", date)
        assert start is not None
        assert start.hour == 19
        assert end is not None
        assert end.hour == 22

    def test_parse_time_range_start_only(self) -> None:
        """_parse_time_range handles single time (no range separator)."""
        from datetime import datetime

        venue = _make_venue()
        parser = HtmlSelectorParser(venue)
        date = datetime(2025, 7, 4)

        start, end = parser._parse_time_range("7:00 PM", date)
        assert start is not None
        assert start.hour == 19
        assert end is None

    def test_parse_time_am(self) -> None:
        """_parse_single_time handles AM times correctly."""
        from datetime import datetime

        venue = _make_venue()
        parser = HtmlSelectorParser(venue)
        date = datetime(2025, 7, 4)

        result = parser._parse_single_time("11:30 AM", date)
        assert result is not None
        assert result.hour == 11
        assert result.minute == 30

    def test_parse_time_midnight(self) -> None:
        """_parse_single_time handles 12:00 AM as midnight."""
        from datetime import datetime

        venue = _make_venue()
        parser = HtmlSelectorParser(venue)
        date = datetime(2025, 7, 4)

        result = parser._parse_single_time("12:00 AM", date)
        assert result is not None
        assert result.hour == 0

    def test_parse_time_noon(self) -> None:
        """_parse_single_time handles 12:00 PM as noon."""
        from datetime import datetime

        venue = _make_venue()
        parser = HtmlSelectorParser(venue)
        date = datetime(2025, 7, 4)

        result = parser._parse_single_time("12:00 PM", date)
        assert result is not None
        assert result.hour == 12

    def test_parse_time_range_compact_pm_carry_forward(self) -> None:
        """'5pm-8:30' carries PM forward → end=20:30."""
        from datetime import datetime

        venue = _make_venue()
        parser = HtmlSelectorParser(venue)
        date = datetime(2025, 7, 4)

        start, end = parser._parse_time_range("5pm-8:30", date)
        assert start is not None
        assert start.hour == 17
        assert end is not None
        assert end.hour == 20
        assert end.minute == 30

    def test_parse_time_range_compact_am_carry_forward(self) -> None:
        """'9am-11:30' carries AM forward → end=11:30."""
        from datetime import datetime

        venue = _make_venue()
        parser = HtmlSelectorParser(venue)
        date = datetime(2025, 7, 4)

        start, end = parser._parse_time_range("9am-11:30", date)
        assert start is not None
        assert start.hour == 9
        assert end is not None
        assert end.hour == 11
        assert end.minute == 30

    def test_parse_time_range_explicit_periods_no_carry(self) -> None:
        """'5pm-11:00 PM' — both have explicit periods, no carry needed."""
        from datetime import datetime

        venue = _make_venue()
        parser = HtmlSelectorParser(venue)
        date = datetime(2025, 7, 4)

        start, end = parser._parse_time_range("5pm-11:00 PM", date)
        assert start is not None
        assert start.hour == 17
        assert end is not None
        assert end.hour == 23
        assert end.minute == 0

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("1-7pm", ((13, 0), (19, 0))),  # am/pm carried back from the end
            ("11-2pm", ((11, 0), (14, 0))),  # start later than end: other half
            ("6:30-9pm", ((18, 30), (21, 0))),
            ("5pm-8", ((17, 0), (20, 0))),  # bare end hour takes the start's
        ],
    )
    def test_parse_time_range_period_from_either_side(
        self, text: str, expected: tuple
    ) -> None:
        from datetime import datetime

        parser = HtmlSelectorParser(_make_venue())
        start, end = parser._parse_time_range(text, datetime(2026, 10, 17))
        assert start is not None and end is not None
        assert ((start.hour, start.minute), (end.hour, end.minute)) == expected

    def test_bare_hour_without_any_period_is_not_a_time(self) -> None:
        from datetime import datetime

        parser = HtmlSelectorParser(_make_venue())
        assert parser._parse_time_range("1-7", datetime(2026, 10, 17)) == (None, None)


EXCERPT_HTML = """
<html><body>
  <div class="card">
    <h1 class="title">Fresh Hop Festival!</h1>
    <p class="excerpt">Saturday, Oct 17, 1-7pm
    THIRTY+ wet/fresh hop beers on tap, 30 taps!</p>
  </div>
  <div class="card">
    <h1 class="title">Quiz Night</h1>
    <p class="excerpt">Join us EVERY Wed at 8pm for two hours of questions!</p>
  </div>
</body></html>
"""

EXCERPT_CONFIG = {
    "event_container": ".card",
    "title_selector": ".title",
    "date_selector": ".excerpt",
    "date_pattern": r"\b(?:sat|sun)(?:urday|day)?,?\s+([a-z]{3,9}\.?\s+\d{1,2})",
    "time_selector": ".excerpt",
    "time_pattern": r"\b\d{1,2}(?::\d{2})?\s*(?:am|pm)?\s*[-–]\s*\d{1,2}\s*(?:am|pm)\b",
}


class TestDateAndTimePatterns:
    @pytest.mark.asyncio
    async def test_patterns_pick_date_and_time_out_of_an_excerpt(self) -> None:
        from datetime import datetime

        parser = HtmlSelectorParser(_make_venue(parser_config=EXCERPT_CONFIG))
        with patch.object(
            parser, "fetch_page", return_value=BeautifulSoup(EXCERPT_HTML, "lxml")
        ):
            events = await parser.parse(MagicMock())

        # Quiz Night has no date matching date_pattern, so it is skipped.
        assert [e.title for e in events] == ["Fresh Hop Festival!"]
        assert events[0].date.date() == datetime(datetime.now().year, 10, 17).date()
        assert events[0].start_time is not None and events[0].start_time.hour == 13
        assert events[0].end_time is not None and events[0].end_time.hour == 19

    @pytest.mark.asyncio
    async def test_time_pattern_without_a_match_leaves_times_empty(self) -> None:
        config = {**EXCERPT_CONFIG, "time_pattern": r"\bdoors at (\d+pm)"}
        parser = HtmlSelectorParser(_make_venue(parser_config=config))
        with patch.object(
            parser, "fetch_page", return_value=BeautifulSoup(EXCERPT_HTML, "lxml")
        ):
            events = await parser.parse(MagicMock())

        assert len(events) == 1
        assert events[0].start_time is None and events[0].end_time is None

    @pytest.mark.asyncio
    async def test_invalid_pattern_raises(self) -> None:
        config = {**EXCERPT_CONFIG, "date_pattern": "(unclosed"}
        parser = HtmlSelectorParser(_make_venue(parser_config=config))
        with pytest.raises(ValueError, match="invalid date/time pattern"):
            await parser.parse(MagicMock())
