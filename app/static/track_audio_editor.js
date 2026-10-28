/* Draft audio policy stays local until an explicit, revision-checked save. */
(() => {
  const root=document.getElementById('media-editor'),form=document.getElementById('audio-edits');
  if(!root||!form)return;
  const scope=FreoPage,fields=['cue_in_ms','cue_out_ms','fade_in_ms','fade_out_ms','gain_trim_db'];
  const status=document.getElementById('audio-edit-status'),summary=document.getElementById('audio-edit-summary');
  const wrap=document.querySelector('.waveform-wrap'),canvas=document.createElement('canvas');
  canvas.className='audio-edit-overlay';canvas.setAttribute('aria-hidden','true');wrap.append(canvas);
  let state=null,revision=0,dirty=false,saving=false;
  const markers={};
  const read=()=>Object.fromEntries(fields.map(k=>[k,form.elements[k].value===''?null:Number(form.elements[k].value)]));
  function policy(){
    const v=read(),length=state.audio.source_duration_ms,start=v.cue_in_ms??0,end=v.cue_out_ms??length;
    const fi=v.fade_in_ms??0,fo=v.fade_out_ms??0,trim=v.gain_trim_db??0;
    if(fields.some(k=>v[k]!==null&&(!Number.isFinite(v[k])||(k!=='gain_trim_db'&&!Number.isInteger(v[k]))))||start<0||end>length||start>=end||fi<0||fo<0||fi+fo>end-start||trim < -12||trim>12)throw Error('Choose whole-millisecond cue points, fades that fit, and gain between −12 and +12 dB.');
    const base=state.audio.gain,db=Math.max(-60,Math.min(base.normalization_db+trim,base.max_gain_db));
    return {...state.audio,enabled:true,effective:{cue_in_ms:start,cue_out_ms:end,fade_in_ms:fi,fade_out_ms:fo,gain_trim_db:trim},duration_ms:end-start,gain:{...base,db,factor:10**(db/20),requested_trim_db:trim,status:db<base.normalization_db+trim-.05?'Gain limited':base.status==='Needs analysis'?'Needs analysis':'Edited preview'}};
  }
  function draw(){
    if(!state)return;
    const length=state.audio.source_duration_ms,v=read(),start=v.cue_in_ms??0,end=v.cue_out_ms??length;
    const positions={cue_in_ms:start,cue_out_ms:end,fade_in_ms:start+(v.fade_in_ms??0),fade_out_ms:end-(v.fade_out_ms??0)};
    for(const [key,button] of Object.entries(markers)){button.style.left=`${Math.max(0,Math.min(100,positions[key]/length*100))}%`;button.setAttribute('aria-valuenow',String(v[key]??(key==='cue_out_ms'?length:0)));button.setAttribute('aria-valuemax',String(length));}
    canvas.width=wrap.clientWidth*devicePixelRatio;canvas.height=100*devicePixelRatio;
    const ctx=canvas.getContext('2d'),x=ms=>ms/length*canvas.width,h=canvas.height;
    ctx.fillStyle='rgba(0,0,0,.35)';ctx.fillRect(0,0,x(start),h);ctx.fillRect(x(end),0,canvas.width-x(end),h);
    ctx.strokeStyle=getComputedStyle(document.documentElement).getPropertyValue('--theme-accent');ctx.lineWidth=2*devicePixelRatio;
    ctx.beginPath();ctx.moveTo(x(start),h);ctx.lineTo(x(positions.fade_in_ms),0);ctx.lineTo(x(positions.fade_out_ms),0);ctx.lineTo(x(end),h);ctx.stroke();
    try{const p=policy();summary.textContent=`Playable ${(p.duration_ms/1000).toFixed(3)} s · Normalization ${p.gain.normalization_db.toFixed(1)} dB · Effective gain ${p.gain.db.toFixed(1)} dB${p.gain.db<p.gain.normalization_db+(v.gain_trim_db??0)-.05?' (limited)':''}`;form.querySelector('[type=submit]').disabled=saving;}
    catch(e){summary.textContent=e.message;form.querySelector('[type=submit]').disabled=true;}
  }
  function change(){dirty=true;status.textContent='Unsaved audio edits';draw();}
  for(const [key,label] of Object.entries({cue_in_ms:'Cue in',cue_out_ms:'Cue out',fade_in_ms:'Fade in',fade_out_ms:'Fade out'})){
    const button=document.createElement('button');button.type='button';button.className='audio-edit-marker '+(key.startsWith('fade')?'fade-marker':'');button.textContent=label;
    button.setAttribute('role','slider');button.setAttribute('aria-label',label+' milliseconds');button.setAttribute('aria-valuemin','0');button.disabled=form.querySelector('fieldset').disabled;wrap.append(button);markers[key]=button;
    const move=e=>{const box=wrap.getBoundingClientRect(),v=read(),point=Math.round(Math.max(0,Math.min(1,(e.clientX-box.left)/box.width))*state.audio.source_duration_ms);form.elements[key].value=key==='fade_in_ms'?Math.max(0,point-(v.cue_in_ms??0)):key==='fade_out_ms'?Math.max(0,(v.cue_out_ms??state.audio.source_duration_ms)-point):point;change();};
    button.addEventListener('pointerdown',e=>{if(!state||button.disabled)return;e.preventDefault();button.setPointerCapture(e.pointerId);move(e);});
    button.addEventListener('pointermove',e=>{if(button.hasPointerCapture(e.pointerId))move(e);});
    button.addEventListener('keydown',e=>{if(!state||!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(e.key))return;e.preventDefault();const fallback=key==='cue_out_ms'?state.audio.source_duration_ms:0;form.elements[key].value=Math.max(0,Math.min(state.audio.source_duration_ms,Number(form.elements[key].value||fallback)+(['ArrowRight','ArrowUp'].includes(e.key)?1:-1)*(e.shiftKey?1000:10)));change();});
  }
  function load(next,force=false){state=next;if(!dirty||force){revision=next.audio.revision;for(const key of fields)form.elements[key].value=next.audio.saved[key]??'';dirty=false;status.textContent=next.audio.enabled?'Saved audio edits are active.':'Stored cue suggestions are inactive until you save audio edits.';}draw();}
  scope.listen(root,'freo:track-state',e=>load(e.detail));if(root.freoTrackState)load(root.freoTrackState);
  scope.listen(window,'resize',draw);scope.listen(window,'freo:themechange',draw);form.addEventListener('input',change);
  document.getElementById('audio-reset').onclick=()=>{for(const k of fields)form.elements[k].value=k.startsWith('fade')?'0':'';change();};
  document.getElementById('audio-reload').onclick=async()=>{try{const r=await scope.fetch(root.dataset.songUrl,{cache:'no-store'});if(!r.ok)throw Error('Could not reload audio settings');load(await r.json(),true);}catch(e){status.textContent=e.message;}};
  form.onsubmit=async e=>{e.preventDefault();if(saving)return;try{policy();saving=true;draw();const next=await FreoCatalog.api(root.dataset.songUrl+'/audio',root.dataset.csrf,{data:JSON.stringify({...read(),revision})});load(next,true);root.freoTrackState=next;root.dispatchEvent(new CustomEvent('freo:track-state',{detail:next}));status.textContent='Audio edits saved';document.dispatchEvent(new CustomEvent('freo:form-saved',{detail:{form}}));}catch(e){status.textContent=e.message;}finally{saving=false;draw();}};
  async function preview(original){try{const p=original?state.audio:policy();await FreoPreview.play({uuid:state.uuid,title:state.title,artist:state.artist,audition:state.audition,audio:p,original,restart:true});}catch(e){status.textContent=e.message;}}
  document.getElementById('audio-preview').onclick=()=>preview(false);document.getElementById('audio-original').onclick=()=>preview(true);
})();
