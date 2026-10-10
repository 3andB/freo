(() => {
  const root=document.getElementById('production');if(!root)return;
  const base=root.dataset.base, csrf=root.dataset.csrf, $=id=>document.getElementById(id);
  let current=null, playlists=[], cursor='', models=[], recorder=null, stream=null, recorded=null, localURL=null, poll=null;
  const message=value=>{$('production-message').textContent=value;};
  async function api(url,data){const response=await fetch(url,{...(data?{method:'POST',body:data}:{}),headers:{Accept:'application/json'}});
    let value;try{value=await response.json();}catch{throw new Error('Request failed. Refresh your login or try again.');}
    if(!response.ok)throw new Error(value.error||'Request failed.');return value;}
  function formData(values={}){const data=new FormData();data.set('csrf',csrf);data.set('data',JSON.stringify(values));return data;}
  function option(select,value,label){const node=document.createElement('option');node.value=value;node.textContent=label;select.append(node);}
  function audioPlayer(parent,label,url){const title=document.createElement('p');title.textContent=label;const player=document.createElement('audio');player.controls=true;player.preload='none';player.src=url;parent.append(title,player);}
  function formValues(form){const values=Object.fromEntries(new FormData(form));form.querySelectorAll('input[type=checkbox]').forEach(x=>values[x.name]=x.checked);return values;}
  function selectValue(select,value){if(value&&!Array.from(select.options).some(x=>x.value===value))option(select,value,value);select.value=value||'';}
  function paint(row){const changed=!current||row.revision!==current.revision||row.state!==current.state;
    current=row;$('production-editor').hidden=false;$('production-title').textContent=row.title;
    $('production-state').textContent=(row.busy?'Working… ':row.state+' · ')+(row.spec.duration_ms?(row.spec.duration_ms/1000).toFixed(1)+' seconds':'')+(row.error?' — '+row.error:'');
    $('production-working').hidden=['saved','ingesting','deleted','expired'].includes(row.state);
    root.querySelectorAll('[data-mode]').forEach(x=>x.hidden=x.dataset.mode!==row.mode);
    $('production-placement').hidden=row.state!=='saved'||!row.playable;
    $('production-track').hidden=!row.track_url;if(row.track_url)$('production-track').href=row.track_url;
    $('production-delete').disabled=row.busy||row.state==='ingesting';
    root.querySelectorAll('#production-working form button').forEach(button=>button.disabled=row.busy);
    if(changed){
      const voice=root.querySelector('[data-action=voice]');voice.elements.script.value=row.spec.script||'';
      selectValue($('voice-select'),row.spec.voice_id);selectValue($('model-select'),row.spec.model_id);
      const saved=$('saved-preview');saved.replaceChildren();saved.hidden=row.state!=='saved';if(row.state==='saved'&&row.components.render)audioPlayer(saved,'Saved STATION audio',row.components.render);
      const previews=$('component-previews');previews.replaceChildren();Object.entries(row.components).forEach(([name,url])=>audioPlayer(previews,name==='render'?'Finished preview':name,url));
      const designs=$('design-previews');designs.replaceChildren();if($('design-select'))$('design-select').replaceChildren();
      row.designs.forEach((x,i)=>{audioPlayer(designs,'Voice design '+(i+1),x.url);if($('design-select'))option($('design-select'),x.id,'Preview '+(i+1));});
      const history=$('production-history');history.replaceChildren();row.attempts.forEach(x=>{const p=document.createElement('p');p.textContent=new Date(x.created_at).toLocaleString()+' · '+x.action+' · '+x.status+(x.error?' · '+x.error:'')+(x.usage&&Object.keys(x.usage).length?' · Usage: '+JSON.stringify(x.usage):'');history.append(p);});
    }
    clearTimeout(poll);if(row.busy||row.state==='ingesting')poll=setTimeout(async()=>{try{const latest=await api(base+'/'+row.id);paint(latest);if(!latest.busy&&latest.state!=='ingesting')await refresh();}catch(error){message(error.message);}},2000);
  }
  function placementOptions(){const select=$('placement-playlist'), old=select.value;select.replaceChildren();playlists.forEach(p=>option(select,p.id,p.name));if(old)select.value=old;replacementOptions();}
  function replacementOptions(){const select=$('placement-replace');select.replaceChildren();option(select,'0','Choose a track');const p=playlists.find(x=>String(x.id)===$('placement-playlist').value);(p?.items||[]).forEach(x=>option(select,x.id,x.title));}
  async function refresh(){const data=await api(base+'/drafts');playlists=data.playlists;placementOptions();const list=$('production-list');list.replaceChildren();data.drafts.forEach(row=>{const button=document.createElement('button');button.type='button';button.textContent=row.title+' · '+row.state;button.onclick=()=>paint(row);list.append(button);});}
  async function action(name,values={},file){if(!current)return;const data=formData(values);data.set('request_id',FreoUUID());data.set('revision',current.revision);if(file)data.set('audio',file,'voice-track'+(file.type.includes('webm')?'.webm':'.audio'));
    try{message('Submitting…');paint(await api(base+'/'+current.id+'/'+name,data));message('');await refresh();}catch(error){message(error.message);}}
  $('production-create').addEventListener('submit',async event=>{event.preventDefault();try{const row=await api(base+'/drafts',formData(formValues(event.target)));paint(row);await refresh();if(row.mode==='ai')await loadModels();}catch(error){message(error.message);}});
  root.querySelectorAll('[data-action]').forEach(form=>form.addEventListener('submit',event=>{event.preventDefault();action(form.dataset.action,formValues(form));}));
  $('production-upload').addEventListener('submit',event=>{event.preventDefault();action('upload',{},event.target.elements.audio.files[0]);});
  $('production-delete').onclick=async()=>{if(!current||!confirm('Delete this production and its saved audio?'))return;await action('delete');if(current.state==='deleted'){$('production-editor').hidden=true;current=null;}};
  $('production-place').addEventListener('submit',event=>{event.preventDefault();const values=formValues(event.target),p=playlists.find(x=>String(x.id)===values.playlist_id);if(!p)return;values.revision=p.revision;values.position=Number(values.position)-1;action('place',values);});
  $('placement-playlist').onchange=replacementOptions;
  async function loadVoices(more=false){try{const data=await api(base+'/voices?q='+encodeURIComponent($('voice-search').value)+(more?'&cursor='+encodeURIComponent(cursor):''));const select=$('voice-select'),selected=select.value;if(!more)select.replaceChildren();data.voices.forEach(v=>option(select,v.id,v.name));if(selected)selectValue(select,selected);cursor=data.cursor||'';$('voice-more').hidden=!cursor;await loadModels();}catch(error){message(error.message);}}
  async function loadModels(){try{const data=await api(base+'/models');models=data.models;const select=$('model-select'),selected=select.value;select.replaceChildren();models.forEach(m=>option(select,m.id,m.name));if(selected)selectValue(select,selected);modelControls();}catch(error){message(error.message);}}
  function modelControls(){const model=models.find(x=>x.id===$('model-select').value);root.querySelector('[name=stability]').step=$('model-select').value==='eleven_v3'?'.5':'.05';['style','similarity'].forEach(name=>{const node=root.querySelector('[data-control='+name+']');node.hidden=model&&model[name]===false;node.querySelector('input').disabled=node.hidden;});}
  $('model-select').onchange=modelControls;$('voice-find').onclick=()=>loadVoices();$('voice-more').onclick=()=>loadVoices(true);
  $('voice-preview').onclick=async()=>{const id=$('voice-select').value;if(!id)return;try{const response=await fetch(base+'/voices/'+encodeURIComponent(id)+'/preview');if(!response.ok){const error=await response.json();throw new Error(error.error||'Preview unavailable.');}const player=$('provider-preview');if(player.dataset.objectUrl)URL.revokeObjectURL(player.dataset.objectUrl);player.src=URL.createObjectURL(await response.blob());player.dataset.objectUrl=player.src;player.hidden=false;await player.play();}catch(error){message(error.message);}};
  $('record-start').onclick=async()=>{try{if(!navigator.mediaDevices||!window.MediaRecorder)throw new Error('Microphone recording is unavailable here. Upload an audio file instead.');
    stream=await navigator.mediaDevices.getUserMedia({audio:true});const mime=['audio/webm;codecs=opus','audio/ogg;codecs=opus','audio/mp4'].find(x=>MediaRecorder.isTypeSupported(x));recorder=new MediaRecorder(stream,mime?{mimeType:mime}:{});const chunks=[];recorder.ondataavailable=e=>{if(e.data.size)chunks.push(e.data);};
    const timer=setTimeout(()=>{if(recorder?.state==='recording')recorder.stop();},300000);
    recorder.onstop=()=>{clearTimeout(timer);stream.getTracks().forEach(t=>t.stop());recorded=new Blob(chunks,{type:recorder.mimeType});if(localURL)URL.revokeObjectURL(localURL);localURL=URL.createObjectURL(recorded);const player=$('record-preview');player.src=localURL;player.hidden=false;$('record-upload').disabled=false;$('record-start').disabled=false;$('record-stop').disabled=true;};
    recorder.start(1000);$('record-start').disabled=true;$('record-stop').disabled=false;message('Recording…');
  }catch(error){stream?.getTracks().forEach(t=>t.stop());message(error.message);}};
  $('record-stop').onclick=()=>{if(recorder?.state==='recording')recorder.stop();message('Review your recording, then choose Use recording.');};
  $('record-upload').onclick=()=>action('upload',{},recorded);
  window.addEventListener('pagehide',()=>{clearTimeout(poll);stream?.getTracks().forEach(t=>t.stop());if(localURL)URL.revokeObjectURL(localURL);});
  refresh().then(async()=>{const id=new URLSearchParams(location.search).get('draft');if(id)paint(await api(base+'/'+encodeURIComponent(id)));}).catch(error=>message(error.message));
})();
