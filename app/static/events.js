(() => {
  const recurrence = document.getElementById('event-recurrence');
  if (!recurrence) return;
  const form = recurrence.closest('form');
  const content = form.elements.content_identifier;
  function update() {
    const weekly = recurrence.value === 'WEEKLY';
    form.querySelector('[data-event-once]').hidden = weekly;
    form.querySelector('[data-event-weekly]').hidden = !weekly;
    form.elements.local_date.required = !weekly;
    const kind = form.elements.content_type.value;
    Array.from(content.options).forEach(option => {
      const wrong = option.dataset.contentType && option.dataset.contentType !== kind;
      option.hidden = !!wrong;
      option.disabled = !!wrong;
      if (wrong && option.selected) content.value = '';
    });
  }
  recurrence.addEventListener('change', update);
  form.elements.content_type.addEventListener('change', update);
  form.elements.timing_mode.addEventListener('change', () => {
    form.elements.interrupt_policy.value = form.elements.timing_mode.value === 'HARD' ? 'MUSIC_ONLY' : 'NEVER';
  });
  update();
})();
