(() => {
  async function probePublicStream() {
    const probes = document.querySelectorAll('.admin-stream-probe');
    if (!probes.length) return;
    const path = probes[0].dataset.streamPath;
    if (!/^\/stream\/[a-z0-9][a-z0-9-]*$/.test(path)) {
      probes.forEach(node => node.textContent = 'Unknown');
      return;
    }
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 5000);
    let result = 'Unavailable';
    try {
      const response = await fetch(path, {cache: 'no-store', signal: controller.signal});
      if (response.ok && response.body && (response.headers.get('content-type') || '').startsWith('audio/')) {
        const chunk = await response.body.getReader().read();
        if (chunk.value?.length) result = 'Receiving audio';
      }
    } catch { /* A stopped stream or timed-out route is unavailable. */ }
    finally { clearTimeout(timeout); controller.abort(); }
    probes.forEach(node => node.textContent = result);
  }
  probePublicStream();
  if (document.querySelector('.admin-stream-probe')) setInterval(probePublicStream, 60000);
  const page = document.querySelector('.admin-hero');
  if (!page) return;
  const station = new URLSearchParams(location.search).get('station') ||
    document.querySelector('.station-picker select')?.value;
  if (!station) return;
  const base = `/admin/api/stations/${encodeURIComponent(station)}`;
  const set = (id, value) => {
    const element = document.getElementById(id);
    if (element) element.textContent = value ?? '—';
  };
  const get = async path => {
    const response = await fetch(path, {cache: 'no-store'});
    if (!response.ok) throw new Error('Observation unavailable');
    return response.json();
  };
  const title = value => value ? value.charAt(0).toUpperCase() + value.slice(1) : 'Unknown';
  async function refreshNow() {
    try {
      const payload = await get(`${base}/now`);
      if (!payload.now_playing) {
        set('admin-track', 'No confirmed start');
        set('admin-artist', 'Waiting for verified playback.');
      } else {
        set('admin-track', payload.now_playing.title || 'Track unavailable');
        set('admin-artist', payload.now_playing.artist || 'Unknown artist');
      }
    } catch {
      set('admin-track', 'Playback observation unavailable');
      set('admin-artist', 'Try refreshing later.');
    }
  }
  async function refreshRuntime() {
    try {
      const payload = await get(`${base}/snapshot`);
      const online = payload.observed?.stream === 'online';
      set('admin-onair', online ? 'ON AIR' : 'OFFLINE');
      document.getElementById('admin-onair').className = `onair-pill ${online ? 'is-on' : 'is-off'}`;
      set('admin-stream', title(payload.observed?.stream));
      set('admin-playout', title(payload.observed?.playout));
      set('admin-worker', title(payload.worker));
      set('admin-queue', payload.queue_depth == null ? 'Unknown' : String(payload.queue_depth));
    } catch {
      set('admin-onair', 'UNKNOWN');
      document.getElementById('admin-onair').className = 'onair-pill is-off';
      for (const id of ['admin-stream', 'admin-playout', 'admin-worker', 'admin-queue']) set(id, 'Unknown');
    }
  }
  async function refreshProgramming() {
    try {
      const payload = await get(`${base}/snapshot`);
      set('admin-clock', payload.clock || 'No active clock');
      set('admin-slot', payload.next_slot || 'Not available');
      set('admin-local-time', `${payload.local_time.slice(0, 16).replace('T', ' ')} ${payload.timezone}`);
      set('admin-transition', payload.next_transition || 'No weekly transition');
    } catch {
      set('admin-clock', 'Programming unavailable');
      set('admin-slot', 'Unknown');
      set('admin-local-time', 'Unknown');
      set('admin-transition', 'Unknown');
    }
  }
  refreshNow(); refreshRuntime();
  setInterval(refreshNow, 5000);
  setInterval(refreshRuntime, 15000);
  setInterval(refreshProgramming, 45000);
})();
