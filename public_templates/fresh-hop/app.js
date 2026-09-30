// Seattle Freshies: renders one page, chosen by <body data-page>, from the
// shared data.json:
//   freshhop  fresh-hop beers at breweries
//   festbier  festbiers, Oktoberfests and Märzens at breweries
//   bars      both, at bottle shops and bars
//   events    upcoming fresh-hop events

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
const CATEGORY_LABELS = { 'fresh-hop': 'Fresh hop', festbier: 'Festbier' };
const PAGES = {
    freshhop: {
        venueType: type => type !== 'bar',
        categories: ['fresh-hop'],
        places: BREWERIES,
        beers: n => count(n, 'fresh-hop beer', 'fresh-hop beers'),
        none: 'no fresh hops',
    },
    festbier: {
        venueType: type => type !== 'bar',
        categories: ['festbier'],
        places: BREWERIES,
        beers: n => count(n, 'festbier or Oktoberfest beer', 'festbiers and Oktoberfest beers'),
        none: 'no festbiers',
    },
    bars: {
        venueType: type => type === 'bar',
        categories: ['fresh-hop', 'festbier'],
        places: n => count(n, 'bottle shop or bar', 'bottle shops and bars'),
        beers: n => count(n, 'fresh-hop beer or festbier', 'fresh-hop beers and festbiers'),
        none: 'no fresh hops or festbiers',
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
    // Aggregated lists put the host venue in the description; the source
    // venue is then shown as "via".
    const where = e.description ? `${esc(e.description)} · via ${esc(e.venue)}` : esc(e.venue);
    const title = safeUrl(e.venue_url)
        ? `<a href="${esc(e.venue_url)}" target="_blank" rel="noopener">${esc(e.title)}</a>`
        : esc(e.title);
    return `<div class="event">
        <div class="event-date">${esc(formatDate(e.date.split('T')[0]))}${time ? ' · ' + esc(time) : ''}</div>
        <div class="beer-name">${title}</div>
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
        listingsEl.innerHTML = '<div class="empty">No upcoming fresh-hop events found.</div>';
        return;
    }
    summaryEl.innerHTML = `<strong>${esc(count(events.length, 'upcoming fresh-hop event', 'upcoming fresh-hop events'))}</strong> in and around Seattle.`;
    listingsEl.innerHTML = `<section class="venue">${events.map(renderEvent).join('')}</section>
        <p class="notice"><a class="calendar-link" href="events.ics">Subscribe to these events in your calendar</a></p>`;
}

function renderListingsPage(data, venueInfo, listingsEl, summaryEl) {
    const onThisPage = key => PAGE.venueType((venueInfo.get(key) || {}).type || 'brewery');
    const pageVenues = [...venueInfo.values()].filter(v => onThisPage(v.key));
    const listings = (data.events || []).filter(e => e.kind === 'listing'
        && onThisPage(e.venue_key) && PAGE.categories.includes(e.category || 'fresh-hop'));

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

    if (!venues.size) {
        listingsEl.innerHTML = `<div class="empty">Found ${esc(PAGE.none)} on tap right now.</div>`;
    } else {
        const summary = `<strong>${esc(PAGE.beers(listings.length))}</strong> pouring at ${esc(PAGE.places(venues.size))}.`;
        summaryEl.innerHTML = summary;
        listingsEl.innerHTML = [...venues.values()].map(renderVenue).join('');
        setupSearch(listingsEl, summaryEl, summary);
    }

    // Places checked that have nothing on right now (failed ones are named in
    // the errors line instead).
    const errors = data.errors || [];
    const quiet = pageVenues.filter(v =>
        !venues.has(v.key) && !errors.some(msg => String(msg).includes(v.name)));
    if (quiet.length) {
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

        // Errors name venues ("Failed to fetch information for: <name>"). Show
        // those for this page's tap-list venues; event sources' errors go on
        // the events page.
        const mentions = (msg, v) => String(msg).includes(v.name);
        const isListingError = msg => [...venueInfo.values()].some(v => mentions(msg, v));
        const pageErrors = (data.errors || []).filter(msg => PAGE.events
            ? !isListingError(msg)
            : pageVenues.some(v => mentions(msg, v)));
        if (pageErrors.length) {
            const el = document.getElementById('errors');
            el.hidden = false;
            el.textContent = 'Couldn’t check some lists this time: ' + pageErrors.join(' ');
        }
    })
    .catch(() => {
        document.getElementById('listings').innerHTML =
            '<div class="empty">Could not load the lists.</div>';
    });
