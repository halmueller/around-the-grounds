"""Decide which tap-list entries belong on a listing site, by category.

Parsers pass every text field they have for an entry (name, style,
description), name first; the entry matches a category when any field hits
one of its include patterns and no field hits one of the venue's exclude
patterns. The name and style are also tried joined (``"name | style"``), so
a two-part pattern such as "barrel-aged … stout" matches when the two words
are split between them. The built-in excludes look at the name only.

Built-in categories:

- ``fresh-hop``: fresh/wet-hop beers, including the abbreviation "FH" in a
  name or style. Venues extend it with
  ``listing_include`` / ``listing_exclude`` for beers whose names never say
  "fresh hop".
- ``festbier``: Oktoberfest-season beers (Festbier, Oktoberfest, Märzen,
  plus harvest lagers, Dunkels, and Weizenbocks). Venues extend it with
  ``festbier_include`` / ``festbier_exclude``.
- ``pumpkin``: pumpkin beers (pumpkin, gourd, jack-o'-lantern, calabaza).
  Venues extend it with ``pumpkin_include`` / ``pumpkin_exclude``.
- ``winter``: winter seasonals (winter ales, warmers, IPAs, and lagers;
  Christmas and holiday beers; named seasonals such as Jubelale, Jolly
  Roger, and High Camp), holiday-focused ciders (wassail, mulled, hot
  spiced), barleywines and wheatwines, and barrel-aged or spiced stouts.
  Venues extend it with ``winter_include`` / ``winter_exclude``.

A beer's description (``matches_description``) is checked against a
narrower list per category: brewers write "FRESH HOP collab…" or "our
yearly Festbier" there, but also mention Dunkel malt or a harvest.
"""

import re
from typing import Any, Dict, List, Optional, Pattern, Sequence, Tuple

FRESH_HOP = "fresh-hop"
FESTBIER = "festbier"
PUMPKIN = "pumpkin"
WINTER = "winter"

# "fresh hop", "wet-hop", "Freshhop", "Fresh Hops", "wet-hopped". Requiring
# "hop" right after "fresh"/"wet" keeps out "Fresh Squeezed IPA" and
# "brewed with fresh Simcoe hops".
DEFAULT_INCLUDE = [r"\b(?:fresh|wet)[\s-]*hop(?:s|ped)?\b"]

# Counted by name or style only: tap lists abbreviate fresh hop as "FH"
# ("Bug Hazy FH IPA", style "FH Italian Pilsner").
FRESH_HOP_INCLUDE = DEFAULT_INCLUDE + [r"\bFH\b"]

# Fresh-hop festivals show up in tap-list pages alongside the beers. Checked
# against the name only: a beer "brewed for Fresh Hop Ale Festival" stays.
# ("\bfest\b" does not match "Festbier", and "Fest Bier" is let through.)
DEFAULT_EXCLUDE = [r"\bfest(?:ival)?\b(?![\s-]*b(?:ie|ee)r\b)"]

# Also the patterns checked in descriptions ("our yearly golden Festbier").
FESTBIER_CORE = [
    r"\bfest[\s-]*b(?:ie|ee)r\b",  # Festbier, Fest Bier, Fest Beer
    # Oktoberfest, Octoberfest, Bobtoberfest; not Artoberfest, an art fair
    # named in Santiam's beer awards
    r"(?<!\bar)tober[\s-]*fest",
    r"\bm(?:ä|ae|a)rzen\b",  # Märzen, Maerzen, Marzen
    r"\bwies[’'`]?n\b",  # Wiesn, Wies'n
]

# Season beers counted by name or style only.
FESTBIER_INCLUDE = FESTBIER_CORE + [
    r"\bharvest[\s-]*lager\b",
    r"\bdunkel\b",  # Dunkel Lager, Munich Dunkel; not Dunkelweizen
    r"\bm(?:ü|ue|u)nich[\s-]+dark\b",  # Hacker-Pschorr Münich Dark
    r"\bweizen[\s-]*bock\b",
]

# Also the patterns checked in descriptions ("brewed with roasted pumpkin").
PUMPKIN_INCLUDE = [
    r"pumpkin",  # Pumpkin Ale, Kilty MacPumpkin, Punkuccino's "Coffee Pumpkin Ale"
    r"\bgourd",  # Ravenna's "Hello, Gourdgeous"
    r"\bjack[\s-]*o[\s'’-]*lantern",
    r"\bcalabaza\b",
]

