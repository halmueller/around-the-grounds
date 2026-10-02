"""Generic CSS-selector-driven HTML parser.

Triggered by source_type: "html" when no venue-specific parser is registered.
Extracts events using configurable CSS selectors from parser_config.

When the date or time shares an element with other text ("Saturday, Oct 17,
1-7pm THIRTY+ fresh hop beers…"), ``date_pattern`` / ``time_pattern`` pick
it out: a regex whose first group (or whole match) is parsed. An item whose
text has no match is skipped.

``link_selector`` picks the link to the event's own page inside each
container (or the container itself, when it is the link and nothing inside
matches); its ``href`` becomes ``Event.url``, resolved against the venue URL.
"""

import re

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from urllib.parse import urljoin

import aiohttp
from bs4 import BeautifulSoup, Tag

try:
    from zoneinfo import ZoneInfo  # type: ignore
except ImportError:
    from backports.zoneinfo import ZoneInfo  # type: ignore

from ...models import Event, Venue
from ..base import BaseParser


class HtmlSelectorParser(BaseParser):
    """Generic parser using CSS selectors from venue.parser_config."""

    def __init__(self, venue: Venue) -> None:
        super().__init__(venue)
        self.logger = logging.getLogger(self.__class__.__name__)

    async def parse(self, session: aiohttp.ClientSession) -> List[Event]:
        config = self.venue.parser_config or {}

        event_container = config.get("event_container", ".event-item")
        title_selector = config.get("title_selector", ".event-title")
        date_selector = config.get("date_selector", ".event-date")
        date_attribute: Optional[str] = config.get("date_attribute")
        time_selector: Optional[str] = config.get("time_selector")
        desc_selector: Optional[str] = config.get("description_selector")
        link_selector: Optional[str] = config.get("link_selector")
        date_format: str = config.get("date_format", "auto")
        # Optional: convert timezone-aware dates (e.g. ISO "...Z" attributes)
        # to this zone so a late-evening UTC timestamp keeps its local day.
        tz_name: Optional[str] = config.get("timezone")
        try:
            date_pattern = self._compile(config.get("date_pattern"))
            time_pattern = self._compile(config.get("time_pattern"))
        except re.error as e:
            raise ValueError(f"{self.venue.key}: invalid date/time pattern: {e}") from e

        soup = await self.fetch_page(session, self.venue.url)

        containers = soup.select(event_container)
        if not containers:
            self.logger.info(
                f"HtmlSelectorParser: no containers matching '{event_container}' "
                f"at {self.venue.url}"
            )
            return []

        events: List[Event] = []
        for container in containers:
            event = self._parse_container(
                container,
                title_selector=title_selector,
                date_selector=date_selector,
                date_attribute=date_attribute,
                time_selector=time_selector,
                desc_selector=desc_selector,
                date_format=date_format,
                date_pattern=date_pattern,
                time_pattern=time_pattern,
            )
            if event:
                if link_selector:
                    event.url = self._event_url(container, link_selector)
                events.append(self._localize(event, tz_name) if tz_name else event)

        self.logger.info(
            f"HtmlSelectorParser: {len(events)} events from {self.venue.url}"
        )
        return events

    def _parse_container(
        self,
        container: Tag,
        title_selector: str,
        date_selector: str,
        date_attribute: Optional[str],
        time_selector: Optional[str],
        desc_selector: Optional[str],
        date_format: str,
        date_pattern: Optional["re.Pattern[str]"] = None,
        time_pattern: Optional["re.Pattern[str]"] = None,
    ) -> Optional[Event]:
        """Extract a single Event from one HTML container."""
        try:
            title_el = container.select_one(title_selector)
            if not title_el:
                return None
            title = title_el.get_text(strip=True)
            if not title:
                return None

            date_el = container.select_one(date_selector)
            if not date_el:
                return None
            if date_attribute:
                date_text = str(date_el.get(date_attribute, "")).strip()
            else:
                date_text = date_el.get_text(separator=" ", strip=True)
            if date_pattern is not None:
                picked = self._pick(date_pattern, date_text)
                if picked is None:
                    return None
                date_text = picked
            date = self._parse_date(date_text, date_format)
            if not date:
                return None

            start_time: Optional[datetime] = None
            end_time: Optional[datetime] = None
            if time_selector:
                time_el = container.select_one(time_selector)
                time_text: Optional[str] = (
                    time_el.get_text(separator=" ", strip=True) if time_el else None
                )
                if time_text and time_pattern is not None:
                    time_text = self._pick(time_pattern, time_text)
                if time_text:
                    start_time, end_time = self._parse_time_range(time_text, date)

            description: Optional[str] = None
            if desc_selector:
                desc_el = container.select_one(desc_selector)
                if desc_el:
                    description = desc_el.get_text(strip=True) or None

            return Event(
                venue_key=self.venue.key,
                venue_name=self.venue.name,
                title=title,
                date=date,
                start_time=start_time,
                end_time=end_time,
                description=description,
                extraction_method="html",
            )
        except Exception as e:
            self.logger.debug(f"Error parsing container: {e}")
            return None

    def _event_url(self, container: Tag, link_selector: str) -> Optional[str]:
        """The http(s) URL of the event's own page, if the container links one."""
        try:
            link = container.select_one(link_selector) or container
            href = str(link.get("href") or "").strip()
            if not href:
                return None
            url = urljoin(self.venue.url, href)
            return url if url.startswith(("http://", "https://")) else None
        except Exception as e:
            self.logger.debug(f"Error reading event link: {e}")
            return None

    @staticmethod
    def _compile(pattern: Optional[str]) -> Optional["re.Pattern[str]"]:
        return re.compile(pattern, re.IGNORECASE) if pattern else None

    @staticmethod
    def _pick(pattern: "re.Pattern[str]", text: str) -> Optional[str]:
        """The pattern's first group (or whole match) in *text*, if any."""
        m = pattern.search(text)
        if not m:
            return None
        return (m.group(1) if pattern.groups else m.group(0)).strip() or None

    @staticmethod
    def _localize(event: Event, tz_name: str) -> Event:
        """Convert the event's timezone-aware datetimes to naive *tz_name* time."""
        zone = ZoneInfo(tz_name)

        def local(value: Optional[datetime]) -> Optional[datetime]:
            if value is None or value.tzinfo is None:
                return value
            return value.astimezone(zone).replace(tzinfo=None)

        event.date = local(event.date) or event.date
        event.start_time = local(event.start_time)
        event.end_time = local(event.end_time)
        return event

    def _parse_date(self, text: str, date_format: str) -> Optional[datetime]:
        """Parse a date string using the configured format or dateutil auto-parse."""
        text = text.strip()
        if not text:
            return None
        if date_format == "auto":
            try:
                from dateutil import parser as dateutil_parser

                return dateutil_parser.parse(text, fuzzy=True)
            except Exception:
                return None
        try:
            return datetime.strptime(text, date_format)
        except ValueError:
            return None

    @staticmethod
    def _extract_period(text: str) -> Optional[str]:
        """Extract AM/PM period from a time string, if present."""
        m = re.search(r"(am|pm)", text, re.IGNORECASE)
        return m.group(1).lower() if m else None

    def _parse_time_range(self, text: str, date: datetime) -> tuple:
        """Parse a time range like '7:00 PM - 10:00 PM' relative to date.

        Carries forward AM/PM from the start part when the end part lacks it,
        e.g. '5pm-8:30' → start=17:00, end=20:30, and back from the end when
        only it has one: '1-7pm' → 13:00-19:00, '11-2pm' → 11:00-14:00.
        """
        parts = re.split(r"\s*[-–—]\s*", text, maxsplit=1)
        start_time: Optional[datetime] = None
        end_time: Optional[datetime] = None

        start_period: Optional[str] = None
        if parts:
            start_period = self._extract_period(parts[0])
            start_time = self._parse_single_time(parts[0].strip(), date)

        if len(parts) > 1:
            end_time = self._parse_single_time(
                parts[1].strip(), date, default_period=start_period
            )
            end_period = self._extract_period(parts[1])
            if start_period is None and end_period:
                start_time = self._parse_single_time(
                    parts[0].strip(), date, default_period=end_period
                )
                # "11-2pm": a start later than the end is in the other half.
                if start_time and end_time and start_time > end_time:
                    other = "am" if end_period == "pm" else "pm"
                    start_time = self._parse_single_time(
                        parts[0].strip(), date, default_period=other
                    )

        return start_time, end_time

    def _parse_single_time(
        self,
        text: str,
        date: datetime,
        default_period: Optional[str] = None,
    ) -> Optional[datetime]:
        """Parse a single time string like '7:00 PM' relative to date.

        When the text has no AM/PM suffix and *default_period* is provided,
        the default is used instead (enables carry-forward from the start time),
        and a bare hour ("1") is accepted.
        """
        m = re.search(r"(\d{1,2}):(\d{2})\s*(am|pm)?", text, re.IGNORECASE)
        if not m:
            m = re.search(r"(\d{1,2})\s*(am|pm)", text, re.IGNORECASE)
            if not m and default_period:
                m = re.fullmatch(r"(\d{1,2})", text.strip())
            if not m:
                return None
            hour = int(m.group(1))
            minute = 0
            period: Optional[str] = (
                m.group(2).lower() if m.lastindex == 2 else default_period
            )
        else:
            hour = int(m.group(1))
            minute = int(m.group(2))
            period = m.group(3).lower() if m.group(3) else default_period

        if period == "pm" and hour != 12:
            hour += 12
        elif period == "am" and hour == 12:
            hour = 0

        try:
            return date.replace(hour=hour, minute=minute, second=0, microsecond=0)
        except ValueError:
            return None
