/* Explicit diagnostic only: a bounded station sample, never a visualizer input. */
(() => {
  const scope = window.FreoPage, $ = id => document.getElementById(id);
  const button = $('audio-source-check'), status = $('audio-source-check-status');
  if (!scope || !button || !status) return;
  let active = null;
  const metrics = values => {
    let peak = 0, sum = 0;
    for (const value of values) {peak = Math.max(peak, Math.abs(value)); sum += value * value;}
    return {peak, rms: values.length ? Math.sqrt(sum / values.length) : 0};
  };
  function nativeSample(graph) {
    const wave = new Float32Array(graph.analyser?.fftSize || 0);
    const frequency = new Uint8Array(graph.analyser?.frequencyBinCount || 0);
    graph.analyser?.getFloatTimeDomainData(wave);
    graph.analyser?.getByteFrequencyData(frequency);
    return {mediaTime: graph.audio.currentTime, contextTime: graph.context.currentTime,
      contextState: graph.context.state, ...metrics(wave), frequencyPeak: frequency.reduce((a, b) => Math.max(a, b), 0)};
  }
  function publish(job, text) {
    if (scope.signal.aborted) return;
    status.textContent = text;
    document.dispatchEvent(new CustomEvent('freo:source-check', {detail: {...job.result}}));
  }
  function disconnect(job) {
    // Remove only the temporary edge; never disconnect the live audible route.
    if (job.liveAttached) {try {job.input.disconnect(job.analyser);} catch {} job.liveAttached = false;}
    try {job.source?.stop();} catch {}
    for (const node of [job.source, job.analyser, job.gain]) {try {node?.disconnect();} catch {}}
    job.source = job.analyser = job.gain = null;
  }
  function cancel() {
    if (!active) return;
    active.cancelled = true; active.controller.abort(); disconnect(active);
  }
  function requireCurrent(job) {
    if (job.cancelled || scope.signal.aborted || document.hidden ||
        $('station-audio') !== job.graph.audio || job.graph.audio.paused || job.graph.audio.currentSrc !== job.src ||
        window.FreoAudioAnalysis?.read(job.graph.audio) !== job.graph || job.graph.analyser !== job.nativeAnalyser ||
        job.graph.context.state !== 'running') throw new Error('Playback changed or check cancelled.');
  }
  async function measure(job) {
    let peak = 0, maxRms = 0;
    const wave = new Float32Array(job.analyser.fftSize);
    for (let i = 0; i < 12; i++) {
      await new Promise(resolve => setTimeout(resolve, 75)); requireCurrent(job);
      job.analyser.getFloatTimeDomainData(wave);
      const sample = metrics(wave); peak = Math.max(peak, sample.peak); maxRms = Math.max(maxRms, sample.rms);
    }
    return {peak, maxRms, contextState: job.graph.context.state};
  }
  async function run() {
    if (active) {cancel(); return;}
    const audio = $('station-audio'), graph = window.FreoAudioAnalysis?.read(audio);
    if (!audio || audio.paused || !graph?.analyser || graph.context?.state !== 'running') {
      status.textContent = 'Play the station and open the visualizer before running this check.'; return;
    }
    const stream = new URL(audio.currentSrc, location.href);
    if (stream.origin !== location.origin || !/^\/(listen|stream)\//.test(stream.pathname)) {
      status.textContent = 'Source check requires this station’s same-origin stream.'; return;
    }
    const job = active = {graph, nativeAnalyser: graph.analyser, src: audio.currentSrc, controller: new AbortController(),
      cancelled: false, result: {status: 'capturing', startedAt: new Date().toISOString(), byteLimit: 196608, captureLimitMs: 6000}};
    button.textContent = 'Cancel source check';
    let reader, captureTimer, decodeTimer;
    try {
      job.result.nativeBefore = nativeSample(graph);
      publish(job, 'Checking a short sample of the station. Your live playback continues.');
      stream.searchParams.set('_freo_probe', String(Date.now()));
      captureTimer = setTimeout(() => {job.result.captureTimedOut = true; job.controller.abort();}, 6000);
      const response = await fetch(stream.href, {signal: job.controller.signal, cache: 'no-store', credentials: 'same-origin', mode: 'same-origin'});
      const finalUrl = new URL(response.url);
      job.result.response = {status: response.status, type: response.type, redirected: response.redirected,
        url: finalUrl.origin + finalUrl.pathname, sameOrigin: finalUrl.origin === location.origin,
        contentType: response.headers.get('content-type'), allowOrigin: response.headers.get('access-control-allow-origin')};
      if (!response.ok || finalUrl.origin !== location.origin || !response.body) throw new Error('Station sample request failed.');
      reader = response.body.getReader();
      const chunks = []; let length = 0;
      try {
        while (length < job.result.byteLimit) {
          requireCurrent(job);
          const {done, value} = await reader.read(); if (done) break;
          const chunk = value.subarray(0, job.result.byteLimit - length); chunks.push(chunk); length += chunk.length;
        }
      } catch (error) {if (!job.result.captureTimedOut || job.cancelled) throw error;}
      clearTimeout(captureTimer); reader.cancel().catch(() => {}); job.controller.abort();
      job.result.bytes = length;
      requireCurrent(job);
      if (length < 4096) throw new Error('Too little station audio was received; try again while music is audible.');
      const bytes = new Uint8Array(length); let offset = 0;
      for (const chunk of chunks) {bytes.set(chunk, offset); offset += chunk.length;}
      job.result.status = 'decoding'; publish(job, 'Decoding the captured station sample…');
      const decoded = await Promise.race([
        graph.context.decodeAudioData(bytes.buffer),
        new Promise((_, reject) => {decodeTimer = setTimeout(() => reject(new Error('Station sample decode timed out.')), 8000);})
      ]);
      clearTimeout(decodeTimer); requireCurrent(job);
      const decodedChannels = [];
      for (let channel = 0; channel < decoded.numberOfChannels; channel++)
        decodedChannels.push(metrics(decoded.getChannelData(channel).subarray(0, Math.min(decoded.length, decoded.sampleRate * 3))));
      job.result.decoded = {duration: decoded.duration, sampleRate: decoded.sampleRate, channels: decodedChannels};
      // Test the live source and decoded station PCM through the SAME fresh,
      // muted analyser. Leave the player's analyser and audible gain untouched.
      job.analyser = graph.context.createAnalyser(); job.analyser.fftSize = 1024;
      job.gain = graph.context.createGain(); job.gain.gain.value = 0;
      job.analyser.connect(job.gain); job.gain.connect(graph.context.destination);
      job.input = graph.source || graph.captureSource;
      job.input.connect(job.analyser); job.liveAttached = true;
      job.result.status = 'checking'; publish(job, 'Checking the live source through a fresh, silent analyser…');
      job.result.nativeTap = await measure(job);
      job.input.disconnect(job.analyser); job.liveAttached = false;
      job.source = graph.context.createBufferSource(); job.source.buffer = decoded;
      job.source.connect(job.analyser);
      publish(job, 'Checking decoded station audio through the same silent analyser…');
      job.source.start(0, 0, Math.min(decoded.duration, 1.5));
      job.result.control = await measure(job);
      disconnect(job);
      job.result.nativeAfter = nativeSample(graph);
      job.result.playbackGraphUnchanged = window.FreoAudioAnalysis?.read(audio) === graph && graph.analyser === job.nativeAnalyser;
      job.result.mediaTimeAdvanced = job.result.nativeAfter.mediaTime > job.result.nativeBefore.mediaTime;
      job.result.status = 'complete';
      const nativeSilent = job.result.nativeBefore.peak === 0 && job.result.nativeAfter.peak === 0 &&
        job.result.nativeBefore.frequencyPeak === 0 && job.result.nativeAfter.frequencyPeak === 0;
      job.result.outcome = job.result.control.peak > .00001
        ? (job.result.nativeTap.peak > .00001 ? (nativeSilent ? 'native-signal-original-analyser-silent' : 'decoded-and-native-signal')
          : nativeSilent ? 'decoded-signal-native-silent' : 'control-inconclusive') : 'control-inconclusive';
      publish(job, job.result.outcome === 'decoded-signal-native-silent'
        ? 'Station audio decodes and reaches Web Audio, but both live-source checks are silent. Copy this report.'
        : job.result.outcome === 'native-signal-original-analyser-silent' ? 'The fresh live-source analyser receives audio; the original analyser is silent. Copy this report.'
        : job.result.outcome === 'decoded-and-native-signal' ? 'Decoded and live station samples both reach Web Audio. Copy this report.'
        : 'The control did not produce detectable samples. Copy this report; this result alone does not identify the cause.');
    } catch (error) {
      job.result.status = job.cancelled ? 'cancelled' : 'error';
      job.result.error = {name: error.name, message: error.message};
      publish(job, job.cancelled ? 'Source check cancelled. Live playback is unaffected.' : 'Source check could not finish: ' + error.message + ' Copy this report.');
    } finally {
      clearTimeout(captureTimer); clearTimeout(decodeTimer);
      reader?.cancel().catch(() => {}); job.controller.abort(); disconnect(job);
      if (active === job) active = null;
      button.textContent = 'Run source check';
    }
  }
  scope.listen(button, 'click', run);
  scope.listen($('visualizer-dialog'), 'close', cancel);
  scope.listen(document, 'visibilitychange', () => {if (document.hidden) cancel();});
  for (const name of ['pause', 'loadstart']) scope.listen(document, name, e => {if (active && e.target === active.graph.audio) cancel();}, true);
  scope.cleanup(cancel);
})();