# Barrel-aged and spiced stouts. A plain, imperial, coffee, or pastry stout
# does not count on its own.
_AGED = (
    r"(?:barrel|bourbon|whiske?y|rye|rum|brandy|port|peat)"
    r"[\s-]*(?:barrel[\s-]*)?aged"
)
_SPICE = (
    r"(?:spiced|cinnamon|nutmeg|clove|ginger(?:bread)?|allspice"
    r"|mexican[\s-]*(?:hot[\s-]*)?chocolate|chai|peppermint)"
)

# Also the patterns checked in descriptions: seasonal phrases and winter style
# names, which a brewer would not use for some other beer ("perfect for
# winter nights" stays out; "a malt-forward wee heavy" or "Barrel-aged
# Belgian Quadrupel" counts).
WINTER_CORE = [
    r"\bwinter[\s-]+(?:ale|warmer|ipa|lager|seasonal|beer)\b",
    r"\bholiday[\s-]+(?:ale|beer|seasonal)\b",
    r"\bchristmas[\s-]+(?:ale|beer)\b",
    r"\bbarley[\s-]*wine",
    r"\bwheat[\s-]*wine",
    r"\bwassail",
    r"\bmulled\b",
    # Scotch ales and wee heavies (Hal, 2026-11-06). Not light "Scottish"
    # ales such as Shepherd's Crook (4.6%) or a Scottish oatmeal porter.
    r"\bscotch[\s-]+ale\b",  # "Scotch Ale", "Strong Scotch Ale"
    r"\bwee[\s-]*heavy\b",
    r"\bdoppel[\s-]*bock",  # Doppelbock, Doppel Bock (Hal, 2026-11-06)
    # Classic doppelbocks often listed by name alone (Ayinger Celebrator at
    # the Prost! bars)
    r"\b(?:celebrator|salvator|optimator)\b",
    # Fir-tip porters (Ferment's Woodsman, "Porter w/ Doug Fir Tips"), name
    # and style joined (Hal, 2026-11-06)
    r"\bfir[\s-]*tips?\b.*\bporter\b",
    r"\bporter\b.*\bfir[\s-]*tips?\b",
    # Belgian quads and strong ales, dark or golden (Hal, 2026-11-06): style
    # "Belgian Quadrupel", "Belgian Strong Dark Ale", "Belgian Strong Golden
    # Ale"; Obec's "B.A. Belgian Quad". Not a quadruple IPA ("Quad IPA").
    r"\bquad(?:rupel|ruple)?\b(?![\s-]*(?:ipa|ddh|dry[\s-]*hop|hop))",
    # "Belgian Strong", "Belgian Strong Dark Ale", "Belgian-Style Golden
    # Strong" (Flying Lion's Velvet Uppercut)
    r"\bbelgian(?:[\s-]+style)?[\s-]+(?:(?:dark|golden|blonde?|pale)[\s-]+)?strong\b",
    # Solstice beers, except summer ones (Anderson Valley's Summer Solstice)
    r"(?<!summer\s)(?<!summer-)\bsolstice\b",
    # Winter-warmer recipes: "SPICED AMBER ALE WITH ORANGE PEEL, CINNAMON…"
    # (Strange Weather). Not spiced brown ale: Beer of the Dead is a Day of
    # the Dead beer.
    r"\bspiced[\s-]+(?:amber|red|dark|strong|winter|holiday)\b",
]

