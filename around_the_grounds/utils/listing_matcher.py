"""Decide which tap-list entries belong on a listing site, by category.

Parsers pass every text field they have for an entry (name, style,
description); the entry matches a category when any field hits one of its
include patterns and no field hits one of its exclude patterns.

Built-in categories:

- ``fresh-hop``: fresh/wet-hop beers. Venues extend it with
  ``listing_include`` / ``listing_exclude`` for beers whose names never say
  "fresh hop".
- ``festbier``: Oktoberfest-season beers (Festbier, Oktoberfest, Märzen,
  plus harvest lagers, Dunkels, and Weizenbocks). Venues extend it with
  ``festbier_include`` / ``festbier_exclude``.

A beer's description (``matches_description``) is checked against a
narrower list per category: brewers write "FRESH HOP collab…" or "our
yearly Festbier" there, but also mention Dunkel malt or a harvest.
"""

import re
from typing import Any, Dict, List, Optional, Pattern, Sequence, Tuple

FRESH_HOP = "fresh-hop"
FESTBIER = "festbier"

# "fresh hop", "wet-hop", "Freshhop", "Fresh Hops", "wet-hopped". Requiring
# "hop" right after "fresh"/"wet" keeps out "Fresh Squeezed IPA" and
# "brewed with fresh Simcoe hops".
DEFAULT_INCLUDE = [r"\b(?:fresh|wet)[\s-]*hop(?:s|ped)?\b"]

# Fresh-hop festivals show up in tap-list pages alongside the beers. ("\bfest\b"
# does not match "Festbier".)
DEFAULT_EXCLUDE = [r"\bfest(?:ival)?\b"]

# Also the patterns checked in descriptions ("our yearly golden Festbier").
FESTBIER_CORE = [
    r"\bfest[\s-]*b(?:ie|ee)r\b",  # Festbier, Fest Bier, Fest Beer
    r"tober[\s-]*fest",  # Oktoberfest, Octoberfest, Bobtoberfest
    r"\bm(?:ä|ae|a)rzen\b",  # Märzen, Maerzen, Marzen
    r"\bwiesn\b",
]

# Season beers counted by name or style only.
FESTBIER_INCLUDE = FESTBIER_CORE + [
    r"\bharvest[\s-]*lager\b",
    r"\bdunkel\b",  # Dunkel Lager, Munich Dunkel; not Dunkelweizen
    r"\bweizen[\s-]*bock\b",
]

# category -> (include patterns, exclude patterns, config key prefix,
#              include patterns for descriptions)
CATEGORIES: Dict[str, Tuple[List[str], List[str], str, List[str]]] = {
    FRESH_HOP: (DEFAULT_INCLUDE, DEFAULT_EXCLUDE, "listing", DEFAULT_INCLUDE),
    FESTBIER: (FESTBIER_INCLUDE, [], "festbier", FESTBIER_CORE),
}


class ListingMatcher:
    """Case-insensitive include/exclude matcher over an entry's text fields."""

    def __init__(
        self,
        include: Optional[Sequence[str]] = None,
        exclude: Optional[Sequence[str]] = None,
        default_exclude: bool = True,
        category: str = FRESH_HOP,
    ) -> None:
        """``default_exclude=False`` keeps festivals, for matching events."""
        if category not in CATEGORIES:
            raise ValueError(f"Unknown listing category {category!r}")
        base_include, base_exclude, prefix, description_include = CATEGORIES[category]
        self.category = category
        self._include = self._compile(
            base_include + list(include or []), f"{prefix}_include"
        )
        self._description_include = self._compile(
            description_include, f"{prefix}_include"
        )
        defaults = base_exclude if default_exclude else []
        self._exclude = self._compile(
            defaults + list(exclude or []), f"{prefix}_exclude"
        )

    @classmethod
    def from_config(
        cls,
        parser_config: Optional[Dict[str, Any]],
        default_exclude: bool = True,
        category: str = FRESH_HOP,
    ) -> "ListingMatcher":
        """Build a matcher for *category* from a venue's ``parser_config``.

        ``<prefix>_include`` / ``<prefix>_exclude`` (``listing_*`` for fresh
        hop, ``festbier_*`` for festbier) may each be a pattern or a list of
        patterns; they extend the defaults rather than replace them.
        """
        if category not in CATEGORIES:
            raise ValueError(f"Unknown listing category {category!r}")
        prefix = CATEGORIES[category][2]
        config = parser_config or {}
        return cls(
            include=cls._as_list(config.get(f"{prefix}_include")),
            exclude=cls._as_list(config.get(f"{prefix}_exclude")),
            default_exclude=default_exclude,
            category=category,
        )

    @classmethod
    def for_venue(
        cls, parser_config: Optional[Dict[str, Any]]
    ) -> List["ListingMatcher"]:
        """One matcher per category the venue lists (``listing_categories``,
        default: every built-in category)."""
        config = parser_config or {}
        categories = cls._as_list(config.get("listing_categories")) or list(CATEGORIES)
        return [cls.from_config(config, category=c) for c in categories]

    def matches(self, *texts: Optional[str]) -> bool:
        fields = [t for t in texts if t]
        if not any(p.search(t) for p in self._include for t in fields):
            return False
        return not any(p.search(t) for p in self._exclude for t in fields)

    def matches_description(
        self, description: Optional[str], *texts: Optional[str]
    ) -> bool:
        """Match on a beer's *description* (with the narrower description
        patterns) when its other *texts* don't; excludes cover all of them."""
        if not description:
            return False
        if not any(p.search(description) for p in self._description_include):
            return False
        fields = [t for t in texts if t] + [description]
        return not any(p.search(t) for p in self._exclude for t in fields)

    @staticmethod
    def _as_list(value: Any) -> List[Any]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value]
        return list(value)

    @staticmethod
    def _compile(patterns: Sequence[Any], key: str) -> List[Pattern[str]]:
        compiled = []
        for pattern in patterns:
            if not isinstance(pattern, str):
                raise ValueError(f"{key} patterns must be strings, got {pattern!r}")
            try:
                compiled.append(re.compile(pattern, re.IGNORECASE))
            except re.error as e:
                raise ValueError(f"Invalid {key} pattern {pattern!r}: {e}") from e
        return compiled
