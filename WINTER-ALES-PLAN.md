# Plan: add a winter ales page to Seattle Freshies

Status: not started. Written 2026-10-01; decisions settled the same day.

Goal: a fourth seasonal list, winter ales at breweries, at its own permanent
URL, which becomes the home page (`/` 302) once winter beers are pouring. The
`pumpkin` category is the model for every step: it was the last one added and
touches the same files. Two companion changes ride along: an out-of-season
message on every list, and an events page that covers all seasonal events
rather than fresh-hop events only.

## Decisions (settled)

1. **URL: `winter-ales.html`.** Permanent; no year in the name.
2. **Category key: `winter`**, giving per-venue config keys `winter_include` /
   `winter_exclude`, tag class `tag-winter`, and `data-page="winter"`.
3. **What counts:** winter ales and warmers, Christmas and holiday beers, named
   seasonals that never say "winter" (Jolly Roger, Jubelale, Bifrost,
   Abominable, and so on), and, on their own, **barleywines, spiced stouts, and
   barrel-aged stouts**, whether or not the venue calls them a winter beer.
   Borderline beers go on the list, not off it.
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

## Steps

### 1. Matcher: `around_the_grounds/utils/listing_matcher.py`

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
  as with Old Stove Pike Place's `pumpkin_exclude`).

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

Also update the category comment on `Event.category` in
`around_the_grounds/models/schedule.py`.

### 2. Template: `public_templates/fresh-hop/`

- **`winter-ales.html`**: copy `pumpkin.html`; change `data-page`, title,
  description, canonical, `og:*`, heading emoji, tagline, and the current tab.
- **Tab bar on every page** (`fresh-hops.html`, `festbier.html`, `pumpkin.html`,
  `taprooms.html`, `events.html`, and the new page): add the "Winter ales" tab
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
  mention winter ales (source in `deploy/images/`, rendered by `render.py`).

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
`months: [11, 2]`, and `offSeason: 'Winter ales are out of season.'`; add
"Winter ale season runs from November through February." to its tagline; and
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

- `tests/unit/test_listing_matcher.py`: winter matches, near misses, description
  matching, and `winter_include` / `winter_exclude` from config. Cover
  barleywine spellings; barrel-aged and spiced stouts with the two words in
  one field and split across name and style; and plain, imperial, and coffee
  stouts staying off.
- `tests/unit/test_seattle_freshies_config.py`: add the page to
  `test_template_has_every_page` (file list, `data-page` pairs, and the
  expected tab `href` list), `test_open_graph_tags`, and
  `test_pages_link_the_favicon_files`. The sitemap test picks it up by itself.
- `tests/parsers/test_taplist_parsers.py` and `test_pdf_taplist.py`: check for
  assertions that count categories or matched entries per fixture.

### 6. Docs

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
2. Later, when winter ales are the main thing pouring, follow the steps in the
   comment above `RedirectMatch` in
   `deploy/digitalocean/seattlefreshies.com.conf`: change the page name in both
   live Apache files, reload, then make the same change in the repo conf and in
   `public_templates/fresh-hop/index.html` (refresh and canonical lines).
   `test_home_redirects_to_the_in_season_page` fails if the repo copies disagree.

Expected home page sequence: `fresh-hops.html` now, `festbier.html` or
`pumpkin.html` when fresh hops fade, then `winter-ales.html`.

## Out of scope

- Extensionless URLs.
- New event sources beyond the six configured today.
