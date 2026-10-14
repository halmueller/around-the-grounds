"""The untappd-board parser: Untappd for Business display boards, whose page
carries the board as JSON in a data-react-props attribute (Cooper Mountain
Tigard; items cut down from 2026-10-14)."""

import html
import json
import logging
from typing import Any, Dict, List

import aiohttp
import pytest
from aioresponses import aioresponses

from around_the_grounds.config.loader import load_site_config
from around_the_grounds.models import Venue
from around_the_grounds.parsers.generic.listing_common import build_listings
from around_the_grounds.parsers.generic.untappd_board import (
    BOARD_URL,
    UntappdBoardParser,
    parse_untappd_board,
)
from around_the_grounds.parsers.registry import ParserRegistry

LOGGER = logging.getLogger(__name__)


def _item(name: Any, style: str, abv: Any, **extra: Any) -> Dict[str, Any]:
    item = {
        "name": name,
        "brewery": "Cooper Mountain Ale Works",
        "style": style,
        "abv": abv,
        "description": "",
        "hidden": False,
        "type": "beer",
    }
    item.update(extra)
    return item


def _menu(items: List[Dict[str, Any]], **extra: Any) -> Dict[str, Any]:
    menu = {
        "name": "Tigard Tap List",
        "unpublished": False,
        "draft": False,
        "sections": [{"name": "Cooper Mountain", "items": items}],
    }
    menu.update(extra)
    return menu


def _page(menus: List[Dict[str, Any]]) -> str:
    props = html.escape(json.dumps({"board": {"menus": menus}, "page": "1"}))
    return (
        "<html><body><div data-react-class='Board' "
        f'data-react-props="{props}"></div>'
        "<noscript>You need to enable JavaScript to run this app.</noscript>"
        "</body></html>"
    )


PAGE = _page(
    [
        _menu(
            [
                _item("Polo Match", "Lager - Polotmavé (Czech Amber)", "6.0"),
                _item("Hit Me With Your Fresh Hop", "Pale Ale - American", "5.8"),
                _item("You Can Fest If You Want To", "Festbier", "6.0"),
                _item("Retired Fest", "Festbier", "6.0", hidden=True),
                _item(None, "Fresh Hop IPA", "6.0"),
                _item("Root Beer", "Root Beer", "0.0"),
            ]
        ),
        _menu([_item("Draft Fresh Hop", "IPA", "6.5")], draft=True),
        _menu([_item("Old Fresh Hop", "IPA", "6.5")], unpublished=True),
    ]
)


def _venue(**config: Any) -> Venue:
    return Venue("pub-taps", "A Pub", "https://pub.example", "untappd-board", config)


def test_registered() -> None:
    assert ParserRegistry.get_parser(_venue()) is UntappdBoardParser
    assert UntappdBoardParser.PRODUCES_LISTINGS


def test_reads_visible_items_on_published_menus() -> None:
    entries = parse_untappd_board(PAGE)
    assert [(e.name, e.style, e.abv) for e in entries] == [
        ("Polo Match", "Lager - Polotmavé (Czech Amber)", "6%"),
        ("Hit Me With Your Fresh Hop", "Pale Ale - American", "5.8%"),
        ("You Can Fest If You Want To", "Festbier", "6%"),
        ("Root Beer", "Root Beer", None),
    ]
    assert entries[0].brewery == "Cooper Mountain Ale Works"


def test_listings() -> None:
    events = build_listings(
        _venue(), parse_untappd_board(PAGE), "untappd-board", LOGGER
    )
    assert [[e.title, e.category] for e in events] == [
        ["Hit Me With Your Fresh Hop", "fresh-hop"],
        ["You Can Fest If You Want To", "festbier"],
    ]


@pytest.mark.parametrize(
    "page",
    [
        "<html><body>You need to enable JavaScript.</body></html>",
        "<div data-react-props='not json'></div>",
        "<div data-react-props='{\"board\": {}}'></div>",
        '<div data-react-props=\'{"board": {"menus": 3}}\'></div>',
    ],
)
def test_page_without_board_data_raises(page: str) -> None:
    with pytest.raises(ValueError):
        parse_untappd_board(page)


@pytest.mark.asyncio
async def test_parser_fetches_the_board() -> None:
    venue = _venue(board_id=57393)
    with aioresponses() as m:
        m.get(BOARD_URL.format(board_id=57393), body=PAGE)
        async with aiohttp.ClientSession() as session:
            events = await UntappdBoardParser(venue).parse(session)
    assert [e.title for e in events] == [
        "Hit Me With Your Fresh Hop",
        "You Can Fest If You Want To",
    ]


@pytest.mark.asyncio
async def test_missing_board_id_raises() -> None:
    async with aiohttp.ClientSession() as session:
        with pytest.raises(ValueError, match="board_id"):
            await UntappdBoardParser(_venue()).parse(session)


def test_cooper_mountain_boards() -> None:
    venues = {v.key: v for v in load_site_config("portland-freshies").venues}
    boards = {
        key: (venues[key].parser_config or {})["board_id"]
        for key in ("cooper-mountain-tigard-taps", "cooper-mountain-sherwood-taps")
    }
    assert boards == {
        "cooper-mountain-tigard-taps": 57393,
        "cooper-mountain-sherwood-taps": 67649,
    }
