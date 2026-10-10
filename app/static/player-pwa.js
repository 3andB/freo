/* Native install prompt only. Kept across player navigation, without duplicate listeners. */
(() => {
  if(window.FreoPlayerInstall){window.FreoPlayerInstall.update();return;}
  let pending=null;
  const standalone=()=>matchMedia('(display-mode: standalone)').matches || navigator.standalone===true;
  const update=()=>{const button=document.getElementById('install-freo');if(button)button.hidden=!pending || standalone();};
  window.FreoPlayerInstall={update};
  window.addEventListener('beforeinstallprompt',event=>{event.preventDefault();pending=event;update();});
  window.addEventListener('appinstalled',()=>{pending=null;update();});
  matchMedia('(display-mode: standalone)').addEventListener('change',update);
  document.addEventListener('click',async event=>{
    if(!event.target.closest('#install-freo') || !pending || standalone())return;
    const prompt=pending;pending=null;update();
    try{await prompt.prompt();await prompt.userChoice;}catch{}
  });
  if('serviceWorker' in navigator && isSecureContext)navigator.serviceWorker.register('/player/sw.js',{scope:'/player/'}).catch(error=>console.warn('Freo offline shell unavailable:',error.name));
  update();
})();
