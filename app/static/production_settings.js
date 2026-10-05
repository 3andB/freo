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
    const data = new FormData(form); data.set('action', event.submitter.value);
    form.querySelector('[name=key]').value = '';
    try { const result = await submit(form.dataset.url, data); message.textContent = result.message;
      if (event.submitter.value !== 'test') location.reload();
    } catch (error) { message.textContent = error.message; }
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
