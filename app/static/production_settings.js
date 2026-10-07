(() => {
  const message = document.getElementById('production-message');
  async function submit(url, data) {
    const response = await fetch(url, {method:'POST', body:data, headers:{Accept:'application/json'}});
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Settings could not be saved.');
    return result;
  }
  document.querySelectorAll('.provider-form').forEach(form => form.addEventListener('submit', async event => {
    event.preventDefault();
    if (form.getAttribute('aria-busy') === 'true') return;
    const action = event.submitter?.value || 'save';
    const data = new FormData(form); data.set('action', action);
    const feedback = form.querySelector('[data-provider-message]');
    const buttons = Array.from(form.querySelectorAll('button'));
    form.querySelector('[name=key]').value = '';
    form.setAttribute('aria-busy', 'true');
    buttons.forEach(button => { button.disabled = true; });
    feedback.classList.remove('is-error');
    feedback.textContent = action === 'test' ? 'Testing saved connection…' : 'Saving settings…';
    try {
      const result = await submit(form.dataset.url, data);
      feedback.textContent = result.message;
      if (action !== 'test') {
        form.elements.revision.value = result.revision;
        const badge = form.closest('.ops-provider').querySelector('.ops-badge');
        badge.textContent = result.configured ? 'Configured' : 'Not configured';
        badge.classList.toggle('is-ready', result.configured);
      }
    } catch (error) {
      feedback.classList.add('is-error');
      feedback.textContent = error.message;
    } finally {
      form.removeAttribute('aria-busy');
      buttons.forEach(button => { button.disabled = false; });
    }
  }));
  const form = document.getElementById('station-production-settings');
  if (!form) return;
  form.addEventListener('submit', async event => {
    event.preventDefault();
    const values = {revision:Number(form.dataset.revision),enabled:form.elements.enabled.checked,
      script_provider:form.elements.script_provider.value,voice_id:form.elements.voice_id.value,model_id:form.elements.model_id.value,
      grants:Array.from(form.querySelectorAll('[data-user-id]')).map(row => ({user_id:Number(row.dataset.userId),
        voice_tracking:row.querySelector('[name=voice_tracking]').checked,ai_generation:row.querySelector('[name=ai_generation]').checked,
        playlists:Array.from(row.querySelectorAll('[name=playlist]:checked')).map(x => Number(x.value))}))};
    const data = new FormData();data.set('csrf',form.dataset.csrf);data.set('data',JSON.stringify(values));
    try { await submit(location.pathname,data);location.reload(); } catch (error) { message.textContent=error.message; }
  });
})();
