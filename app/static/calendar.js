(() => {
  const dialog=document.getElementById('program-dialog');if(!dialog)return;
  const form=dialog.querySelector('form[method="post"]');let dragged=null;
  const open=(day,category,name)=>{
    form.elements.program_id.value='';
    if(day!==undefined)form.querySelectorAll('[name="weekday"]').forEach(input=>input.checked=input.value===String(day));
    if(category){form.elements.kind.value='category';form.elements.category.value=category;form.elements.name.value=name;}
    showKind();dialog.showModal();form.elements.name.focus();
  };
  const showKind=()=>form.querySelectorAll('[data-kind]').forEach(label=>label.hidden=label.dataset.kind!==form.elements.kind.value);
  form.elements.kind.addEventListener('change',showKind);
  document.querySelectorAll('[data-edit-program]').forEach(button=>button.addEventListener('click',()=>{const data=button.dataset;open(data.weekday);form.elements.program_id.value=data.id;form.elements.name.value=data.name;form.elements.start.value=data.start;form.elements.end.value=data.end;form.elements.kind.value='clock';form.elements.clock.value=data.clock;form.elements.on_date.value=data.onDate;showKind();}));
  document.querySelectorAll('[data-new-program]').forEach(button=>button.addEventListener('click',()=>open(button.dataset.day)));
  document.querySelectorAll('[data-category]').forEach(button=>{
    button.addEventListener('click',()=>open(undefined,button.dataset.category,button.dataset.categoryName));
    button.addEventListener('dragstart',event=>{dragged=button.dataset;event.dataTransfer.setData('text/plain',button.dataset.category);});
    button.addEventListener('dragend',()=>dragged=null);
  });
  document.querySelectorAll('.calendar-day-body').forEach(day=>{
    day.addEventListener('dragover',event=>{if(dragged){event.preventDefault();day.classList.add('drag-over');}});
    day.addEventListener('dragleave',()=>day.classList.remove('drag-over'));
    day.addEventListener('drop',event=>{if(!dragged)return;event.preventDefault();day.classList.remove('drag-over');open(day.dataset.day,dragged.category,dragged.categoryName);});
  });
})();
