(() => {
  const scope = window.FreoPage;
  let queue = Promise.resolve(), pending = 0;
  const states = new WeakMap();
  const run = task => {
    const result = queue.then(task);
    queue = result.catch(() => {});
    return result;
  };
  async function request(config, action, payload) {
    return run(async () => {
      const body = new FormData();
      body.set('csrf', config.csrf);
      body.set('data', JSON.stringify(payload));
      const response = await scope.fetch(config.actions.replace('ACTION', action), {
        method: 'POST', body, headers: {Accept: 'application/json'}
      });
      if (!response.headers.get('content-type')?.includes('application/json')) throw Error('Unable to save. Please check your connection and sign-in.');
      const result = await response.json();
      if (!response.ok) throw Error(result.message || 'Unable to save. Try again.');
      return result;
    });
  }
  function paint(button, assigned) {
    button.setAttribute('aria-pressed', String(assigned));
    button.querySelector('.toggle-check').textContent = assigned ? '✓' : '+';
  }
  scope.listen(document, 'click', async event => {
    const button = event.target.closest('[data-music-toggle]');
    if (!button) return;
    const group = button.closest('.music-toggles');
    let state = states.get(button);
    if (!state) {
      state = {confirmed: button.getAttribute('aria-pressed') === 'true', sequence: 0};
      states.set(button, state);
    }
    const assigned = button.getAttribute('aria-pressed') !== 'true', sequence = ++state.sequence;
    const payload = {kind: button.dataset.kind, target: Number(button.dataset.target), songs: [group.dataset.song], operation: assigned ? 'add' : 'remove'};
    paint(button, assigned);
    button.setAttribute('aria-busy', 'true');
    const status = group.querySelector('[role=status]');
    status.textContent = 'Saving…';
    pending++;
    document.dispatchEvent(new CustomEvent('music-toggle-start'));
    try {
      await request(group.dataset, 'assign', payload);
      const before = state.confirmed;
      state.confirmed = assigned;
      document.dispatchEvent(new CustomEvent('music-toggle-saved', {detail: {...payload, assigned, before}}));
      if (sequence === state.sequence) status.textContent = 'Saved';
    } catch (error) {
      if (sequence === state.sequence) paint(button, state.confirmed);
      status.textContent = error.message;
    } finally {
      pending--;
      if (sequence === state.sequence) button.removeAttribute('aria-busy');
    }
  });
  function create(song, catalog, config) {
    const group = document.createElement('div');
    group.className = 'music-toggles';
    Object.assign(group.dataset, {song: song.uuid, actions: config.actions, csrf: config.csrf});
    for (const [kind, items, ids] of [['tag', catalog.tags, song.tags], ['category', catalog.categories, song.categories]]) {
      const line = document.createElement('div');line.className = 'music-toggle-group';line.setAttribute('role', 'group');
      const label = kind === 'tag' ? 'Tags' : 'Categories';line.setAttribute('aria-label', label);
      const heading = document.createElement('small');heading.textContent = label;line.append(heading);
      for (const item of items) {
        const button = document.createElement('button');button.type = 'button';button.className = 'music-toggle';
        Object.assign(button.dataset, {musicToggle: '', kind, target: item.id});
        button.setAttribute('aria-label', `${item.name} for ${song.title}`);
        button.title = [item.description, item.enabled === false ? 'Disabled in programming' : ''].filter(Boolean).join(' · ');
        if (item.description) {button.dataset.description = item.description;button.setAttribute('aria-description', item.description);}
        const check = document.createElement('span');check.className = 'toggle-check';check.setAttribute('aria-hidden', 'true');
        button.append(check, document.createTextNode(item.name));paint(button, ids.includes(item.id));line.append(button);
      }
      if (!items.length) {const empty = document.createElement('span');empty.className = 'room-hint';empty.textContent = `No ${label.toLowerCase()} yet`;line.append(empty);}
      group.append(line);
    }
    const status = document.createElement('small');status.setAttribute('role', 'status');status.className = 'toggle-status';group.append(status);
    return group;
  }
  window.FreoMusicToggles = {create, request, get pending() {return pending > 0;}};
})();
