# Plan: Freshies sites for Portland, the Yakima Valley, and Bend

Status: phase 0 done (2026-10-12). Phase 1 (Portland) started: first survey
pass done and 28 venues configured (2026-10-13); not live.
Written 2026-10-12.

Goal: reuse the Seattle Freshies site (the `fresh-hop` template, the tap-list
parsers, and the `--output-dir` cron deploy) for three more regions, one site
config and one domain each. Order: **Portland first**, then the Yakima Valley
(with Ellensburg, Prosser, and the Tri-Cities), then Bend.

Nothing here needs a new parser up front. The work is a one-time change so the
template and deploy scripts stop assuming Seattle, then a venue survey and a
config file per region.

## What the repo assumes about Seattle today

- **Template text.** `public_templates/fresh-hop/` names Seattle or
  seattlefreshies.com about 60 times: every page's title, description,
  canonical, `og:*` tags, heading, and tagline; `sitemap.xml`; `robots.txt`;
  the `index.html` fallback; and one string in `app.js` ("in and around
  Seattle"). `_write_site_output` copies the template as is, with no
  substitution.
- **Open Graph card.** `og-image.png` is rendered from
  `deploy/images/seattle-freshies.html` and lives in the shared template.
- **Deploy.** `deploy/digitalocean/run.sh` hardcodes `--site seattle-freshies`;
  the Apache conf, crontab example, log name, and lock file are all
  Seattle-named.
- **Tests.** `tests/unit/test_seattle_freshies_config.py` (15 tests) loads one
  site and asserts Seattle URLs.

Everything else is already per-site: the matcher, the parsers, `venue_type`,
`event_filter`, the season logic in `app.js`, and `public_url`.

## Decisions to settle before starting

Settled 2026-10-12: the Portland domain is `portlandfreshies.com` (not yet
registered), and the first pass covers the metro area, including Vancouver,
WA. Items 3 and 4 were built as recommended. Still open: the Yakima site's
name, and item 5.

1. **Names and domains.** As of 2026-10-12, `whois` shows no registration for
   `portlandfreshies.com`, `pdxfreshies.com`, `yakimafreshies.com`, or
   `bendfreshies.com`. Recommended: `portlandfreshies.com` (matches the Seattle
   name; `pdxfreshies.com` as a redirect if wanted) and `bendfreshies.com`.
   The Yakima site reaches from Ellensburg to the Tri-Cities, so
   `yakimafreshies.com` undersells it; decide between that and a wider name.
2. **Portland's edge.** Recommended: city of Portland first, then a metro sweep
   (Beaverton, Hillsboro, Milwaukie, Oregon City, Gresham, and Vancouver, WA),
   as Seattle did with Redmond, Bothell, and Edmonds. Hood River and the Gorge
   stay out; they are their own cluster.
3. **One template or a copy per city.** Recommended: one template with
   build-time placeholders (phase 0). Copies would drift the first time a page
   or tab is added, and the winter ales page is about to add one.
4. **Same droplet.** Recommended: yes, one more virtual host, cron line, and
   web root per site, under the same `freshies` user.
5. **Area grouping for the Yakima site.** Its venues are up to 100 miles apart.
   Recommended: start with the town in the venue name, as Seattle does with
   "(Ballard)", and add grouping by area only if the flat list reads badly.

## Timing

Fresh-hop season is nearly over, and patterns can only be tuned against live
tap lists (no archived pages). So a site launched this fall opens on the tail
of festbier and pumpkin, then winter ales, and gets its fresh-hop tuning in
August 2027. That is fine for Portland, where the point of launching now is to
be indexed and known before next harvest. The Yakima site is mostly a fresh-hop
site; building it in summer 2027 loses little.

## Phase 0: make the template and deploy region-neutral

Do this once, before the Portland config. Seattle's output must stay
byte-identical apart from intended changes.

### 0.1 Placeholders in the `fresh-hop` template (done 2026-10-12)

Shipped as planned, with these specifics: tokens are `{{site_name}}`,
`{{public_url}}`, and `{{place}}` (no `{{domain}}`; the bare domain only
appeared in comments). Values must be plain text, since they land unescaped in
HTML, XML, JSON, and JavaScript. Rendered Seattle output differs from the
previous template only in three comments. `test_seattle_freshies_config.py`
now reads the rendered site; the cross-site parametrizing is still 0.4.
The header byline is per site too: `{{author_home}}` is "Ballard" for
Seattle and "Seattle" for the other cities, and the ballardfoodtrucks.com
line sits in a `{{#ballard_food_trucks}}` block that only Seattle turns on.

Original notes:


- Add an optional `template_vars` object to the site JSON and `SiteConfig`
  (default empty), loaded in `config/loader.py`.
- In `_write_site_output`, after the copy, substitute `{{name}}` tokens in the
  template's text files (`.html`, `.js`, `.xml`, `.txt`) when the site has
  `template_vars`. Sites without it (Ballard, Park Slope, children's events)
  are untouched, which keeps this safe for the other maintainers.
- The Temporal `deploy_to_git` activity only receives `web_data`, so carry the
  vars in `web_data` (as `public_url` is today) rather than reading the config
  at write time.
- Substitution is deterministic, so the no-op deploy short-circuit still holds.
- Fail the build on an unknown or leftover `{{token}}` rather than publish it.
- Tokens needed, from the grep of Seattle strings:
  - `{{site_name}}`: "Seattle Freshies"
  - `{{public_url}}` and `{{domain}}`: canonical, `og:url`, `og:image`,
    sitemap, robots
  - `{{place}}`: "Seattle", used as "at {{place}} breweries" and "in and
    around {{place}}"; "Portland" and "Bend" drop in, and the Yakima site needs
    wording that reads well in both spots (check when writing it)
- Replace the Seattle strings in all six HTML files, `app.js`, `sitemap.xml`,
  and `robots.txt`, and add `template_vars` to `seattle-freshies.json`.

### 0.2 Per-site Open Graph card (done 2026-10-12)

Shipped: `deploy/images/og-card.html` is the one card source, and
`render.py` writes `public_templates/_overlays/<site key>/og-image.png` for
every site on the `fresh-hop` template (or the keys given), shrinking the name
when it would wrap. `_write_site_output` copies a site's overlay directory over
the template. Seattle's card moved there unchanged. A test fails for any
`fresh-hop` site without a card.

Original notes:


- `deploy/images/render.py`: take the site name and domain as arguments and
  render one card per site from one HTML source.
- The card cannot live in the shared template. Add a small per-site overlay
  directory, copied on top of the template in `_write_site_output`, holding
  `og-image.png` for now. Favicons stay shared.

### 0.3 Deploy scripts: `deploy/digitalocean/` (done 2026-10-12)

Shipped:

- `run.sh [site key]` (default `seattle-freshies`, so the live cron line keeps
  working). The web root defaults to `/var/www/<host of public_url>`, read from
  the site config, and the per-site lock to `/tmp/<site key>.lock`.
- Sites take turns: `run.sh` holds one lock shared by every site while it
  scrapes, waiting up to 25 minutes, so staggered cron minutes are a
  convenience rather than the only protection for shared upstream hosts.
- `seattlefreshies.com.conf` became `freshies-site.conf`, one virtual host
  with `SITEDOMAIN` standing for the domain. New sites' Apache logs are named
  `<domain>-error.log`; Seattle's live ones keep their older names.
- `crontab.example` has a line per site (Portland's commented out, at :22) and
  shows the per-line `HEALTHCHECK_URL=` form. `logrotate.conf` covers every
  site's log and installs once as `/etc/logrotate.d/freshies`.
- `README.md` there is written for any site, using `$SITE` and `$DOMAIN`.

To do on the droplet after pulling (Seattle keeps running either way):
replace `/etc/logrotate.d/seattle-freshies` with the new `freshies` file
before a second site's log exists.

Original notes:


- `run.sh`: take `SITE_KEY` (default `seattle-freshies`, so the live cron line
  keeps working) and derive `WEB_ROOT` and `LOCK_FILE` from it.
- Apache: one conf per domain. Either copy `seattlefreshies.com.conf` per site
  or turn it into a template with the domain as the only variable. The home
  page `RedirectMatch` is the same in-season page for every site.
- `crontab.example`: one line per site, staggered across the hour (Seattle at
  :07 today). `HostThrottle` spaces requests per process, so two sites running
  at once would double the rate on shared hosts such as business.untappd.com
  and docs.google.com. Check the Seattle log for run length and leave a gap.
- Per site on the server: web root, certificate, `analytics-config.js` with its
  own TelemetryDeck app ID, log file, and healthchecks.io check.
- Update `deploy/digitalocean/README.md` (21 Seattle references).

### 0.4 Tests (done 2026-10-12)

Shipped: `tests/unit/test_freshies_sites.py` runs once per site on the
`fresh-hop` template and reads the site as published (placeholders filled,
overlay copied). A new site is covered as soon as its config file exists, and
fails until it has `template_vars`, a card, alphabetical venues, and so on.
`test_seattle_freshies_config.py` keeps only what is true of Seattle (its
name and URL, the Bale Breaker location, and its event-source and taproom
keys); give each new site a file like it. Placeholder, overlay, and `run.sh`
tests came with 0.1 through 0.3.

Original notes:


- Turn `test_seattle_freshies_config.py` into a test parametrized over every
  site whose template is `fresh-hop`: basics, unique keys, alphabetical order
  ignoring articles, generic listing parsers only, typed taprooms, sitemap,
  robots, home redirect, and Open Graph tags against that site's `public_url`.
  Seattle-only assertions (Bale Breaker's Ballard taproom) stay in their own
  test.
- New tests for substitution: every token replaced, no leftover `{{`, sites
  without `template_vars` copied unchanged, and unknown tokens rejected.
- `tests/integration/test_output_dir.py` and
  `tests/browser/render_fresh_hop.mjs`: run against substituted output.

## Phase 1: Portland

### 1.1 Venue survey

This is most of the work, and the step that decides the real effort. For each
venue: is it open, does it publish a current draft list as text, on what
platform, and is that host reachable from the droplet.

- Start from a current list, not memory. The New School tracks Oregon openings
  and closings, and the Oregon Brewers Guild has a member directory. Oregon
  lost 29 breweries, taprooms, and cideries in 2025, so any older list is
  wrong in places.
- Known closed (from 2026 news): Upright, Assembly, and Rogue. Believed
  closed: Ecliptic.
- Candidate breweries, unverified: Breakside (several pubs), Great Notion,
  Ruse, Wayfinder, Gigantic, Baerlic, Von Ebert, Level, StormBreaker,
  Migration, Occidental, Zoiglhaus, Grand Fir, Living Häus, Steeplejack,
  Threshold, Little Beast, Hopworks, Cascade, Deschutes (Pearl), 10 Barrel,
  Fort George's Portland outpost if it has one, Old Town, Lucky Labrador,
  Laurelwood, Montavilla Brew Works, Gateway, Labyrinth Forge, and
  McMenamins (many pubs; likely one brewery-wide list, as with Elliott Bay).
- Candidate taprooms and bottle shops, unverified: Belmont Station, The
  BeerMongers, Roscoe's, Saraveza, John's Marketplace, Loyal Legion, Imperial
  Bottle Shop, Horse Brass, Apex, Prost, and Bottles.
- Great Notion was skipped in Seattle because its tap list pages were stale
  screenshots; check whether the Portland pubs differ.
- Expect DigitalPour to be common (it is a Portland company), then Untappd for
  Business embeds. Seattle has one `digitalpour` venue, so that parser has had
  little exercise; test it against several Portland venues early.
- Approved sources carry over: Untappd for Business embeds, venues' own sites,
  and BeerMenus at a low rate with the honest User-Agent. untappd.com venue
  pages are blocked from the droplet. Image-only tap lists are skipped until
  the OCR question is settled.
- Record skips and closures with the reason, as for Seattle.

#### Survey, first pass (2026-10-12)

Starting list: Open Brewery DB records for Portland and 22 nearby cities
(156 records, many stale) plus about 60 newer breweries and taprooms from
memory. Each site was fetched with the scraper's own User-Agent, along with
its menu-like pages, and searched for tap-list platforms. This says what a
site serves to the scraper from a home connection; the droplet check (1.5) is
still to do. Web addresses for the "not reached" group were guesses or old
records, so that group says nothing yet about whether the venue is open.

**Configured and scraping (13):** ABV Public House (Hillsboro), The
BeerMongers, Belmont Station, Brothers Cascadia Evergreen Pub (Vancouver),
Deschutes (Pearl District), Final Draft Taphouse (Vancouver), Heathen
(Vancouver), The Hoppy Brewer (Gresham), Loyal Legion (Beaverton and
Southeast Portland), Saraveza, Uptown Beer Co., and Victor 23 (Vancouver).
Ten are Untappd embeds, two DigitalPour, and one TapHunter. The first live run
found 154 matching beers (the two Loyal Legions alone had 59 fresh-hop beers).

**Second batch, configured 2026-10-13 (15):** Ancestry (Tualatin), Away Days,
Bent Shovel (Oregon City), Brujos, Duality, FlyBoy (Tigard), Function PDX,
Grains of Wrath (Camas), Montavilla Brew Works, Prost, StormBreaker (St. Johns
and Mississippi), Three Mugs brewery (Hillsboro), TPK, and Wayfinder. All use
`html-taplist` or `text-taplist`. Brujos and Wayfinder put the name on one
line and what the beer is on the next, so `text-taplist` gained a
`detail_lines` option. With both batches a live run finds 191 matching beers
at 28 venues, with no errors.

**Still to check: is the page a current draft list or a catalogue?** Barrel
Mountain (Battle Ground), Breakside (per-location pages), Chuckanut P-Nut
Beer Hall, Coin Toss (Oregon City), Living Häus, Mad Cow, Rosenstadt, and
Zoiglhaus. Ridgefield Craft Brewing's page says it lists "a few of the beers
you'll find on tap throughout the year", so it is a catalogue: not added.
Threshold's published Google Doc turned out to be its music schedule; its tap
list is on its home page and needs a closer look.

**Needs a closer look** (list loads by script, sits in a PDF or an ordering
site, or was not found): Alameda, Baerlic, Binary (Beaverton), Cascade, Double
Mountain (Overlook and Woodstock), Gigantic, Golden Valley (Beaverton), Grand
Fir (PDF), Imperial Bottle Shop (Google Docs), John's Marketplace, Laurelwood,
Level, Loowit (Vancouver), Oakshire's Portland beer hall (its embed is the
Eugene pub's), Old Market Pub, Old Town, Oregon City Brewing, pFriem
(Milwaukie), Roscoe's, Ruse (site "undergoing updates"), Sasquatch, Shoug
(Washougal, PDF), Steeplejack (PDFs), Stickmen, Tiny Bubble Room, Trap Door
(Vancouver), Vanguard (Wilsonville), Von Ebert, Waltz (Forest Grove), and
Wolf Tree. McMenamins has one "On Tap" page for all its pubs; decide whether
to treat it as Elliott Bay was in Seattle.

**Would need a new parser or a decision:**

- Canva draft lists: Migration (Glisan, Williams, and Gresham). The `canva`
  parser sends a browser User-Agent, approved so far only for Old Stove and
  Ship Canal; ask before using it here.
- Pourwall embeds: Three Mugs pub and Vertigo (both Hillsboro). No parser yet.
- Arryved online ordering: Wayfinder and Little Beast. No parser yet;
  Wayfinder's menu page may do without one.
- Untappd display boards (not the website embed): Cooper Mountain (Tigard and
  Sherwood). No parser yet.
- untappd.com venue page only: Horse Brass. Blocked from the droplet.

**Bot challenge (Cloudflare) from a home connection:** Hopworks, Lucky
Labrador, Crux (Portland), and 649 Taphouse (Aloha).

**Skipped:** The Civic Taproom and Raindrop Taphouse (Beaverton): their pages
carry an Untappd embed, but Untappd answers 404 for both. Full Sail and The
Growler Guys showed no Portland-area location; Ex Novo's site lists only its
New Mexico locations.

**Closed:** Ambacht (Hillsboro; its site says so), Mayfly (closed 2026-09-12;
its site says so), and, from 2026 news reports, Upright, Assembly, and Rogue.
Believed closed, not verified: Ecliptic, Hair of the Dog, BridgePort, Burnside,
Portland Brewing, Base Camp, and Culmination.

**Domain now shows unrelated content** (likely closed, or the address is
wrong): Gateway, Pono, Scout, Second Profession, Natian, Railside (Vancouver),
Columbia River, Max's Fanno Creek, and Tin Bucket.

**Not reached; need the right address:** Great Notion, Occidental, Back
Pedal, Brewery 26, Doomsday (Washougal), Drinking Horse (Clackamas), Feckin
(Oregon City), Hammer & Stitch, Dirty Pretty, Shattered Oak (Oregon City),
Hetty Alice, Labrewatory, Mt Tabor, Smockville (Sherwood), Two Kilts
(Sherwood), Hillbilly (Ridgefield), Apex, N.W.I.P.A., Lombard House, Bridgetown
Beerhouse, Concordia Ale House, Growlers Hawthorne, Orenco Taphouse, Tigard
Taphouse, Ben's Bottle Shop and The Thirsty Sasquatch (Vancouver), and
Brewed (Vancouver). Empty or script-only home pages: Fortside, Heavy Metal,
Irrelevant, and Vice (all Vancouver), Northwood (Battle Ground), Kaiser
(Forest Grove), Tall Trees (Hillsboro), Beer Bunker, Beer Store Milwaukie,
Little Hop, Look Long, Labyrinth Forge, Fracture, and Proper Pint.

**Not yet looked up at all:** 10 Barrel's Portland pub, and anything that
opened recently enough to be in neither starting list. Cross-check against
The New School's openings and closings before calling the survey complete.

Tuning notes from the first run: Uptown Beer Co. numbers its taps in the beer
name ("2. 🌿Fresh Hop Cumulus (Citra)"); strip the number in 1.4. A pumpkin
cider at Loyal Legion matches `pumpkin`, as it would in Seattle.

### 1.2 Site config: `config/sites/portland-freshies.json`

- `template: "fresh-hop"`, `timezone: "America/Los_Angeles"`, `public_url`,
  `generate_description: false`, no `target_repo`, and `template_vars`.
- Venues alphabetical ignoring articles, the neighborhood in parentheses for
  multi-location breweries, and `venue_type: "taproom"` for bottle shops and
  taprooms.
- Add in batches of 10 to 15, previewing each batch, rather than all at once.

### 1.3 Event sources

Pick four to six venue or guild calendars with `event_filter` and
`event_window_days: 365`, as Seattle has. Candidates come out of the survey;
the Fresh Hop Pop-Up Beer Fest and the Oregon Brewers Guild calendar are the
ones to look for first.

### 1.4 Tune against live lists

```bash
uv run around-the-grounds --site portland-freshies --preview --verbose
cd public && python -m http.server 8000
```

Read every venue's matches and skim full lists for misses. Festbier and
pumpkin can be tuned now; barleywines and barrel-aged stouts too, once the
winter category exists. Fresh-hop tuning waits for August 2027. Watch for
Oregon naming the Seattle patterns have not seen, and fix general terms in
`listing_matcher.py` and one venue's habits with per-venue includes and
excludes.

### 1.5 Droplet dry run

Run the preview on the droplet before publishing. Datacenter addresses get
bot-challenged where a home connection does not; this is what removed several
Seattle venues.

### 1.6 Launch

1. Register the domain and point DNS at the droplet.
2. Web root, Apache conf, certificate, analytics config, and healthcheck.
3. Add the staggered cron line and confirm the first hourly publish.
4. Submit the sitemap to Google Search Console.
5. Docs: `CLAUDE.md` (site list, config tree, test count), `README.md`, and
   `ADDING-VENUES.md` (the `template_vars` field).

## Phase 2: Yakima Valley, Ellensburg, Prosser, and the Tri-Cities

Same steps as Portland with a smaller survey, roughly 25 to 35 venues.

- Start from the Washington Beer brewery list for Kittitas, Yakima, Benton,
  and Franklin counties.
- Candidates, unverified:
  - Yakima area: Bale Breaker (Moxee), Single Hill, Cowiche Creek, Wandering
    Hop, Valley Brewing, Hop Capital, Bron Yr Aur (Naches), and Varietal
    (Sunnyside).
  - Ellensburg: Iron Horse and Whipsaw.
  - Prosser: Horse Heaven Hills.
  - Tri-Cities: Ice Harbor, White Bluffs, Bombing Range, Moonshot, Atomic Ale,
    and Paper Street, plus taprooms such as Dovetail Joint.
- **Venue key clash:** the registry looks up `venue.key` before `source_type`,
  and `bale-breaker` belongs to Ballard's food-truck parser. The Moxee taproom
  needs a different key, as `bale-breaker-seattle-taps` does in Seattle. Check
  every new key against `parsers/registry.py`.
- Events matter more here than anywhere: the Fresh Hop Ale Festival in Yakima
  and the harvest-season brewery events are the draw.
- Small-town breweries are more likely to post the tap list as a photo or on
  Facebook only. Expect a higher skip rate than Seattle's.
- Target: surveyed and configured by July 2027, live before harvest.

## Phase 3: Bend and Central Oregon

Roughly 30 to 40 venues; includes Sisters, Redmond, and Sunriver.

- Candidates, unverified: Deschutes, Crux, Boneyard, Bend Brewing, Silver
  Moon, Sunriver, GoodLife, Monkless, Van Henion, Bevel, Spider City, Cascade
  Lakes, Terranaut, Three Creeks and Funky Fauna (Sisters), and Wild Ride
  (Redmond). Taprooms: The Growler Guys, On Tap, The Lot, Crosscut Warming
  Hut, and River's Place.
- Several are Oregon chains already surveyed for Portland (Deschutes, 10
  Barrel, Breakside if it has a Bend pub), so their parser configs carry over.
- Event sources: the Sisters Fresh Hop Festival and the Bend Ale Trail.
- Can run in parallel with phase 2; neither depends on the other.

## Open questions

- Whether the four sites should link to each other (a "Freshies in other
  cities" line in the footer). Cheap once `template_vars` exists.
- Whether cron for four sites stays hourly each. Four scrapes an hour of up to
  100 venues is fine for the droplet, but shared upstream hosts see four times
  the requests.
- The deploy branch is still `feature/fresh-hop-site`. More sites make merging
  to `main` more worthwhile, and phase 0 touches `main.py`, which the other
  maintainers share.

## Out of scope

- New parsers, until the surveys show a platform that needs one.
- OCR for image-only tap lists (deferred 2026-10-10).
- A combined all-regions site.
