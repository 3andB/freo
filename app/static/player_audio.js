/* Playback owns audible output. Presentation only borrows the analyser. */
(() => {
  const scope = window.FreoPage;
  if (!scope || !document.querySelector('.radio-experience')) return;
  let graph = null, enabled = false;
  const changed = () => document.dispatchEvent(new Event('freo:analysis'));
  const captureSupported = audio => !!(audio.captureStream || audio.mozCaptureStream);
  function clearAnalysis(g) {
    if (!g) return;
    g.capture?.removeEventListener('addtrack', g.attach);
    try { g.captureSource?.disconnect(); } catch {}
    try { g.capture?.getTracks().forEach(track => track.stop()); } catch {}
    try { if (g.analyser && g.source) g.source.disconnect(g.analyser); } catch {}
    try { g.analyser?.disconnect(); g.sink?.disconnect(); } catch {}
    g.capture = g.captureSource = g.analyser = g.sink = null;
  }
  function release() {
    const previous = graph;
    graph = null;
    if (!previous) return;
    previous.events.abort();
    clearAnalysis(previous);
    // The player has already retired this element; never pause it here.
    try { previous.source?.disconnect(); previous.gain?.disconnect(); } catch {}
    try { previous.context?.close().catch(() => {}); } catch {}
  }
  function error(g, reason) {
    if (graph !== g) return;
    clearAnalysis(g);
    g.error = reason?.name || reason || 'AnalysisError';
    changed();
  }
  function setVolume(audio, level, muted) {
    const g = graph;
    if (g?.audio !== audio) return false;
    if (level !== undefined) g.level = level;
    if (muted !== undefined) g.muted = muted;
    if (!g.source) return false;
    g.gain.gain.setTargetAtTime(g.muted ? 0 : g.level, g.context.currentTime, .015);
    return true;
  }
  function analyse(g) {
    if (graph !== g || !enabled || g.error || g.analyser || g.audio.paused) return;
    try {
      const input = g.source || g.captureSource;
      if (!input) return;
      const analyser = g.context.createAnalyser();
      analyser.fftSize = 1024; analyser.smoothingTimeConstant = .72;
      g.analyser = analyser;
      if(!g.capturing){
        // A silent, pulled analysis branch; audible output remains source -> gain.
        g.sink=g.context.createGain();g.sink.gain.value=0;
        analyser.connect(g.sink);g.sink.connect(g.context.destination);
      }
      input.connect(analyser);
      changed();
    } catch (reason) { error(g, reason); }
  }
  function connect(g) {
    if (graph !== g || (g.error && (g.capturing || !g.source)) || scope.signal.aborted || g.context?.state !== 'running') return;
    if (g.capturing) {
      if (!enabled || g.audio.paused) return;
      try {
        if (!g.capture) {
          g.capture = (g.audio.captureStream || g.audio.mozCaptureStream).call(g.audio);
          g.attach = () => {
            if (graph !== g || !enabled || g.captureSource || !g.capture?.getAudioTracks().length) return;
            try { g.captureSource = g.context.createMediaStreamSource(g.capture); analyse(g); }
            catch (reason) { error(g, reason); }
          };
          g.capture.addEventListener('addtrack', g.attach);
        }
        g.attach();
      } catch (reason) { error(g, reason); }
    } else {
      if (!g.source) {
        if (g.audio.paused) return;
        try {
          // Prepare the output before taking ownership. Analysis is never in series.
          const gain = g.context.createGain(); gain.gain.value = g.muted ? 0 : g.level;
          gain.connect(g.context.destination); g.gain = gain;
          g.source = g.context.createMediaElementSource(g.audio);
          g.source.connect(gain);
          g.audio.volume = 1; g.audio.muted = false;
        } catch (reason) { error(g, reason); return; }
      }
      analyse(g);
    }
  }
  function resume(g, gesture=false) {
    if (graph !== g || !g.context || (g.error && !g.source)) return;
    if (g.context.state === 'running' && !gesture) {connect(g);return;}
    // Safari can leave a resume promise pending through an interruption. A fresh
    // gesture must be able to retry without waiting for that promise forever.
    if(g.resuming && !gesture)return;
    const attempt=++g.resumeAttempt;g.resuming=true;
    try {
      g.context.resume().then(() => {if(graph===g && attempt===g.resumeAttempt){g.resuming=false;connect(g);changed();}})
        .catch(reason => {if(graph===g && attempt===g.resumeAttempt){g.resuming=false;error(g,reason);}});
    } catch(reason){g.resuming=false;error(g,reason);}
  }
  function unlock(g) {
    if(g.capturing || !g.context || g.unlocked || !navigator.userActivation?.isActive)return;
    // Prime iOS's audio unit inside the same gesture, before asynchronous media
    // readiness. A single silent sample has no stream or audible output.
    try {
      const node=g.context.createBufferSource();node.buffer=g.context.createBuffer(1,1,g.context.sampleRate);
      const gain=g.context.createGain();gain.gain.value=0;node.connect(gain);gain.connect(g.context.destination);
      node.onended=()=>{node.disconnect();gain.disconnect();};node.start();g.unlocked=true;
    }catch{}
  }
  function prepare(audio, level, muted, gesture=false) {
    if (!audio) return;
    if (graph?.audio !== audio) {
      release();
      const capturing = captureSupported(audio);
      const g = graph = {audio, capturing, level:level ?? audio.volume, muted:muted ?? audio.muted, context:null, source:null, gain:null, analyser:null,
        capture:null, captureSource:null, error:null, resuming:false, resumeAttempt:0, unlocked:false, events:new AbortController()};
      // Our public /listen route redirects to the same-origin /stream proxy.
      // Never reroute an unknown external resource through a media-element source.
      const url = new URL(audio.getAttribute('src') || audio.dataset.stream || '', location.href);
      g.safe = url.origin === location.origin && /^\/(listen|stream)\//.test(url.pathname);
      const listen = (name, fn) => audio.addEventListener(name, fn, {signal:g.events.signal});
      listen('playing', () => { resume(g); connect(g); changed(); });
      listen('loadstart', () => { clearAnalysis(g); g.error = null; g.resuming=false; ++g.resumeAttempt; });
      listen('pause', () => { clearAnalysis(g); changed(); });
      listen('emptied', () => { clearAnalysis(g); changed(); });
    }
    const g = graph;
    setVolume(audio, level, muted);
    if (!g.context && !g.error && (g.capturing ? enabled : g.safe)) {
      try {
        try { if (!g.capturing && navigator.audioSession) navigator.audioSession.type = 'playback'; } catch {}
        // Called synchronously from Play / visualizer-open, even before media is ready.
        g.context = new (window.AudioContext || window.webkitAudioContext)();
        g.context.addEventListener('statechange', () => { if (graph === g) { if(g.context.state==='running')g.resuming=false;connect(g); changed(); } });
      } catch (reason) { error(g, reason); }
    }
    unlock(g);resume(g,gesture);
  }
  function activate(audio) {
    enabled = true;
    // An explicit user gesture can retry an analysis failure.
    if (graph?.audio === audio && graph.error) {
      graph.error = null;
      if (graph.context?.state === 'closed') graph.context = null;
    }
    prepare(audio,undefined,undefined,true);
  }
  function deactivate() {
    enabled = false;
    clearAnalysis(graph);
    // The capture context has no audible output and can be disposed independently.
    if (graph?.capturing) release();
  }
  const api = {prepare, activate, deactivate, setVolume, read(audio) {return graph?.audio === audio ? graph : null;},
    fail(reason) {if (graph) error(graph, reason);}};
  window.FreoAudioAnalysis = api;
  scope.listen(document, 'visibilitychange', () => {
    if (!document.hidden && graph && !graph.audio.paused) resume(graph);
  });
  scope.listen(window,'pageshow',()=>{if(graph && !graph.audio.paused)resume(graph);});
  scope.cleanup(() => {release(); if (window.FreoAudioAnalysis === api) delete window.FreoAudioAnalysis;});
})();
