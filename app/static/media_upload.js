(async () => {
  const form=document.getElementById('media-upload-form');if(!form)return;
  const scope=FreoPage,$=id=>document.getElementById(id),{el}=FreoCatalog,config=form.dataset;
  let items=[],uploading=false,catalog,batchSelectors,batchChips,batchCover=null;
  const message=text=>$('import-message').textContent=text;
  form.inert=true;
  try {
    const response=await scope.fetch(config.noticeUrl,{method:'POST',body:new URLSearchParams({csrf:config.csrf})});
    if(!response.ok)throw Error('Could not open the importer. Refresh to retry.');
    if((await response.json()).show) {
      const accepted=await FreoDialog.confirm({title:'Before importing music',message:'Only upload and broadcast material you own or are legally authorized to use. Uploading or broadcasting copyrighted material without the necessary rights can violate copyright law and lead to removal, legal action, or financial liability. You are responsible for obtaining the required permissions and licences.',confirmLabel:'Continue to import',signal:scope.signal});
      if(scope.signal.aborted)return;
      if(!accepted){FreoWorkspace.navigate(config.libraryUrl);return;}
    }
    form.inert=false;
  } catch(e){message(e.message);return;}
  try{catalog=await FreoCatalog.load(config.base);batchSelectors=FreoCatalog.selectors($('batch-catalog'),catalog,{}, {...config,importing:true,message});batchChips=FreoCatalog.chips($('batch-classification'),catalog);}catch(e){message(e.message);return;}
  function summary(){$('import-defaults').hidden=items.length<2;$('selection-summary').textContent=`${items.length} files · ${items.filter(i=>i.selected.checked&&!i.job).length} selected for import`;form.querySelector('[type=submit]').disabled=uploading||!items.some(i=>i.selected.checked&&!i.job&&!i.invalid);}
  function addFiles(files){
    if(uploading)return;
    for(const file of files){if(items.some(i=>i.file.name===file.name&&i.file.size===file.size&&i.file.lastModified===file.lastModified))continue;
      const item={file,cover:null,job:null,invalid:!(/\.(mp3|wav|m4a|flac)$/i.test(file.name))||file.size>Number(config.fileLimit)};
      const card=el('article',undefined,'import-card'),top=el('div',undefined,'import-card-head'),check=el('input'),title=el('input'),status=el('p'),preview=el('button','▶ Listen'),details=el('div',undefined,'import-song-fields'),classifications=el('div');
      check.type='checkbox';check.checked=!item.invalid;check.setAttribute('aria-label',`Import ${file.name}`);title.placeholder='Song title — from file metadata';title.maxLength=200;title.setAttribute('aria-label',`Song title for ${file.name}`);preview.type='button';
      const source=URL.createObjectURL(file);item.source=source;preview.onclick=()=>FreoPreview.play({uuid:source,title:title.value||file.name,artist:'Import preview',audition:source});
      const remove=el('button','Remove');remove.type='button';remove.onclick=()=>{if(uploading||item.job)return;URL.revokeObjectURL(source);items=items.filter(i=>i!==item);card.remove();summary();};
      top.append(check,el('b',file.webkitRelativePath||file.name),preview,remove);const label=el('label','Song title');label.append(title);details.append(label);const selectorHost=el('div');details.append(selectorHost);
      const selectors=FreoCatalog.selectors(selectorHost,catalog,{}, {...config,importing:true,message});const chips=FreoCatalog.chips(classifications,catalog);
      const number=el('input');number.type='number';number.min=1;number.max=999;const numberLabel=el('label','Track number');numberLabel.append(number);details.append(numberLabel);
      const art=el('button','+ Artwork');art.type='button';const image=el('img',undefined,'import-cover');image.hidden=true;art.onclick=async()=>{const cover=await FreoCatalog.chooseCover(config);if(cover){item.cover=cover;image.src=cover.url;image.hidden=false;}};
      status.setAttribute('role','status');status.textContent=item.invalid?'Choose WAV, M4A, MP3 or FLAC within the per-song size limit':'Ready to import';card.append(top,details,classifications,image,art,status);$('selected-files').append(card);
      Object.assign(item,{card,selected:check,title,selectors,chips,number,status,image,art,preview});check.onchange=summary;items.push(item);
      FreoReadMetadata(file).then(metadata=>{if(item.job||uploading)return;if(!title.value&&metadata.title)title.value=metadata.title;if(!number.value&&metadata.track_number)number.value=parseInt(metadata.track_number)||'';selectors.detected(metadata);}).catch(()=>{});
    }
    $('import-defaults').hidden=items.length<2;summary();
  }
  $('choose-files').onclick=()=>$('media-file').click();$('choose-folder').onclick=()=>$('media-folder').click();for(const id of ['media-file','media-folder'])$(id).onchange=e=>addFiles([...e.target.files]);
  async function walk(entry){if(entry.isFile)return [await new Promise((resolve,reject)=>entry.file(resolve,reject))];if(!entry.isDirectory)return [];const reader=entry.createReader();let result=[];while(true){const chunk=await new Promise((resolve,reject)=>reader.readEntries(resolve,reject));if(!chunk.length)return result;for(const child of chunk)result.push(...await walk(child));}}
  const zone=form.querySelector('.drop-zone');zone.ondragover=e=>{e.preventDefault();zone.classList.add('is-dragging');};zone.ondragleave=()=>zone.classList.remove('is-dragging');zone.ondrop=async e=>{e.preventDefault();zone.classList.remove('is-dragging');const entries=[...e.dataTransfer.items].map(i=>i.webkitGetAsEntry?.()).filter(Boolean),files=[...e.dataTransfer.files];try{let found=[];if(entries.length){for(const entry of entries)found.push(...await walk(entry));}else found=files;addFiles(found);}catch(_){message('Could not read the folder. Use Choose folder.');}};
  scope.listen(window,'dragover',e=>{if([...e.dataTransfer.types].includes('Files'))e.preventDefault();});scope.listen(window,'drop',e=>{if([...e.dataTransfer.types].includes('Files'))e.preventDefault();});
  $('batch-artwork').onclick=async()=>{const result=await FreoCatalog.chooseCover(config);if(result){batchCover=result;$('batch-status').textContent='Artwork selected. Apply it to the selected songs below.';}};
  $('apply-batch').onclick=async()=>{const values=batchSelectors.values();for(const item of items.filter(i=>i.selected.checked&&!i.job)){await item.selectors.refresh();item.selectors.set(values);item.chips.set(batchChips.values());if(batchCover){item.cover=batchCover;item.image.src=batchCover.url;item.image.hidden=false;}}$('batch-status').textContent='Choices applied. Individual song details can still be changed.';};
  function upload(item){return new Promise((resolve,reject)=>{const xhr=new XMLHttpRequest(),body=new FormData();const metadata={...item.selectors.values(),...item.chips.values()};if(item.title.value.trim())metadata.title=item.title.value.trim();if(item.number.value)metadata.track_number=item.number.value;if(item.cover)metadata.cover_id=item.cover.id;body.set('metadata',JSON.stringify(metadata));body.set('csrf',config.csrf);body.append('files',item.file,item.file.name);xhr.open('POST',form.action);xhr.setRequestHeader('Accept','application/json');xhr.timeout=180000;
    xhr.upload.onprogress=e=>{if(e.lengthComputable){$('upload-progress').querySelector('progress').value=e.loaded/e.total*100;$('upload-progress').querySelector('span').textContent=`${item.file.name} · ${Math.round(e.loaded/e.total*100)}%`;}};
    xhr.onload=()=>{try{const result=JSON.parse(xhr.responseText);if(xhr.status>=400||!result.jobs?.length)throw Error(result.message||result.errors?.join(' ')||'Upload failed');resolve(result.jobs[0]);}catch(e){reject(Error(e.message));}};xhr.onerror=()=>reject(Error('Connection interrupted. Retry import.'));xhr.ontimeout=()=>reject(Error('Upload timed out. Retry import.'));xhr.send(body);});}
  async function observe(item){try{const response=await scope.fetch(item.job.status_url,{cache:'no-store'});if(!response.ok)throw Error();const result=await response.json();const song=result.song;
    if(result.status==='duplicate')item.status.textContent='Already in your library — existing song kept';
    else if(['rejected','error'].includes(result.status))item.status.textContent=`Import failed: ${result.error||'invalid audio'}`;
    else if(song)item.status.textContent=song.error?`Processing needs attention: ${song.error}`:song.analysis==='complete'?song.broadcast:`Audio ${song.analysis}…`;
    else item.status.textContent=result.status==='processing'?'Checking audio…':'Waiting for audio processing…';
    if(result.review_url&&!item.review){item.review=el('a','Edit song');item.review.href=result.review_url;item.card.append(item.review);}
    if(song){item.preview.onclick=()=>FreoPreview.play({uuid:song.uuid,title:song.title,artist:song.artist,audition:song.audition});if(!item.title.value)item.title.value=song.title;}
    item.done=['duplicate','rejected','error'].includes(result.status)||(song&&['complete','failed'].includes(song.analysis));
    if((['rejected','error'].includes(result.status)||song?.analysis==='failed')&&!item.retry){
      item.retry=el('button',song?'Retry processing':'Retry import');item.retry.type='button';item.card.append(item.retry);
      item.retry.onclick=async()=>{try{if(song){await FreoCatalog.api(config.base.replace(/\/catalog$/,'/music/actions/process'),config.csrf,{data:JSON.stringify({songs:[song.uuid]})});item.done=false;item.status.textContent='Processing queued…';}else{item.job=null;item.done=false;item.card.querySelectorAll('input,select,button').forEach(n=>n.disabled=false);item.status.textContent='Ready to retry. Import selected music.';summary();}item.retry.remove();item.retry=null;}catch(e){item.status.textContent=e.message;}};
    }

  }catch(_){item.status.textContent='Uploaded; status temporarily unavailable. Checking again…';}}
  form.onsubmit=async e=>{e.preventDefault();if(uploading)return;uploading=true;summary();$('upload-progress').hidden=false;const pending=items.filter(i=>i.selected.checked&&!i.job&&!i.invalid);
    for(const item of pending){item.status.textContent='Uploading…';item.card.querySelectorAll('input,select,button').forEach(n=>n.disabled=true);try{item.job=await upload(item);item.preview.disabled=false;observe(item);}catch(error){item.status.textContent=error.message;item.card.querySelectorAll('input,select,button').forEach(n=>n.disabled=false);}}
    uploading=false;$('upload-progress').hidden=true;summary();};
  scope.interval(()=>{for(const item of items)if(item.job&&!item.done)observe(item);},2500);scope.cleanup(()=>items.forEach(i=>URL.revokeObjectURL(i.source)));for(const id of ['media-file','media-folder'])if($(id).files.length)addFiles([...$(id).files]);summary();
})();
