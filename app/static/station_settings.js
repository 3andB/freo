(() => {
  const scope=window.FreoPage,button=document.getElementById('copy-station-url');if(!button)return;
  scope.listen(button,'click',async()=>{
    const input=document.getElementById('station-public-url'),status=document.getElementById('copy-url-status');
    try{await navigator.clipboard.writeText(input.value);status.textContent=' Copied';}
    catch(_){input.focus();input.select();status.textContent=' Select and copy this URL';}
  });
  const audio=document.getElementById('audio-settings');
  if(audio){
    let revision=Number(audio.querySelector('[name=revision]').value);
    scope.interval(async()=>{
      try{
        const response=await scope.fetch(audio.dataset.audioApi,{cache:'no-store'});if(!response.ok)return;
        const result=await response.json(),busy=['pending','applying'].includes(result.status);
        audio.querySelector('fieldset').disabled=busy;
        document.getElementById('audio-active-bitrate').textContent=result.active.bitrate;
        document.getElementById('audio-settings-status').textContent=result.error||(busy?`Audio changes ${result.status}…`:'Audio settings are up to date.');
        // Keep stale forms stale: another tab must not silently authorize an overwrite.
        if(result.revision!==revision){document.getElementById('audio-settings-status').textContent+=' Settings changed in another window. Refresh before editing.';audio.querySelector('fieldset').disabled=true;}
      }catch(_){document.getElementById('audio-settings-status').textContent='Status temporarily unavailable. Checking again…';}
    },2500);
  }
})();
