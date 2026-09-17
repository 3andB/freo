/* Refresh observations without replacing forms, focus, or station controls. */
(() => {
  const root = document.getElementById('operations');
  if (!root) return;
  const scope = window.FreoPage;
  let pending = false;
  const value = (v, fallback = '—') => v == null || v === '' ? fallback : String(v);
  async function refresh() {
    if (pending || document.hidden) return;
    pending = true;
    const controller = new AbortController();
    const abort = () => controller.abort();
    scope.signal.addEventListener('abort', abort, {once: true});
    const timeout = setTimeout(abort, 10000);
    try {
      const response = await scope.fetch(root.dataset.url, {cache: 'no-store', signal: controller.signal});
      if (!response.ok || !response.headers.get('content-type')?.includes('application/json')) throw new Error('Unavailable');
      const data = await response.json();
      if (scope.signal.aborted) return;
      root.querySelectorAll('[data-summary]').forEach(el => {el.textContent = value(data.summary[el.dataset.summary]);});
      root.querySelectorAll('[data-connection]').forEach(el => {el.textContent = value(data.connection[el.dataset.connection], '');});
      root.querySelector('[data-storage]').textContent = data.summary.storage == null ? 'Not yet measured' : `${(data.summary.storage / 1000000).toLocaleString(undefined, {maximumFractionDigits: 1})} MB`;
      root.querySelectorAll('[data-ops-station]').forEach(card => {
        const row = data.stations[card.dataset.opsStation];
        if (!row) {card.querySelector('[data-station-field="status"]').textContent = 'Removed · refresh page'; return;}
        card.querySelectorAll('[data-station-field]').forEach(el => {
          const key = el.dataset.stationField;
          el.textContent = value(row[key], key === 'artist' ? '' : 'Unknown');
          if (key === 'status') {el.classList.toggle('is-on', row.status === 'On air'); el.classList.toggle('is-off', row.status !== 'On air');}
        });
      });
      document.getElementById('ops-freshness').textContent = `Updated ${new Date(data.generated_at * 1000).toLocaleTimeString()} · Worker observations refresh every 15 seconds.`;
    } catch {
      if (!scope.signal.aborted) {
        document.getElementById('ops-freshness').textContent = 'Updates unavailable. Displayed values are from the last successful refresh.';
        root.querySelectorAll('[data-station-field="status"]').forEach(el => {el.textContent = 'Unknown · update unavailable'; el.classList.remove('is-on'); el.classList.add('is-off');});
        root.querySelector('[data-connection="status"]').textContent = 'Connection observation unavailable';
        root.querySelectorAll('[data-station-field="playback_label"]').forEach(el => {el.textContent = 'Last observed playback';});
      }
    } finally {clearTimeout(timeout); scope.signal.removeEventListener('abort', abort); pending = false;}
  }
  scope.interval(refresh, 15000);
  scope.listen(document, 'visibilitychange', () => {if (!document.hidden) refresh();});
})();
