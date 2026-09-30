"""Tests for the fresh-hop listing matcher. Cases are real tap-list text
collected from Seattle breweries and bars in September 2026."""

import pytest

from around_the_grounds.utils.listing_matcher import ListingMatcher


@pytest.fixture
def matcher() -> ListingMatcher:
    return ListingMatcher()


@pytest.mark.parametrize(
    "text",
    [
        "Fresh Hop Crikey™",  # Reuben's
        "Sticky Notes: Fresh Hop Extra Pale Ale",  # Reuben's
        "Citra Slicker Wet Hop IPA (Cloudburst Collab)",  # Bale Breaker
        "WET & FRESH HOP AMARILLO IPA",  # Cloudburst
        "DDH West Coast Wet Hop DIPA",  # Cloudburst
        "Mostly Wet Simcoe Fresh Hop IPA (westbound & down collab)",
        "Late Harvest Fresh Hop IPA 2026 IPA - American",  # Hellbent
        "🌿Cloudburst: Aqua Seafoam Shame - Wet Hop Hazy IPA (Strata)🌿",  # Chuck's
        "Head Full of Fresh Hops",  # Fremont (plural)
        "Fresh-Hop Pilsner",
        "Freshhop Pale",
        "Wet-hopped Red Ale",
        "Fresh Hop Hazy IPA",  # non-breaking space from HTML
        "Centy McFreshface Fresh Hop IPA",  # Seapine
    ],
)
def test_fresh_hop_names_match(matcher: ListingMatcher, text: str) -> None:
    assert matcher.matches(text)


@pytest.mark.parametrize(
    "text",
    [
        "Fresh! Raspberry",  # Reuben's fruit beer
        "Fresh Squeezed IPA",
        "A crisp, dry French Saison with a splash of Fresh ginger juice",
        "Refreshing hoppy lager",
        "Hazy IPA brewed with fresh Simcoe hops",  # hop variety breaks the phrase
        "Fresh Hop Fest!",  # an event, not a beer
        "Georgetown Fresh Hop Festival",
        "Oktoberfest Märzen",
        "",
    ],
)
def test_non_fresh_hop_text_does_not_match(matcher: ListingMatcher, text: str) -> None:
    assert not matcher.matches(text)


def test_matches_any_of_several_fields(matcher: ListingMatcher) -> None:
    # Stoup puts "Fresh Hop" only in the style tags, not the beer name.
    assert matcher.matches(
        "Citra Fiend IPA", "IPA, Northwest, Fresh Hop, Traditionally Fall"
    )


def test_none_fields_are_ignored(matcher: ListingMatcher) -> None:
    assert matcher.matches(None, "Fresh Hop IPA", None)
    assert not matcher.matches(None, None)


def test_exclusion_wins_across_fields(matcher: ListingMatcher) -> None:
    assert not matcher.matches("Fresh Hop IPA", "Fresh Hop Fest pour")


class TestFromConfig:
    def test_defaults_without_config(self) -> None:
        matcher = ListingMatcher.from_config(None)
        assert matcher.matches("Fresh Hop IPA")
        assert not matcher.matches("Hazy Cowiche")

    def test_extra_include_extends_defaults(self) -> None:
        # Fremont's fresh-hop beers are named for hop farms, not "fresh hop".
        matcher = ListingMatcher.from_config({"listing_include": ["cowiche"]})
        assert matcher.matches("Hazy Cowiche")
        assert matcher.matches("Fresh Hop IPA")

    def test_extra_exclude_extends_defaults(self) -> None:
        matcher = ListingMatcher.from_config({"listing_exclude": [r"\(2025\)"]})
        assert not matcher.matches("Fresh Hop West Coast IPA (2025)")
        assert not matcher.matches("Fresh Hop Fest!")
        assert matcher.matches("Fresh Hop West Coast IPA (2026)")

    def test_single_string_is_accepted(self) -> None:
        matcher = ListingMatcher.from_config({"listing_include": "cowiche"})
        assert matcher.matches("Hazy Cowiche")

    def test_invalid_pattern_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="listing_include"):
            ListingMatcher.from_config({"listing_include": ["(unclosed"]})

    def test_non_string_pattern_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="listing_exclude"):
            ListingMatcher.from_config({"listing_exclude": [42]})
