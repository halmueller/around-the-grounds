"""Tests for per-venue event filtering (event_filter) and upcoming windows
(event_window_days) in the coordinator, used by fresh-hop event sources."""

from datetime import datetime, timedelta
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from around_the_grounds.models import Event, Venue
from around_the_grounds.scrapers.coordinator import ScraperCoordinator
from around_the_grounds.utils.listing_matcher import ListingMatcher
from around_the_grounds.utils.timezone_utils import now_in_site_timezone_naive


def _now() -> datetime:
    return now_in_site_timezone_naive("America/Los_Angeles")


def _event(title: str, days: int = 1, description: Any = None) -> Event:
    return Event(
        "src", "Source", title, _now() + timedelta(days=days), None, None, description
    )


async def _scrape(config: Dict[str, Any], events: List[Event]) -> List[Event]:
    venue = Venue("src", "Source", "https://example.com", "html", config)
    parser = MagicMock()
    parser.return_value.parse = AsyncMock(return_value=events)
    with patch(
        "around_the_grounds.scrapers.coordinator.ParserRegistry.get_parser",
        return_value=parser,
    ):
        result, error = await ScraperCoordinator().scrape_one(venue)
    assert error is None
    return result


class TestMatcherForEvents:
    def test_festivals_are_kept_when_default_exclusion_is_off(self) -> None:
        assert not ListingMatcher().matches("Fresh Hop Fest!")
        assert ListingMatcher(default_exclude=False).matches("Fresh Hop Fest!")

    def test_venue_exclusions_still_apply(self) -> None:
        matcher = ListingMatcher.from_config(
            {"listing_exclude": ["yakima"]}, default_exclude=False
        )
        assert not matcher.matches("Yakima Fresh Hop Ale Festival")


class TestEventFilter:
    @pytest.mark.asyncio
    async def test_keeps_only_fresh_hop_events(self) -> None:
        events = [
            _event("Fresh Hop Fest!"),
            _event("Trivia Night"),
            _event("Release party", description="Our wet hop IPA is here"),
        ]
        result = await _scrape({"event_filter": True}, events)
        assert [e.title for e in result] == ["Fresh Hop Fest!", "Release party"]

    @pytest.mark.asyncio
    async def test_no_filter_without_config(self) -> None:
        result = await _scrape({}, [_event("Trivia Night")])
        assert [e.title for e in result] == ["Trivia Night"]

    @pytest.mark.asyncio
    async def test_listings_pass_through(self) -> None:
        listing = _event("Oktoberfest")
        listing.kind = "listing"
        result = await _scrape({"event_filter": True}, [listing])
        assert result == [listing]


class TestEventWindow:
    @pytest.mark.asyncio
    async def test_default_window_is_seven_days(self) -> None:
        result = await _scrape({}, [_event("Fresh Hop Fest", days=30)])
        assert result == []

    @pytest.mark.asyncio
    async def test_configured_window(self) -> None:
        events = [_event("Soon", days=30), _event("Too far", days=90)]
        result = await _scrape({"event_window_days": 60}, events)
        assert [e.title for e in result] == ["Soon"]

    @pytest.mark.parametrize("bad", [0, -5, "60", True, None])
    def test_invalid_windows_are_ignored(self, bad: Any) -> None:
        venue = Venue(
            "v", "V", "https://x.com", parser_config={"event_window_days": bad}
        )
        assert ScraperCoordinator._event_windows([venue]) == {}

    def test_windows_are_per_venue(self) -> None:
        coordinator = ScraperCoordinator()
        far = _now() + timedelta(days=30)
        events = [Event("fest", "F", "A", far), Event("other", "O", "B", far)]
        result = coordinator._filter_and_sort_events(events, event_windows={"fest": 60})
        assert [e.venue_key for e in result] == ["fest"]
