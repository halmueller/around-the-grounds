"""Tap lists kept in a public Cloud Firestore collection (Project 9 Brewing).

Some breweries run their own web app, which reads its beer list from
Firestore in the browser. This parser asks the Firestore REST API for the
same documents: the ones not archived, on a tap, and not sold out.

Config (``source_type: "firestore-taplist"``)::

    "parser_config": {"project": "project9brewing"}

Optional: ``collection`` (default ``"beers"``) and ``fields``, a map from
``name`` / ``style`` / ``abv`` / ``description`` / ``notes`` / ``brewery`` /
``tap`` / ``archived`` / ``sold_out`` to the document's field names, for apps
that name them differently. An empty ``tap`` or ``sold_out`` name turns that
check off.

The venue ``url`` is the venue's own beer page, for people; it is not
fetched.
"""

import json
from typing import Any, Dict, List, Optional

import aiohttp

from ...models import Event
from ..base import BaseParser
from .listing_common import TapEntry, build_listings, fetch_listing_text

API_URL = (
    "https://firestore.googleapis.com/v1/projects/{project}"
    "/databases/(default)/documents:runQuery"
)

DEFAULT_FIELDS = {
    "name": "name",
    "style": "beerStyle",
    "abv": "abv",
    "description": "description",
    "notes": "menuNotes",
    "brewery": "",
    "tap": "tapNumber",
    "archived": "isArchived",
    "sold_out": "soldOutTime",
}


def _value(fields: Dict[str, Any], name: str) -> Any:
    """The plain value of a Firestore typed field, or None."""
    typed = fields.get(name) if name else None
    if not isinstance(typed, dict):
        return None
    for kind, value in typed.items():
        if kind == "nullValue":
            return None
        if kind == "integerValue":
            try:
                return int(value)
            except (TypeError, ValueError):
                return None
        if kind in ("stringValue", "doubleValue", "booleanValue", "timestampValue"):
            return value
    return None


def _clean(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())
    return text or None


def _abv(value: Any) -> Optional[str]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return f"{value:g}%"


def build_query(collection: str, names: Dict[str, str]) -> Dict[str, Any]:
    query: Dict[str, Any] = {"from": [{"collectionId": collection}]}
    if names["archived"]:
        query["where"] = {
            "fieldFilter": {
                "field": {"fieldPath": names["archived"]},
                "op": "EQUAL",
                "value": {"booleanValue": False},
            }
        }
    paths = sorted({name for name in names.values() if name})
    query["select"] = {"fields": [{"fieldPath": path} for path in paths]}
    return {"structuredQuery": query}


def parse_firestore_taplist(rows: List[Any], names: Dict[str, str]) -> List[TapEntry]:
    found = []
    for row in rows:
        document = row.get("document") if isinstance(row, dict) else None
        fields = document.get("fields") if isinstance(document, dict) else None
        if not isinstance(fields, dict):
            continue
        name = _clean(_value(fields, names["name"]))
        if not name or _value(fields, names["archived"]) is True:
            continue
        tap = _value(fields, names["tap"])
        if names["tap"] and not (isinstance(tap, int) and tap > 0):
            continue
        if _value(fields, names["sold_out"]) is not None:
            continue
        texts = [_clean(_value(fields, names[key])) for key in ("description", "notes")]
        entry = TapEntry(
            name=name,
            brewery=_clean(_value(fields, names["brewery"])),
            style=_clean(_value(fields, names["style"])),
            abv=_abv(_value(fields, names["abv"])),
            description=" ".join(t for t in texts if t) or None,
        )
        found.append((tap if isinstance(tap, int) else 0, entry))
    found.sort(key=lambda pair: pair[0])
    return [entry for _, entry in found]


class FirestoreTaplistParser(BaseParser):
    PRODUCES_LISTINGS = True

    async def parse(self, session: aiohttp.ClientSession) -> List[Event]:
        config = self.venue.parser_config or {}
        project = str(config.get("project") or "").strip()
        if not project:
            raise ValueError(f"{self.venue.key}: firestore-taplist needs project")
        names = dict(DEFAULT_FIELDS)
        names.update(config.get("fields") or {})
        url = API_URL.format(project=project)
        body = build_query(str(config.get("collection") or "beers"), names)
        text = await fetch_listing_text(session, url, json_body=body)
        try:
            rows = json.loads(text)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON from Firestore: {e}") from e
        if not isinstance(rows, list) or any(
            isinstance(row, dict) and "error" in row for row in rows
        ):
            raise ValueError(f"Unexpected Firestore response from {url}")
        entries = parse_firestore_taplist(rows, names)
        if not entries:
            self.logger.warning(f"{self.venue.name}: no beers on tap in Firestore")
        return build_listings(self.venue, entries, "firestore-taplist", self.logger)
