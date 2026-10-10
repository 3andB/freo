/* A station's working set persists on the server; this module only edits intent. */
window.FreoCue = {
  create({root, scope, post, choose, notice}) {
    const $ = id => document.getElementById(id), list = $('booth-cue-list');
    const panel = root.querySelector('.cue-panel'), workspace = root.querySelector('.cue-workspace');
    let cue = null, latest = null, signature = '', saving = false, dragging = false, searchVersion = 0, searchTimer;
    let lastObservation = -Infinity;
    function paintActivity() {
      const connected = performance.now() - lastObservation < 5000 && latest?.observation_fresh && !latest.playout_error &&
        latest.desired_state === 'running' && latest.broadcast?.online !== false && latest.mode === 'DJ_BOOTH' && root.dataset.board !== 'LIVE_MIC';
      const playing = connected && cue?.entries.some(song => song.decks.some(deck => deck.playing &&
        latest.current?.decision_id === latest.mixer?.[deck.deck.toLowerCase()]?.decision_id));
      panel.dataset.cueActivity = playing ? 'playing' : connected && cue?.auto_enabled ? 'armed' : 'idle';
    }
    function disconnect() {lastObservation = -Infinity; paintActivity();}
    scope.interval(paintActivity, 500);
    let category = new URL(location.href).searchParams.get('category') || '', offset = 0;
    const time = ms => {const seconds = Math.round((ms || 0) / 1000); return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;};
    const el = (tag, text, cls) => {const node = document.createElement(tag); if (text !== undefined) node.textContent = text; if (cls) node.className = cls; return node;};
    const button = (label, action, title) => {const node = el('button', label); node.type = 'button'; if (action) node.dataset.cueAction = action; if (title) node.setAttribute('aria-label', title); return node;};
    async function edit(operation, data = {}) {
      if (!cue || saving) return false;
      saving = true; $('cue-save-state').textContent = 'Saving…';
      const ok = await post('cue-list', {operation, revision: cue.revision, nonce: FreoUUID(), ...data});
      if (scope.signal.aborted) return false;
      saving = false; $('cue-save-state').textContent = ok ? 'Saved' : 'Not saved · retry';
      return ok;
    }
    function render(state) {
      if (state !== latest) lastObservation = performance.now();
      latest = state;
      if (!state.cue_list) {disconnect(); return;}
      cue = state.cue_list;
      paintActivity();
      $('cue-name').textContent = cue.name; $('cue-name').title = cue.name;
      $('cue-total').textContent = cue.entries.length;
      $('cue-duration').textContent = time(cue.entries.reduce((sum, song) => sum + (song.duration_ms || 0), 0));
      $('cue-auto').setAttribute('aria-pressed', String(cue.auto_enabled));
      $('cue-auto').querySelector('b').textContent = cue.auto_enabled ? 'ON' : 'OFF';
      $('cue-auto').disabled = !!state.playout_error || state.mode !== 'DJ_BOOTH' || (!cue.entries.length && !cue.auto_enabled);
      panel.classList.toggle('auto-cue-on', cue.auto_enabled);
      const next = cue.entries.find(song => song.available && !song.decks.some(deck => deck.playing)) || cue.entries.find(song => song.available);
      $('cue-next').textContent = next ? `NEXT · ${next.title}` : 'Add songs below to build your set';
      $('cue-next').title = $('cue-next').textContent;
      $('cue-help').textContent = cue.auto_enabled ? (cue.message || 'AUTO_CUE armed') : (cue.message || 'Drag to reorder · Finished songs move to the bottom');
      const nextSignature = JSON.stringify([cue.entries, state.playout_error, state.deck_command?.status]);
      if (dragging || signature === nextSignature) return;
      signature = nextSignature;
      const focused = list.contains(document.activeElement) ? {entry: document.activeElement.closest('[data-cue-entry]')?.dataset.cueEntry, action: document.activeElement.dataset.cueAction, deck: document.activeElement.dataset.loadDeck} : null;
      const rows = cue.entries.map((song, index) => {
        const row = el('li', undefined, 'cue-row'); row.dataset.cueEntry = song.id; row.dataset.id = song.uuid || '';
        const handle = button('⠿', 'handle', `Move ${song.title}. Use Alt plus Up or Down to reorder.`); handle.className = 'cue-handle';
        const number = el('span', String(index + 1).padStart(2, '0'), 'cue-number');
        const copy = el('div', undefined, 'cue-song'); const title = el('b', song.title); title.title = song.title;
        const subtitle = el('span', song.artist); subtitle.title = song.artist; copy.append(title, subtitle);
        const status = song.decks.map(deck => `${deck.playing ? 'PLAYING' : 'ON'} ${deck.deck}`).join(' · ') || (!song.available ? 'UNAVAILABLE' : song.id === next?.id ? 'NEXT' : '');
        const length = el('div', undefined, 'cue-length'); length.append(el('small', status), el('span', time(song.duration_ms)));
        row.classList.toggle('is-playing', song.decks.some(deck => deck.playing)); row.classList.toggle('is-unavailable', !song.available);
        const actions = el('div', undefined, 'cue-row-actions');
        for (const deck of ['A', 'B']) {const load = button(`LOAD ${deck}`, null, `Load ${song.title} on Deck ${deck}`); load.dataset.loadDeck = deck; load.disabled = !song.available || !!state.playout_error || state.deck_command?.status === 'pending'; actions.append(load);}
        const remove = button('×', 'remove', `Remove ${song.title} from Cue`); remove.className = 'cue-remove'; actions.append(remove);
        row.append(handle, number, copy, length, actions); return row;
      });
      if (!rows.length) {const empty = el('li', undefined, 'cue-empty-list'); empty.append(el('b', 'Your next great set starts here'), el('span', 'Drop songs here or use + CUE below.')); rows.push(empty);}
      list.replaceChildren(...rows);
      if (focused) {
        const row = [...list.children].find(node => node.dataset.cueEntry === focused.entry);
        const target = row && [...row.querySelectorAll('button')].find(node => focused.action ? node.dataset.cueAction === focused.action : node.dataset.loadDeck === focused.deck);
        target?.focus({preventScroll: true});
      }
    }
    const dialog = $('cue-dialog'), content = $('cue-dialog-content');
    function openDialog(title) {content.replaceChildren(); $('cue-dialog-title').textContent = title; if (!dialog.open) dialog.showModal();}
    function saveDialog(operation = 'save', after) {
      openDialog(operation === 'save-as' ? 'Save Cue as…' : operation === 'rename' ? 'Rename Cue' : 'Save Cue');
      const form = el('form'); const label = el('label', 'Set name'); const input = el('input'); input.name = 'name'; input.required = true; input.maxLength = 120; input.value = cue.name === 'Untitled Cue' ? '' : cue.name; label.append(input);
      const hint = el('p', 'Saves the current order as a named set. Your working Cue keeps autosaving as songs play.');
      const submit = button('Save Cue'); submit.type = 'submit'; const error = el('p'); error.setAttribute('role', 'status');
      form.append(label, hint, error, submit); content.append(form);
      form.addEventListener('submit', async event => {event.preventDefault(); submit.disabled = true; const ok = await edit(operation, {name: input.value}); submit.disabled = false; if (ok) {dialog.close(); after?.();} else error.textContent = 'Could not save. Review the booth message and try again.';});
      input.focus(); input.select();
    }
    async function replace(operation, data) {
      if (cue.dirty) {
        openDialog('Keep your current set?');
        content.append(el('p', 'Save the current order before replacing this Cue? The song on air will keep playing.'));
        const actions = el('div', undefined, 'cue-dialog-actions');
        const save = button('Save first'), discard = button('Discard & continue'), cancel = button('Cancel');
        save.addEventListener('click', () => saveDialog('save', () => edit(operation, {...data, discard: 'true'})));
        discard.addEventListener('click', async () => {if (await edit(operation, {...data, discard: 'true'})) dialog.close();});
        cancel.addEventListener('click', () => dialog.close()); actions.append(save, discard, cancel); content.append(actions); return;
      }
      if (await edit(operation, data)) dialog.close();
    }
    function loadDialog() {
      openDialog('Load a Cue');
      if (!cue.saved.length) {content.append(el('p', 'No saved sets yet. Build a Cue and save it to see it here.')); return;}
      const sets = el('div', undefined, 'cue-saved-sets');
      for (const saved of cue.saved) {const item = button(`${saved.name} · ${saved.count} songs`); item.addEventListener('click', () => replace('load', {saved_id: saved.id})); sets.append(item);}
      content.append(sets);
    }
    scope.listen(panel, 'click', event => {
      const action = event.target.closest('[data-cue-action]')?.dataset.cueAction;
      if (!action || !cue || saving) return;
      if (action === 'remove') edit('remove', {entry_id: event.target.closest('[data-cue-entry]').dataset.cueEntry});
      else if (action === 'new') replace('new', {});
      else if (action === 'load') loadDialog();
      else if (['save', 'save-as', 'rename'].includes(action)) saveDialog(action);
      panel.querySelector('.cue-menu').open = false;
    });
    scope.listen($('cue-auto'), 'click', () => edit('auto', {enabled: String(!cue.auto_enabled)}));
    scope.listen(list, 'keydown', event => {
      if (!event.altKey || !['ArrowUp', 'ArrowDown'].includes(event.key)) return;
      const row = event.target.closest('[data-cue-entry]'); if (!row) return;
      event.preventDefault(); const index = cue.entries.findIndex(song => song.id === row.dataset.cueEntry);
      if (event.key === 'ArrowUp' && index > 0) edit('move', {entry_id: row.dataset.cueEntry, before: cue.entries[index - 1].id});
      if (event.key === 'ArrowDown' && index < cue.entries.length - 1) edit('move', {entry_id: row.dataset.cueEntry, before: cue.entries[index + 2]?.id || ''});
    });
    let resizing = null;
    const divider = $('cue-divider'), storageKey = `freo-cue-split:${location.pathname}`;
    let split = 48;
    try {const value = Number(localStorage.getItem(storageKey)); if (value >= 25 && value <= 70) split = value;} catch (_) {}
    function resize(value) {split = Math.max(25, Math.min(70, value)); workspace.style.setProperty('--cue-split', `${split}%`); divider.setAttribute('aria-valuenow', String(Math.round(split))); try {localStorage.setItem(storageKey, split);} catch (_) {}}
    resize(split);
    scope.listen(divider, 'pointerdown', event => {if (event.button !== 0) return; resizing = {id: event.pointerId, y: event.clientY, split}; divider.setPointerCapture(event.pointerId);});
    scope.listen(divider, 'pointermove', event => {if (resizing?.id === event.pointerId) resize(resizing.split + (event.clientY - resizing.y) / workspace.clientHeight * 100);});
    scope.listen(divider, 'pointerup', () => {resizing = null;}); scope.listen(divider, 'pointercancel', () => {resizing = null;});
    scope.listen(divider, 'keydown', event => {if (['ArrowUp', 'ArrowDown'].includes(event.key)) {event.preventDefault(); resize(split + (event.key === 'ArrowUp' ? -5 : 5));}});

    const search = root.querySelector('.booth-search'), shelf = root.querySelector('.song-shelf'), more = $('song-more');
    function songCard(song) {
      const card = el('article', undefined, 'song-card'); card.dataset.kind = 'track'; card.dataset.id = song.uuid;
      const art = el('div', undefined, 'song-art'); if (song.artwork) {const img = el('img'); img.src = song.artwork; img.alt = ''; img.draggable = false; art.append(img);} else art.textContent = '♫';
      const copy = el('div'); const title = el('b', song.title); title.title = song.title;
      copy.append(title, el('span', song.artist), el('small', `${song.album || 'Single'} · ${time(song.duration_ms)}${song.bpm ? ` · ${Math.round(song.bpm)} BPM` : ''}`));
      const actions = el('div', undefined, 'song-actions'); const add = button('+ CUE', null, `Add ${song.title} to Cue`); add.dataset.addCue = ''; actions.append(add);
      for (const deck of ['A', 'B']) {const load = button(`LOAD ${deck}`); load.dataset.loadDeck = deck; load.disabled = !latest?.mixer || !!latest?.playout_error; actions.append(load);}
      card.append(art, copy, actions); return card;
    }
    async function searchSongs(append = false) {
      const version = ++searchVersion; more.disabled = true;
      const params = new URLSearchParams({q: search.elements.q.value, category, offset: append ? offset : 0, paged: '1'});
      try {
        const response = await scope.fetch(`${root.dataset.songSearchUrl}?${params}`); if (!response.ok) throw new Error('Song search is unavailable. Try again.');
        const result = await response.json(); if (scope.signal.aborted || version !== searchVersion) return;
        const cards = result.songs.map(songCard); if (append) shelf.append(...cards); else {shelf.replaceChildren(...cards); shelf.scrollTop = 0;}
        offset = (append ? offset : 0) + result.songs.length;
        if (!offset) shelf.append(el('p', 'No enabled songs match.', 'empty-copy'));
        more.hidden = !result.has_more;
      } catch (error) {if (version === searchVersion) notice(error.message, true);}
      finally {if (version === searchVersion) more.disabled = false;}
    }
    scope.listen(search, 'submit', event => {event.preventDefault(); clearTimeout(searchTimer); searchSongs();});
    scope.listen(search.elements.q, 'input', () => {++searchVersion; clearTimeout(searchTimer); searchTimer = setTimeout(() => searchSongs(), 180);});
    scope.cleanup(() => {clearTimeout(searchTimer); ++searchVersion;});
    scope.listen(root.querySelector('.category-strip'), 'click', event => {
      const link = event.target.closest('a'); if (!link) return; event.preventDefault();
      category = new URL(link.href).searchParams.get('category') || '';
      root.querySelectorAll('.category-strip a').forEach(item => item.removeAttribute('aria-current')); link.setAttribute('aria-current', 'page'); searchSongs();
    });
    scope.listen(more, 'click', () => searchSongs(true));
    searchSongs();
    return {
      render,
      disconnect,
      add: (identifier, before = '') => edit('add', {identifier, before}),
      move: (entry_id, before = '') => entry_id !== before && edit('move', {entry_id, before}),
      drag(active) {dragging = active; if (!active && latest) render(latest);},
      insertion(y, entryId) {const rows = [...list.querySelectorAll('[data-cue-entry]')].filter(row => row.dataset.cueEntry !== entryId); return rows.find(row => y < row.getBoundingClientRect().top + row.offsetHeight / 2)?.dataset.cueEntry || '';},
      highlight(before) {list.querySelectorAll('.cue-insert-before').forEach(row => row.classList.remove('cue-insert-before')); list.classList.toggle('cue-insert-end', before === ''); if (before) [...list.children].find(row => row.dataset.cueEntry === before)?.classList.add('cue-insert-before');},
      clearHighlight() {list.classList.remove('cue-insert-end'); list.querySelectorAll('.cue-insert-before').forEach(row => row.classList.remove('cue-insert-before'));}
    };
  }
};
