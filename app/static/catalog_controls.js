(() => {
  const scope=FreoPage;
  const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
  async function api(url,csrf,payload){
    const body=payload instanceof FormData?payload:new FormData();
    if(!(payload instanceof FormData))for(const [k,v] of Object.entries(payload))body.set(k,v);
    body.set('csrf',csrf);
    const response=await scope.fetch(url,{method:'POST',body,headers:{Accept:'application/json'}});
    if(!response.headers.get('content-type')?.includes('application/json'))throw Error('Session unavailable. Sign in again to save.');
    const result=await response.json();if(!response.ok)throw Error(result.message||'Unable to save');return result;
  }
  async function load(base){const response=await scope.fetch(base,{cache:'no-store'});if(!response.ok)throw Error('Catalog could not load');return response.json();}
  function selectors(container,catalog,initial,config){
    let data=catalog,detected={};
    const artist=el('select'),album=el('select'),search=el('input');search.type='search';search.placeholder='Search artists';search.setAttribute('aria-label','Search artists');
    artist.setAttribute('aria-label','Artist');album.setAttribute('aria-label','Album');
    const fields={artist_id:initial.artist_id||'',album_id:initial.album_id??undefined};
    function populate(){
      const chosen=String(fields.artist_id||'');artist.replaceChildren(new Option(config.importing?(detected.artist?`From file: ${detected.artist}`:'From file metadata'):'Choose artist',''));
      data.artists.filter(a=>String(a.id)===chosen||a.name.toLowerCase().includes(search.value.toLowerCase())).forEach(a=>artist.append(new Option(a.name,a.id)));
      artist.value=chosen;album.replaceChildren(new Option(config.importing?(detected.album?`From file: ${detected.album}`:'From file metadata'):'Single / No album',''));
      if(config.importing)album.append(new Option('Single / No album','single'));
      data.albums.filter(a=>String(a.artist_id)===chosen).forEach(a=>album.append(new Option(a.name,a.id)));
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
        save.onclick=async()=>{if(!name.value.trim()){error.textContent='Enter a name';return;}save.disabled=true;try{const result=await api(config.base+'/'+kind,config.csrf,{name:name.value,artist_id:fields.artist_id});data=await load(config.base);if(kind==='artists'){fields.artist_id=result.id;fields.album_id=config.importing?undefined:null;search.value='';}else fields.album_id=result.id;populate();config.change?.();close();}catch(e){error.textContent=e.message;save.disabled=false;}};
        name.addEventListener('keydown',event=>{if(event.key==='Enter'){event.preventDefault();save.click();}});
      });
    }
    search.addEventListener('input',populate);
    artist.addEventListener('change',()=>{fields.artist_id=artist.value;fields.album_id=config.importing?undefined:null;populate();config.change?.();});
    album.addEventListener('change',()=>{fields.album_id=album.value==='single'?null:album.value|| (config.importing?undefined:null);config.change?.();});populate();
    return {detected(values){detected=values;populate();},values:()=>{const result={};if(fields.artist_id)result.artist_id=Number(fields.artist_id);if(fields.album_id!==undefined)result.album_id=fields.album_id?Number(fields.album_id):null;return result;},set(values){Object.assign(fields,values);populate();},refresh:async()=>{data=await load(config.base);populate();}};
  }
  function chips(container,catalog,values={}){
    const selected={tags:new Set(values.tags||[]),categories:new Set(values.categories||[])};
    for(const key of ['tags','categories']){const group=el('div',undefined,'music-toggle-group');group.setAttribute('role','group');group.setAttribute('aria-label',key);group.append(el('small',key));
      for(const item of catalog[key]){const button=el('button',undefined,'music-toggle');button.type='button';const paint=()=>{button.textContent=(selected[key].has(item.id)?'✓ ':'+ ')+item.name;button.setAttribute('aria-pressed',selected[key].has(item.id)?'true':'false');};button.onclick=()=>{selected[key].has(item.id)?selected[key].delete(item.id):selected[key].add(item.id);paint();};paint();group.append(button);}container.append(group);}
    return {values:()=>Object.fromEntries(Object.entries(selected).map(([key,value])=>[key,[...value]])),set(values){for(const key of ['tags','categories']){selected[key]=new Set(values[key]||[]);const buttons=container.querySelector(`[aria-label="${key}"]`).querySelectorAll('button');buttons.forEach((b,i)=>{const item=catalog[key][i];b.textContent=(selected[key].has(item.id)?'✓ ':'+ ')+item.name;b.setAttribute('aria-pressed',String(selected[key].has(item.id)));});}}};
  }
  function chooseCover(config,extra={}){
    return new Promise(resolve=>{
      const dialog=el('dialog',undefined,'studio-dialog artwork-dialog'),file=el('input'),canvas=el('canvas'),status=el('p'),save=el('button','Save artwork'),cancel=el('button','Cancel');
      file.type='file';file.accept='image/jpeg,image/png';file.setAttribute('aria-label','Album artwork file');canvas.width=canvas.height=320;save.type=cancel.type='button';save.disabled=true;status.setAttribute('role','status');
      dialog.append(el('h2','Album artwork'),el('p','Drop a JPEG or PNG here. Square, 3000 × 3000 recommended. Crop and position below.'),file,canvas);
      const sliders={};for(const [name,min,max,value] of [['Zoom',1,4,1],['Horizontal',0,100,50],['Vertical',0,100,50]]){const label=el('label',name),input=el('input');input.type='range';Object.assign(input,{min,max,value,step:.01});label.append(input);dialog.append(label);sliders[name]=input;input.oninput=draw;}
      dialog.append(status,save,cancel);document.body.append(dialog);dialog.showModal();let picture=null;
      function geometry(){const side=Math.min(picture.width,picture.height)/Number(sliders.Zoom.value);return [(picture.width-side)*Number(sliders.Horizontal.value)/100,(picture.height-side)*Number(sliders.Vertical.value)/100,side];}
      function draw(){if(!picture)return;const [x,y,side]=geometry();canvas.getContext('2d').drawImage(picture,x,y,side,side,0,0,320,320);}
      async function read(f){if(!f)return;if(f.size>20*1024*1024){status.textContent='Choose artwork under 20 MB';return;}try{const next=await createImageBitmap(f,{imageOrientation:'from-image'});if(next.width>10000||next.height>10000){next.close();throw Error('Artwork must be no larger than 10000 pixels per side');}picture?.close();picture=next;sliders.Zoom.value=1;sliders.Horizontal.value=sliders.Vertical.value=50;draw();save.disabled=false;status.textContent=Math.min(picture.width,picture.height)<640?'Small artwork may look blurry. It will not be enlarged.':'';}catch(e){status.textContent=e.message||'Choose a valid JPEG or PNG';}}
      file.onchange=()=>read(file.files[0]);dialog.ondragover=e=>e.preventDefault();dialog.ondrop=e=>{e.preventDefault();read(e.dataTransfer.files[0]);};
      const close=result=>{picture?.close();dialog.remove();resolve(result);};cancel.onclick=()=>close(null);dialog.oncancel=e=>{e.preventDefault();close(null);};scope.cleanup(()=>close(null));
      save.onclick=async()=>{save.disabled=true;try{const [x,y,side]=geometry(),out=el('canvas');out.width=out.height=Math.min(3000,Math.floor(side));out.getContext('2d').drawImage(picture,x,y,side,side,0,0,out.width,out.height);const blob=await new Promise(r=>out.toBlob(r,'image/jpeg',.93));const body=new FormData();body.append('file',blob,'cover.jpg');for(const [k,v] of Object.entries(extra))if(v)body.set(k,v);const result=await api(config.base.replace(/\/catalog$/,'/artwork'),config.csrf,body);close(result);}catch(e){status.textContent=e.message;save.disabled=false;}};
    });
  }
  window.FreoCatalog={load,selectors,chips,chooseCover,api,el};
  const album=document.getElementById('album-cover-editor');if(album)document.getElementById('album-cover-button').onclick=async()=>{const result=await chooseCover(album.dataset,{album_id:album.dataset.album});if(result){let img=document.querySelector('.album-head img');if(!img){img=el('img',undefined,'catalog-art large');document.querySelector('.album-head .catalog-art').replaceWith(img);}img.src=result.url;document.getElementById('album-cover-status').textContent='Album artwork saved';}};
})();
