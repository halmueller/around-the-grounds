"""Tap lists published as Canva designs (Old Stove Brewing's draft lists).

A venue embeds a view-only design (``canva.com/design/<id>/<key>/view?embed``)
in an iframe. Canva serves non-browser clients an "Unsupported client" page,
so this parser — unlike the others — sends a browser User-Agent. The design
arrives as JSON inside the page (``window['bootstrap'] = JSON.parse('…')``);
its text boxes carry their position and font size.

Designs differ, so beers are found by layout: every "5.6% ABV | 21 IBU"
line anchors a card. Its name is the nearest box above it, in the same
column, set in larger type (Pike Place's smaller descriptions sit between
name and ABV; Ship Canal's styles sit right under the ABV line). A short
box in the card is the style; the card's other text is its description
(for matching). Text outside any card ("Ask your server about our fresh hop
beers!…") becomes an entry of its own, so a note that names fresh hops
still makes the list.

Config (``source_type: "canva"``)::

    "parser_config": {
      "design_url": "https://www.canva.com/design/<id>/<key>/view?embed"
    }

``design_url`` is fetched; the venue ``url`` (the page embedding the design,
for people) is used when it is absent.
"""

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import aiohttp

from ...models import Event
from ..base import BaseParser
from .listing_common import TapEntry, build_listings, fetch_listing_text, normalize_abv

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}

_BOOTSTRAP = re.compile(
    r"window\['bootstrap'\]\s*=\s*JSON\.parse\('((?:[^'\\]|\\.)*)'\)", re.S
)
_JS_ESCAPE = re.compile(r"\\(u[0-9a-fA-F]{4}|x[0-9a-fA-F]{2}|.)", re.S)
_SIMPLE_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f", "v": "\v"}


def _unescape_js(literal: str) -> str:
    def replace(match: "re.Match[str]") -> str:
        code = match.group(1)
        if code[0] in "ux" and len(code) > 1:
            return chr(int(code[1:], 16))
        return _SIMPLE_ESCAPES.get(code, code)

    return _JS_ESCAPE.sub(replace, literal)


def decode_design(page_html: str) -> Dict[str, Any]:
    """The design document from a Canva view page."""
    match = _BOOTSTRAP.search(page_html)
    if not match:
        raise ValueError("Canva page has no design data (blocked or not a design?)")
    try:
        bootstrap = json.loads(_unescape_js(match.group(1)))
    except json.JSONDecodeError as e:
        raise ValueError(f"Could not decode Canva design data: {e}") from e
    page = bootstrap.get("page") if isinstance(bootstrap, dict) else None
    if not isinstance(page, dict):
        raise ValueError("Canva design data has no page")
    return page


_ABV_LINE = re.compile(r"\bABV\b", re.I)
# Lines that are never a beer's style: serving sizes, prices, to-go notes.
_NOT_STYLE = re.compile(r"^\$|^\d+\s*oz\b|\bavailable\b|\bto-?go\b", re.I)
# How far (in design units) a name may sit above its ABV line, and a style
# below it.
_MAX_GAP = 160.0
_STYLE_GAP = 10.0
# A name is set noticeably larger than its ABV line.
_NAME_SCALE = 1.15
_MAX_STYLE_LENGTH = 40


@dataclass
class TextBox:
    text: str
    font: float
    top: float
    left: float
    width: float
    height: float

    @property
    def bottom(self) -> float:
        return self.top + self.height

    @property
    def right(self) -> float:
        return self.left + self.width


def _number(value: Any) -> float:
    return float(value) if isinstance(value, (int, float)) else 0.0


def _font(style: Dict[str, Any]) -> float:
    try:
        return float(str(style.get("G", "0")).rstrip("px"))
    except ValueError:
        return 0.0


