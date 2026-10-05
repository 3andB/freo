'use strict';
(() => {
  const root = document.getElementById('requests');
  if (!root || root.dataset.enabled !== 'yes') return;
  const api = root.dataset.api, notice = document.getElementById('notice');
  const songs = document.getElementById('songs'), next = document.getElementById('next'), previous = document.getElementById('previous');
  let token = '', offset = 0, query = '', loading = false;
  try { token = localStorage.getItem('freo-requests:' + api) || ''; } catch (_) { /* Storage can be blocked in an embed. */ }
  async function search() {
    if (loading) return;
    loading = true; notice.textContent = 'Loading songs…';
    try {
      const response = await fetch(api + '?q=' + encodeURIComponent(query) + '&offset=' + offset, {credentials: 'omit', headers: {'X-Request-Token': token}});
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'Songs could not be loaded.');
      token = data.token;
      try { localStorage.setItem('freo-requests:' + api, token); } catch (_) {}
      songs.replaceChildren();
      for (const track of data.tracks) {
        const li = document.createElement('li'), title = document.createElement('span'), button = document.createElement('button');
        title.textContent = track.title + ' — ' + track.artist; button.textContent = 'Request'; button.type = 'button';
        const nonce = FreoUUID();
        button.addEventListener('click', async () => {
          button.disabled = true;
          try {
            const response = await fetch(api, {method: 'POST', credentials: 'omit', headers: {'Content-Type': 'application/json', 'X-Request-Token': token}, body: JSON.stringify({track: track.uuid, nonce})});
            const data = await response.json();
            if (!response.ok) throw new Error(data.error || 'Request could not be sent. Reopen this page and try again.');
            notice.textContent = data.message; button.textContent = 'Requested';
          } catch (error) { notice.textContent = error.message; button.disabled = false; }
        });
        li.append(title, button); songs.append(li);
      }
      next.disabled = !data.more; previous.disabled = offset === 0;
      notice.textContent = data.tracks.length ? '' : 'No matching songs.';
    } catch (error) { notice.textContent = error.message; }
    finally { loading = false; }
  }
  document.getElementById('search').addEventListener('submit', event => { event.preventDefault(); if (loading) return; offset = 0; query = document.getElementById('query').value; search(); });
  next.addEventListener('click', () => { if (!loading) { offset += 25; search(); } });
  previous.addEventListener('click', () => { if (!loading) { offset = Math.max(0, offset - 25); search(); } });
  search();
})();
