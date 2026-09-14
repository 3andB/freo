(() => {
  const root = document.querySelector('.player-shell');
  if (!root) return;
  const slug = root.dataset.station;
  const base = `/api/stations/${encodeURIComponent(slug)}`;
  const byId = id => document.getElementById(id);
  const audio = byId('station-audio');
  const button = byId('play-button');
  const message = byId('audio-message');
  const status = byId('stream-status');
  const setText = (id, value) => { byId(id).textContent = value ?? '—'; };
  const get = async path => {
    const response = await fetch(path, {cache: 'no-store'});
    if (!response.ok) throw new Error('Unavailable');
    return response.json();
  };
  const clock = value => value ? new Date(value).toLocaleString([], {dateStyle:'medium', timeStyle:'short'}) : '—';
  const stationClock = (value, zone) => value ? `${value.slice(0, 16).replace('T', ' ')} ${zone || ''}` : '—';
  function showHistory(rows) {
    const list = byId('recent-history');
    list.replaceChildren();
    if (!rows.length) { const item = document.createElement('li'); item.textContent = 'No confirmed starts yet.'; list.append(item); return; }
    for (const row of rows.slice(0, 6)) {
      const item = document.createElement('li');
      item.textContent = `${row.title || 'Track unavailable'} — ${row.artist || 'Unknown artist'}`;
      const time = document.createElement('span'); time.textContent = clock(row.started_at);
      item.append(time); list.append(item);
    }
    const latest = rows[0];
    setText('playing-heading', latest.title || 'Track unavailable');
    setText('playing-artist', latest.artist || 'Unknown artist');
    setText('playing-detail', `Confirmed start: ${clock(latest.started_at)}. This may not be the track currently playing.`);
  }
  async function refresh() {
    const [station, observed, history, schedule] = await Promise.allSettled([
      get(base), get(`${base}/status`), get(`${base}/history`), get(`${base}/schedule/current`)
    ]);
    if (station.status === 'fulfilled') setText('station-format', `${station.value.bitrate} kbps ${station.value.format.toUpperCase()}`);
    if (observed.status === 'fulfilled') {
      const online = observed.value.stream === 'online';
      status.textContent = online ? 'STREAM ONLINE' : 'STREAM UNAVAILABLE';
      status.className = `status-badge ${online ? 'online' : 'offline'}`;
    } else { status.textContent = 'STATUS UNKNOWN'; status.className = 'status-badge'; }
    if (schedule.status === 'fulfilled') {
      setText('station-time', stationClock(schedule.value.local_time, schedule.value.timezone));
      setText('station-clock', schedule.value.clock || 'No active clock');
    }
    if (history.status === 'fulfilled') showHistory(history.value.history);
    else { setText('playing-detail', 'Playback history is temporarily unavailable.'); }
  }
  function syncAudio() {
    const playing = !audio.paused && !audio.ended;
    button.textContent = playing ? 'Ⅱ' : '▶';
    button.setAttribute('aria-label', playing ? 'Pause live stream' : 'Play live stream');
  }
  button.addEventListener('click', async () => {
    if (!audio.paused) { audio.pause(); return; }
    message.textContent = 'Connecting…';
    try { await audio.play(); message.textContent = 'Playing live stream.'; }
    catch (error) { message.textContent = error.name === 'NotAllowedError' ? 'Tap play to allow audio.' : 'Could not connect. Try again.'; syncAudio(); }
  });
  audio.addEventListener('playing', () => { message.textContent = 'Playing live stream.'; syncAudio(); });
  audio.addEventListener('pause', () => { message.textContent = 'Paused.'; syncAudio(); });
  audio.addEventListener('waiting', () => { message.textContent = 'Buffering…'; });
  audio.addEventListener('error', () => { message.textContent = 'Stream disconnected. Press play to retry.'; syncAudio(); });
  byId('volume').addEventListener('input', event => { audio.volume = Number(event.target.value) / 100; });
  audio.volume = .8;
  byId('share-button').addEventListener('click', async event => {
    try { await navigator.clipboard.writeText(location.href); event.target.textContent = 'Link copied'; }
    catch { event.target.textContent = 'Copy this page URL'; }
    setTimeout(() => { event.target.textContent = 'Copy player link'; }, 2200);
  });
  refresh(); setInterval(refresh, 15000);
})();
