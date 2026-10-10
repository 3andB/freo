(() => {
  const root=document.getElementById('media-job');if(!root||!['pending','processing'].includes(root.dataset.status))return;
  const scope=FreoPage;let done=false,busy=false;
  scope.interval(async()=>{if(done||busy)return;busy=true;try{
    const response=await scope.fetch(root.dataset.url,{headers:{Accept:'application/json'},cache:'no-store'});
    if(!response.ok)throw Error();const job=await response.json();
    if(['pending','processing'].includes(job.status))return;
    done=true;root.querySelector('h2').textContent=job.status==='accepted'?'Complete':job.status==='duplicate'?'Already imported':'Could not finish';
    root.querySelector('p').textContent=job.status==='accepted'?(root.dataset.kind==='delete'?'Song and audio permanently deleted from all channels.':'Media operation completed.'):'The operation could not finish. '+(root.dataset.kind==='delete'?'The song remains removed from Music. Retry file cleanup below.':job.error||'Please retry.');
    const retry=document.getElementById('retry-delete');if(retry)retry.hidden=!['error','rejected'].includes(job.status);
  }catch(_){root.querySelector('p').textContent='Status is temporarily unavailable. Reconnecting…';}finally{busy=false;}},2000);
})();
