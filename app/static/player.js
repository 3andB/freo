(() => {
  const root = document.querySelector('.radio-experience');
  if (!root) return;
  const scope = window.FreoPage, $ = id => document.getElementById(id);
  const base = `/api/stations/${encodeURIComponent(root.dataset.station)}`;
  let audio = $('station-audio');
  const play = $('play-button'), message = $('audio-message');
  const stream = audio.getAttribute('src');
  const zone = root.dataset.timezone, canVote = root.dataset.voting === 'yes';
  const storage = {get(key) {try {return localStorage.getItem(key);} catch {return null;}}, set(key,value) {try {localStorage.setItem(key,value);} catch {}}};
  const el = (tag, text, className) => {const node = document.createElement(tag); if (text !== undefined) node.textContent = text; if (className) node.className = className; return node;};
  const button = (text, handler, className) => {const node = el('button',text,className); node.type='button'; node.addEventListener('click',handler); return node;};
  async function get(path, options={}) {
    const response = await scope.fetch(path, {...options,cache:'no-store'});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Temporarily unavailable. Please try again.');
    return data;
  }
  const time = value => new Intl.DateTimeFormat([], {timeZone:zone,hour:'2-digit',minute:'2-digit'}).format(new Date(value));
  const dateKey = value => {const parts=new Intl.DateTimeFormat('en-CA',{timeZone:zone,year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date(value));const part=type=>parts.find(p=>p.type===type).value;return `${part('year')}-${part('month')}-${part('day')}`;};
  const shift = (day, days) => {const value=new Date(day+'T12:00:00Z');value.setUTCDate(value.getUTCDate()+days);return value.toISOString().slice(0,10);};
  const label=root.querySelector('.vinyl-label'), labelFallback=label.cloneNode(true);
  let artworkKey='';
  let wanted=false, connecting=false, retryAt=0, retries=0, currentKey='', recentKey='', busyRefresh=false;
  let audioAttempt=0, connectingSince=0;
  let audioEvents=new AbortController();
  let currentTitle=root.querySelector('h1').textContent, currentArtist='Live radio';
  let motionReduced=storage.get('freo-motion') === 'reduced' || root.dataset.motion!=='yes';
  function motion() {root.classList.toggle('low-motion',motionReduced);$('motion-button').setAttribute('aria-pressed',String(motionReduced));}
  motion();
  $('motion-button').addEventListener('click',()=>{motionReduced=!motionReduced;storage.set('freo-motion',motionReduced?'reduced':'full');motion();});
  const announcement=root.querySelector('.radio-announcement');
  if (announcement) {
    const key='freo-message-'+announcement.dataset.messageKey;
    announcement.hidden=storage.get(key)==='dismissed';
    $('dismiss-message').addEventListener('click',()=>{announcement.hidden=true;storage.set(key,'dismissed');});
  }
  function syncAudio() {
    const playing=!audio.paused&&!audio.ended&&!connecting;
    root.classList.toggle('is-playing',playing);
    play.textContent=wanted?'Ⅱ':'▶';play.setAttribute('aria-label',wanted?'Pause live stream':'Play live stream');
    if ('mediaSession' in navigator) navigator.mediaSession.playbackState=playing?'playing':'paused';
  }
  async function start(retry=false) {
    const attempt=++audioAttempt;
    retryAt=0;
    if(!retry)retries=0;
    connectingSince=Date.now();
    wanted=true;connecting=true;message.textContent=retry?'Reconnecting…':'Connecting…';syncAudio();
    document.querySelectorAll('audio,video').forEach(other=>{if(other!==audio)other.pause();});
    window.FreoMonitor?.stop();
    // Safari can retain a failed native media resource after load(). A manual
    // play gets a new element within the gesture; automatic retries retain the
    // element's playback permission. Neither path reuses a cached stream URL.
    if(!retry){
      const previous=audio;
      audioEvents.abort();
      audio=document.createElement('audio');
      audio.id='station-audio';audio.preload='none';audio.setAttribute('playsinline','');
      audio.volume=previous.volume;audio.muted=previous.muted;
      previous.pause();previous.removeAttribute('src');previous.load();
      previous.replaceWith(audio);
      bindAudio();
    }
    const source=new URL(stream,location.href);
    source.searchParams.set('_freo',`${Date.now()}-${attempt}`);
    audio.src=source.href;
    // Setting src starts resource selection. Avoid a second load/reset before
    // play(), which can queue an extra abort on WebKit.
    try {await audio.play();}
    catch(error) {
      if(attempt!==audioAttempt || !wanted)return;
      if(error.name==='NotAllowedError'){
        wanted=false;connecting=false;connectingSince=0;
        message.textContent='Tap play to allow audio.';syncAudio();
      }else reconnect();
    }
  }
  function pause() {
    audioAttempt++;wanted=false;retryAt=0;retries=0;connecting=false;connectingSince=0;
    audio.pause();audio.removeAttribute('src');audio.load();
    message.textContent='Paused. Come back anytime.';syncAudio();
  }
  function reconnect() {
    if(!wanted || retryAt)return;
    audioAttempt++;connecting=false;connectingSince=0;
    if(wanted && retries<3){retryAt=Date.now()+Math.pow(2,retries++)*2000;message.textContent='Signal interrupted. Reconnecting shortly…';}
    else {wanted=false;retryAt=0;audio.pause();message.textContent='Signal unavailable. Press play to retry.';}
    syncAudio();
  }
  play.addEventListener('click',()=>wanted?pause():start());
  function buffering(){if(!wanted || retryAt)return;if(!connecting)connectingSince=Date.now();connecting=true;message.textContent='Buffering…';syncAudio();}
  function bindAudio(){
    audioEvents=new AbortController();
    const current=audio;
    const listen=(event,handler)=>current.addEventListener(event,()=>{if(audio===current)handler();},{signal:audioEvents.signal});
    listen('playing',()=>{if(!wanted){audio.pause();return;}connecting=false;connectingSince=0;retryAt=0;retries=0;message.textContent='You’re listening live.';syncAudio();});
    listen('waiting',buffering);
    listen('stalled',()=>{if(audio.readyState<3)buffering();});
    listen('pause',()=>{if(wanted && audio.paused && !connecting && !retryAt)pause();});
    listen('error',()=>{if(audio.error)reconnect();});
    listen('ended',()=>{if(audio.ended)reconnect();});
  }
  bindAudio();
  scope.interval(()=>{
    if(wanted && connecting && Date.now()-connectingSince>=15000)reconnect();
    if(retryAt && Date.now()>=retryAt){retryAt=0;start(true);}
  },1000);
  audio.volume=.8;
  $('volume').addEventListener('input',event=>{audio.volume=Number(event.target.value)/100;audio.muted=false;$('mute-button').setAttribute('aria-pressed','false');$('mute-button').setAttribute('aria-label','Mute');});
  $('mute-button').addEventListener('click',()=>{audio.muted=!audio.muted;$('mute-button').setAttribute('aria-pressed',String(audio.muted));$('mute-button').setAttribute('aria-label',audio.muted?'Unmute':'Mute');});
  $('share-button').addEventListener('click',async()=>{try{if(navigator.share)await navigator.share({title:root.querySelector('h1').textContent,url:location.href});else{await navigator.clipboard.writeText(location.href);$('share-button').textContent='Link copied';}}catch(error){if(error.name!=='AbortError')$('share-button').textContent='Share this page’s URL';}});
  scope.listen(document,'visibilitychange',()=>root.classList.toggle('tab-hidden',document.hidden));
  if ('mediaSession' in navigator) {
    try {navigator.mediaSession.setActionHandler('play',()=>start());navigator.mediaSession.setActionHandler('pause',pause);}catch{}
    scope.cleanup(()=>{navigator.mediaSession.setActionHandler('play',null);navigator.mediaSession.setActionHandler('pause',null);navigator.mediaSession.metadata=null;});
  }
  const sentinel=el('div');$('radio-transport').before(sentinel);
  const sticky=new IntersectionObserver(entries=>{const entry=entries[0];$('radio-transport').classList.toggle('transport-sticky',!entry.isIntersecting&&matchMedia('(max-width:650px)').matches);});
  sticky.observe(sentinel);scope.cleanup(()=>{sticky.disconnect();audioEvents.abort();pause();});

  // A feedback dialog owns its captured song, even if the live song changes.
  const dialog=$('feedback-dialog');let captured=null,feedback=null,feedbackBusy=false,feedbackGeneration=0;
  function feedbackControls(disabled){dialog?.querySelectorAll('[data-vote],#feedback-save').forEach(node=>node.disabled=disabled);}
  function showVote(){if(!feedback)return;dialog.querySelectorAll('[data-vote]').forEach(node=>node.setAttribute('aria-pressed',String(Number(node.dataset.vote)===feedback.vote.value)));const totals=feedback.totals;$('feedback-totals').textContent=totals?`${totals.up} up · ${totals.down} down · ${totals.approval===null?'No votes yet':totals.approval+'% approval'}`:'';}
  async function submitVote(value,comment) {
    if(feedbackBusy||!feedback||!captured)return;
    feedbackBusy=true;feedbackControls(true);const generation=feedbackGeneration;
    try {
      const data=await get(`${base}/feedback/${captured.decision_id}`,{method:'POST',headers:{'Content-Type':'application/json','X-Listener-CSRF':feedback.csrf},body:JSON.stringify({value,revision:feedback.vote.revision,...(comment!==undefined?{comment}:{})})});
      if(generation!==feedbackGeneration)return;
      feedback=data;showVote();$('feedback-status').textContent=value===0?'Vote removed.':'Thanks — your feedback is saved.';
    } catch(error) {if(generation===feedbackGeneration)$('feedback-status').textContent=error.message;}
    finally {if(generation===feedbackGeneration){feedbackBusy=false;feedbackControls(false);}}
  }
  async function openFeedback(song,initialValue) {
    if(!dialog||dialog.open)return;
    captured={...song};feedback=null;feedbackBusy=true;const generation=++feedbackGeneration;
    $('feedback-song').textContent=`${song.title} — ${song.artist}`;$('feedback-status').textContent='Loading your feedback…';$('feedback-totals').textContent='';if($('feedback-comment'))$('feedback-comment').value='';feedbackControls(true);dialog.showModal();
    try {
      const data=await get(`${base}/feedback/${song.decision_id}`);
      if(generation!==feedbackGeneration)return;
      feedback=data;feedbackBusy=false;feedbackControls(false);showVote();if($('feedback-comment'))$('feedback-comment').value=data.vote.comment;
      $('feedback-status').textContent='Choose a vote. You can change it anytime.';
      if(initialValue!==undefined)await submitVote(initialValue);
    }catch(error){if(generation===feedbackGeneration)$('feedback-status').textContent=error.message;}
  }
  if(dialog){
    dialog.querySelector('.feedback-close').addEventListener('click',()=>dialog.close());
    dialog.addEventListener('close',()=>{feedbackGeneration++;feedbackBusy=false;captured=null;feedback=null;});
    dialog.querySelectorAll('[data-vote]').forEach(node=>node.addEventListener('click',()=>submitVote(Number(node.dataset.vote))));
    $('feedback-form').addEventListener('submit',event=>{event.preventDefault();if(feedback)submitVote(feedback.vote.value,$('feedback-comment')?.value);});
  }
  function renderCurrent(rows,fresh){
    const key=JSON.stringify([rows,fresh]);if(key===currentKey)return;currentKey=key;
    const song=rows[0];
    $('copyright-identification').hidden=!(fresh && song?.freo_track_id);
    $('freo-track-id').textContent=song?.freo_track_id?`FREO TRACK · ${song.freo_track_id}`:'';
    $('copyright-report').href=(fresh && song?.report_url)||$('copyright-report').dataset.fallbackUrl;
    $('playing-label').textContent=song?'NOW ON AIR':fresh?'LIVE STATION':'WAITING FOR LIVE METADATA';
    $('playing-heading').textContent=song?.title||root.querySelector('h1').textContent;
    $('playing-artist').textContent=song?.artist||'Keep listening. We’ll bring you the details.';
    $('playing-detail').textContent=rows.length>1?`Also on air: ${rows.slice(1).map(row=>row.title).join(' · ')}`:song?'Live stream timing may vary slightly on your device.':fresh?'No confirmed song is currently on air.':'Recent plays are available below.';
    currentTitle=song?.title||root.querySelector('h1').textContent;currentArtist=song?.artist||'Live radio';
    if((song?.artwork||'')!==artworkKey){
      artworkKey=song?.artwork||'';label.replaceChildren(...[...labelFallback.childNodes].map(node=>node.cloneNode(true)));
      if(artworkKey){const img=el('img');img.alt='';img.src=artworkKey;img.addEventListener('load',()=>{if(img.src.endsWith(artworkKey)&&artworkKey){label.replaceChildren(img,el('i'));}},{once:true});}
    }
    if('mediaSession' in navigator && 'MediaMetadata' in window) navigator.mediaSession.metadata=new MediaMetadata({title:currentTitle,artist:currentArtist,album:root.querySelector('h1').textContent});
    const controls=$('current-feedback');controls.replaceChildren();
    if(canVote)for(const row of rows.filter(row=>row.votable)){
      controls.append(button(rows.length>1?`↑ ${row.title}`:'↑ Love it',()=>openFeedback(row,1)),button(rows.length>1?`↓ ${row.title}`:'↓ Not for me',()=>openFeedback(row,-1)));
    }
  }
  function renderRecent(rows){
    const key=JSON.stringify(rows);if(key===recentKey)return;recentKey=key;
    const list=$('recent-history');list.replaceChildren();
    if(!rows.length){list.append(el('li','The first play is still ahead.'));return;}
    for(const song of rows){const item=el('li'),copy=el('div',undefined,'recent-copy');copy.append(el('strong',song.title),el('span',song.artist));const when=el('time',time(song.started_at));when.dateTime=song.started_at;item.append(copy,when);if(canVote&&song.votable)item.append(button('Vote',()=>openFeedback(song),'recent-vote'));list.append(item);}
  }
  async function refresh(){
    if(busyRefresh)return;busyRefresh=true;
    try{const data=await get(`${base}/player`);renderCurrent(data.current,data.fresh);renderRecent(data.recent);$('station-clock').textContent=data.program;$('next-program').textContent=data.next_program?`Scheduled next · ${data.next_program.title} · ${new Intl.DateTimeFormat([],{timeZone:zone,month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'}).format(new Date(data.next_program.start))}`:'';$('station-time').textContent=new Intl.DateTimeFormat([],{timeZone:zone,weekday:'long',hour:'2-digit',minute:'2-digit'}).format(new Date())+' · '+zone;const online=data.stream_online;$('stream-status').textContent=online===true?'Broadcast live':online===false?'Signal offline':'Signal unconfirmed';$('stream-status').classList.toggle('online',online===true);}
    catch{renderCurrent([],false);$('stream-status').textContent='Signal unconfirmed';$('stream-status').classList.remove('online');}
    finally{busyRefresh=false;}
  }
  refresh();scope.interval(()=>{if(!document.hidden)refresh();},5000);

  // Calendar controls only update their own region; the audio element survives.
  let view=root.dataset.view, scheduleGeneration=0;
  const dateInput=$('schedule-date');
  const length=()=>view==='day'?1:view==='week'?7:new Date(Number(dateInput.value.slice(0,4)),Number(dateInput.value.slice(5,7)),0).getDate();
  function today(){return dateKey(new Date());}
  function programNode(entry,day){const node=el('article',undefined,'schedule-program');node.classList.toggle('is-current',new Date(entry.start)<=new Date()&&new Date(entry.end)>new Date());node.append(el('time',`${dateKey(entry.start)<day?'00:00':time(entry.start)} – ${dateKey(entry.end)>day?'24:00':time(entry.end)}`),el('strong',entry.title));if(entry.description)node.append(el('p',entry.description));return node;}
  async function loadSchedule(){
    if(!dateInput?.value)return;const generation=++scheduleGeneration;
    if(view==='month')dateInput.value=dateInput.value.slice(0,8)+'01';
    root.querySelectorAll('[data-schedule-view]').forEach(node=>node.setAttribute('aria-pressed',String(node.dataset.scheduleView===view)));
    $('schedule-status').textContent='Loading the lineup…';
    try{
      const start=dateInput.value, days=length();const data=await get(`${base}/public-schedule?start=${start}&days=${days}`);if(generation!==scheduleGeneration)return;
      const host=$('schedule-entries');host.replaceChildren();host.classList.toggle('schedule-agenda',view==='day'||(view==='week'&&matchMedia('(max-width:650px)').matches));
      const grid=el('div',undefined,'schedule-days');
      for(let offset=0;offset<days;offset++){
        const day=shift(start,offset);
        const rows=data.entries.filter(entry=>dateKey(entry.start)<=day && (dateKey(entry.end)>day || (dateKey(entry.end)===day && new Intl.DateTimeFormat('en-GB',{timeZone:zone,hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(new Date(entry.end))!=='00:00')));
        const title=new Intl.DateTimeFormat([],{weekday:'short',month:'short',day:'numeric',timeZone:'UTC'}).format(new Date(day+'T12:00:00Z'));
        if(view==='month'){
          const cell=button('',()=>{view='day';dateInput.value=day;loadSchedule();},'schedule-day-button');cell.append(el('b',title),el('small',rows.length?rows[0].title:'No published listings'),el('small',rows.length?`${rows.length} program${rows.length===1?'':'s'}`:''));grid.append(cell);
        }else{const cell=el('section',undefined,'schedule-day');cell.append(el('h3',title));const programs=el('div');for(const entry of rows)programs.append(programNode(entry,day));if(!rows.length)programs.append(el('p','No published listings.'));cell.append(programs);grid.append(cell);}
      }
      host.append(grid);$('schedule-status').textContent=data.revision?'Published lineup · times shown in '+zone:'The station hasn’t published its schedule yet.';
    }catch(error){if(generation===scheduleGeneration)$('schedule-status').textContent=error.message;}
  }
  if(dateInput){dateInput.value=today();root.querySelectorAll('[data-schedule-view]').forEach(node=>node.addEventListener('click',()=>{view=node.dataset.scheduleView;loadSchedule();}));dateInput.addEventListener('change',loadSchedule);$('schedule-today').addEventListener('click',()=>{dateInput.value=today();loadSchedule();});for(const [id,direction] of [['schedule-previous',-1],['schedule-next',1]])$(id).addEventListener('click',()=>{if(view==='month'){const d=new Date(dateInput.value+'T12:00:00Z');d.setUTCMonth(d.getUTCMonth()+direction);dateInput.value=d.toISOString().slice(0,10);}else dateInput.value=shift(dateInput.value,direction*length());loadSchedule();});loadSchedule();}
})();
