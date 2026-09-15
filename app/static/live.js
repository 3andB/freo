(() => {
  const root = document.getElementById('dj-booth');
  if (!root) return;
  let state = null;
  let dragged = null;
  const actionUrl = action => root.dataset.actionBase.replace('ACTION', action);
  const text = (id, value) => { const node=document.getElementById(id); if(node) node.textContent=value; };
  const nonce = () => crypto.randomUUID();
  const readDrag = event => {
    try { return JSON.parse(event.dataTransfer.getData('application/x-freo')); }
    catch (_) { return dragged; }
  };
  const post = async (action, data={}) => {
    const body=new FormData(); body.set('csrf',root.dataset.csrf);
    Object.entries(data).forEach(([key,value]) => body.set(key,value ?? ''));
    const response=await fetch(actionUrl(action),{method:'POST',body,credentials:'same-origin'});
    if (!response.ok) throw new Error(`Control failed (${response.status})`);
    location.reload();
  };

  document.querySelectorAll('[draggable="true"]').forEach(node => {
    node.addEventListener('dragstart', event => {
      dragged={kind:node.dataset.kind,id:node.dataset.id,audition:node.dataset.audition};
      event.dataTransfer.effectAllowed='copy';
      event.dataTransfer.setData('application/x-freo',JSON.stringify(dragged));
      event.dataTransfer.setData('text/plain',node.dataset.id || '');
      node.classList.add('dragging');
    });
    node.addEventListener('dragend',()=>{node.classList.remove('dragging');dragged=null;});
  });
  const dropZone = (selector, kind, handler) => {
    const zone=document.querySelector(selector); if(!zone)return;
    zone.addEventListener('dragenter',e=>{const item=readDrag(e);if(item?.kind===kind){e.preventDefault();zone.classList.add('drop-active');}});
    zone.addEventListener('dragover',e=>{const item=readDrag(e);if(item?.kind===kind){e.preventDefault();e.dataTransfer.dropEffect='copy';}});
    zone.addEventListener('dragleave',e=>{if(!zone.contains(e.relatedTarget))zone.classList.remove('drop-active');});
    zone.addEventListener('drop',e=>{e.preventDefault();zone.classList.remove('drop-active');const item=readDrag(e);if(item?.kind===kind)handler(item);});
  };
  dropZone('.up-next','track',item=>post('queue-track',{identifier:item.id,nonce:nonce()}));
  dropZone('#cue-drop','track',item=>post('cue',{identifier:item.id}));
  dropZone('#now-drop','track',item=>{
    if(!state?.current)return;
    if(confirm('Fade the current item and take this song on air?'))post('takeover',{identifier:item.id,expected_decision_id:state.current.decision_id,nonce:nonce()});
  });
  document.querySelectorAll('.hot-cart,.id-cart').forEach(slot=>dropZone(`[data-role="${slot.dataset.role}"][data-position="${slot.dataset.position}"]`,'imaging',item=>post('assign-cart',{identifier:item.id,role:slot.dataset.role,position:slot.dataset.position})));
  document.querySelectorAll('[data-queue-track]').forEach(button=>button.addEventListener('click',()=>post('queue-track',{identifier:button.closest('.song-card').dataset.id,nonce:nonce()})));
  document.querySelectorAll('[data-cue-track]').forEach(button=>button.addEventListener('click',()=>post('cue',{identifier:button.closest('.song-card').dataset.id})));
  document.querySelectorAll('[data-fire-imaging]').forEach(button=>button.addEventListener('click',()=>post('queue-imaging',{identifier:button.dataset.fireImaging,nonce:nonce()})));

  // A pointer-driven path makes song dragging reliable for mouse, pen, touch,
  // nested artwork, and browsers with restricted DataTransfer access.
  let pointerDrag=null;
  document.querySelectorAll('.song-card').forEach(card=>card.addEventListener('pointerdown',event=>{
    if(event.button!==0||event.target.closest('button,a,input'))return;
    pointerDrag={id:card.dataset.id,startX:event.clientX,startY:event.clientY,active:false,card,ghost:null};
  }));
  document.addEventListener('pointermove',event=>{
    if(!pointerDrag)return;
    if(!pointerDrag.active&&Math.hypot(event.clientX-pointerDrag.startX,event.clientY-pointerDrag.startY)>7){
      pointerDrag.active=true;pointerDrag.ghost=document.createElement('div');pointerDrag.ghost.className='pointer-drag-ghost';pointerDrag.ghost.textContent=pointerDrag.card.querySelector('b').textContent;document.body.append(pointerDrag.ghost);document.body.classList.add('booth-dragging');
    }
    if(!pointerDrag.active)return;
    event.preventDefault();pointerDrag.ghost.style.transform=`translate3d(${event.clientX+14}px,${event.clientY+14}px,0)`;
    const under=document.elementFromPoint(event.clientX,event.clientY);
    document.querySelectorAll('#now-drop,#cue-drop,.up-next').forEach(zone=>zone.classList.toggle('drop-active',zone.contains(under)));
  },{passive:false});
  document.addEventListener('pointerup',event=>{
    if(!pointerDrag)return;const item=pointerDrag,under=document.elementFromPoint(event.clientX,event.clientY);item.ghost?.remove();document.body.classList.remove('booth-dragging');document.querySelectorAll('.drop-active').forEach(x=>x.classList.remove('drop-active'));pointerDrag=null;if(!item.active)return;
    if(under?.closest('#cue-drop'))post('cue',{identifier:item.id});
    else if(under?.closest('.up-next'))post('queue-track',{identifier:item.id,nonce:nonce()});
    else if(under?.closest('#now-drop')&&state?.current&&confirm('Fade the current item and take this song on air?'))post('takeover',{identifier:item.id,expected_decision_id:state.current.decision_id,nonce:nonce()});
  });
  document.addEventListener('pointercancel',()=>{pointerDrag?.ghost?.remove();pointerDrag=null;document.body.classList.remove('booth-dragging');});

  const dialog=document.getElementById('cart-assign-dialog'), assignForm=document.getElementById('cart-assign-form');
  const openAssign=slot=>{assignForm.elements.role.value=slot.dataset.role;assignForm.elements.position.value=slot.dataset.position;dialog.showModal();};
  document.querySelectorAll('[data-assign]').forEach(button=>button.addEventListener('click',()=>openAssign(button.closest('[data-role]'))));
  document.querySelectorAll('[data-open-assign]').forEach(button=>button.addEventListener('click',()=>openAssign(button.closest('section').querySelector('[data-role]'))));
  assignForm.addEventListener('submit',event=>{event.preventDefault();post('assign-cart',Object.fromEntries(new FormData(assignForm)));});

  const AudioCtx=window.AudioContext||window.webkitAudioContext;
  const analyserFor=(audio,leftId,rightId)=>{
    if(!AudioCtx)return null;const context=new AudioCtx(),source=context.createMediaElementSource(audio),split=context.createChannelSplitter(2),left=context.createAnalyser(),right=context.createAnalyser();
    left.fftSize=256;right.fftSize=256;source.connect(split);source.connect(context.destination);split.connect(left,0);split.connect(right,1);
    const ld=new Uint8Array(left.fftSize),rd=new Uint8Array(right.fftSize),level=(a,d)=>{a.getByteTimeDomainData(d);let sum=0;for(const value of d){const x=(value-128)/128;sum+=x*x;}return Math.min(1,Math.sqrt(sum/d.length)*2.4);};
    const tick=()=>{document.getElementById(leftId).value=level(left,ld);document.getElementById(rightId).value=level(right,rd);requestAnimationFrame(tick);};tick();return context;
  };
  const monitor=document.getElementById('booth-monitor');let programContext=null;
  document.querySelectorAll('[data-monitor-toggle]').forEach(button=>button.addEventListener('click',async()=>{if(monitor.paused){await monitor.play();programContext ||= analyserFor(monitor,'monitor-left','monitor-right');document.querySelectorAll('[data-monitor-toggle]').forEach(x=>x.textContent='MUTE MONITOR');}else{monitor.pause();document.getElementById('monitor-left').value=0;document.getElementById('monitor-right').value=0;document.querySelectorAll('[data-monitor-toggle]').forEach(x=>x.textContent='MONITOR');}}));
  const cueMonitor=document.getElementById('cue-monitor');let cueContext=null;
  document.getElementById('audition-cue')?.addEventListener('click',async event=>{if(!state?.cue)return;cueMonitor.src=`${location.pathname.replace(/\/live$/,'/media')}/${encodeURIComponent(state.cue.uuid)}/audition`;await cueMonitor.play();cueContext ||= analyserFor(cueMonitor,'monitor-left','monitor-right');event.currentTarget.textContent='CUE PLAYING';});

  let showArtist=false,morphDecision=null;
  setInterval(()=>{showArtist=!showArtist;const node=document.getElementById('morph-text');if(!node)return;node.classList.add('morphing');setTimeout(()=>{node.textContent=showArtist?(state?.current?.artist||'FREO'):(state?.current?.title||'ON AIR');node.classList.remove('morphing');},220);},3200);
  let programTarget=0,programLevel=0,lastPeak=0;
  const headerSegments=[...document.querySelectorAll('.header-vu>i')],particleLayer=document.getElementById('peak-particles');
  const animateProgram=()=>{
    programLevel+=(programTarget-programLevel)*.18;
    headerSegments.forEach((bar,index)=>bar.classList.toggle('lit',index/headerSegments.length<programLevel));
    if(programTarget>lastPeak+.08&&programTarget>.3){for(let n=0;n<5;n++){const particle=document.createElement('b');particle.style.left=`${Math.min(98,programTarget*100)}%`;particle.style.setProperty('--drift',`${(n-2)*9}px`);particleLayer.append(particle);setTimeout(()=>particle.remove(),900);}}
    lastPeak=Math.max(programTarget,lastPeak*.94);requestAnimationFrame(animateProgram);
  };animateProgram();

  const fillQueue=items=>{const list=document.getElementById('live-queue');list.replaceChildren();if(!items.length){const li=document.createElement('li');li.className='empty-copy';li.textContent='Queue is empty';list.append(li);}items.forEach((item,index)=>{const li=document.createElement('li');li.innerHTML=`<span class="queue-index">${index+1}</span><div><b></b><small></small></div>`;li.querySelector('b').textContent=item.title;li.querySelector('small').textContent=`${item.artist} · ${item.source}`;list.append(li);});};
  function timing(){const current=state?.current;if(!current?.started_at||!current.duration_ms)return;const elapsed=Math.max(0,Date.now()-Date.parse(current.started_at)),fraction=Math.min(1,elapsed/current.duration_ms),clock=ms=>`${Math.floor(ms/60000)}:${String(Math.floor(ms/1000)%60).padStart(2,'0')}`;text('elapsed',clock(elapsed));text('remaining',`-${clock(Math.max(0,current.duration_ms-elapsed))}`);document.getElementById('time-progress').style.width=`${fraction*100}%`;for(const id of ['progress-ring','auto-ring']){const ring=document.getElementById(id);if(ring){const circumference=2*Math.PI*parseFloat(ring.getAttribute('r'));ring.style.strokeDasharray=circumference;ring.style.strokeDashoffset=circumference*(1-fraction);}}}
  async function refresh(){try{const response=await fetch(root.dataset.statusUrl,{credentials:'same-origin',cache:'no-store'});if(!response.ok)throw new Error();state=await response.json();root.dataset.mode=state.mode;root.className=`dj-booth booth-mode-${state.mode.toLowerCase().replace('_','-')}`;text('led-detail',state.mode.replace('_',' '));text('live-mode',state.mode);text('live-clock',state.clock||'None');text('auto-clock',state.clock||'No active clock');text('live-transition',state.next_transition||'None');text('live-playout',state.playout_error||'Connected');text('live-fallback',state.fallback);text('next-event-name',state.next_event?.name||'None');text('current-source',state.current?.source||'FALLBACK');const current=state.current;const rms=Number.isFinite(state.program_rms)?Math.min(1,state.program_rms*2.8):0;programTarget=rms;document.getElementById('program-left').value=rms;document.getElementById('program-right').value=rms;if(current?.decision_id!==morphDecision){morphDecision=current?.decision_id;text('morph-text',current?.title||'ON AIR');showArtist=false;}document.querySelector('#live-current h2').textContent=current?.title||'Fallback / awaiting confirmation';document.querySelector('#live-current p').textContent=current?.artist||'Live broadcast';text('now-album',current?.album||'Live broadcast');text('auto-title',current?.title||'Fallback / awaiting confirmation');text('auto-artist',current?.artist||'Live broadcast');text('auto-category',current?.category||'No category');text('fact-category',current?.category||'NO CATEGORY');text('fact-bpm',current?.bpm?`${Math.round(current.bpm)} BPM`:'BPM —');text('fact-year',current?.year||'YEAR —');text('fact-lufs',current?.loudness_lufs?`${current.loudness_lufs.toFixed(1)} LUFS`:'LUFS —');text('queue-count',state.queue.length);fillQueue(state.queue);document.querySelectorAll('.current-decision').forEach(input=>input.value=current?.decision_id||'');document.querySelectorAll('.current-control button').forEach(button=>button.disabled=!current);document.querySelectorAll('.mode-button').forEach(button=>button.classList.toggle('active',button.dataset.mode===state.mode));text('cue-title',state.cue?.title||'NOTHING CUED');text('cue-artist',state.cue?.artist||'Drag a song here before taking control');text('cue-album',state.cue?.album||'Cue deck is empty');document.getElementById('cue-warning').hidden=!!state.cue;timing();}catch(_){text('live-playout','Status unavailable');}}
  setInterval(timing,500);setInterval(refresh,2000);refresh();
})();
