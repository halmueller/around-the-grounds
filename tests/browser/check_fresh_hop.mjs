// Offline browser checks for one Freshies site as published (the fresh-hop
// template with placeholders filled). Serves the rendered folder with a
// hostile data.json and asserts, in a real Chromium, that:
//   - every page loads without script errors, and scraped strings (beer,
//     venue, event, skipped, and failed names) render as text, never markup;
//     non-http links from data.json never become hrefs
//   - the tab bar lists the expected pages, marks only the current one, and
//     leads each list tab with its count
//   - search filters the list and echoes the query as text
//   - Google's preferred-source badge links to this site's domain, loads, and
//     follows the light/dark color scheme
//   - phones (390, 360, 320px) never scroll sideways, and the tab bar fits
//   - on phones only the tab bar stays pinned, and the credit bar is not;
//     desktops keep the whole header and the credit bar pinned
// Usage: node check_fresh_hop.mjs <rendered dir> <expectations JSON>
// where the JSON is {"domain": ..., "site_name": ..., "pages": [...]}.
// Invoked by tests/integration/test_templates_browser.py.
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const { chromium } = require('playwright');

const [ROOT, EXPECT_JSON] = process.argv.slice(2);
const EXPECT = JSON.parse(EXPECT_JSON);
const PAYLOAD = `O'Brien & "quoted" <img src=x onerror="window.injected=true">`;
const PLAIN = `Bob's "Hazy" & Fresh`;
const DATA_PAGES = {
  'fresh-hops.html': 'freshhop',
  'festbier.html': 'festbier',
  'pumpkin.html': 'pumpkin',
  'winter-beers.html': 'winter',
  'taprooms.html': 'taprooms',
  'events.html': 'events',
};
const TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript',
  '.css': 'text/css',
  '.png': 'image/png',
  '.svg': 'image/svg+xml',
  '.ico': 'image/x-icon',
  '.xml': 'application/xml',
  '.txt': 'text/plain',
};

function assert(cond, msg) {
  if (!cond) throw new Error(`ASSERTION FAILED: ${msg}`);
}

const listing = (over) => ({
  kind: 'listing',
  date: '2026-11-22T00:00:00',
  venue_key: 'brewery-a',
  venue: PAYLOAD,
  venue_url: 'https://example.com/taps',
  title: PAYLOAD,
  description: PAYLOAD,
  category: 'fresh-hop',
  ...over,
});

// Collected in November, so the winter list is in season.
const DATA = {
  site_name: EXPECT.site_name,
  timezone: 'America/Los_Angeles',
  timezone_label: 'PT',
  updated: '2026-11-22T20:00:00+00:00',
  listing_venues: [
    { key: 'brewery-a', name: PAYLOAD, url: 'https://example.com/taps' },
    { key: 'brewery-b', name: PLAIN, url: 'javascript:window.injected=true' },
    { key: 'brewery-quiet', name: PAYLOAD, url: 'https://example.com/quiet' },
    { key: 'shop', name: 'Corner Bottle Shop', url: 'https://example.com/shop', type: 'taproom' },
  ],
  events: [
    listing({}),
    listing({ category: 'festbier', title: 'Festbier' }),
    listing({ category: 'pumpkin', title: 'Pumpkin Ale' }),
    listing({ category: 'winter', title: PLAIN, description: '7.2%' }),
    listing({
      category: 'winter', venue_key: 'brewery-b', venue: PLAIN,
      venue_url: 'javascript:window.injected=true', title: 'Winter Warmer',
    }),
    listing({
      category: 'winter', venue_key: 'shop', venue: 'Corner Bottle Shop',
      venue_url: 'https://example.com/shop', title: 'Holiday Ale',
    }),
    {
      date: '2026-11-28T00:00:00', title: PAYLOAD, venue: PAYLOAD,
      place: PAYLOAD, description: PAYLOAD, url: 'javascript:window.injected=true',
      venue_url: 'https://example.com/events', start_time_raw: '5:00 PM',
      category: 'winter',
    },
  ],
  skipped_venues: [{ name: PAYLOAD, url: 'javascript:window.injected=true' }],
  failed_venues: [{ key: 'brewery-quiet-failed', name: PAYLOAD }],
};
// The failed venue is a listing venue too, so its error shows on list pages.
DATA.listing_venues.push({ key: 'brewery-quiet-failed', name: PAYLOAD, url: '' });

