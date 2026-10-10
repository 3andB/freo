/* Refresh observations without replacing forms, focus, or station controls. */
(() => {
  const root = document.getElementById('operations');
  if (!root) return;
  const scope = window.FreoPage;
  let pending = false;
  const value = (v, fallback = '—') => v == null || v === '' ? fallback : String(v);
  const checkForm = root.querySelector('#connection-check');
  const checkMessage = root.querySelector('#connection-check-status');
  const checkButton = checkForm.querySelector('button');
  let submitting = false;
  let checkGeneration = 0;
  let busy = ['queued', 'checking'].includes(checkMessage.dataset.checkStatus);
  let retryAt = Number(checkMessage.dataset.retryAt || 0);
  function updateButton() {
    checkButton.disabled = submitting || busy || Date.now() / 1000 < retryAt;
    checkButton.textContent = submitting ? 'Requesting…' : busy ?
      (checkMessage.dataset.checkStatus === 'checking' ? 'Checking…' : 'Queued') : 'Check connection now';
  }
  function renderCheck(check) {
    busy = check.busy;
    retryAt = check.retry_at || 0;
    checkMessage.dataset.checkStatus = check.status;
    checkMessage.textContent = check.message;
    if (!busy && retryAt > Date.now() / 1000) {
      checkMessage.textContent += ` Available again at ${new Date(retryAt * 1000).toLocaleTimeString()}.`;
    }
    updateButton();
  }
  scope.listen(checkForm, 'submit', async event => {
    event.preventDefault();
    if (submitting || busy || Date.now() / 1000 < retryAt) return;
    submitting = true;
    checkGeneration += 1;
    updateButton();
    const controller = new AbortController();
    const abort = () => controller.abort();
    scope.signal.addEventListener('abort', abort, {once: true});
    const timeout = setTimeout(abort, 10000);
    try {
      const response = await scope.fetch(checkForm.action, {method: 'POST', body: new FormData(checkForm),
        headers: {Accept: 'application/json'}, signal: controller.signal});
      if (!response.ok || !response.headers.get('content-type')?.includes('application/json')) throw new Error('Unavailable');
      renderCheck(await response.json());
    } catch {
      if (!scope.signal.aborted) checkMessage.textContent = 'Could not confirm the request. Refreshing its status; previous results are still shown.';
    } finally {
      clearTimeout(timeout);
      scope.signal.removeEventListener('abort', abort);
      submitting = false;
      if (!scope.signal.aborted) {updateButton(); refresh();}
    }
  });
  async function refresh() {
    if (pending || document.hidden) return;
    const generation = checkGeneration;
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
      root.querySelector('[data-version-notice]').hidden = data.connection.update_available !== true;
      const releaseLink = root.querySelector('[data-release-link]');
      releaseLink.hidden = !data.connection.release_url;
      if (data.connection.release_url) releaseLink.href = data.connection.release_url;
      else releaseLink.removeAttribute('href');
      // A snapshot started before a click must not replace its queued response.
      if (!submitting && generation === checkGeneration) renderCheck(data.connection.check);
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
  scope.interval(() => {updateButton(); if (busy) refresh();}, 2000);
  updateButton();
  scope.listen(document, 'visibilitychange', () => {if (!document.hidden) refresh();});
})();
