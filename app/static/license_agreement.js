(() => {
  const dialog = document.getElementById('license-agreement');
  if (!dialog) return;
  const scope = window.FreoPage;
  const form = dialog.querySelector('#license-accept-form');
  const close = dialog.querySelector('[data-license-close]');
  const error = dialog.querySelector('[data-license-error]');
  const heading = dialog.querySelector('h2');
  const required = () => dialog.dataset.required === 'true';
  const open = () => {if (dialog.open) dialog.close(); dialog.showModal(); heading.focus();};
  scope.listen(dialog, 'cancel', event => {if (required()) event.preventDefault();});
  scope.listen(dialog, 'keydown', event => {
    if (required() && event.key === 'Escape') event.preventDefault();
  });
  scope.listen(close, 'click', () => dialog.close());
  document.querySelectorAll('[data-license-open]').forEach(button => scope.listen(button, 'click', open));
  scope.listen(form, 'submit', async event => {
    event.preventDefault();
    if (!form.reportValidity()) return;
    const button = form.querySelector('button[type="submit"]');
    if (button.disabled) return;
    button.disabled = true;
    error.hidden = true;
    try {
      const response = await scope.fetch(form.action, {
        method: 'POST', body: new FormData(form), headers: {Accept: 'application/json'},
        signal: AbortSignal.any([scope.signal, AbortSignal.timeout(15000)])
      });
      if (!response.ok || !(await response.json()).accepted) throw new Error('Acceptance failed');
      dialog.dataset.required = 'false';
      dialog.setAttribute('closedby', 'closerequest');
      form.hidden = true;
      dialog.querySelector('[data-license-decline]').hidden = true;
      close.hidden = false;
      document.dispatchEvent(new CustomEvent('freo:form-saved', {detail: {form}}));
      dialog.close();
    } catch (_) {
      error.textContent = 'Your acceptance could not be saved. Check your connection and try again.';
      error.hidden = false;
    } finally {button.disabled = false;}
  });
  if (required()) open();
})();
