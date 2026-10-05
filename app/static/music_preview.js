(() => {
  const scope = window.FreoPage;
  const player=document.getElementById('music-player');if(!player)return;
  const audio=document.getElementById('music-audio'),toggle=document.getElementById('preview-toggle');
  const seek=document.getElementById('preview-seek'),normalized=document.getElementById('preview-normalized');
  const dockSpace=()=>document.documentElement.style.setProperty('--music-preview-space',player.hidden?'0px':(player.getBoundingClientRect().height+16)+'px');
  const dockObserver=new ResizeObserver(dockSpace);dockObserver.observe(player);
  scope.cleanup(()=>{dockObserver.disconnect();document.documentElement.style.removeProperty('--music-preview-space');});
  let current=null,context=null,gain=null,version=0,waiting=false;
  const clock=value=>`${Math.floor((value||0)/60)}:${String(Math.floor((value||0)%60)).padStart(2,'0')}`;
  const label=(id,value)=>document.getElementById(id).textContent=value;
  const sync=()=>{
    toggle.textContent=audio.paused?'▶':'Ⅱ';toggle.setAttribute('aria-label',audio.paused?'Play preview':'Pause preview');
    document.querySelectorAll('[data-preview]').forEach(button=>{
      const playing=button.dataset.preview===current?.uuid&&!audio.paused;
      button.textContent=playing?'Ⅱ':'▶';button.classList.toggle('is-playing',playing);button.setAttribute('aria-label',`${playing?'Pause':'Play'} ${button.dataset.title||''}`);
    });
  };
  const edited=()=>current?.audio?.enabled&&!current.original;
  const bounds=()=>edited()?{start:current.audio.effective.cue_in_ms/1000,end:current.audio.effective.cue_out_ms/1000}:{start:0,end:audio.duration};
  // Schedule ramps on the audio clock, not timeupdate callbacks. Pause/seek
  // cancels and rebuilds the envelope against the current source position.
  const updateGain=()=>{
    const g=current?.audio?.gain||current?.gain,active=edited(),v=current?.audio?.effective;
    const factor=current?.original?1:(active||normalized.checked?(g?.factor??1):1);
    label('preview-gain',current?.original||(!active&&!normalized.checked)?'Original':`${active?'Edited · ':''}${g?.db??0} dB · ${g?.status||''}`);
    if(!gain)return;
    const now=context.currentTime,t=audio.currentTime,{start,end}=bounds();
    const fi=active?v.fade_in_ms/1000:0,fo=active?v.fade_out_ms/1000:0;
    const envelope=p=>!active?1:p<start||p>=end?0:Math.min(1,fi?(p-start)/fi:1,fo?(end-p)/fo:1);
    gain.gain.cancelScheduledValues(now);gain.gain.setValueAtTime(factor*envelope(t),now);
    if(audio.paused||waiting||!active)return;
    const rate=audio.playbackRate||1;
    for(const p of [start+fi,end-fo])if(p>t)gain.gain.linearRampToValueAtTime(factor,now+(p-t)/rate);
    if(end>t){
      if(fo>0)gain.gain.linearRampToValueAtTime(0,now+(end-t)/rate);
      else gain.gain.setValueAtTime(0,now+(end-t)/rate);
    }
  };
  const error=message=>{const el=document.getElementById('preview-error');el.hidden=false;el.textContent=message;};
  const start=async song=>{
    const attempt=++version;player.hidden=false;document.getElementById('preview-error').hidden=true;
    try{
      const changed=song&&song.uuid!==current?.uuid;
      if(!changed&&!song?.restart&&!audio.paused){audio.pause();sync();return;}
      if(changed||song?.restart||(song&&!song.audio)){
        audio.pause();const next={...song};delete next.restart;
        if(!song.audio){
          const match=song.audition?.match(/^\/admin\/stations\/([^/]+)\/media\/([^/]+)\/audition$/);
          if(match){const response=await scope.fetch(`/admin/api/stations/${match[1]}/song/${match[2]}`,{cache:'no-store'});if(!response.ok)throw Error();const data=await response.json();if(attempt!==version)return;next.audio=data.audio;}
        }
        current=next;
        if(changed)audio.src=song.audition;
        label('preview-title',song.title);label('preview-artist',song.artist);seek.value=0;
      }
      if(!current)return;
      if(!context){const AudioCtx=window.AudioContext||window.webkitAudioContext;if(AudioCtx){context=new AudioCtx();gain=context.createGain();context.createMediaElementSource(audio).connect(gain);gain.connect(context.destination);}else{if(edited())throw Error();normalized.checked=false;normalized.disabled=true;}}
      if(edited()&&(changed||song?.restart||audio.currentTime<bounds().start||audio.currentTime>=bounds().end-.02))audio.currentTime=bounds().start;
      else if(song?.restart)audio.currentTime=0;
      FreoMonitor.stop();updateGain();await context?.resume();if(attempt!==version)return;await audio.play();if(attempt!==version)return;updateGain();sync();
    }catch(_){if(attempt===version){audio.pause();error('Audio could not start. Check your connection and that the song is available.');sync();}}
  };
  scope.interval(()=>{if(edited()&&!audio.paused&&audio.currentTime>=bounds().end){audio.pause();audio.currentTime=bounds().end;}},25);
  scope.listen(audio,'waiting',()=>{waiting=true;updateGain();});
  scope.listen(audio,'seeking',()=>{waiting=true;updateGain();});
  scope.listen(audio,'playing',()=>{waiting=false;updateGain();});
  scope.listen(audio,'seeked',()=>{
    if(edited()&&audio.currentTime<bounds().start){audio.currentTime=bounds().start;return;}
    waiting=audio.readyState<3;updateGain();
  });
  for(const event of ['play','pause','loadedmetadata','ratechange'])scope.listen(audio,event,()=>{
    if(edited()&&audio.currentTime<bounds().start){audio.currentTime=bounds().start;return;}
    updateGain();
  });
  scope.listen(document,'music-song-deleted',event=>{if(current?.uuid===event.detail.uuid){version++;audio.pause();audio.removeAttribute('src');audio.load();current=null;player.hidden=true;sync();}});
  scope.listen(document,'click',event=>{
    const button=event.target.closest('[data-preview]');if(!button)return;
    event.stopPropagation();const d=button.dataset;
    start({uuid:d.preview,title:d.title,artist:d.artist,audition:d.audition,gain:{factor:Number(d.gain||1),db:Number(d.gainDb||0),status:d.gainStatus}});
  });
  toggle.addEventListener('click',()=>start(current));normalized.addEventListener('change',updateGain);
  document.getElementById('preview-close').addEventListener('click',()=>{version++;audio.pause();player.hidden=true;sync();});
  document.getElementById('preview-volume').addEventListener('input',event=>audio.volume=Number(event.target.value));audio.volume=.8;
  seek.addEventListener('input',()=>{if(Number.isFinite(audio.duration)){const b=bounds();audio.currentTime=b.start+(b.end-b.start)*Number(seek.value)/100;}});
  audio.addEventListener('timeupdate',()=>{const b=bounds(),elapsed=Math.max(0,audio.currentTime-b.start),duration=b.end-b.start;label('preview-elapsed',clock(elapsed));label('preview-duration',clock(duration));if(duration>0)seek.value=Math.max(0,Math.min(100,elapsed/duration*100));});
  for(const name of ['play','pause','ended'])audio.addEventListener(name,sync);
  audio.addEventListener('error',()=>error('This audio file is unavailable. Try again or inspect the song details.'));
  scope.cleanup(()=>{context?.close();delete window.FreoPreview;});
  window.FreoPreview={play:start,sync};
})();
