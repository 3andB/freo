(() => {
  const recurrence = document.getElementById('event-recurrence');
  if (!recurrence) return;
  const form = recurrence.closest('form'), browser = form.querySelector('.event-audio-browser');
  const search = document.getElementById('event-audio-search'), results = document.getElementById('event-audio-results');
  const more = document.getElementById('event-audio-more'), selected = document.getElementById('event-audio-selected');
  let page = 1, timer, controller, audio;
  window.FreoPage.cleanup(()=>{clearTimeout(timer);controller?.abort();audio?.pause();});
  function update() {
    const weekly = recurrence.value === 'WEEKLY';
    form.querySelector('[data-event-once]').hidden = weekly;
    form.querySelector('[data-event-weekly]').hidden = !weekly;
    form.querySelector('[data-event-weekly-hours]').hidden = !weekly;
    form.elements.local_date.required = !weekly;
  }
  async function load(append = false) {
    controller?.abort(); controller = new AbortController();
    if (!append) page = 1;
    results.replaceChildren();
    const kind = {TRACK:'song', IMAGING_ASSET:'imaging', EVENT_BLOCK:'sequence'}[form.elements.content_type.value];
    const url = new URL(browser.dataset.sourcesUrl, location.origin);
    url.search = new URLSearchParams({kind, q:search.value, page});
    try {
      const response = await fetch(url, {signal:controller.signal});
      const data = await response.json(); if (!response.ok) throw Error(data.error);
      for (const item of data.items) {
        const button = document.createElement('button'); button.type = 'button'; button.textContent = item.name;
        button.addEventListener('click', () => {form.elements.content_identifier.value = item.identifier; selected.textContent = `Selected: ${item.name}`;});
        const row=document.createElement('div');row.append(button);
        if(item.audition){const preview=document.createElement('button');preview.type='button';preview.textContent='Preview';preview.setAttribute('aria-label','Preview '+item.name);preview.onclick=()=>{audio?.pause();audio=new Audio(item.audition);window.FreoMonitor?.stop();audio.play().catch(()=>{selected.textContent='Audio preview is unavailable.';});};row.append(preview);}
        results.append(row);
      }
      if (!data.items.length && !append) results.textContent = 'No approved audio found. Try another search or content type.';
      more.hidden = !data.more;document.getElementById('event-audio-prev').hidden=page<=1;
    } catch (error) { if (error.name !== 'AbortError') results.textContent = 'Unable to load audio. Change your search to retry.'; }
  }
  recurrence.addEventListener('change', update);
  form.elements.content_type.addEventListener('change', () => {
    form.elements.content_identifier.value = ''; selected.textContent = 'Choose approved audio below'; load();
  });
  search.addEventListener('input', () => {clearTimeout(timer); timer = setTimeout(() => load(), 200);});
  document.getElementById('event-audio-prev').addEventListener('click',()=>{page=Math.max(1,page-1);load(true);});
  more.addEventListener('click', () => {page++; load(true);});
  form.addEventListener('submit', event => {if (!form.elements.content_identifier.value) {event.preventDefault(); selected.textContent = 'Choose audio before saving.'; search.focus();}});
  form.elements.timing_mode.addEventListener('change', () => {
    form.elements.interrupt_policy.value = form.elements.timing_mode.value === 'HARD' ? 'MUSIC_ONLY' : 'NEVER';
  });
  update(); load();
})();
