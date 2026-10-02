"""Tests for the fresh-hop event sources of seattle-freshies. Fixtures are
live pages saved on 2026-09-29 and 2026-09-30: Georgetown Brewing's event
list, Beveridge Place Pub's events page, Stoup's events page, and Fremont's
Squarespace events collection (JSON)."""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List
from zoneinfo import ZoneInfo

import aiohttp
import pytest
from aioresponses import aioresponses
from bs4 import BeautifulSoup
from freezegun import freeze_time

from around_the_grounds.config.loader import load_site_config
from around_the_grounds.models import Venue
from around_the_grounds.parsers.generic import HtmlSelectorParser
from around_the_grounds.parsers.generic.squarespace_events import (
    SquarespaceEventsParser,
    parse_squarespace_events,
)
from around_the_grounds.scrapers.coordinator import ScraperCoordinator
from around_the_grounds.utils.host_throttle import listing_throttle

VENUES = {v.key: v for v in load_site_config("seattle-freshies").venues}
# 8 PM Sept 29 Pacific, when the fixtures were saved.
NOW = "2026-09-30 03:00:00"


@pytest.fixture(autouse=True)
def no_throttle() -> Iterator[None]:
    saved = listing_throttle.min_interval
    listing_throttle.min_interval = 0
    yield
    listing_throttle.min_interval = saved


def _html(fixtures_dir: Path, name: str) -> str:
    return (fixtures_dir / "html" / name).read_text()


class TestGeorgetownEventList:
    @pytest.fixture
    def venue(self) -> Venue:
        return VENUES["georgetown-event-list"]

    @pytest.mark.asyncio
    async def test_parser_reads_seattle_items_in_local_time(
        self, venue: Venue, fixtures_dir: Path
    ) -> None:
        with aioresponses() as m:
            m.get(
                venue.url,
                status=200,
                body=_html(fixtures_dir, "events_georgetown.html"),
            )
            async with aiohttp.ClientSession() as session:
                events = await HtmlSelectorParser(venue).parse(session)

        # 6 of the 13 items are tagged Seattle; Yakima's festival is not.
        # Beveridge Place's fest is left out: its own events page lists it.
        assert len(events) == 5
        assert not any("State Fair Park" in (e.place or "") for e in events)
        assert not any("Beveridge" in (e.place or "") for e in events)
        # The host venue is the event's place, not its description.
        assert all(e.place and e.description is None for e in events)
        ravenna = next(e for e in events if e.place == "Ravenna Brewing, Ravenna")
        assert ravenna.title == "Fresh Hop Fest!"
        # 2026-10-10T18:00:00Z is 11 AM Pacific, stored naive.
        assert ravenna.date == datetime(2026, 10, 10, 11, 0)
        # Each event links its own page, not the list.
        assert {e.title: e.url for e in events}["PNA Winter Beer Taste"] == (
            "https://georgetownbeer.com/blogs/news/pna-winter-beer-taste"
        )
        assert all(
            (e.url or "").startswith("https://georgetownbeer.com/blogs/news/")
            for e in events
        )

    @freeze_time(NOW)
    @pytest.mark.asyncio
    async def test_coordinator_keeps_every_event_and_tags_the_seasonal(
        self, venue: Venue, fixtures_dir: Path
    ) -> None:
        # The list is all beer events, so the venue's event_include keeps
        # everything; only the fresh-hop fest carries a category.
        with aioresponses() as m:
            m.get(
                venue.url,
                status=200,
                body=_html(fixtures_dir, "events_georgetown.html"),
            )
            events, error = await ScraperCoordinator().scrape_one(venue)

        assert error is None
        assert [(e.title, e.category) for e in events] == [
            ("Fresh Hop Fest!", "fresh-hop"),
            ("Night of the Bodhi", None),
            ("PNA Winter Beer Taste", None),
            ("Winter Beer Fest", None),
        ]