# Counted by name or style (alone or joined).
WINTER_INCLUDE = WINTER_CORE + [
    r"\bwinter",  # Winter Ale, Winter IPA, "The Wintering", "wintery spices"
    r"christmas",
    r"\bxmas",
    r"holiday",  # Holiday Haze, Festivus Holiday Ale
    r"\bno[eë]l\b",  # Delirium Noël
    r"\byule",
    r"\bjul(?:e|ø)",  # Julebokk, Juleøl, Julebryg
    r"jubel",  # Jubelale
    r"sleigh",  # Sleigh'r, Sleighjacker
    # Saint Nick and Santa; not "Russian River Santa Rosa, CA"
    r"\bsanta\b(?![\s-]*(?:rosa|cruz|barbara|fe|clara|monica|ana)\b)",
    r"\b(?:saint|st\.?)[\s-]*nick\b",  # Ol' Saint Nick
    r"\bscrooge",  # Scrooge McBluffs
    r"\bkrampus",
    r"gingerbread",
    r"\bfa[\s-]*la\b",  # Fa La La
    r"\bfestive\b",  # Reuben's Festive Ale
    r"\bfestivus\b",
    r"\bsnow",  # Snowmotion, Snow Day, Snow Cap
    r"jolly[\s-]*roger",
    r"bifrost",
    r"abominable",
    r"\bhigh[\s-]*camp\b",  # Bale Breaker
    r"\bwarmer\b",
    r"\bhot[\s-]*spiced\b",  # Old Stove Hot Spiced Cider
    # Spiced ciders ("Spiced Pear", style "Cider - Herbed"; Lost Lake Cider,
    # style "Imperial Spiced"), and cranberry with spice. "Pumpkin Spice"
    # says "spice", not "spiced", so pumpkin ciders stay on the pumpkin list.
    r"\bspiced\b.*\bcider\b",
    r"\bcider\b.*\bspiced\b",
    r"\bspiced[\s-]+cranberr",  # Offset Spiced Cranberry
    r"\bcranberr\w*\s*(?:\+|&|and)?\s*spice",  # "CRANBERRY + SPICE"
    r"\bsugar[\s-]*plum",  # Reuben's Fresh! Sugar Plum
    r"\bnew[\s-]*year",  # Seapine "New Year, Old Habits" strong ale
    # Sierra Nevada's winter IPA, listed as "Celebration (2026)". Only at the
    # start of the name: Dirty Couch's "Premature Celebration" is a festbier.
    r"^\s*(?:sierra[\s-]+nevada[\s-]+)?celebration\b",
    rf"\b{_AGED}\b.*\bstout\b",
    rf"\bstout\b.*\b{_AGED}\b",
    r"\bBA\b.*\bstout\b",  # "BA Imperial Stout", "Mayan Chocolate BA Stout"
    rf"\b{_SPICE}\b.*\bstout\b",
    rf"\bstout\b.*\b{_SPICE}\b",
]

# category -> (include patterns, exclude patterns, config key prefix,
#              include patterns for descriptions)
CATEGORIES: Dict[str, Tuple[List[str], List[str], str, List[str]]] = {
    FRESH_HOP: (FRESH_HOP_INCLUDE, DEFAULT_EXCLUDE, "listing", DEFAULT_INCLUDE),
    FESTBIER: (FESTBIER_INCLUDE, [], "festbier", FESTBIER_CORE),
    PUMPKIN: (PUMPKIN_INCLUDE, [], "pumpkin", PUMPKIN_INCLUDE),
    WINTER: (WINTER_INCLUDE, [], "winter", WINTER_CORE),
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
        self._name_exclude = self._compile(
            base_exclude if default_exclude else [], f"{prefix}_exclude"
        )
        self._exclude = self._compile(list(exclude or []), f"{prefix}_exclude")

    @classmethod
    def from_config(
        cls,
        parser_config: Optional[Dict[str, Any]],
        default_exclude: bool = True,
        category: str = FRESH_HOP,
    ) -> "ListingMatcher":
        """Build a matcher for *category* from a venue's ``parser_config``.

        ``<prefix>_include`` / ``<prefix>_exclude`` (``listing_*`` for fresh
        hop, ``festbier_*`` for festbier, ``pumpkin_*`` for pumpkin,
        ``winter_*`` for winter) may each be a pattern or a list of
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
        cls, parser_config: Optional[Dict[str, Any]], default_exclude: bool = True
    ) -> List["ListingMatcher"]:
        """One matcher per category the venue lists (``listing_categories``,
        default: every built-in category)."""
        config = parser_config or {}
        categories = cls._as_list(config.get("listing_categories")) or list(CATEGORIES)
        return [
            cls.from_config(config, default_exclude=default_exclude, category=c)
            for c in categories
        ]

    def matches(self, *texts: Optional[str]) -> bool:
        """*texts* are an entry's fields, name first, then style.

        The name and style are also tried joined by " | ", so a pattern
        with ``.*`` can span them ("Bourbon Barrel Aged Dark Star" with
        style "Imperial Oatmeal Stout"); ``[\\s-]*`` cannot cross the bar.
        """
        fields = [t for t in texts if t]
        if len(texts) >= 2 and texts[0] and texts[1]:
            fields.append(f"{texts[0]} | {texts[1]}")
        if not any(p.search(t) for p in self._include for t in fields):
            return False
        return not self._excluded(texts)

    def _excluded(self, texts: Sequence[Optional[str]]) -> bool:
        name = texts[0] if texts else None
        if name and any(p.search(name) for p in self._name_exclude):
            return True
        return any(p.search(t) for p in self._exclude for t in texts if t)

    def matches_description(
        self, description: Optional[str], *texts: Optional[str]
    ) -> bool:
        """Match on a beer's *description* (with the narrower description
        patterns) when its other *texts* (name first) don't; the venue's
        excludes cover all of them."""
        if not description:
            return False
        if not any(p.search(description) for p in self._description_include):
            return False
        return not self._excluded(list(texts) + [description])

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
