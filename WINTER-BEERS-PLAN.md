# Plan: add a winter beers page to every Freshies site

Written 2026-10-01; decisions settled the same day.
Steps 1, 2, 5, and 6 done 2026-11-06 (step 3 and 4 earlier); left: step 7
(tune against live lists) and step 8 (ship, then switch the home page).
Revised 2026-11-06 after the first scan with winter beers pouring (see
"Findings from the 2026-11-06 scan").

Scope: all three Freshies sites (Seattle, Portland, and Yakima). They share
the `fresh-hop` template, the matcher, and one Apache conf, so each step below
is done once and every site gets the page. Per-site work is limited to venue
`winter_include` / `winter_exclude` entries, each site's Open Graph card in
`public_templates/_overlays/<site key>/`, and the live Apache files on the
droplet (one pair per domain) when the home page switches.

Goal: a fourth seasonal list, winter beers at breweries, at its own permanent
URL, which becomes the home page (`/` 302) once winter beers are pouring. The
`pumpkin` category is the model for every step: it was the last one added and
touches the same files. Two companion changes ride along: an out-of-season
message on every list, and an events page that covers all seasonal events
rather than fresh-hop events only.

## Decisions (settled)

1. **URL: `winter-beers.html`; label "Winter beers"** (tab, heading, and
   title; changed from "winter ales" on 2026-11-06, before anything shipped,
   since winter IPAs and lagers are a large share of the list). Permanent; no
   year in the name.
2. **Category key: `winter`**, giving per-venue config keys `winter_include` /
   `winter_exclude`, tag class `tag-winter`, and `data-page="winter"`.
3. **What counts:** winter ales and warmers, Christmas and holiday beers, named
   seasonals that never say "winter" (Jolly Roger, Jubelale, Bifrost,
   Abominable, and so on), and, on their own, **barleywines, spiced stouts, and
   barrel-aged stouts**, whether or not the venue calls them a winter beer.
   Borderline beers go on the list, not off it. **Ciders count when they look
   holiday-focused** (decided 2026-11-06): a wassail, a hot spiced or mulled
   cider, a cider with a winter or holiday name. A cider with no seasonal word
   stays off, which the seasonal patterns already ensure; there is no cider
   exclude.
4. **Every list gets an out-of-season message** (step 3).
5. **`events.html` covers all seasonal events**, not only fresh-hop ones
   (step 4).

## Timing

Patterns have to be tuned against live tap lists (no archived pages), and
winter beers do not reach taps until roughly November. So:

- The code, page, and tab can be built any time with a first-guess pattern list.
- Barleywines and barrel-aged stouts pour year-round, so those patterns can be
  tuned against live lists right away.
- Tuning the winter and holiday names (step 7) waits until those beers are
  actually pouring.
- The events change (step 4) did not depend on winter and has shipped.
- Publish the page and its tab a few weeks before making it the home page, so
  it is crawled and indexed with real content first.
- `scripts/winter_scan.py` was used to check live lists before the category
  existed; it was deleted when step 1 shipped. Use `--preview` (step 7) now.

## Steps

### 1. Matcher: `around_the_grounds/utils/listing_matcher.py`

Done 2026-11-06 (committed the same day). The `winter` category is
in `listing_matcher.py` with the patterns below plus the 2026-11-06 additions.
`matches` now also tries the name and style joined by " | ", which settles the
"name and style together" question: a `.*` pattern can span the two fields,
while `[\s-]*` patterns cannot cross the bar, so the other categories behave
as before. Venue excludes: Big Time (liquor rows) in `seattle-freshies.json`
and Stein (cocktails and Glühwein) in `yakima-freshies.json`. No venue sets
`listing_categories`, so every venue picks winter up. Live rescan: Seattle 48,
Portland 31, Yakima 20 after the Stein exclude. "Snow" names (Snow Wit,
Snowblind, Snow Miser) are kept under the include-when-unsure rule.

- Add `WINTER = "winter"`, a `WINTER_INCLUDE` list (name and style), and a
  narrower `WINTER_CORE` list for descriptions.
- Add the `CATEGORIES` entry: `WINTER: (WINTER_INCLUDE, [], "winter", WINTER_CORE)`.
- Update the module docstring and the `from_config` docstring.
- `ListingMatcher.for_venue` defaults to every built-in category, so all venues
  pick winter up with no config change. Check any venue in
  `seattle-freshies.json` that sets `listing_categories` explicitly.

