"""Tests for the fresh-hop listing matcher. Cases are real tap-list text
collected from Seattle breweries and taprooms in September 2026."""

import pytest

from around_the_grounds.config.loader import load_site_config
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
            "Bloktoberfest",  # Block 15
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
            "2015 Artoberfest - People's Choice winner",  # Santiam's awards
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


class TestWinter:
    """Cases from live Seattle, Portland, and Yakima tap lists, 2026-11-06."""

    @pytest.fixture
    def winter(self) -> ListingMatcher:
        return ListingMatcher(category="winter")

    @pytest.mark.parametrize(
        "text",
        [
            "High Camp Winter IPA",  # Bale Breaker
            "Winter Ale",  # Fremont, pFriem
            "Festivus Holiday Ale",  # Black Raven
            "Holiday Haze",  # Reuben's
            "Julebokk Winter Lager (on our Lager Faucet)",  # Reuben's
            "Juleøl",  # Aass at Stein
            "Jubelale (2026)",  # Deschutes
            "Nitro Jubelale",
            "Sleigh'r",  # Ninkasi
            "Sleighjacker - Belgian Strong",  # Victor 23
            "Noël Winter Belgian Ale",  # Delirium
            "BELGIAN CHRISTMAS ALE",  # pFriem
            "Better Than Christmas (2026 Fresh Hop)",  # Elliott Bay; on both lists
            "OL’ SAINT NICK",  # Block 15
            "Ol' Saint Nick (2026)",
            "Scrooge Mcbluffs",  # White Bluffs
            "Nitro: Fa La La",  # Double Mountain
            "SNOWMOTION WINTER ALE",  # Ravenna at Maize & Barley
            "Jolly Roger Strong Ale 2026",  # Rooftop Brew Co at the Jolly Roger
            "Abominable Winter Ale",  # Hopworks
            "The Wintering - Coffee Stout",  # Kings & Daughters
            "Festive Ale",  # Reuben's
            "Gingerbread Cream Stout",  # Lucky Envelope
        ],
    )
    def test_seasonal_names_match(self, winter: ListingMatcher, text: str) -> None:
        assert winter.matches(text)

    @pytest.mark.parametrize(
        "name, style",
        [
            ("High Camp", "Winter IPA"),  # Public House of Yakima
            ("Kitten Mittens", "Winter Ale"),  # Kulshan
            ("Festive Ale", "Winter Warmer"),  # Reuben's at Treebeerd's
            ("Gods Of Winter", "Weizenbock"),  # White Bluffs
        ],
    )
    def test_style_alone_matches(
        self, winter: ListingMatcher, name: str, style: str
    ) -> None:
        assert winter.matches(name, style)

    @pytest.mark.parametrize(
        "name, style",
        [
            ("Castaway ‘25", "Barrel Aged Barleywine"),  # Old Stove
            ("Walls of the Cave English Style Barleywine", None),  # Georgetown
            ("Old Pirates Barrel Aged Barley Wine", "Barleywine - American"),
            ("Mother of All Storms (2025)", "Barleywine - English"),  # Pelican
            ("Scrooge Mcbluffs", "2025 Wheatwine"),
            ("Zvezda", "Barrel Aged Russian Imperial Stout"),  # Burke-Gilman
            ("Bourbon Barrel Aged Imperial Stout", "Stout - Imperial"),  # Hellbent
            ("Overstory Rye Reserve '25", "Rye Barrel-Aged Imperial Stout"),
            ("Overstory Peated Reserve '25", "Peat Barrel-Aged Imperial Stout"),
            ("Skybreak '25", "Mayan Chocolate BA Stout"),  # Single Hill
            ("Cherry Decadence - BA Imperial Stout", None),  # Alesong
            ("The Abyss Port Barrel Aged Stout", "Stout - Imperial"),  # Deschutes
            ("MEXICAN CHOCOLATE STOUT", None),  # pFriem
            ("Stout", "Imperial Stout w/ Cinnamon & Vanilla"),
        ],
    )
    def test_barleywines_and_aged_or_spiced_stouts_match(
        self, winter: ListingMatcher, name: str, style: str
    ) -> None:
        assert winter.matches(name, style)

    def test_aged_and_stout_split_across_name_and_style(
        self, winter: ListingMatcher
    ) -> None:
        # Fremont lists the beer as "Bourbon Barrel-Aged Dark Star"; a bar
        # could carry the style alone as "Imperial Oatmeal Stout".
        assert winter.matches("Bourbon Barrel-Aged Dark Star", "Imperial Oatmeal Stout")
        assert winter.matches("Lighthouse In The Woods", "BA Imperial Stout")
        assert winter.matches("Dark Star", "Imperial Stout · Bourbon Barrel-Aged")

    @pytest.mark.parametrize(
        "name, style",
        [
            ("Wassail", "Cider - Herbed"),  # Yonder at Bale Breaker
            ("HOT SPICED CIDER", None),  # Old Stove
            ("Mulled Cider", None),
        ],
    )
    def test_holiday_ciders_match(
        self, winter: ListingMatcher, name: str, style: str
    ) -> None:
        assert winter.matches(name, style)

    @pytest.mark.parametrize(
        "name, style",
        [
            ("Russian Imperial Stout", None),
            ("Breakfast Stout", "Stout - Coffee"),
            ("Pastry Stout", "Stout - Imperial / Double Pastry"),
            ("Tayberry", "Sour - Barrel-Aged"),  # E9: aged, but not a stout
            ("Resolute", "Porter - Barrel Aged"),  # Dirty Couch
            ("Premature Celebration", "Festbier"),  # Dirty Couch
            ("Pliny the Elder", "Russian River Santa Rosa, CA USA"),  # Über Tavern
            ("Dry Cider", "Cider - Dry"),
            ("Barrel Aged Saison", None),
            ("Snoqualmie Pale", None),
            ("Stoutly Hazy", "IPA - Hazy"),
        ],
    )
    def test_look_alikes_do_not_match(
        self, winter: ListingMatcher, name: str, style: str
    ) -> None:
        assert not winter.matches(name, style)

    @pytest.mark.parametrize(
        "name, style",
        [
            # Step 7 misses, live lists 2026-11-06
            ("Celebration (2026)", "IPA - American"),  # Sierra Nevada
            ("Sierra Nevada Celebration Fresh Hop IPA", None),
            ("New Year, Old Habits - Dry Hopped Strong Ale", None),  # Seapine
            ("Fresh! Sugar Plum 2026", None),  # Reuben's
            ("Spiced Pear", "Cider - Herbed"),  # Single Hill Commons
            ("Lost Lake Cider", "Imperial Spiced"),  # Fremont
            ("Spiced Apple Cider Slushy", None),  # Stoup
            ("16oz Can - Offset Spiced Cranberry", None),  # Big Time
            ("CRANBERRY + SPICE", "Cider - Sweet"),  # Special Brews
            ("Cranberry Spice", None),  # Offset Ciderworks at Ridgecrest
            ("Second Sight", "Strong Scotch Ale"),  # Black Raven
            ("Muckle Flugga Scotch Ale", None),  # Bellevue Brewing
            ("Willie Heavy", "Wee Heavy Scotch Ale"),  # Roscoe's
            ("Cold Smoke", "Scotch Ale"),  # KettleHouse at Public House
            ("Incinerator Doppelbock", None),  # Old Stove Pike Place
            ("Salvator", "Doppelbock"),  # Paulaner at Stein
            ("Co-conspirator - Doppelbock", None),  # Victor 23
            ("Celebrator", "Bock - Doppelbock"),
            ("Ayinger Celebrator, 6.7% ABV", None),  # Prost! West Seattle
            ("Spaten Optimator", None),
            ("Ferment Brewing Woodsman Porter brewed with fir tips", "Porter"),
            ("Woodsman", "Porter w/ Doug Fir Tips"),  # Saraveza
            ("Solstice", "Winter Warmer"),
            ("Solstice Stout", None),
            ("Winter Solstice Ale", None),
        ],
    )
    def test_tuning_additions_match(
        self, winter: ListingMatcher, name: str, style: str
    ) -> None:
        assert winter.matches(name, style)

    def test_wee_heavy_in_a_description_matches(self, winter: ListingMatcher) -> None:
        # Calapooia's Caber Toss is listed as a Scottish Ale
        assert winter.matches_description(
            "A malt-forward ‘wee heavy’ Scottish Ale, loaded with Special B",
            "Caber Toss Scottish Ale",
        )

    def test_spiced_amber_ale_description_matches(self, winter: ListingMatcher) -> None:
        # Strange Weather at Special Brews
        assert winter.matches_description(
            "SPICED AMBER ALE WITH ORANGE PEEL, CINNAMON, GINGER, NUTMEG",
            "Strange Weather",
            "Red Ale - American Amber",
        )

    @pytest.mark.parametrize(
        "name, style",
        [
            ("Elvira's - Spicy Pumpkin Spice Cider", "Cider"),  # pumpkin list
            ("Seattle Cider Pumpkin Spice", None),
            ("Beer of the Dead Spiced Brown Ale", "Brown Ale - Other"),
            ("Cranberry Cider", "Cider - Other Fruit"),
            ("Premature Celebration", "Festbier"),
            ("SHEPHERD'S CROOK SCOTTISH EXPORT", None),  # 4.6%
            ("Thistle While You Work", "Scottish Export Ale"),
            ("Scottish Oatmeal Porter", None),  # Montavilla
            ("Maibock", "Bock - Hell / Maibock / Lentebock"),
            ("Imitator IPA", "IPA - American"),  # Victor 23
            ("Summer Solstice", "Cream Ale"),  # Anderson Valley
            ("Summer-Solstice Saison", None),
            ("The Greater Tingle", "IPA brewed with spruce tips"),  # Stickmen
            ("Venus In Firs", "Farmhouse Ale - Saison"),
            ("Shipwreck Spiced Rum, Scotch, lemon", None),
        ],
    )
    def test_tuning_look_alikes_do_not_match(
        self, winter: ListingMatcher, name: str, style: str
    ) -> None:
        assert not winter.matches(name, style)

    def test_aged_and_stout_do_not_span_into_extra_text(
        self, winter: ListingMatcher
    ) -> None:
        # Only the name and style are joined; a description-like third field
        # mentioning "stout" does not complete "barrel-aged" in the name.
        assert not winter.matches(
            "Bourbon Barrel Aged Sour", None, "aged where our stout once rested"
        )

    def test_join_does_not_change_other_categories(self) -> None:
        # "[\\s-]*" cannot cross the " | " between name and style.
        assert not ListingMatcher().matches("Something Fresh", "Hop Water")

    @pytest.mark.parametrize(
        "description",
        [
            "Our winter ale, brewed with toasted malts.",
            "A holiday beer for the long nights.",
            "English-style barleywine aged two years.",
            "A hot mulled cider for cold days.",
        ],
    )
    def test_description_core_matches(
        self, winter: ListingMatcher, description: str
    ) -> None:
        assert winter.matches_description(description, "Seasonal Special")

    @pytest.mark.parametrize(
        "description",
        [
            "Perfect for winter nights.",
            "Blended with a touch of our barrel-aged stock.",
            "Closed for the holiday.",
        ],
    )
    def test_loose_description_words_do_not_match(
        self, winter: ListingMatcher, description: str
    ) -> None:
        assert not winter.matches_description(description, "Seasonal Special")

    def test_venue_extras_use_winter_keys(self) -> None:
        winter = ListingMatcher.from_config(
            {
                "winter_include": [r"\bsolstice\b"],
                "winter_exclude": [r"^rum\b"],
            },
            category="winter",
        )
        assert winter.matches("Solstice Saison")
        assert not winter.matches("Rum – Jolly Rogers (well), Bacardi")
        assert winter.matches("Jolly Roger Strong Ale")


