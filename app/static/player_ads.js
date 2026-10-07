/* Optional public advertising. Nothing visible until a creative is ready. */
(() => {
  const scope = window.FreoPage;
  if (!scope) return;
  const placements = [...document.querySelectorAll('.phase9-ad[data-ad]')];
  let googleLoading = false, disposed = false;
  const controllers = [];
  function loadGoogle() {
    if (googleLoading) return;
    googleLoading = true;
    window.googletag = window.googletag || {cmd: []};
    const script = document.createElement('script');
    script.async = true; script.src = 'https://securepubads.g.doubleclick.net/tag/js/gpt.js';
    script.crossOrigin = 'anonymous'; document.head.append(script);
  }
  for (const host of placements) {
    let config;
    try {config = JSON.parse(host.dataset.ad);} catch {host.remove(); continue;}
    let expiryTimer, refreshTimer, refreshing = false;
    let generation = 0, frame = null, slot = null, timer = null, currentKey = '', nonce = '', slotHandler = null;
    const collapse = () => {host.hidden = true; host.replaceChildren();};
    const clear = () => {
      generation++; clearTimeout(timer); frame = null; collapse();
      if (slotHandler) {window.googletag?.pubads().removeEventListener('slotRenderEnded', slotHandler); slotHandler = null;}
      if (slot) {const previous = slot; slot = null; window.googletag?.cmd.push(() => window.googletag.destroySlots([previous]));}
    };
    const widthAvailable = () => Math.max(0, Math.min(1100, document.documentElement.clientWidth - 32));
    function choice() {
      const mobile = matchMedia('(max-width:650px)').matches;
      const desired = config.variants[mobile ? 'mobile' : 'desktop'];
      const fallback = config.variants[mobile ? 'desktop' : 'mobile'];
      if (config.source !== 'image') return desired && desired.width <= widthAvailable() ? desired : null;
      if (desired) return desired;
      return fallback && fallback.width <= widthAvailable() ? fallback : null;
    }
    function render() {
      if (disposed) return;
      clearTimeout(expiryTimer);
      if (!config || (config.end && Date.parse(config.end) <= Date.now())) {clear(); currentKey = ''; return;}
      if (config.end) expiryTimer = setTimeout(render, Math.min(2147483647, Math.max(0, Date.parse(config.end)-Date.now())));
      if (host.closest('dialog') && !host.closest('dialog').open) return;
      const variant = choice(), key = JSON.stringify([config, variant]);
      if (key === currentKey) return;
      currentKey = key; clear();
      if (!variant) return;
      const attempt = generation;
      const reveal = node => {
        if (disposed || attempt !== generation || (config.end && Date.parse(config.end) <= Date.now())) return;
        host.replaceChildren(node); host.hidden = false;
      };
      if (config.source === 'image') {
        const image = new Image(); image.alt = config.label; image.width = variant.width; image.height = variant.height;
        image.onload = () => {
          const link = document.createElement('a'); link.href = config.destination;
          link.target = '_blank'; link.rel = 'noopener noreferrer sponsored'; link.append(image); reveal(link);
        };
        image.onerror = () => {if (attempt === generation) clear();};
        image.src = variant.url;
      } else if (config.source === 'iframe') {
        nonce = FreoUUID();
        const url = new URL(config.iframe);
        url.searchParams.set('freo_placement', host.dataset.placement);
        url.searchParams.set('freo_nonce', nonce);
        url.searchParams.set('freo_width', variant.width); url.searchParams.set('freo_height', variant.height);
        frame = document.createElement('iframe'); frame.title = config.label;
        // Opaque origin: provider code cannot read parent DOM or Freo cookies.
        frame.setAttribute('sandbox', 'allow-scripts allow-popups allow-popups-to-escape-sandbox');
        frame.setAttribute('referrerpolicy', 'no-referrer'); frame.setAttribute('credentialless', '');
        frame.width = variant.width; frame.height = variant.height; frame.src = url.href;
        host.append(frame);
        timer = setTimeout(() => {if (attempt === generation) clear();}, 10000);
      } else if (config.source === 'google') {
        loadGoogle();
        const target = document.createElement('div'); target.id = 'freo-ad-' + FreoUUID();
        // GPT's own collapse-before-fetch mechanism keeps the layout empty.
        host.append(target);
        timer = setTimeout(() => {if (attempt === generation) clear();}, 10000);
        window.googletag.cmd.push(() => {
          if (disposed || attempt !== generation) return;
          const gt = window.googletag;
          slot = gt.defineSlot(config.unit, [variant.width, variant.height], target.id);
          if (!slot) return;
          slot.setConfig({collapseDiv: 'BEFORE_FETCH'});
          slot.addService(gt.pubads());
          const handler = event => {
            if (event.slot !== slot || disposed || attempt !== generation) return;
            clearTimeout(timer);
            if (event.isEmpty || !event.size || event.size[0] !== variant.width || event.size[1] !== variant.height) clear();
            else {host.hidden = false;}
          };
          gt.pubads().addEventListener('slotRenderEnded', handler);
          slotHandler = handler;
          gt.enableServices(); gt.display(target.id);
        });
      }
    }
    const message = event => {
      // sandboxed frames have the literal opaque origin "null". A per-load nonce
      // and exact WindowProxy bind the message to this configured placement.
      const data = event.data;
      if (!frame || event.source !== frame.contentWindow || event.origin !== 'null' ||
          !data || data.type !== 'freo-ad-status' || data.nonce !== nonce || data.placement !== host.dataset.placement) return;
      if (data.status === 'empty') {clear(); return;}
      const variant = choice();
      if (data.status !== 'filled' || !variant || data.width !== variant.width || data.height !== variant.height) return;
      clearTimeout(timer); host.hidden = false;
    };
    scope.listen(window, 'message', message);
    let resizeTimer;
    scope.listen(window, 'resize', () => {clearTimeout(resizeTimer); resizeTimer = setTimeout(render, 150);});
    const refresh = async () => {
      if (disposed || refreshing || !host.dataset.adUrl || document.hidden) return;
      if (host.closest('dialog') && !host.closest('dialog').open) return;
      refreshing = true;
      try {
        const url = new URL(host.dataset.adUrl, location.origin);
        if (config?.campaign_id) url.searchParams.set('current', config.campaign_id);
        const response = await fetch(url, {cache:'no-store', signal: aborter.signal});
        if (!response.ok) throw new Error('Advertisement unavailable');
        const data = await response.json();
        if (disposed) return;
        config = data.ad; render();
      } catch {if (!disposed) {config = null; currentKey = ''; clear();}}
      finally {refreshing = false;}
    };
    const aborter = new AbortController();
    if (host.dataset.adUrl) refreshTimer = setInterval(refresh, 60000);
    scope.listen(document, 'visibilitychange', () => {if (!document.hidden) refresh();});
    const dialog = host.closest('dialog');
    const observer = dialog ? new MutationObserver(() => {
      if (dialog.open) {try {render(); refresh();} catch {clear();}}
      else {clear(); currentKey = '';}
    }) : null;
    if (observer) observer.observe(dialog, {attributes:true, attributeFilter:['open']});
    controllers.push(() => {aborter.abort(); observer?.disconnect(); clearInterval(refreshTimer); clearTimeout(expiryTimer); clearTimeout(resizeTimer); clear();});
    try {render();} catch {clear();}
  }
  scope.cleanup(() => {disposed = true; for (const dispose of controllers) dispose();});
})();
