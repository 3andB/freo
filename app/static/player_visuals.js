/* Optional, read-only presentation. Native stream playback owns its audio path. */
(() => {
  const root = document.querySelector('.radio-experience'), scope = window.FreoPage;
  const $ = id => document.getElementById(id), dialog = $('visualizer-dialog');
  if (!root || !scope || !dialog) return;
  const canvas = $('player-visual'), stage = dialog.querySelector('.visualizer-stage');
  const select = $('visual-mode'), palette = $('visual-palette'), status = $('visual-status');
  const fullscreen = $('visualizer-fullscreen'), reduced = matchMedia('(prefers-reduced-motion: reduce)');
  const key = 'freo-visual-' + root.dataset.station;
  const modes = ['fractal', 'spectrum', 'waveform', 'particles', 'ambient'];
  const palettes = {aurora: [155, 205, 285], sunset: [18, 335, 275], electric: [190, 260, 320]};
  try {
    const saved = localStorage.getItem(key); if (modes.includes(saved)) select.value = saved;
    const savedPalette = localStorage.getItem(key + '-palette'); if (Object.hasOwn(palettes, savedPalette)) palette.value = savedPalette;
  } catch {}
  let ctx, audio, captured, context, analyser, source, attachListener;
  let fullscreenNoticeUntil = 0;
  let raf = 0, last = 0, phase = 0, disposed = false, failed = false, generation = 0;
  let bass = 0, mids = 0, treble = 0, energy = 0, measured = false;
  const frequency = new Uint8Array(512), waveform = new Uint8Array(1024);
  const bars = new Float32Array(64), peaks = new Float32Array(64);
  const particles = Array.from({length: 150}, (_, i) => ({angle: i * 2.399963, radius: ((i * 73) % 151) / 151, size: 1 + i % 4}));
  const active = () => dialog.open && !disposed && !failed && !document.hidden;
  const moving = () => active() && !reduced.matches && !root.classList.contains('low-motion') && audio && !audio.paused && root.classList.contains('is-playing');
  const color = (index, alpha = 1, light = 65) => `hsla(${palettes[palette.value][index % 3]},95%,${light}%,${alpha})`;
  function detach() {
    generation++;
    try {captured?.removeEventListener('addtrack', attachListener);} catch {}
    try {source?.disconnect();} catch {}
    // These are capture tracks only; never stop or reset the native audio element.
    try {captured?.getTracks().forEach(track => track.stop());} catch {}
    try {context?.close().catch(() => {});} catch {}
    captured = context = analyser = source = attachListener = null;
    measured = false; bass = mids = treble = energy = 0; bars.fill(0); peaks.fill(0);
  }
  function fail() {
    failed = true; cancelAnimationFrame(raf); raf = 0; detach(); canvas.hidden = true;
    status.textContent = 'Visualization unavailable. Your audio keeps playing.';
  }
  function observeAudio() {
    const next = $('station-audio');
    if (audio !== next) {detach(); audio = next;}
    if (!active() || !audio || audio.paused || captured || !(audio.captureStream || audio.mozCaptureStream)) return;
    try {
      captured = (audio.captureStream || audio.mozCaptureStream).call(audio);
      const token = generation;
      attachListener = () => {
        if (!active() || token !== generation || analyser || !captured?.getAudioTracks().length) return;
        try {
          context = new (window.AudioContext || window.webkitAudioContext)();
          analyser = context.createAnalyser(); analyser.fftSize = 1024; analyser.smoothingTimeConstant = .72;
          source = context.createMediaStreamSource(captured); source.connect(analyser);
          // No context.destination connection: no second playback or audio routing.
          context.resume().catch(() => {if (token === generation) detach();});
        } catch {detach();}
      };
      captured.addEventListener('addtrack', attachListener); attachListener();
    } catch {detach();}
  }
  function sample(dt) {
    measured = !!(analyser && context?.state === 'running' && audio && !audio.paused);
    if (measured) {
      try {analyser.getByteFrequencyData(frequency); analyser.getByteTimeDomainData(waveform);} catch {detach();}
    }
    if (!measured) {frequency.fill(0); waveform.fill(128);}
    const band = (from, to) => {
      let total = 0; for (let i = from; i < to; i++) total += frequency[i];
      return total / ((to - from) * 255);
    };
    const smooth = 1 - Math.exp(-dt * 12);
    bass += (band(1, 7) - bass) * smooth; mids += (band(7, 60) - mids) * smooth;
    treble += (band(60, 220) - treble) * smooth;
    energy = bass * .45 + mids * .4 + treble * .15;
    for (let i = 0; i < bars.length; i++) {
      const from = Math.floor(Math.pow(512, i / 64)), to = Math.max(from + 1, Math.floor(Math.pow(512, (i + 1) / 64)));
      bars[i] += (band(from, Math.min(512, to)) - bars[i]) * smooth;
      peaks[i] = Math.max(bars[i], peaks[i] - dt * .25);
    }
    canvas.dataset.analysis = measured ? 'live' : 'unavailable';
    const notice = measured ? '' : audio && !audio.paused ? 'Audio analysis unavailable · resting visual' : 'Press play on the player to bring this scene to life.';
    if (performance.now() > fullscreenNoticeUntil && status.textContent !== notice) status.textContent = notice;
  }
  function line(points, stroke, width) {
    ctx.beginPath(); points.forEach(([x, y], i) => i ? ctx.lineTo(x, y) : ctx.moveTo(x, y));
    ctx.strokeStyle = stroke; ctx.lineWidth = width; ctx.stroke();
  }
  function draw(dt = 1 / 60) {
    sample(dt);
    const w = canvas.width, h = canvas.height, cx = w / 2, cy = h / 2, unit = Math.min(w, h);
    ctx.clearRect(0, 0, w, h); ctx.fillStyle = '#070914'; ctx.fillRect(0, 0, w, h);
    const glow = ctx.createRadialGradient(cx, cy, 0, cx, cy, Math.max(w, h) * .65);
    glow.addColorStop(0, color(1, .16 + energy * .18, 35)); glow.addColorStop(.5, color(2, .09, 22)); glow.addColorStop(1, '#070914');
    ctx.fillStyle = glow; ctx.fillRect(0, 0, w, h);
    ctx.lineCap = 'round'; ctx.lineJoin = 'round';
    canvas.dataset.mode = select.value;
    if (select.value === 'spectrum') {
      const gap = w * .82 / 64, floor = h * .77;
      for (let i = 0; i < 64; i++) {
        const x = w * .09 + i * gap, height = Math.max(2, bars[i] * h * .57), hue = palettes[palette.value][0] + i * 2.4;
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
      const dt = Math.min((now - last) / 1000 || 1 / 60, .05); last = now;
      // No fabricated audio reactivity when capture is unavailable.
      if (measured) phase += dt * (.6 + energy * 2.5);
      draw(dt); raf = requestAnimationFrame(tick);
    } catch {fail();}
  }
  function update() {
    if (!active()) return;
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
      const ratio = Math.min(devicePixelRatio || 1, 1.5, Math.sqrt(1800000 / Math.max(1, bounds.width * bounds.height)));
      canvas.width = Math.max(1, Math.round(bounds.width * ratio)); canvas.height = Math.max(1, Math.round(bounds.height * ratio));
      update();
    } catch {fail();}
  }
  $('visualizer-open').addEventListener('click', () => {
    if (dialog.open) return;
    failed = false; canvas.hidden = false; dialog.showModal();
    try {ctx = canvas.getContext('2d'); if (!ctx) throw new Error('No canvas'); size();} catch {fail();}
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
    try {localStorage.setItem(key, select.value); localStorage.setItem(key + '-palette', palette.value);} catch {}
    update();
  });
  const observer = new MutationObserver(update); observer.observe(root, {attributes: true, attributeFilter: ['class']});
  scope.listen(document, 'playing', update, true); scope.listen(document, 'pause', update, true);
  scope.listen(document, 'visibilitychange', () => {if (document.hidden) {cancelAnimationFrame(raf); raf = 0;} else update();});
  scope.listen(reduced, 'change', update);
  const resize = new ResizeObserver(size); resize.observe(stage);
  scope.cleanup(() => {disposed = true; cancelAnimationFrame(raf); observer.disconnect(); resize.disconnect(); detach(); exitFullscreen(); if (dialog.open) dialog.close();});
})();
