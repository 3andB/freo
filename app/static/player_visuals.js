/* Optional, read-only presentation. Native stream playback owns its audio path. */
(() => {
  const root = document.querySelector('.radio-experience'), scope = window.FreoPage;
  const $ = id => document.getElementById(id), dialog = $('visualizer-dialog');
  if (!root || !scope || !dialog) return;
  const canvas = $('player-visual'), stage = dialog.querySelector('.visualizer-stage');
  const select = $('visual-mode'), palette = $('visual-palette'), status = $('visual-status');
  const fullscreen = $('visualizer-fullscreen');
  const key = 'freo-visual-' + root.dataset.station;
  const modes = Array.from(select.options, option => option.value);
  const palettes = {aurora: [155, 205, 285], sunset: [18, 335, 275], electric: [190, 260, 320], ocean: [190, 215, 170], amethyst: [265, 290, 225], rose_gold: [345, 20, 42], emerald: [145, 170, 80], solar: [42, 18, 330]};
  try {
    const saved = localStorage.getItem(key); if (modes.includes(saved)) select.value = saved;
    const savedPalette = localStorage.getItem(key + '-palette'); if (Object.hasOwn(palettes, savedPalette)) palette.value = savedPalette;
  } catch {}
  let ctx, audio, context, analyser, scenes;
  let sceneTime = 0, sceneElapsed = 0, fractalTime = 0;
  const tempo=window.FreoVisualScenes?.createTempo();
  let beat={bpm:0,pulse:0,onsets:0};
  let fullscreenNoticeUntil = 0;
  let raf = 0, last = 0, phase = 0, disposed = false, failed = false;
  let bass = 0, mids = 0, treble = 0, energy = 0, measured = false;
  const frequency = new Uint8Array(512), waveform = new Uint8Array(1024), decibels = new Float32Array(512);
  let spectrumEdges = [], spectrumRate = 0, waitingSince = 0;
  const retry = $('visualizer-retry');
  const bars = new Float32Array(64), peaks = new Float32Array(64);
  const particles = Array.from({length: 150}, (_, i) => ({angle: i * 2.399963, radius: ((i * 73) % 151) / 151, size: 1 + i % 4}));
  const active = () => dialog.open && !disposed && !failed && !document.hidden;
  const moving = () => active() && audio && !audio.paused && !audio.ended && analyser && context?.state==='running';
  const color = (index, alpha = 1, light = 65) => `hsla(${palettes[palette.value][index % 3]},95%,${light}%,${alpha})`;
  function detach() {
    window.FreoAudioAnalysis?.deactivate();
    context = analyser = null;
    measured = false; bass = mids = treble = energy = 0; bars.fill(0); peaks.fill(0);
    beat=tempo?.sample(frequency,0,false) || {bpm:0,pulse:0,onsets:0};waitingSince=0;
  }
  function fail() {
    failed = true; cancelAnimationFrame(raf); raf = 0; detach(); canvas.hidden = true;
    status.textContent = 'Visualization unavailable. Your audio keeps playing.';
  }
  function observeAudio() {
    audio = $('station-audio');
    const graph = window.FreoAudioAnalysis?.read(audio);
    context = graph?.context; analyser = graph?.analyser;
    canvas.dataset.analysisReason = graph?.error || '';
  }
  function sample(dt) {
    measured = !!(analyser && context?.state === 'running' && audio && !audio.paused);
    if (measured) {
      try {analyser.getByteFrequencyData(frequency); analyser.getByteTimeDomainData(waveform);} catch(error) {canvas.dataset.analysisReason=error.name || 'AnalysisError';window.FreoAudioAnalysis?.fail(error);analyser=null;measured=false;}
    }
    if (!measured) {frequency.fill(0); waveform.fill(128);}
    const band = (from, to) => {
      let total = 0; for (let i = from; i < to; i++) total += frequency[i] * frequency[i];
      return Math.sqrt(total / (to - from)) / 255;
    };
    const smooth = 1 - Math.exp(-dt * 12);
    bass += (band(1, 7) - bass) * smooth; mids += (band(7, 60) - mids) * smooth;
    treble += (band(60, 220) - treble) * smooth;
    let rms = 0;
    for (const value of waveform) rms += Math.pow((value - 128) / 128, 2);
    energy = Math.min(1, Math.sqrt(rms / waveform.length) * 2 + bass * .35 + mids * .3 + treble * .15);
    // Distinct contiguous FFT bands: never repeat the first bin across bars.
    if (context && analyser && spectrumRate !== context.sampleRate) {
      spectrumRate = context.sampleRate;
      const limit = Math.min(512, Math.floor(20000 * analyser.fftSize / spectrumRate) + 1);
      spectrumEdges = [1];
      for (let i=1;i<=64;i++) spectrumEdges.push(Math.min(limit-64+i, Math.max(spectrumEdges[i-1]+1, Math.round(Math.pow(limit,i/64)))));
    }
    if (select.value === 'spectrum') {
      decibels.fill(-Infinity);
      if (measured) {try {analyser.getFloatFrequencyData(decibels);} catch { /* Keep playback independent. */ }}
      for (let i=0;i<bars.length;i++) {
        let peak=-Infinity;
        for(let bin=spectrumEdges[i] || 1;bin<(spectrumEdges[i+1] || 1);bin++)peak=Math.max(peak,decibels[bin]);
        const level=Math.max(0,Math.min(1,(peak+90)/80));
        bars[i]+=(level-bars[i])*smooth;peaks[i]=Math.max(bars[i],peaks[i]-dt*.25);
      }
    }
    beat=tempo?.sample(frequency,sceneElapsed,measured) || beat;
    canvas.dataset.bpm=beat.bpm?String(Math.round(beat.bpm)):'';
    canvas.dataset.beatOnsets=String(beat.onsets);
    const signal = measured && (frequency.some(value=>value>0) || rms>.000001);
    if (signal || !audio || audio.paused) waitingSince=0;
    else waitingSince ||= performance.now();
    const waiting = !!waitingSince && performance.now()-waitingSince>6000;
    canvas.dataset.contextState=context?.state || 'unavailable';
    canvas.dataset.signal=signal?'present':'waiting';
    if(retry)retry.hidden=!(audio && !audio.paused && ((!measured) || waiting));
    canvas.dataset.analysis = measured ? 'live' : 'unavailable';
    const notice = waiting ? 'No audio samples yet. Enable visuals to retry.' : measured ? '' : audio && !audio.paused ? 'Audio analysis unavailable · resting visual' : 'Press play on the player to bring this scene to life.';
    if (performance.now() > fullscreenNoticeUntil && status.textContent !== notice) status.textContent = notice;
  }
  function line(points, stroke, width) {
    ctx.beginPath(); points.forEach(([x, y], i) => i ? ctx.lineTo(x, y) : ctx.moveTo(x, y));
    ctx.strokeStyle = stroke; ctx.lineWidth = width; ctx.stroke();
  }
  // Bounded geometry shared by all frames; no image downloads or graphics framework.
  const stars = Array.from({length:110}, (_,i)=>({x:((i*73+19)%211)/211,y:((i*137+31)%223)/223,size:.5+i%3*.4}));
  const continents = [
    [[-.72,-.52],[-.43,-.7],[-.1,-.58],[-.15,-.39],[-.32,-.25],[-.21,-.05],[-.38,.02],[-.51,-.19],[-.7,-.28]],
    [[-.28,.04],[-.03,.13],[.06,.35],[-.11,.66],[-.26,.8],[-.29,.47],[-.39,.2]],
    [[.05,-.53],[.34,-.65],[.7,-.46],[.88,-.18],[.6,-.07],[.43,-.23],[.25,-.1],[.29,.22],[.1,.51],[-.06,.18],[-.04,-.09],[.11,-.23]],
    [[.56,.43],[.77,.38],[.89,.56],[.72,.69],[.53,.59]]
  ];
  const worlds = [
    {orbit:.28,offset:.5,speed:.075,size:.018,tint:'#dc8667',kind:'mars'},
    {orbit:.38,offset:2.4,speed:.036,size:.041,tint:'#cfb896',kind:'jupiter'},
    {orbit:.46,offset:4.1,speed:.024,size:.032,tint:'#d9c89b',kind:'saturn'},
    {orbit:.35,offset:5.4,speed:.046,size:.023,tint:'#6596e5',kind:'neptune'}
  ];
  let auroraSurface, auroraContext, auroraDetail=1, auroraCost=0, auroraFrames=0;
  scope.cleanup(()=>{if(auroraSurface)auroraSurface.width=auroraSurface.height=1;auroraSurface=auroraContext=null;});
  function aurora(w,h) {
    const started=performance.now();
    auroraSurface ||= document.createElement('canvas');auroraContext ||= auroraSurface.getContext('2d');
    const skyHeight=Math.round(h*.67);
    const skyRatio=Math.min(1,Math.sqrt(350000*auroraDetail/(w*skyHeight))),skyWidth=Math.max(1,Math.round(w*skyRatio)),skyPixels=Math.max(1,Math.round(skyHeight*skyRatio));
    if(auroraSurface.width!==skyWidth || auroraSurface.height!==skyPixels){auroraSurface.width=skyWidth;auroraSurface.height=skyPixels;}
    const main=ctx;ctx=auroraContext;
    try {
      ctx.setTransform(skyWidth/w,0,0,skyPixels/skyHeight,0,0);ctx.clearRect(0,0,w,skyHeight);
      ctx.fillStyle='#dce9ff';
      const count=w<700?48:85;
      for(let i=0;i<count;i++){const star=stars[i];ctx.globalAlpha=.22+star.size*.13+treble*.12;ctx.beginPath();ctx.arc(star.x*w,star.y*skyHeight*.9,Math.max(.5,star.size*w/1200),0,Math.PI*2);ctx.fill();}ctx.globalAlpha=1;
      auroraCurtains(w,skyHeight);
      const cycle=(sceneTime+2)%23;
      canvas.dataset.auroraComet=cycle<7?'visible':'waiting';
      if(cycle<7){const t=cycle/7,x=w*(-.1+t*1.3),y=skyHeight*(.06+t*.4),length=w*.12;
        const trail=ctx.createLinearGradient(x-length,y-length*.25,x,y);trail.addColorStop(0,'#b5bfff00');trail.addColorStop(1,`rgba(224,239,255,${.45+energy*.4})`);
        line([[x-length,y-length*.25],[x,y]],trail,Math.max(1,w*.002));ctx.fillStyle='#eaf4ff';ctx.beginPath();ctx.arc(x,y,Math.max(1,w*.0018),0,Math.PI*2);ctx.fill();}
    }finally{ctx=main;}
    ctx.drawImage(auroraSurface,0,0,w,skyHeight);
    const lake=ctx.createLinearGradient(0,skyHeight,0,h);lake.addColorStop(0,'#132137');lake.addColorStop(1,'#030812');ctx.fillStyle=lake;ctx.fillRect(0,skyHeight,w,h-skyHeight);
    // Reflected sky strips stay bounded; ripples move without pixel readbacks.
    const strips=Math.round((w<700?18:30)*Math.max(.7,auroraDetail));
    for(let i=0;i<strips;i++){const t=i/strips,dy=(h-skyHeight)/strips,sy=skyHeight*(1-t)-skyHeight/strips;
      const shift=Math.sin(t*37-sceneTime*.8)*w*(.002+t*.009)*(1+bass*.35);
      ctx.globalAlpha=(1-t)*.36;ctx.drawImage(auroraSurface,0,Math.max(0,sy)*skyPixels/skyHeight,skyWidth,skyPixels/strips,shift,skyHeight+i*dy,w,dy+1);}
    ctx.globalAlpha=1;ctx.strokeStyle=color(1,.13);ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(0,skyHeight);ctx.lineTo(w,skyHeight);ctx.stroke();
    canvas.dataset.waterReflection='true';
    auroraCost+=performance.now()-started;if(++auroraFrames===6){if(auroraCost/auroraFrames>20)auroraDetail=Math.max(.5,auroraDetail*.75);auroraCost=auroraFrames=0;}
  }
  function auroraCurtains(w,h) {
    ctx.globalCompositeOperation='screen';
    for(let layer=0;layer<(w<700?3:4);layer++) {
      const base=h*(.3+layer*.105), amplitude=h*(.05+mids*.05), drift=sceneTime*(.045+layer*.015)*(1+energy*.3);
      const curve=x=>base+Math.sin(x/w*5+drift+layer)*amplitude+Math.sin(x/w*11-drift*.7+layer)*h*.025;
      const height=x=>h*(.2+.07*Math.sin(x/w*5+layer)+bass*.08);
      const beam=ctx.createLinearGradient(0,base-h*.4,0,base+h*.16);
      beam.addColorStop(0,color(layer,0));beam.addColorStop(.55,color(layer,.1+energy*.25));beam.addColorStop(.82,color(layer,.16+energy*.22));beam.addColorStop(1,color(layer,0));
      ctx.fillStyle=beam;ctx.beginPath();
      for(let i=0;i<=60;i++){const x=w*i/60,y=curve(x);if(i)ctx.lineTo(x,y);else ctx.moveTo(x,y);}
      for(let i=60;i>=0;i--){const x=w*i/60;ctx.lineTo(x,curve(x)-height(x));}
      ctx.closePath();ctx.fill();
      for(let ribbon=0;ribbon<5;ribbon++) {
        const points=[];
        for(let i=0;i<=60;i++){const x=w*i/60;points.push([x,curve(x)+ribbon*h*.005]);}
        line(points,color(layer,(.28+energy*.35)/(1+ribbon)),Math.max(1,w/850));
      }
    }
    ctx.globalCompositeOperation='source-over';
  }
  function ethereal(w,h) {
    ctx.globalCompositeOperation='screen';
    const originX=w*(.5+Math.sin(phase*.055)*.12);
    for(let ray=0;ray<9;ray++) {
      const x=w*(ray/8), spread=w*(.04+treble*.05);
      const gradient=ctx.createLinearGradient(originX,-h*.12,x,h*.92);
      gradient.addColorStop(0,color(ray,.04+treble*.1));gradient.addColorStop(.45,color(ray,.025+energy*.04));gradient.addColorStop(1,color(ray,0));
      ctx.fillStyle=gradient;ctx.beginPath();ctx.moveTo(originX,-h*.15);ctx.lineTo(x-spread,h);ctx.lineTo(x+spread,h);ctx.closePath();ctx.fill();
    }
    for(let cloud=0;cloud<4;cloud++) {
      for(let strand=0;strand<10;strand++) {
        const points=[];
        for(let i=0;i<=90;i++) {
          const t=i/90,x=w*t,envelope=Math.sin(t*Math.PI);
          const y=h*(.33+cloud*.13)+Math.sin(t*7+phase*.12+cloud*.9)*h*.07+
            Math.sin(t*13-phase*.09+strand*.09)*envelope*h*(.025+mids*.06)+
            Math.cos(strand/9*Math.PI)*h*.055*envelope;
          points.push([x,y]);
        }
        line(points,color(cloud,.055+energy*.09+Math.sin(strand/9*Math.PI)*.055),Math.max(.7,w/1500));
      }
    }
    ctx.globalCompositeOperation='source-over';
  }
  function sphere(x,y,r,tint) {
    const gradient=ctx.createRadialGradient(x-r*.4,y-r*.4,r*.02,x+r*.3,y+r*.2,r*1.4);
    gradient.addColorStop(0,'#e3eaff');gradient.addColorStop(.2,tint);gradient.addColorStop(.75,tint);gradient.addColorStop(1,'#050b20');
    ctx.fillStyle=gradient;ctx.beginPath();ctx.arc(x,y,r,0,Math.PI*2);ctx.fill();
  }
  function space(w,h,unit) {
    const cx=w*.5,cy=h*.51,earth=unit*.105,reach=Math.hypot(w,h)*.53;
    ctx.fillStyle='#c8ddff';
    for(const star of stars){ctx.globalAlpha=.2+star.size*.2;ctx.beginPath();ctx.arc(star.x*w,star.y*h,star.size*unit/650,0,Math.PI*2);ctx.fill();}
    ctx.globalAlpha=1;
    // Expanding fronts share the same travel coordinate used for planet illumination.
    const fronts=[];
    for(let n=0;n<6;n++) {
      const travel=(phase*.09+n/6)%1,radius=earth+travel*reach;
      fronts.push(radius);
      ctx.strokeStyle=color(n,(1-travel)*energy*.7);ctx.lineWidth=Math.max(1,unit*(.001+ bass*.004));
      ctx.beginPath();ctx.ellipse(cx,cy,radius,radius*(.62+mids*.12),-.16,0,Math.PI*2);ctx.stroke();
      ctx.strokeStyle=color(n+1,(1-travel)*treble*.25);ctx.lineWidth=1;
      ctx.beginPath();ctx.ellipse(cx,cy,radius+unit*.008,radius*(.62+mids*.12)+unit*.008,-.16,0,Math.PI*2);ctx.stroke();
    }
    for(const planet of worlds) {
      const angle=planet.offset+phase*planet.speed;
      const x=cx+Math.cos(angle)*w*planet.orbit,y=cy+Math.sin(angle)*h*planet.orbit*.78;
      const radius=unit*planet.size,dx=x-cx,dy=y-cy;
      const waveX=dx*Math.cos(.16)-dy*Math.sin(.16),waveY=dx*Math.sin(.16)+dy*Math.cos(.16);
      const distance=Math.hypot(waveX,waveY/(.62+mids*.12));
      const hit=Math.max(...fronts.map(front=>Math.max(0,1-Math.abs(front-distance)/(unit*.065))))*energy;
      if(hit>.005){const glow=ctx.createRadialGradient(x,y,radius,x,y,radius*3);glow.addColorStop(0,color(1,hit*.8));glow.addColorStop(1,color(1,0));ctx.fillStyle=glow;ctx.fillRect(x-radius*3,y-radius*3,radius*6,radius*6);}
      sphere(x,y,radius,planet.tint);
      if(planet.kind==='jupiter') {
        ctx.save();ctx.beginPath();ctx.arc(x,y,radius,0,Math.PI*2);ctx.clip();
        for(let stripe=-2;stripe<=2;stripe++){ctx.strokeStyle=stripe%2?'#b3796255':'#f5e4bf77';ctx.lineWidth=radius*.18;ctx.beginPath();ctx.ellipse(x,y+stripe*radius*.3,radius*1.2,radius*.15,.15,0,Math.PI*2);ctx.stroke();}
        ctx.restore();
      }
      if(planet.kind==='saturn'){ctx.strokeStyle='#dbc6a480';ctx.lineWidth=radius*.27;ctx.beginPath();ctx.ellipse(x,y,radius*1.85,radius*.5,-.4,0,Math.PI*2);ctx.stroke();}
    }
    const halo=ctx.createRadialGradient(cx,cy,earth*.9,cx,cy,earth*1.8);
    halo.addColorStop(0,'#66d8ff77');halo.addColorStop(.3,color(1,.12+bass*.25));halo.addColorStop(1,'#2565ab00');
    ctx.fillStyle=halo;ctx.fillRect(cx-earth*1.8,cy-earth*1.8,earth*3.6,earth*3.6);
    sphere(cx,cy,earth,'#247dbb');
    ctx.save();ctx.beginPath();ctx.arc(cx,cy,earth,0,Math.PI*2);ctx.clip();
    ctx.fillStyle='#7dc4ad';
    for(const land of continents){ctx.beginPath();land.forEach(([x,y],i)=>i?ctx.lineTo(cx+x*earth,cy+y*earth):ctx.moveTo(cx+x*earth,cy+y*earth));ctx.closePath();ctx.fill();}
    for(let cloud=0;cloud<4;cloud++){const y=cy+(cloud-1.5)*earth*.43;ctx.strokeStyle='#efffff55';ctx.lineWidth=earth*.045;ctx.beginPath();ctx.ellipse(cx+Math.sin(phase*.05+cloud)*earth*.2,y,earth*.85,earth*.1,-.2,0,Math.PI*1.6);ctx.stroke();}
    const shade=ctx.createLinearGradient(cx-earth,cy-earth,cx+earth,cy+earth);shade.addColorStop(0,'#ffffff20');shade.addColorStop(.5,'#00000000');shade.addColorStop(1,'#020719cc');ctx.fillStyle=shade;ctx.fillRect(cx-earth,cy-earth,earth*2,earth*2);ctx.restore();
  }

  function draw(dt = 1 / 60) {
    sample(dt);
    if (measured && energy > .001) {sceneTime += sceneElapsed;fractalTime += sceneElapsed*(beat.bpm?beat.bpm/96:1);}
    const w = canvas.width, h = canvas.height, cx = w / 2, cy = h / 2, unit = Math.min(w, h);
    ctx.clearRect(0, 0, w, h); ctx.fillStyle = '#070914'; ctx.fillRect(0, 0, w, h);
    const glow = ctx.createRadialGradient(cx, cy, 0, cx, cy, Math.max(w, h) * .65);
    glow.addColorStop(0, color(1, .16 + energy * .18, 35)); glow.addColorStop(.5, color(2, .09, 22)); glow.addColorStop(1, '#070914');
    ctx.fillStyle = glow; ctx.fillRect(0, 0, w, h);
    ctx.lineCap = 'round'; ctx.lineJoin = 'round';
    canvas.dataset.mode = select.value;
    const rendered = scenes?.render(select.value, {w,h,unit,time:sceneTime,elapsed:sceneElapsed,bass,mids,treble,energy,measured,
      fractalTime,beatPulse:beat.pulse,mobile:stage.clientWidth<700, color, hues:palettes[palette.value], earth:()=>space(w,h,unit)});
    if (rendered) { /* Rich scenes use the same canvas and borrowed audio measurements. */
    } else if (select.value === 'aurora') {aurora(w,h);
    } else if (select.value === 'ethereal') {ethereal(w,h);
    } else if (select.value === 'space') {space(w,h,unit);
    } else if (select.value === 'spectrum') {
      const gap = w * .82 / 64, floor = h * .77;
      for (let i = 0; i < 64; i++) {
        const x = w * .09 + i * gap, height = Math.max(2, bars[i] * h * .57), hue = palettes[palette.value][Math.min(2,Math.floor(i/22))] + (i%22)*.7;
        const gradient = ctx.createLinearGradient(0, floor, 0, floor - height);
        gradient.addColorStop(0, `hsla(${hue},95%,45%,.45)`); gradient.addColorStop(1, `hsl(${hue + 40},100%,75%)`);
        ctx.fillStyle = gradient; ctx.fillRect(x, floor - height, gap * .62, height);
        ctx.fillStyle = color(0, .12); ctx.fillRect(x, floor + 8, gap * .62, height * .18);
        ctx.fillStyle = `hsla(${hue + 40},100%,85%,.8)`; ctx.fillRect(x, floor - peaks[i] * h * .57 - 5, gap * .62, 2);
      }
    } else if (select.value === 'waveform') {
      for (let layer = 3; layer >= 0; layer--) {
        const points = [];
        for (let i = 0; i < 512; i++) {
          const x = i * w / 511, envelope = Math.sin(i / 511 * Math.PI);
          const wave = (waveform[i * 2] - 128) / 128;
          points.push([x, cy + wave * h * (.27 + layer * .035) + Math.sin(i * .018 + phase + layer * .8) * envelope * mids * h * .12]);
        }
        line(points, color(layer, layer === 0 ? .95 : .3), (layer === 0 ? 2 : 6 + layer * 3) * w / 1200);
      }
    } else if (select.value === 'fractal') {
      ctx.save(); ctx.translate(cx, cy); ctx.rotate(phase * .045);
      const branch = (length, depth, seed) => {
        if (!depth) return;
        const spread = .4 + bass * .6 + Math.sin(phase * .4 + seed) * .13;
        line([[0, 0], [0, -length]], color(depth + seed, .25 + depth * .1), Math.max(1, depth * unit / 1100));
        ctx.translate(0, -length);
        for (const direction of [-1, 1]) {ctx.save(); ctx.rotate(direction * spread); branch(length * .65, depth - 1, seed); ctx.restore();}
      };
      for (let ray = 0; ray < 8; ray++) {ctx.save(); ctx.rotate(ray * Math.PI / 4); ctx.translate(0, -unit * .035); branch(unit * (.12 + energy * .05), 6, ray); ctx.restore();}
      ctx.restore();
    } else if (select.value === 'particles') {
      ctx.globalCompositeOperation = 'lighter';
      for (let i = 0; i < particles.length; i++) {
        const p = particles[i], angle = p.angle + phase * (.08 + p.size * .008), radius = ((p.radius + phase * .025) % 1) * unit * (.68 + bass * .16);
        const x = cx + Math.cos(angle) * radius * (w / h > 1.4 ? 1.35 : 1), y = cy + Math.sin(angle) * radius;
        const size = p.size * unit / 650 * (1 + treble * 2), alpha = .2 + .7 * (1 - radius / (unit * .9));
        line([[x - Math.cos(angle) * (6 + energy * 65), y - Math.sin(angle) * (6 + energy * 65)], [x, y]], color(i, alpha * .35), size);
        ctx.fillStyle = color(i, alpha); ctx.beginPath(); ctx.arc(x, y, Math.max(.6, size), 0, Math.PI * 2); ctx.fill();
      }
      ctx.globalCompositeOperation = 'source-over';
    } else {
      for (let ring = 10; ring >= 0; ring--) {
        const points = [], radius = unit * (.065 + ring * .036 + bass * .05);
        for (let i = 0; i <= 6; i++) {
          const a = i * Math.PI / 3 + phase * .075 * (ring % 2 ? 1 : -1) + ring * .13;
          points.push([cx + Math.cos(a) * radius, cy + Math.sin(a) * radius]);
        }
        ctx.fillStyle = color(ring, .025); ctx.beginPath(); points.forEach(([x, y], i) => i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)); ctx.fill();
        line(points, color(ring, .3 + mids * .5), Math.max(1, unit / 550));
      }
    }
  }
  function tick(now) {
    raf = 0; if (!moving()) return;
    try {
      if (now - last < 1000 / 30) {raf = requestAnimationFrame(tick);return;}
      const elapsed = Math.min((now - last) / 1000 || 1 / 30, 2);
      const dt = Math.min(elapsed, .1); last = now;
      // No fabricated audio reactivity when capture is unavailable.
      if (measured && energy > .001) phase += dt * (.3 + energy * .8);
      observeAudio(); sceneElapsed=elapsed; draw(dt); sceneElapsed=0; raf = requestAnimationFrame(tick);
    } catch {sceneElapsed=0;fail();}
  }
  function update() {
    if (!active() || !ctx) return;
    try {
      observeAudio(); draw();
      if (moving() && !raf) {last = performance.now(); raf = requestAnimationFrame(tick);}
      else if (!moving()) {cancelAnimationFrame(raf); raf = 0;}
    } catch {fail();}
  }
  function size() {
    if (!active()) return;
    try {
      const bounds = canvas.getBoundingClientRect();
      const budget = bounds.width < 700 ? 600000 : 1000000;
      const ratio = Math.min(devicePixelRatio || 1, 1.25, Math.sqrt(budget / Math.max(1, bounds.width * bounds.height)));
      canvas.width = Math.max(1, Math.round(bounds.width * ratio)); canvas.height = Math.max(1, Math.round(bounds.height * ratio));
      update();
    } catch {fail();}
  }
  $('visualizer-open').addEventListener('click', () => {
    if (dialog.open) return;
    failed = false; canvas.hidden = false; dialog.showModal();
    window.FreoAudioAnalysis?.activate($('station-audio'));
    try {ctx = canvas.getContext('2d'); if (!ctx) throw new Error('No canvas');
      scenes ||= window.FreoVisualScenes?.create(canvas,ctx,scope); size();} catch {fail();}
  });
  const exitFullscreen = () => {
    if (document.fullscreenElement === stage) return document.exitFullscreen().catch(() => {});
    return Promise.resolve();
  };
  $('visualizer-close').addEventListener('click', async () => {await exitFullscreen(); dialog.close();});
  dialog.addEventListener('close', () => {cancelAnimationFrame(raf); raf = 0; detach(); exitFullscreen(); if (!disposed) $('visualizer-open')?.focus();});
  fullscreen.hidden = !document.fullscreenEnabled || !stage.requestFullscreen;
  fullscreen.addEventListener('click', async () => {
    try {if (document.fullscreenElement === stage) await document.exitFullscreen(); else await stage.requestFullscreen();}
    catch {fullscreenNoticeUntil = performance.now() + 5000; status.textContent = 'Fullscreen is unavailable. You can keep watching here.';}
  });
  scope.listen(document, 'fullscreenchange', () => {fullscreen.textContent = document.fullscreenElement === stage ? 'Exit fullscreen' : 'Fullscreen'; size();});
  for (const control of [select, palette]) control.addEventListener('change', () => {
    if (control === select) {sceneTime=0;fractalTime=0;sceneElapsed=0;}
    if(active())window.FreoAudioAnalysis?.activate($('station-audio'));
    try {localStorage.setItem(key, select.value); localStorage.setItem(key + '-palette', palette.value);} catch {}
    update();
  });
  retry?.addEventListener('click',()=>{waitingSince=0;window.FreoAudioAnalysis?.activate($('station-audio'));update();});
  scope.listen(window,'pageshow',activity);
  const observer = new MutationObserver(activity); observer.observe(root, {attributes: true, attributeFilter: ['class']});
  scope.listen(document, 'playing', update, true); scope.listen(document, 'pause', update, true);
  function activity() {
    cancelAnimationFrame(raf);raf=0;
    if(active())window.FreoAudioAnalysis?.activate($('station-audio'));
    else detach();
    update();
  }
  scope.listen(document, 'visibilitychange', activity);
  scope.listen(document, 'freo:analysis', update);
  const resize = new ResizeObserver(size); resize.observe(stage);
  scope.cleanup(() => {disposed = true; cancelAnimationFrame(raf); observer.disconnect(); resize.disconnect(); detach(); exitFullscreen(); if (dialog.open) dialog.close();});
})();
