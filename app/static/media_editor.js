(async () => {
  const root=document.getElementById('media-editor');if(!root)return;
  const scope=FreoPage,$=id=>document.getElementById(id),config=root.dataset;
  root.inert=true;root.setAttribute('aria-busy','true');
  let state=null,selectors,busy=false,peaks=[],seekDragging=false;
  const detailSave=$('song-details').querySelector('[type=submit]'),saveUnavailable=detailSave.disabled;
  const message=text=>$('editor-status').textContent=text;
  function draw(){const canvas=$('song-waveform'),ctx=canvas.getContext('2d');canvas.width=Math.max(300,canvas.clientWidth*devicePixelRatio);canvas.height=100*devicePixelRatio;ctx.clearRect(0,0,canvas.width,canvas.height);const colors=getComputedStyle(document.documentElement),played=colors.getPropertyValue('--theme-accent').trim(),unplayed=colors.getPropertyValue('--theme-border').trim();const progress=Number($('waveform-seek').value)/1000;peaks.forEach((p,i)=>{ctx.fillStyle=i/peaks.length<progress?played:unplayed;const h=Math.max(2,p*canvas.height*.9);ctx.fillRect(i*canvas.width/peaks.length,(canvas.height-h)/2,Math.max(1,canvas.width/peaks.length-1),h);});}
  scope.listen(window,'freo:themechange',draw);
  function paint(next){state=next;$('broadcast-status').textContent=next.broadcast;$('processing-status').textContent=next.processing_requested?'Queued':next.analysis==='complete'?'Audio processing complete':`Audio ${next.analysis}`;$('processing-error').textContent=next.error||'';
    const toggle=$('broadcast-toggle');if(toggle){toggle.textContent=next.enabled?'Disable broadcast':next.analysis==='complete'?'Enable broadcast':'Keep disabled after processing';toggle.setAttribute('aria-pressed',String(next.enabled));}
    const process=$('process-song');if(process){process.disabled=next.analysis==='processing'||next.processing_requested;process.textContent=next.processing_requested?'Queued…':next.analysis==='processing'?'Processing…':next.analysis==='failed'?'Retry processing':'Process song';}
    if(JSON.stringify(peaks)!==JSON.stringify(next.waveform)){peaks=next.waveform||[];draw();}$('waveform-status').hidden=peaks.length>0;
    if(next.cover){$('editor-cover').src=next.cover;$('editor-cover').hidden=false;$('cover-placeholder').hidden=true;}else{$('editor-cover').hidden=true;$('cover-placeholder').hidden=false;}
  }
  async function refresh(){if(busy||FreoMusicToggles.pending)return;try{const response=await scope.fetch(config.songUrl,{cache:'no-store'});if(!response.ok)throw Error();paint(await response.json());}catch(_){message('Status unavailable. Your edits are still here.');}}
  async function save(){if(busy)return false;if(selectors?.pending){message('Wait for artist or album creation to finish.');return false;}busy=true;message('Saving…');try{const form=$('song-details'),data={audio_kind:form.elements.audio_kind.value,audio_subtype:form.elements.audio_kind.value==='STATION'?form.elements.audio_subtype.value:'',cart_code:form.elements.cart_code.value,isrc:form.elements.isrc.value,title:form.elements.title.value,track_number:form.elements.track_number.value,...selectors.values()};const next=await FreoCatalog.api(config.songUrl,config.csrf,{data:JSON.stringify(data)});paint(next);form.elements.isrc.value=next.isrc||'';$('editor-title').textContent=next.title;$('editor-subtitle').textContent=`${next.artist} · ${next.album||'Single'}`;
      const advanced=root.querySelector('details form');for(const key of ['title','artist','album','track_number'])if(advanced.elements[key])advanced.elements[key].value=next[key]??'';
      root.querySelector('[data-preview]').dataset.title=next.title;message('Saved');return true;
    }catch(e){message(e.message);return false;}finally{busy=false;}}
  try{const catalog=await FreoCatalog.load(config.base);selectors=FreoCatalog.selectors($('editor-catalog'),catalog,{artist_id:config.artist,album_id:config.album||null},{...config,message,searchable:true,pending:value=>{detailSave.disabled=value||saveUnavailable;}});await refresh();if(!state)throw Error('Song details are unavailable. Reload to try again.');}catch(e){message(e.message);const retry=document.createElement('a');retry.href=location.href;retry.textContent='Could not load the editor. Reload to try again.';retry.className='admin-notice error';root.before(retry);scope.cleanup(()=>retry.remove());return;}
  $('editor-availability')?.addEventListener('click',()=>{if(state?.availability&&window.FreoAvailability)FreoAvailability.open(state,config.csrf);});
  $('song-details').onsubmit=e=>{e.preventDefault();save();};
  $('cover-edit').onclick=async()=>{if(await save()){const result=await FreoCatalog.chooseCover(config,{song_id:config.song});if(result){message('Artwork saved');refresh();}}};
  $('broadcast-toggle')?.addEventListener('click',async()=>{if(busy)return;busy=true;try{const enabling=!state.enabled&&state.analysis==='complete';paint(await FreoCatalog.api(config.songUrl,config.csrf,{data:JSON.stringify({enabled:enabling})}));message('Broadcast state saved');}catch(e){message(e.message);}finally{busy=false;}});
  $('process-song')?.addEventListener('click',async()=>{if(busy)return;busy=true;$('process-song').disabled=true;$('process-song').textContent='Queuing…';message('Queuing audio processing…');try{await FreoCatalog.api($('process-song').dataset.url,config.csrf,{data:JSON.stringify({songs:[config.song]})});message('Audio processing queued');}catch(e){message(e.message);}finally{busy=false;refresh();}});
  const audio=$('music-audio'),seek=$('waveform-seek');
  $('editor-volume').oninput=e=>{audio.volume=Number(e.target.value);$('preview-volume').value=e.target.value;};
  const seekTo=async()=>{if(!audio.src.includes(state.audition)){await FreoPreview.play({uuid:config.song,title:state.title,artist:state.artist,audition:state.audition});}if(Number.isFinite(audio.duration))audio.currentTime=Number(seek.value)/1000*audio.duration;draw();};
  seek.oninput=()=>{seekDragging=true;draw();};seek.onchange=()=>{seekTo();seekDragging=false;};
  scope.listen(audio,'timeupdate',()=>{if(!audio.src.includes(state?.audition))return;if(!seekDragging&&audio.duration)seek.value=audio.currentTime/audio.duration*1000;$('editor-time').textContent=`${Math.floor(audio.currentTime/60)}:${String(Math.floor(audio.currentTime%60)).padStart(2,'0')} / ${Math.floor((audio.duration||0)/60)}:${String(Math.floor((audio.duration||0)%60)).padStart(2,'0')}`;draw();});
  scope.listen(window,'resize',draw);scope.listen(document,'music-toggle-saved',()=>setTimeout(refresh,0));scope.interval(refresh,3000);
  // Save advanced settings in place too; the server retains validation and CSRF.
  const advanced=root.querySelector('details form');advanced.onsubmit=async e=>{e.preventDefault();message('Saving advanced settings…');try{const response=await scope.fetch(advanced.action,{method:'POST',body:new FormData(advanced),headers:{Accept:'application/json'}});const result=await response.json();if(!response.ok)throw Error(result.message);message('Advanced settings saved');document.dispatchEvent(new CustomEvent('freo:form-saved',{detail:{form:advanced}}));refresh();}catch(e){message(e.message);}};
  root.inert=false;root.removeAttribute('aria-busy');
})();