// Expected tab counts: beers per brewery list, places on the taprooms list.
const TAB_COUNTS = {
  'fresh-hops.html': 1, 'festbier.html': 1, 'pumpkin.html': 1,
  'winter-beers.html': 2, 'taprooms.html': 1,
};

function serve() {
  const server = http.createServer((req, res) => {
    const url = decodeURIComponent(req.url.split('?')[0]);
    if (url === '/data.json') {
      res.writeHead(200, { 'content-type': 'application/json' });
      res.end(JSON.stringify(DATA));
      return;
    }
    const file = path.join(ROOT, url === '/' ? 'index.html' : url);
    if (!file.startsWith(ROOT) || !fs.existsSync(file) || !fs.statSync(file).isFile()) {
      // analytics-config.js lives only on the server; 404 like a fresh host.
      res.writeHead(404);
      res.end();
      return;
    }
    res.writeHead(200, { 'content-type': TYPES[path.extname(file)] || 'application/octet-stream' });
    res.end(fs.readFileSync(file));
  });
  return new Promise((resolve) => server.listen(0, '127.0.0.1', () => resolve(server)));
}

async function withPage(browser, server, page, options, fn) {
  const context = await browser.newContext({ timezoneId: 'America/Los_Angeles', ...options });
  const tab = await context.newPage();
  const errors = [];
  tab.on('pageerror', (e) => errors.push(String(e)));
  // Fully offline: Google, TelemetryDeck, and anything else external are
  // aborted so the check never waits on the network.
  await tab.route('**/*', (route) => {
    const url = new URL(route.request().url());
    return url.hostname === '127.0.0.1' ? route.continue() : route.abort();
  });
  await tab.goto(`http://127.0.0.1:${server.address().port}/${page}`);
  try {
    await fn(tab);
    assert(errors.length === 0, `[${page}] page errors: ${errors.join('; ')}`);
  } finally {
    await context.close();
  }
}

async function assertNoInjection(tab, where) {
  assert((await tab.evaluate(() => window.injected)) === undefined, `[${where}] injected script ran`);
  assert((await tab.locator('img[src="x"]').count()) === 0, `[${where}] injected <img> was created`);
  const bad = await tab.locator('a[href^="javascript:"]').count();
  assert(bad === 0, `[${where}] ${bad} javascript: link(s) rendered`);
}

async function waitForRender(tab) {
  // app.js replaces "Loading…" once data.json is in.
  await tab.waitForFunction(() => !document.querySelector('#listings .empty')
    || document.querySelector('#listings .empty').textContent !== 'Loading…');
}

