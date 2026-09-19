(() => {
  const root = document.getElementById('playlist-workspace'); if (!root) return;
  const scope = window.FreoPage, $ = id => document.getElementById(id);
  const form = $('playlist-form'), selected = new Set();
  let catalog, current, undo, dirty = false, busy = false, dragged, searchPage = 1, detailSequence = 0;
  const node = (tag, text, cls) => { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; if (cls) n.className = cls; return n; };
  const button = (text, fn, label) => { const n = node('button', text); n.type = 'button'; if (label) n.setAttribute('aria-label', label); n.addEventListener('click', fn); return n; };
  const duration = ms => { const seconds = Math.floor((ms || 0) / 1000); return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`; };
  const message = text => { $('playlist-message').textContent = text; $('playlist-add-status').textContent = text; };
  async function get(url) { const r = await scope.fetch(url, {cache: 'no-store'}); if (!r.ok || !r.headers.get('content-type')?.includes('application/json')) throw Error('Unable to load playlists. Refresh and try again.'); return r.json(); }
  async function post(action, payload) {
    if (busy) return null;
    busy = true; root.setAttribute('aria-busy', 'true');
    try {
      const result = await FreoMusicToggles.request(root.dataset, action, payload); message(result.message);
      undo = result.undo || null; $('playlist-undo').hidden = !undo;
      return result;
    } catch (e) { message(e.message); return null; }
    finally { busy = false; root.removeAttribute('aria-busy'); }
  }
  function canChange() { if (busy) return false; if (dirty) { message('Save or discard your playlist details first.'); return false; } return true; }
  function setDirty(value) { dirty = value; $('playlist-save-state').textContent = value ? 'Unsaved changes' : 'Saved'; $('playlist-discard').hidden = !value; }
  function fillForm() { for (const key of ['name', 'description', 'mode']) form.elements[key].value = current[key]; setDirty(false); }
  function preview(song) {
    const b = node('button', '▶', 'preview-button'); b.type = 'button'; b.disabled = !song.audition;
    b.setAttribute('aria-label', `Play ${song.title}`);
    if (song.audition) Object.assign(b.dataset, {preview: song.uuid, title: song.title, artist: song.artist, audition: song.audition, gain: song.gain.factor, gainDb: song.gain.db, gainStatus: song.gain.status});
    return b;
  }
  function renderList() {
    const list = $('playlist-list'); list.replaceChildren();
    for (const item of catalog.playlists) {
      const b = button(item.name, () => { if (canChange()) open(item.id); }); b.className = 'playlist-choice';
      b.append(node('small', `${item.count} songs · ${duration(item.duration_ms)} · ${item.mode === 'RANDOM' ? 'Random' : 'Straight'}`));
      if (current?.id === item.id) b.setAttribute('aria-current', 'true'); list.append(b);
    }
  }
  function renderSongs() {
    $('playlist-delete').disabled=!!current.system_key;
    const list = $('playlist-songs'); list.replaceChildren();
    const term = $('playlist-search').value.trim().toLowerCase();
    const songs = current.songs.filter(s => `${s.title} ${s.artist} ${s.album}`.toLowerCase().includes(term));
    $('playlist-count').textContent = `${current.count} songs · ${duration(current.duration_ms)}`;
    $('playlist-mode-hint').textContent = current.mode === 'RANDOM' ? 'Shuffles without repeating a song until the cycle finishes.' : 'Plays from top to bottom, then repeats.';
    if (!songs.length) list.append(node('p', current.count ? 'No matching songs.' : 'Your playlist is ready for music. Choose Add music to begin.', 'room-empty'));
    songs.forEach(song => {
      const row = node('article', undefined, 'playlist-song'); row.dataset.song = song.uuid;
      const check = node('input'); check.type = 'checkbox'; check.checked = selected.has(song.uuid); check.setAttribute('aria-label', `Select ${song.title}`);
      check.addEventListener('change', () => { check.checked ? selected.add(song.uuid) : selected.delete(song.uuid); $('playlist-remove').disabled = !selected.size; });
      const handle = node('span', '⠿', 'playlist-grip'); handle.draggable = !term; handle.title = 'Drag to reorder';
      handle.addEventListener('dragstart', e => { if (!canChange() || term) { e.preventDefault(); return; } dragged = song.uuid; e.dataTransfer.setData('text/plain', song.uuid); });
      handle.addEventListener('dragend', () => { dragged = null; root.querySelectorAll('.drop-active').forEach(n => n.classList.remove('drop-active')); });
      row.addEventListener('dragover', e => { if (dragged && !term) { e.preventDefault(); row.classList.add('drop-active'); } });
      row.addEventListener('dragleave', () => row.classList.remove('drop-active'));
      row.addEventListener('drop', e => { e.preventDefault(); row.classList.remove('drop-active'); if (dragged && !term) reorder(dragged, current.songs.findIndex(s => s.uuid === song.uuid)); dragged = null; });
      const copy = node('div', undefined, 'playlist-song-copy'); copy.append(node('b', song.title), node('small', `${song.artist} · ${duration(song.duration_ms)}${song.playable ? '' : ' · Unavailable for broadcast'}`));
      const index = current.songs.findIndex(s => s.uuid === song.uuid);
      const up = button('↑', () => reorder(song.uuid, index - 1), `Move ${song.title} up`), down = button('↓', () => reorder(song.uuid, index + 1), `Move ${song.title} down`);
      up.disabled = index === 0 || !!term; down.disabled = index === current.songs.length - 1 || !!term;
      row.append(check, handle, node('span', String(index + 1)), preview(song), copy, up, down, button('Remove', () => remove([song.uuid]), `Remove ${song.title} from playlist`)); list.append(row);
    });
    $('playlist-remove').disabled = !selected.size; window.FreoPreview?.sync();
  }
  async function open(id) {
    const sequence = ++detailSequence;
    try {
      const next = await get(root.dataset.catalog + '/' + id); if (sequence !== detailSequence) return;
      current = next; selected.clear(); $('playlist-search').value = ''; fillForm(); renderList(); renderSongs();
      $('playlist-editor').hidden = false; $('playlist-empty').hidden = true;
      const url = new URL(location.href); url.searchParams.set('playlist', id); history.replaceState(null, '', url);
    } catch (e) { message(e.message); }
  }
  async function refresh(id = current?.id) {
    catalog = await get(root.dataset.catalog); renderList();
    const target = catalog.playlists.find(p => p.id === Number(id)) || catalog.playlists[0];
    if (target) await open(target.id);
    else { current = null; $('playlist-editor').hidden = true; $('playlist-empty').hidden = false; $('playlist-empty').textContent = 'Create a playlist to start adding music.'; }
  }
  async function reorder(uuid, index) {
    if (!canChange()) return;
    const ids = current.songs.map(s => s.uuid), from = ids.indexOf(uuid);
    if (from < 0 || index < 0 || index >= ids.length || index === from) return;
    ids.splice(index, 0, ids.splice(from, 1)[0]);
    if (await post('playlist-reorder', {id: current.id, revision: current.revision, songs: ids})) await refresh();
  }
  async function remove(ids) { if (canChange() && await post('playlist-remove', {id: current.id, songs: ids})) await refresh(); }
  $('playlist-new').addEventListener('click', async () => {
    if (!canChange()) return;
    const result = await post('create-playlist', {name: 'New playlist', description: '', mode: 'STRAIGHT'});
    if (result) { await refresh(result.playlist_id); form.elements.name.focus(); form.elements.name.select(); }
  });
  form.addEventListener('input', () => setDirty(true));
  form.addEventListener('submit', async e => { e.preventDefault(); if (!current) return; const payload = {id: current.id, revision: current.revision}; for (const key of ['name', 'description', 'mode']) payload[key] = form.elements[key].value; if (await post('edit-playlist', payload)) { setDirty(false); await refresh(); } });
  $('playlist-discard').addEventListener('click', () => { setDirty(false); open(current.id); });
  $('playlist-search').addEventListener('input', renderSongs);
  $('playlist-remove').addEventListener('click', () => remove([...selected]));
  $('playlist-delete').addEventListener('click', async () => { if (!canChange() || !await FreoDialog.confirm({title: `Delete “${current.name}”?`, message: 'Songs will remain in Music.', confirmLabel: 'Delete playlist'})) return; if (await post('delete-playlist', {id: current.id, confirm: current.id})) await refresh(); });
  $('playlist-undo').addEventListener('click', async () => { if (canChange() && undo && await post('undo', {id: undo})) await refresh(); });
  const sourceForm = $('playlist-source-form');
  function sources() { const select = sourceForm.elements.source; select.replaceChildren(); const key = {category: 'categories', artist: 'artists', album: 'albums'}[sourceForm.elements.kind.value]; for (const item of catalog[key]) select.append(new Option(item.name, item.id)); sourceForm.querySelector('button').disabled = !select.options.length; }
  sourceForm.elements.kind.addEventListener('change', sources);
  sourceForm.addEventListener('submit', async e => { e.preventDefault(); if (await post('playlist-source', {id: current.id, kind: sourceForm.elements.kind.value, source: Number(sourceForm.elements.source.value)})) { await refresh(); await search(); } });
  let searchSequence = 0;
  async function search() {
    const sequence = ++searchSequence;
    try {
      const params = new URLSearchParams({q: $('playlist-song-search').elements.q.value, page: searchPage});
      const result = await get(root.dataset.music + '?' + params); if (sequence !== searchSequence) return;
      const list = $('playlist-results'); list.replaceChildren();
      result.songs.forEach(song => { const row = node('div', undefined, 'playlist-result'), added = current.songs.some(s => s.uuid === song.uuid); const add = button(added ? 'Added' : 'Add', async () => { if (await post('assign', {kind: 'playlist', target: current.id, operation: 'add', songs: [song.uuid]})) { await refresh(); await search(); } }, `Add ${song.title} to playlist`); add.disabled = added; row.append(preview(song), node('span', `${song.title} · ${song.artist}`), add); list.append(row); });
      if (!result.songs.length) list.append(node('p', 'No songs found.'));
      $('playlist-results-page').textContent = `${result.page} / ${result.pages}`; $('playlist-results-prev').disabled = result.page <= 1; $('playlist-results-next').disabled = result.page >= result.pages; window.FreoPreview?.sync();
    } catch (e) { message(e.message); }
  }
  $('playlist-add').addEventListener('click', () => { if (!canChange()) return; sources(); searchPage = 1; $('playlist-add-status').textContent = ''; $('playlist-add-dialog').showModal(); search(); });
  $('playlist-song-search').addEventListener('submit', e => { e.preventDefault(); searchPage = 1; search(); });
  $('playlist-results-prev').addEventListener('click', () => { searchPage--; search(); });
  $('playlist-results-next').addEventListener('click', () => { searchPage++; search(); });
  scope.listen(document, 'click', e => { if (dirty && e.target.closest('a[href]')) { e.preventDefault(); e.stopImmediatePropagation(); message('Save or discard your playlist details before leaving.'); } }, true);
  scope.listen(document, 'submit', e => { if (dirty && !root.contains(e.target)) { e.preventDefault(); e.stopImmediatePropagation(); message('Save or discard your playlist details before leaving.'); } }, true);
  scope.listen(window, 'beforeunload', e => { if (dirty) { e.preventDefault(); e.returnValue = ''; } });
  refresh(new URLSearchParams(location.search).get('playlist')).catch(e => message(e.message));
})();
