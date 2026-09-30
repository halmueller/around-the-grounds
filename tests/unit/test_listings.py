"""Tests for "listing" events: things available now (e.g. a beer on tap) rather
than scheduled for a date. Listings bypass the 7-day window, stay out of the
calendar feed, and must round-trip through the Temporal activity payloads.
Ordinary events must serialize exactly as before so existing sites' output
does not change."""

import logging
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from around_the_grounds.config.loader import load_site_config
from around_the_grounds.main import generate_web_data
from around_the_grounds.models import Event, Venue
from around_the_grounds.parsers.registry import ParserRegistry
from around_the_grounds.scrapers.coordinator import ScraperCoordinator
from around_the_grounds.temporal.activities import (
    DeploymentActivities,
    ScrapeActivities,
)
from around_the_grounds.utils.timezone_utils import now_in_site_timezone_naive
from tests.unit.test_ics_generator import make_web_data, make_web_event, vevents


def _now() -> datetime:
    return now_in_site_timezone_naive("America/Los_Angeles")


def _listing(**overrides: object) -> Event:
    fields = dict(
        venue_key="growler-guys",
        venue_name="The Growler Guys",
        title="Fresh Hop Crikey",
        date=_now(),
        kind="listing",
    )
    fields.update(overrides)
    return Event(**fields)  # type: ignore[arg-type]


class TestEventKind:
    def test_kind_defaults_to_event(self) -> None:
        event = Event("k", "Venue", "Show", _now())
        assert event.kind == "event"

    def test_listing_kind(self) -> None:
        assert _listing().kind == "listing"


class TestCoordinatorWindow:
    def test_listing_outside_window_is_kept(self) -> None:
        coordinator = ScraperCoordinator()
        stale_date = _now() - timedelta(days=30)
        listing = _listing(date=stale_date)
        event = Event("k", "Venue", "Old Show", stale_date)

        result = coordinator._filter_and_sort_events([listing, event])

        assert result == [listing]


class TestMissingTimeWarning:
    @pytest.mark.asyncio
    async def test_listings_do_not_warn_about_missing_times(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        listing = _listing()
        timeless_event = Event("growler-guys", "The Growler Guys", "Trivia", _now())
        venue = Venue("growler-guys", "The Growler Guys", "https://example.com")
        parser = MagicMock()
        parser.return_value.parse = AsyncMock(return_value=[listing, timeless_event])

        with patch(
            "around_the_grounds.scrapers.coordinator.ParserRegistry.get_parser",
            return_value=parser,
        ):
            with caplog.at_level(logging.WARNING):
                events, error = await ScraperCoordinator().scrape_one(venue)

        assert error is None
        assert len(events) == 2
        # Only the timeless ordinary event counts toward the warning.
        assert "1/2 events from The Growler Guys are missing start_time" in caplog.text


class TestWebData:
    @pytest.mark.asyncio
    async def test_ordinary_event_has_no_kind_key(self) -> None:
        data = await generate_web_data([Event("k", "Venue", "Show", _now())])
        assert "kind" not in data["events"][0]

    @pytest.mark.asyncio
    async def test_listing_carries_kind(self) -> None:
        data = await generate_web_data([_listing()])
        assert data["events"][0]["kind"] == "listing"


class TestListingVenues:
    @pytest.mark.asyncio
    async def test_tap_list_site_lists_its_listing_venues(self) -> None:
        site = load_site_config("seattle-fall-beers")
        data = await generate_web_data([], site=site)

        keys = [v["key"] for v in data["listing_venues"]]
        assert "fair-isle-taps" in keys
        assert all(key.endswith("-taps") for key in keys)  # no event sources
        assert keys == [v.key for v in site.venues if v.key.endswith("-taps")]
        fair_isle = data["listing_venues"][keys.index("fair-isle-taps")]
        assert fair_isle == {
            "key": "fair-isle-taps",
            "name": "Fair Isle Brewing (Ballard)",
            "url": "https://fairislebrewing.com/location/taproom/",
        }

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "site_key", ["ballard-food-trucks", "park-slope-music", "childrens-events"]
    )
    async def test_other_sites_are_unchanged(self, site_key: str) -> None:
        data = await generate_web_data([], site=load_site_config(site_key))
        assert "listing_venues" not in data

    def test_only_tap_list_parsers_produce_listings(self) -> None:
        listing_types = {
            "untappd-embed",
            "untappd-venue",
            "sheet-taplist",
            "html-taplist",
            "craftpeak-wot",
            "digitalpour",
            "text-taplist",
        }
        for source_type, parser in ParserRegistry._generic.items():
            assert parser.PRODUCES_LISTINGS == (
                source_type in listing_types
            ), source_type
        assert not any(p.PRODUCES_LISTINGS for p in ParserRegistry._specific.values())


class TestCalendarFeed:
    def test_listings_are_left_out_of_the_feed(self) -> None:
        listing = make_web_event(title="Fresh Hop Crikey", kind="listing")
        show = make_web_event(title="Woodshop BBQ")

        events = vevents(make_web_data([listing, show]))

        assert [str(e["SUMMARY"]) for e in events] == ["Woodshop BBQ"]


class TestTemporalPayloads:
    def test_ordinary_event_payload_is_unchanged(self) -> None:
        payload = ScrapeActivities._serialize_event(Event("k", "Venue", "Show", _now()))
        assert "kind" not in payload

    @pytest.mark.asyncio
    async def test_listing_round_trips_through_activities(self) -> None:
        payload = ScrapeActivities._serialize_event(_listing())
        assert payload["kind"] == "listing"

        data = await DeploymentActivities().generate_web_data(
            {"events": [payload], "errors": []}
        )

        assert data["events"][0]["kind"] == "listing"