async function checkPage(browser, server, page) {
  await withPage(browser, server, page, {}, async (tab) => {
    await waitForRender(tab);
    assert(
      await tab.evaluate(() => document.body.dataset.page) === DATA_PAGES[page],
      `[${page}] wrong data-page`,
    );
    await assertNoInjection(tab, page);
    const listings = await tab.locator('#listings').innerText();
    assert(!listings.includes('Could not load'), `[${page}] data.json did not load`);

    // Tabs: the expected pages in order, only this one current.
    const tabs = tab.locator('nav.tabs a');
    const hrefs = await tabs.evaluateAll((as) => as.map((a) => a.getAttribute('href')));
    assert(JSON.stringify(hrefs) === JSON.stringify(EXPECT.pages), `[${page}] tabs ${JSON.stringify(hrefs)}`);
    const current = await tab.locator('nav.tabs a[aria-current="page"]')
      .evaluateAll((as) => as.map((a) => a.getAttribute('href')));
    assert(JSON.stringify(current) === JSON.stringify([page]), `[${page}] current tab ${JSON.stringify(current)}`);
    for (const [href, n] of Object.entries(TAB_COUNTS)) {
      const text = await tab.locator(`nav.tabs a[href="${href}"] .tab-count`).innerText();
      assert(text === String(n), `[${page}] ${href} tab count ${text}, want ${n}`);
    }
    assert((await tab.locator('nav.tabs a[href="events.html"] .tab-count').count()) === 0,
      `[${page}] events tab has a count`);

    // Preferred-source badge, just above the tabs.
    const link = tab.locator('.preferred-source a');
    assert((await link.count()) === 1, `[${page}] preferred-source link missing`);
    assert(
      await link.getAttribute('href') === `https://www.google.com/preferences/source?q=${EXPECT.domain}`,
      `[${page}] preferred-source href ${await link.getAttribute('href')}`,
    );
    assert(
      await tab.evaluate(() => document.querySelector('.preferred-source').nextElementSibling
        === document.querySelector('nav.tabs')),
      `[${page}] badge is not just above the tabs`,
    );

    if (page === 'events.html') {
      assert(listings.includes(PAYLOAD), `[${page}] hostile event not rendered as text`);
      const title = tab.locator('.event .beer-name a');
      assert(await title.getAttribute('href') === 'https://example.com/events',
        `[${page}] javascript: event url not replaced by the venue url`);
      return;
    }

    // Hostile strings show as text in the list and the notices.
    if (page === 'fresh-hops.html') {
      assert(listings.includes(PAYLOAD), `[${page}] hostile beer/venue not rendered as text`);
    }
    if (page === 'winter-beers.html') {
      assert(listings.includes(PLAIN) && listings.includes('Winter Warmer'), `[${page}] beers missing`);
      // brewery-b's javascript: url gets no "Tap list" link.
      const venueLinks = await tab.locator('.venue-link').count();
      assert(venueLinks === 1, `[${page}] ${venueLinks} venue links, want 1`);
      assert(!listings.includes('Holiday Ale'), `[${page}] taproom beer on a brewery list`);
    }
    if (page === 'taprooms.html') {
      assert(listings.includes('Holiday Ale'), `[${page}] taproom beer missing`);
      assert(!listings.includes('Winter Warmer'), `[${page}] brewery beer on the taprooms list`);
      return;
    }
    const quiet = await tab.locator('#quiet').innerText();
    assert(quiet.includes(PAYLOAD), `[${page}] quiet notice not text: ${quiet}`);
    const skipped = await tab.locator('#skipped').innerText();
    assert(skipped.includes(PAYLOAD), `[${page}] skipped notice not text: ${skipped}`);
    const errors = await tab.locator('#errors').innerText();
    assert(errors.includes(PAYLOAD), `[${page}] errors notice not text: ${errors}`);

    // Search: filters and echoes the query as text.
    if (page === 'winter-beers.html') {
      const search = tab.locator('#search');
      assert(await search.isVisible(), `[${page}] search hidden`);
      await search.fill('warmer');
      const visible = await tab.locator('.beer:not([hidden])').allInnerTexts();
      assert(visible.length === 1 && visible[0].includes('Winter Warmer'), `[${page}] search kept ${JSON.stringify(visible)}`);
      await search.fill('<img src=x onerror="window.injected=true">');
      await assertNoInjection(tab, `${page} search`);
      const summary = await tab.locator('#summary').innerText();
      assert(summary.includes('<img src=x'), `[${page}] search echo not text: ${summary}`);
      await search.fill('');
      assert((await tab.locator('.beer:not([hidden])').count()) === 2, `[${page}] search did not clear`);
    }
    await assertNoInjection(tab, page);
  });
}

