(() => {
  const scope=FreoPage;
  document.querySelectorAll('form').forEach(form=>{
    const name=form.querySelector('[name="name"]'),slug=form.querySelector('[name="slug"]');
    if(name&&slug){let edited=!!slug.value;slug.addEventListener('input',()=>edited=true);name.addEventListener('input',()=>{if(!edited)slug.value=name.value.toLowerCase().normalize('NFKD').replace(/[\u0300-\u036f]/g,'').replace(/[^a-z0-9]+/g,'-').replace(/^-|-$/g,'').slice(0,64);});}
  });
  const drop=document.querySelector('[data-membership-drop]');if(!drop)return;
  let dragged=null;
  document.querySelectorAll('[data-track-id]').forEach(row=>{
    row.addEventListener('dragstart',event=>{dragged=row.dataset.trackId;event.dataTransfer.setData('text/plain',dragged);});
    row.addEventListener('dragend',()=>{dragged=null;drop.classList.remove('drag-over');});
  });
  drop.addEventListener('dragover',event=>{if(dragged){event.preventDefault();drop.classList.add('drag-over');}});
  drop.addEventListener('dragleave',()=>drop.classList.remove('drag-over'));
  drop.addEventListener('drop',event=>{
    if(!dragged)return;event.preventDefault();
    const form=drop.closest('form');form.querySelectorAll('[name="track_uuid"]').forEach(el=>el.checked=el.value===dragged);
    form.requestSubmit(form.querySelector('button[type="submit"]'));
  });
})();
