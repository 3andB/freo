(async () => {
  const root=document.getElementById('media-editor');if(!root)return;
  const scope=FreoPage,$=id=>document.getElementById(id),config=root.dataset;
  let state=null,selectors,busy=false,peaks=[],seekDragging=false;
  const message=text=>$('editor-status').textContent=text;
  function draw(){const canvas=$('song-waveform'),ctx=canvas.getContext('2d');canvas.width=Math.max(300,canvas.clientWidth*devicePixelRatio);canvas.height=100*devicePixelRatio;ctx.clearRect(0,0,canvas.width,canvas.height);const progress=Number($('waveform-seek').value)/1000;peaks.forEach((p,i)=>{ctx.fillStyle=i/peaks.length<progress?'#b9e79b':'#5c726b';const h=Math.max(2,p*canvas.height*.9);ctx.fillRect(i*canvas.width/peaks.length,(canvas.height-h)/2,Math.max(1,canvas.width/peaks.length-1),h);});}
  function paint(next){state=next;$('broadcast-status').textContent=next.broadcast;$('processing-status').textContent=next.processing_requested?'Queued':next.analysis==='complete'?'Audio processing complete':`Audio ${next.analysis}`;$('processing-error').textContent=next.error||'';
    const toggle=$('broadcast-toggle');if(toggle){toggle.textContent=next.enabled?'Disable broadcast':next.analysis==='complete'?'Enable broadcast':'Keep disabled after processing';toggle.setAttribute('aria-pressed',String(next.enabled));}
    const process=$('process-song');if(process)process.disabled=next.analysis==='processing'||next.processing_requested;
    if(JSON.stringify(peaks)!==JSON.stringify(next.waveform)){peaks=next.waveform||[];draw();}$('waveform-status').hidden=peaks.length>0;
    if(next.cover){$('editor-cover').src=next.cover;$('editor-cover').hidden=false;$('cover-placeholder').hidden=true;}else{$('editor-cover').hidden=true;$('cover-placeholder').hidden=false;}
  }
  async function refresh(){if(busy||FreoMusicToggles.pending)return;try{const response=await scope.fetch(config.songUrl,{cache:'no-store'});if(!response.ok)throw Error();paint(await response.json());}catch(_){message('Status unavailable. Your edits are still here.');}}
  async function save(){if(busy)return false;busy=true;message('Saving…');try{const form=$('song-details'),data={title:form.elements.title.value,track_number:form.elements.track_number.value,...selectors.values()};const next=await FreoCatalog.api(config.songUrl,config.csrf,{data:JSON.stringify(data)});paint(next);$('editor-title').textContent=next.title;$('editor-subtitle').textContent=`${next.artist} · ${next.album||'Single'}`;
      const advanced=root.querySelector('details form');for(const key of ['title','artist','album','track_number'])if(advanced.elements[key])advanced.elements[key].value=next[key]??'';
      root.querySelector('[data-preview]').dataset.title=next.title;message('Saved');return true;
    }catch(e){message(e.message);return false;}finally{busy=false;}}
  try{const catalog=await FreoCatalog.load(config.base);selectors=FreoCatalog.selectors($('editor-catalog'),catalog,{artist_id:config.artist,album_id:config.album||null},{...config,message});await refresh();}catch(e){message(e.message);return;}
  $('song-details').onsubmit=e=>{e.preventDefault();save();};
  $('cover-edit').onclick=async()=>{if(await save()){const result=await FreoCatalog.chooseCover(config,{song_id:config.song});if(result){message('Artwork saved');refresh();}}};
  $('broadcast-toggle')?.addEventListener('click',async()=>{if(busy)return;busy=true;try{const enabling=!state.enabled&&state.analysis==='complete';paint(await FreoCatalog.api(config.songUrl,config.csrf,{data:JSON.stringify({enabled:enabling})}));message('Broadcast state saved');}catch(e){message(e.message);}finally{busy=false;}});
  $('process-song')?.addEventListener('click',async()=>{if(busy)return;busy=true;try{await FreoCatalog.api($('process-song').dataset.url,config.csrf,{data:JSON.stringify({songs:[config.song]})});message('Audio processing queued');}catch(e){message(e.message);}finally{busy=false;refresh();}});
  const audio=$('music-audio'),seek=$('waveform-seek');
  $('editor-volume').oninput=e=>{audio.volume=Number(e.target.value);$('preview-volume').value=e.target.value;};
  const seekTo=async()=>{if(!audio.src.includes(state.audition)){await FreoPreview.play({uuid:config.song,title:state.title,artist:state.artist,audition:state.audition});}if(Number.isFinite(audio.duration))audio.currentTime=Number(seek.value)/1000*audio.duration;draw();};
  seek.oninput=()=>{seekDragging=true;draw();};seek.onchange=()=>{seekTo();seekDragging=false;};
  scope.listen(audio,'timeupdate',()=>{if(!audio.src.includes(state?.audition))return;if(!seekDragging&&audio.duration)seek.value=audio.currentTime/audio.duration*1000;$('editor-time').textContent=`${Math.floor(audio.currentTime/60)}:${String(Math.floor(audio.currentTime%60)).padStart(2,'0')} / ${Math.floor((audio.duration||0)/60)}:${String(Math.floor((audio.duration||0)%60)).padStart(2,'0')}`;draw();});
  scope.listen(window,'resize',draw);scope.listen(document,'music-toggle-saved',()=>setTimeout(refresh,0));scope.interval(refresh,3000);
  // Save advanced settings in place too; the server retains validation and CSRF.
  const advanced=root.querySelector('details form');advanced.onsubmit=async e=>{e.preventDefault();message('Saving advanced settings…');try{const response=await scope.fetch(advanced.action,{method:'POST',body:new FormData(advanced),headers:{Accept:'application/json'}});const result=await response.json();if(!response.ok)throw Error(result.message);message('Advanced settings saved');refresh();}catch(e){message(e.message);}};
})();