def _boxes(node: Any, top: float, left: float, out: List[TextBox]) -> None:
    """Collect text boxes under *node*; groups ("H") offset their children."""
    if isinstance(node, dict):
        kind = node.get("A?")
        if kind == "K":
            try:
                content = node["a"]["C"]
                text = " ".join("".join(content["A"]).split())
                style = content["C"][0] if content.get("C") else {}
            except (KeyError, TypeError, IndexError):
                return
            text = text.strip("\u200b ‘")
            if text:
                out.append(
                    TextBox(
                        text,
                        _font(style),
                        top + _number(node.get("A")),
                        left + _number(node.get("B")),
                        _number(node.get("D")),
                        _number(node.get("C")),
                    )
                )
            return
        if kind == "H":
            for child in node.get("c") or []:
                _boxes(
                    child,
                    top + _number(node.get("A")),
                    left + _number(node.get("B")),
                    out,
                )
            return
        for value in node.values():
            _boxes(value, top, left, out)
    elif isinstance(node, list):
        for value in node:
            _boxes(value, top, left, out)


def design_pages(page: Dict[str, Any]) -> List[List[TextBox]]:
    """Text boxes of each page of the design (positions are per page)."""
    try:
        pages = page["C"]["D"]["A"]["A"]
    except (KeyError, TypeError):
        pages = None
    if not isinstance(pages, list):
        pages = [page]
    result = []
    for design_page in pages:
        out: List[TextBox] = []
        _boxes(design_page, 0.0, 0.0, out)
        result.append(out)
    return result


def _same_column(a: TextBox, b: TextBox) -> bool:
    overlap = min(a.right, b.right) - max(a.left, b.left)
    return overlap >= 0.3 * min(a.width, b.width)


def _name_for(abv: TextBox, boxes: List[TextBox], taken: set) -> Optional[TextBox]:
    """The nearest box above *abv* in its column set larger than it."""
    candidates = [
        b
        for b in boxes
        if id(b) not in taken
        and b is not abv
        and not _ABV_LINE.search(b.text)
        and not _NOT_STYLE.search(b.text)
        and b.font >= _NAME_SCALE * abv.font
        and b.top <= abv.top + 1
        and abv.top - b.bottom <= _MAX_GAP
        and _same_column(b, abv)
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda b: b.top)


def parse_design(page: Dict[str, Any]) -> List[TapEntry]:
    entries: List[TapEntry] = []
    for boxes in design_pages(page):
        abvs = sorted(
            (b for b in boxes if _ABV_LINE.search(b.text)),
            key=lambda b: (b.left, b.top),
        )
        names: Dict[int, TextBox] = {}
        taken: set = set()
        for abv in abvs:
            name = _name_for(abv, boxes, taken)
            if name is not None:
                names[id(abv)] = name
                taken.add(id(name))
        claimed = set(taken) | {id(a) for a in abvs}
        cards: List[Tuple[TextBox, TextBox, List[TextBox]]] = []
        for abv in abvs:
            name = names.get(id(abv))
            if name is None:
                continue
            # Between the name and the ABV line (a description), or right
            # under the ABV line (a style).
            members = [
                b
                for b in boxes
                if id(b) not in claimed
                and _same_column(b, abv)
                and (
                    name.top <= b.top <= abv.top
                    or abv.top < b.top <= abv.bottom + _STYLE_GAP
                )
            ]
            claimed.update(id(b) for b in members)
            cards.append((name, abv, members))
        for name, abv, members in cards:
            members.sort(key=lambda b: b.top)
            styles = [
                b
                for b in members
                if len(b.text) <= _MAX_STYLE_LENGTH and not _NOT_STYLE.search(b.text)
            ]
            style = styles[0].text if styles else None
            description = " ".join(b.text for b in members if b.text != style)
            entries.append(
                TapEntry(
                    name=name.text,
                    style=style,
                    abv=normalize_abv(abv.text),
                    description=description or None,
                )
            )
        # Notes between cards; build_listings keeps them only if they match.
        entries.extend(TapEntry(name=b.text) for b in boxes if id(b) not in claimed)
    return entries


class CanvaParser(BaseParser):
    PRODUCES_LISTINGS = True

    async def parse(self, session: aiohttp.ClientSession) -> List[Event]:
        config = self.venue.parser_config or {}
        url = config.get("design_url") or self.venue.url
        html = await fetch_listing_text(session, url, headers=BROWSER_HEADERS)
        entries = parse_design(decode_design(html))
        if not any(e.abv for e in entries):
            self.logger.warning(f"{self.venue.name}: no beers found in the design")
        return build_listings(self.venue, entries, "canva", self.logger)
