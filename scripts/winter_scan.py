"""Scan live tap lists for winter beers, ahead of the real winter category.

Registers a temporary ``winter`` listing category, in this process only, using
the first-guess patterns from WINTER-ALES-PLAN.md, scrapes each site, and
prints the entries that match. Nothing is written or deployed. Use it to tune
the patterns before step 1 of the plan; delete it once the category ships.

    uv run python scripts/winter_scan.py                    # all Freshies sites
    uv run python scripts/winter_scan.py seattle-freshies   # one site

Known false positives at the first run (2026-10-20): ``\\bsanta`` matches
"Russian River Santa Rosa", "Jolly Roger" matches a rum in a spirits menu, and
"wintery spices" in a description matches a hot spiced cider.
"""

import asyncio
import logging
import sys
from typing import List, Sequence, Tuple

from around_the_grounds.config.loader import load_site_config
from around_the_grounds.main import scrape_site
from around_the_grounds.models import Event
from around_the_grounds.utils import listing_matcher

DEFAULT_SITES = ["seattle-freshies", "portland-freshies", "yakima-freshies"]

AGED = r"(?:barrel|bourbon|whiske?y|rye|rum|brandy)[\s-]*(?:barrel[\s-]*)?aged"
SPICE = (
    r"(?:spiced|cinnamon|nutmeg|clove|ginger(?:bread)?|allspice"
    r"|mexican[\s-]*(?:hot[\s-]*)?chocolate|chai|peppermint)"
)

WINTER_INCLUDE = [
    r"\bwinter",
    r"christmas",
    r"\bxmas",
    r"holiday",
    r"\bno[eë]l\b",
    r"\byule",
    r"wassail",
    r"jubel",
    r"sleigh",
    r"\bsanta",
    r"snow[\s-]*cap",
    r"jolly[\s-]*roger",
    r"bifrost",
    r"abominable",
    r"\bwarmer\b",
    r"barley[\s-]*wine",
    r"wheat[\s-]*wine",
    rf"\b{AGED}\b.*\bstout\b",
    rf"\bstout\b.*\b{AGED}\b",
    r"\bBA\b.*\bstout\b",
    rf"\b{SPICE}\b.*\bstout\b",
    rf"\bstout\b.*\b{SPICE}\b",
]

# Narrower patterns for descriptions.
WINTER_CORE = [
    r"winter\s+(?:ale|warmer)",
    r"holiday\s+(?:ale|beer)",
    r"christmas\s+(?:ale|beer)",
    r"barley[\s-]*wine",
]


async def scan_site(site_key: str) -> Tuple[str, List[Event], List[object]]:
    """Scrape *site_key* and return its winter entries and venue errors."""
    site = load_site_config(site_key)
    events, errors = await scrape_site(site)
    hits = [e for e in events if e.category == "winter"]
    return site_key, hits, errors


async def scan(site_keys: Sequence[str]) -> None:
    results = await asyncio.gather(*(scan_site(k) for k in site_keys))
    for site_key, hits, errors in results:
        print(
            f"\n=== {site_key}: {len(hits)} winter hits, "
            f"{len(errors)} venue errors ==="
        )
        for e in sorted(hits, key=lambda e: (e.venue_name, e.title)):
            description = (e.description or "")[:160].replace("\n", " ")
            print(f"- {e.venue_name} | {e.title} | {description}")
        for error in errors:
            print(f"  ERROR {error}")


def main(argv: Sequence[str]) -> int:
    logging.basicConfig(level=logging.WARNING)
    listing_matcher.CATEGORIES["winter"] = (WINTER_INCLUDE, [], "winter", WINTER_CORE)
    asyncio.run(scan(list(argv) or DEFAULT_SITES))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