First-guess patterns, to be checked against live lists:

- Name or style, seasonal: `winter` (ale, warmer, lager, bock), `christmas` /
  `xmas`, `holiday`, `no[eë]l`, `yule`, `wassail`, `jubel`, `sleigh`, `santa`,
  `snow[\s-]*cap`, and named seasonals as they turn up.
- Name or style, by style:
  - Barleywine: `barley[\s-]*wine` (covers "Barleywine", "Barley Wine",
    "American Barleywine"); consider `wheat[\s-]*wine` under the
    include-when-unsure rule.
  - Barrel-aged stout: a stout whose name or style also says barrel-aged, in
    either order: `\b(?:barrel|bourbon|whiske?y|rye|rum|brandy)[\s-]*(?:barrel[\s-]*)?aged\b.*\bstout\b`,
    the reverse order, and `\bBA\b.*\bstout\b` (tap lists abbreviate it,
    as they do "FH").
  - Spiced stout: a stout with a spice or winter adjunct in the name or style:
    `spiced`, `cinnamon`, `nutmeg`, `clove`, `ginger(bread)?`, `allspice`,
    `mexican[\s-]*(?:hot[\s-]*)?chocolate`, `chai`, `peppermint`.
  A plain stout, an imperial stout, and a coffee or pastry stout with none of
  those words do not count; that is the line to check against real lists.
- Name and style together: "barrel-aged" is often in the name while "stout" is
  in the style (or the other way around). The matcher tests each field
  separately today, so these two-part patterns need the name and style joined
  into one string for the winter category, or a small "all of these terms,
  across fields" rule in `ListingMatcher`. Decide which when writing the tests.
- Description only (narrower): `winter (ale|warmer)`, `holiday (ale|beer)`,
  `christmas (ale|beer)`, `barley[\s-]*wine`. Plain "winter", "holiday", or
  "barrel-aged" in a description is too loose ("perfect for winter nights",
  "blended with a touch of our barrel-aged stock").
- Overlap: a pumpkin stout with cinnamon lands on both the pumpkin and winter
  lists. That is the existing behavior for a "Fresh Hop Festbier" and is fine.
- Likely excludes: "Winter Park"-style place names, holiday-hours notices and
  gift cards that some tap lists carry as rows, and non-beer rows (cocktails,
  as with Old Stove Pike Place's `pumpkin_exclude`). Holiday-focused ciders
  are not excluded (decision 3).

Findings from a scan of all 67 live tap lists on 2026-10-05, run with the
first-guess patterns above (no winter, Christmas, or holiday ales were pouring
yet; about 14 barleywines and barrel-aged stouts were):

- `santa` matched "Santa Rosa, CA" in the brewery field of two Russian River
  beers at Über Tavern. Use `\bsanta\b(?![\s-]*rosa\b)`, or match seasonal
  names against the name and style only, not the brewery.
- "Celebration" is too loose: it matched Dirty Couch's "Premature Celebration",
  a festbier. Leave it out; add Sierra Nevada's Celebration by full name if it
  turns up.
- A bare `BA` or "barrel-aged" pulls in sours, wild ales, and porters (E9
  Tayberry, de Garde Avenue No. 7, Dirty Couch Resolute, Old Stove's gin-barrel
  sour). It has to be tied to "stout", as the two-part pattern above does.
- `winter` in a description matched Old Stove's "Hot Spiced Cider" ("wintery
  spices"), which confirms that plain "winter" is too loose there and that
  cider rows need excluding.
- Barleywine matching worked as written, including "Barley Wine" and
  "Barleywine - English" styles. White Bluffs' "Scrooge McBluffs" (a
  barleywine) suggests `scrooge` as a seasonal name.

Findings from the 2026-11-06 scan (`scripts/winter_scan.py`, all three
sites; Seattle 44 hits, Portland 27, Yakima 18; three venue 404s, unrelated):

- Winter beers are pouring everywhere. Bale Breaker's High Camp Winter IPA
  shows at its Ballard and Moxee taprooms and at both Public Houses of Yakima,
  where the name is just "High Camp" and only the style ("Winter IPA") matches.
  Other real hits: Fremont Winter Ale, Reuben's Julebokk and Holiday Haze,
  Black Raven Festivus and Hola Daze, Jubelale, Ol' Saint Nick, Abominable,
  Sleigh'r, Delirium Noël, pFriem Winter Ale and Belgian Christmas Ale,
  Seapine Flannel Channel, and many barleywines and barrel-aged stouts.
