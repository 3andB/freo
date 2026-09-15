(() => {
  const scope = window.FreoPage;
  const form=document.getElementById('media-upload-form');
  const input=document.getElementById('media-file');
  // Imaging keeps its native form submission and server-rendered result.
  if(!form||!input)return;
  const folder=document.getElementById('media-folder'),zone=form.querySelector('.drop-zone');
  const list=document.getElementById('selected-files'),summary=document.getElementById('selection-summary');
  const submit=form.querySelector('[type="submit"]'),progress=document.getElementById('upload-progress');
  let selected=[],uploading=false;
  const showSelection=files=>{
    if(uploading)return;
    selected=files.map(file=>({file,status:/\.mp3$/i.test(file.name)?'Ready':'Unsupported format — MP3 required'}));
    render();
  };
  const render=()=>{
    list.replaceChildren();summary.textContent=`${selected.length} file${selected.length===1?'':'s'} selected`;
    selected.forEach(item=>{
      const li=document.createElement('li'),name=document.createElement('b'),status=document.createElement('span');
      name.textContent=item.file.webkitRelativePath||item.file.name;status.textContent=item.status;li.append(name,status);
      if(item.review){const a=document.createElement('a');a.href=item.review;a.textContent='Review song';li.append(a);}
      list.append(li);
    });
    submit.disabled=uploading||!selected.some(item=>item.status==='Ready'||item.status.startsWith('Failed'));
  };
  document.getElementById('choose-files').addEventListener('click',()=>input.click());
  document.getElementById('choose-folder').addEventListener('click',()=>folder.click());
  input.addEventListener('change',()=>showSelection([...input.files]));folder.addEventListener('change',()=>showSelection([...folder.files]));
  const walk=async entry=>{
    if(entry.isFile)return [await new Promise((resolve,reject)=>entry.file(resolve,reject))];
    if(!entry.isDirectory)return [];
    const reader=entry.createReader();let files=[];
    while(true){const entries=await new Promise((resolve,reject)=>reader.readEntries(resolve,reject));if(!entries.length)break;for(const child of entries)files.push(...await walk(child));}
    return files;
  };
  for(const name of ['dragenter','dragover'])zone.addEventListener(name,event=>{event.preventDefault();zone.classList.add('is-dragging');});
  zone.addEventListener('dragleave',event=>{if(!zone.contains(event.relatedTarget))zone.classList.remove('is-dragging');});
  zone.addEventListener('drop',async event=>{
    event.preventDefault();zone.classList.remove('is-dragging');if(uploading)return;
    const entries=[...event.dataTransfer.items].filter(item=>item.kind==='file').map(item=>item.webkitGetAsEntry?.());
    const files=[...event.dataTransfer.files];summary.textContent='Reading files…';
    try{let found=[];if(entries.length&&entries.every(Boolean)){for(const entry of entries)found.push(...await walk(entry));}else found=files;showSelection(found);}
    catch(_){summary.textContent='Could not read that folder. Use Choose folder to try again.';}
  });
  scope.listen(window,'dragover',event=>{if([...event.dataTransfer.types].includes('Files'))event.preventDefault();});
  scope.listen(window,'drop',event=>{if([...event.dataTransfer.types].includes('Files'))event.preventDefault();});
  const upload=item=>new Promise((resolve,reject)=>{
    const request=new XMLHttpRequest(),body=new FormData();
    body.set('csrf',form.elements.csrf.value);body.append('files',item.file,item.file.name);
    request.open('POST',form.action);request.setRequestHeader('Accept','application/json');request.timeout=180000;
    request.upload.onprogress=event=>{if(event.lengthComputable){progress.querySelector('progress').value=event.loaded/event.total*100;progress.querySelector('span').textContent=`${item.file.name} · ${Math.round(event.loaded/event.total*100)}%`;}};
    request.onload=()=>{try{const result=JSON.parse(request.responseText);if(request.status>=400)throw new Error(result.errors?.join(' ')||result.message||'Upload rejected');resolve(result.jobs[0]);}catch(error){reject(new Error(request.status===413?'File exceeds the server upload limit':error instanceof SyntaxError?'Session or server unavailable. Refresh and sign in if needed.':error.message));}};
    request.onerror=()=>reject(new Error('Connection interrupted; retry this file.'));request.ontimeout=()=>reject(new Error('Upload timed out; retry this file.'));request.send(body);
  });
  const observe=async(item,url)=>{
    try{
      const response=await scope.fetch(url,{headers:{Accept:'application/json'},cache:'no-store'});if(!response.ok)throw new Error();const job=await response.json();
      item.status=({pending:'Waiting for audio processing',processing:'Processing audio',accepted:'Imported — review and enable to use in the booth',duplicate:'Already in your library',rejected:'Audio rejected'})[job.status]||`Processing result: ${job.status}`;
      item.review=job.review_url;render();
      if(['pending','processing'].includes(job.status))setTimeout(()=>observe(item,url),3000);
    }catch(_){item.status='Uploaded; status unavailable. Check Music for the result.';render();}
  };
  form.addEventListener('submit',async event=>{
    event.preventDefault();if(uploading)return;uploading=true;progress.hidden=false;render();
    for(const item of selected){
      if(item.status!=='Ready'&&!item.status.startsWith('Failed'))continue;
      if(item.file.size>Number(form.dataset.fileLimit)){item.status='File exceeds the per-song limit';continue;}
      item.status='Uploading…';render();
      try{const job=await upload(item);item.status='Uploaded — processing';observe(item,job.status_url);}
      catch(error){item.status=`Failed: ${error.message}`;}
      render();
    }
    uploading=false;progress.hidden=true;render();
  });
  render();
})();
