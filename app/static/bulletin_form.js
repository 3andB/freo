(() => {
  const form = document.getElementById('bulletin-form');
  if (!form) return;
  const recurrence = form.elements.recurrence_type;
  const update = () => form.querySelectorAll('[data-recurrence]').forEach(label => {
    const visible = label.dataset.recurrence === recurrence.value;
    label.hidden = !visible;
    label.querySelectorAll('input,select').forEach(input => { input.disabled = !visible; });
    if (label.dataset.recurrence === 'ONE_TIME') label.querySelector('input').required = visible;
  });
  recurrence.addEventListener('change', update);
  update();
})();