- Winter IPAs and winter lagers are common (High Camp, Everglow, Fa La La,
  Yippee Ki-P-A, Julebokk, Juleøl). `\bwinter` already takes them. See the
  label decision (decision 1).
- False positives to fix:
  - `santa` still matches "Russian River Santa Rosa, CA" (three rows at Über
    Tavern). Use the negative lookahead from the October findings.
  - Big Time's spirits rows ("Rum – Jolly Rogers (well)…"): a venue
    `winter_exclude` on `\bwell\b` or `\brum\b`, or keep `jolly roger` out of
    the built-ins and add it only for Rooftop Brew Co at the Jolly Roger.
- Ciders: Old Stove's "Hot Spiced Cider" ("wintery spices") and Yonder's
  "Wassail" at Bale Breaker Ballard both look holiday-focused, so both stay
  (decision 3). Hot Spiced Cider matches only because its second field
  says "wintery spices", which is luck; add `mulled` and `hot[\s-]*spiced` to
  the name patterns (alongside `wassail`) so ciders like it match on their
  names.
- Borderline, keep (include when unsure): Elliott Bay "Better Than Christmas
  (2026 Fresh Hop)", which is a fresh-hop pale ale that will sit on both
  lists; Ravenna "Short Days, Long Nights, Let's Party" (fresh-hop winter
  IPA); Stickmen "Lack-O-Jantern" (pumpkin barleywine, on both lists).
- Check why these matched before writing tests (probably a description hit):
  Big Time "Breakfast Cereal Killer Stout", Urban Family "Treehouse In the
  City '25", and Calapooia "Turkish Coffee Stout".
- Names to add to the built-ins, since a row with no style would miss them:
  `high[\s-]*camp`, `scrooge`, `saint[\s-]*nick`, `\bfa[\s-]*la\b`,
  `festive`, `\bjul(?:e|ø|ebokk)`, `\bsnow` (Snowmotion, New Belgium Snow
  Day), `festivus`. Skim each venue's full list during step 7 for others.

Also update the category comment on `Event.category` in
`around_the_grounds/models/schedule.py`.

### 2. Template: `public_templates/fresh-hop/`

Done 2026-11-06 (committed the same day). `winter-beers.html`
(❄️, `data-page="winter"`) has a tagline naming what the list holds ("Winter
warmers, holiday beers and ciders, barleywines, and barrel-aged stouts…") and
the season (November through February). The "Winter" tab sits between Pumpkin
and Taprooms on every page. `app.js` has the `winter` page (`months: [11, 2]`)
and label, and the taprooms page takes winter too. Tag colors: `--winter`
#2c5d8a light, #8dbbe6 dark (AA on the chip in both). Six tabs fit from 375px
up as before; a new `max-width: 360px` rule (11px type, 3px padding) fits
them at 320px. The Open Graph card says "and other seasonal beers", so it is
unchanged. Step 3's leftover items (season, out-of-season sentence, and the
parametrized tests) are done here too. Seattle preview: 36 winter beers at 21
breweries, and 20 winter tags on the taprooms page.

- **`winter-beers.html`**: copy `pumpkin.html`; change `data-page`, title,
  description, canonical, `og:*`, heading emoji, tagline, and the current tab.
- **Tab bar on every page** (`fresh-hops.html`, `festbier.html`, `pumpkin.html`,
  `taprooms.html`, `events.html`, and the new page): add the "Winter beers" tab
  and update the shared-layout comment. That makes six tabs; check that the
  pinned bar still fits at phone width.
- **`app.js`**: add `winter` to `PAGES` and `CATEGORY_LABELS`, and to the
  header comment. Add `'winter'` to the `taprooms` page's `categories` and
  reword its `beers` / `none` strings, which currently name all three lists.
- **`taprooms.html`**: tagline and meta descriptions name the three lists;
  reword.
- **`styles.css`**: a `--winter` color for light and dark themes and a
  `.tag-winter` rule, next to `--pumpkin` / `.tag-pumpkin`.
- **`sitemap.xml`**: add the new URL.
- **`og-image.png`**: check whether the card text or its alt text should
  mention winter beers (source in `deploy/images/`, rendered by `render.py`).

