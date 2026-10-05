(() => {
  const status = document.getElementById('relay-status');
  if (!status) return;
  const text = (id, value) => { document.getElementById(id).textContent = value; };
  const poll = async () => {
    try {
      const response = await fetch(status.dataset.statusUrl, {cache:'no-store'});
      if (!response.ok) throw new Error();
      const value = await response.json();
      status.textContent = `${value.enabled ? 'Enabled' : 'Disabled'} · ${value.connected === null ? 'Connection unknown' : value.connected ? 'Connected' : 'Disconnected'} · Source: ${value.source}${value.pending ? ' · Changes pending' : ''}`;
      text('relay-metadata', [value.artist, value.title].filter(Boolean).join(' — '));
      text('relay-history', `Last failure: ${value.last_failure_at || 'None observed'} · Last connection: ${value.last_reconnect_at || 'None observed'}`);
      text('relay-error', value.error || '');
    } catch (_) { status.textContent = 'Relay status unavailable'; }
    window.setTimeout(poll, 3000);
  };
  poll();
})();
