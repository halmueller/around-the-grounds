"""Tests for the fresh-hop listing matcher. Cases are real tap-list text
collected from Seattle breweries and taprooms in September 2026."""

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


@pytest.mark.parametrize(
    "text",
    ["Bug Hazy FH IPA", "FH Italian Pilsner", "Wet Season Citra fh Hazy IPA"],
)
def test_fh_abbreviation_matches(matcher: ListingMatcher, text: str) -> None:
    assert matcher.matches(text)


@pytest.mark.parametrize("text", ["FHB Lager", "Chief Hop IPA", "UFH Stout"])
def test_fh_inside_other_words_does_not_match(
    matcher: ListingMatcher, text: str
) -> None:
    assert not matcher.matches(text)


def test_fh_in_a_description_does_not_count(matcher: ListingMatcher) -> None:
    assert not matcher.matches_description("Brewed for FH season", "Pale Ale")


def test_matches_any_of_several_fields(matcher: ListingMatcher) -> None:
    # Stoup puts "Fresh Hop" only in the style tags, not the beer name.
    assert matcher.matches(
        "Citra Fiend IPA", "IPA, Northwest, Fresh Hop, Traditionally Fall"
    )


def test_none_fields_are_ignored(matcher: ListingMatcher) -> None:
    assert matcher.matches(None, "Fresh Hop IPA", None)
    assert not matcher.matches(None, None)


def test_festival_names_are_excluded(matcher: ListingMatcher) -> None:
    assert not matcher.matches("Fresh Hop Fest")
    assert not matcher.matches("Fresh Hop Ale Festival", "Saturday")


def test_festival_exclude_is_name_only(matcher: ListingMatcher) -> None:
    assert matcher.matches("Fresh Hop IPA", "Fresh Hop Fest pour")
    assert matcher.matches_description(
        "FRESH HOP collab brewed for Fresh Hop Ale Festival", "Collab IPA"
    )
    assert matcher.matches("Fresh Hop Fest Bier")


def test_venue_exclusion_wins_across_fields() -> None:
    matcher = ListingMatcher(exclude=["cocktail"])
    assert not matcher.matches("Fresh Hop IPA", "Fresh Hop cocktail")
    assert not matcher.matches_description("fresh hop cocktail", "Spritz")


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


class TestFestbierCategory:
    @pytest.fixture
    def festbier(self) -> ListingMatcher:
        return ListingMatcher(category="festbier")

    @pytest.mark.parametrize(
        "text",
        [
            "Festbier",  # style (Beer Junction, Stoup)
            "BEHIND THE ROWS - FESTBIER",  # Bizarre
            "German-Style Festbier",  # Cloudburst
            "Fest Beer",
            "Oktoberfest Märzen",  # Obec
            "Oktoberfest Marzen",
            "Bobtoberfest",  # Heater Allen, at Beer Junction
            "Octoberfest Lager",
            "Maerzen",
            "Märzen",
            "Wiesn",
        ],
    )
    def test_festbier_names_match(self, festbier: ListingMatcher, text: str) -> None:
        assert festbier.matches(text)

    @pytest.mark.parametrize(
        "text",
        [
            "Fresh Hop Fest!",
            "Fresh Hop Festival",
            "Festive Winter Ale",
            "Fresh Hop IPA",
        ],
    )
    def test_look_alikes_do_not_match(
        self, festbier: ListingMatcher, text: str
    ) -> None:
        assert not festbier.matches(text)

    def test_fresh_hop_festbier_is_both(self, festbier: ListingMatcher) -> None:
        assert festbier.matches("Fresh Hop Festbier (2026)")
        assert ListingMatcher().matches("Fresh Hop Festbier (2026)")

    def test_venue_extras_use_their_own_keys(self) -> None:
        config = {"festbier_include": ["zwickel"], "listing_include": ["cowiche"]}
        festbier = ListingMatcher.from_config(config, category="festbier")
        assert festbier.matches("Zwickel Lager")
        assert not festbier.matches("Hazy Cowiche")


class TestPumpkin:
    @pytest.fixture
    def pumpkin(self) -> ListingMatcher:
        return ListingMatcher(category="pumpkin")

    @pytest.mark.parametrize(
        "text",
        [
            "Pumpkin Ale",  # Fremont
            "Kilty MacPumpkin",  # Postdoc
            "Your Worst Nightmare Pumpkin Double Milk Stout",  # Cloudburst
            "MOONSHAKE OAT STOUT: PUMPKIN EDITION",  # Bizarre
            "Hello, Gourdgeous: A collaboration with A La Mode Pies",  # Ravenna
            "Punkuccino - Coffee Pumpkin Ale",  # Elysian at Chuck's
            "Jack-o'-Lantern Ale",
            "Calabaza Blanca",
        ],
    )
    def test_pumpkin_names_match(self, pumpkin: ListingMatcher, text: str) -> None:
        assert pumpkin.matches(text)

    @pytest.mark.parametrize(
        "text", ["Fall Hornin'", "Oktoberfest Märzen", "Squash Court Saison", ""]
    )
    def test_other_beers_do_not_match(self, pumpkin: ListingMatcher, text: str) -> None:
        assert not pumpkin.matches(text)

    def test_style_alone_matches(self, pumpkin: ListingMatcher) -> None:
        # Untappd lists Anderson Valley's Fall Hornin' with style "Pumpkin".
        assert pumpkin.matches("Fall Hornin'", "Pumpkin")

    def test_description_matches(self, pumpkin: ListingMatcher) -> None:
        assert pumpkin.matches_description(
            "A dark ale brewed with roasted pumpkin.", "Looming Specter"
        )

    def test_venue_exclude_drops_cocktail(self) -> None:
        pumpkin = ListingMatcher.from_config(
            {"pumpkin_exclude": [r"\bvodka\b"]}, category="pumpkin"
        )
        assert not pumpkin.matches("Batch 206 Vodka, Cold brew, Pumpkin Spiced Simple")
        assert pumpkin.matches("PUMPKIN ALE")


class TestVenueCategories:
    def test_default_is_every_category(self) -> None:
        assert [m.category for m in ListingMatcher.for_venue({})] == [
            "fresh-hop",
            "festbier",
            "pumpkin",
        ]

    def test_venue_can_limit_categories(self) -> None:
        matchers = ListingMatcher.for_venue({"listing_categories": ["fresh-hop"]})
        assert [m.category for m in matchers] == ["fresh-hop"]

    def test_unknown_category_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown listing category"):
            ListingMatcher.for_venue({"listing_categories": ["gose"]})
