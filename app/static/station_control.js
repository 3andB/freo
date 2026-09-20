(() => {
  'use strict';
  const root = document.getElementById('station-control');
  if (!root) return;
  const page = window.FreoPage;
  const $ = id => document.getElementById(id);
  const title = mode => mode.charAt(0) + mode.slice(1).toLowerCase();
  let state = JSON.parse($('control-initial').value), busy = false, broadcastBusy = false, refreshing = false, refreshFailed = false;
  const pending = () => state.transition && ['PENDING', 'PREPARING', 'FADING'].includes(state.transition.state);

  async function api(action, data) {
    const options = data === undefined ? {} : {method: 'POST', body: new URLSearchParams({csrf: root.dataset.csrf, payload: JSON.stringify(data)})};
    const response = await page.fetch(root.dataset.api + action, options);
    const result = await response.json();
    if (!response.ok) throw Error(result.error || 'Unable to reach station control.');
    return result;
  }
  function message(text, error = false) {
    $('control-message').textContent = text;
    $('control-message').classList.toggle('error', error);
  }
  function render() {
    const broadcast = state.broadcast;
    const toggle = $('master-broadcast-toggle');
    if (toggle) {
      toggle.disabled = broadcastBusy;
      toggle.setAttribute('aria-checked', String(broadcast.enabled));
      toggle.textContent = broadcast.enabled ? 'ON' : 'OFF';
    }
    $('broadcast-retry').hidden = broadcast.status !== 'failed' || !toggle;
    $('broadcast-retry').disabled = broadcastBusy;
    $('broadcast-message').textContent = broadcast.error || (['pending', 'applying'].includes(broadcast.status)
      ? (broadcast.enabled ? 'Starting broadcast…' : 'Stopping broadcast…')
      : broadcast.online === null ? 'Broadcast status unavailable. Checking…'
      : broadcast.online ? (broadcast.tone ? 'Broadcasting tone' : 'Station is broadcasting')
      : broadcast.enabled ? 'Master is ON, but the stream is offline.' : 'Broadcast is OFF');
    $('control-status-heading').textContent = `System currently running in ${title(state.mode)} mode.`;
    $('control-transition').textContent = pending()
      ? `Switching to ${title(state.transition.mode)}… Waiting for the playback engine.`
      : state.transition?.state === 'FAILED' ? `Switch failed: ${state.transition.error || 'Current mode retained.'}` : '';
    $('control-detail').textContent = `Station timezone: ${state.timezone}` + (state.playing_fallback
      ? ` · Playing default playlist: ${state.fallback?.name || 'Unavailable'}` : '');
    root.querySelectorAll('[data-mode]').forEach(card => card.classList.toggle('is-active', card.dataset.mode === state.mode));
    root.querySelectorAll('[data-control-badge]').forEach(badge => {
      badge.textContent = badge.dataset.controlBadge === state.mode ? 'Current mode' : '';
    });
    root.querySelectorAll('[data-switch-mode]').forEach(button => {
      const active = state.activated && button.dataset.switchMode === state.mode && !state.held;
      button.disabled = busy || broadcastBusy || pending() || active;
      button.textContent = active ? 'Active mode' : `Use ${title(button.dataset.switchMode)}`;
    });
    const label = document.querySelector('.schedule-mode-status');
    if (label) label.textContent = pending() ? `Switching ${title(state.mode)} → ${title(state.transition.mode)}…` : `Active mode: ${title(state.mode)}`;
  }
  async function setBroadcast(enabled) {
    if (broadcastBusy) return;
    broadcastBusy = true; render(); message('');
    try { state = await api('broadcast', {enabled, revision: state.broadcast.revision}); }
    catch (error) { message(error.message, true); }
    finally { broadcastBusy = false; if (!page.signal.aborted) render(); }
  }
  $('master-broadcast-toggle')?.addEventListener('click', () => setBroadcast(!state.broadcast.enabled));
  $('broadcast-retry').addEventListener('click', () => setBroadcast(state.broadcast.enabled));
  async function refresh() {
    if (busy || broadcastBusy || refreshing || document.hidden) return;
    refreshing = true;
    try {
      const latest = await api('state');
      if (!busy && !broadcastBusy && latest.broadcast.revision >= state.broadcast.revision && latest.revision >= state.revision) { state = latest; render(); if (refreshFailed) message(''); refreshFailed = false; }
    }
    catch { if (!busy && !broadcastBusy) {
      refreshFailed = true; state.broadcast.online = null; state.broadcast.tone = null;
      render(); message('Unable to refresh station status. Retrying…', true);
    } }
    finally { refreshing = false; }
  }
  root.querySelectorAll('[data-switch-mode]').forEach(button => {
    button.onclick = async () => {
      if (busy || pending()) return;
      busy = true; render(); message('');
      try {
        state = await api('state'); render();
        if (pending()) throw Error('Wait for the current mode change to finish.');
        const mode = button.dataset.switchMode;
        const preview = await api('transition-preview', {mode});
        if (!preview.playable) throw Error('Nothing playable. Configure this mode or choose a default playlist in Station settings.');
        const payload = {id: crypto.randomUUID(), current: state.mode, mode, revision: state.revision};
        const confirmed = await window.FreoDialog.confirm({
          title: `Switch from ${title(state.mode)} to ${title(mode)}?`,
          message: `This fades the current audio now, including any Event or live audio. Saved schedules are kept and future Events remain enabled. Will play now: ${preview.source.name}${preview.reason ? ' · Default playlist (' + preview.reason + ')' : ''}.`,
          confirmLabel: 'Confirm & switch now', signal: page.signal
        });
        if (!confirmed) return;
        await api('transition', payload);
        state = await api('state');
      } catch (error) { message(error.message, true); }
      finally { busy = false; if (!page.signal.aborted) render(); }
    };
  });
  render();
  page.interval(refresh, 4000);
  refresh();
})();
