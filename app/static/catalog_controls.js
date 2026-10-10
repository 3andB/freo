(() => {
  const scope=FreoPage;
  const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
  function decodeResponse(status,url,type,text,action='complete this request'){
    if(status===413)throw Error('Upload exceeds the server upload limit. Your file is kept here; retry after the limit is corrected or choose a smaller file.');
    if(status===401||new URL(url||location.href,location.href).pathname==='/admin/login'){
      document.dispatchEvent(new Event('freo:authentication-required'));
      throw Error('Your session expired. Sign in again, then resume your import.');
    }
    if(status===403)throw Error('You do not have permission to '+action+'. Check your access, then retry.');
    const failed=`Could not ${action} (HTTP ${status}). Please retry.`;
    if(!type?.toLowerCase().includes('application/json')){if(status===400){document.dispatchEvent(new Event('freo:authentication-required'));throw Error('Your page has expired. Sign in again, then resume your import.');}throw Error(failed);}
    let result;try{result=JSON.parse(text);}catch(_){throw Error('The server returned an invalid response. Please retry.');}
    if(status<200||status>=300)throw Error(typeof result?.message==='string'?result.message:failed);
    return result;
  }
  const readResponse=async(response,action)=>decodeResponse(response.status,response.url,response.headers.get('content-type'),await response.text(),action);
  async function api(url,csrf,payload){
    const body=payload instanceof FormData?payload:new FormData();
    if(!(payload instanceof FormData))for(const [k,v] of Object.entries(payload))body.set(k,v);
    body.set('csrf',csrf);
    const response=await scope.fetch(url,{method:'POST',body,headers:{Accept:'application/json'}});
    return readResponse(response,'save changes');
  }
  const stores=new Map(), listeners=new WeakMap();
  const notify=data=>(listeners.get(data)||[]).forEach(fn=>fn());
  async function load(base){const next=await readResponse(await scope.fetch(base,{cache:'no-store',headers:{Accept:'application/json'}}),'load the catalog');if(!stores.has(base))stores.set(base,next);else Object.assign(stores.get(base),next);const data=stores.get(base);notify(data);return data;}
  function subscribe(data,fn){if(!listeners.has(data))listeners.set(data,new Set());listeners.get(data).add(fn);const dispose=()=>listeners.get(data)?.delete(fn);scope.cleanup(dispose);return dispose;}
  function upsert(data,kind,row){const rows=data[kind];const index=rows.findIndex(r=>r.id===row.id);if(index<0)rows.push(row);else rows[index]=row;rows.sort((a,b)=>a.name.localeCompare(b.name));notify(data);}

  function selectors(container,catalog,initial,config){
    if(config.importing||config.searchable)return picker(container,catalog,initial,config);
    let data=catalog,detected={};
    const artist=el('select'),album=el('select'),search=el('input');search.type='search';search.placeholder='Search artists';search.setAttribute('aria-label','Search artists');
    artist.setAttribute('aria-label','Artist');album.setAttribute('aria-label','Album');
    const fields={artist_id:initial.artist_id||'',album_id:initial.album_id??undefined};
    function populate(){
      const chosen=String(fields.artist_id||'');artist.replaceChildren(new Option(config.importing?(detected.artist?`From file: ${detected.artist}`:'From file metadata'):'Choose artist',''));
      data.artists.filter(a=>String(a.id)===chosen||a.name.toLowerCase().includes(search.value.toLowerCase())).forEach(a=>artist.append(new Option(a.name,a.id)));
      artist.value=chosen;album.replaceChildren(new Option(config.importing?(detected.album?`From file: ${detected.album}`:'From file metadata'):'Single / No album',''));
      if(config.importing)album.append(new Option('Single / No album','single'));
      data.albums.filter(a=>String(a.artist_id)===chosen||String(a.id)===String(fields.album_id)).forEach(a=>album.append(new Option(a.name,a.id)));
      album.value=fields.album_id===null&&config.importing?'single':String(fields.album_id||'');
    }
    for(const [kind,label,select] of [['artists','Artist',artist],['albums','Album',album]]){
      const wrap=el('div',undefined,'catalog-field'),heading=el('label',label),line=el('div',undefined,'catalog-select');
      const add=el('button','+ Add');add.type='button';add.setAttribute('aria-label',`Add ${label.toLowerCase()}`);line.append(select,add);heading.append(line);wrap.append(heading);if(kind==='artists')wrap.prepend(search);container.append(wrap);
      add.addEventListener('click',()=>{
        if(kind==='albums'&&!fields.artist_id){config.message('Choose or add an artist first.');return;}
        const panel=el(config.importing?'div':'dialog',undefined,config.importing?'inline-catalog-add':'studio-dialog');
        const name=el('input');name.maxLength=200;name.placeholder=`New ${label.toLowerCase()} name`;name.setAttribute('aria-label',name.placeholder);
        const save=el('button',`Add ${label.toLowerCase()}`),cancel=el('button','Cancel'),error=el('p');save.type=cancel.type='button';error.setAttribute('role','status');panel.append(el('h3',`Add ${label.toLowerCase()}`),name,save,cancel,error);
        const close=()=>{panel.remove();add.disabled=false;add.focus();};add.disabled=true;
        if(config.importing)wrap.append(panel);else{document.body.append(panel);panel.showModal();panel.addEventListener('cancel',close);}
        cancel.onclick=close;name.focus();
        save.onclick=async()=>{if(!name.value.trim()){error.textContent='Enter a name';return;}save.disabled=true;try{const result=await api(config.base+'/'+kind,config.csrf,{name:name.value,artist_id:fields.artist_id});upsert(data,kind,result);if(kind==='artists'){fields.artist_id=result.id;fields.album_id=config.importing?undefined:null;search.value='';}else fields.album_id=result.id;populate();config.change?.();close();}catch(e){error.textContent=e.message;save.disabled=false;}};
        name.addEventListener('keydown',event=>{if(event.key==='Enter'){event.preventDefault();save.click();}});
      });
    }
    search.addEventListener('input',populate);
    artist.addEventListener('change',()=>{fields.artist_id=artist.value;fields.album_id=config.importing?undefined:null;populate();config.change?.();});
    album.addEventListener('change',()=>{fields.album_id=album.value==='single'?null:album.value|| (config.importing?undefined:null);config.change?.();});subscribe(data,populate);populate();
    return {detected(values){detected=values;populate();},values:()=>{const result={};if(fields.artist_id)result.artist_id=Number(fields.artist_id);if(fields.album_id!==undefined)result.album_id=fields.album_id?Number(fields.album_id):null;if(fields.album_id)result.album_artist_id=data.albums.find(a=>a.id===Number(fields.album_id))?.artist_id;return result;},set(values){Object.assign(fields,values);populate();},refresh:async()=>{data=await load(config.base);populate();}};
  }
  function picker(container,catalog,initial,config){
    let fields={...initial},detected={},creating=false;
    if(fields.artist_id)fields.artist_id=Number(fields.artist_id);if(fields.album_id){fields.album_id=Number(fields.album_id);fields.album_artist_id=catalog.albums.find(a=>a.id===fields.album_id)?.artist_id;}
    const touched=new Set(),controls={};
    const names={artist_id:'Artist',album_id:'Album'};
    const valueText=key=>{
      const id=fields[key],kind=key==='artist_id'?'artists':'albums';
      if(id)return catalog[kind].find(row=>row.id===Number(id))?.name||'';
      if(key==='album_id'&&id===null)return 'No album';
      return fields[key==='artist_id'?'artist_name':'album_name']||'';
    };
    function paint(){for(const [key,{input,list}] of Object.entries(controls)){
      if(document.activeElement!==input||list.hidden)input.value=valueText(key);
      input.placeholder=!config.importing?`Search ${names[key].toLowerCase()}s`:config.batch&&!touched.has(key)?'Leave unchanged':`From file: ${detected[key==='artist_id'?'artist':'album']||'metadata'}`;
    }}
    function select(key,value){
      const previousArtist=fields.artist_id;fields[key]=value;delete fields[key==='artist_id'?'artist_name':'album_name'];if(key==='album_id')delete fields.album_artist;touched.add(key);
      if(key==='artist_id'){
        const album=catalog.albums.find(a=>a.id===fields.album_id);
        if(album&&album.artist_id!==value&&(!previousArtist||album.artist_id===previousArtist)){delete fields.album_id;delete fields.album_artist_id;touched.add('album_id');}
      } else if(value)fields.album_artist_id=catalog.albums.find(a=>a.id===value)?.artist_id;
      else delete fields.album_artist_id;
      controls[key].input.focus();controls[key].list.hidden=true;controls[key].input.setAttribute('aria-expanded','false');
      controls[key].input.value=valueText(key);paint();config.change?.(key);
    }
    for(const [key,label] of Object.entries(names)){
      const kind=key==='artist_id'?'artists':'albums',wrap=el('div',undefined,'catalog-field catalog-combobox'),notice=el('p',undefined,'catalog-error'),heading=el('label',label),input=el('input'),list=el('div',undefined,'catalog-options');
      input.type='text';input.maxLength=200;input.autocomplete='off';input.setAttribute('aria-label',label);input.setAttribute('role','combobox');input.setAttribute('aria-autocomplete','list');input.setAttribute('aria-expanded','false');list.id='catalog-'+FreoUUID();list.setAttribute('role','listbox');input.setAttribute('aria-controls',list.id);list.hidden=true;heading.append(input);notice.setAttribute('role','status');wrap.append(heading,list,notice);container.append(wrap);controls[key]={input,list};
      function option(text,fn){const button=el('button',text);button.type='button';button.setAttribute('role','option');button.onmousedown=e=>e.preventDefault();button.onclick=()=>{fn();};list.append(button);return button;}
      function suggestions(){
        if(creating)return;list.replaceChildren();list.hidden=false;input.setAttribute('aria-expanded','true');
        if(config.importing)option('Use file metadata',()=>select(key,undefined));
        if(key==='album_id')option('No album / Single',()=>select(key,null));
        const query=input.value.trim(),identity=s=>s.trim().replace(/\s+/g,' ').toLocaleLowerCase();
        const rows=catalog[kind].filter(row=>row.name.toLocaleLowerCase().includes(query.toLocaleLowerCase()));
        rows.slice(0,30).forEach(row=>option(row.name+(key==='album_id'?' · '+(catalog.artists.find(a=>a.id===row.artist_id)?.name||''):''),()=>select(key,row.id)));
        if(query&&!rows.some(row=>identity(row.name)===identity(query))){
          const button=option(`Create “${query}”`,async()=>{
            if(creating)return;creating=true;button.disabled=true;notice.textContent='';config.pending?.(true);
            try{
              let owner=fields.artist_id;
              if(kind==='albums'&&!owner){
                const name=detected.album_artist||detected.artist;
                if(!name||name==='Unknown Artist')throw Error('Choose an artist before creating an album.');
                const result=await api(config.base+'/artists',config.csrf,{name});upsert(catalog,'artists',result);owner=result.id;
              }
              const result=await api(config.base+'/'+kind,config.csrf,{name:query,artist_id:owner||''});
              upsert(catalog,kind,result);select(key,result.id);config.message?.(`${label} selected${config.target?' for '+config.target:''}.`);
            }catch(error){notice.textContent=error.message;button.disabled=false;}finally{creating=false;config.pending?.(false);}
          });button.setAttribute('aria-label',`Create ${label.toLowerCase()} ${query}`);
        }
      }
      input.onfocus=()=>{input.select();suggestions();};input.oninput=suggestions;
      input.onkeydown=e=>{
        if(e.key==='Escape'){list.hidden=true;input.value=valueText(key);input.setAttribute('aria-expanded','false');}
        if(e.key==='ArrowDown'){e.preventDefault();if(list.hidden)suggestions();list.querySelector('button')?.focus();}
        if(e.key==='Enter'){e.preventDefault();const buttons=[...list.querySelectorAll('button')];const exact=buttons.find(b=>b.textContent===input.value.trim());(exact||buttons.at(-1))?.click();}
      };
      list.onkeydown=e=>{const buttons=[...list.querySelectorAll('button')],at=buttons.indexOf(document.activeElement);if(['ArrowDown','ArrowUp'].includes(e.key)){e.preventDefault();buttons[(at+(e.key==='ArrowDown'?1:buttons.length-1))%buttons.length]?.focus();}if(e.key==='Escape'){list.hidden=true;input.focus();list.hidden=true;input.setAttribute('aria-expanded','false');}};
      wrap.addEventListener('focusout',e=>{if(!wrap.contains(e.relatedTarget)){list.hidden=true;input.value=valueText(key);input.setAttribute('aria-expanded','false');}});
    }
    const dispose=subscribe(catalog,paint);paint();
    return {detected(data){detected=data||{};paint();},values(){const result={};if(!fields.artist_id&&fields.artist_name)result.artist_name=fields.artist_name;if(fields.album_id===undefined&&fields.album_name){result.album_name=fields.album_name;if(fields.album_artist)result.album_artist=fields.album_artist;}if(fields.artist_id)result.artist_id=Number(fields.artist_id);if(fields.album_id!==undefined)result.album_id=fields.album_id;if(fields.album_artist_id&&fields.album_id)result.album_artist_id=fields.album_artist_id;return result;},
      get pending(){return creating;},
      patch(){return Object.fromEntries([...touched].map(key=>[key,fields[key]??(key==='album_id'&&fields[key]===null?null:'file')]));},
      set(values){fields={...values};paint();},reset(){fields={};touched.clear();paint();},destroy:dispose,refresh:()=>load(config.base)};
  }
  function chips(container,catalog,values={},keys=['tags','categories']){
    const selected=Object.fromEntries(keys.map(key=>[key,new Set(values[key]||[])])),touched=new Set();
    for(const key of keys){const group=el('div',undefined,'music-toggle-group');group.setAttribute('role','group');group.setAttribute('aria-label',key);group.append(el('small',key));
      for(const item of catalog[key]||[]){const button=el('button',undefined,'music-toggle');button.type='button';const paint=()=>{button.textContent=(selected[key].has(item.id)?'✓ ':'+ ')+item.name;button.setAttribute('aria-pressed',selected[key].has(item.id)?'true':'false');};button.onclick=()=>{touched.add(key);container.dispatchEvent(new Event('classificationchange',{bubbles:true}));selected[key].has(item.id)?selected[key].delete(item.id):selected[key].add(item.id);paint();};paint();group.append(button);}container.append(group);}
    return {touched:()=>[...touched],clearTouched:()=>touched.clear(),values:()=>Object.fromEntries(Object.entries(selected).map(([key,value])=>[key,[...value]])),set(values){for(const key of keys){selected[key]=new Set(values[key]||[]);const buttons=container.querySelector(`[aria-label="${key}"]`).querySelectorAll('button');buttons.forEach((b,i)=>{const item=catalog[key][i];b.textContent=(selected[key].has(item.id)?'✓ ':'+ ')+item.name;b.setAttribute('aria-pressed',String(selected[key].has(item.id)));});}}};
  }
  function chooseCover(config,extra={},initialFile=null){
    return new Promise(resolve=>{
      const dialog=el('dialog',undefined,'studio-dialog artwork-dialog'),file=el('input'),canvas=el('canvas'),status=el('p'),save=el('button','Save artwork'),cancel=el('button','Cancel');
      file.type='file';file.accept='image/jpeg,image/png';file.setAttribute('aria-label','Album artwork file');canvas.width=canvas.height=320;save.type=cancel.type='button';save.disabled=true;status.setAttribute('role','status');
      dialog.append(el('h2','Album artwork'),el('p','Drop a JPEG or PNG here. Square, 3000 × 3000 recommended. Crop and position below.'),file,canvas);
      const sliders={};for(const [name,min,max,value] of [['Zoom',1,4,1],['Horizontal',0,100,50],['Vertical',0,100,50]]){const label=el('label',name),input=el('input');input.type='range';Object.assign(input,{min,max,value,step:.01});label.append(input);dialog.append(label);sliders[name]=input;input.oninput=draw;}
      dialog.append(status,save,cancel);document.body.append(dialog);dialog.showModal();let picture=null;
      function geometry(){const side=Math.min(picture.width,picture.height)/Number(sliders.Zoom.value);return [(picture.width-side)*Number(sliders.Horizontal.value)/100,(picture.height-side)*Number(sliders.Vertical.value)/100,side];}
      function draw(){if(!picture)return;const [x,y,side]=geometry();canvas.getContext('2d').drawImage(picture,x,y,side,side,0,0,320,320);}
      async function read(f){if(!f)return;if(f.size>20*1024*1024){status.textContent='Choose artwork under 20 MB';return;}try{const next=await createImageBitmap(f,{imageOrientation:'from-image'});if(next.width>10000||next.height>10000){next.close();throw Error('Artwork must be no larger than 10000 pixels per side');}picture?.close();picture=next;sliders.Zoom.value=1;sliders.Horizontal.value=sliders.Vertical.value=50;draw();save.disabled=false;status.textContent=Math.min(picture.width,picture.height)<640?'Small artwork may look blurry. It will not be enlarged.':'';}catch(e){status.textContent=e.message||'Choose a valid JPEG or PNG';}}
      if(initialFile)read(initialFile);
      file.onchange=()=>read(file.files[0]);dialog.ondragover=e=>e.preventDefault();dialog.ondrop=e=>{e.preventDefault();read(e.dataTransfer.files[0]);};
      const close=result=>{picture?.close();dialog.remove();resolve(result);};cancel.onclick=()=>close(null);dialog.oncancel=e=>{e.preventDefault();close(null);};scope.cleanup(()=>close(null));
      save.onclick=async()=>{save.disabled=true;try{const [x,y,side]=geometry(),out=el('canvas');out.width=out.height=Math.min(3000,Math.floor(side));out.getContext('2d').drawImage(picture,x,y,side,side,0,0,out.width,out.height);const blob=await new Promise(r=>out.toBlob(r,'image/jpeg',.93));const body=new FormData();body.append('file',blob,'cover.jpg');for(const [k,v] of Object.entries(extra))if(v)body.set(k,v);const result=await api(config.base.replace(/\/catalog$/,'/artwork'),config.csrf,body);close(result);}catch(e){status.textContent=e.message;save.disabled=false;}};
    });
  }
  window.FreoCatalog={load,selectors,chips,chooseCover,api,el,readResponse,decodeResponse};
  const album=document.getElementById('album-cover-editor');if(album)document.getElementById('album-cover-button').onclick=async()=>{const result=await chooseCover(album.dataset,{album_id:album.dataset.album});if(result){let img=document.querySelector('.album-head img');if(!img){img=el('img',undefined,'catalog-art large');document.querySelector('.album-head .catalog-art').replaceWith(img);}img.src=result.url;document.getElementById('album-cover-status').textContent='Album artwork saved';}};
})();
