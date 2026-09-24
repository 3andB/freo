(() => {
  const scope=window.FreoPage,form=document.getElementById('station-settings-form');if(!form)return;
  const status=document.getElementById('station-save-status'),save=form.querySelector('.settings-save-bar button');
  let dirty=false,saving=false;
  const locationNames=['city','region','country','latitude','longitude'];
  const locationConfirmation=form.elements.location_confirmation;
  const locationSnapshot=()=>JSON.stringify(locationNames.map(name=>form.elements[name].value));
  for(const name of locationNames){
    for(const event of ['input','change'])scope.listen(form.elements[name],event,()=>{
      locationConfirmation.checked=false;locationConfirmation.value=locationSnapshot();
    });
  }
  scope.listen(locationConfirmation,'change',()=>{locationConfirmation.value=locationSnapshot();});
  const mark=()=>{dirty=true;status.textContent='Unsaved changes';};
  scope.listen(form,'input',mark);scope.listen(form,'change',mark);
  const confirmLeave=()=>!dirty||FreoDialog.confirm({title:'Leave unsaved changes?',message:'Your station edits have not been saved. Leave and discard them?',confirmLabel:'Discard changes'});
  scope.beforeLeave=confirmLeave;
  scope.listen(window,'beforeunload',event=>{if(dirty){event.preventDefault();event.returnValue='';}});
  // Operational actions submit separately; never discard a settings draft silently.
  scope.listen(document,'submit',async event=>{
    if(event.target===form||!dirty)return;
    event.preventDefault();event.stopImmediatePropagation();
    if(!event.target.closest('.settings-workspace')){if(await confirmLeave()){dirty=false;event.target.requestSubmit(event.submitter);}return;}
    status.textContent='Save your station changes before using this action.';
    status.scrollIntoView({block:'center',behavior:'smooth'});
  },{capture:true});
  scope.listen(form,'submit',async event=>{
    event.preventDefault();if(saving)return;saving=true;save.disabled=true;form.inert=true;status.textContent='Saving all changes…';
    try{
      const response=await scope.fetch(form.action,{method:'POST',body:new FormData(form),headers:{Accept:'application/json'}});
      if(!response.headers.get('content-type')?.includes('application/json'))throw Error('Your session may have expired. Sign in in another tab, then retry. Your edits are still here.');
      const result=await response.json();if(!response.ok)throw Error(result.error||'Could not save. Your edits are still here.');
      form.elements.settings_token.value=result.token;form.elements.revision.value=result.audio_revision;
      form.elements.latitude.value=result.latitude??'';form.elements.longitude.value=result.longitude??'';
      locationConfirmation.checked=false;locationConfirmation.value=locationSnapshot();
      document.getElementById('station-public-url').value=result.public_url;
      const preview=document.getElementById('station-logo-preview');preview.replaceChildren();
      if(result.logo_url){const img=document.createElement('img');img.src=result.logo_url;img.alt='Current station logo';img.className='station-logo settings-logo';const label=document.createElement('label'),remove=document.createElement('input');remove.type='checkbox';remove.name='remove_logo';remove.value='yes';label.append(remove,' Remove logo');preview.append(img,label);}
      dirty=false;status.textContent=result.message;
      form.querySelectorAll('input[type=file]').forEach(input=>input.value='');
      document.dispatchEvent(new CustomEvent('freo:form-saved',{detail:{form}}));
    }catch(error){if(error.name!=='AbortError')status.textContent=error.message;}
    finally{saving=false;save.disabled=false;form.inert=false;}
  });
  scope.listen(document.getElementById('copy-station-url'),'click',async()=>{
    const input=document.getElementById('station-public-url'),copyStatus=document.getElementById('copy-url-status');
    try{await navigator.clipboard.writeText(input.value);copyStatus.textContent=' Copied';}
    catch(_){input.focus();input.select();copyStatus.textContent=' Select and copy this URL';}
  });
  const audio=document.getElementById('audio-settings');
  async function audioStatus(){try{
    const response=await scope.fetch(audio.dataset.audioApi,{cache:'no-store'});if(!response.ok)return;
    const result=await response.json(),busy=['pending','applying'].includes(result.status);
    document.getElementById('audio-active-bitrate').textContent=result.active.bitrate;
    document.getElementById('audio-settings-status').textContent=result.error||(busy?`Saved · audio changes ${result.status}…`:'Saved audio settings are on air.');
    if(!dirty&&result.revision===Number(form.elements.revision.value))audio.querySelector('fieldset').disabled=busy;
    // Polling never overwrites an unsaved draft.
  }catch(_){document.getElementById('audio-settings-status').textContent='Audio status temporarily unavailable. Checking again…';}}
  scope.interval(audioStatus,5000);
})();
