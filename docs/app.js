(async function () {
  const $list = document.getElementById('list');
  const $notice = document.getElementById('notice');
  const $updated = document.getElementById('updated');
  const $sources = document.getElementById('sources');
  const $q = document.getElementById('q');
  const $from = document.getElementById('from');
  const $to = document.getElementById('to');
  const $clear = document.getElementById('clear');

  // Load JSON produced by the harvester (written by the workflow below)
  let data;
  try {
    const res = await fetch('data/events.json', { cache: 'no-store' });
    data = await res.json();
  } catch (e) {
    $updated.textContent = 'Could not load events.json';
    return;
  }

  const meta = data.meta || {};
  const events = Array.isArray(data.events) ? data.events : [];
  $updated.textContent = meta.ts_utc ? `Last updated: ${meta.ts_utc}` : 'No timestamp';
  $sources.textContent = (meta.sources || []).join(', ') || '—';

  if (!events.length) {
    $notice.classList.remove('hidden');
    $notice.innerHTML =
      `No events harvested yet. As sources are added (ICS feeds or HTML scrapers), they will appear here automatically.`;
  }

  const fmt = (s) => new Date(s).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' });

  function render(list) {
    $list.innerHTML = '';
    list.forEach(ev => {
      const li = document.createElement('li');
      li.className = 'card';
      const when = ev.start ? fmt(ev.start) : 'TBA';
      const where = [ev.city, ev.state, ev.country].filter(Boolean).join(', ') || 'Online / TBA';
      const org = ev.organizer || ev.source || '';
      const link = ev.url ? `<a href="${ev.url}" target="_blank" rel="noopener">event link</a>` : '';

      li.innerHTML = `
        <h3>${ev.title || 'Untitled'} ${ev.source ? `<span class="badge">${ev.source}</span>` : ''}</h3>
        <div class="meta">${when} • ${where}${org ? ` • ${org}` : ''}</div>
        <div>${ev.summary || ''}</div>
        <div class="meta">${link}</div>
      `;
      $list.appendChild(li);
    });
  }

  function applyFilters() {
    const q = ($q.value || '').toLowerCase().trim();
    const f = $from.value ? new Date($from.value) : null;
    const t = $to.value ? new Date($to.value) : null;
    const filtered = events.filter(ev => {
      const hay = [
        ev.title, ev.city, ev.state, ev.country, ev.organizer, ev.source, ev.summary
      ].filter(Boolean).join(' ').toLowerCase();
      const okQ = q ? hay.includes(q) : true;
      const start = ev.start ? new Date(ev.start) : null;
      const okFrom = f && start ? start >= f : true;
      const okTo   = t && start ? start <= t : true;
      return okQ && okFrom && okTo;
    }).sort((a,b) => (a.start||'').localeCompare(b.start||''));
    render(filtered);
  }

  $q.oninput = $from.onchange = $to.onchange = applyFilters;
  $clear.onclick = () => { $q.value=''; $from.value=''; $to.value=''; applyFilters(); };

  render(events);
})();
