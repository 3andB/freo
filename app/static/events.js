(() => {
  const recurrence = document.getElementById('event-recurrence'); if (!recurrence) return;
  const form = recurrence.closest('form'), browser = form.querySelector('.event-audio-browser');
  const $ = id => document.getElementById(id), fields = form.elements;
  let page = 1, within = '', timer, controller, audio;
  FreoPage.cleanup(() => {clearTimeout(timer);controller?.abort();audio?.pause();});
  function update() {
    const kind=recurrence.value;
    for(const [selector,show] of [['[data-event-once]',kind==='ONE_TIME'],['[data-event-days]',['WEEKLY','HOURLY','QUARTER_HOUR'].includes(kind)],['[data-event-hours]',['WEEKLY','HOURLY','QUARTER_HOUR'].includes(kind)],['[data-weekly-hourly]',kind==='WEEKLY'],['[data-event-month]',kind==='MONTHLY'],['[data-event-range]',kind!=='ONE_TIME'],['[data-quarter-help]',kind==='QUARTER_HOUR'],['[data-playlist-playback]',fields.content_type.value==='PLAYLIST']])form.querySelector(selector).hidden=!show;
    fields.local_date.required=kind==='ONE_TIME';
  }
  function button(text,fn){const b=document.createElement('button');b.type='button';b.textContent=text;b.onclick=fn;return b;}
  async function load(reset=true){
    if(reset)page=1;controller?.abort();controller=new AbortController();
    const params=new URLSearchParams({kind:$('event-filter').value,q:$('event-audio-search').value,page});if(within)params.set('playlist',within);
    const results=$('event-audio-results');results.replaceChildren();
    try{
      const response=await FreoPage.fetch(browser.dataset.sourcesUrl+'?'+params,{signal:controller.signal});const data=await response.json();if(!response.ok)throw Error(data.error);
      for(const item of data.items){
        const row=document.createElement('article');row.className='event-audio-result';
        const choose=button(item.name,()=>{fields.content_type.value=item.kind;fields.content_identifier.value=item.identifier;$('event-audio-selected').textContent=`Selected: ${item.name} · ${item.duration}s`;if(item.kind==='PLAYLIST')fields.playlist_playback.value=item.purpose==='COMMERCIALS'?'ALL':'ONE';update();});choose.disabled=!item.playable;
        const meta=document.createElement('small');meta.textContent=[item.purpose,item.subtype,item.artist,item.cart_code,item.count!==undefined?`${item.count} items`:null,`${item.duration}s`,!item.playable?'Unavailable':null].filter(Boolean).join(' · ');
        row.append(choose,meta);
        if(item.kind==='PLAYLIST')row.append(button('Search within',()=>{within=item.identifier;$('event-filter').value='ALL';$('event-all-playlists').hidden=false;load();}));
        if(item.audition)row.append(button('Preview',()=>{audio?.pause();audio=new Audio(item.audition);window.FreoMonitor?.stop();audio.play().catch(()=>{$('event-audio-selected').textContent='Preview unavailable';});}));
        results.append(row);
      }
      if(!data.items.length)results.textContent='No matching audio. Try another search or filter.';
      $('event-audio-prev').hidden=page<=1;$('event-audio-more').hidden=!data.more;
    }catch(error){if(error.name!=='AbortError')results.textContent='Unable to load audio. Change the search to retry.';}
  }
  $('event-audio-search').oninput=()=>{clearTimeout(timer);timer=setTimeout(()=>load(),200);};
  $('event-filter').onchange=()=>{within='';$('event-all-playlists').hidden=true;load();};
  $('event-all-playlists').onclick=()=>{within='';$('event-all-playlists').hidden=true;load();};
  $('event-audio-prev').onclick=()=>{page--;load(false);};$('event-audio-more').onclick=()=>{page++;load(false);};
  recurrence.onchange=update;
  $('event-preview').onclick=async()=>{
    try{const params=new URLSearchParams(new FormData(form));params.delete('csrf');const response=await FreoPage.fetch(browser.dataset.previewUrl+'?'+params);const data=await response.json();if(!response.ok)throw Error(data.error);$('event-summary').textContent=data.summary;$('event-next-runs').replaceChildren(...data.times.map(text=>{const li=document.createElement('li');li.textContent=text;return li;}));}
    catch(error){$('event-summary').textContent=error.message;}
  };
  form.addEventListener('submit',event=>{if(!fields.content_identifier.value){event.preventDefault();$('event-audio-selected').textContent='Choose audio before saving.';$('event-audio-search').focus();}});
  update();load();
})();