class TestVenueCategories:
    def test_default_is_every_category(self) -> None:
        assert [m.category for m in ListingMatcher.for_venue({})] == [
            "fresh-hop",
            "festbier",
            "pumpkin",
            "winter",
        ]

    def test_venue_can_limit_categories(self) -> None:
        matchers = ListingMatcher.for_venue({"listing_categories": ["fresh-hop"]})
        assert [m.category for m in matchers] == ["fresh-hop"]

    def test_unknown_category_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown listing category"):
            ListingMatcher.for_venue({"listing_categories": ["gose"]})


class TestVenueWinterExcludes:
    """Venue ``winter_exclude`` entries for non-beer rows (2026-11-06)."""

    @staticmethod
    def _winter(site: str, key: str) -> ListingMatcher:
        venue = next(v for v in load_site_config(site).venues if v.key == key)
        return ListingMatcher.from_config(venue.parser_config, category="winter")

    def test_big_time_liquor_rows_stay_off(self) -> None:
        winter = self._winter("seattle-freshies", "big-time-taps")
        assert not winter.matches("Rum – Jolly Rogers (well), Jolly Rogers Dark Rum")
        assert winter.matches("Jolly Roger Christmas Ale")

    @pytest.mark.parametrize(
        "name",
        [
            "Krampus Kaffe - rye whiskey / Campari / Ancho Reyes / cinnamon / coffee",
            "Old Saint Nick - dark rum / mint / lime / prosecco",
            "Stein's Gluhwein - house-made German mulled wine",
        ],
    )
    def test_stein_cocktails_stay_off(self, name: str) -> None:
        assert not self._winter("yakima-freshies", "stein-leavenworth-taps").matches(
            name
        )

    def test_old_stove_pike_place_cocktails_stay_off(self) -> None:
        winter = self._winter("seattle-freshies", "old-stove-pike-place-taps")
        assert not winter.matches("Shipwreck Spiced Rum, Ryan’s Apple Cider")
        assert not winter.matches("Solstice Sipper")
        assert winter.matches("HOT SPICED CIDER")

    def test_stein_winter_beers_stay_on(self) -> None:
        winter = self._winter("yakima-freshies", "stein-leavenworth-taps")
        assert winter.matches("Juleøl", "Winter Lager")
        assert winter.matches("KBS Spicy Chocolate", "Barrel Aged Stout")
