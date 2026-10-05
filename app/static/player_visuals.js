/* Read-only visualization: native audio playback never depends on this module. */
(() => {
  const root = document.querySelector('.radio-experience'), canvas = document.getElementById('player-visual');
  const select = document.getElementById('visual-mode'), scope = window.FreoPage;
  if (!root || !canvas || !select || !scope) return;
  let ctx;
  try {ctx = canvas.getContext('2d');} catch {return;}
  if (!ctx) return;
  const modes = ['fractal', 'spectrum', 'waveform', 'particles', 'ambient'];
  const key = 'freo-visual-' + root.dataset.station;
  try {const saved = localStorage.getItem(key); if (modes.includes(saved)) select.value = saved;} catch {}
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  let audio = null, captured = null, context = null, analyser = null, source = null, raf = 0, last = 0, phase = 0, disposed = false;
  const frequency = new Uint8Array(128), waveform = new Uint8Array(256);
  const motion = () => !reduced.matches && !root.classList.contains('low-motion') && !document.hidden && audio && !audio.paused && root.classList.contains('is-playing');
  function detach() {
    try {source?.disconnect(); captured?.getTracks().forEach(track => track.stop()); context?.close().catch(() => {});} catch {}
    captured = context = analyser = source = null;
  }
  function observeAudio() {
    const next = document.getElementById('station-audio');
    if (audio !== next) {detach(); audio = next;}
    if (!audio || audio.paused || captured || !(audio.captureStream || audio.mozCaptureStream)) return;
    try {
      captured = (audio.captureStream || audio.mozCaptureStream).call(audio);
      const attach = () => {
        if (disposed || analyser || !captured?.getAudioTracks().length) return;
        context = new (window.AudioContext || window.webkitAudioContext)();
        analyser = context.createAnalyser(); analyser.fftSize = 256;
        source = context.createMediaStreamSource(captured); source.connect(analyser);
        // Deliberately no connection to context.destination: no double playback.
        context.resume().catch(() => {});
      };
      captured.addEventListener('addtrack', attach); attach();
    } catch {detach();}
  }
  function size() {
    const bounds = canvas.getBoundingClientRect(), ratio = Math.min(devicePixelRatio || 1, 2);
    canvas.width = Math.max(1, Math.round(bounds.width * ratio)); canvas.height = Math.max(1, Math.round(bounds.height * ratio));
    draw();
  }
  function draw() {
    const w = canvas.width, h = canvas.height, cx = w / 2, cy = h / 2, unit = Math.min(w, h);
    ctx.clearRect(0, 0, w, h); ctx.fillStyle = '#10242c'; ctx.fillRect(0, 0, w, h);
    let measured = false, energy = .12;
    if (analyser && context?.state === 'running' && audio && !audio.paused) {
      try {analyser.getByteFrequencyData(frequency); analyser.getByteTimeDomainData(waveform); measured = true; energy = frequency.reduce((a,b) => a+b, 0) / (128*255);} catch {}
    }
    const mode = select.value;
    canvas.dataset.mode = mode;
    document.getElementById('visual-status').textContent = ['spectrum','waveform'].includes(mode) && !measured ? 'Audio analysis unavailable; showing a resting visual.' : mode + ' visualization';
    ctx.strokeStyle = '#a9e8ce'; ctx.fillStyle = '#a9e8ce'; ctx.lineWidth = Math.max(1, w / 350);
    if (mode === 'spectrum') {
      for (let i=0; i<48; i++) {const height = measured ? Math.max(2,frequency[i*2]/255*h*.72) : 2; ctx.fillRect(w*.1+i*w*.8/48, h*.84-height, w*.8/64, height);}
    } else if (mode === 'waveform') {
      ctx.beginPath(); for(let i=0;i<256;i++){const x=i*w/255, y=cy+(measured?(waveform[i]-128)/128*h*.4:0); if(i)ctx.lineTo(x,y);else ctx.moveTo(x,y);} ctx.stroke();
    } else if (mode === 'fractal') {
      const branch = (x,y,length,angle,depth) => {if (!depth) return;const nx=x+Math.cos(angle)*length,ny=y+Math.sin(angle)*length;ctx.beginPath();ctx.moveTo(x,y);ctx.lineTo(nx,ny);ctx.stroke();const spread=.48+Math.sin(phase*.3)*.12+energy*.25;branch(nx,ny,length*.69,angle-spread,depth-1);branch(nx,ny,length*.69,angle+spread,depth-1);};
      branch(cx,h*.9,unit*.24,-Math.PI/2,7);
    } else if (mode === 'particles') {
      for(let i=0;i<64;i++){const angle=i*2.399+phase*.18,radius=unit*(.08+(i%17)/50)+energy*unit*.1;ctx.globalAlpha=.35+(i%7)/12;ctx.beginPath();ctx.arc(cx+Math.cos(angle)*radius,cy+Math.sin(angle*1.07)*radius,unit*(.003+(i%4)*.002),0,Math.PI*2);ctx.fill();}ctx.globalAlpha=1;
    } else {
      for(let ring=0;ring<6;ring++){ctx.beginPath();for(let i=0;i<=6;i++){const a=i*Math.PI/3+phase*.06*(ring%2?1:-1),r=unit*(.09+ring*.05+energy*.06);const x=cx+Math.cos(a)*r,y=cy+Math.sin(a)*r;if(i)ctx.lineTo(x,y);else ctx.moveTo(x,y);}ctx.stroke();}
    }
  }
  function tick(now) {
    raf=0;if(disposed)return;
    try {if(now-last>=33){phase+=Math.min((now-last)/1000,.1);last=now;draw();}if(motion())raf=requestAnimationFrame(tick);}catch{canvas.hidden=true;}
  }
  function update() {
    if(disposed)return;
    try {observeAudio();draw();if(motion()&&!raf)raf=requestAnimationFrame(tick);else if(!motion()){cancelAnimationFrame(raf);raf=0;}}catch{canvas.hidden=true;}
  }
  select.addEventListener('change', () => {try{localStorage.setItem(key,select.value);}catch{} update();});
  const observer = new MutationObserver(update);
  observer.observe(root,{attributes:true,attributeFilter:['class']});
  scope.listen(document,'playing',update,true);scope.listen(document,'pause',update,true);
  scope.listen(document,'visibilitychange',update);scope.listen(reduced,'change',update);
  const resize = new ResizeObserver(size);resize.observe(canvas);
  scope.cleanup(() => {disposed=true;cancelAnimationFrame(raf);observer.disconnect();resize.disconnect();detach();});
  try {size();update();}catch{canvas.hidden=true;}
})();
