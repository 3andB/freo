(() => {
  const scope=window.FreoPage,button=document.getElementById('copy-station-url');if(!button)return;
  scope.listen(button,'click',async()=>{
    const input=document.getElementById('station-public-url'),status=document.getElementById('copy-url-status');
    try{await navigator.clipboard.writeText(input.value);status.textContent=' Copied';}
    catch(_){input.focus();input.select();status.textContent=' Select and copy this URL';}
  });
})();
