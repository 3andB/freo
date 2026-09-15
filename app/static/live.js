(() => {
  const root = document.getElementById('live-strip');
  if (!root) return;
  const picker = document.querySelector('.station-picker');
  if (picker) picker.addEventListener('submit', event => {
    event.preventDefault();
    const slug = picker.querySelector('select[name="station"]').value;
    if (/^[a-z0-9-]{1,64}$/.test(slug)) location.assign(`/admin/stations/${encodeURIComponent(slug)}/live`);
  });
  const text = (id, value) => { const el = document.getElementById(id); if (el) el.textContent = value; };
  const fill = (id, items, empty) => {
    const list = document.getElementById(id);
    list.replaceChildren();
    if (!items.length) { const li = document.createElement('li'); li.className = 'empty-copy'; li.textContent = empty; list.append(li); return; }
    for (const item of items) {
      const li = document.createElement('li');
      const b = document.createElement('b'); b.textContent = item.title;
      const small = document.createElement('small'); small.textContent = `${item.artist} · ${item.source}${item.started_at ? ' · ' + item.started_at : ''}`;
      li.append(b, small); list.append(li);
    }
  };
  async function refresh() {
    try {
      const response = await fetch(root.dataset.statusUrl, {credentials: 'same-origin', cache: 'no-store'});
      if (!response.ok) throw new Error('status');
      const data = await response.json();
      text('live-mode', data.automation);
      text('live-clock', data.clock || 'No active clock');
      text('live-transition', data.next_transition || 'No next transition');
      text('live-playout', data.playout_error || 'Connected');
      text('live-fallback', `Fallback: ${data.fallback}`);
      text('next-event-name', data.next_event?.name || 'None scheduled');
      const eventDetail = document.getElementById('next-event-detail');
      eventDetail.dataset.at = data.next_event?.scheduled_for || '';
      const overrun = data.next_event?.estimated_current_overrun_seconds;
      eventDetail.textContent = data.next_event ? `${data.next_event.timing_mode} · ${data.next_event.state}${overrun == null ? '' : ` · current estimate ${overrun > 0 ? '+' : ''}${overrun}s`}` : 'Timed events remain active during automation hold.';
      text('queue-count', String(data.queue.length));
      const current = document.getElementById('live-current');
      current.replaceChildren();
      const title = document.createElement('strong'); title.textContent = data.current?.title || 'No approved request observed on air';
      const detail = document.createElement('span'); detail.textContent = data.current ? `${data.current.artist} · ${data.current.source}` : 'Generated fallback may be active.';
      current.append(title, detail);
      document.getElementById('skip-decision').value = data.current?.decision_id || '';
      document.querySelector('#skip-form button').disabled = !data.current;
      fill('live-queue', data.queue, 'Queue is empty.');
      fill('live-recent', data.recent, 'No confirmed starts yet.');
    } catch { text('live-playout', 'Status unavailable'); }
  }
  function countdown() {
    const at = document.getElementById('next-event-detail').dataset.at;
    if (!at) return text('event-countdown', '');
    const seconds = Math.round((Date.parse(at) - Date.now()) / 1000);
    const sign = seconds < 0 ? '+' : '';
    const value = Math.abs(seconds);
    text('event-countdown', `${sign}${Math.floor(value / 60)}:${String(value % 60).padStart(2, '0')}`);
  }
  document.querySelectorAll('.live-results form, .cart-wall form, #skip-form').forEach(form => form.addEventListener('submit', () => {
    form.querySelector('button').disabled = true;
  }));
  setInterval(refresh, 3000);
  countdown(); setInterval(countdown, 1000);
})();
