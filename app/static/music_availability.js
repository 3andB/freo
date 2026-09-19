(() => {
  const scope=FreoPage;
  async function save(form){
    const button=form.querySelector('[type=submit]'),status=form.querySelector('[role=status]');
    if(button.disabled)return false;button.disabled=true;status.textContent='Saving…';
    try{
      const response=await scope.fetch(form.action,{method:'POST',body:new FormData(form),headers:{Accept:'application/json'}});
      if(!response.headers.get('content-type')?.includes('application/json'))throw Error('Could not save. Check your connection and sign-in.');
      const result=await response.json();if(!response.ok)throw Error(result.message||'Could not save availability.');
      status.textContent=result.message;document.dispatchEvent(new CustomEvent('freo:form-saved',{detail:{form}}));const badge=form.closest('.availability-card')?.querySelector('.availability-badge');if(badge)badge.textContent=form.elements.available_to_all.checked||form.dataset.inherited==='true'?'All channels':form.dataset.owner;document.dispatchEvent(new Event('music-availability-saved'));return true;
    }catch(error){status.textContent=error.message;return false;}finally{button.disabled=false;}
  }
  scope.listen(document,'submit',event=>{if(event.target.matches('[data-availability-form]')){event.preventDefault();save(event.target);}}, {capture:true});
  window.FreoAvailability={open(song,csrf){
    if(document.querySelector('.availability-dialog'))return;
    const previous=document.activeElement,availability=song.availability,dialog=document.createElement('dialog');dialog.className='studio-dialog availability-dialog';
    dialog.innerHTML='<h2 id="availability-dialog-title">Channel availability</h2><p class="availability-song"></p><form><input type="hidden" name="csrf"><label class="availability-option"><input type="checkbox" name="available_to_all"><span><strong>Available to all channels</strong><small>Includes channels added later.</small></span></label><p class="availability-inherited"></p><p role="status" aria-live="polite"></p><div class="availability-actions"><button type="button">Cancel</button><button type="submit" class="ui-primary">Save availability</button></div></form>';
    dialog.setAttribute('aria-labelledby','availability-dialog-title');dialog.querySelector('.availability-song').textContent=song.title;
    const form=dialog.querySelector('form');form.action=availability.url;form.elements.csrf.value=csrf;form.elements.available_to_all.checked=availability.direct;
    dialog.querySelector('.availability-inherited').textContent=availability.inherited?'Also shared through its artist or album. Turning this switch off keeps that inherited availability.':`When off, available to ${availability.owner}.`;
    const close=()=>{dialog.close();dialog.remove();if(previous?.isConnected)previous.focus();};
    form.querySelector('[type=button]').onclick=close;dialog.oncancel=e=>{e.preventDefault();close();};dialog.onclick=e=>{if(e.target===dialog){const r=dialog.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)close();}};
    form.onsubmit=async e=>{e.preventDefault();if(await save(form)){availability.direct=form.elements.available_to_all.checked;availability.effective=availability.direct||availability.inherited;close();}};
    document.body.append(dialog);dialog.showModal();scope.cleanup(close);
  }};
})();
