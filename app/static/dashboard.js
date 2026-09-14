(() => {
  const root = document.querySelector('.dashboard-shell');
  if (!root) return;
  const base = `/api/stations/${encodeURIComponent(root.dataset.station)}`;
  const text = (id, value) => { document.getElementById(id).textContent = value ?? '—'; };
  const stamp = value => value ? new Date(value).toLocaleString([], {dateStyle:'medium',timeStyle:'short'}) : '—';
  const stationClock = (value, zone) => value ? `${value.slice(0, 16).replace('T', ' ')} ${zone || ''}` : '—';
  const get = async path => { const response = await fetch(path, {cache:'no-store'}); if (!response.ok) throw new Error('Unavailable'); return response.json(); };
  async function refresh() {
    const results = await Promise.allSettled([
      get(`${base}/status`), get(`${base}/automation/status`), get(`${base}/media`),
      get(`${base}/categories`), get(`${base}/history`)
    ]);
    const value = index => results[index].status === 'fulfilled' ? results[index].value : null;
    const station = value(0), automation = value(1), media = value(2), categories = value(3), history = value(4);
    text('d-stream', station?.stream || 'Unknown');
    text('d-stream-detail', station ? `Icecast mount: ${station.icecast_mount}` : 'Status observation unavailable');
    text('d-playout', station?.playout || 'Unknown');
    text('d-desired', station ? `Desired: ${station.desired_state}` : 'Desired state unavailable');
    text('d-automation', automation ? automation.enabled ? 'Enabled' : 'Disabled' : 'Unknown');
    text('d-worker', automation ? `Station heartbeat: ${stamp(automation.worker_heartbeat)}` : 'Heartbeat unavailable');
    text('d-queue', automation?.queue_depth == null ? 'Unknown' : String(automation.queue_depth));
    text('d-clock', automation ? automation.active_clock || 'No active clock' : 'Clock unavailable');
    text('d-time', automation ? stationClock(automation.local_time, automation.timezone) : '—');
    text('d-rotation', automation?.active_rotation || 'None');
    text('d-transition', automation ? stamp(automation.next_transition) : '—');
    text('d-media', media ? `${media.tracks.length}${media.tracks.length === 100 ? '+' : ''} tracks shown` : 'Library unavailable');
    text('d-categories', categories ? `${categories.categories.length} categories` : 'Categories unavailable');
    const list = document.getElementById('d-history'); list.replaceChildren();
    if (history) {
      for (const row of history.history.slice(0, 12)) {
        const item = document.createElement('li');
        item.textContent = `${row.title || 'Track unavailable'} — ${row.artist || 'Unknown artist'}`;
        const detail = document.createElement('span');
        detail.textContent = `${stamp(row.started_at)} · ${row.clock || row.rotation || 'manual'} · ${row.category || 'category unavailable'}`;
        item.append(detail); list.append(item);
      }
      if (!history.history.length) { const item = document.createElement('li'); item.textContent = 'No confirmed starts yet.'; list.append(item); }
    } else { const item = document.createElement('li'); item.textContent = 'History unavailable.'; list.append(item); }
  }
  refresh(); setInterval(refresh, 15000);
})();