async function checkBadgeScheme(browser, server, colorScheme) {
  await withPage(browser, server, 'winter-beers.html', { colorScheme }, async (tab) => {
    const img = tab.locator('.preferred-source img');
    await img.evaluate((el) => el.decode());
    const { src, width } = await img.evaluate((el) => ({ src: el.currentSrc, width: el.naturalWidth }));
    assert(src.endsWith(`/preferred-source-${colorScheme}.png`), `[${colorScheme}] badge is ${src}`);
    assert(width === 338, `[${colorScheme}] badge did not load (naturalWidth ${width})`);
    assert(await img.isVisible(), `[${colorScheme}] badge not visible`);
  });
}

async function checkPhone(browser, server, width) {
  for (const page of EXPECT.pages) {
    await withPage(browser, server, page, { viewport: { width, height: 800 } }, async (tab) => {
      await waitForRender(tab);
      const { scroll, client, wide } = await tab.evaluate(() => {
        const client = document.documentElement.clientWidth;
        // The widest elements past the right edge, outside the tab bar
        // (which scrolls on its own), to name in a failure.
        const wide = [...document.querySelectorAll('body *')]
          .filter((el) => !el.closest('nav.tabs') && el.getBoundingClientRect().right > client + 0.5)
          .slice(-3)
          .map((el) => `${el.tagName.toLowerCase()}.${el.className}: ${el.textContent.trim().slice(0, 50)}`);
        return { scroll: document.documentElement.scrollWidth, client, wide };
      });
      assert(scroll <= client,
        `[${page} @${width}px] page scrolls sideways (${scroll} > ${client}): ${JSON.stringify(wide)}`);
      const tabs = await tab.locator('nav.tabs').evaluate((el) => ({ scroll: el.scrollWidth, client: el.clientWidth }));
      assert(tabs.scroll <= tabs.client, `[${page} @${width}px] tabs overflow (${tabs.scroll} > ${tabs.client})`);
    });
  }
}

// After scrolling, phones keep only the tab bar on screen; desktops keep
// the whole header and the credit bar.
async function checkPinning(browser, server, width, phone) {
  for (const page of EXPECT.pages) {
    await withPage(browser, server, page, { viewport: { width, height: 800 } }, async (tab) => {
      await waitForRender(tab);
      await tab.evaluate(() => {
        document.getElementById('listings').style.minHeight = '4000px';
        window.scrollTo(0, 1500);
      });
      // Let the ResizeObserver and the scroll settle.
      await tab.waitForTimeout(100);
      const got = await tab.evaluate(() => ({
        tabs: document.querySelector('nav.tabs').getBoundingClientRect().top,
        title: document.querySelector('.topbar h1').getBoundingClientRect().bottom,
        credit: getComputedStyle(document.querySelector('.creditbar')).position,
      }));
      const where = `[${page} @${width}px]`;
      if (phone) {
        assert(got.tabs >= -1 && got.tabs <= 1, `${where} tabs not pinned at the top (${got.tabs})`);
        assert(got.title <= 0, `${where} title still on screen (${got.title})`);
        assert(got.credit === 'static', `${where} credit bar is ${got.credit}`);
      } else {
        assert(got.title > 0, `${where} header scrolled away on a desktop (${got.title})`);
        assert(got.credit === 'sticky', `${where} credit bar is ${got.credit}`);
      }
    });
  }
}

async function checkHome(browser, server) {
  // index.html is the redirect for hosts without the Apache rule.
  await withPage(browser, server, '', {}, async (tab) => {
    await tab.waitForURL(/\.html$/);
    const page = new URL(tab.url()).pathname.slice(1);
    assert(EXPECT.pages.includes(page) && page !== 'events.html', `home went to ${page}`);
  });
}

const server = await serve();
const browser = await chromium.launch();
try {
  for (const page of EXPECT.pages) await checkPage(browser, server, page);
  await checkBadgeScheme(browser, server, 'light');
  await checkBadgeScheme(browser, server, 'dark');
  for (const width of [390, 360, 320]) await checkPhone(browser, server, width);
  await checkPinning(browser, server, 390, true);
  await checkPinning(browser, server, 1000, false);
  await checkHome(browser, server);
  console.log('fresh-hop: ok');
} finally {
  await browser.close();
  server.close();
}
