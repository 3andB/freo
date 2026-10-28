/* Optional MP3 analysis fallback. Native playback never depends on this stream. */
(() => {
  const scope = window.FreoPage;
  if (!scope) return;
  const api = {start};
  window.FreoStreamAnalysis = api;
  scope.cleanup(() => {if (window.FreoStreamAnalysis === api) delete window.FreoStreamAnalysis;});
  function start(graph, isCurrent, changed) {
    const original = graph.analyser, context = graph.context, audio = graph.audio, src = audio.currentSrc;
    const controller = new AbortController(), nodes = new Set();
    let worker, reader, analyser, input, sink, pending, sequence = 0, nextTime = 0, watchdog;
    let lastProgress = performance.now();
    const state = {active: true, status: 'connecting', error: null, input: null, startedAt: performance.now(),
      bytes: 0, samples: 0, sampleRate: null, queuedSeconds: 0, underruns: 0, buffers: 0,
      stop, diagnostics: () => ({active: state.active, status: state.status, error: state.error,
        bytes: state.bytes, samples: state.samples, sampleRate: state.sampleRate,
        queuedSeconds: Math.round(state.queuedSeconds * 1000) / 1000, buffers: nodes.size,
        underruns: state.underruns, outputGain: sink?.gain.value ?? 0,
        connection: 'independent-same-station-stream'})};
    graph.fallback = state;
    function stop() {
      if (!state.active) return;
      state.active = false; state.status = 'stopped';
      controller.abort(); clearInterval(watchdog);
      reader?.cancel().catch(() => {}); worker?.terminate();
      if (pending) {clearTimeout(pending.timer); pending.reject(new Error('Analysis stopped')); pending = null;}
      for (const node of nodes) {try {node.stop(); node.disconnect();} catch {}}
      nodes.clear();
      for (const node of [input, analyser, sink]) {try {node?.disconnect();} catch {}}
      if (graph.analyser === analyser) graph.analyser = original;
      state.input = null; state.queuedSeconds = 0;
    }
    function valid() {
      if (controller.signal.aborted) throw controller.signal.reason || new Error('Analysis stopped');
      if (!state.active || !isCurrent() || document.hidden || audio.paused || audio.readyState < 3 || audio.currentSrc !== src || context.state !== 'running')
        throw new Error('Analysis playback changed');
    }
    function wait(ms) {
      return new Promise((resolve, reject) => {
        const done = () => {clearTimeout(timer); controller.signal.removeEventListener('abort', abort); resolve();};
        const abort = () => {clearTimeout(timer); reject(new Error('Analysis stopped'));};
        const timer = setTimeout(done, ms);
        controller.signal.addEventListener('abort', abort, {once: true});
        if (controller.signal.aborted) abort();
      });
    }
    function request(type, bytes) {
      return new Promise((resolve, reject) => {
        const id = ++sequence;
        const timer = setTimeout(() => {pending = null; reject(new Error('Audio decoder timed out'));}, 8000);
        pending = {id, resolve, reject, timer};
        worker.postMessage({id, type, bytes}, bytes ? [bytes.buffer] : []);
      });
    }
    async function schedule(decoded) {
      if (!decoded.samplesDecoded) return;
      state.samples += decoded.samplesDecoded; state.sampleRate = decoded.sampleRate;
      // Small chunks and backpressure bound scheduled PCM to about 2.3 seconds.
      const blockSize = Math.floor(decoded.sampleRate / 4);
      for (let offset = 0; offset < decoded.samplesDecoded; offset += blockSize) {
        valid();
        while (nextTime - context.currentTime > 2) {await wait(50); valid();}
        if (nodes.size >= 32) throw new Error('Analysis buffer limit reached');
        const length = Math.min(blockSize, decoded.samplesDecoded - offset);
        const buffer = context.createBuffer(decoded.channelData.length, length, decoded.sampleRate);
        decoded.channelData.forEach((channel, index) => buffer.copyToChannel(channel.subarray(offset, offset + length), index));
        const node = context.createBufferSource(); node.buffer = buffer; node.connect(input); nodes.add(node);
        node.onended = () => {nodes.delete(node); node.disconnect();};
        if (nextTime && nextTime < context.currentTime) state.underruns++;
        const when = Math.max(nextTime, context.currentTime + .06);
        node.start(when); nextTime = when + buffer.duration;
        state.queuedSeconds = nextTime - context.currentTime; state.buffers = nodes.size;
      }
    }
    async function run() {
      try {
        valid();
        const url = new URL(src, location.href);
        if (url.origin !== location.origin || !/^\/(listen|stream)\//.test(url.pathname)) throw new Error('Unsupported analysis stream');
        worker = new Worker('/static/player_stream_worker.js?v=v1-iphone-stream-1');
        worker.onmessage = ({data}) => {
          if (!pending || data.id !== pending.id) return;
          const reply = pending; pending = null; clearTimeout(reply.timer);
          data.error ? reply.reject(new Error(data.error)) : reply.resolve(data);
        };
        worker.onerror = () => {if (pending) {const reply = pending; pending = null; clearTimeout(reply.timer); reply.reject(new Error('Audio decoder unavailable'));}};
        await request('init'); valid();
        input = context.createGain(); analyser = context.createAnalyser(); sink = context.createGain();
        analyser.fftSize = 1024; analyser.smoothingTimeConstant = .72; sink.gain.value = 0;
        input.connect(analyser); analyser.connect(sink); sink.connect(context.destination);
        state.input = input; graph.analyser = analyser; changed();
        url.searchParams.set('_freo_visual', String(Date.now()));
        watchdog = setInterval(() => {
          if (performance.now() - lastProgress > 12000 || (!state.samples && performance.now() - state.startedAt > 12000))
            controller.abort(new Error('Analysis stream stalled'));
        }, 1000);
        const response = await fetch(url.href, {signal: controller.signal, mode: 'same-origin', credentials: 'same-origin', cache: 'no-store'});
        if (!response.ok || new URL(response.url).origin !== location.origin ||
            !/^audio\/(mpeg|mp3)(;|$)/i.test(response.headers.get('content-type') || '') || !response.body)
          throw new Error('MP3 analysis stream unavailable');
        reader = response.body.getReader();
        state.status = 'streaming'; changed();
        while (true) {
          valid();
          const {done, value} = await reader.read();
          if (done) throw new Error('Analysis stream ended');
          lastProgress = performance.now(); state.bytes += value.length;
          // Keep exactly one decoder operation in flight; never queue raw chunks.
          for (let offset = 0; offset < value.length; offset += 8192) {
            valid();
            const decoded = await request('decode', value.slice(offset, offset + 8192));
            valid(); await schedule(decoded); lastProgress = performance.now();
          }
        }
      } catch (error) {
        if (!state.active) return;
        const message = controller.signal.reason?.message || error.message;
        stop(); state.status = 'error'; state.error = message; changed();
      }
    }
    run();
    return state;
  }
})();
