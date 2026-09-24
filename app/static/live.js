(() => {
  const scope = window.FreoPage;
  const root = document.getElementById('dj-booth');
  if (!root) return;
  const active = () => !scope.signal.aborted && root.isConnected;
  let state = null;
  const pendingLoads=new Map();
  const text = (id, value) => { if(!active())return; const node=document.getElementById(id); if(node) node.textContent=value; };
  const nonce = () => FreoUUID();
  let noticeUntil=0;
  function systemStatus(){
    if(!active())return;
    if(Date.now()<noticeUntil)return;
    const node=document.getElementById('booth-notice');
    const fault=state?.playout_error || (state?.broadcast?.online===false&&state?.desired_state==='running'?'Broadcast stream is offline':null);
    const broadcast=state?.broadcast?.online;
    const listeners=state?.broadcast?.listeners;
    const messages=[broadcast===true?'Broadcast online · Station stream is available':broadcast===false?'Broadcast offline':'Broadcast status unavailable',
      state?.mode==='AUTO'?`Auto · ${state.automation==='RUNNING'?'Following schedule':state.automation?.toLowerCase()||'Checking automation'}`:'DJ mode · '+(state?.mixer?.auto_standby?'Auto is on air; decks are ready':state?.current?'Live playback active':'No live deck'),
      Number.isInteger(listeners)?`${listeners} listener${listeners===1?'':'s'} connected`:'Listener count unavailable'];
    const message=fault || (!state?'Checking station status…':messages[Math.floor(Date.now()/5000)%messages.length]);
    if(node.textContent!==message)node.textContent=message;
    node.classList.toggle('error',!!fault);node.dataset.message='system';
  }
  const notice = (message, error=false) => {
    if(!active())return;
    noticeUntil=Date.now()+15000;
    const node=document.getElementById('booth-notice');
    node.dataset.message='action';node.hidden=false; node.textContent=message; node.classList.toggle('error',error);
  };
  let busy=false,commandRefresh=false;
  const post = async (action, data={}) => {
    if(busy||!active()) return false;
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
      if(!active())return false;
      if(!response.ok) throw new Error(result.message || 'Control failed. Try again.');
      notice(result.message); await refresh(true);
      if(!active())return false;
      if(action==='assign-cart') await FreoWorkspace.navigate(location.href,{submitted:true});
      return true;
    } catch(error) { if(!active())return false; notice(error.message || 'Connection lost. Try again.',true); if(action==='cue-list')await refresh(true); return false; }
    finally {busy=false;root.removeAttribute('aria-busy');}
  };
  const fadeControl=document.getElementById('deck-fade-seconds');
  try {const saved=localStorage.getItem('freo-deck-fade');if(saved!==null&&Number.isFinite(Number(saved))&&Number(saved)>=0&&Number(saved)<=10)fadeControl.value=saved;}catch(_){}
  const updateFade=()=>{text('deck-fade-value',`${Number(fadeControl.value)} s`);try{localStorage.setItem('freo-deck-fade',fadeControl.value);}catch(_){}};
  fadeControl.addEventListener('input',updateFade);updateFade();
  const deckCommand=(deck,operation,identifier='',playOnLoad=false,cueEntryId='')=>post('deck',{deck,operation,identifier,cue_entry_id:cueEntryId,play_on_load:String(playOnLoad),fade_seconds:fadeControl.value,expected_decision_id:state?.mixer?.[deck.toLowerCase()]?.decision_id||'',nonce:nonce()});
  const choose = async (id, target, cueEntryId='') => {
    if(target==='queue')return state?.mode==='AUTO'&&post('queue-track',{identifier:id,nonce:nonce()});
    if(!state?.mixer||state.playout_error){notice('Station connection is unavailable. Try again when the deck reconnects.',true);return false;}
    const deck=target==='A'||target==='air'?'A':'B';
    const playing=!!state.mixer[deck.toLowerCase()]&&!!state.mixer[deck.toLowerCase()+'_playing'];
    const expected=state.mixer[deck.toLowerCase()]?.decision_id;
    if(playing && !await FreoDialog.confirm({title:`Replace and go live on Deck ${deck}?`,message:'This deck is playing. Replace its song and play the dropped song from the beginning?',confirmLabel:'Replace & go live'}))return false;
    if(!active())return false;
    if(state.mixer[deck.toLowerCase()]?.decision_id!==expected){notice('This deck changed. Drop the song again.',true);return false;}
    if(busy||state.deck_command?.status==='pending')return false;
    pendingLoads.set(deck.toLowerCase(),{expected,uuid:id});
    paintLoading(deck.toLowerCase());timing();
    const loaded=await deckCommand(deck,'LOAD',id,playing,cueEntryId);
    if(!loaded){pendingLoads.delete(deck.toLowerCase());await refresh();}
    return loaded;
  };
  const cueUI=window.FreoCue.create({root,scope,post,choose,notice});
  root.querySelectorAll('form[method="post"]').forEach(form=>form.addEventListener('submit',async event=>{
    event.preventDefault(); const data=Object.fromEntries(new FormData(form));
    if(data.mode&&root.dataset.modeChanging==='true')return;
    if(data.mode)root.dataset.modeChanging='true';
    try{
      if (data.mode && scope.mic && !await scope.mic.leave()) return;
      if('nonce' in data)data.nonce=nonce();
      const changed=await post(new URL(form.action).pathname.split('/').pop(),data);
      if(data.mode&&changed&&active()) {root.dataset.board=data.mode;window.dispatchEvent(new CustomEvent('freo-board-change'));}
    }finally{if(data.mode)delete root.dataset.modeChanging;}
  }));
  root.querySelectorAll('[data-queue-track]').forEach(button=>button.addEventListener('click',()=>choose(button.closest('.song-card').dataset.id,'queue')));
  scope.listen(root,'click',event=>{
    const button=event.target.closest('[data-load-deck],[data-add-cue]');
    if(!button||button.disabled)return;
    const card=button.closest('.song-card,[data-cue-entry]');if(!card?.dataset.id)return;
    if(button.hasAttribute('data-add-cue'))cueUI.add(card.dataset.id);
    else choose(card.dataset.id,button.dataset.loadDeck,card.dataset.cueEntry||'');
  });

  // One pointer gesture owns the drag, including drags beginning on artwork.
  let drag=null;
  const zones=[...root.querySelectorAll('#now-drop,#cue-drop,.up-next,.cue-panel')];
  const cleanDrag=()=>{drag?.ghost?.remove();drag=null;cueUI.clearHighlight();cueUI.drag(false);document.body.classList.remove('booth-dragging');zones.forEach(zone=>zone.classList.remove('drop-active'));};
  scope.listen(root,'dragstart',event=>{if(event.target.closest('.song-card,[data-cue-entry]'))event.preventDefault();});
  scope.listen(root,'pointerdown',event=>{
    const card=event.target.closest('.song-card,[data-cue-entry]');
    if(!card||event.button!==0||!event.isPrimary)return;
    if(event.target.closest('button,a,input')&&!event.target.closest('.cue-handle'))return;
    if(card.dataset.cueEntry&&!event.target.closest('.cue-handle')&&event.pointerType==='touch')return;
    drag={id:card.dataset.id,entryId:card.dataset.cueEntry||'',pointer:event.pointerId,x:event.clientX,y:event.clientY,card,ghost:null};
    cueUI.drag(true);card.setPointerCapture(event.pointerId);
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
    if(under?.closest('.cue-panel')){
      cueUI.highlight(cueUI.insertion(event.clientY,drag.entryId));
      const list=document.getElementById('booth-cue-list'),bounds=list.getBoundingClientRect();
      if(event.clientY<bounds.top+30)list.scrollBy(0,-14);else if(event.clientY>bounds.bottom-30)list.scrollBy(0,14);
    }else cueUI.clearHighlight();
    if(event.clientY<70)window.scrollBy(0,-18);else if(event.clientY>innerHeight-70)window.scrollBy(0,18);
  },{passive:false});
  scope.listen(document,'pointerup',event=>{
    if(!drag||event.pointerId!==drag.pointer)return;
    const item=drag,under=document.elementFromPoint(event.clientX,event.clientY),inCue=under?.closest('.cue-panel'),before=inCue?cueUI.insertion(event.clientY,item.entryId):'';cleanDrag();
    if(!item.ghost)return;
    if(inCue){if(item.entryId)cueUI.move(item.entryId,before);else cueUI.add(item.id,before);}
    else if(under?.closest('#cue-drop')&&item.id)choose(item.id,'cue',item.entryId);
    else if(under?.closest('#now-drop')&&item.id)choose(item.id,'air',item.entryId);
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
  assignForm.addEventListener('submit',async event=>{event.preventDefault();const ok=await post('assign-cart',Object.fromEntries(new FormData(assignForm)));if(!active())return;if(ok)dialog.close();else document.getElementById('cart-assign-error').textContent=document.getElementById('booth-notice').textContent;});
  function updateCartExplanation(){const over=assignForm.elements.playback_mode.value==='OVER',reduction=Number(assignForm.elements.duck_percent.value);text('cart-duck-value',`${reduction}%`);document.getElementById('cart-duck-setting').hidden=!over;text('cart-mode-explanation',over?`The program (music or live mic) plays at ${100-reduction}% of its previous volume while this cart plays, then returns to normal.`:'The cart plays by itself. Music pauses and resumes from the same position; a live mic is muted for the cart, then reopened.');}
  assignForm.elements.playback_mode.addEventListener('change',updateCartExplanation);assignForm.elements.duck_percent.addEventListener('input',updateCartExplanation);
  let cartSearchVersion=0;
  document.getElementById('cart-audio-search').addEventListener('input',async event=>{const version=++cartSearchVersion;try{const response=await scope.fetch(root.dataset.songSearchUrl.replace('song-search','cart-search')+'?q='+encodeURIComponent(event.target.value));if(!response.ok)throw new Error();const items=await response.json();if(!active()||version!==cartSearchVersion)return;assignForm.elements.identifier.replaceChildren(...items.map(item=>new Option(item.label,item.uuid)));}catch(_){text('cart-assign-error','Audio search is unavailable. Try again.');}});
  let localCart=null,lastCartFailure=null;
  function paintCarts(){
    const cart=state?.cart;
    if(state?.cart_result?.status==='failed'&&lastCartFailure!==state.cart_result.id){lastCartFailure=state.cart_result.id;notice('Cart playback failed. Check the audio and station connection before trying again.',true);}
    const locked=!!localCart||!state?.observation_fresh||!state?.mixer||!!state?.playout_error||cart?.locked;
    root.querySelectorAll('[data-role][data-position]').forEach(slot=>{
      const selected=(cart?.role===slot.dataset.role&&String(cart.position)===slot.dataset.position)||(localCart?.role===slot.dataset.role&&localCart?.position===slot.dataset.position);
      const connected=state?.observation_fresh&&!state?.playout_error;
      const playing=selected&&cart?.state==='playing'&&connected;
      slot.classList.toggle('cart-playing',!!playing);slot.classList.toggle('cart-queued',!!selected&&!playing&&!!locked&&!!connected);
      const button=slot.querySelector('[data-fire-cart]');
      if(button){button.disabled=!!locked;button.textContent=playing?'PLAYING':selected&&locked?(connected?'QUEUED…':'CHECKING…'):'PLAY';}
      slot.querySelector('[data-assign]').disabled=!!locked;
    });
  }
  root.querySelectorAll('[data-fire-cart]').forEach(button=>scope.listen(button,'click',async()=>{
    if(button.disabled||localCart||busy)return;
    const slot=button.closest('[data-role]');localCart={role:slot.dataset.role,position:slot.dataset.position};paintCarts();
    await post('fire-cart',{...localCart,nonce:nonce()});localCart=null;paintCarts();
  }));
  const songDialog=document.getElementById('song-picker-dialog'),songSearch=document.getElementById('song-picker-search'),songResults=document.getElementById('song-picker-results');
  let searchTimer,searchVersion=0,pickerTarget='cue';
  const searchSongs=async()=>{
    if(!active())return;
    const version=++searchVersion;songResults.textContent='Searching…';
    try {
      const response=await scope.fetch(`${root.dataset.songSearchUrl}?q=${encodeURIComponent(songSearch.value)}`,{credentials:'same-origin',cache:'no-store'});
      if(!response.ok||!response.headers.get('content-type')?.includes('application/json'))throw new Error('Search unavailable. Refresh and sign in if needed.');
      const songs=await response.json();if(!active()||version!==searchVersion)return;songResults.replaceChildren();
      for(const song of songs){
        const button=document.createElement('button');button.type='button';
        for(const [tag,value] of [['b',song.title],['span',song.artist],['small',song.album||'Single']]){const el=document.createElement(tag);el.textContent=value;button.append(el);}
        button.addEventListener('click',async()=>{button.disabled=true;const ok=await choose(song.uuid,pickerTarget);if(!active())return;button.disabled=false;if(ok)songDialog.close();else document.getElementById('picker-status').textContent=document.getElementById('booth-notice').textContent;});
        songResults.append(button);
      }
      if(!songs.length)songResults.textContent='No enabled songs found. Imported songs must be reviewed and enabled in Music.';
    }catch(error){if(active()&&version===searchVersion)songResults.textContent=error.message;}
  };
  root.querySelectorAll('.cue-picker-button').forEach(button=>button.addEventListener('click',()=>{
    pickerTarget=button.dataset.target||'B';text('song-picker-title',`Load a song on Deck ${pickerTarget}`);text('picker-status','');songDialog.showModal();songSearch.focus();searchSongs();
  }));
  songSearch.addEventListener('input',()=>{++searchVersion;songResults.textContent='Searching…';clearTimeout(searchTimer);searchTimer=setTimeout(searchSongs,180);});
  scope.cleanup(()=>{clearTimeout(searchTimer);++searchVersion;++cartSearchVersion;});
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
  const deckClock=ms=>{const seconds=Math.max(0,Math.floor(ms/1000));return `${Math.floor(seconds/3600)}:${Math.floor(seconds/60)%60}:${String(seconds%60).padStart(2,'0')}`;};
  function paintLoading(key){
    const panel=document.getElementById(key==='a'?'now-drop':'cue-drop');
    panel.classList.add('is-loading');panel.classList.remove('mix-live','is-fading','is-incoming');
    text(`deck-${key}-state`,'LOADING');text(`deck-${key}-message`,'RESETTING DECK · PREPARING SONG');
    panel.querySelector('h2').textContent='LOADING SONG';panel.querySelector('.now-copy p').textContent='Preparing from 0:0:00';
    panel.querySelector('.now-copy small').textContent='';panel.querySelectorAll('.track-facts span').forEach(node=>node.textContent='—');text(`deck-${key}-label`,key.toUpperCase());
    panel.querySelector('.disc').classList.remove('playing');
    panel.querySelectorAll('[data-operation]').forEach(button=>{button.disabled=true;button.classList.remove('is-live','is-incoming');if(button.dataset.operation==='PLAY')button.textContent='LOADING';});
  }
  function timing(){
    for(const key of ['a','b']){
      const item=state?.mixer?.[key],loading=pendingLoads.has(key);
      const elapsed=!loading&&item?Math.max(0,state.mixer[key+'_elapsed']||0)*1000:0;
      const duration=!loading&&item?item.duration_ms:0,fraction=duration?Math.min(1,elapsed/duration):0;
      text(key==='a'?'elapsed':'b-elapsed',deckClock(elapsed));
      text(key==='a'?'remaining':'b-remaining',duration?'-'+deckClock(Math.max(0,duration-elapsed)):'—:—:—');
      document.getElementById(key==='a'?'time-progress':'b-progress').style.width=`${fraction*100}%`;
      const ring=document.getElementById(key==='a'?'progress-ring':'b-progress-ring'),circumference=2*Math.PI*63;
      ring.style.strokeDasharray=circumference;ring.style.strokeDashoffset=circumference*(1-fraction);
    }
  }
  let refreshVersion=0,lastFailedCommand=null;
  scope.cleanup(()=>{++refreshVersion;});
  async function refresh(afterCommand=false){
    if(!active())return;
    const version=++refreshVersion;
    if(afterCommand)commandRefresh=true;
    try{
      const response=await scope.fetch(root.dataset.statusUrl,{credentials:'same-origin',cache:'no-store'});
      if(!response.ok)throw new Error();
      const next=await response.json();if(!active()||version!==refreshVersion)return;
      if(next.playout_error&&!next.mixer&&state?.mixer)next.mixer=state.mixer;
      const previous=state;
      state=next;
      cueUI.render(state);
      if(previous?.mode==='DJ_BOOTH' && state.mode==='AUTO' && state.mixer?.transition?.progress !== undefined){
        pendingLoads.clear();
        FreoDialog.notify({title:'Returning to Auto',message:state.mode_notice?.message || 'Returning to the schedule with a fade.'});
      }
      root.dataset.mode=state.mode;
      const board=root.dataset.micActive==='true'&&['AUTO','DJ_BOOTH'].includes(root.dataset.board)?root.dataset.board:state.mode;
      root.className=`dj-booth booth-mode-${board.toLowerCase().replace('_','-')}`;
      text('led-detail',state.mixer?.auto_standby?'AUTO ON AIR · DJ READY':state.mode.replace('_',' '));text('live-mode',state.mode);
      text('live-clock',state.clock||'None');
      text('auto-program','Following Auto schedule: '+(state.program||'No active program'));
      const aired=state.current;
      text('auto-category',state.playout_error?'Now playing category: Unavailable':aired?.source==='CART'?'Now playing: Cart':aired?.kind==='imaging'?'Now playing: Station audio':aired?.category?'Now playing category: '+aired.category:aired?'Now playing: '+(aired.source==='MANUAL'?'Manual selection':aired.source==='EVENT'?'Timed event':aired.source==='BLOCK'?'Scheduled block':'Uncategorized song'):'Now playing: No confirmed item');
      text('auto-song',state.playout_error?'Playback connection unavailable':aired?[aired.artist,aired.title].filter(Boolean).join(' — '):'Waiting for playback');
      systemStatus();
      text('live-transition',state.next_transition||'None');text('live-playout',state.playout_error||'Connected');
      text('live-fallback',state.fallback);text('next-event-name',state.next_event?.name||'None');
      const current=state.mode==='DJ_BOOTH' ? state.mixer?.a : (state.current || (state.playout_error ? state.last_known_current : null)), cue=state.mixer?.b;
      const engine=state.mixer,pending=state.deck_command?.status==='pending';
      if(state.deck_command?.status==='failed'&&state.deck_command.error!=='cue_changed'&&lastFailedCommand!==state.deck_command.id){
        lastFailedCommand=state.deck_command.id;notice(`Deck ${state.deck_command.deck} could not apply ${state.deck_command.operation.toLowerCase()}. The song or station state changed; review the deck and try again.`,true);
      }
      root.querySelectorAll('.cue-picker-button,[data-load-deck]').forEach(button=>button.disabled=pending||!engine||!!state.playout_error||!!button.closest('[data-cue-entry]:not([data-id]),[data-cue-entry][data-id=""]'));

      for(const [key,load] of pendingLoads){
        const item=engine?.[key],command=state.deck_command;
        // Status includes the worker's queued item for a paused deck. The engine's
        // current id can stay empty until PLAY, so it must not gate READY.
        if((item&&item.decision_id!==load.expected&&item.uuid===load.uuid)||(command?.deck===key.toUpperCase()&&command.operation==='LOAD'&&command.status==='failed'))pendingLoads.delete(key);
      }
      for(const deck of ['A','B']){
        const key=deck.toLowerCase(),item=engine?.[key],playing=!!item&&engine?.[key+'_playing'];
        const panel=document.getElementById(deck==='A'?'now-drop':'cue-drop');
        const incoming=engine?.transition?.incoming,fading=!!incoming&&playing&&!state.playout_error;
        panel.classList.toggle('mix-live',playing&&!state.playout_error);
        panel.classList.toggle('is-fading',fading);panel.classList.toggle('is-incoming',fading&&incoming===deck);panel.classList.toggle('is-loading',pendingLoads.has(key));
        text(`deck-${key}-message`,state.playout_error?'CONNECTION DELAY':fading?(incoming===deck?'GOING LIVE':'FADING OUT'):playing?'ON AIR':item?'CUED · READY TO TAKE AIR':'');
        text(`deck-${key}-state`,state.playout_error?'CONNECTION DELAY':!item?'EMPTY':fading?(incoming===deck?'GOING LIVE':'FADING OUT'):playing?'LIVE':item.started_at?'PAUSED':'READY');
        root.querySelectorAll(`[data-deck="${deck}"][data-operation]`).forEach(button=>{
          const operation=button.dataset.operation;
          button.disabled=pending||!engine||!item||!!state.playout_error||(operation==='PLAY'&&playing)||(['PAUSE','FADE'].includes(operation)&&!playing)||(operation==='REPEAT'&&item?.kind!=='track');
          if(operation==='PLAY'){button.textContent=fading&&incoming===deck?'GOING LIVE':playing?'LIVE':item?.started_at?'RESUME / TAKE AIR':'PLAY / TAKE AIR';button.classList.toggle('is-live',playing&&!state.playout_error);button.classList.toggle('is-incoming',fading&&incoming===deck);}
        });
        root.querySelector(`[data-preview-deck="${deck}"]`).disabled=!item||item.kind!=='track';
      }
      root.querySelector('.cue-disc').classList.toggle('playing',!!engine?.b&&engine.b_playing);
      paintCarts();
      text('morph-kicker',state.playout_error?'CONNECTION DELAY · LAST OBSERVED':'NOW PLAYING');
      root.querySelectorAll('#spinning-disc,.auto-disc .disc').forEach(disc=>disc.classList.toggle('playing',!!current&&(!state.mixer||state.mixer.a_playing)));
      document.querySelector('.onair-deck').classList.remove('active');
      text('deck-a-label','A');text('deck-b-label','B');
      programTarget=state.playout_error?0:meterLevel(state.program_rms);
      text('program-meter-label',Number.isFinite(state.program_rms)&&!state.playout_error?'PROGRAM / LIVE':'PROGRAM / NO SIGNAL DATA');
      const onAir=state.current || (state.playout_error?state.last_known_current:null);
      text('morph-text',onAir?.title||(state.playout_error?'Reconnecting to station':'Silence · no live deck')); document.getElementById('morph-text').title=onAir?.title||'';document.querySelector('#live-current h2').title=current?.title||'';document.getElementById('cue-title').title=cue?.title||'';text('morph-artist',onAir?.artist||'');
      document.querySelector('#live-current h2').textContent=current?.title||(state.playout_error?'Reconnecting to station':'NOTHING LOADED');
      document.querySelector('#live-current p').textContent=current?.artist||'';
      text('now-album',current?.album||'');
      text('fact-category',current?.category||'NO CATEGORY');
      text('fact-bpm',current?.bpm?`${Math.round(current.bpm)} BPM`:'BPM —');text('fact-year',current?.year||'YEAR —');
      text('fact-lufs',Number.isFinite(current?.loudness_lufs)?`${current.loudness_lufs.toFixed(1)} LUFS`:'LUFS —');
      text('queue-count',state.queue.length);fillQueue(state.queue);autoControls();
      root.querySelectorAll('.current-decision').forEach(input=>input.value=current?.decision_id||'');
      root.querySelectorAll('.current-control button').forEach(button=>button.disabled=!state.current||!!state.playout_error);
      root.querySelectorAll('.mode-button').forEach(button=>button.classList.toggle('active',button.dataset.mode===(root.dataset.board==='LIVE_MIC'? 'LIVE_MIC':board)));
      document.querySelector('.cue-deck').classList.toggle('cue-empty',!cue);
      text('cue-title',cue?.title||'NOTHING LOADED');text('cue-artist',cue?.artist||'');
      text('cue-album',cue?.album||'');document.getElementById('cue-warning').hidden=!!cue;
      if(previewDeck&&!engine?.[previewDeck.toLowerCase()]&&!cueMonitor.paused){cueMonitor.pause();resetPreview();}
      for(const [field,value] of [['category',cue?.category||'NO CATEGORY'],['bpm',cue?.bpm?`${Math.round(cue.bpm)} BPM`:'BPM —'],['year',cue?.year||'YEAR —'],['lufs',Number.isFinite(cue?.loudness_lufs)?`${cue.loudness_lufs.toFixed(1)} LUFS`:'LUFS —']])text('b-fact-'+field,value);
      for(const key of pendingLoads.keys())paintLoading(key);
      timing();
      window.dispatchEvent(new CustomEvent('freo-booth-refreshed'));
    }catch(_){
      if(!active()||version!==refreshVersion)return;
      cueUI.disconnect();
      text('live-playout','Reconnecting — controls will recover automatically');
      if(state)state={...state,playout_error:'Connection delayed'};autoControls();paintCarts();systemStatus();
      text('morph-kicker','CONNECTION DELAY · LAST OBSERVED');programTarget=0;
      root.querySelectorAll('.deck').forEach(panel=>panel.classList.remove('mix-live','is-fading','is-incoming'));
      root.querySelectorAll('.deck-take').forEach(button=>button.classList.remove('is-live','is-incoming'));
      root.querySelectorAll('[data-operation]').forEach(button=>button.disabled=true);

    }finally{if(afterCommand)commandRefresh=false;}
  }
  let skipRequested=null,skipFailureSeen=null;
  function autoControls(){
    if(!active())return;
    const reliable=state?.observation_fresh&&!state?.playout_error;
    const command=state?.skip_command;
    if(command?.status==='failed'&&command.id!==skipFailureSeen){skipFailureSeen=command.id;notice(command.error||'Skip failed; refresh and try again.',true);skipRequested=null;}
    const current=state?.current;
    const pending=skipRequested===current?.decision_id||(command&&command.expected_decision_id===current?.decision_id&&['pending','sent'].includes(command.status));
    const skip=document.getElementById('auto-skip');
    skip.disabled=!reliable||!current||state.mode!=='AUTO'||pending||state.cart?.locked;
    skip.textContent=pending?(command?.status==='sent'?'FADING…':'FADE REQUESTED…'):'SKIP TO NEXT';
    const next=state?.queue?.[0];
    text('auto-next',!reliable?'NEXT: Connection unavailable':state.unknown_queue_items?'NEXT: Queue item unavailable':next?'NEXT: '+[next.artist,next.title].filter(Boolean).join(' — '):'NEXT: Queue is empty');
    document.getElementById('auto-flag').disabled=!reliable||current?.kind!=='track';
  }
  scope.listen(document.getElementById('auto-skip'),'click',async()=>{
    const decision=state?.current?.decision_id;if(!decision||document.getElementById('auto-skip').disabled)return;
    skipRequested=decision;autoControls();
    if(!await post('skip',{expected_decision_id:decision,nonce:nonce()}))skipRequested=null;
    autoControls();
  });
  scope.listen(document.getElementById('auto-flag'),'click',()=>{
    if(state?.current?.kind==='track'&&!state.playout_error)window.FreoSongFlags.open({...state.current});
  });
  scope.listen(document,'song-flag-saved',()=>notice('Song flag saved. Review flagged songs in Music.'));
  let polling=false,lastPoll=0;
  scope.interval(()=>{const delay=root.dataset.mode==='DJ_BOOTH'&&!document.hidden?250:2000;if(!commandRefresh&&!polling&&Date.now()-lastPoll>=delay){polling=true;lastPoll=Date.now();refresh().finally(()=>polling=false);}},250);
  scope.interval(systemStatus,250);scope.interval(timing,250);refresh();
})();
