# ADDING NEW SITES AND VENUES

## Generic vs Venue-Specific: Which Path?

Start with a generic parser. Fall back to a venue-specific parser only when one of these is true:

- **The source isn't HTTP + JSON/HTML/WordPress.** Google Sheets CSV, Squarespace embedded JSON blobs in HTML attributes, iCal feeds — none of these fit the generic parsers.
- **The site needs a custom fallback pipeline.** Urban Family has a WordPress Sugar Calendar as its primary source and the legacy Hivey API as a fallback, plus AI vision extraction for logos without a text title — too many branches for a config-driven parser.
- **The vendor name isn't present in the scraped data.** You need to extract it from a logo image via `VisionAnalyzer`, which means custom logic in `_extract_food_truck_name`.
- **The date/time format needs context-aware parsing.** Stoup's "Sat 07.05" requires year inference from the current Pacific date; the generic HTML parser's `date_format: auto` won't handle that cleanly.

If none of those apply, use a generic parser and set `source_type` accordingly.

**Real examples in this repo:**

| Venue-specific parser | Why |
|---|---|
| `stoup_ballard.py` | Context-aware Pacific year inference, multi-format fallback |
| `urban_family.py` | WordPress Sugar Calendar primary + Hivey API fallback + vision analysis |
| `bale_breaker.py` | Squarespace calendar API with quirks |
| `obec_brewing.py` | Custom regex for "Food truck: \<name\> \<time\>" prose |
| `wheelie_pop.py` | Simple text search with custom day-of-week handling |
| `chucks_greenwood.py` | Google Sheets CSV export (desktop tab; the mobile tab drops times) |
| `salehs_corner.py` | Seattle Food Truck API |
| `channel_marker.py` | Google Sheets CSV export, M/D/YY date format |
| `lucky_envelope.py` | Squarespace `data-current-context` embedded JSON |

Most *new* sites will use the generic parsers. For Ballard, all 9 venues happen to need custom logic — hence the 9 venue-specific parser files.

## Adding a New Venue to an Existing Site

If the venue's platform is already supported (WordPress, HTML with CSS selectors, AJAX/JSON API, or JSON-LD), just add a venue entry to the site's JSON config — **no parser code needed**.

### 1. Choose the Right `source_type`

| Platform | `source_type` | When to Use |
|----------|---------------|-------------|
| WordPress REST API | `"wordpress"` | Site has `/wp-json/wp/v2/posts` endpoint |
| HTML with structured markup | `"html"` | Events are in repeating HTML containers with consistent CSS selectors |
| JSON/AJAX API | `"ajax"` | Site exposes events via a JSON endpoint |

### 2. Add Venue to Site Config

Edit the appropriate file in `around_the_grounds/config/sites/`:

**WordPress example** (`source_type: "wordpress"`):
```json
{
  "key": "new-venue",
  "name": "New Venue Name",
  "url": "https://newvenue.com",
  "source_type": "wordpress",
  "parser_config": {
    "api_path": "/wp-json/wp/v2/posts",
    "category_id": "123,456",
    "per_page": 20
  }
}
```

**HTML selector example** (`source_type: "html"`):
```json
{
  "key": "new-venue",
  "name": "New Venue Name",
  "url": "https://newvenue.com/events",
  "source_type": "html",
  "parser_config": {
    "event_container": ".event-item",
    "title_selector": ".event-title",
    "date_selector": ".event-date",
    "time_selector": ".event-time",
    "description_selector": ".event-description",
    "date_format": "auto"
  }
}
```

When the date or hours share an element with other text (Beveridge Place's
"Saturday, Oct 17, 1-7pm THIRTY+ fresh hop beers…"), add `date_pattern` and/or
`time_pattern`: a regex whose first group (or whole match) is the part to
parse. Items with no date match are skipped. A time range borrows am/pm from
whichever end has it ("1-7pm" is 1–7 pm).

