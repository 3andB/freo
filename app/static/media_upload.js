/* A durable review workspace. DOM controls edit explicit per-song overrides. */
(async () => {
  const form=document.getElementById('media-upload-form');if(!form)return;
  const scope=FreoPage,$=id=>document.getElementById(id),{el,api}=FreoCatalog,config=form.dataset;
  let session=null,catalog,items=new Map(),groups={},uploadQueue=[],uploading=false,finalizing=false,polling=false,batchSelectors,batchChips,batchCover=null,albumScope=null,undo=null,folderCover=null,folderCovers=new Map(),batchBusy=false,switching=false,authPaused=false,nextPollAt=0;
  const message=text=>{$('import-message').textContent=text;};
  const button=(text,fn)=>{const node=el('button',text);node.type='button';node.onclick=fn;return node;};
  const jsonGet=async url=>FreoCatalog.readResponse(await scope.fetch(url,{cache:'no-store',headers:{Accept:'application/json'}}),'load your import');
  scope.listen(document,'freo:authentication-required',()=>{authPaused=true;$('import-auth').hidden=false;});
  const isDuplicate=item=>!!item.remote?.duplicate||item.remote?.job_status==='duplicate';
  let rotation='',resetAfterImport=false,completedImport=null;
  const rotationKey=config.imports+'/rotation';
  try{rotation=localStorage.getItem(rotationKey)||'';}catch(_){}
  const rotationChoices=()=>rotation?{categories:rotation==='library'?[]:[Number(rotation)]}:{};
  const post=(url,data)=>api(url,config.csrf,{data:JSON.stringify(data)});
  const itemUrl=item=>session.url+'/items/'+item.id;
  const localKey=()=>config.imports+'/'+session.id;
  function remember(){try{localStorage.setItem(localKey(),JSON.stringify([...items.values()].filter(i=>!i.remote).map(i=>({id:i.id,name:i.name,size:i.size,path:i.path,choices:i.choices}))));}catch(_){}}
  const editable=item=>!isDuplicate(item)&&item.remote&&!['cancelled','expired'].includes(item.remote.status)&&(item.remote.status!=='finalized'||!!item.remote.song||['error','rejected'].includes(item.remote.job_status));
  const pending=item=>item.remote?.status!=='finalized';
  const attention=item=>(!item.remote&&!item.file)||!!item.error||!!item.numberWarning||(item.remote?.status==='ready'&&effective(item).artist==='Unknown Artist')||['failed','expired'].includes(item.remote?.status)||['error','rejected'].includes(item.remote?.job_status)||item.remote?.song?.analysis==='failed';
  const sourceMetadata=item=>item.remote?.detected||{};
  function groupKey(item){const d=sourceMetadata(item);return item.choices.group??(item.choices.album_id?'manual:'+item.choices.album_id:item.choices.album_name?('named:'+JSON.stringify([item.choices.album_artist||item.choices.artist_name||item.choices.artist_id,item.choices.album_name])).slice(0,300):item.choices.album_id===null?'songs':d.album?('album:'+JSON.stringify([d.album_artist||d.artist,d.album].map(value=>(value||'').trim().replace(/\s+/g,' ').toLocaleLowerCase()))).slice(0,300):item.path.includes('/')?'folder:'+item.path.split('/').slice(0,-1).join('/').slice(0,290):'songs');}
  function effective(item){const d=sourceMetadata(item),c=item.choices;return {...d,...c,artist:c.artist_id?catalog.artists.find(a=>a.id===c.artist_id)?.name||d.artist:c.artist_name||d.artist,album:c.album_id===null?'':c.album_id?catalog.albums.find(a=>a.id===c.album_id)?.name||d.album:c.album_name||d.album};}
  function songChoices(song){return {title:song.title,artist_id:song.artist_id,album_id:song.album_id,album_artist_id:song.album_artist_id,track_number:song.track_number,disc_number:song.disc_number,release_year:song.release_year,tags:song.tags,categories:song.categories,playlists:song.playlists,available_to_all:song.availability.direct};}
  function status(item){
    if(item.error)return item.error;if(isDuplicate(item))return 'Already in library · skipped · existing details kept';if(item.uploading)return `Uploading for review · ${item.progress||0}%`;if(!item.remote)return item.file?'Waiting to upload for review…':'Reselect this file to finish uploading.';
    const r=item.remote;if(r.status==='finalized'){
      if(r.job_status==='duplicate')return 'Already in library · existing song kept';
      if(['error','rejected'].includes(r.job_status))return 'Import failed · '+(r.job_error||'retry with the source file');
      if(r.song)return r.song.error|| (r.song.analysis==='complete'?'Imported · '+r.song.broadcast:'Imported · audio '+r.song.analysis+'…');
      return 'Importing · checking audio…';
    }
    return {pending:'Uploaded · waiting to read details…',preparing:'Reading audio and metadata…',ready:'Ready to import'+(effective(item).artist==='Unknown Artist'?' · Artist not found. Choose an artist or import as Unknown Artist.':'')+(item.numberWarning?' · '+item.numberWarning:''),failed:r.error,expired:r.error}[r.status]||r.status;
  }
  function summary(){
    const all=[...items.values()],selectable=all.filter(i=>pending(i)&&!isDuplicate(i)),selected=selectable.filter(i=>i.selected),ready=selected.filter(i=>i.remote?.status==='ready'&&(!i.error||i.errorMode==='save'));
    const imported=all.filter(i=>i.remote?.song&&!isDuplicate(i)).length,duplicates=all.filter(isDuplicate).length,failed=all.filter(i=>!isDuplicate(i)&&attention(i)).length;
    form.classList.toggle('has-files',!!all.length);
    $('import-tools').hidden=!all.length;$('selection-summary').textContent=all.length?`${selected.length} selected · ${ready.length} ready · ${all.length} files`:'Choose music to get started';
    $('import-completion').textContent=[imported?`${imported} in your library`:'',duplicates?`${duplicates} already in library · skipped`:'',failed?`${failed} need attention — ready songs can still be imported`:'',uploading?'Uploading for review…':''].filter(Boolean).join(' · ');
    const submit=form.querySelector('[type=submit]');submit.disabled=finalizing||batchBusy||!ready.length;
    submit.textContent=finalizing?'Starting import…':ready.length?`Import ${ready.length} ready ${ready.length===1?'song':'songs'}`:selectable.length?'Preparing songs…':'Import music';
    if(!ready.length&&selectable.length&&!uploading&&!selectable.some(i=>['pending','preparing'].includes(i.remote?.status)))submit.textContent='Select ready songs';
    const active=all.some(i=>!isDuplicate(i)&&(['pending','preparing'].includes(i.remote?.status)||['pending','processing'].includes(i.remote?.job_status)));
    const processing=all.some(i=>!isDuplicate(i)&&['pending','processing'].includes(i.remote?.song?.analysis));
    submit.hidden=!!all.length&&!selectable.length&&!active;
    $('view-imported').hidden=!imported&&!completedImport;$('view-imported').href=imported?session.library_url:completedImport?.url||config.libraryUrl;
    if(all.length&&!selectable.length&&!active)$('selection-summary').textContent=failed?'Some songs need attention':processing?'Imported · finishing audio processing':'Import complete';
    else if(active&&!selectable.length)$('selection-summary').textContent='Importing your songs…';
    $('select-all').checked=!!selectable.length&&selectable.every(i=>i.selected);
    $('select-all').indeterminate=selectable.some(i=>i.selected)&&!$('select-all').checked;
    $('edit-selected').disabled=!all.some(i=>i.selected&&editable(i)&&pending(i));
    $('new-import').disabled=uploading||finalizing||batchBusy||switching;$('import-sessions').disabled=uploading||finalizing||batchBusy||switching;
    $('import-rotation').disabled=uploading||finalizing||batchBusy;
    positionActions();
  }
  function drawRow(item){
    const value=item.remote?.song&&!item.dirty&&!item.saving?item.remote.song:effective(item);
    item.heading.textContent=(value.track_number?`${value.disc_number>1?value.disc_number+'.':''}${value.track_number} · `:'')+(value.title||item.name);
    item.subtitle.textContent=[value.artist,value.album,value.duration_ms?`${Math.floor(value.duration_ms/60000)}:${String(Math.floor(value.duration_ms/1000)%60).padStart(2,'0')}`:''].filter(Boolean).join(' · ')||item.name;
    item.status.textContent=status(item);item.status.classList.toggle('import-error',attention(item));
    item.check.checked=item.selected;item.check.disabled=!pending(item)||isDuplicate(item)||finalizing;
    item.editor.disabled=!editable(item)||finalizing;item.edit.disabled=!editable(item);
    item.card.hidden=$('attention-only').checked&&!attention(item);
    item.save.textContent=item.saving?'Saving…':item.dirty?'Save details':'Saved';item.save.disabled=!item.dirty||item.saving;
    item.card.classList.toggle('is-imported',!pending(item));item.remove.textContent=pending(item)?'Remove':'Dismiss';
    item.retry.hidden=!((item.error&&item.errorMode!=='save')||(!item.remote&&!item.file)||['failed','expired'].includes(item.remote?.status)||['error','rejected'].includes(item.remote?.job_status)||item.remote?.song?.analysis==='failed');item.retry.textContent=item.remote?.song?'Retry processing':item.remote?.status==='failed'?'Retry preparation':!item.remote&&!item.file?'Choose file':'Retry';item.reload.hidden=!item.conflict;
    const r=item.remote;if(r?.song){item.preview.disabled=false;item.preview.onclick=()=>FreoPreview.play({uuid:r.song.uuid,title:r.song.title,artist:r.song.artist,audition:r.song.audition});item.review.href=r.review_url;item.review.hidden=false;item.review.textContent='View song';if(r.album_url){item.albumLink.href=r.album_url;item.albumLink.hidden=false;}}
    else{item.preview.disabled=!item.source&&!r?.preview_url;item.preview.onclick=()=>FreoPreview.play({uuid:item.id,title:value.title||item.name,artist:value.artist||'Import preview',audition:r?.preview_url||item.source});}
    if(r?.duplicate){item.review.href=r.duplicate.review_url;item.review.hidden=false;item.review.textContent='View existing song';}
    item.enableWrap.hidden=!pending(item)||isDuplicate(item);
    const cover=item.coverUrl||r?.song?.cover||r?.cover_url;if(cover){item.image.src=cover;item.image.hidden=false;}else item.image.hidden=true;
  }
  function fill(item){
    const value=effective(item),c=item.choices;
    item.title.value=c.title??value.title??'';item.number.value=c.track_number??value.track_number??'';item.disc.value=c.disc_number??value.disc_number??'';item.year.value=c.release_year??value.release_year??'';
    item.selectors.set(c);item.selectors.detected(sourceMetadata(item));item.chips.set(c);item.keepDisabled.checked=!!c.keep_disabled;item.sharing.checked=!!c.available_to_all;item.sharing.disabled=(c.audio_kind||item.remote?.song?.audio_kind||'MUSIC')!=='MUSIC';
  }
  function change(item){item.dirty=true;item.generation++;item.error='';clearTimeout(item.timer);item.timer=setTimeout(()=>{if(!batchBusy)save(item);},600);drawRow(item);summary();}
  async function save(item){
    clearTimeout(item.timer);if(!item.dirty||!editable(item)||item.conflict)return;if(item.saving){await item.saving;return save(item);}
    const generation=item.generation,snapshot=structuredClone(item.choices),revision=item.remote.revision;
    item.saving=(async()=>{try{const next=await post(itemUrl(item),{revision,choices:snapshot});item.remote=next;
      if(generation===item.generation){item.dirty=false;item.error='';}
    }catch(error){item.error=error.message;item.errorMode='save';if(error.message.includes('another tab'))item.conflict=true;}finally{item.saving=null;drawRow(item);summary();}})();
    drawRow(item);await item.saving;
  }
  async function flush(targets=[...items.values()]){
    for(const item of targets)clearTimeout(item.timer);
    await Promise.all(targets.map(i=>i.saving));
    const drafts=targets.filter(i=>i.dirty&&editable(i)&&!i.conflict);
    if(drafts.length>1){
      const snapshots=drafts.map(i=>({id:i.id,revision:i.remote.revision,choices:structuredClone(i.choices),generation:i.generation}));
      const saving=(async()=>{try{
        const next=await post(session.url,{action:'save-items',items:snapshots.map(({generation,...data})=>data)});
        for(const snapshot of snapshots){const item=items.get(snapshot.id),remote=next.items.find(i=>i.id===snapshot.id);if(!item||!remote)continue;item.remote=remote;if(item.generation===snapshot.generation){item.dirty=false;item.error='';}}
      }catch(error){for(const item of drafts){item.error=error.message;item.errorMode='save';if(error.message.includes('another tab'))item.conflict=true;}}
      finally{for(const item of drafts){item.saving=null;drawRow(item);}summary();}})();
      for(const item of drafts)item.saving=saving;
      await saving;
    }
    await Promise.all(targets.filter(i=>!drafts.includes(i)||drafts.length===1).map(save));
    if(targets.some(i=>i.dirty))throw Error('Save or resolve the highlighted song details before continuing.');
  }
  for(const id of ['import-audio-kind','import-audio-subtype'])$(id).onchange=()=>{for(const item of items.values()){if(item.selected&&pending(item)&&editable(item)){item.choices.audio_kind=$('import-audio-kind').value;item.choices.audio_subtype=item.choices.audio_kind==='STATION'?$('import-audio-subtype').value:'';if(item.choices.audio_kind!=='MUSIC')item.choices.available_to_all=false;fill(item);change(item);}}};
  function makeItem(data,file=null){
    const item={id:data.id,name:data.name,size:data.size,path:data.path||'',choices:structuredClone(data.choices||(file?{...structuredClone(groups.__defaults__||{}),...rotationChoices(),audio_kind:$('import-audio-kind').value,audio_subtype:$('import-audio-kind').value==='STATION'?$('import-audio-subtype').value:''}:{})),remote:data.status?data:null,file,selected:!data.duplicate,dirty:false,generation:0};
    if(item.choices.audio_kind&&item.choices.audio_kind!=='MUSIC')item.choices.available_to_all=false;
    if(data.song)item.choices={...songChoices(data.song),group:groupKey(item)};
    item.source=file?URL.createObjectURL(file):null;
    const card=el('article',undefined,'import-card'),head=el('div',undefined,'import-card-head'),check=el('input'),copy=el('div',undefined,'import-row-copy'),heading=el('b'),subtitle=el('small');
    check.type='checkbox';check.setAttribute('aria-label',`Select ${item.name}`);check.onchange=()=>{item.selected=check.checked;summary();};copy.append(heading,subtitle);
    const editor=el('fieldset',undefined,'import-row-editor');editor.hidden=false;const legend=el('legend',`Details for ${item.name}`);legend.className='sr-only';editor.append(legend);
    const edit=button('Hide details',()=>{editor.hidden=!editor.hidden;edit.textContent=editor.hidden?'Edit details':'Hide details';edit.setAttribute('aria-expanded',String(!editor.hidden));if(!editor.hidden)item.title.focus();});edit.setAttribute('aria-expanded','true');edit.setAttribute('aria-label',`Edit details for ${item.name}`);
    const preview=button('▶ Listen',()=>{}),remove=button('Remove',async()=>{if(item.uploading)return;try{if(item.saving)await item.saving;if(item.remote)await post(itemUrl(item),{action:'dismiss',revision:item.remote.revision});clearTimeout(item.timer);item.selectors.destroy();if(item.source)URL.revokeObjectURL(item.source);items.delete(item.id);card.remove();remember();renderGroups();}catch(e){message(e.message);}});
    head.append(check,copy,preview,edit,button('Apply artist & album to all',()=>applyIdentity(item)),remove);card.append(head);
    const fields=el('div',undefined,'import-song-fields');const input=(label,type='text')=>{const wrap=el('label',label),n=el('input');n.type=type;n.setAttribute('aria-label',`${label} for ${item.name}`);wrap.append(n);fields.append(wrap);return n;};
    const title=input('Song title');title.maxLength=200;const selectorHost=el('div',undefined,'import-row-catalog');fields.append(selectorHost);
    const number=input('Track number','number'),disc=input('Disc number','number'),year=input('Year','number');number.min=disc.min=1;number.max=999;disc.max=99;year.min=1000;year.max=3000;
    const classifications=el('div');const selectors=FreoCatalog.selectors(selectorHost,catalog,item.choices,{...config,get csrf(){return form.dataset.csrf;},importing:true,target:item.name,message,change:changedKey=>{
      for(const key of ['artist_id','artist_name','album_id','album_name','album_artist_id'])delete item.choices[key];Object.assign(item.choices,selectors.values());
      const fileFields=new Set(item.choices.file_fields||[]);for(const key of ['artist_id','album_id'])if(item.choices[key]===undefined)fileFields.add(key);else fileFields.delete(key);item.choices.file_fields=[...fileFields];
      if(!pending(item)){const d=sourceMetadata(item);if(!item.choices.artist_id)item.choices.artist_name=d.artist||'Unknown Artist';if(item.choices.album_id===undefined){if(d.album){item.choices.album_name=d.album;item.choices.album_artist=d.album_artist||d.artist;}else item.choices.album_id=null;}}
      change(item);
    }});
    const chips=FreoCatalog.chips(classifications,catalog,item.choices,['playlists','categories','tags']);classifications.addEventListener('click',()=>{Object.assign(item.choices,chips.values());change(item);});
    for(const [node,key] of [[title,'title'],[number,'track_number'],[disc,'disc_number'],[year,'release_year']])node.oninput=()=>{if(key==='title'){if(node.value.trim())item.choices.title=node.value.trim();else delete item.choices.title;}else item.choices[key]=node.value?Number(node.value):null;change(item);};
    const keepDisabled=el('input');keepDisabled.type='checkbox';keepDisabled.onchange=()=>{item.choices.keep_disabled=keepDisabled.checked;change(item);};const enableWrap=el('label',undefined,'import-enable');enableWrap.append(keepDisabled,document.createTextNode(' Keep disabled after import'));const rotation=el('p','An active category makes enabled songs available for rotation.','footnote');
    const image=el('img',undefined,'import-cover');image.alt='Cover artwork';image.hidden=true;
    const art=button('Choose artwork',async()=>{try{const cover=await FreoCatalog.chooseCover(config);if(cover){item.choices.cover_id=cover.id;item.coverUrl=cover.url;change(item);}}catch(e){message(e.message);}});
    const coverNote=el('p','Artwork assigned to an existing album also updates its other songs.','footnote');
    const sharing=el('input');sharing.type='checkbox';sharing.onchange=()=>{item.choices.available_to_all=sharing.checked;change(item);};const shareWrap=el('label',undefined,'import-enable');shareWrap.append(sharing,document.createTextNode(' Available to all stations'));
    const advanced=el('details',undefined,'import-more'),extraFields=el('div',undefined,'import-extra-fields');advanced.open=true;advanced.append(el('summary','Track details, artwork & rotation'));for(const node of [number,disc,year])extraFields.append(node.parentElement);advanced.append(el('p',`Source: ${item.path||item.name}`,'footnote'),extraFields,classifications,shareWrap,rotation,enableWrap,image,art,coverNote);const saveButton=button('Saved',()=>save(item));editor.append(fields,advanced,saveButton);card.append(editor);
    const statusNode=el('p',undefined,'import-row-status');statusNode.setAttribute('role','status');const retry=button('Retry',async()=>{
      try{if(item.dirty&&item.remote)await flush([item]);if(!item.remote){item.error='';if(item.file){uploadQueue.push(item);pump();}else $('media-file').click();}
      else if(item.remote.song){await api(config.base.replace(/\/catalog$/,'/music/actions/process'),config.csrf,{data:JSON.stringify({songs:[item.remote.song.uuid]})});item.error='';poll();}
      else if(item.remote.status==='failed'||['error','rejected'].includes(item.remote.job_status)){item.remote=await post(itemUrl(item),{revision:item.remote.revision,action:'retry'});item.error='';drawRow(item);}
      else message('Add the source file again to retry this import. Your other songs are safe.');}catch(e){message(e.message);}
    });retry.hidden=true;
    const reload=button('Reload saved details',async()=>{item.dirty=false;item.conflict=false;item.error='';await poll();fill(item);drawRow(item);});reload.hidden=true;
    const review=el('a','View song'),albumLink=el('a','View album');review.hidden=albumLink.hidden=true;card.append(statusNode,retry,reload,review,albumLink);
    Object.assign(item,{card,check,heading,subtitle,editor,edit,preview,remove,title,number,disc,year,selectors,chips,sharing,keepDisabled,enableWrap,image,status:statusNode,retry,reload,review,albumLink,save:saveButton});items.set(item.id,item);fill(item);drawRow(item);return item;
  }
  function renderGroups(){
    const host=$('selected-files'),map=new Map();
    for(const item of items.values()){const key=groupKey(item);if(!map.has(key))map.set(key,[]);map.get(key).push(item);}
    for(const [key,members] of map){const counts=new Map();for(const item of members){const value=effective(item),number=`${value.disc_number||1}:${value.track_number}`;counts.set(number,(counts.get(number)||0)+1);}for(const item of members){const value=effective(item);item.numberWarning=key==='songs'||members.length<2||item.remote?.status!=='ready'?'':!value.track_number?'Track number missing':counts.get(`${value.disc_number||1}:${value.track_number}`)>1?'Repeated track number on this disc':'';}}
    for(const members of map.values())members.sort((a,b)=>(effective(a).disc_number||1)-(effective(b).disc_number||1)||(effective(a).track_number||999)-(effective(b).track_number||999)||a.name.localeCompare(b.name,undefined,{numeric:true}));
    for(const header of host.querySelectorAll('.import-group-head')){
      const members=map.get(header.dataset.group);if(!members?.length)continue;const first=members[0],d=effective(first),owner=catalog.artists.find(a=>a.id===(first.choices.album_artist_id||first.choices.artist_id))?.name;
      header.querySelector('h2').textContent=d.album||first.path.split('/').slice(0,-1).join('/');header.querySelector('p').textContent=`${owner||d.album_artist||d.artist||'Album'} · ${members.length} songs`;
      const art=header.querySelector('img'),cover=first.coverUrl||first.remote?.song?.cover||first.remote?.cover_url;art.hidden=!cover;if(cover)art.src=cover;
    }
    const layout=JSON.stringify([...map].map(([key,members])=>[key,members.map(i=>i.id)]));
    if(host.dataset.layout===layout||host.contains(document.activeElement)){for(const item of items.values()){if(!host.contains(item.card))host.append(item.card);drawRow(item);}summary();return;}
    host.dataset.layout=layout;
    for(const old of host.querySelectorAll('.import-group-head'))old.remove();
    for(const [key,members] of map){
      if(key!=='songs'){
        const d=effective(members[0]),header=el('div',undefined,'import-group-head'),copy=el('div'),art=el('img',undefined,'import-cover');header.dataset.group=key;art.alt='Album artwork';const cover=members[0].coverUrl||members[0].remote?.song?.cover||members[0].remote?.cover_url;art.hidden=!cover;if(cover)art.src=cover;header.append(art);copy.append(el('h2',d.album||members[0].path.split('/').slice(0,-1).join('/')),el('p',`${d.album_artist||d.artist||'Album'} · ${members.length} songs`));
        header.append(copy,button('Edit album',()=>openBatch(key)),button('Show individually',async()=>{for(const item of members.filter(pending)){item.choices.group='songs';change(item);}try{await flush();renderGroups();}catch(e){message(e.message);}}));host.append(header);
      }
      members.sort((a,b)=>(effective(a).disc_number||1)-(effective(b).disc_number||1)||(effective(a).track_number||999)-(effective(b).track_number||999)||a.name.localeCompare(b.name,undefined,{numeric:true}));
      for(const item of members){host.append(item.card);drawRow(item);}
    }
    summary();
  }
  function inherit(item){const key=groupKey(item);if(!item.inherited&&!item.choices.inherited_group&&item.remote?.status==='ready'&&groups[key]&&pending(item)){
    item.inherited=true;for(const [field,value] of Object.entries(groups[key]))if(!(field in item.choices)&&!(item.choices.file_fields||[]).includes(field))item.choices[field]=structuredClone(value);item.choices.inherited_group=key;
    fill(item);change(item);
  }}
  function merge(next){
    if(next.id!==session?.id)return;
    groups=next.groups||{};
    for(const data of next.items){let item=items.get(data.id);if(item?.remote&&data.revision<item.remote.revision)continue;if(!item){item=makeItem(data);item.inherited=true;}
      else if(!item.dirty&&!item.saving){const becameSong=!item.remote?.song&&data.song;const changed=JSON.stringify(item.remote?.detected)!==JSON.stringify(data.detected)||item.remote?.revision!==data.revision||becameSong;item.remote=data;item.error='';if(becameSong||data.song)item.choices={...songChoices(data.song),group:groupKey(item)};else item.choices=structuredClone(data.choices);if(changed)fill(item);}
      else if(item.remote){const detectedChanged=JSON.stringify(item.remote.detected)!==JSON.stringify(data.detected);item.remote={...item.remote,status:data.status,detected:data.detected,song:data.song,job_status:data.job_status,job_error:data.job_error,duplicate:data.duplicate};if(detectedChanged)fill(item);}
      if(isDuplicate(item)){item.selected=false;item.dirty=false;}else inherit(item);drawRow(item);
    }
    renderGroups();
  }
  async function poll(){if(!session||polling||finalizing||switching||authPaused)return;polling=true;try{const next=await jsonGet(session.url);if(next.items.some(i=>i.song&&(!catalog.artists.some(a=>a.id===i.song.artist_id)||(i.song.album_id&&!catalog.albums.some(a=>a.id===i.song.album_id)))))await FreoCatalog.load(config.base);merge(next);await completeImport();return true;}catch(e){message(e.message);return false;}finally{polling=false;const busy=[...items.values()].some(i=>pending(i)&&!isDuplicate(i)||['pending','processing'].includes(i.remote?.job_status)||['pending','processing'].includes(i.remote?.song?.analysis));nextPollAt=Date.now()+(busy?2500:30000);}}
  async function completeImport(){
    if(!resetAfterImport||uploading||finalizing||batchBusy||switching)return;
    const rows=[...items.values()];
    if(!rows.length||rows.some(i=>i.dirty||i.saving||i.error||(!isDuplicate(i)&&(!i.remote?.song||i.remote.song.analysis!=='complete'))))return;
    const count=rows.filter(i=>!isDuplicate(i)).length,url=session.library_url;
    await openSession();resetAfterImport=false;completedImport={url,count};
    for(const id of ['media-file','media-folder'])$(id).value='';
    $('attention-only').checked=false;
    $('import-success').hidden=false;$('import-success').textContent=`${count} song${count===1?'':'s'} imported successfully. Ready for your next song.`;
    $('view-imported').href=url;$('view-imported').hidden=false;
    message('Choose more music, or select Done to return to your library.');
  }
  async function sessionList(){const result=await jsonGet(config.imports);if(result.csrf)config.csrf=result.csrf;const select=$('import-sessions');select.replaceChildren();for(const row of result.sessions)select.append(new Option(`${row.name||'Import'} · ${{empty:'Ready for songs',draft:'Resume draft',processing:'Processing',attention:'Needs attention',complete:'Completed'}[row.state]||'Import'} · ${row.count} files · ${new Date(row.created_at).toLocaleDateString()}`,row.id));if(session&&!result.sessions.some(s=>s.id===session.id))select.append(new Option('New import',session.id));if(session)select.value=session.id;return result.sessions;}
  async function openSession(identifier){
    if(switching)return;switching=true;form.inert=true;try{
    await flush();const next=identifier?await jsonGet(config.imports+'/'+identifier):await post(config.imports,{});for(const item of items.values()){clearTimeout(item.timer);item.selectors.destroy();if(item.source)URL.revokeObjectURL(item.source);}items=new Map();folderCover=null;folderCovers.clear();$('folder-artwork-choice').hidden=true;$('folder-artworks').replaceChildren();$('selected-files').replaceChildren();delete $('selected-files').dataset.layout;$('import-defaults').hidden=true;undo=null;$('undo-batch').hidden=true;
    session=next;groups=session.groups||{};merge(session);
    try{const local=JSON.parse(localStorage.getItem(localKey())||'[]');for(const data of local)if(!items.has(data.id))makeItem(data);}catch(_){}
    renderGroups();await sessionList();
    }finally{if(session)$('import-sessions').value=session.id;switching=false;form.inert=false;summary();}
  }
  function uploadResult(xhr){
    const result=FreoCatalog.decodeResponse(xhr.status,xhr.responseURL,xhr.getResponseHeader('Content-Type'),xhr.responseText,'upload');
    if(!result||typeof result!=='object'||!result.id||!result.status)throw Error('The server returned an invalid upload response. Retry this file.');
    return result;
  }
  async function pump(){
    if(uploading)return;uploading=true;summary();
    while(uploadQueue.length&&!scope.signal.aborted){const item=uploadQueue.shift();if(!items.has(item.id))continue;item.uploading=true;item.error='';
      try{
        const data=await new Promise((resolve,reject)=>{const xhr=new XMLHttpRequest(),body=new FormData();body.set('id',item.id);body.set('path',item.path);body.set('csrf',config.csrf);body.set('data',JSON.stringify(item.choices));body.append('file',item.file,item.name);xhr.open('POST',session.url+'/files');xhr.setRequestHeader('Accept','application/json');xhr.timeout=180000;const abort=()=>xhr.abort();scope.signal.addEventListener('abort',abort,{once:true});xhr.onloadend=()=>scope.signal.removeEventListener('abort',abort);
          xhr.upload.onprogress=e=>{if(e.lengthComputable){item.progress=Math.round(e.loaded/e.total*100);drawRow(item);}};
          xhr.onload=()=>{try{resolve(uploadResult(xhr));}catch(e){reject(e);}};xhr.onerror=xhr.ontimeout=xhr.onabort=()=>reject(Error('Upload interrupted. Retry this file.'));xhr.send(body);
        });item.remote=data;if(isDuplicate(item))item.selected=false;remember();fill(item);
      }catch(e){item.errorMode='upload';if(e.message.includes('fresh file identifier')){items.delete(item.id);item.id=FreoUUID();items.set(item.id,item);remember();item.error='Upload interrupted. Retry this file.';}else item.error=e.message;}finally{item.uploading=false;drawRow(item);summary();}
    }
    uploading=false;summary();try{await sessionList();await poll();}catch(e){message(e.message);}
  }
  function addFiles(files){
    let skipped=0;
    for(const file of files){
      if(!/\.(mp3|wav|m4a|flac)$/i.test(file.name)){if(/^(cover|folder)\.(jpe?g|png)$/i.test(file.name)){const key=file.webkitRelativePath||file.name;folderCovers.set(key,file);if(![...$('folder-artworks').options].some(o=>o.value===key))$('folder-artworks').append(new Option(key,key));$('folder-artwork-choice').hidden=false;}else skipped++;continue;}
      let item=[...items.values()].find(i=>i.name===file.name&&i.size===file.size&&i.path===(file.webkitRelativePath||'')&&(!i.remote||i.file?.lastModified===file.lastModified)&&!['finalized','expired','cancelled'].includes(i.remote?.status));
      if(item?.remote||item?.uploading)continue;
      if(!item)item=makeItem({id:FreoUUID(),name:file.name,size:file.size,path:file.webkitRelativePath||''},file);else{item.file=file;item.source=URL.createObjectURL(file);}
      if(!file.size||file.size>Number(config.fileLimit)){item.error=!file.size?'This file is empty.':'This file exceeds the per-song size limit.';item.selected=false;drawRow(item);continue;}
      if(!uploadQueue.includes(item))uploadQueue.push(item);
    }
    if(skipped)message(`${skipped} non-audio file${skipped===1?' was':'s were'} skipped. You can add a cover with Choose artwork.`);

    remember();renderGroups();pump();
  }
  function openBatch(key=null){
    if(batchBusy)return;
    $('batch-sharing').value='';$('batch-future').checked=false;albumScope=key;$('group-selected').checked=!!key;batchSelectors.reset();batchChips.set({});batchChips.clearTouched();batchCover=null;
    if(key)for(const item of items.values())item.selected=groupKey(item)===key&&pending(item)&&!isDuplicate(item);
    const selected=[...items.values()].filter(i=>i.selected&&pending(i));$('preserve-artists').checked=new Set(selected.map(i=>effective(i).artist)).size>1;
    $('batch-heading').textContent=key?'Edit album details':`Edit ${selected.length} selected songs`;$('batch-status').textContent='';$('import-defaults').hidden=false;summary();for(const item of items.values())drawRow(item);$('import-defaults').scrollIntoView({block:'start',behavior:'instant'});
  }
  async function applyBatch(numbering=false){
    if(batchBusy)return;
    const selected=[...$('selected-files').querySelectorAll('.import-card')].map(card=>[...items.values()].find(i=>i.card===card)).filter(i=>i.selected&&pending(i)&&editable(i));
    if(!selected.length)return;
    const patch=batchSelectors.patch(),values=batchSelectors.values(),classifications=batchChips.values(),touched=batchChips.touched();
    if($('group-selected').checked&&!albumScope){if(!values.album_id){$('batch-status').textContent='Choose or create an album to group these songs.';return;}albumScope='manual:'+values.album_id;}
    batchBusy=true;$('apply-batch').disabled=$('number-tracks').disabled=$('undo-batch').disabled=true;summary();
    undo={items:selected.map(item=>({id:item.id,choices:structuredClone(item.choices)})),group:albumScope,defaults:albumScope?structuredClone(groups[albumScope]||null):null,future:structuredClone(groups.__defaults__||null)};
    const shared=structuredClone(albumScope?groups[albumScope]||{}:groups.__defaults__||{});
    for(const [index,item] of selected.entries()){
      if(albumScope&&$('group-selected').checked){item.choices.group=albumScope;shared.group=albumScope;}
      for(const [key,value] of Object.entries(patch)){
        if(key==='artist_id'&&$('preserve-artists').checked)continue;
        const name=key==='artist_id'?'artist_name':'album_name';delete item.choices[name];
        if(value==='file'){delete item.choices[key];item.choices.file_fields=[...new Set([...(item.choices.file_fields||[]),key])];}else{item.choices[key]=value;item.choices.file_fields=(item.choices.file_fields||[]).filter(field=>field!==key);}
        if(key==='artist_id'&&!('album_id' in patch)){delete item.choices.album_id;delete item.choices.album_artist_id;}
        if(value!=='file')shared[key]=value;else delete shared[key];
        if(key==='artist_id'&&!('album_id' in patch)){delete shared.album_id;delete shared.album_artist_id;}
      }
      if('album_id' in patch&&values.album_id){item.choices.album_artist_id=values.album_artist_id;shared.album_artist_id=values.album_artist_id;}
      for(const key of touched){const current=new Set(item.choices[key]||[]),chosen=classifications[key],op=$('classification-operation').value;
        item.choices[key]=op==='replace'?chosen:op==='remove'?[...current].filter(id=>!chosen.includes(id)):[...new Set([...current,...chosen])];shared[key]=op==='replace'?chosen:op==='remove'?(shared[key]||[]).filter(id=>!chosen.includes(id)):[...new Set([...(shared[key]||[]),...chosen])];}
      if($('batch-sharing').value){item.choices.available_to_all=$('batch-sharing').value==='all';shared.available_to_all=item.choices.available_to_all;}
      if(batchCover){item.choices.cover_id=batchCover.id;item.coverUrl=batchCover.url;shared.cover_id=batchCover.id;}
      if(numbering)item.choices.track_number=index+1;
      fill(item);change(item);
    }
    try{await flush();if(albumScope){const result=await post(session.url,{action:'group',key:albumScope,choices:shared});groups=result.groups;} if($('batch-future').checked){const nextDefaults={...groups.__defaults__};for(const key of touched)nextDefaults[key]=shared[key];if($('batch-sharing').value)nextDefaults.available_to_all=shared.available_to_all;const result=await post(session.url,{action:'group',key:'__defaults__',choices:nextDefaults});groups=result.groups;} $('batch-status').textContent=`Updated ${selected.length} songs. You can still change individual details.`;$('undo-batch').hidden=false;renderGroups();}catch(e){message(e.message);}finally{batchBusy=false;$('apply-batch').disabled=$('number-tracks').disabled=$('undo-batch').disabled=false;summary();}
  }
  async function applyIdentity(source){
    if(batchBusy||finalizing)return;
    const selected=[...items.values()].filter(editable);
    if(!selected.length)return;
    batchBusy=true;summary();
    try{
      await flush();
      const value=effective(source),c=source.choices;
      const patch=c.artist_id?{artist_id:c.artist_id}:{artist_name:value.artist||'Unknown Artist'};
      if(c.album_id){patch.album_id=c.album_id;patch.album_artist_id=c.album_artist_id||catalog.albums.find(a=>a.id===c.album_id)?.artist_id;}
      else if(value.album){patch.album_name=value.album;patch.album_artist=value.album_artist||value.artist||'Unknown Artist';}
      else patch.album_id=null;
      undo={items:selected.map(item=>({id:item.id,choices:structuredClone(item.choices)}))};
      for(const item of selected){
        for(const key of ['artist_id','artist_name','album_id','album_name','album_artist_id','album_artist'])delete item.choices[key];
        Object.assign(item.choices,patch);item.choices.file_fields=(item.choices.file_fields||[]).filter(key=>!['artist_id','album_id'].includes(key));
        fill(item);change(item);
      }
      await flush(selected);renderGroups();$('undo-batch').hidden=false;
      const skipped=items.size-selected.length;
      message(`Artist and album applied to ${selected.length} songs.${skipped?' '+skipped+' unavailable or duplicate songs skipped.':''}`);
    }catch(error){message(error.message);$('undo-batch').hidden=!undo;}
    finally{batchBusy=false;summary();}
  }
  function positionActions(){const bounds=form.getBoundingClientRect(),bar=form.querySelector('.import-action-bar'),player=$('music-player'),height=player&&!player.hidden?player.getBoundingClientRect().height:0,left=Math.max(8,bounds.left);bar.style.left=left+'px';bar.style.width=Math.max(0,Math.min(innerWidth-left-8,bounds.width))+'px';bar.style.bottom=(height+12)+'px';const space=(bar.getBoundingClientRect().height+height+24)+'px';form.style.paddingBottom=space;form.style.setProperty('--import-dock-space',space);}
  positionActions();scope.listen(window,'resize',()=>scope.frame(positionActions));
  const layoutObserver=new ResizeObserver(positionActions);layoutObserver.observe(form.querySelector('.import-action-bar'));if($('music-player'))layoutObserver.observe($('music-player'));scope.cleanup(()=>layoutObserver.disconnect());
  form.inert=true;
  form.setAttribute('aria-busy','true');message('Opening music import…');
  try{
    const response=await scope.fetch(config.noticeUrl,{method:'POST',body:new URLSearchParams({csrf:config.csrf})});
    if((await FreoCatalog.readResponse(response,'open the importer')).show&&!await FreoDialog.confirm({title:'Before importing music',message:'Only upload and broadcast material you own or are legally authorized to use. Uploading or broadcasting copyrighted material without the necessary rights can violate copyright law and lead to removal, legal action, or financial liability. You are responsible for obtaining the required permissions and licences.',confirmLabel:'Continue to import',signal:scope.signal})){FreoWorkspace.navigate(config.libraryUrl);return;}
    catalog=await FreoCatalog.load(config.base);batchSelectors=FreoCatalog.selectors($('batch-catalog'),catalog,{}, {...config,get csrf(){return form.dataset.csrf;},importing:true,batch:true,message,target:'the selected songs'});batchChips=FreoCatalog.chips($('batch-classification'),catalog,{},['playlists','categories','tags']);
    const rotationSelect=$('import-rotation');for(const category of catalog.categories.filter(c=>c.enabled))rotationSelect.append(new Option('Rotation: '+category.name,String(category.id)));if(![...rotationSelect.options].some(o=>o.value===rotation))rotation='';rotationSelect.value=rotation;
    const list=await sessionList();const requested=new URLSearchParams(location.search).get('import_session');const resume=['draft','attention','empty'].includes(list[0]?.state)?list[0]:null;await openSession(requested||resume?.id||list.find(row=>row.state==='empty')?.id);form.inert=false;form.setAttribute('aria-busy','false');message('Choose music or drop files here to get started.');
  }catch(e){message('Could not open music import. '+e.message);form.inert=false;form.setAttribute('aria-busy','false');const retry=button('Reload importer',()=>location.reload());$('import-message').append(document.createTextNode(' '),retry);return;}
  $('choose-files').onclick=()=>$('media-file').click();$('choose-folder').onclick=()=>$('media-folder').click();for(const id of ['media-file','media-folder'])$(id).onchange=e=>{addFiles([...e.target.files]);e.target.value='';};
  async function walk(entry,prefix=''){if(entry.isFile){const file=await new Promise((resolve,reject)=>entry.file(resolve,reject));Object.defineProperty(file,'webkitRelativePath',{value:prefix+file.name});return[file];}if(!entry.isDirectory)return[];const reader=entry.createReader();let result=[];while(true){const chunk=await new Promise((resolve,reject)=>reader.readEntries(resolve,reject));if(!chunk.length)return result;for(const child of chunk)result.push(...await walk(child,prefix+entry.name+'/'));}}
  const zone=form.querySelector('.drop-zone');zone.ondragover=e=>{e.preventDefault();zone.classList.add('is-dragging');};zone.ondragleave=()=>zone.classList.remove('is-dragging');zone.ondrop=async e=>{e.preventDefault();zone.classList.remove('is-dragging');const entries=[...e.dataTransfer.items].map(i=>i.webkitGetAsEntry?.()).filter(Boolean),files=[...e.dataTransfer.files];try{let found=[];if(entries.length)for(const entry of entries)found.push(...await walk(entry));else found=files;addFiles(found);}catch(_){message('Could not read the folder. Use Choose folder.');}};
  scope.listen(window,'dragover',e=>{if([...e.dataTransfer.types].includes('Files'))e.preventDefault();});scope.listen(window,'drop',e=>{if([...e.dataTransfer.types].includes('Files'))e.preventDefault();});
  $('new-import').onclick=()=>{resetAfterImport=false;return openSession().catch(e=>message(e.message));};$('import-sessions').onchange=e=>{resetAfterImport=false;return openSession(e.target.value).catch(error=>message(error.message));};
  $('select-all').onchange=e=>{for(const item of items.values())if(pending(item)&&!isDuplicate(item))item.selected=e.target.checked;renderGroups();};$('attention-only').onchange=renderGroups;
  $('edit-selected').onclick=()=>openBatch();$('close-batch').onclick=()=>{$('import-defaults').hidden=true;};
  $('folder-artwork').onclick=async()=>{folderCover=folderCovers.get($('folder-artworks').value);if(!folderCover)return;const cover=await FreoCatalog.chooseCover(config,{},folderCover);if(cover){const folder=folderCover.webkitRelativePath?.split('/').slice(0,-1).join('/');if(folder)for(const item of items.values())item.selected=pending(item)&&item.path.split('/').slice(0,-1).join('/')===folder;const selected=[...items.values()].filter(i=>i.selected&&pending(i));const keys=new Set(selected.map(groupKey));openBatch(keys.size===1&&[...keys][0]!=='songs'?[...keys][0]:null);batchCover=cover;$('batch-status').textContent='Folder artwork selected. Apply it to the selected songs.';}};
  $('batch-artwork').onclick=async()=>{batchCover=await FreoCatalog.chooseCover(config);if(batchCover)$('batch-status').textContent='Artwork selected. Apply it to the selected songs.';};
  $('apply-batch').onclick=()=>applyBatch();$('number-tracks').onclick=()=>applyBatch(true);
  $('undo-batch').onclick=async()=>{if(!undo||batchBusy)return;batchBusy=true;$('undo-batch').disabled=true;summary();for(const previous of undo.items){const item=items.get(previous.id);if(item&&editable(item)){item.choices=previous.choices;fill(item);change(item);}}try{await flush();if(undo.group){const result=await post(session.url,{action:'group',key:undo.group,choices:undo.defaults});groups=result.groups;}if('future' in undo){const result=await post(session.url,{action:'group',key:'__defaults__',choices:undo.future});groups=result.groups;}undo=null;$('undo-batch').hidden=true;renderGroups();message('Shared changes undone.');}catch(e){message(e.message);}finally{batchBusy=false;$('undo-batch').disabled=false;summary();}};
  form.onsubmit=async e=>{e.preventDefault();if(finalizing)return;try{const selected=[...items.values()].filter(i=>i.selected&&!isDuplicate(i)&&i.remote?.status==='ready');if(!selected.length)return;await flush(selected);finalizing=true;summary();merge(await post(session.url,{action:'finalize',items:selected.map(i=>({id:i.id,revision:i.remote.revision}))}));resetAfterImport=true;$('import-success').hidden=true;message('Import started. You can add more music while these songs process.');$('import-defaults').hidden=true;$('undo-batch').hidden=true;}catch(error){message(error.message);}finally{finalizing=false;renderGroups();}};
  scope.beforeLeave=async()=>{if(uploading&&!await FreoDialog.confirm({title:'Leave while files upload?',message:'Uploaded files are saved. Unfinished uploads will need to be reselected when you return.',confirmLabel:'Leave import',signal:scope.signal}))return false;try{await flush();return true;}catch(e){message(e.message);return false;}};
  scope.listen(window,'beforeunload',e=>{if(uploading||[...items.values()].some(i=>i.dirty)){e.preventDefault();e.returnValue='';}});
  scope.cleanup(()=>{for(const item of items.values()){clearTimeout(item.timer);if(item.source)URL.revokeObjectURL(item.source);}});
  for(const id of ['media-file','media-folder'])if($(id).files.length){addFiles([...$(id).files]);$(id).value='';}
  $('import-rotation').onchange=e=>{rotation=e.target.value;try{localStorage.setItem(rotationKey,rotation);}catch(_){}if(!rotation)return;for(const item of items.values())if(item.selected&&pending(item)&&!isDuplicate(item)){Object.assign(item.choices,rotationChoices());fill(item);if(item.remote)change(item);}remember();summary();};
  $('resume-import').onclick=async()=>{try{await sessionList();authPaused=false;$('import-auth').hidden=true;await flush();if(await poll())message('Import resumed. Retry any interrupted uploads.');}catch(e){message(e.message);}};
  scope.listen(document,'visibilitychange',()=>{if(!document.hidden)poll();});
  scope.interval(()=>{if(!document.hidden&&Date.now()>=nextPollAt)poll();},2500);summary();
})();
