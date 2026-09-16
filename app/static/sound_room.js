(() => {
  const scope = window.FreoPage;
  const root=document.getElementById('sound-room');if(!root)return;
  const $=id=>document.getElementById(id), selected=new Set();
  let data=null,active=null,activeSong=null,page=1,filter={},version=0,busy=false,undo=null,drag=null,editing=null,notesDirty=false,editingCategory=null,suppressClickUntil=0;
  const initial=new URLSearchParams(location.search);active=initial.get('song');
  const el=(tag,text,cls)=>{const node=document.createElement(tag);if(text!==undefined)node.textContent=text;if(cls)node.className=cls;return node;};
  const button=(text,fn,cls)=>{const node=el('button',text,cls);node.type='button';node.addEventListener('click',fn);return node;};
  function fitWorkspace(){
    const dock=$('music-player'), bottom=dock&&!dock.hidden?dock.getBoundingClientRect().top:innerHeight;
    const sidebar=root.querySelector('.room-destinations'), songs=$('room-songs');
    sidebar.style.maxHeight=innerWidth>600?Math.max(200,bottom-sidebar.getBoundingClientRect().top-20)+'px':'';
    // Keep the scrolling song list above the private preview dock, including
    // when filters wrap or classification chips make a row taller.
    songs.style.minHeight='180px';
    const available=bottom-Math.max(0,songs.getBoundingClientRect().top)-24;
    songs.style.maxHeight=Math.max(180,Math.min(innerHeight*(innerWidth<=850?.55:.62),available))+'px';
  }
  scope.listen(window,'resize',fitWorkspace);scope.listen(window,'scroll',fitWorkspace,{passive:true});scope.frame(fitWorkspace);
  const layoutObserver=new ResizeObserver(fitWorkspace);
  [document.querySelector('.admin-topbar'),root.querySelector('.room-search'),root.querySelector('.room-library > header'),$('music-player')].filter(Boolean).forEach(node=>layoutObserver.observe(node));
  scope.cleanup(()=>layoutObserver.disconnect());
  const message=(text,error=false)=>{const node=root.querySelector('.room-message');node.hidden=false;node.classList.toggle('error',error);$('room-message-text').textContent=text;fitWorkspace();};
  async function post(action,payload){
    if(busy){message('Finishing the previous change…');return null;}
    busy=true;root.setAttribute('aria-busy','true');
    try{
      const result=await FreoMusicToggles.request(root.dataset,action,payload);
      message(result.message);root.querySelector('.job-status-link')?.remove();if(result.job_url){const link=el('a','Deletion status','job-status-link');link.href=result.job_url;root.querySelector('.room-message').append(link);}if(result.undo){undo=result.undo;$('room-undo').hidden=false;}
      if(action==='undo'){undo=null;$('room-undo').hidden=true;}
      return result;
    }catch(error){message(error.message,true);return null;}
    finally{busy=false;root.removeAttribute('aria-busy');}
  }
  const duration=ms=>`${Math.floor(ms/60000)}:${String(Math.floor(ms/1000)%60).padStart(2,'0')}`;
  function preview(song){
    const node=el('button','▶','preview-button');node.type='button';
    Object.assign(node.dataset,{preview:song.uuid,title:song.title,artist:song.artist,audition:song.audition,gain:song.gain.factor,gainDb:song.gain.db,gainStatus:song.gain.status});
    node.setAttribute('aria-label',`Play ${song.title}`);return node;
  }
  function selection(){
    $('selection-count').textContent=`${selected.size} selected`;
    $('process-selected').disabled=!selected.size;
    root.querySelectorAll('[data-apply]').forEach(node=>node.disabled=!selected.size);
    root.querySelectorAll('.room-song').forEach(row=>{row.classList.toggle('selected',selected.has(row.dataset.song));row.querySelector('input').checked=selected.has(row.dataset.song);});
    const visible=data?.songs||[];$('room-select-all').checked=!!visible.length&&visible.every(song=>selected.has(song.uuid));
    $('room-select-all').indeterminate=visible.some(song=>selected.has(song.uuid))&&!$('room-select-all').checked;
  }
  async function assign(kind,target,ids,operation='add'){
    if(!ids.length){message('Select songs first.');return;}
    const result=await post('assign',{kind,target,songs:ids,operation});if(result)await load();
  }
  function setFilter(next,title){if(notesDirty){message('Save or discard your edits before changing collections.',true);return;}filter=next;page=1;$('collection-title').textContent=title;load();}
  function destinations(){
    for(const [kind,items] of [['playlist',data.playlists],['category',data.categories],['tag',data.tags]]){
      const list=$(kind==='playlist'?'room-playlists':kind==='category'?'room-categories':'room-tags');
      const signature=JSON.stringify([items,filter[kind]]);
      if(list.dataset.render===signature)continue;
      list.dataset.render=signature;list.replaceChildren();
      if(!items.length)list.append(el('p',`Create your first ${kind}.`,'room-hint'));
      items.forEach(item=>{
        const row=el('div',undefined,'destination-row');Object.assign(row.dataset,{dropKind:kind,dropTarget:item.id});
        if(kind==='tag'){
          const handle=el('span','⠿','tag-drag');handle.title='Drag this tag onto a song';handle.setAttribute('aria-hidden','true');Object.assign(handle.dataset,{tag:item.id});row.append(handle);row.style.setProperty('--tag-color',item.color);
        }
        const name=kind==='playlist'?el('a',item.name,'destination-name'):button(item.name,()=>{if(kind==='category')openCategory(item);else{editingCategory=null;setFilter({[kind]:item.id},item.name);}},'destination-name');if(kind==='playlist')name.href=root.dataset.playlists+'?playlist='+item.id;name.append(el('small',`${item.count}${kind==='category'?` songs · ${item.play_count} plays`:''}${item.enabled===false?' · disabled':''}`));
        if(String(filter[kind])===String(item.id))name.setAttribute('aria-current','true');
        const apply=button('Apply',()=>assign(kind,item.id,[...selected]),'destination-apply');apply.dataset.apply='';apply.title=`Apply ${item.name} to selected songs`;
        row.append(name,apply);
        if(kind==='tag'){const edit=button('⋯',()=>openDestination('tag',item),'tag-edit');edit.setAttribute('aria-label',`Edit ${item.name}`);row.append(edit);}
        list.append(row);
      });
    }
    $('unfinished-count').textContent=data.unfinished;$('flagged-count').textContent=data.flagged_count;
  }
  const rowsSignature=()=>JSON.stringify([data.songs,data.tags,data.categories,data.playlists,data.page,data.total,editingCategory]);
  function rows(){
    const list=$('room-songs'),signature=rowsSignature();if(list.dataset.render===signature){selection();window.FreoPreview?.sync();return;}list.dataset.render=signature;list.replaceChildren();
    if(!data.songs.length)list.append(el('p','No songs match. Try another filter or import some music.','room-empty'));
    data.songs.forEach(song=>{
      const row=el('article',undefined,'room-song');row.dataset.song=song.uuid;row.tabIndex=0;row.classList.toggle('inspecting',active===song.uuid);
      const check=el('input');check.type='checkbox';check.setAttribute('aria-label',`Select ${song.title}`);check.addEventListener('change',()=>{check.checked?selected.add(song.uuid):selected.delete(song.uuid);selection();});
      const handle=el('span','⠿','song-drag');handle.title='Drag song to a category or tag';handle.setAttribute('aria-hidden','true');
      const copy=el('div',undefined,'song-row-copy');copy.append(el('b',song.title),el('span',song.artist),el('small',`${song.album||'Single'} · ${duration(song.duration_ms)} · ${song.play_count} plays · ↑ ${song.votes?.up||0} ↓ ${song.votes?.down||0}`));
      copy.append(FreoMusicToggles.create(song,data,root.dataset));
      const status=el('div',undefined,'song-row-status');status.append(el('span',song.analysis==='pending'?(song.requested?'Queued':'Waiting'):song.analysis),el('small',song.lufs===null?'LUFS pending':`${song.lufs.toFixed(1)} LUFS`));
      status.append(button(song.flag?(song.flag.resolved?'💬 Resolved':'💬 Flagged'):'💬 Flag',()=>window.FreoSongFlags.open(song),'song-flag-button'));
      if(!song.enabled)status.append(el('small','Needs review'));
      const menu=el('details',undefined,'song-menu'),summary=el('summary','⋯');summary.setAttribute('aria-label',`Song menu: ${song.title}`);menu.append(summary);
      const link=el('a','Edit song');link.href=song.detail;menu.append(link,button('Process song',()=>process([song.uuid])),button('Permanently delete',()=>deleteSong(song),'delete-song'));
      row.append(check,handle,preview(song),copy,status,menu);
      row.addEventListener('click',event=>{if(!event.target.closest('button,input,a,summary,details'))inspect(song.uuid);});
      row.addEventListener('keydown',event=>{if(event.target===row&&event.key==='Enter')inspect(song.uuid);});list.append(row);
    });
    $('room-total').textContent=`${data.total} songs`;$('room-page').textContent=`${data.page} / ${data.pages}`;$('room-prev').disabled=data.page<=1;$('room-next').disabled=data.page>=data.pages;
    selection();window.FreoPreview?.sync();
  }
  async function inspect(id){
    if(notesDirty&&id!==active){message('Save or discard your notes before changing songs.',true);return;}
    editingCategory=null;active=id;
    try{const response=await scope.fetch(root.dataset.catalog+'/'+encodeURIComponent(id),{cache:'no-store'});if(!response.ok)throw Error();const song=await response.json();if(active!==id)return;activeSong=song;inspector(song);root.querySelectorAll('.room-song').forEach(row=>row.classList.toggle('inspecting',row.dataset.song===id));}
    catch(_){message('Song details are unavailable. Refresh and try again.',true);}
  }
  function inspector(song){
    if(notesDirty)return;
    const panel=$('song-inspector'),signature='song:'+JSON.stringify(song);if(panel.dataset.render===signature)return;if(panel.contains(document.activeElement)&&document.activeElement.matches('input,textarea,select'))return;panel.dataset.render=signature;panel.replaceChildren();delete panel.dataset.dropKind;delete panel.dataset.dropTarget;
    const art=el('div',undefined,'inspector-art');if(song.artwork){const img=el('img');img.src=song.artwork;img.alt='';art.append(img);}else art.append(el('span','♫'));
    panel.append(art,el('span','SELECTED SONG','eyebrow'));
    const heading=el('div',undefined,'inspector-heading');heading.append(preview(song),el('h2',song.title));panel.append(heading,el('p',song.artist,'inspector-artist'));
    const link=el('a','Edit song ↗','inspector-link');link.href=song.detail;panel.append(link);
    panel.append(button(song.flag?'💬 Review flag':'💬 Flag song',()=>window.FreoSongFlags.open(song),'song-flag-button'));
    const metrics=el('div',undefined,'inspector-metrics');
    for(const [name,value] of [['Confirmed plays',song.play_count],['Listener votes',`↑ ${song.votes?.up||0} · ↓ ${song.votes?.down||0}`],['Approval',song.votes?.total?`${song.votes.approval}% (${song.votes.total} votes)`:'No votes'],['Net score',song.votes?.net||0],['Loudness',song.lufs===null?'Not measured':`${song.lufs.toFixed(1)} LUFS`],['Playback gain',`${song.gain.db} dB`],['Target',`${song.gain.target} LUFS`],['Status',song.gain.status]]){const cell=el('div');cell.append(el('small',name),el('b',value));metrics.append(cell);}panel.append(metrics);if(song.feedback_url){const feedback=el('a',`${song.votes?.comments||0} listener comments →`,'inspector-link');feedback.href=song.feedback_url;panel.append(feedback);}
    const processing=button(song.analysis==='processing'?'Processing…':song.requested?'Queued for processing':'Process song',()=>process([song.uuid]),'process-song');processing.disabled=song.analysis==='processing'||song.requested;panel.append(processing);
    if(song.error)panel.append(el('p',song.error,'room-hint'));
    for(const [kind,ids,items] of [['playlist',song.playlists,data.playlists],['category',song.categories,data.categories],['tag',song.tags,data.tags]]){
      panel.append(el('h3',kind==='playlist'?'Playlists':kind==='category'?'Categories':'Tags'));
      const chips=el('div',undefined,'inspector-chips');ids.forEach(id=>{const item=items.find(x=>x.id===id);if(!item)return;const chip=button(`${item.name} ×`,()=>assign(kind,id,[song.uuid],'remove'),'song-chip');if(kind==='tag')chip.style.setProperty('--tag-color',item.color);chip.setAttribute('aria-label',`Remove ${item.name} from ${song.title}`);chips.append(chip);});panel.append(chips);
      const select=el('select');select.setAttribute('aria-label',`Add ${kind}`);select.append(new Option(`Add ${kind}…`,''));items.filter(x=>!ids.includes(x.id)).forEach(x=>select.append(new Option(x.name,x.id)));select.addEventListener('change',()=>{if(select.value)assign(kind,Number(select.value),[song.uuid]);});panel.append(select);
    }
    const label=el('label','Song notes','notes-label'),notes=el('textarea');notes.maxLength=4000;notes.value=song.notes;notes.placeholder='Mood, a great segue, a moment to remember…';notes.id='song-notes';label.append(notes);panel.append(label);
    const noteStatus=el('small','Saved','notes-status');
    notes.addEventListener('input',()=>{notesDirty=notes.value!==song.notes;noteStatus.textContent=notesDirty?'Unsaved changes':'Saved';});
    const save=button('Save notes',async()=>{const result=await post('notes',{songs:[song.uuid],notes:notes.value,previous:song.notes});if(result){notesDirty=false;await inspect(song.uuid);}});
    const discard=button('Discard',()=>{notesDirty=false;delete $('song-inspector').dataset.render;inspect(song.uuid);});const actions=el('div',undefined,'notes-actions');actions.append(save,discard);panel.append(noteStatus,actions,button('Permanently delete song',()=>deleteSong(song),'delete-song inspector-delete'));
    window.FreoPreview?.sync();
  }
  function openCategory(item){
    if(notesDirty){message('Save or discard your notes before opening a category.',true);return;}
    editingCategory=item.id;active=null;setFilter({category:item.id},item.name);
  }
  function categoryInspector(item){
    const panel=$('song-inspector'),signature='category:'+JSON.stringify(item);if(panel.dataset.render===signature)return;if(panel.contains(document.activeElement)&&document.activeElement.matches('input,textarea,select'))return;panel.dataset.render=signature;panel.replaceChildren();panel.append(el('span','CATEGORY EDITOR','eyebrow'),el('h2',item.name));
    const form=el('form',undefined,'category-editor');
    const nameLabel=el('label','Name'),name=el('input');name.name='name';name.value=item.name;name.required=true;name.maxLength=120;nameLabel.append(name);
    const descriptionLabel=el('label','Description'),description=el('textarea');description.name='description';description.value=item.description||'';description.maxLength=500;descriptionLabel.append(description);
    const enabledLabel=el('label',' Enabled in programming'),enabled=el('input');enabled.type='checkbox';enabled.name='enabled';enabled.checked=item.enabled;enabledLabel.prepend(enabled);
    const save=el('button','Save category');save.type='submit';form.append(nameLabel,descriptionLabel,enabledLabel,save);
    form.addEventListener('input',()=>{notesDirty=true;});
    form.addEventListener('submit',async event=>{event.preventDefault();if(await post('edit-category',{id:item.id,name:name.value,description:description.value,enabled:enabled.checked})){notesDirty=false;load();}});
    panel.append(form,button('Discard changes',()=>{notesDirty=false;delete $('song-inspector').dataset.render;load();}),el('h3',`${item.count} songs · ${item.play_count} plays`),el('p','Add and remove songs using the controls in the song list. Drag selected songs here or onto this category in the sidebar.','room-hint'));
    panel.dataset.dropKind='category';panel.dataset.dropTarget=item.id;
    panel.append(button('Browse songs to add',()=>{filter={};page=1;$('collection-title').textContent=`Add songs to ${item.name}`;load();}),button('View category songs',()=>setFilter({category:item.id},item.name)));
  }
  scope.listen(document,'music-assignment',event=>{if(event.detail.kind!=='playlist')return;message(event.detail.message);if(event.detail.undo){undo=event.detail.undo;$('room-undo').hidden=false;}});
  scope.listen(document,'music-toggle-start',()=>{version++;});
  scope.listen(document,'music-toggle-saved',event=>{
    const {kind,target,songs,assigned,before}=event.detail;
    const key=kind==='playlist'?'playlists':kind==='tag'?'tags':'categories';
    for(const song of [...(data?.songs||[]),activeSong].filter(Boolean)){
      if(!songs.includes(song.uuid))continue;
      song[key]=assigned?[...new Set([...song[key],target])]:song[key].filter(id=>id!==target);
    }
    const item=data?.[key].find(item=>item.id===target);
    if(item&&assigned!==before)item.count+=assigned?1:-1;
    if(data){destinations();$('room-songs').dataset.render=rowsSignature();}
    if(activeSong&&!notesDirty)inspector(activeSong);
  });
  async function load(){
    if(FreoMusicToggles.pending)return;
    const attempt=++version;const params=new URLSearchParams({...filter,page});
    const form=$('room-search');for(const key of ['q','analysis','enabled'])if(form.elements[key].value)params.set(key,form.elements[key].value);
    try{const response=await scope.fetch(root.dataset.catalog+'?'+params,{cache:'no-store'});if(!response.ok||!response.headers.get('content-type')?.includes('application/json'))throw Error();const next=await response.json();if(attempt!==version||FreoMusicToggles.pending||drag)return;data=next;destinations();rows();fitWorkspace();if(editingCategory&&!notesDirty){const category=data.categories.find(x=>x.id===editingCategory);if(category)categoryInspector(category);}else if(active&&!notesDirty)await inspect(active);}
    catch(_){message('Music could not load. Check your connection or refresh to sign in again.',true);}
  }
  async function process(ids){if(!ids.length)return;const result=await post('process',{songs:ids});if(result)load();}
  function openDestination(kind,item=null){editing={kind,item};$('destination-title').textContent=`${item?'Edit':'Create'} ${kind}`;const form=$('destination-form');form.elements.name.value=item?.name||'';form.elements.color.value=item?.color||'#b9e79b';form.elements.description.value=item?.description||'';$('tag-color-label').hidden=kind!=='tag';$('destination-error').textContent='';$('destination-dialog').showModal();form.elements.name.focus();}
  root.querySelectorAll('[data-create]').forEach(node=>node.addEventListener('click',()=>openDestination(node.dataset.create)));
  $('destination-form').addEventListener('submit',async event=>{event.preventDefault();const form=event.currentTarget;const action=editing.item?'edit-tag':`create-${editing.kind}`;const result=await post(action,{name:form.elements.name.value,color:form.elements.color.value,description:form.elements.description.value,id:editing.item?.id});if(result){$('destination-dialog').close();load();}else $('destination-error').textContent=$('room-message-text').textContent;});
  $('target-form').addEventListener('submit',async event=>{event.preventDefault();if(await post('loudness',{target:event.currentTarget.elements.target.value}))load();});
  $('room-search').addEventListener('submit',event=>{event.preventDefault();page=1;load();});
  let timer;$('room-search').elements.q.addEventListener('input',()=>{clearTimeout(timer);timer=setTimeout(()=>{page=1;load();},200);});
  for(const name of ['analysis','enabled'])$('room-search').elements[name].addEventListener('change',()=>{page=1;load();});
  $('room-all').addEventListener('click',()=>{for(const key of ['q','analysis','enabled'])$('room-search').elements[key].value='';editingCategory=null;setFilter({},'All songs');});
  $('room-unfiled').addEventListener('click',()=>setFilter({uncategorized:1},'Uncategorized'));
  $('room-flagged').addEventListener('click',()=>setFilter({flags:'open'},'Flagged songs'));
  $('room-resolved').addEventListener('click',()=>setFilter({flags:'resolved'},'Resolved flags'));
  scope.listen(document,'song-flag-saved',()=>load());
  $('room-unfinished').addEventListener('click',()=>{$('room-search').elements.analysis.value='unfinished';setFilter({},'Needs processing');});
  $('room-select-all').addEventListener('change',event=>{data.songs.forEach(song=>event.target.checked?selected.add(song.uuid):selected.delete(song.uuid));selection();});
  $('room-clear-selection').addEventListener('click',()=>{selected.clear();selection();});
  $('process-selected').addEventListener('click',()=>process([...selected]));
  $('room-prev').addEventListener('click',()=>{page--;load();});$('room-next').addEventListener('click',()=>{page++;load();});
  $('room-undo').addEventListener('click',async()=>{if(undo&&await post('undo',{id:undo}))load();});

  // Pointer ownership avoids the native image drag and DataTransfer failures.
  const cleanDrag=()=>{drag?.ghost?.remove();drag=null;root.querySelectorAll('.drop-active').forEach(node=>node.classList.remove('drop-active'));document.body.classList.remove('music-dragging');};
  root.addEventListener('click',event=>{if(Date.now()<suppressClickUntil){event.preventDefault();event.stopPropagation();}},true);
  root.addEventListener('dragstart',event=>event.preventDefault());
  root.addEventListener('pointerdown',event=>{
    if(event.button!==0||!event.isPrimary||event.target.closest('button,input,select,textarea,a,summary,details'))return;
    const row=event.target.closest('.room-song'),tag=event.target.closest('.tag-drag');
    if(!row&&!tag)return;if(event.pointerType==='touch'&&!event.target.closest('.song-drag,.tag-drag'))return;
    drag={pointer:event.pointerId,x:event.clientX,y:event.clientY,row,tag:tag?.dataset.tag,ghost:null};
    (row||tag).setPointerCapture(event.pointerId);
  });
  scope.listen(document,'pointermove',event=>{
    if(!drag||event.pointerId!==drag.pointer)return;
    if(!drag.ghost&&Math.hypot(event.clientX-drag.x,event.clientY-drag.y)>7){
      if(drag.row&&!selected.has(drag.row.dataset.song)){selected.clear();selected.add(drag.row.dataset.song);selection();}
      drag.ids=[...selected];drag.ghost=el('div',drag.tag?'Apply tag':`${drag.ids.length} song${drag.ids.length===1?'':'s'}`,'music-drag-ghost');document.body.append(drag.ghost);document.body.classList.add('music-dragging');
    }
    if(!drag.ghost)return;event.preventDefault();drag.ghost.style.transform=`translate(${event.clientX+14}px,${event.clientY+14}px)`;
    const under=document.elementFromPoint(event.clientX,event.clientY);root.querySelectorAll('.drop-active').forEach(node=>node.classList.remove('drop-active'));
    const target=under?.closest(drag.tag?'.room-song':'[data-drop-kind]');target?.classList.add('drop-active');
    if(event.clientY>innerHeight-70)window.scrollBy(0,16);else if(event.clientY<70)window.scrollBy(0,-16);
  },{passive:false});
  scope.listen(document,'pointerup',event=>{
    if(!drag||event.pointerId!==drag.pointer)return;const item=drag,under=document.elementFromPoint(event.clientX,event.clientY);cleanDrag();if(!item.ghost)return;suppressClickUntil=Date.now()+250;
    if(item.tag){const row=under?.closest('.room-song');if(row)assign('tag',Number(item.tag),[row.dataset.song]);}
    else{const target=under?.closest('[data-drop-kind]');if(target)assign(target.dataset.dropKind,Number(target.dataset.dropTarget),item.ids);}
  });
  scope.listen(document,'pointercancel',cleanDrag);scope.listen(window,'blur',cleanDrag);scope.listen(document,'keydown',event=>{if(event.key==='Escape')cleanDrag();});

  async function deleteSong(song){
    if(!await FreoDialog.confirm({title:`Delete “${song.title}”?`,message:'The audio will be deleted and the song removed from Music. Past play history remains. This cannot be undone.',confirmLabel:'Delete song'}))return;
    if(await post('delete',{songs:[song.uuid],confirm:song.uuid})){selected.delete(song.uuid);if(active===song.uuid){active=null;notesDirty=false;$('song-inspector').replaceChildren(el('p','Deletion queued.','room-empty'));}load();}
  }
  load();scope.interval(()=>{if(!drag&&!busy&&!document.hidden&&!document.querySelector('dialog[open]')&&!root.querySelector('.song-menu[open]'))load();},10000);
})();
