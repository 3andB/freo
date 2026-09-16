(() => {
 const label=document.querySelector('.schedule-mode-status');if(!label||document.getElementById('schedule-studio'))return;
 async function refresh(){if(document.hidden)return;try{const response=await fetch(label.dataset.statusUrl);if(!response.ok)return;const state=await response.json();const switching=state.transition&&['PENDING','PREPARING','FADING'].includes(state.transition.state);label.textContent=switching?`Switching ${state.mode} → ${state.transition.mode}…`:`Active mode: ${state.mode.charAt(0)+state.mode.slice(1).toLowerCase()}`;if(state.playing_fallback)label.textContent+=' · Default playlist';}catch{}}
 window.FreoPage.interval(refresh,8000);refresh();
})();