def test_timezone_is_opt_in(fixtures_dir: Path) -> None:
    """Without a timezone the html parser keeps aware dates as before."""
    config = dict(VENUES["georgetown-event-list"].parser_config or {})
    del config["timezone"]
    venue = Venue("gt", "Georgetown", "https://georgetownbeer.com/", "html", config)
    parser = HtmlSelectorParser(venue)
    soup = BeautifulSoup(_html(fixtures_dir, "events_georgetown.html"), "html.parser")
    container = soup.select_one(config["event_container"])
    assert container is not None
    event = parser._parse_container(
        container,
        title_selector=config["title_selector"],
        date_selector=config["date_selector"],
        date_attribute=config["date_attribute"],
        time_selector=None,
        desc_selector=None,
        date_format="auto",
    )
    assert event is not None and event.date.tzinfo is not None


class TestBeveridgePlaceEvents:
    @pytest.fixture
    def venue(self) -> Venue:
        return VENUES["beveridge-place-events"]

    @freeze_time(NOW)
    @pytest.mark.asyncio
    async def test_reads_the_fest_date_and_hours(
        self, venue: Venue, fixtures_dir: Path
    ) -> None:
        with aioresponses() as m:
            m.get(
                venue.url,
                status=200,
                body=_html(fixtures_dir, "events_beveridge_place.html"),
            )
            async with aiohttp.ClientSession() as session:
                events = await HtmlSelectorParser(venue).parse(session)

        # The weekly quiz, monthly book club, and drag bingo cards give no date.
        assert [(e.title, e.start_time, e.end_time) for e in events] == [
            (
                "BPP/WBB Fresh Hop Festival!",
                datetime(2026, 10, 17, 13, 0),
                datetime(2026, 10, 17, 19, 0),
            )
        ]
        assert (events[0].url or "").startswith("https://beveridgeplacepub.com/events/")

    @freeze_time(NOW)
    @pytest.mark.asyncio
    async def test_coordinator_keeps_the_fest(
        self, venue: Venue, fixtures_dir: Path
    ) -> None:
        with aioresponses() as m:
            m.get(
                venue.url,
                status=200,
                body=_html(fixtures_dir, "events_beveridge_place.html"),
            )
            events, error = await ScraperCoordinator().scrape_one(venue)

        assert error is None
        assert [e.date.date().isoformat() for e in events] == ["2026-10-17"]


class TestStoupEvents:
    @freeze_time(NOW)
    @pytest.mark.asyncio
    async def test_reads_only_its_location_section(self, fixtures_dir: Path) -> None:
        venue = VENUES["stoup-ballard-events"]
        with aioresponses() as m:
            m.get(venue.url, status=200, body=_html(fixtures_dir, "events_stoup.html"))
            async with aiohttp.ClientSession() as session:
                events = await HtmlSelectorParser(venue).parse(session)

        assert len(events) == 5
        # The Yakima Valley showcase is in Stoup's "other" (offsite) section.
        assert not any("Fresh Hop" in e.title for e in events)
        # The container is itself the link to the event's page.
        assert all(
            (e.url or "").startswith("https://www.stoupbrewing.com/stoup-event/")
            for e in events
        )
        first = events[0]
        assert first.date.year == 2026
        assert first.start_time is not None


