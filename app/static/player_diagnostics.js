/* Retained for future device debugging: player.html loads this only with
 * ?audio_debug=1. Open Audio report to inspect/copy local observations. */
/* Opt-in, local-only audio observations. Never connects, resumes or reloads audio. */
(() => {
  const scope = window.FreoPage, $ = id => document.getElementById(id);
  const panel = $('audio-diagnostics'), dialog = $('visualizer-dialog');
  if (!scope || !panel || !dialog) return;
  const output = $('audio-diagnostics-report'), message = $('audio-diagnostics-status');
  const build = 'v1-iphone-stream-1', started = performance.now();
  let enabled = new URLSearchParams(location.search).get('audio_debug') === '1';
  const enabledFromLoad = enabled;
  let nextId = 0, previous = null, sourceCheck = null;
  const ids = new WeakMap(), loads = new WeakMap(), contexts = new WeakSet();
  const events = [], samples = [];
  const elapsed = () => Math.round(performance.now() - started);
  const id = object => {
    if (!object) return null;
    if (!ids.has(object)) ids.set(object, ++nextId);
    return ids.get(object);
  };
  const bounded = (list, value, limit) => {list.push(value); if (list.length > limit) list.shift();};
  const event = (type, detail = {}) => {
    if (enabled) bounded(events, {ms: elapsed(), type, ...detail}, 60);
  };
  const url = value => {
    if (!value) return null;
    try {const parsed = new URL(value, location.href); return parsed.origin + parsed.pathname;} catch {return null;}
  };
  const number = value => Number.isFinite(value) ? Math.round(value * 1000000) / 1000000 : null;
  function snapshot() {
    const audio = $('station-audio'), graph = window.FreoAudioAnalysis?.read(audio);
    const context = graph?.context, analyser = graph?.analyser;
    if (enabled && context && !contexts.has(context)) {
      contexts.add(context);
      scope.listen(context, 'statechange', () => event('context-state', {context: id(context), state: context.state}));
    }
    let frequencyPeak = null, rms = null, waveformPeak = null, readError = null;
    if (analyser && context?.state === 'running' && audio && !audio.paused) {
      try {
        const frequencies = new Uint8Array(analyser.frequencyBinCount);
        const waveform = new Float32Array(analyser.fftSize);
        analyser.getByteFrequencyData(frequencies);
        analyser.getFloatTimeDomainData(waveform);
        frequencyPeak = frequencies.reduce((peak, value) => Math.max(peak, value), 0);
        waveformPeak = waveform.reduce((peak, value) => Math.max(peak, Math.abs(value)), 0);
        rms = Math.sqrt(waveform.reduce((sum, value) => sum + value * value, 0) / waveform.length);
      } catch (error) {readError = error.name + ': ' + error.message;}
    }
    const sample = {
      ms: elapsed(), audio: id(audio), context: id(context), source: id(graph?.fallback?.active ? graph.fallback.input : graph?.source || graph?.captureSource), nativeSource: id(graph?.source), analyser: id(analyser),
      mediaTime: number(audio?.currentTime), contextTime: number(context?.currentTime), contextState: context?.state || 'unavailable',
      paused: audio?.paused ?? null, readyState: audio?.readyState ?? null,
      frequencyPeak, waveformPeak: number(waveformPeak), rms: number(rms), readError,
      signal: readError ? 'read-error' : rms === null ? 'unavailable' : frequencyPeak > 0 || rms > .00001 ? 'present' : 'silent',
      visualSignal: $('player-visual')?.dataset.signal || null,
      sourceMatchesElement: graph?.source && !graph.fallback?.active ? graph.source.mediaElement === audio : null,
      sourceContextMatches: graph?.source || graph?.captureSource ? (graph.source || graph.captureSource).context === context : null,
      analyserContextMatches: analyser ? analyser.context === context : null,
      graphError: graph?.error || null
    };
    if (previous && sample.audio === previous.audio) sample.mediaTimeDelta = number(sample.mediaTime - previous.mediaTime);
    if (previous && sample.context && sample.context === previous.context) sample.contextTimeDelta = number(sample.contextTime - previous.contextTime);
    previous = sample;
    return {sample, audio, graph};
  }
  function collect() {
    if (!enabled || document.hidden) return;
    try {bounded(samples, snapshot().sample, 40);} catch (error) {event('diagnostic-error', {name: error.name});}
  }
  function report() {
    const {sample, audio, graph} = snapshot();
    let assessment = 'Press Play and open the visualizer, then wait ten seconds and refresh this report.';
    if (sample.signal === 'present') assessment = 'The analyser is receiving nonzero station samples.';
    else if (audio && !audio.paused) {
      if (sample.graphError || sample.readError) assessment = 'Analysis reported an error; see the details below.';
      else if (sample.contextState !== 'running') assessment = 'The audio context is not running. Tap Enable visuals, wait ten seconds, then copy another report.';
      else if (!sample.analyser || !sample.source) assessment = 'The context is running, but the analysis source or analyser is missing.';
      else assessment = 'The graph is running but this sample is silent. If you hear music, copy this report; silence alone does not establish the cause.';
    }
    message.textContent = assessment;
    const data = {
      reportVersion: 4, build, enabledFromLoad, sourceCheck, heardMusic: $('audio-diagnostics-audible').value, capturedAt: new Date().toISOString(), page: url(location.href),
      userAgent: navigator.userAgent, platform: navigator.platform, secureContext: isSecureContext,
      visibility: document.visibilityState, standalone: !!navigator.standalone,
      userActivation: navigator.userActivation ? {active: navigator.userActivation.isActive, hasBeenActive: navigator.userActivation.hasBeenActive} : null,
      audioSessionType: navigator.audioSession?.type || null, assessment,
      media: audio ? {
        requestMode: audio.dataset.requestMode || 'default', src: url(audio.getAttribute('src')), currentSrc: url(audio.currentSrc), crossOrigin: audio.crossOrigin,
        lastLoad: loads.get(audio) || null, readyState: audio.readyState, networkState: audio.networkState,
        paused: audio.paused, ended: audio.ended, muted: audio.muted, volume: audio.volume,
        error: audio.error ? {code: audio.error.code, message: audio.error.message} : null,
        captureStreamAvailable: typeof audio.captureStream === 'function' || typeof audio.mozCaptureStream === 'function'
      } : null,
      graph: graph ? {
        safe: graph.safe, route: graph.fallback?.active ? 'stream-decoder' : graph.capturing ? 'capture-stream' : 'media-element-source',
        fallback: graph.fallback?.diagnostics() || null,
        resuming: graph.resuming, resumeAttempt: graph.resumeAttempt, unlocked: graph.unlocked,
        sampleRate: graph.context?.sampleRate || null, fftSize: graph.analyser?.fftSize || null,
        outputGain: graph.gain?.gain.value ?? null, analysisSinkGain: graph.sink?.gain.value ?? null,
        captureTracks: graph.capture?.getAudioTracks().map(track => ({readyState: track.readyState, enabled: track.enabled, muted: track.muted})) || []
      } : null,
      current: sample, samples: [...samples], events: [...events]
    };
    output.value = JSON.stringify(data, null, 2);
    return output.value;
  }
  function refresh() {
    try {return report();} catch (error) {
      message.textContent = 'Report unavailable: ' + error.name + '. Playback is unaffected.';
      return null;
    }
  }
  scope.listen(document, 'freo:source-check', e => {sourceCheck = e.detail; event('source-check', {status: sourceCheck.status}); collect(); if (!panel.hidden) refresh();});
  const comparison = new URL(location.href);
  const usingCors = new URLSearchParams(location.search).get('audio_debug') === '1' && new URLSearchParams(location.search).get('audio_cors') === '1';
  comparison.search = ''; comparison.hash = ''; comparison.searchParams.set('audio_debug', '1');
  if (!usingCors) comparison.searchParams.set('audio_cors', '1');
  $('audio-cors-comparison').href = comparison.href;
  $('audio-cors-comparison').textContent = usingCors ? 'Reload with default stream request' : 'Reload with CORS before stream loading';
  scope.listen($('audio-diagnostics-open'), 'click', () => {
    enabled = true; panel.hidden = false; event('report-open'); collect(); refresh();
    $('audio-diagnostics-close').focus();
  });
  scope.listen($('audio-diagnostics-close'), 'click', () => {panel.hidden = true; $('audio-diagnostics-open').focus();});
  scope.listen($('audio-diagnostics-refresh'), 'click', refresh);
  scope.listen($('audio-diagnostics-audible'), 'change', refresh);
  scope.listen($('audio-diagnostics-copy'), 'click', async () => {
    const text = refresh(); if (!text) return;
    try {await navigator.clipboard.writeText(text); message.textContent = 'Report copied. Paste it into the support conversation.';}
    catch {output.focus(); output.select(); output.setSelectionRange(0, output.value.length); message.textContent = 'Touch and hold the selected report, then choose Copy.';}
  });
  scope.listen(dialog, 'close', () => {panel.hidden = true;});
  scope.listen(document, 'click', e => {
    const control = e.target.closest?.('#play-button, #visualizer-open, #visualizer-retry, #visualizer-close');
    if (control) {event(control.id, {gesture: navigator.userActivation?.isActive ?? null}); collect();}
  }, true);
  scope.listen($('visual-mode'), 'change', () => event('visual-mode', {value: $('visual-mode').value}));
  for (const name of ['loadstart', 'loadedmetadata', 'canplay', 'playing', 'pause', 'waiting', 'stalled', 'emptied', 'ended', 'error']) {
    scope.listen(document, name, e => {
      if (e.target.id !== 'station-audio') return;
      const audio = e.target;
      if (name === 'loadstart') loads.set(audio, {ms: elapsed(), src: url(audio.getAttribute('src')), crossOrigin: audio.crossOrigin});
      event('media-' + name, {audio: id(audio), readyState: audio.readyState, mediaTime: number(audio.currentTime), errorCode: audio.error?.code || null});
    }, true);
  }
  scope.listen(document, 'freo:analysis', () => {event('analysis-change'); collect();});
  scope.listen(document, 'visibilitychange', () => event('visibility', {state: document.visibilityState}));
  scope.listen(window, 'pageshow', e => event('pageshow', {persisted: e.persisted}));
  scope.listen(window, 'error', e => event('script-error', {message: (e.message || '').slice(0, 300), file: url(e.filename), line: e.lineno}));
  scope.listen(window, 'unhandledrejection', e => event('unhandled-rejection', {name: e.reason?.name || 'Unknown', message: String(e.reason?.message || '').slice(0, 300)}));
  scope.interval(() => {if (dialog.open) collect();}, 500);
  // With the debug link, preserve initial state before the first Play gesture.
  collect();
})();
