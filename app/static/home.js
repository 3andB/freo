/* Public site interactions use the persistent workspace's disposable page scope. */
(() => {
  if (!document.body.classList.contains('station-home')) return;
  const scope = window.FreoPage;
  const header = document.querySelector('.station-header'), menu = document.querySelector('.station-menu');
  const nav = document.querySelector('#station-navigation');
  header.classList.add('enhanced'); menu.hidden = false;
  function closeMenu(focus = false) { nav.classList.remove('is-open'); menu.setAttribute('aria-expanded', 'false'); if (focus) menu.focus(); }
  scope.listen(menu, 'click', () => { const open = menu.getAttribute('aria-expanded') !== 'true'; nav.classList.toggle('is-open', open); menu.setAttribute('aria-expanded', String(open)); });
  scope.listen(nav, 'click', () => closeMenu());
  scope.listen(document, 'keydown', e => { if (e.key === 'Escape' && menu.getAttribute('aria-expanded') === 'true') closeMenu(true); });
  const toggle = document.querySelector('.site-theme-toggle');
  const preferred = matchMedia('(prefers-color-scheme: dark)');
  let choice = null;
  try { choice = localStorage.getItem('freo.website.theme'); } catch (_) {}
  function theme() {
    const value = ['day','night'].includes(choice) ? choice : toggle.dataset.defaultTheme === 'system' ? (preferred.matches ? 'night' : 'day') : toggle.dataset.defaultTheme;
    document.body.dataset.siteTheme = value;
    toggle.setAttribute('aria-label', value === 'night' ? 'Switch to day theme' : 'Switch to night theme');
    toggle.setAttribute('aria-pressed', String(value === 'night'));
  }
  toggle.hidden = false; theme();
  scope.listen(toggle, 'click', () => { choice = document.body.dataset.siteTheme === 'night' ? 'day' : 'night'; try {localStorage.setItem('freo.website.theme',choice);} catch (_) {} theme(); });
  scope.listen(preferred, 'change', theme);
  const filter = document.querySelector('[data-schedule-filter]');
  if (filter) scope.listen(filter, 'change', () => {
    let visible = 0;
    document.querySelectorAll('[data-schedule-channel]').forEach(row => { row.hidden = !!filter.value && row.dataset.scheduleChannel !== filter.value; if (!row.hidden) visible++; });
    document.querySelector('.schedule-no-results').hidden = visible > 0;
  });
  let busy = false;
  async function refresh() {
    if (document.hidden || busy) return;
    busy = true;
    try {
      for (const card of document.querySelectorAll('[data-channel-state]')) {
        if (scope.signal.aborted) return;
        const status = card.querySelector('[data-status]'), song = card.querySelector('[data-now-song]');
        try {
          const response = await scope.fetch(card.dataset.channelState, {headers:{Accept:'application/json'}});
          if (!response.ok) throw new Error('Unavailable');
          const state = await response.json();
          status.classList.toggle('is-online', state.stream_online === true);
          status.replaceChildren(document.createElement('i'), document.createTextNode(state.stream_online === true ? 'On air' : state.stream_online === false ? 'Off air' : 'Status unavailable'));
          song.textContent = state.fresh && state.current.length ? state.current.map(item => [item.artist,item.title].filter(Boolean).join(' — ')).join(' / ') : state.stream_online === false ? 'Taking a little breather. Check back soon.' : 'Open the player to discover what’s on.';
        } catch (_) { status.classList.remove('is-online'); status.textContent = 'Status unavailable'; song.textContent = 'Open the player to discover what’s on.'; }
      }
    } finally { busy = false; }
  }
  refresh(); scope.interval(refresh, 12000); scope.listen(document, 'visibilitychange', refresh);
})();
