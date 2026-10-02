// Seattle Freshies: renders one page, chosen by <body data-page>, from the
// shared data.json:
//   freshhop  fresh-hop beers at breweries
//   festbier  festbiers, Oktoberfests, and Märzens at breweries
//   pumpkin   pumpkin beers at breweries
//   taprooms  all three, at bottle shops and taprooms
//   events    upcoming beer events

// Escape text for safe insertion into innerHTML (text nodes and
// double-quoted attribute values). Scraped strings are data, not markup.
function esc(value) {
    return String(value ?? '').replace(/[&<>"']/g, ch => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    })[ch]);
}

// Only http(s) links from data.json become hrefs.
function safeUrl(url) {
    return /^https?:\/\//i.test(url || '') ? url : '';
}

function formatDate(dateKey) {
    return new Date(dateKey + 'T12:00:00Z').toLocaleDateString('en-US', {
        weekday: 'short', month: 'short', day: 'numeric', timeZone: 'UTC'
    });
}

function count(n, one, many) { return `${n} ${n === 1 ? one : many}`; }

const BREWERIES = n => count(n, 'brewery', 'breweries');
const CATEGORY_LABELS = { 'fresh-hop': 'Fresh hop', festbier: 'Festbier', pumpkin: 'Pumpkin' };
// A seasonal list has `months`, its season as [first, last] month numbers
// (inclusive; may wrap the new year), and `offSeason`, shown instead of
// "Found no …" when the list is empty outside those months. Each page's
// tagline spells the season out; keep the two in step.
const PAGES = {
    freshhop: {
        href: 'fresh-hops.html',
        label: 'Fresh hops',
        venueType: type => type !== 'taproom',
        categories: ['fresh-hop'],
        places: BREWERIES,
        beers: n => count(n, 'fresh-hop beer', 'fresh-hop beers'),
        none: 'no fresh hops',
        months: [8, 10],
        offSeason: 'Fresh hops are out of season.',
    },
    festbier: {
        href: 'festbier.html',
        label: 'Festbiers',
        venueType: type => type !== 'taproom',
        categories: ['festbier'],
        places: BREWERIES,
        beers: n => count(n, 'festbier or Oktoberfest beer', 'festbiers and Oktoberfest beers'),
        none: 'no festbiers',
        months: [9, 10],
        offSeason: 'Festbiers are out of season.',
    },
    pumpkin: {
        href: 'pumpkin.html',
        label: 'Pumpkin',
        venueType: type => type !== 'taproom',
        categories: ['pumpkin'],
        places: BREWERIES,
        beers: n => count(n, 'pumpkin beer', 'pumpkin beers'),
        none: 'no pumpkin beers',
        months: [9, 11],
        offSeason: 'Pumpkin beers are out of season.',
    },
    taprooms: {
        href: 'taprooms.html',
        label: 'Taprooms',
        venueType: type => type === 'taproom',
        categories: ['fresh-hop', 'festbier', 'pumpkin'],
        places: n => count(n, 'bottle shop or taproom', 'bottle shops and taprooms'),
        beers: n => count(n, 'fresh-hop, festbier, or pumpkin beer', 'fresh-hop, festbier, and pumpkin beers'),
        none: 'no fresh hops, festbiers, or pumpkin beers',
        tags: true,
    },
    events: { events: true },
};
const PAGE = PAGES[document.body.dataset.page] || PAGES.freshhop;

function renderVenue(venue) {
    const link = safeUrl(venue.url)
        ? `<a class="venue-link" href="${esc(venue.url)}" target="_blank" rel="noopener">Tap list ↗</a>`
        : '';
    const items = venue.beers.map(b => {
        const tag = PAGE.tags && CATEGORY_LABELS[b.category]
            ? ` <span class="tag tag-${esc(b.category)}">${esc(CATEGORY_LABELS[b.category])}</span>`
            : '';
        return `<div class="beer">
            <div class="beer-name">${esc(b.title)}${tag}</div>
            ${b.description ? `<div class="beer-meta">${esc(b.description)}</div>` : ''}
        </div>`;
    }).join('');
    return `<section class="venue" data-search="${esc(venue.search)}">
        <div class="venue-head">
            <div class="venue-name">${esc(venue.name)}<span class="venue-count">${venue.beers.length}</span></div>
            ${link}
        </div>
        ${items}
    </section>`;
}

function renderEvent(e) {
    const time = e.start_time_raw
        ? (e.end_time_raw ? `${e.start_time_raw} – ${e.end_time_raw}` : e.start_time_raw)
        : '';
    // Aggregated lists name the host venue in `place`; the source venue is
    // then shown as "via".
    const details = [e.place, e.description].filter(Boolean).map(esc).join(' · ');
    const where = details ? `${details} · via ${esc(e.venue)}` : esc(e.venue);
    // The event's own page when the source links one, else the source itself.
    const link = safeUrl(e.url) || safeUrl(e.venue_url);
    const title = link
        ? `<a href="${esc(link)}" target="_blank" rel="noopener">${esc(e.title)}</a>`
        : esc(e.title);
    const tag = CATEGORY_LABELS[e.category]
        ? ` <span class="tag tag-${esc(e.category)}">${esc(CATEGORY_LABELS[e.category])}</span>`
        : '';
    return `<div class="event">
        <div class="event-date">${esc(formatDate(e.date.split('T')[0]))}${time ? ' · ' + esc(time) : ''}</div>
        <div class="beer-name">${title}${tag}</div>
        <div class="beer-meta">${where}</div>
    </div>`;
}

function setupSearch(listingsEl, summaryEl, summary) {
    const search = document.getElementById('search');
    search.hidden = false;
    search.addEventListener('input', () => {
        const q = search.value.trim().toLowerCase();
        let shown = 0;
        listingsEl.querySelectorAll('.venue').forEach(section => {
            const venueName = section.querySelector('.venue-name').textContent.toLowerCase();
            let visibleBeers = 0;
            section.querySelectorAll('.beer').forEach(beer => {
                const hit = !q || beer.textContent.toLowerCase().includes(q) || venueName.includes(q);
                beer.hidden = !hit;
                if (hit) visibleBeers++;
            });
            section.hidden = !(section.dataset.search.includes(q) && visibleBeers);
            if (!section.hidden) shown++;
        });
        summaryEl.innerHTML = q ? `${esc(PAGE.places(shown))} match “${esc(q)}”.` : summary;
    });
}

function showNotice(id, html) {
    const el = document.getElementById(id);
    el.hidden = false;
    el.innerHTML = html;
}

function renderEventsPage(data, listingsEl, summaryEl) {
    const events = (data.events || []).filter(e => e.kind !== 'listing');
    if (!events.length) {
        listingsEl.innerHTML = '<div class="empty">No upcoming beer events found.</div>';
        return;
    }
    summaryEl.innerHTML = `<strong>${esc(count(events.length, 'upcoming beer event', 'upcoming beer events'))}</strong> in and around Seattle.`;
    listingsEl.innerHTML = `<section class="venue">${events.map(renderEvent).join('')}</section>
        <p class="notice"><a class="calendar-link" href="events.ics">Subscribe to these events in your calendar</a></p>`;
}

// The listings that belong on a list page.
function pageListings(page, data, venueInfo) {
    return (data.events || []).filter(e => e.kind === 'listing'
        && page.venueType((venueInfo.get(e.venue_key) || {}).type || 'brewery')
        && page.categories.includes(e.category || 'fresh-hop'));
}

// Whether the data was gathered outside a seasonal page's months (site time).
function outOfSeason(page, data) {
    if (!page.months) return false;
    const month = Number(new Date(data.updated || Date.now()).toLocaleString('en-US', {
        month: 'numeric', timeZone: data.timezone || 'America/Los_Angeles'
    }));
    const [first, last] = page.months;
    return first <= last ? month < first || month > last : month < first && month > last;
}

// Shown in place of an empty out-of-season list: what is pouring instead.
function renderOffSeason(data, venueInfo) {
    const others = Object.values(PAGES)
        .filter(p => p !== PAGE && p.categories)
        .map(p => ({ page: p, n: pageListings(p, data, venueInfo).length }))
        .filter(o => o.n)
        .map(o => `<a href="${esc(o.page.href)}">${esc(o.page.label)}</a> (${o.n})`);
    return `<div class="empty">${esc(PAGE.offSeason)}`
        + (others.length ? `<br>Pouring now: ${others.join(', ')}.` : '') + '</div>';
}

function renderListingsPage(data, venueInfo, listingsEl, summaryEl) {
    const onThisPage = key => PAGE.venueType((venueInfo.get(key) || {}).type || 'brewery');
    const pageVenues = [...venueInfo.values()].filter(v => onThisPage(v.key));
    const listings = pageListings(PAGE, data, venueInfo);

    // Group listings by venue, keeping the config order the data arrives in.
    const venues = new Map();
    listings.forEach(e => {
        if (!venues.has(e.venue_key)) {
            venues.set(e.venue_key, { name: e.venue, url: e.venue_url, beers: [] });
        }
        venues.get(e.venue_key).beers.push(e);
    });
    // Within a venue, beers go alphabetically (case-insensitive, "2" before "10").
    const byTitle = new Intl.Collator('en', { sensitivity: 'base', numeric: true });
    venues.forEach(v => {
        v.beers.sort((a, b) => byTitle.compare(a.title, b.title));
        v.search =[v.name, ...v.beers.map(b => `${b.title} ${b.description || ''}`)]
            .join(' ').toLowerCase();
    });

    const offSeason = !venues.size && outOfSeason(PAGE, data);
    if (offSeason) {
        listingsEl.innerHTML = renderOffSeason(data, venueInfo);
    } else if (!venues.size) {
        listingsEl.innerHTML = `<div class="empty">Found ${esc(PAGE.none)} on tap right now.</div>`;
    } else {
        const summary = `<strong>${esc(PAGE.beers(listings.length))}</strong> pouring at ${esc(PAGE.places(venues.size))}.`;
        summaryEl.innerHTML = summary;
        listingsEl.innerHTML = [...venues.values()].map(renderVenue).join('');
        setupSearch(listingsEl, summaryEl, summary);
    }

    // Places checked that have nothing on right now (failed ones are named in
    // the errors line instead). Out of season that is every place, so skip it.
    const failed = new Set((data.failed_venues || []).map(v => v.key));
    const quiet = pageVenues.filter(v => !venues.has(v.key) && !failed.has(v.key));
    if (quiet.length && !offSeason) {
        showNotice('quiet', `Checked, ${esc(PAGE.none)} on right now: ` + quiet.map(v =>
            safeUrl(v.url)
                ? `<a href="${esc(v.url)}" target="_blank" rel="noopener">${esc(v.name)}</a>`
                : esc(v.name)
        ).join(', ') + '.');
    }
    return pageVenues;
}

fetch('data.json')
    .then(r => r.json())
    .then(data => {
        if (data.updated) {
            document.getElementById('updated').textContent =
                'Checked ' + new Date(data.updated).toLocaleString('en-US', {
                    dateStyle: 'medium', timeStyle: 'short', timeZone: data.timezone || 'America/Los_Angeles'
                }) + ' (' + (data.timezone_label || 'PT') + ').';
        }

        const venueInfo = new Map((data.listing_venues || []).map(v => [v.key, v]));
        const listingsEl = document.getElementById('listings');
        const summaryEl = document.getElementById('summary');
        const pageVenues = PAGE.events
            ? (renderEventsPage(data, listingsEl, summaryEl), [])
            : renderListingsPage(data, venueInfo, listingsEl, summaryEl);

        // Show failures for this page's tap-list venues; event sources'
        // failures go on the events page. Matched by key: a brewery's tap
        // list and its events source can share a name.
        const onPage = new Set(pageVenues.map(v => v.key));
        const pageErrors = (data.failed_venues || []).filter(v => PAGE.events
            ? !venueInfo.has(v.key)
            : onPage.has(v.key));
        if (pageErrors.length) {
            const el = document.getElementById('errors');
            el.hidden = false;
            el.textContent = 'Couldn’t check some lists this time: '
                + pageErrors.map(v => v.name).join(', ') + '.';
        }
    })
    .catch(() => {
        document.getElementById('listings').innerHTML =
            '<div class="empty">Could not load the lists.</div>';
    });
