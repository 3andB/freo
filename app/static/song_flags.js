(() => {
  const scope=window.FreoPage,dialog=document.getElementById('song-flag-dialog');if(!dialog)return;
  const $=id=>document.getElementById('song-flag-'+id);
  let captured=null,flag=null,busy=false,generation=0;
  function buttons(disabled){dialog.querySelectorAll('#song-flag-form button').forEach(button=>button.disabled=disabled);}
  window.FreoSongFlags={open:async(song)=>{
    if(dialog.open||busy)return;
    captured={uuid:song.uuid,title:song.title,artist:song.artist,decision_id:song.decision_id};flag=null;
    const version=++generation;
    $('song').textContent=[captured.artist,captured.title].filter(Boolean).join(' — ');
    $('note').value='';$('error').textContent='';$('state').textContent='Loading review…';
    $('resolve').hidden=true;$('reopen').hidden=true;buttons(true);dialog.showModal();
    try{
      const response=await scope.fetch(dialog.dataset.url.replace('IDENTIFIER',encodeURIComponent(captured.uuid)),{cache:'no-store'});
      if(!response.ok)throw Error('Could not load this song’s flag. Close and try again.');
      const data=await response.json();if(version!==generation||!dialog.open)return;
      flag=data.flag;$('note').value=flag?.note||'';
      $('state').textContent=flag?(flag.resolved?'Resolved flag':'Open flag')+' · Updated '+new Date(flag.updated_at).toLocaleString():'Flag this song for review on this station.';
      $('resolve').hidden=!flag||flag.resolved;$('reopen').hidden=!flag||!flag.resolved;buttons(false);$('note').focus();
    }catch(error){$('error').textContent=error.message;}
  }};
  async function save(action){
    if(busy)return;busy=true;dialog.querySelector('[aria-label="Close song flag"]').disabled=true;buttons(true);$('error').textContent='';
    try{
      const body=new FormData();Object.entries({csrf:dialog.dataset.csrf,action,note:$('note').value,revision:flag?.revision||0,decision_id:captured.decision_id||''}).forEach(([key,value])=>body.set(key,value));
      const response=await scope.fetch(dialog.dataset.url.replace('IDENTIFIER',encodeURIComponent(captured.uuid)),{method:'POST',body});
      const data=await response.json();if(!response.ok)throw Error(data.message||'Could not save flag');
      dialog.close();document.dispatchEvent(new CustomEvent('song-flag-saved',{detail:{uuid:captured.uuid,flag:data.flag}}));
    }catch(error){$('error').textContent=error.message;}
    finally{busy=false;dialog.querySelector('[aria-label="Close song flag"]').disabled=false;buttons(false);}
  }
  scope.listen($('form'),'submit',event=>{event.preventDefault();save('save');});
  scope.listen($('resolve'),'click',()=>save('resolve'));scope.listen($('reopen'),'click',()=>save('reopen'));
  scope.listen(dialog,'cancel',event=>{if(busy)event.preventDefault();});
  scope.listen(dialog,'close',()=>{generation++;});
})();
