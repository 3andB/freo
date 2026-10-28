/* Retained behind ?audio_debug=1 and an explicit Run source check click.
 * The isolated calibration diagnoses sample delivery; never use its generated
 * PCM for visuals or reconnect/reload native playback from this test. */
/* Explicit diagnostic only. Calibration PCM never enters the player's analyser. */
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
    active.cancelled = true; disconnect(active);
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
    if (graph.fallback?.active) {
      status.textContent = 'The stream decoder is active. Copy the main report to check its real station samples.'; return;
    }
    const job = active = {graph, nativeAnalyser: graph.analyser, src: audio.currentSrc,
      cancelled: false, result: {status: 'checking', startedAt: new Date().toISOString(),
        method: 'live-source-tap-and-isolated-pcm-calibration', additionalStreamRequests: 0}};
    button.textContent = 'Cancel source check';
    try {
      job.result.nativeBefore = nativeSample(graph);
      // Test the live source and a known calibration input through the SAME fresh,
      // muted analyser. Leave the player's analyser and audible gain untouched.
      job.analyser = graph.context.createAnalyser(); job.analyser.fftSize = 1024;
      job.gain = graph.context.createGain(); job.gain.gain.value = 0;
      job.analyser.connect(job.gain); job.gain.connect(graph.context.destination);
      job.input = graph.source || graph.captureSource;
      job.input.connect(job.analyser); job.liveAttached = true;
      job.result.status = 'checking'; publish(job, 'Checking the live source through a fresh, silent analyser…');
      job.result.nativeTap = await measure(job);
      job.input.disconnect(job.analyser); job.liveAttached = false;
      // Known deterministic input tests Web Audio itself, without depending on
      // Safari decoding a partial MP3. This branch is silent and diagnostic only.
      const calibration = graph.context.createBuffer(1, 2048, graph.context.sampleRate);
      const pcm = calibration.getChannelData(0);
      for (let i = 0; i < pcm.length; i++) pcm[i] = .125 * Math.sin(2 * Math.PI * i / 32);
      job.source = graph.context.createBufferSource(); job.source.buffer = calibration; job.source.loop = true;
      job.source.connect(job.analyser);
      job.result.status = 'calibrating'; publish(job, 'Running an isolated, silent Web Audio self-test…');
      job.source.start();
      job.result.calibration = {kind: 'known-pcm-self-test', outputGain: job.gain.gain.value, ...await measure(job)};
      disconnect(job);
      job.result.nativeAfter = nativeSample(graph);
      job.result.playbackGraphUnchanged = window.FreoAudioAnalysis?.read(audio) === graph && graph.analyser === job.nativeAnalyser;
      job.result.mediaTimeAdvanced = job.result.nativeAfter.mediaTime > job.result.nativeBefore.mediaTime;
      job.result.status = 'complete';
      const nativeSilent = job.result.nativeBefore.peak === 0 && job.result.nativeAfter.peak === 0 &&
        job.result.nativeBefore.frequencyPeak === 0 && job.result.nativeAfter.frequencyPeak === 0;
      job.result.outcome = job.result.calibration.peak > .00001
        ? (job.result.nativeTap.peak > .00001 ? (nativeSilent ? 'native-signal-original-analyser-silent' : 'live-source-signal')
          : nativeSilent ? 'live-source-silent-calibration-passed' : 'control-inconclusive') : 'control-inconclusive';
      publish(job, job.result.outcome === 'live-source-silent-calibration-passed'
        ? 'Web Audio passes its self-test, but both live-source checks are silent. Select whether you hear music, then copy this report.'
        : job.result.outcome === 'native-signal-original-analyser-silent' ? 'The fresh live-source analyser receives audio; the original analyser is silent. Copy this report.'
        : job.result.outcome === 'live-source-signal' ? 'Both live-source analysers receive station audio, and the self-test passes. Copy this report.'
        : 'The control did not produce detectable samples. Copy this report; this result alone does not identify the cause.');
    } catch (error) {
      job.result.status = job.cancelled ? 'cancelled' : 'error';
      job.result.error = {name: error.name, message: error.message};
      publish(job, job.cancelled ? 'Source check cancelled. Live playback is unaffected.' : 'Source check could not finish: ' + error.message + ' Copy this report.');
    } finally {
      disconnect(job);
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