**AJAX/JSON API example** (`source_type: "ajax"`):
```json
{
  "key": "new-venue",
  "name": "New Venue Name",
  "url": "https://newvenue.com/events",
  "source_type": "ajax",
  "parser_config": {
    "api_url": "https://api.newvenue.com/v1/events",
    "method": "GET",
    "params": {"limit": 50},
    "response_path": "data.events",
    "field_map": {
      "title": "name",
      "date": "start_date",
      "start_time": "start_date",
      "end_time": "end_date",
      "description": "summary"
    }
  }
}
```

**AJAX with date placeholders** (replaced at runtime):
```json
{
  "params": {
    "query": "{\"startDate\":\"{{today_iso}}\",\"endDate\":\"{{end_date_iso}}\"}"
  }
}
```

### Tap-list ("listing") venues

Sites like `seattle-freshies` list what is available *now* (beers on tap)
rather than dated events. These parsers read a venue's live tap list, keep the
entries the fresh-hop matcher accepts, and emit `kind="listing"` events, which
skip the 7-day window and stay out of `events.ics`.

| Platform | `source_type` | Config |
|----------|---------------|--------|
| Untappd for Business website embed (`PreloadEmbedMenu(container, location, theme)`) | `"untappd-embed"` | `location_id`, `theme_id`; optional `menu_name` when one embed holds several taprooms' tabs (Postdoc) |
| Published menu on an `untappd.com/v/<slug>/<id>` venue page | `"untappd-venue"` | venue `url` is the page — untappd.com challenges datacenter IPs (Cloudflare), so prefer the venue's own site when the scraper runs on a server |
| Public Google Sheet tab (e.g. Chuck's Hop Shop) | `"sheet-taplist"` | `sheet_id`, `sheet_name`, `columns` (`name` required), optional `header_contains`, `brewery_separator`, `skip_prefix` |
| Craftpeak/Arryved "What's On Tap" module | `"craftpeak-wot"` | none (preset) |
| DigitalPour embedded menu (`fbpage.digitalpour.com/?companyID=…&locationID=…`) | `"digitalpour"` | `company_id`, `location_id` |
| Bevwerk website menu (`<bw-website-menu-root taplist-id="…">`, e.g. Watershed Pub) | `"bevwerk"` | `taplist_id`; venue `url` is the bar's menu page (not fetched) |
| Canva design embedded as a draft list (`canva.com/design/…/view?embed`, e.g. Old Stove) | `"canva"` | `design_url` (venue `url` is the page embedding it). Beers are found by layout around each "ABV" line. Sends a browser User-Agent: Canva refuses others |
| Repeated HTML items | `"html-taplist"` | `item`, `name`, optional `style`, `brewery`, `abv`, `style_pattern`, `name_pattern`, `match_whole_item`, `exclude_sections` |
| Shared Airtable interface page (`airtable.com/embed/app…/shr…`, e.g. Rooftop) | `"airtable"` | `share_url` (venue `url` is the page embedding it). The table's primary column is the beer name; `Style`, `ABV`, and `Description` columns are read when present — rename with optional `columns`. Uses the page's own data request, not Airtable's documented API, so it may need care when Airtable changes |
| PDF menu (e.g. El Sueñito) | `"pdf-taplist"` | `line_pattern` with a `(?P<name>…)` group, matched against each line of the PDF's text (optional `style`, `abv`, `brewery` groups; a following line that starts with a percentage supplies the ABV). Optional `link_pattern`: venue `url` is then a web page, and its first `.pdf` link whose text or `aria-label` matches is the menu — use it when the file name changes with every upload (Wix). Without it, venue `url` is the PDF |
| Free text, one beer per line | `"text-taplist"` | `line_pattern` with a `(?P<name>…)` group, optional `section_tag`, `include_sections`, `exclude_sections`, `line_tags` (elements that hold entries; default `p`, `li` — set `["h2"]` when beers are headings) |

Listings are sorted into **categories**: `fresh-hop` (fresh/wet hop),
`festbier` (Festbier, Oktoberfest/-toberfest, Märzen, Wiesn/Wies'n, plus harvest
lagers, Dunkels/Munich Dark, and Weizenbocks; not Dunkelweizen), and `pumpkin`
(pumpkin, gourd, jack-o'-lantern, calabaza).

A parser that supplies beer descriptions (`TapEntry.description`;
`untappd-embed` and `bevwerk`) lets a beer match by its description when its
name and style don't: fresh/wet hop for `fresh-hop` ("FRESH HOP Collab with
Uprise"), Festbier, Oktoberfest, Märzen, or Wiesn for `festbier` ("our
yearly golden Festbier"), and any `pumpkin` word ("brewed with roasted
pumpkin"). Harvest lager, Dunkel, and Weizenbock count only in the name or
style.

Festivals named on a tap-list page ("Fresh Hop Fest") are dropped from
`fresh-hop` by the beer's name only, so a beer "brewed for Fresh Hop Ale
Festival" or named "Fresh Hop Fest Bier" stays.

An entry matching several categories yields one listing per category, and each listing carries
`category` in `data.json`. Per venue:

| Option | Effect |
|--------|--------|
| `listing_include` / `listing_exclude` | Extra fresh-hop patterns (e.g. Bizarre's `"fresh hoppy"`) |
| `festbier_include` / `festbier_exclude` | Extra festbier patterns |
| `pumpkin_include` / `pumpkin_exclude` | Extra pumpkin patterns (e.g. Old Stove Pike Place's `"\\bvodka\\b"` drops a cocktail) |
| `listing_categories` | Limit the venue to some categories (default: all) |
| `venue_type` | Grouping for templates: `"taproom"` for bottle shops/taprooms (default: brewery) |
| `timezone` | Site-local "today" for listing dates |

A site with listing venues also gets `listing_venues` (key, name, url) in
`data.json`; the `fresh-hop` template uses it to name places that were
checked but have nothing matching. Other sites' `data.json` is unchanged.

- Point at the venue's **current** tap list, not a beer catalog or a packaged
  "available beer" page — and check a multi-location brewery's page is for the
  right taproom (Bale Breaker's Yakima menu is not its Seattle one).
- **Use a venue key no venue-specific parser owns** (the registry matches
  `venue.key` first): `stoup-ballard-taps`, not `stoup-ballard`.
- Requests to a shared host are spaced 5s apart; Cloudflare challenges are
  reported by name.

### Filtering and looking further ahead (any event source)

These `parser_config` options work with every event parser (`html`,
`json-ld`, `wordpress`, `ajax`, `squarespace-events`, …):

| Option | Effect |
|--------|--------|
| `"event_filter": true` | Keep only events whose title/description match the fresh-hop matcher (festivals are kept; `listing_include` / `listing_exclude` apply) |
| `"event_window_days": 60` | Keep events up to this many days ahead instead of the default 7 (fests are announced weeks out) |
| `"timezone": "America/Los_Angeles"` | `html` parser only: convert timezone-aware dates (e.g. ISO `...Z` attributes) to local time so evening events keep their day |

`squarespace-events` reads a Squarespace events collection page as JSON
(`?format=json`); the venue `url` is the collection page. For an aggregated
list whose items happen elsewhere, put the host venue in the description
(the `fresh-hop` template shows it with "via <source>"), and use a CSS
attribute selector to keep only local items, e.g.
`article.article-event-item[data-tags*="Seattle"]`.

### 3. Test

```bash
# Run the site to verify events are fetched
uv run around-the-grounds --site <site-key> --verbose

# Preview locally
uv run around-the-grounds --site <site-key> --preview
cd public && python -m http.server 8000
```

## Adding a New Site

### 1. Create Site Config

Create a new JSON file in `around_the_grounds/config/sites/<site-key>.json`:

```json
{
  "key": "my-new-site",
  "name": "My New Event Site",
  "template": "music",
  "timezone": "America/New_York",
  "target_repo": "https://github.com/username/atg-my-new-site.git",
  "deploy_subdir": "",
  "generate_description": false,
  "venues": [
    {
      "key": "venue-one",
      "name": "Venue One",
      "url": "https://venueone.com/events",
      "source_type": "html",
      "parser_config": { ... }
    }
  ]
}
```

### Deploy strategy (`deploy_subdir`)

- **`""` (or omit the field) — root mode.** The system will `git init` a fresh local repo, write your template to the repo root, and **force-push** to the target's `main`. Use this when the target repo is dedicated to the generated output and served by GitHub Pages from the repo root. This is what `park-slope-music` and `childrens-events` use.
- **`"public"` (or any non-empty value) — subdir mode.** The system will `git clone` the target repo, write your template into that subdirectory, scoped-stage only that subdirectory, and **normal-push**. Use this when the target repo has files at the root that must be preserved — for example, a Vercel project that reads its build output from `public/` while keeping `vercel.json` and `README.md` at the root. This is what `ballard-food-trucks` uses.

**Pick based on what your target host expects**, not by preference. Root mode is simpler but destructive (history is rewritten every deploy); subdir mode is safer but requires the target repo to exist and be clonable.

### 2. Choose or Create a Template

Available templates in `public_templates/`:
- `food-trucks` — dark theme, food truck oriented
- `music` — dark theme, music/show oriented
- `kids` — bright/playful theme, children's event oriented
- `fresh-hop` — tap-list ("listing") sites: five pages sharing `app.js`/`styles.css` under a pinned tab bar — fresh hops at breweries (`index.html`), festbiers at breweries (`festbier.html`), pumpkin beers at breweries (`pumpkin.html`), all three at bottle shops and taprooms (`taprooms.html`, the "Taprooms" tab, venues with `venue_type: "taproom"`), and dated events (`events.html`)

To create a new template, add a directory under `public_templates/` with at least an `index.html`.

### 3. Set Up Target Repository

1. Create the GitHub repo (e.g., `atg-my-new-site`)
2. Configure your target host:
   - **Root mode + GitHub Pages**: Settings → Pages → Deploy from `main` branch root
   - **Subdir mode + Vercel**: Create a Vercel project watching the repo, set the "Output Directory" to match your `deploy_subdir` value (e.g. `public`)
3. Install your GitHub App on the repo (it needs Contents: Read & Write)

A site with no `target_repo` is **preview-only**: `--deploy` skips it (with a
message) instead of falling back to `GIT_REPOSITORY_URL` or the default repo,
unless you pass `--git-repo` explicitly.

### 4. Test and Deploy

```bash
uv run around-the-grounds --site my-new-site --preview   # Local preview
uv run around-the-grounds --site my-new-site --deploy     # Deploy to GitHub Pages
```

## Adding a Venue-Specific Parser (Unsupported Platform)

If the venue uses a platform not covered by the generic parsers:

### 1. Create Parser Class

```python
from .base import BaseParser
from ..models import Event
from typing import List
import aiohttp

class NewVenueParser(BaseParser):
    async def parse(self, session: aiohttp.ClientSession) -> List[Event]:
        try:
            soup = await self.fetch_page(session, self.venue.url)
            events = []

            # Extract events from HTML with error handling
            # Use self.logger for debugging
            # Use self.validate_event() for data validation

            valid_events = self.filter_valid_events(events)
            self.logger.info(f"Parsed {len(valid_events)} valid events")
            return valid_events

        except Exception as e:
            self.logger.error(f"Error parsing {self.venue.name}: {str(e)}")
            raise ValueError(f"Failed to parse venue website: {str(e)}")
```

### 2. Register Parser

In `parsers/registry.py`, add to the `_specific` dict:

```python
from .new_venue import NewVenueParser

class ParserRegistry:
    _specific: Dict[str, Type[BaseParser]] = {
        'new-venue-key': NewVenueParser,
        # ... existing parsers
    }
```

Venue-specific parsers take precedence over generic parsers. The registry looks up by `venue.key` first, then falls back to `venue.source_type`.

### 3. Add Venue to Site Config

Add the venue to the appropriate `config/sites/<key>.json`. The `source_type` doesn't matter for venue-specific parsers since the registry matches by key.

### 4. Write Tests

Create `tests/parsers/test_new_venue.py`:
- Test successful parsing with mock HTML
- Test error scenarios (network, parsing, validation)
- Test with real HTML fixtures if available
- Mock vision analysis if your parser uses it
