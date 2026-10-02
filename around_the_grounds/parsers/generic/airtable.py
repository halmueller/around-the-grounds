"""Tap lists published as a shared Airtable interface page (Rooftop Brewing).

A venue embeds ``airtable.com/embed/<app id>/<share id>``. That page carries
a signed, short-lived ``accessPolicy`` for the share; with it the page's own
script asks ``readForSharedPages`` for the page's data, which comes back with
the rows its list shows (already filtered to what is on tap). This parser
makes the same two requests.

Rows are keyed by column id, so fields are found by column name: the table's
primary column is the beer's name, and ``Style``, ``ABV`` and ``Description``
are read when present (override the names with ``columns``). Single-select
cells hold a choice id, resolved to its label; an ABV stored as a fraction
(0.066) is shown as a percentage.

Config (``source_type: "airtable"``)::

    "parser_config": {
      "share_url": "https://airtable.com/embed/appXXXX/shrXXXX",
      "columns": {"style": "Style", "abv": "ABV", "description": "Description"}
    }

``share_url`` is fetched; the venue ``url`` is the page embedding it, for
people. This is not Airtable's documented API, so expect it to need care
when Airtable changes its pages.
"""

import json
import re
import secrets
import string
from typing import Any, Dict, List, Optional

import aiohttp

from ...models import Event
from ..base import BaseParser
from .listing_common import TapEntry, build_listings, fetch_listing_text

API_URL = "https://airtable.com/v0.3/application/{app_id}/readForSharedPages"
# The page-layout version the request says it understands; Airtable answers
# with the page's published layout, whose rows are all this parser reads.
PAGE_LAYOUT_SCHEMA_VERSION = 26
DEFAULT_COLUMNS = {"style": "Style", "abv": "ABV", "description": "Description"}

_SHARE_URL = re.compile(r"airtable\.com/(?:embed/)?(app\w+)/(shr\w+)")
_ACCESS_POLICY = re.compile(r'"accessPolicy":"((?:[^"\\]|\\.)*)"')
_PAGE_ID = re.compile(r'"sharedPageId":"(pag\w+)"')
_REQUEST_ID_ALPHABET = string.ascii_letters + string.digits


def read_share_page(html: str) -> Dict[str, str]:
    """The signed access policy and page id from the embed page's HTML."""
    policy = _ACCESS_POLICY.search(html)
    page = _PAGE_ID.search(html)
    if not policy or not page:
        raise ValueError("Airtable share page has no access policy or page id")
    try:
        access_policy: str = json.loads(f'"{policy.group(1)}"')
    except json.JSONDecodeError as e:
        raise ValueError(f"Could not decode Airtable access policy: {e}") from e
    return {"access_policy": access_policy, "page_id": page.group(1)}


def _clean(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())
    return text or None


def _abv(value: Any) -> Optional[str]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return _clean(value)
    percent = value * 100 if value < 1 else value
    return f"{round(percent, 2):g}%"


def parse_shared_page(
    payload: Dict[str, Any], columns: Optional[Dict[str, str]] = None
) -> List[TapEntry]:
    """Entries from a ``readForSharedPages`` response, in the page's order."""
    names = {**DEFAULT_COLUMNS, **(columns or {})}
    data = payload.get("data") or {}
    results = data.get("preloadPageQueryResults") or {}
    schemas = {t.get("id"): t for t in data.get("tableSchemas") or []}
    entries: List[TapEntry] = []
    for query_slice in results.get("querySlices") or []:
        table_id = query_slice.get("tableId")
        schema = schemas.get(table_id) or {}
        by_name = {c.get("name"): c for c in schema.get("columns") or []}
        rows = ((results.get("tableDataById") or {}).get(table_id) or {}).get(
            "partialRowById"
        ) or {}

        def cell(row: Dict[str, Any], field: str) -> Any:
            column = by_name.get(names[field]) or {}
            value = (row.get("cellValuesByColumnId") or {}).get(column.get("id"))
            choices = (column.get("typeOptions") or {}).get("choices") or {}
            if isinstance(value, str) and value in choices:
                return choices[value].get("name")
            return value

        for row_id in query_slice.get("rowIds") or []:
            row = rows.get(row_id) or {}
            cells = row.get("cellValuesByColumnId") or {}
            name = _clean(cells.get(schema.get("primaryColumnId")))
            if not name:
                continue
            entries.append(
                TapEntry(
                    name=name,
                    style=_clean(cell(row, "style")),
                    abv=_abv(cell(row, "abv")),
                    description=_clean(cell(row, "description")),
                )
            )
    return entries


class AirtableParser(BaseParser):
    PRODUCES_LISTINGS = True

    async def parse(self, session: aiohttp.ClientSession) -> List[Event]:
        config = self.venue.parser_config or {}
        share_url = config.get("share_url") or ""
        match = _SHARE_URL.search(share_url)
        if not match:
            raise ValueError(
                f"{self.venue.key}: airtable needs a share_url like "
                "https://airtable.com/embed/app…/shr…"
            )
        app_id = match.group(1)
        share = read_share_page(await fetch_listing_text(session, share_url))
        request_id = "req" + "".join(
            secrets.choice(_REQUEST_ID_ALPHABET) for _ in range(14)
        )
        params = {
            "stringifiedObjectParams": json.dumps(
                {
                    "includeDataForPageId": share["page_id"],
                    "shouldIncludeSchemaChecksum": True,
                    "expectedPageLayoutSchemaVersion": PAGE_LAYOUT_SCHEMA_VERSION,
                    "shouldPreloadQueries": True,
                    "shouldPreloadAllPossibleContainerElementQueries": True,
                    "urlSearch": "",
                    "navigationMode": "view",
                }
            ),
            "requestId": request_id,
            "accessPolicy": share["access_policy"],
        }
        headers = {
            "x-airtable-application-id": app_id,
            "x-airtable-inter-service-client": "webClient",
            "x-requested-with": "XMLHttpRequest",
            "x-time-zone": "America/Los_Angeles",
            "x-user-locale": "en",
        }
        text = await fetch_listing_text(
            session, API_URL.format(app_id=app_id), params=params, headers=headers
        )
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON from Airtable: {e}") from e
        entries = parse_shared_page(payload, config.get("columns"))
        if not entries:
            self.logger.warning(f"{self.venue.name}: no rows on the Airtable page")
        return build_listings(self.venue, entries, "airtable", self.logger)
