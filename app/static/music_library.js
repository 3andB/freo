(() => {
  const form=document.getElementById('music-organizer');
  if(!form)return;
  let dragged=null;
  form.querySelectorAll('tr[data-song]').forEach(row=>row.addEventListener('dragstart',()=>{
    dragged=row.dataset.song;const box=row.querySelector('input[type=checkbox]');if(box)box.checked=true;
  }));
  form.querySelectorAll('.category-target').forEach(target=>{
    target.addEventListener('dragover',event=>{event.preventDefault();target.classList.add('is-dragging');});
    target.addEventListener('dragleave',()=>target.classList.remove('is-dragging'));
    target.addEventListener('drop',event=>{event.preventDefault();target.classList.remove('is-dragging');if(!dragged)return;const box=form.querySelector(`input[value="${CSS.escape(dragged)}"]`);if(box)box.checked=true;target.click();});
  });
})();
