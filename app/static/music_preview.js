(() => {
  const scope = window.FreoPage;
  const player=document.getElementById('music-player');if(!player)return;
  const audio=document.getElementById('music-audio'),toggle=document.getElementById('preview-toggle');
  const seek=document.getElementById('preview-seek'),normalized=document.getElementById('preview-normalized');
  const dockSpace=()=>document.documentElement.style.setProperty('--music-preview-space',player.hidden?'0px':(player.getBoundingClientRect().height+16)+'px');
  const dockObserver=new ResizeObserver(dockSpace);dockObserver.observe(player);
  scope.cleanup(()=>{dockObserver.disconnect();document.documentElement.style.removeProperty('--music-preview-space');});
  let current=null,context=null,gain=null,version=0;
  const clock=value=>`${Math.floor((value||0)/60)}:${String(Math.floor((value||0)%60)).padStart(2,'0')}`;
  const label=(id,value)=>document.getElementById(id).textContent=value;
  const sync=()=>{
    toggle.textContent=audio.paused?'▶':'Ⅱ';toggle.setAttribute('aria-label',audio.paused?'Play preview':'Pause preview');
    document.querySelectorAll('[data-preview]').forEach(button=>{
      const playing=button.dataset.preview===current?.uuid&&!audio.paused;
      button.textContent=playing?'Ⅱ':'▶';button.classList.toggle('is-playing',playing);button.setAttribute('aria-label',`${playing?'Pause':'Play'} ${button.dataset.title||''}`);
    });
  };
  const updateGain=()=>{
    if(gain)gain.gain.value=normalized.checked?(current?.gain?.factor??1):1;
    label('preview-gain',normalized.checked?(current?.gain?.status==='Needs analysis'?'Needs analysis':`${current?.gain?.db??0} dB · ${current?.gain?.status||''}`):'Original');
  };
  const error=message=>{const el=document.getElementById('preview-error');el.hidden=false;el.textContent=message;};
  const start=async song=>{
    const attempt=++version;player.hidden=false;document.getElementById('preview-error').hidden=true;
    try{
      if(song&&song.uuid!==current?.uuid){audio.pause();current=song;audio.src=song.audition;label('preview-title',song.title);label('preview-artist',song.artist);seek.value=0;}
      else if(!audio.paused){audio.pause();sync();return;}
      if(!current)return;
      if(!context){const AudioCtx=window.AudioContext||window.webkitAudioContext;if(AudioCtx){context=new AudioCtx();gain=context.createGain();context.createMediaElementSource(audio).connect(gain);gain.connect(context.destination);}else{normalized.checked=false;normalized.disabled=true;}}
      FreoMonitor.stop();updateGain();await context?.resume();if(attempt!==version)return;await audio.play();if(attempt!==version)return;sync();
    }catch(_){if(attempt===version){error('Audio could not start. Check your connection and that the song is available.');sync();}}
  };
  scope.listen(document,'click',event=>{
    const button=event.target.closest('[data-preview]');if(!button)return;
    event.stopPropagation();const d=button.dataset;
    start({uuid:d.preview,title:d.title,artist:d.artist,audition:d.audition,gain:{factor:Number(d.gain||1),db:Number(d.gainDb||0),status:d.gainStatus}});
  });
  toggle.addEventListener('click',()=>start(current));normalized.addEventListener('change',updateGain);
  document.getElementById('preview-close').addEventListener('click',()=>{version++;audio.pause();player.hidden=true;sync();});
  document.getElementById('preview-volume').addEventListener('input',event=>audio.volume=Number(event.target.value));audio.volume=.8;
  seek.addEventListener('input',()=>{if(Number.isFinite(audio.duration))audio.currentTime=audio.duration*Number(seek.value)/100;});
  audio.addEventListener('timeupdate',()=>{label('preview-elapsed',clock(audio.currentTime));label('preview-duration',clock(audio.duration));if(audio.duration)seek.value=audio.currentTime/audio.duration*100;});
  for(const name of ['play','pause','ended'])audio.addEventListener(name,sync);
  audio.addEventListener('error',()=>error('This audio file is unavailable. Try again or inspect the song details.'));
  scope.cleanup(()=>{context?.close();delete window.FreoPreview;});
  window.FreoPreview={play:start,sync};
})();
