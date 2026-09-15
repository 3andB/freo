(() => {
  const scope = window.FreoPage;
  const root = document.getElementById('dj-booth');
  if (!root) return;
  let state = null;
  const text = (id, value) => { const node=document.getElementById(id); if(node) node.textContent=value; };
  const nonce = () => crypto.randomUUID();
  const notice = (message, error=false) => {
    const node=document.getElementById('booth-notice');
    node.hidden=false; node.textContent=message; node.classList.toggle('error',error);
  };
  let busy=false;
  const post = async (action, data={}) => {
    if(busy) return false;
    busy=true; root.setAttribute('aria-busy','true'); notice('Working…');
    try {
      const body=new FormData(); body.set('csrf',root.dataset.csrf);
      Object.entries(data).forEach(([key,value])=>body.set(key,value ?? ''));
      const response=await scope.fetch(root.dataset.actionBase.replace('ACTION',action),{
        method:'POST',body,credentials:'same-origin',headers:{Accept:'application/json'}
      });
      if(!response.headers.get('content-type')?.includes('application/json'))
        throw new Error(response.status===400 ? 'Your session token expired. Refresh this page and try again.' : 'Session or server unavailable. Refresh this page and sign in if needed.');
      const result=await response.json();
      if(!response.ok) throw new Error(result.message || 'Control failed. Try again.');
      notice(result.message); await refresh();
      if(action==='assign-cart') await FreoWorkspace.navigate(location.href,{submitted:true});
      return true;
    } catch(error) { notice(error.message || 'Connection lost. Try again.',true); return false; }
    finally {busy=false;root.removeAttribute('aria-busy');}
  };
  const fadeControl=document.getElementById('deck-fade-seconds');
  try {const saved=localStorage.getItem('freo-deck-fade');if(saved!==null&&Number.isFinite(Number(saved))&&Number(saved)>=0&&Number(saved)<=10)fadeControl.value=saved;}catch(_){}
  const updateFade=()=>{text('deck-fade-value',`${Number(fadeControl.value)} s`);try{localStorage.setItem('freo-deck-fade',fadeControl.value);}catch(_){}};
  fadeControl.addEventListener('input',updateFade);updateFade();
  const deckCommand=(deck,operation,identifier='',playOnLoad=false)=>post('deck',{deck,operation,identifier,play_on_load:String(playOnLoad),fade_seconds:fadeControl.value,expected_decision_id:state?.mixer?.[deck.toLowerCase()]?.decision_id||'',nonce:nonce()});
  const choose = async (id, target) => {
    if(target==='queue')return state?.mode==='AUTO'&&post('queue-track',{identifier:id,nonce:nonce()});
    if(!state?.mixer||state.playout_error){notice('Station connection is unavailable. Try again when the deck reconnects.',true);return false;}
    const deck=target==='A'||target==='air'?'A':'B';
    const playing=!!state.mixer[deck.toLowerCase()]&&!!state.mixer[deck.toLowerCase()+'_playing'];
    const expected=state.mixer[deck.toLowerCase()]?.decision_id;
    if(playing && !await FreoDialog.confirm({title:`Replace and go live on Deck ${deck}?`,message:'This deck is playing. Replace its song and play the dropped song from the beginning?',confirmLabel:'Replace & go live'}))return false;
    if(state.mixer[deck.toLowerCase()]?.decision_id!==expected){notice('This deck changed. Drop the song again.',true);return false;}
    return deckCommand(deck,'LOAD',id,playing);
  };
  root.querySelectorAll('form[method="post"]').forEach(form=>form.addEventListener('submit',event=>{
    event.preventDefault(); const data=Object.fromEntries(new FormData(form));
    if('nonce' in data)data.nonce=nonce();
    post(new URL(form.action).pathname.split('/').pop(),data);
  }));
  root.querySelectorAll('[data-queue-track]').forEach(button=>button.addEventListener('click',()=>choose(button.closest('.song-card').dataset.id,'queue')));
  root.querySelectorAll('[data-load-deck]').forEach(button=>button.addEventListener('click',()=>choose(button.closest('.song-card').dataset.id,button.dataset.loadDeck)));
  root.querySelectorAll('[data-fire-imaging]').forEach(button=>button.addEventListener('click',()=>post('queue-imaging',{identifier:button.dataset.fireImaging,nonce:nonce()})));

  // One pointer gesture owns the drag, including drags beginning on artwork.
  let drag=null;
  const zones=[...root.querySelectorAll('#now-drop,#cue-drop,.up-next')];
  const cleanDrag=()=>{drag?.ghost?.remove();drag=null;document.body.classList.remove('booth-dragging');zones.forEach(zone=>zone.classList.remove('drop-active'));};
  root.querySelectorAll('.song-card').forEach(card=>{
    card.addEventListener('dragstart',event=>event.preventDefault());
    card.addEventListener('pointerdown',event=>{
      if(event.button!==0||event.target.closest('button,a,input')||!event.isPrimary)return;
      drag={id:card.dataset.id,pointer:event.pointerId,x:event.clientX,y:event.clientY,card,ghost:null};
      card.setPointerCapture(event.pointerId);
    });
  });
  scope.listen(document,'pointermove',event=>{
    if(!drag||event.pointerId!==drag.pointer)return;
    if(!drag.ghost&&Math.hypot(event.clientX-drag.x,event.clientY-drag.y)>7){
      drag.ghost=document.createElement('div');drag.ghost.className='pointer-drag-ghost';
      drag.ghost.textContent=drag.card.querySelector('b').textContent;document.body.append(drag.ghost);document.body.classList.add('booth-dragging');
    }
    if(!drag.ghost)return;
    event.preventDefault();drag.ghost.style.transform=`translate(${event.clientX+14}px,${event.clientY+14}px)`;
    const under=document.elementFromPoint(event.clientX,event.clientY);
    zones.forEach(zone=>zone.classList.toggle('drop-active',zone.contains(under)));
    if(event.clientY<70)window.scrollBy(0,-18);else if(event.clientY>innerHeight-70)window.scrollBy(0,18);
  },{passive:false});
  scope.listen(document,'pointerup',event=>{
    if(!drag||event.pointerId!==drag.pointer)return;
    const item=drag,under=document.elementFromPoint(event.clientX,event.clientY);cleanDrag();
    if(!item.ghost)return;
    if(under?.closest('#cue-drop'))choose(item.id,'cue');
    else if(under?.closest('#now-drop'))choose(item.id,'air');
    else if(state?.mode==='AUTO'&&under?.closest('.up-next'))choose(item.id,'queue');
    else if(under?.closest('[data-role]')){const slot=under.closest('[data-role]');openAssign(slot);assignForm.elements.identifier.add(new Option(item.card.querySelector('b').textContent,item.id,true,true));}
  });
  scope.listen(document,'pointercancel',cleanDrag);scope.listen(window,'blur',cleanDrag);
  scope.listen(document,'keydown',event=>{if(event.key==='Escape')cleanDrag();});

  const dialog=document.getElementById('cart-assign-dialog'), assignForm=document.getElementById('cart-assign-form');
  const openAssign=slot=>{
    assignForm.elements.role.value=slot.dataset.role;assignForm.elements.position.value=slot.dataset.position;
    for(const [name,key] of [['label','label'],['description','description'],['playback_mode','playbackMode'],['duck_percent','duckPercent']])assignForm.elements[name].value=slot.dataset[key]|| (name==='duck_percent'?'50':name==='playback_mode'?'OVER':'');
    if(slot.dataset.identifier && ![...assignForm.elements.identifier.options].some(option=>option.value===slot.dataset.identifier))assignForm.elements.identifier.add(new Option(slot.querySelector('b').textContent,slot.dataset.identifier));
    assignForm.elements.identifier.value=slot.dataset.identifier || assignForm.elements.identifier.options[0]?.value || '';
    document.getElementById('cart-assign-error').textContent='';updateCartExplanation();dialog.showModal();
  };
  root.querySelectorAll('[data-assign]').forEach(button=>button.addEventListener('click',()=>openAssign(button.closest('[data-role]'))));
  root.querySelectorAll('[data-open-assign]').forEach(button=>button.addEventListener('click',()=>openAssign(button.closest('section').querySelector('[data-role]'))));
  assignForm.addEventListener('submit',async event=>{event.preventDefault();const ok=await post('assign-cart',Object.fromEntries(new FormData(assignForm)));if(ok)dialog.close();else document.getElementById('cart-assign-error').textContent=document.getElementById('booth-notice').textContent;});
  function updateCartExplanation(){const over=assignForm.elements.playback_mode.value==='OVER',reduction=Number(assignForm.elements.duck_percent.value);text('cart-duck-value',`${reduction}%`);document.getElementById('cart-duck-setting').hidden=!over;text('cart-mode-explanation',over?`Music keeps playing at ${100-reduction}% of its previous volume while this cart plays, then returns to normal.`:'The main audio pauses. The cart plays by itself, then the interrupted audio resumes from the same position.');}
  assignForm.elements.playback_mode.addEventListener('change',updateCartExplanation);assignForm.elements.duck_percent.addEventListener('input',updateCartExplanation);
  let cartSearchVersion=0;
  document.getElementById('cart-audio-search').addEventListener('input',async event=>{const version=++cartSearchVersion;try{const response=await scope.fetch(root.dataset.songSearchUrl.replace('song-search','cart-search')+'?q='+encodeURIComponent(event.target.value));if(!response.ok)throw new Error();const items=await response.json();if(version!==cartSearchVersion)return;assignForm.elements.identifier.replaceChildren(...items.map(item=>new Option(item.label,item.uuid)));}catch(_){text('cart-assign-error','Audio search is unavailable. Try again.');}});
  root.querySelectorAll('[data-fire-cart]').forEach(button=>button.addEventListener('click',()=>{const slot=button.closest('[data-role]');post('fire-cart',{role:slot.dataset.role,position:slot.dataset.position,nonce:nonce()});}));
  // Native imaging payloads are separate from the song pointer gesture.
  let imaging=null;
  root.querySelectorAll('[data-kind="imaging"]').forEach(button=>{
    button.addEventListener('dragstart',event=>{imaging=button.dataset.id;event.dataTransfer.setData('text/plain',imaging);});
    button.addEventListener('dragend',()=>{imaging=null;});
  });
  root.querySelectorAll('.hot-cart,.id-cart').forEach(slot=>{
    slot.addEventListener('dragover',event=>{if(imaging)event.preventDefault();});
    slot.addEventListener('drop',event=>{if(!imaging)return;event.preventDefault();post('assign-cart',{identifier:imaging,role:slot.dataset.role,position:slot.dataset.position});});
  });
  const songDialog=document.getElementById('song-picker-dialog'),songSearch=document.getElementById('song-picker-search'),songResults=document.getElementById('song-picker-results');
  let searchTimer,searchVersion=0,pickerTarget='cue';
  const searchSongs=async()=>{
    const version=++searchVersion;songResults.textContent='Searching…';
    try {
      const response=await scope.fetch(`${root.dataset.songSearchUrl}?q=${encodeURIComponent(songSearch.value)}`,{credentials:'same-origin',cache:'no-store'});
      if(!response.ok||!response.headers.get('content-type')?.includes('application/json'))throw new Error('Search unavailable. Refresh and sign in if needed.');
      const songs=await response.json();if(version!==searchVersion)return;songResults.replaceChildren();
      for(const song of songs){
        const button=document.createElement('button');button.type='button';
        for(const [tag,value] of [['b',song.title],['span',song.artist],['small',song.album||'Single']]){const el=document.createElement(tag);el.textContent=value;button.append(el);}
        button.addEventListener('click',async()=>{button.disabled=true;const ok=await choose(song.uuid,pickerTarget);button.disabled=false;if(ok)songDialog.close();else document.getElementById('picker-status').textContent=document.getElementById('booth-notice').textContent;});
        songResults.append(button);
      }
      if(!songs.length)songResults.textContent='No enabled songs found. Imported songs must be reviewed and enabled in Music.';
    }catch(error){if(version===searchVersion)songResults.textContent=error.message;}
  };
  root.querySelectorAll('.cue-picker-button').forEach(button=>button.addEventListener('click',()=>{
    pickerTarget=button.dataset.target||'B';text('song-picker-title',`Load a song on Deck ${pickerTarget}`);text('picker-status','');songDialog.showModal();songSearch.focus();searchSongs();
  }));
  songSearch.addEventListener('input',()=>{++searchVersion;songResults.textContent='Searching…';clearTimeout(searchTimer);searchTimer=setTimeout(searchSongs,180);});
  const meterLevel=rms=>Number.isFinite(rms)&&rms>0?Math.max(0,Math.min(1,(20*Math.log10(rms)+60)/60)):0;
  const AudioCtx=window.AudioContext||window.webkitAudioContext;
  const analyserFor=(audio,leftId,rightId)=>{
    if(!AudioCtx)return null;const context=new AudioCtx(),source=context.createMediaElementSource(audio),split=context.createChannelSplitter(2),left=context.createAnalyser(),right=context.createAnalyser();
    left.fftSize=256;right.fftSize=256;source.connect(split);source.connect(context.destination);split.connect(left,0);split.connect(right,1);
    const ld=new Uint8Array(left.fftSize),rd=new Uint8Array(right.fftSize),level=(a,d)=>{a.getByteTimeDomainData(d);let sum=0;for(const value of d){const x=(value-128)/128;sum+=x*x;}return meterLevel(Math.sqrt(sum/d.length));};
    const tick=()=>{if(!audio.paused){document.getElementById(leftId).value=level(left,ld);document.getElementById(rightId).value=level(right,rd);}else if(FreoMonitor.audio.paused&&document.getElementById('cue-monitor').paused){document.getElementById(leftId).value=0;document.getElementById(rightId).value=0;}scope.frame(tick);};tick();return context;
  };
  const monitor=FreoMonitor.audio,cueMonitor=document.getElementById('cue-monitor');
  let cueContext=null;
  scope.cleanup(()=>cueContext?.close());
  root.querySelectorAll('[data-monitor-toggle]').forEach(button=>button.addEventListener('click',()=>FreoMonitor.toggle()));
  let previewDeck=null;
  const resetPreview=()=>root.querySelectorAll('[data-preview-deck]').forEach(button=>button.textContent='PREVIEW');
  root.querySelectorAll('[data-preview-deck]').forEach(button=>button.addEventListener('click',async()=>{
    const deck=button.dataset.previewDeck,item=state?.mixer?.[deck.toLowerCase()];
    if(!item)return;
    if(previewDeck===deck&&!cueMonitor.paused){cueMonitor.pause();resetPreview();return;}
    try{
      FreoMonitor.stop();resetPreview();previewDeck=deck;
      cueMonitor.src=`${location.pathname.replace(/\/live$/,'/media')}/${encodeURIComponent(item.uuid)}/audition`;
      cueContext ||= analyserFor(cueMonitor,'monitor-left','monitor-right');await cueContext?.resume();await cueMonitor.play();button.textContent='STOP PREVIEW';
    }catch(_){notice('Preview could not start. Check the song audio.',true);}
  }));
  cueMonitor.addEventListener('ended',resetPreview);
  root.querySelectorAll('[data-operation]').forEach(button=>button.addEventListener('click',()=>deckCommand(button.dataset.deck,button.dataset.operation)));

  let programTarget=0,programLevel=0;
  const headerSegments=[...document.querySelectorAll('.header-vu>i')];
  const animateProgram=()=>{programLevel+=(programTarget-programLevel)*.12;headerSegments.forEach((bar,index)=>bar.classList.toggle('lit',index/headerSegments.length<programLevel));document.getElementById('program-left').value=programLevel;document.getElementById('program-right').value=programLevel;if(cueMonitor.paused){const levels=FreoMonitor.levels();document.getElementById('monitor-left').value=meterLevel(levels[0]);document.getElementById('monitor-right').value=meterLevel(levels[1]);}scope.frame(animateProgram);};animateProgram();

  const fillQueue=items=>{const list=document.getElementById('live-queue');list.replaceChildren();if(!items.length){const li=document.createElement('li');li.className='empty-copy';li.textContent='Queue is empty';list.append(li);}items.forEach((item,index)=>{const li=document.createElement('li');li.innerHTML=`<span class="queue-index">${index+1}</span><div><b></b><small></small></div>`;li.querySelector('b').textContent=item.title;li.querySelector('small').textContent=`${item.artist} · ${item.source}`;list.append(li);});};
  let observedAt=Date.now();
  function timing(){
    const b=state?.mixer?.b,ms=(state?.mixer?.b_elapsed||0)*1000;
    const clockB=value=>`${Math.floor(value/60000)}:${String(Math.floor(value/1000)%60).padStart(2,'0')}`;
    text('b-elapsed',clockB(ms));text('b-remaining',b?'-'+clockB(Math.max(0,b.duration_ms-ms)):'—:—');
    document.getElementById('b-progress').style.width=`${b?Math.min(100,ms/b.duration_ms*100):0}%`;
    const current=state?.mode==='DJ_BOOTH'?state?.mixer?.a:state?.current;if(!current?.duration_ms)return;
    const engine=state.mixer;
    const elapsed=engine ? engine.a_elapsed*1000 : Math.max(0,Date.now()-Date.parse(current.started_at));
    const fraction=Math.min(1,elapsed/current.duration_ms),clock=ms=>`${Math.floor(ms/60000)}:${String(Math.floor(ms/1000)%60).padStart(2,'0')}`;
    text('elapsed',clock(elapsed));text('remaining',`-${clock(Math.max(0,current.duration_ms-elapsed))}`);document.getElementById('time-progress').style.width=`${fraction*100}%`;
    for(const id of ['progress-ring']){const ring=document.getElementById(id);if(ring){const circumference=2*Math.PI*parseFloat(ring.getAttribute('r'));ring.style.strokeDasharray=circumference;ring.style.strokeDashoffset=circumference*(1-fraction);}}
  }
  let refreshVersion=0,lastFailedCommand=null;
  async function refresh(){
    const version=++refreshVersion;
    try{
      const response=await scope.fetch(root.dataset.statusUrl,{credentials:'same-origin',cache:'no-store'});
      if(!response.ok)throw new Error();
      const next=await response.json();if(version!==refreshVersion)return;
      if(next.playout_error&&!next.mixer&&state?.mixer)next.mixer=state.mixer;
      state=next;
      root.dataset.mode=state.mode;
      root.className=`dj-booth booth-mode-${state.mode.toLowerCase().replace('_','-')}`;
      text('led-detail',state.mode.replace('_',' '));text('live-mode',state.mode);
      text('live-clock',state.clock||'None');text('auto-clock',state.clock||'No active clock');
      text('live-transition',state.next_transition||'None');text('live-playout',state.playout_error||'Connected');
      text('live-fallback',state.fallback);text('next-event-name',state.next_event?.name||'None');
      const current=state.mode==='DJ_BOOTH' ? state.mixer?.a : (state.current || (state.playout_error ? state.last_known_current : null)), cue=state.mixer?.b;
      const engine=state.mixer,pending=state.deck_command?.status==='pending';
      if(state.deck_command?.status==='failed'&&lastFailedCommand!==state.deck_command.id){
        lastFailedCommand=state.deck_command.id;notice(`Deck ${state.deck_command.deck} could not apply ${state.deck_command.operation.toLowerCase()}. The song or station state changed; review the deck and try again.`,true);
      }
      root.querySelectorAll('.cue-picker-button,[data-load-deck]').forEach(button=>button.disabled=pending||!engine||!!state.playout_error);

      for(const deck of ['A','B']){
        const key=deck.toLowerCase(),item=engine?.[key],playing=!!item&&engine?.[key+'_playing'];
        const panel=document.getElementById(deck==='A'?'now-drop':'cue-drop');
        panel.classList.toggle('mix-live',playing&&!state.playout_error);panel.style.setProperty('--deck-gain',playing?1:0);
        text(`deck-${key}-state`,state.playout_error?'CONNECTION DELAY':!item?'EMPTY':playing?'LIVE':item.started_at?'PAUSED':'READY');
        root.querySelectorAll(`[data-deck="${deck}"][data-operation]`).forEach(button=>{
          const operation=button.dataset.operation;
          button.disabled=pending||!engine||!item||!!state.playout_error||(operation==='PLAY'&&playing)||(['PAUSE','FADE'].includes(operation)&&!playing)||(operation==='REPEAT'&&item?.kind!=='track');
          if(operation==='PLAY')button.textContent=item?.started_at?'RESUME / TAKE AIR':'PLAY / TAKE AIR';
        });
        root.querySelector(`[data-preview-deck="${deck}"]`).disabled=!item||item.kind!=='track';
      }
      root.querySelector('.cue-disc').classList.toggle('playing',!!engine?.b&&engine.b_playing);
      root.querySelectorAll('[data-fire-cart]').forEach(button=>button.disabled=!engine);
      text('morph-kicker',state.playout_error?'CONNECTION DELAY · LAST OBSERVED':'NOW PLAYING');
      root.querySelectorAll('#spinning-disc,.auto-disc .disc').forEach(disc=>disc.classList.toggle('playing',!!current&&(!state.mixer||state.mixer.a_playing)));
      document.querySelector('.onair-deck').classList.toggle('active',!!current);
      text('deck-a-label',current?(state.mixer&&!state.mixer.a_playing?(current.started_at?'PAUSED':'READY'):'A'):'A');text('deck-b-label',state.mixer?.b?(state.mixer.b_playing?'B':(state.mixer.b.started_at?'PAUSED':'READY')):'B');
      programTarget=state.playout_error?0:meterLevel(state.program_rms);
      text('program-meter-label',Number.isFinite(state.program_rms)&&!state.playout_error?'PROGRAM / LIVE':'PROGRAM / NO SIGNAL DATA');
      const onAir=state.current || (state.playout_error?state.last_known_current:null);
      text('morph-text',onAir?.title||(state.playout_error?'Reconnecting to station':'Silence · no live deck')); document.getElementById('morph-text').title=onAir?.title||'';document.querySelector('#live-current h2').title=current?.title||'';document.getElementById('cue-title').title=cue?.title||'';text('morph-artist',onAir?.artist||'');
      document.querySelector('#live-current h2').textContent=current?.title||(state.playout_error?'Reconnecting to station':'No song on air');
      document.querySelector('#live-current p').textContent=current?.artist||'Live broadcast';
      text('now-album',current?.album||'');
      text('fact-category',current?.category||'NO CATEGORY');
      text('fact-bpm',current?.bpm?`${Math.round(current.bpm)} BPM`:'BPM —');text('fact-year',current?.year||'YEAR —');
      text('fact-lufs',Number.isFinite(current?.loudness_lufs)?`${current.loudness_lufs.toFixed(1)} LUFS`:'LUFS —');
      text('queue-count',state.queue.length);fillQueue(state.queue);
      root.querySelectorAll('.current-decision').forEach(input=>input.value=current?.decision_id||'');
      root.querySelectorAll('.current-control button').forEach(button=>button.disabled=!state.current||!!state.playout_error);
      root.querySelectorAll('.mode-button').forEach(button=>button.classList.toggle('active',button.dataset.mode===state.mode));
      document.querySelector('.cue-deck').classList.toggle('cue-empty',!cue);
      text('cue-title',cue?.title||'NOTHING LOADED');text('cue-artist',cue?.artist||'Drop a song here or choose Load Song');
      text('cue-album',cue?.album||'Prepare your next song on this deck');document.getElementById('cue-warning').hidden=!!cue;
      if(previewDeck&&!engine?.[previewDeck.toLowerCase()]&&!cueMonitor.paused){cueMonitor.pause();resetPreview();}
      if(!current){for(const id of ['progress-ring']){const ring=document.getElementById(id);ring.style.strokeDashoffset=2*Math.PI*parseFloat(ring.getAttribute('r'));}text('elapsed','0:00');text('remaining','—:—');document.getElementById('time-progress').style.width='0%';}
      timing();
    }catch(_){
      if(version!==refreshVersion)return;
      text('live-playout','Reconnecting — controls will recover automatically');
      if(state)state={...state,playout_error:'Connection delayed'};
      text('morph-kicker','CONNECTION DELAY · LAST OBSERVED');programTarget=0;
      root.querySelectorAll('[data-operation]').forEach(button=>button.disabled=true);

    }
  }
  scope.interval(timing,500);scope.interval(refresh,2000);refresh();
})();
