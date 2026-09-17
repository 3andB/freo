(() => {
  const form = document.querySelector('[data-website-editor]');
  if (!form) return;
  const scope = window.FreoPage, state = document.querySelector('.website-save-state');
  let dirty = false;
  function changed() {dirty = true; state.textContent = 'Unsaved changes'; state.classList.add('is-dirty');}
  scope.listen(form,'input',changed); scope.listen(form,'change',changed);
  scope.listen(form,'submit',() => {dirty = false;});
  scope.listen(window,'beforeunload',event => {if(dirty){event.preventDefault();event.returnValue='';}});
  // The workspace otherwise intercepts internal links before beforeunload can run.
  scope.listen(document,'click',event => {
    const link = event.target.closest('a[href]');
    if(dirty && link && !link.target && !link.getAttribute('href').startsWith('#')) {
      event.preventDefault();event.stopImmediatePropagation();
      window.FreoDialog.confirm({title:'Leave unsaved changes?',message:'Save your draft before leaving to keep these changes.',confirmLabel:'Leave without saving',signal:scope.signal}).then(ok=>{if(ok){dirty=false;location.assign(link.href);}});
    }
  },{capture:true});
  scope.listen(form,'click',event => {
    const button = event.target.closest('[data-move]');if(!button)return;
    const row = button.closest('.website-order-row'), list = row.parentElement;
    if(button.dataset.move==='up' && row.previousElementSibling)list.insertBefore(row,row.previousElementSibling);
    if(button.dataset.move==='down' && row.nextElementSibling)list.insertBefore(row.nextElementSibling,row);
    button.focus();changed();
  });
  const palettes = {
    olive:['#f5f3ed','#ffffff','#242a23','#365b38','#171d19','#222b24','#f5f3ed','#c5d5a8'],
    ocean:['#eef3f5','#ffffff','#1f303e','#285977','#141e29','#1c2b38','#eef3f5','#a6cee6'],
    clay:['#f7f1eb','#ffffff','#392a26','#85442f','#251b19','#342521','#fff3eb','#efb49c']
  };
  scope.listen(form.querySelector('[data-website-palette]'),'change',event=>{
    const colors=palettes[event.target.value];if(!colors)return;
    ['background','surface','text','accent','night_background','night_surface','night_text','night_accent'].forEach((key,i)=>form.elements[key].value=colors[i]);changed();
  });
})();
