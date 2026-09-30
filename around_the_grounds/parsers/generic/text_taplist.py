"""Tap lists written as free text, one beer per line.

The page is split into lines (block elements and ``<br>`` breaks), and each
line is matched against ``line_pattern``; its named groups become the entry.
Lines that don't match are ignored. ``section_tag`` headings divide the page
(e.g. one per bar), and ``include_sections`` / ``exclude_sections`` choose
which parts to read.

Config (``source_type: "text-taplist"``; the venue ``url`` is fetched)::

    "parser_config": {
      "line_pattern": "^(?P<name>[^:]+):\\\\s*(?P<style>.+)$",  # needs name
      "section_tag": "h2",                  # optional
      "include_sections": ["^MAIN BAR$"],    # optional, regexes
      "exclude_sections": ["closed"],        # optional, regexes
      "line_tags": ["h2"]                    # optional; default ["p", "li"]
    }

Optional named groups: ``style``, ``abv``, ``brewery``. ``line_tags`` names
the elements whose lines can be entries; by default headings only divide the
page, but some sites (Bizarre) put each beer in a heading.
"""

import re
from typing import Any, Dict, Iterator, List, Optional, Pattern, Tuple

import aiohttp
from bs4 import BeautifulSoup, NavigableString, Tag

from ...models import Event
from ..base import BaseParser
from .listing_common import (
    TapEntry,
    build_listings,
    fetch_listing_text,
    normalize_abv,
)

_BLOCKS = ["h1", "h2", "h3", "h4", "h5", "h6", "p", "li"]
_DEFAULT_LINE_TAGS = ["p", "li"]


def _compile(patterns: Any, key: str) -> List[Pattern[str]]:
    try:
        return [re.compile(p, re.IGNORECASE) for p in patterns or []]
    except re.error as e:
        raise ValueError(f"Invalid {key} pattern: {e}") from e


def iter_lines(html: str) -> Iterator[Tuple[str, str]]:
    """Yield (tag name, line) for each text line in document order."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    for br in soup.find_all("br"):
        br.replace_with(NavigableString("\n"))
    for block in soup.find_all(_BLOCKS):
        if not isinstance(block, Tag) or block.find(_BLOCKS):
            continue  # its inner blocks are visited on their own
        for line in block.get_text("").split("\n"):
            line = " ".join(line.split())
            if line:
                yield block.name, line


def _group(match: "re.Match[str]", name: str) -> Optional[str]:
    if name not in match.re.groupindex:
        return None
    value = match.group(name)
    return value.strip() if value and value.strip() else None


def parse_text_taplist(html: str, config: Dict[str, Any]) -> List[TapEntry]:
    pattern_text = config.get("line_pattern")
    if not pattern_text:
        raise ValueError("text-taplist needs line_pattern")
    try:
        pattern = re.compile(pattern_text)
    except re.error as e:
        raise ValueError(f"Invalid line_pattern: {e}") from e
    if "name" not in pattern.groupindex:
        raise ValueError("text-taplist line_pattern needs a (?P<name>...) group")
    section_tag = config.get("section_tag")
    includes = _compile(config.get("include_sections"), "include_sections")
    excludes = _compile(config.get("exclude_sections"), "exclude_sections")
    line_tags = set(config.get("line_tags") or _DEFAULT_LINE_TAGS)

    section = ""
    entries = []
    for tag, line in iter_lines(html):
        if tag == section_tag:
            section = line
            continue
        if tag not in line_tags:
            continue
        if includes and not any(p.search(section) for p in includes):
            continue
        if any(p.search(section) for p in excludes):
            continue
        match = pattern.search(line)
        if not match:
            continue
        # Footnote markers ("*Fresh Hop Lager") are not part of the name.
        name = (_group(match, "name") or "").strip("* ")
        if not name:
            continue
        entries.append(
            TapEntry(
                name=name,
                brewery=_group(match, "brewery"),
                style=_group(match, "style"),
                abv=normalize_abv(_group(match, "abv")),
            )
        )
    return entries


class TextTaplistParser(BaseParser):
    PRODUCES_LISTINGS = True

    async def parse(self, session: aiohttp.ClientSession) -> List[Event]:
        config = self.venue.parser_config or {}
        html = await fetch_listing_text(session, self.venue.url)
        entries = parse_text_taplist(html, config)
        if not entries:
            self.logger.warning(f"{self.venue.name}: no tap-list lines matched")
        return build_listings(self.venue, entries, "html", self.logger)
