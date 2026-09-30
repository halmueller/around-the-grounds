"""Decide which tap-list entries belong on a listing site (fresh-hop beers).

Parsers pass every text field they have for an entry (name, style,
description); the entry matches when any field hits an include pattern and
no field hits an exclude pattern. Venues can extend both lists through
``parser_config`` for beers whose names never say "fresh hop".
"""

import re
from typing import Any, Dict, List, Optional, Pattern, Sequence

# "fresh hop", "wet-hop", "Freshhop", "Fresh Hops", "wet-hopped". Requiring
# "hop" right after "fresh"/"wet" keeps out "Fresh Squeezed IPA" and
# "brewed with fresh Simcoe hops".
DEFAULT_INCLUDE = [r"\b(?:fresh|wet)[\s-]*hop(?:s|ped)?\b"]

# Fresh-hop festivals show up in tap-list pages alongside the beers.
DEFAULT_EXCLUDE = [r"\bfest(?:ival)?\b"]


class ListingMatcher:
    """Case-insensitive include/exclude matcher over an entry's text fields."""

    def __init__(
        self,
        include: Optional[Sequence[str]] = None,
        exclude: Optional[Sequence[str]] = None,
        default_exclude: bool = True,
    ) -> None:
        """``default_exclude=False`` keeps festivals, for matching events."""
        self._include = self._compile(
            DEFAULT_INCLUDE + list(include or []), "listing_include"
        )
        defaults = DEFAULT_EXCLUDE if default_exclude else []
        self._exclude = self._compile(defaults + list(exclude or []), "listing_exclude")

    @classmethod
    def from_config(
        cls, parser_config: Optional[Dict[str, Any]], default_exclude: bool = True
    ) -> "ListingMatcher":
        """Build a matcher from a venue's ``parser_config``.

        ``listing_include`` and ``listing_exclude`` may each be a pattern or a
        list of patterns; they extend the defaults rather than replace them.
        """
        config = parser_config or {}
        return cls(
            include=cls._as_list(config.get("listing_include")),
            exclude=cls._as_list(config.get("listing_exclude")),
            default_exclude=default_exclude,
        )

    def matches(self, *texts: Optional[str]) -> bool:
        fields = [t for t in texts if t]
        if not any(p.search(t) for p in self._include for t in fields):
            return False
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
