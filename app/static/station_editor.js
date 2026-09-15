(() => {
  document.querySelectorAll('.station-editor form').forEach(form=>{
    const name=form.querySelector('[data-station-name]'),slug=form.querySelector('[data-public-slug]'),preview=form.querySelector('[data-url-preview]');
    let custom=false;
    name.addEventListener('input',()=>{if(!custom){slug.value=name.value.toLowerCase().normalize('NFKD').replace(/[\u0300-\u036f]/g,'').replace(/[^a-z0-9]+/g,'-').replace(/^-|-$/g,'').slice(0,64);preview.textContent=slug.value;}});
    slug.addEventListener('input',()=>{custom=true;preview.textContent=slug.value;});
  });
})();
