// docs/app.js

(function () {
  const $events = document.getElementById('events');

  // Candidate locations for the JSON (tries the first that succeeds)
  const CANDIDATE_URLS = [
    'data/events.json',          // <— our target (harvester writes here)
    'events.json',               // fallback 1 (if you drop it at /docs/)
    'aom-events.json'            // fallback 2 (legacy/artifact name)
  ];

  // --- helpers -------------------------------------------------------------

  const by = (key, dir = 1) => (a, b) => (a[key] > b[key] ? dir : a[key] < b[key] ? -dir : 0);

  function fmtDate(iso) {
    if (!iso) return '';
    try {
      const d = new Date(iso);
      return d.toLocaleString([], {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
      });
    } catch { return iso; }
  }

  function monthKey(iso) {
    const d = new Date(iso);
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
  }

  function esc(str = '') {
    return String(str)
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;');
  }

  function matchesQuery(ev, q) {
    if (!q) return true;
    q = q.toLowerCase();
    const bag = [
      ev.title,
      ev.city,
      ev.state,
      ev.country,
      ev.venue,
      ev.description
    ].filter(Boolean).join(' ').toLowerCase();
    return bag.includes(q);
  }

  // Normalize a variety of event shapes into the one we render
  function normalizeEvents(json) {
    const raw = Array.isArray(json?.events) ? json.events : [];
    return raw.map(e => ({
      title: e.title || e.name || e.summary || 'Untitled event',
      url: e.url || e.link || '#',
      start: e.start_utc || e.start || e.startDate || e.start_time || e.dtstart,
      end: e.end_utc || e.end || e.endDate || e.end_time || e.dtend,
      city: e.city || e.location_city || e.city_name,
      state: e.state || e.region || e.state_code,
      country: e.country || e.country_code,
      venue: e.venue || e.location || e.place,
      source: e.source || e.provider || json?.meta?.sources?.join(', ')
    })).filter(e => e.start); // must have a start time to sort/show
  }

  function renderControls(onFilter) {
    const wrap = document.createElement('div');
    wrap.style.maxWidth = '800px';
    wrap.style.margin = '1rem auto';
    wrap.style.display = 'flex';
    wrap.style.gap = '0.5rem';
    wrap.style.alignItems = 'center';
    wrap.style.justifyContent = 'space-between';

    wrap.innerHTML = `
      <input id="q" type="search" placeholder="Filter by city, title, country…" 
             style="flex:1; padding:.6rem .8rem; border-radius:8px; border:1px solid #333; background:#111; color:#eee;">
      <button id="clear" style="padding:.6rem .9rem; border-radius:8px; border:1px solid #333; background:#222; color:#eee; cursor:pointer">
        Clear
      </button>
    `;
    document.body.insertBefore(wrap, $events.parentElement);

    const q = wrap.querySelector('#q');
    wrap.querySelector('#clear').onclick = () => { q.value = ''; onFilter(''); };
    q.addEventListener('input', () => onFilter(q.value));
  }

  function renderEmpty(msg, note = '') {
    $events.innerHTML = `
      <div style="text-align:center; padding:1rem;">
        <div style="font-weight:700; margin-bottom:.25rem;">${esc(msg)}</div>
        ${note ? `<div style="opacity:.7;">${esc(note)}</div>` : ''}
      </div>
    `;
  }

  function render(events, meta = {}) {
    if (!events.length) {
      const note = (meta?.notes && meta.notes.join(' ')) || '';
      renderEmpty('No upcoming events found.', note);
      return;
    }

    // Sort by start ascending
    events.sort(by('start', 1));

    // Group by month
    const groups = new Map();
    for (const ev of events) {
      const key = monthKey(ev.start);
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(ev);
    }

    // Build HTML
    let html = '';
    for (const [key, list] of groups) {
      const [y, m] = key.split('-');
      const monthName = new Date(`${y}-${m}-01T00:00:00Z`)
        .toLocaleString([], { month: 'long', year: 'numeric' });

      html += `
        <h2 style="margin:1.5rem 0 .75rem 0; color:#f2c14e; border-bottom:1px solid #333; padding-bottom:.25rem;">
          ${esc(monthName)}
        </h2>
      `;

      for (const e of list) {
        const place = [e.city, e.state, e.country].filter(Boolean).join(', ');
        html += `
          <article style="padding:.75rem 0; border-bottom:1px dashed #333;">
            <div style="font-weight:700; font-size:1.05rem; margin-bottom:.15rem;">
              ${e.url && e.url !== '#'
                ? `<a href="${esc(e.url)}" target="_blank" rel="noopener" style="color:#fff; text-decoration:none;">${esc(e.title)}</a>`
                : esc(e.title)}
            </div>
            <div style="opacity:.9;">
              ${esc(fmtDate(e.start))}${e.end ? ` – ${esc(fmtDate(e.end))}` : ''}${place ? ` • ${esc(place)}` : ''}
            </div>
            ${e.venue ? `<div style="opacity:.8;">Venue: ${esc(e.venue)}</div>` : ''}
            ${e.source ? `<div style="opacity:.6; font-size:.9rem;">Source: ${esc(e.source)}</div>` : ''}
          </article>
        `;
      }
    }

    $events.innerHTML = html;
  }

  async function fetchFirst(urls) {
    for (const url of urls) {
      try {
        const r = await fetch(url, { cache: 'no-store' });
        if (r.ok) return await r.json();
      } catch (_) { /* try next */ }
    }
    throw new Error('No events JSON found at known locations.');
  }

  // --- boot ---------------------------------------------------------------

  (async function boot() {
    try {
      const json = await fetchFirst(CANDIDATE_URLS);
      let events = normalizeEvents(json);

      // Only keep future events (start >= now)
      const now = Date.now();
      events = events.filter(e => new Date(e.start).getTime() >= now);

      // Controls
      renderControls(q => {
        const filtered = events.filter(e => matchesQuery(e, q));
        render(filtered, json?.meta);
      });

      render(events, json?.meta);
    } catch (err) {
      console.error(err);
      renderEmpty(
        'Could not load events.',
        'Looking for data/events.json (or a fallback). Once your harvester publishes, this will fill in automatically.'
      );
    }
  })();
})();
