(() => {
  const player=document.querySelector('.radio-experience[data-station]');if(!player||document.querySelector('.radio-preview-notice'))return;
  const scope=window.FreoPage,base='/api/stations/'+encodeURIComponent(player.dataset.station)+'/presence';let token,ignored=false;
  async function beat(){if(ignored||document.hidden&&document.getElementById('station-audio')?.paused)return;try{if(!token){const response=await scope.fetch(base);if(!response.ok)return;const data=await response.json();ignored=!!data.ignored;token=data.csrf;}if(token)await scope.fetch(base,{method:'POST',headers:{'X-Presence-CSRF':token,'Content-Type':'application/json'},body:'{}'});}catch(_){/* Presence must never interrupt playback. */}}
  beat();scope.interval(beat,30000);scope.listen(document,'visibilitychange',()=>{if(!document.hidden)beat();});
})();
