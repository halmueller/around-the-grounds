"""Tests for the Airtable shared-page (airtable) tap-list parser. The fixture
is Rooftop's live ``readForSharedPages`` response from 2026-10-01, trimmed to
the fields read."""

import json
import re
from pathlib import Path
from typing import Any, Dict, Iterator

import aiohttp
import pytest
from aioresponses import aioresponses

from around_the_grounds.config.loader import load_site_config
from around_the_grounds.models import Venue
from around_the_grounds.parsers.generic.airtable import (
    AirtableParser,
    parse_shared_page,
    read_share_page,
)
from around_the_grounds.parsers.registry import ParserRegistry
from around_the_grounds.utils.host_throttle import listing_throttle

VENUE = {v.key: v for v in load_site_config("seattle-freshies").venues}["rooftop-taps"]
SHARE_URL = (VENUE.parser_config or {})["share_url"]
API_PATTERN = re.compile(
    r"^https://airtable\.com/v0\.3/application/appgD6ErPhbVR1opf/readForSharedPages\?"
)
SHARE_PAGE = (
    '<script>window.initData = {"sharedPageId":"pagYoJoWYElTkIv3K",'
    '"accessPolicy":"{\\"shareId\\":\\"shr4MCunGaXTu3WbV\\",'
    '\\"signature\\":\\"abc\\"}"};</script>'
)


@pytest.fixture(autouse=True)
def no_throttle() -> Iterator[None]:
    saved = listing_throttle.min_interval
    listing_throttle.min_interval = 0
    yield
    listing_throttle.min_interval = saved


@pytest.fixture
def payload(fixtures_dir: Path) -> Dict[str, Any]:
    data: Dict[str, Any] = json.loads(
        (fixtures_dir / "json" / "airtable_rooftop.json").read_text()
    )
    return data


def test_source_type_is_registered() -> None:
    venue = Venue("some-taproom", "Some Taproom", "https://example.com", "airtable")
    assert ParserRegistry.get_parser(venue) is AirtableParser
    assert AirtableParser.PRODUCES_LISTINGS


class TestReadSharePage:
    def test_finds_policy_and_page(self) -> None:
        assert read_share_page(SHARE_PAGE) == {
            "access_policy": '{"shareId":"shr4MCunGaXTu3WbV","signature":"abc"}',
            "page_id": "pagYoJoWYElTkIv3K",
        }

    def test_page_without_policy(self) -> None:
        with pytest.raises(ValueError, match="no access policy"):
            read_share_page("<html>Sign in</html>")


class TestParseSharedPage:
    def test_rooftop_rows_in_page_order(self, payload: Dict[str, Any]) -> None:
        entries = parse_shared_page(payload)
        assert len(entries) == 13
        first = entries[0]
        assert (first.name, first.style, first.abv) == (
            "La Azotea Mexi Lager",
            "Lager",  # a single-select choice id, resolved to its label
            "4.5%",  # stored as 0.045
        )
        assert (first.description or "").startswith("Escape en La Azotea!")
        assert [(e.name, e.style, e.abv) for e in entries[-1:]] == [
            ("Fresh Hop - Cascade WC IPA", "Fresh Hop IPA", "6.6%")
        ]

    def test_column_names_can_be_overridden(self, payload: Dict[str, Any]) -> None:
        entries = parse_shared_page(payload, {"style": "No Such Column"})
        assert entries[0].style is None
        assert entries[0].abv == "4.5%"

    def test_rows_without_a_name_are_skipped(self, payload: Dict[str, Any]) -> None:
        table = payload["data"]["tableSchemas"][0]
        rows = payload["data"]["preloadPageQueryResults"]["tableDataById"][table["id"]][
            "partialRowById"
        ]
        first_id = next(iter(rows))
        rows[first_id]["cellValuesByColumnId"].pop(table["primaryColumnId"])
        assert len(parse_shared_page(payload)) == 12

    def test_empty_payload(self) -> None:
        assert parse_shared_page({}) == []
        assert parse_shared_page({"data": {"preloadPageQueryResults": None}}) == []


class TestAirtableParser:
    @pytest.mark.asyncio
    async def test_parse_follows_share_page_to_data(
        self, payload: Dict[str, Any]
    ) -> None:
        with aioresponses() as m:
            m.get(SHARE_URL, status=200, body=SHARE_PAGE)
            m.get(API_PATTERN, status=200, payload=payload)
            async with aiohttp.ClientSession() as session:
                events = await AirtableParser(VENUE).parse(session)
            calls = [
                value
                for key, value in m.requests.items()
                if "readForSharedPages" in str(key[1])
            ][0]
        request = calls[0].kwargs
        assert request["params"]["accessPolicy"].startswith('{"shareId"')
        assert "pagYoJoWYElTkIv3K" in request["params"]["stringifiedObjectParams"]
        assert request["headers"]["x-airtable-application-id"] == "appgD6ErPhbVR1opf"
        assert [(e.title, e.category, e.description) for e in events] == [
            ("Rooftop Festbier", "festbier", "Lager · 4.6%"),
            ("Fresh Hop - Cascade WC IPA", "fresh-hop", "Fresh Hop IPA · 6.6%"),
        ]

    @pytest.mark.asyncio
    async def test_missing_share_url_raises(self) -> None:
        venue = Venue("x-taps", "X", "https://example.com", "airtable", {})
        async with aiohttp.ClientSession() as session:
            with pytest.raises(ValueError, match="needs a share_url"):
                await AirtableParser(venue).parse(session)

    @pytest.mark.asyncio
    async def test_invalid_json_raises(self) -> None:
        with aioresponses() as m:
            m.get(SHARE_URL, status=200, body=SHARE_PAGE)
            m.get(API_PATTERN, status=200, body="<html>nope</html>")
            async with aiohttp.ClientSession() as session:
                with pytest.raises(ValueError, match="Invalid JSON from Airtable"):
                    await AirtableParser(VENUE).parse(session)