### 3. Out-of-season message (done 2026-10-02)

Shipped for the three existing lists. In `app.js`, each seasonal entry in
`PAGES` has `months` ([first, last], inclusive, may wrap the new year) and an
`offSeason` sentence. An empty list outside its months shows that sentence
plus links to the lists that have beers pouring, and hides the "Checked, no …"
notice. A list with beers always shows them. The month comes from
`data.updated` in site time. Each page's tagline states the season in static
HTML for crawlers. Tests: `tests/unit/test_fresh_hop_seasons.py` (runs
`app.js` in Node with a stub DOM).

Ranges (confirmed 2026-10-02): fresh hops August through October,
festbier September through October, pumpkin September through November.

Left for the winter work: give the `winter` page `href`, `label`,
`months: [11, 2]`, and `offSeason: 'Winter beers are out of season.'`; add
"Winter beer season runs from November through February." to its tagline; and
add the page to the two parametrized tests.

### 4. Events page: all beer events (done 2026-10-01)

Shipped ahead of the rest, and wider than first planned: the calendar shows
anything known today that is of interest to beer nerds, not only seasonal
events.

- `event_filter` keeps events matching any of the venue's listing categories
  (setting `Event.category`, shown as a tag) plus untagged general beer events
  by title (`EVENT_INCLUDE` in `scrapers/coordinator.py`: fest, release,
  tapping, anniversary, cask, and so on). Titles saying "closed" or "hours"
  are dropped (`EVENT_EXCLUDE`). Family events with a seasonal word, such as
  pumpkin carving, are kept on purpose.
- Venues adjust it with `event_include` / `event_exclude`. Georgetown's list is
  all beer events, so it sets `event_include: ["."]`.
- All six sources look 365 days ahead, so "Winter Beer Fest" and "PNA Winter
  Beer Taste" already show.

Left for the winter work:

- Once the `winter` category exists, those events gain a "Winter" tag with no
  further change. Add winter cases to `tests/unit/test_event_filtering.py`.
- Winter words are the risky ones for tagging: extend `EVENT_EXCLUDE` for
  "Holiday market", "Christmas Eve", and similar when they turn up.
- More event sources (other breweries' calendars) are a separate question.

### 5. Tests

Done 2026-11-06 with steps 1 and 2 (1427 tests).

- `tests/unit/test_listing_matcher.py`: winter matches, near misses, description
  matching, and `winter_include` / `winter_exclude` from config. Cover
  barleywine spellings; barrel-aged and spiced stouts with the two words in
  one field and split across name and style; and plain, imperial, and coffee
  stouts staying off.
- `tests/unit/test_freshies_sites.py` (runs for every Freshies site): add the
  page to `PAGES`, which feeds the layout, tab order, Open Graph, and favicon
  tests. The sitemap test picks it up by itself.
- `tests/parsers/test_taplist_parsers.py` and `test_pdf_taplist.py`: check for
  assertions that count categories or matched entries per fixture.

### 6. Docs

Done 2026-11-06 with steps 1 and 2.

- `CLAUDE.md`: template tree, the category list in the tap-list parser
  paragraph, and the test count.
- `ADDING-VENUES.md`: category descriptions, the `winter_include` /
  `winter_exclude` row, and the template summary ("five pages" becomes six).
- `README.md`: the Seattle Freshies paragraph and the test count.

### 7. Tune against live data

```bash
uv run around-the-grounds --site seattle-freshies --preview --verbose
cd public && python -m http.server 8000
```

Read every venue's winter matches and skim their full tap lists for misses.
Fix with built-in patterns when a term is general, and with per-venue
`winter_include` / `winter_exclude` when it is one venue's naming.

### 8. Ship, then switch the home page

1. Commit, push, and let the cron job publish the new page and tab.
2. Later, when winter beers are the main thing pouring, follow the steps in the
   comment above `RedirectMatch` in
   `deploy/digitalocean/freshies-site.conf`: change the page name in both
   live Apache files, reload, then make the same change in the repo conf and in
   `public_templates/fresh-hop/index.html` (refresh and canonical lines).
   `test_home_redirects_to_the_in_season_page` fails if the repo copies disagree.

Expected home page sequence: `fresh-hops.html` now, `festbier.html` or
`pumpkin.html` when fresh hops fade, then `winter-beers.html`.

## Out of scope

- Extensionless URLs.
- New event sources beyond the six configured today.
