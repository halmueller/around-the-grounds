"""Tests for "listing" events: things available now (e.g. a beer on tap) rather
than scheduled for a date. Listings bypass the 7-day window, stay out of the
calendar feed, and must round-trip through the Temporal activity payloads.
Ordinary events must serialize exactly as before so existing sites' output
does not change."""

from datetime import datetime, timedelta

import pytest

from around_the_grounds.main import generate_web_data
from around_the_grounds.models import Event
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


class TestWebData:
    @pytest.mark.asyncio
    async def test_ordinary_event_has_no_kind_key(self) -> None:
        data = await generate_web_data([Event("k", "Venue", "Show", _now())])
        assert "kind" not in data["events"][0]

    @pytest.mark.asyncio
    async def test_listing_carries_kind(self) -> None:
        data = await generate_web_data([_listing()])
        assert data["events"][0]["kind"] == "listing"


class TestCalendarFeed:
    def test_listings_are_left_out_of_the_feed(self) -> None:
        listing = make_web_event(title="Fresh Hop Crikey", kind="listing")
        show = make_web_event(title="Woodshop BBQ")

        events = vevents(make_web_data([listing, show]))

        assert [str(e["SUMMARY"]) for e in events] == ["Woodshop BBQ"]


class TestTemporalPayloads:
    def test_ordinary_event_payload_is_unchanged(self) -> None:
        payload = ScrapeActivities._serialize_event(
            Event("k", "Venue", "Show", _now())
        )
        assert "kind" not in payload

    @pytest.mark.asyncio
    async def test_listing_round_trips_through_activities(self) -> None:
        payload = ScrapeActivities._serialize_event(_listing())
        assert payload["kind"] == "listing"

        data = await DeploymentActivities().generate_web_data(
            {"events": [payload], "errors": []}
        )

        assert data["events"][0]["kind"] == "listing"
