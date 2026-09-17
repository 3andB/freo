/* Persistent listening and document navigation. Page scripts own disposable work. */
(() => {
  if (window.FreoWorkspace) return;
  const makeScope = () => {
    const controller = new AbortController(), timers = new Set(), frames = new Set(), cleanups = [];
    return {
      signal: controller.signal,
      listen(target, name, callback, options = {}) {
        target.addEventListener(name, callback, {...(typeof options === 'boolean' ? {capture: options} : options), signal: controller.signal});
      },
      interval(callback, delay) {const id = setInterval(callback, delay); timers.add(id); return id;},
      frame(callback) {
        if (controller.signal.aborted) return;
        const id = requestAnimationFrame(time => {frames.delete(id); if (!controller.signal.aborted) callback(time);});
        frames.add(id); return id;
      },
      cleanup(callback) {cleanups.push(callback);},
      async fetch(url, options = {}) {
        try {return await fetch(url, {...options, signal: options.signal || controller.signal});}
        catch (error) {if (controller.signal.aborted) return new Promise(() => {}); throw error;}
      },
      dispose() {controller.abort(); timers.forEach(clearInterval); frames.forEach(cancelAnimationFrame); cleanups.forEach(fn => fn());}
    };
  };
  window.FreoPage = makeScope();

  window.FreoDialog = {
    notify(options) {return this.confirm({...options,confirmLabel:"OK",notification:true});},
    confirm({title = 'Confirm change', message, confirmLabel = 'Continue', notification = false, signal}) {
      return new Promise(resolve => {
        if(signal?.aborted){resolve(false);return;}
        const dialog = document.createElement('dialog'); dialog.className = 'freo-dialog';
        const heading = document.createElement('h2'); heading.textContent = title;
        heading.id = `dialog-${crypto.randomUUID()}`; dialog.setAttribute('aria-labelledby', heading.id);
        const copy = document.createElement('p'); copy.textContent = message;
        const actions = document.createElement('div'); actions.className = 'dialog-actions';
        const cancel = document.createElement('button'); cancel.textContent = 'Cancel'; cancel.type = 'button';
        const accept = document.createElement('button'); accept.textContent = confirmLabel; accept.className = 'admin-primary'; accept.type = 'button';
        const previous = document.activeElement;
        let settled=false;
        const abort=()=>finish(false);
        const finish = value => {if(settled)return;settled=true;signal?.removeEventListener('abort',abort);dialog.close(); dialog.remove(); previous?.focus(); resolve(value);};
        signal?.addEventListener('abort',abort,{once:true});
        cancel.addEventListener('click', () => finish(false)); accept.addEventListener('click', () => finish(true));
        dialog.addEventListener('cancel', event => {event.preventDefault(); finish(false);});
        if(!notification)actions.append(cancel);actions.append(accept); dialog.append(heading, copy, actions); document.body.append(dialog); dialog.showModal(); (notification ? accept : cancel).focus();
      });
    }
  };

  const audio = new Audio(); audio.crossOrigin = 'anonymous'; audio.preload = 'none'; audio.id = 'master-monitor-audio';
  // Keep one audio graph for the persistent player across page navigation.
  let monitorContext=null, monitorAnalysers=null;
  const prepareMonitorMeter=()=>{
    const AudioCtx=window.AudioContext||window.webkitAudioContext;
    if(!AudioCtx)return;
    if(!monitorContext){
      monitorContext=new AudioCtx();
      const source=monitorContext.createMediaElementSource(audio),stereo=monitorContext.createGain(),split=monitorContext.createChannelSplitter(2);
      stereo.channelCount=2;stereo.channelCountMode='explicit';
      source.connect(stereo);stereo.connect(split);source.connect(monitorContext.destination);
      monitorAnalysers=[0,1].map(channel=>{const analyser=monitorContext.createAnalyser();analyser.fftSize=1024;split.connect(analyser,channel);return {analyser,data:new Float32Array(analyser.fftSize)};});
    }
    return monitorContext.resume();
  };
  const monitorLevels=()=>{
    if(audio.paused||monitorContext?.state!=='running'||!monitorAnalysers)return [0,0];
    return monitorAnalysers.map(({analyser,data})=>{analyser.getFloatTimeDomainData(data);return Math.sqrt(data.reduce((sum,value)=>sum+value*value,0)/data.length)*audio.volume;});
  };
  let host = null, station = '', stationName = '', stream = '', wanted = false, state = 'off', attempt = 0;
  const render = () => {
    if (!host) return;
    const button = host.querySelector('button');
    button.disabled = !stream; button.setAttribute('aria-pressed', String(wanted));
    button.classList.toggle('is-listening', state === 'listening');
    host.querySelector('.monitor-state').textContent = `${stationName || 'Select a station'} · ${state}`;
    document.querySelectorAll('[data-monitor-toggle]').forEach(el => el.textContent = wanted ? 'MUTE MONITOR' : 'MONITOR');
  };
  const stop = () => {attempt++; wanted = false; audio.pause(); audio.removeAttribute('src'); audio.load(); state = 'off'; render();};
  const play = async () => {
    if (!stream) return;
    document.querySelectorAll('audio,video').forEach(el => {if (el !== audio) el.pause();});
    const version = ++attempt; wanted = true; state = 'connecting'; render();
    audio.src = stream;
    try {await prepareMonitorMeter(); await audio.play(); if (version === attempt) {state = 'listening'; render();}}
    catch (_) {if (version === attempt) {wanted = false; state = 'unavailable — press to retry'; render();}}
  };
  audio.addEventListener('playing', () => {if (wanted) {state = 'listening'; render();}});
  audio.addEventListener('waiting', () => {if (wanted) {state = 'connecting'; render();}});
  audio.addEventListener('error', () => {if (wanted) {wanted = false; state = 'unavailable — press to retry'; render();}});
  document.addEventListener('play', event => {if (event.target !== audio && event.target instanceof HTMLMediaElement) stop();}, true);
  let nowTimer, nowRequest, nowVersion = 0, lastPlaying = null;
  const showNow = (label, item) => {
    const banner = document.querySelector('[data-now-playing]');
    if (!banner) return;
    banner.querySelector('[data-now-label]').textContent = label;
    banner.querySelector('[data-now-title]').textContent = item?.title || '—';
    banner.querySelector('[data-now-title]').title = item?.title || '';
    banner.querySelector('[data-now-artist]').title = item?.artist || '';
    banner.querySelector('[data-now-artist]').textContent = item?.artist || '';
  };
  const refreshNow = async () => {
    clearTimeout(nowTimer);
    nowRequest?.abort();
    const version = ++nowVersion, slug = station;
    if (!document.querySelector('[data-now-playing]')) return;
    if (!slug) {showNow('Select a station', null); return;}
    const controller = new AbortController(); nowRequest = controller;
    const timeout = setTimeout(() => controller.abort(), 4000);
    try {
      const response = await fetch(`/admin/api/stations/${encodeURIComponent(slug)}/live-status`, {cache: 'no-store', signal: controller.signal});
      if (!response.ok) throw new Error('Playback status unavailable');
      const payload = await response.json();
      if (version !== nowVersion) return;
      if (payload.playout_error) {
        lastPlaying = payload.last_known_current || lastPlaying;
        showNow(lastPlaying ? 'Last known · Connection lost' : 'Playback unavailable', lastPlaying);
      } else {
        const mixer = payload.mixer;
        const paused = mixer && ['a', 'b'].map(deck => {
          const item = mixer[deck];
          return !mixer[deck + '_playing'] && item?.started_at &&
            (!payload.current || payload.current.decision_id === item.decision_id) ? item : null;
        }).find(Boolean);
        lastPlaying = payload.current || paused || null;
        showNow(paused ? 'Paused' : payload.current ? 'Now playing' : 'Nothing playing', lastPlaying);
      }
    } catch (_) {
      if (version === nowVersion) showNow(lastPlaying ? 'Last known · Connection lost' : 'Playback unavailable', lastPlaying);
    } finally {
      clearTimeout(timeout);
      if (version === nowVersion) nowTimer = setTimeout(refreshNow, 3000);
    }
  };
  const mount = () => {
    const header = document.querySelector('.admin-topbar');
    if (header) {
      const sizeHeader = () => document.documentElement.style.setProperty('--header-height', `${header.getBoundingClientRect().height}px`);
      const observer = new ResizeObserver(sizeHeader);
      observer.observe(header); sizeHeader();
      window.FreoPage.cleanup(() => observer.disconnect());
    }

    const placeholder = document.querySelector('[data-master-monitor]');
    if (!placeholder) {stop(); host?.remove(); clearTimeout(nowTimer); nowVersion++; nowRequest?.abort(); return;}
    const availableStations = placeholder.dataset.availableStations ? JSON.parse(placeholder.dataset.availableStations) : null;
    const preserve = placeholder.hasAttribute('data-preserve-station') && (!availableStations || availableStations.includes(station));
    const next = preserve ? station : placeholder.dataset.station || '', nextStream = preserve ? stream : placeholder.dataset.stream || '';
    stationName = preserve ? stationName : placeholder.dataset.stationName || '';
    if (!host) {
      host = document.createElement('div'); host.className = 'master-monitor';
      host.innerHTML = '<button type="button" aria-pressed="false"><span class="monitor-dot" aria-hidden="true"></span> Monitor</button><small class="monitor-state" role="status"></small><label class="monitor-volume">Volume<input type="range" min="0" max="100" value="80" aria-label="Master monitor listening volume"></label>';
      audio.volume = .8;
      host.querySelector('button').addEventListener('click', () => wanted ? stop() : play());
      host.querySelector('input').addEventListener('input', event => audio.volume = Number(event.target.value) / 100);
    }
    placeholder.replaceWith(host);
    if (next !== station || nextStream !== stream) {
      lastPlaying = null; showNow('Checking playback…', null);
      const resume = wanted; station = next; stream = nextStream;
      if (resume) {stop(); play();}
    }
    render();
    if (lastPlaying) showNow('Checking playback…', lastPlaying);
    refreshNow();
  };
  window.FreoMonitor = {toggle: () => wanted ? stop() : play(), stop, audio, levels:monitorLevels};

  let navigating = false, dirty = false;
  // Browser fragment navigation also emits popstate. Track the rendered page,
  // since location has already changed by the time a history event arrives.
  let renderedPage = location.pathname + location.search;
  const remember = () => history.replaceState({...history.state, freo: true, scroll: scrollY}, '', location.href);
  const isPage = url => url.origin === location.origin && !/\/(api|stream|static)\//.test(url.pathname) && !/\/(audition|artwork|export|download)(\/|$)/.test(url.pathname);
  async function navigate(url, options = {}) {
    if (navigating) return;
    if (dirty && !options.submitted && !await FreoDialog.confirm({title: 'Leave unsaved changes?', message: 'Your edits on this page have not been saved. Leave this page and discard them?', confirmLabel: 'Leave page'})) return;
    navigating = true; document.documentElement.classList.add('is-navigating');
    try {
      const response = await fetch(url, {credentials: 'same-origin', ...options.request});
      if (!response.headers.get('content-type')?.includes('text/html')) {location.assign(url); return;}
      const destination = new URL(response.url);
      const requestedHash = new URL(url, location.href).hash;
      if (requestedHash) destination.hash = requestedHash;
      const next = new DOMParser().parseFromString(await response.text(), 'text/html');
      if (!next.querySelector('#main')) throw new Error('Page unavailable');
      if (!options.pop) remember();
      window.FreoPage.dispose(); window.FreoPage = makeScope();
      document.querySelectorAll('audio,video').forEach(el => {if (el !== audio) {el.pause(); el.removeAttribute('src'); el.load();}});
      host?.remove();
      const scripts = [...next.querySelectorAll('script[src]')].map(el => el.src).filter(src => new URL(src).origin === location.origin && !src.includes('/workspace.js'));
      next.querySelectorAll('script').forEach(el => el.remove());
      document.querySelectorAll('link[href*="/website-theme.css"]').forEach(link => link.remove());
      next.querySelectorAll('link[rel="stylesheet"]').forEach(link => {
        if (![...document.querySelectorAll('link[rel="stylesheet"]')].some(el => el.href === link.href)) document.head.insertBefore(link.cloneNode(true), document.querySelector('link[href*="/theme.css"]'));
      });
      document.title = next.title; document.body.className = next.body.className;
      document.body.replaceChildren(...next.body.childNodes);
      renderedPage = destination.pathname + destination.search;
      window.FreoTheme?.sync();
      if (!options.pop) history.pushState({freo: true, scroll: 0}, '', destination.href);
      dirty = false; mount(); prepareForms();
      for (const src of scripts) await new Promise((resolve, reject) => {
        const script = document.createElement('script'); script.src = src; script.onload = resolve; script.onerror = reject; document.body.append(script);
      });
      document.querySelector('#main')?.setAttribute('tabindex', '-1'); document.querySelector('#main')?.focus({preventScroll: true});
      if (destination.hash) document.getElementById(decodeURIComponent(destination.hash.slice(1)))?.scrollIntoView();
      else window.scrollTo(0, options.pop ? history.state?.scroll || 0 : 0);
    } catch (_) {
      const notice = document.createElement('p'); notice.className = 'admin-notice error'; notice.setAttribute('role', 'alert');
      notice.textContent = 'This page could not load. Check your connection and try again.'; document.querySelector('#main')?.prepend(notice);
    } finally {navigating = false; document.documentElement.classList.remove('is-navigating');}
  }
  const prepareForms = () => document.querySelectorAll('form').forEach(form => {form.noValidate = true;});
  document.addEventListener('input', event => {if (event.target.closest('form[method="post"]')) dirty = true;});
  document.addEventListener('click', event => {
    const link = event.target.closest('a[href]');
    if (!link || event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || link.target || link.hasAttribute('download')) return;
    const url = new URL(link.href);
    if (!isPage(url) || (url.pathname === location.pathname && url.search === location.search && url.hash)) return;
    event.preventDefault(); navigate(url.href);
  });
  document.addEventListener('submit', async event => {
    const form = event.target;
    if (event.defaultPrevented || form.method === 'dialog') return;
    const invalid = [...form.elements].find(el => el.willValidate && !el.validity.valid);
    if (invalid) {event.preventDefault(); invalid.focus(); let error = form.querySelector('.form-error'); if (!error) {error = document.createElement('p'); error.className = 'form-error admin-notice error'; error.setAttribute('role', 'alert'); form.prepend(error);} error.textContent = `${invalid.labels?.[0]?.textContent?.trim() || 'Field'}: ${invalid.validationMessage}`; return;}
    const url = new URL(event.submitter?.hasAttribute('formaction') ? event.submitter.formAction : form.action);
    if (/\/(login|logout)$/.test(url.pathname)) {stop();return;}
    if (!isPage(url) || form.target || event.submitter?.formTarget) return;
    event.preventDefault();
    if (url.pathname.endsWith('/logout')) stop();
    if (form.dataset.confirm && !await FreoDialog.confirm({title:'Confirm change',message:form.dataset.confirm,confirmLabel:event.submitter?.textContent.trim() || 'Continue'})) return;
    const data = new FormData(form, event.submitter);
    if (form.method === 'get') {
      if(form.classList.contains('station-picker')) {
        const selected=String(data.get('station')||'');
        if(/^\/admin\/stations\/[^/]+\//.test(url.pathname))url.pathname=url.pathname.replace(/^(\/admin\/stations\/)[^/]+/, '$1'+encodeURIComponent(selected));
        else if(url.pathname==='/admin/stations')url.pathname='/admin';
      }
      url.search = new URLSearchParams(data).toString(); navigate(url.href);
    }
    else navigate(url.href, {submitted: true, request: {method: 'POST', body: data}});
  });
  window.addEventListener('popstate', () => {
    if (location.pathname + location.search === renderedPage) return;
    navigate(location.href, {pop: true});
  });
  window.FreoWorkspace = {navigate};
  mount(); prepareForms(); remember();
})();
