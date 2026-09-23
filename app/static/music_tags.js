(() => {
  const root = document.getElementById('tag-manager');if (!root) return;
  const status = document.getElementById('tag-status');
  let busy = false;
  async function save(action, payload, done) {
    if (busy) return;
    busy = true;root.querySelectorAll('button').forEach(button => button.disabled = true);
    try {const result = await FreoMusicToggles.request(root.dataset, action, payload);status.textContent = result.message;await done(result);}
    catch (error) {status.textContent = error.message;}
    finally {busy = false;root.querySelectorAll('button').forEach(button => button.disabled = false);}
  }
  root.addEventListener('input',event=>{const form=event.target.closest('[data-tag-id]');if(form)form.querySelector('[type=submit]').textContent='Save changes';});
  root.addEventListener('submit', event => {
    event.preventDefault();const form = event.target, creating = form.id === 'tag-create';
    const payload = {name: form.elements.name.value, description: form.elements.description.value, color: form.elements.color.value};
    if (!creating) payload.id = Number(form.dataset.tagId);
    save(creating ? 'create-tag' : 'edit-tag', payload, async result => {
      if (!creating) {form.querySelector('[type=submit]').textContent='Saved';return;}
      const card = form.cloneNode(true);card.removeAttribute('id');card.querySelector('h2').remove();
      card.dataset.tagId = result.tag_id;
      card.querySelector('button').textContent = 'Save';
      const remove = document.createElement('button');remove.type = 'button';remove.dataset.deleteTag = '';remove.textContent = 'Delete';remove.className='ui-danger';const actions=document.createElement('div');actions.className='tag-actions';actions.append(card.querySelector('button'),remove);card.append(actions);
      document.getElementById('tag-list').append(card);document.getElementById('tags-empty').hidden = true;form.reset();
    });
  });
  root.addEventListener('click', async event => {
    if (!event.target.closest('[data-delete-tag]') || busy) return;
    const form = event.target.closest('form'), id = Number(form.dataset.tagId);
    if (!await FreoDialog.confirm({title: `Delete “${form.elements.name.value}”?`, message: 'This removes the tag from every song. Songs stay in your library.', confirmLabel: 'Delete tag'})) return;
    save('delete-tag', {id, confirm: id}, () => {form.remove();document.getElementById('tags-empty').hidden = !!document.querySelector('[data-tag-id]');});
  });
})();