class TestSquarespaceEvents:
    @pytest.fixture
    def payload(self, fixtures_dir: Path) -> Dict[str, Any]:
        loaded: Dict[str, Any] = json.loads(
            (fixtures_dir / "json" / "squarespace_events_fremont.json").read_text()
        )
        return loaded

    def test_parses_items_in_local_time(self, payload: Dict[str, Any]) -> None:
        events = parse_squarespace_events(
            payload,
            "fremont-events",
            "Fremont",
            "America/Los_Angeles",
            base_url="https://www.fremontbrewing.com/fremont-ubg-events",
        )
        assert len(events) == 4
        party = next(e for e in events if "Oktoberfest" in e.title)
        assert party.url == (
            "https://www.fremontbrewing.com/fremont-ubg-events/"
            "fremont-brewing-oktoberfest-party"
        )
        release = next(e for e in events if e.title == "Fresh Hop Releases")
        assert release.start_time is not None
        assert release.start_time.tzinfo is None
        start_ms = next(
            i["startDate"]
            for i in payload["items"]
            if i["title"] == "Fresh Hop Releases"
        )
        expected = datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc).astimezone(
            ZoneInfo("America/Los_Angeles")
        )
        assert release.start_time == expected.replace(tzinfo=None, microsecond=0)

    def test_skips_bad_items_and_duplicates(self) -> None:
        item = {"id": "a", "title": "Fresh Hop Night", "startDate": 1790000000000}
        payload = {
            "upcoming": [item, {"id": "b", "title": "", "startDate": 1}],
            "past": [item, {"id": "c", "title": "No date"}],
        }
        events = parse_squarespace_events(payload, "k", "V", "America/Los_Angeles")
        assert [e.title for e in events] == ["Fresh Hop Night"]

    def test_description_combines_location_and_excerpt(self) -> None:
        item = {
            "id": "a",
            "title": "Tap takeover",
            "startDate": 1790000000000,
            "location": {"addressTitle": "Fremont Urban Beer Garden"},
            "excerpt": "<p>Fresh hop &amp; friends</p>",
        }
        [event] = parse_squarespace_events({"items": [item]}, "k", "V", "UTC")
        assert event.description == "Fremont Urban Beer Garden · Fresh hop & friends"

    @pytest.mark.asyncio
    async def test_fetches_collection_json(self, payload: Dict[str, Any]) -> None:
        venue = VENUES["fremont-events"]
        with aioresponses() as m:
            m.get(f"{venue.url}?format=json", status=200, body=json.dumps(payload))
            async with aiohttp.ClientSession() as session:
                events = await SquarespaceEventsParser(venue).parse(session)
        assert len(events) == 4

    @pytest.mark.asyncio
    async def test_non_json_raises(self) -> None:
        venue = VENUES["fremont-events"]
        with aioresponses() as m:
            m.get(f"{venue.url}?format=json", status=200, body="<html>nope</html>")
            async with aiohttp.ClientSession() as session:
                with pytest.raises(ValueError, match="not JSON"):
                    await SquarespaceEventsParser(venue).parse(session)


class TestEventLinks:
    HTML = """
    <div class="item"><a class="more" href="/events/one">One</a>
      <span class="title">One</span><span class="date">2026-10-10</span></div>
    <div class="item"><a class="more" href="javascript:alert(1)">Two</a>
      <span class="title">Two</span><span class="date">2026-10-11</span></div>
    <div class="item">
      <span class="title">Three</span><span class="date">2026-10-12</span></div>
    """

    async def _parse(self, config: Dict[str, Any]) -> List[Any]:
        base = {
            "event_container": ".item",
            "title_selector": ".title",
            "date_selector": ".date",
        }
        venue = Venue("v", "V", "https://v.example/events/", "html", {**base, **config})
        with aioresponses() as m:
            m.get(venue.url, status=200, body=self.HTML)
            async with aiohttp.ClientSession() as session:
                return await HtmlSelectorParser(venue).parse(session)

    @pytest.mark.asyncio
    async def test_link_selector_gives_absolute_http_urls_only(self) -> None:
        events = await self._parse({"link_selector": "a.more"})
        assert [e.url for e in events] == ["https://v.example/events/one", None, None]

    @pytest.mark.asyncio
    async def test_no_links_or_places_without_their_selectors(self) -> None:
        events = await self._parse({})
        assert [e.url for e in events] == [None, None, None]
        assert [e.place for e in events] == [None, None, None]

    @pytest.mark.asyncio
    async def test_place_selector_reads_where_the_event_is_held(self) -> None:
        events = await self._parse({"place_selector": ".more"})
        assert [e.place for e in events] == ["One", "Two", None]
