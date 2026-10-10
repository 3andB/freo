(() => {
  const root = document.getElementById('statistics'); if (!root) return;
  const scope = window.FreoPage, $ = id => document.getElementById(id), form = $('stats-filters');
  let result, controller, loading=false, map, mapReady = false, tab = 'overview', transferPeriod = 'month', mapMode = 'live', source = 'stream';
  const params = new URLSearchParams(location.search);
  for (const key of ['range','start','end','timezone']) if (params.has(key)) form.elements[key].value = params.get(key);
  form.elements.compare.checked = params.get('compare') === '1';
  mapMode = ['live','history','all'].includes(params.get('map')) ? params.get('map') : 'live';
  source = params.get('source') === 'website' ? 'website' : 'stream'; $('map-source').value = source;
  let appliedFilters = new URLSearchParams(new FormData(form));
  const number = (v, digits=0) => v === null || v === undefined ? '—' : Number(v).toLocaleString(undefined,{maximumFractionDigits:digits});
  const bytes = v => {if(v === null || v === undefined) return '—'; const scale = v >= 1e12 ? 1e12 : v >= 1e9 ? 1e9 : v >= 1e6 ? 1e6 : v >= 1e3 ? 1e3 : 1;return number(v / scale,2)+' '+({1:'B',1000:'KB',1000000:'MB',1000000000:'GB',1000000000000:'TB'}[scale]);};
  const date = at => at ? new Date(at * 1000).toLocaleString(undefined,{timeZone:result?.timezone || root.dataset.timezone,month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'}) : '—';
  const node = (tag,text,cls) => {const el=document.createElement(tag);if(text!==undefined) el.textContent=text;if(cls) el.className=cls;return el;};
  const percent = v => v === null || v === undefined ? '—' : v > 0 && v < .1 ? '<0.1%' : number(v,1)+'%';
  const empty = (target, text='No activity in this period yet.') => {target.replaceChildren(node('p',text,'stats-empty'));};
  function updateURL(){const p=new URLSearchParams(appliedFilters);p.set('map',mapMode);p.set('source',source);p.set('tab',tab);history.replaceState(null,'',location.pathname+'?'+p);$('stats-export').href=root.dataset.export+'?'+p;return p;}
  function custom(){root.querySelectorAll('.stats-custom').forEach(el=>el.hidden=form.elements.range.value!=='custom');}
  function selectTab(value){tab=value;root.querySelectorAll('[data-tab]').forEach(b=>{const active=b.dataset.tab===value;b.setAttribute('aria-selected',active);b.tabIndex=active?0:-1;});root.querySelectorAll('[data-panels]').forEach(el=>el.hidden=!el.dataset.panels.split(' ').includes(value));$('stats-panels').setAttribute('aria-labelledby','stats-tab-'+value);updateURL();setTimeout(()=>map?.resize(),0);}
  root.querySelectorAll('[data-tab]').forEach((button,index,buttons)=>{scope.listen(button,'click',()=>selectTab(button.dataset.tab));scope.listen(button,'keydown',event=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;event.preventDefault();const next=event.key==='Home'?0:event.key==='End'?buttons.length-1:(index+(event.key==='ArrowRight'?1:-1)+buttons.length)%buttons.length;buttons[next].focus();selectTab(buttons[next].dataset.tab);});});
  const tableSorts = new Map(), tableViews = new Map();
  const sortable = (value, formatter=number) => {
    const span = node('span', formatter(value));
    span.dataset.sortValue = value === null || value === undefined ? '' : String(value);
    return span;
  };
  function table(target, headings, rows) {
    const existing=tableViews.get(target);
    if (rows.length && existing && existing.headings === headings.join('\0')) { existing.rows=rows; existing.render(); return; }
    tableViews.delete(target);
    const focusedColumn = target.contains(document.activeElement) ? document.activeElement.dataset.column : undefined;
    target.replaceChildren();
    if (!rows.length) { empty(target); return; }
    const view={rows,headings:headings.join('\0')};
    const t=node('table',undefined,'admin-table'), thead=node('thead'), tr=node('tr'), body=node('tbody');
    const sortValue = value => {
      if (value instanceof Node && value.dataset.sortValue !== undefined) return value.dataset.sortValue === '' ? null : Number(value.dataset.sortValue);
      const text = value instanceof Node ? value.textContent : String(value ?? '');
      if (text === '—' || text === '') return null;
      // Most existing cells are already formatted counts; preserve numeric order across separators.
      if (/^[\d,.]+%?$/.test(text)) {
        const parts = new Intl.NumberFormat().formatToParts(12345.6);
        const group = parts.find(p => p.type === 'group')?.value || ',';
        const decimal = parts.find(p => p.type === 'decimal')?.value || '.';
        const parsed = Number(text.replaceAll(group, '').replace(decimal, '.').replace('%', ''));
        if (Number.isFinite(parsed)) return parsed;
      }
      return text;
    };
    const render = () => {
      const order = tableSorts.get(target.id);
      const values = [...view.rows];
      if (order) values.sort((a,b) => {
        const left=sortValue(a[order.column]), right=sortValue(b[order.column]);
        if (left === null || right === null) return left === right ? 0 : left === null ? 1 : -1;
        const delta = typeof left === 'number' && typeof right === 'number' ? left-right : String(left).localeCompare(String(right),undefined,{numeric:true});
        return delta * (order.descending ? -1 : 1);
      });
      body.replaceChildren();
      for (const row of values) {
        const r=node('tr');
        row.forEach(value => { const cell=node('td'); if(value instanceof Node) cell.append(value); else cell.textContent=value??'—'; r.append(cell); });
        body.append(r);
      }
      [...tr.children].forEach((th,index) => th.setAttribute('aria-sort', order?.column === index ? (order.descending ? 'descending' : 'ascending') : 'none'));
    };
    headings.forEach((heading,index) => {
      const th=node('th'), button=node('button',heading);
      button.type='button'; button.dataset.column=index;
      button.onclick=() => { const old=tableSorts.get(target.id); tableSorts.set(target.id,{column:index,descending:old?.column===index ? !old.descending : false}); render(); };
      th.append(button); tr.append(th);
    });
    view.render=render; tableViews.set(target,view);
    thead.append(tr); t.append(thead,body); target.append(t); render();
    if (focusedColumn !== undefined) tr.querySelector(`[data-column="${focusedColumn}"]`)?.focus({preventScroll:true});
  }
  function shareBar(value) {
    const cell=node('span',undefined,'stats-share'); cell.dataset.sortValue=value == null ? '' : String(value);
    const text=node('span',percent(value)), track=node('span',undefined,'stats-share-track'), fill=node('i');
    track.setAttribute('aria-hidden','true'); fill.style.width=Math.max(0,Math.min(100,value || 0))+'%';
    track.append(fill); cell.append(text,track); return cell;
  }
  function link(text,url){const a=node('a',text);a.href=url;return a;}
  function songURL(song){const selected=$('stats-scope').value;const channel=result.channels.find(c=>c.id===song.station_id);const match=selected.match(/\/stations\/([^/]+)\//);return '/admin/stations/'+(match?match[1]:channel?.slug || '')+'/media/'+song.uuid;}
  function ranking(target,rows,metric,artist=false){target.replaceChildren();if(!rows.length){empty(target);return;}const max=Math.max(1,...rows.map(r=>r[metric]));rows.slice(0,7).forEach((song,index)=>{const row=node('div',undefined,'stats-ranking'),copy=node('div',undefined,'song-copy');row.append(node('span',String(index+1).padStart(2,'0'),'rank'));if(artist){copy.append(node('b',song.artist));copy.append(node('small','Catalog artist · '+(result.channels.find(c=>c.id===song.station_id)?.name || 'Archived station')));}else{copy.append(link(song.title,songURL(song)),node('small',song.artist));}const bar=node('div',undefined,'rank-bar'),fill=node('i');fill.style.width=(song[metric]/max*100)+'%';bar.append(fill);copy.append(bar);row.append(copy,node('strong',number(song[metric])));target.append(row);});}
  const svgEl=(tag,attrs={})=>{const el=document.createElementNS('http://www.w3.org/2000/svg',tag);Object.entries(attrs).forEach(([k,v])=>el.setAttribute(k,v));return el;};
  const charts = new Map();
  const chartResize = new ResizeObserver(entries => {
    for (const {target} of entries) { const args=charts.get(target); if(args && target.clientWidth) chart(target,...args); }
  });
  scope.cleanup(() => chartResize.disconnect());
  function chart(target, points, key, formatter=number, previous) {
    if (!charts.has(target)) chartResize.observe(target);
    charts.set(target,[points,key,formatter,previous]);
    target.replaceChildren();
    if (![...points,...(previous||[])].some(p => p[key] !== null && p[key] !== undefined)) {
      target.append(node('div','History will appear as observations arrive.','empty')); return;
    }
    if (!target.clientWidth) return;
    const width=Math.max(280,target.clientWidth), left=75, right=width-12, top=18, bottom=180;
    const svg=svgEl('svg',{viewBox:`0 0 ${width} 230`,role:'img','aria-label':'Statistics trend; equivalent values are available in the data table or export'});
    const max=Math.max(1,...points.map(p=>p[key]||0),...(previous||[]).map(p=>p[key]||0));
    for(let i=0;i<4;i++) {
      const y=top+i*(bottom-top)/3;
      svg.append(svgEl('line',{x1:left,y1:y,x2:right,y2:y}));
      const label=svgEl('text',{x:left-10,y:y+4,'text-anchor':'end'});
      label.textContent=formatter(max*(1-i/3),1); svg.append(label);
    }
    function draw(rows,color,dashed) {
      let segment=[];
      const flush=() => {
        if(segment.length) {
          svg.append(svgEl('polyline',{points:segment.join(' '),fill:'none',stroke:color,'stroke-width':2.5,'stroke-linejoin':'round',...(dashed?{'stroke-dasharray':'6 5'}:{})}));
          if(segment.length===1) { const [cx,cy]=segment[0].split(','); svg.append(svgEl('circle',{cx,cy,r:3,fill:color})); }
        }
        segment=[];
      };
      rows.forEach((p,i) => {
        if(p[key]===null || p[key]===undefined) {flush();return;}
        segment.push((left+i/Math.max(1,rows.length-1)*(right-left))+','+(bottom-p[key]/max*(bottom-top)));
      });
      flush();
    }
    if(previous) draw(previous,'#aaa',true);
    draw(points,'#7863e4');
    const first=svgEl('text',{x:left,y:217}); first.textContent=date(points[0]?.at);
    const last=svgEl('text',{x:right,y:217,'text-anchor':'end'}); last.textContent=date(points.at(-1)?.at);
    svg.append(first,last); target.append(svg);
  }
  function insights(target,values){target.replaceChildren();for(const [label,value] of values){const box=node('div');box.append(node('strong',value),node('small',label));target.append(box);}}
  const duration = value => value === null || value === undefined ? '—' : value < 60 ? number(value) + ' sec' : value < 3600 ? number(value / 60, 1) + ' min' : number(value / 3600, 1) + ' hr';
  function renderSessions() {
    const s = result.sessions, previous = s.previous;
    $('session-coverage').textContent = percent(s.coverage) + ' client-list coverage';
    insights($('session-summary'), [
      ['Session starts', number(s.starts)], ['Completed sessions', number(s.completed)],
      ['Average completed duration', duration(s.average_seconds)],
      ['Active now', number(s.active)], ['Interrupted observations', number(s.interrupted)]
    ]);
    let note = s.available ? 'Hourly reporting: ' + date(s.start) + ' – ' + date(s.end) + ' · ' + result.timezone + '. Starts use the first-observed hour; completions and interruptions use the last-observed hour.' : 'Session history is unavailable for this period.';
    note += s.since ? ' Measurement began ' + date(s.since) + '. Earlier durations cannot be reconstructed.' : ' Waiting for the first session observation.';
    if (previous && previous.coverage >= 80 && s.coverage >= 80 && previous.average_seconds !== null) {
      note += ' Previous average: ' + duration(previous.average_seconds) + '; previous starts: ' + number(previous.starts) + '.';
    }
    $('session-note').textContent = note;
    chart($('session-duration-chart'), s.timeline, 'average_seconds', duration, previous?.timeline);
    chart($('session-count-chart'), s.timeline, 'starts', number, previous?.timeline);
    table($('session-trend-data'), ['Time', 'Session starts', 'Completed', 'Average duration'], s.timeline.map(p => [sortable(p.at,date), sortable(p.starts), sortable(p.completed), sortable(p.average_seconds,duration)]));
    table($('session-bands'), ['Observed duration', 'Completed sessions', 'Share'], s.bands.map((b,index) => [sortable(index,()=>b.label), sortable(b.count), shareBar(b.share)]));
    table($('session-retention'), ['Observed for at least', 'Share of completed sessions'], s.retention.map(r => [sortable(r.seconds,duration), shareBar(r.share)]));
    for (const [target, rows] of [['device-table', result.devices.groups], ['player-type-table', result.devices.players]]) {
      table($(target), ['Type', 'Current connections', 'Session starts', 'Share of starts'], rows.map(r => [r.name, sortable(r.current), sortable(r.starts), shareBar(r.share)]));
    }
  }
  function metrics(){const t=result.stats.total,m=result.music,previous=result.previous;const delta=key=>{if(!previous||previous.coverage<80||t.coverage<80||!previous[key])return 'Selected period';return (t[key]>=previous[key]?'+':'')+number((t[key]-previous[key])/previous[key]*100,1)+'% vs previous period';};const data=[['Listening now',number(result.fresh?result.current.listeners:null),result.fresh?'Live stream connections':'Waiting for a fresh observation'],['Average audience',number(t.average,1),'Peak '+number(t.peak)+' · '+delta('average')],['Listener hours',number(t.listener_hours,1),delta('listener_hours')],['Songs played',number(m.plays),number(m.unique_songs)+' different songs'],['Stream transfer · month',bytes(result.transfer.month.bytes),percent(result.transfer.month.coverage)+' transfer coverage'],['Stored media + images',bytes(result.storage?.total),result.storage?'Measured '+date(result.storage.at):'Inventory has not run yet'],['Listener approval',percent(m.feedback.approval),number(m.feedback.total)+' current accepted votes'],[result.current.channels===undefined?'Mount availability':'Expected mounts available',percent(t.uptime),percent(t.coverage)+' observation coverage']];$('stats-metrics').replaceChildren();for(const [label,value,note] of data){const box=node('article',undefined,'stats-metric');box.append(node('small',label),node('strong',value),node('p',note));$('stats-metrics').append(box);}}
  function mapData(){if(!mapReady||!result)return;const features=result.geography.locations.filter(p=>p.lat!==null&&p.lat!==undefined&&(p.count>0||p.seconds>0)).map(p=>({type:'Feature',geometry:{type:'Point',coordinates:[p.lon,p.lat]},properties:{...p,label:[p.city,p.region,p.country].filter(Boolean).join(', ')}}));map.getSource('audience').setData({type:'FeatureCollection',features});root.dataset.mapLocations=features.length;const countries={};result.geography.locations.forEach(p=>{countries[p.country_code]=(countries[p.country_code]||0)+p.count;});const expression=['match',['get','code']];Object.entries(countries).forEach(([code,value])=>expression.push(code,Math.min(.75,.15+Math.log2(value+1)/12)));expression.push(.07);map.setPaintProperty('countries','fill-opacity',expression.length>3?expression:.07);}
  // A Mercator world is 512 CSS pixels at zoom zero. Keep the viewport inside
  // one world at every container size, including fullscreen and hidden tabs.
  // Inset bounds slightly: this MapLibre version wraps exact +/-180 to the same
  // longitude. A tiny zoom margin keeps the zoom-out button at its true limit.
  function worldMinZoom(){const el=$('stats-map');return Math.max(0,Math.log2(Math.max(el.clientWidth,el.clientHeight,1)/512))+.000001;}
  function updateMapLimits(){
    const minimum=worldMinZoom(),overview=map.getZoom()<=map.getMinZoom()+.001;
    if(Math.abs(minimum-map.getMinZoom())<.000001)return;
    map.setMinZoom(minimum);
    if(overview)map.jumpTo({center:[0,20],zoom:minimum});
  }
  function resetMap(){if(map)map.flyTo({center:[0,20],zoom:worldMinZoom(),bearing:0,pitch:0});}
  function mapTheme() {
    if (!mapReady) return;
    const night=document.documentElement.dataset.theme === 'night';
    map.setPaintProperty('background','background-color',night?'#142b35':'#edf0f5');
    map.setPaintProperty('borders','line-color',night?'#66818d':'#aab0c0');
    map.setPaintProperty('countries','fill-color',night?'#a699e5':'#7a68c8');
  }
  scope.listen(window,'freo:themechange',mapTheme);
  function initMap(){if(!window.maplibregl)return;try{maplibregl.setWorkerUrl(root.dataset.worker);map=new maplibregl.Map({container:'stats-map',style:{version:8,sources:{world:{type:'geojson',data:root.dataset.world},audience:{type:'geojson',data:{type:'FeatureCollection',features:[]},cluster:true,clusterRadius:35}},layers:[{id:'background',type:'background',paint:{'background-color':'#edf0f5'}},{id:'countries',type:'fill',source:'world',paint:{'fill-color':'#7a68c8','fill-opacity':.12}},{id:'borders',type:'line',source:'world',paint:{'line-color':'#aab0c0','line-width':.5}},{id:'clusters',type:'circle',source:'audience',filter:['has','point_count'],paint:{'circle-color':'#7863e4','circle-radius':['step',['get','point_count'],15,10,22,50,30],'circle-opacity':.85,'circle-stroke-width':3,'circle-stroke-color':'#ffffff'}},{id:'places',type:'circle',source:'audience',filter:['!', ['has','point_count']],paint:{'circle-color':'#7863e4','circle-radius':['interpolate',['linear'],['get','count'],1,8,25,16,100,24],'circle-opacity':.95,'circle-stroke-width':2,'circle-stroke-color':'#fff'}}]},center:[0,20],zoom:worldMinZoom(),minZoom:worldMinZoom(),maxZoom:8,renderWorldCopies:false,maxBounds:[[-179.999999,-85.051128],[179.999999,85.051128]],dragRotate:false,touchPitch:false,maxPitch:0,attributionControl:false});map.touchZoomRotate.disableRotation();map.keyboard.disableRotation();map.on('resize',updateMapLimits);const mapResize=new ResizeObserver(()=>map.resize());mapResize.observe($('stats-map'));scope.cleanup(()=>mapResize.disconnect());map.addControl(new maplibregl.NavigationControl({showCompass:false}));map.addControl(new maplibregl.FullscreenControl());map.on('load',()=>{mapReady=true;root.dataset.mapReady='true';mapTheme();mapData();});map.on('click','places',event=>{const p=event.features[0].properties;const content=node('div');content.append(node('b',p.label),node('p',number(p.count)+(mapMode==='live'?' online connections':(mapMode==='history'?' session-hours':' recorded sessions'))));new maplibregl.Popup().setLngLat(event.lngLat).setDOMContent(content).addTo(map);});map.on('click','clusters',async event=>{const f=event.features[0];const zoom=await map.getSource('audience').getClusterExpansionZoom(f.properties.cluster_id);map.easeTo({center:f.geometry.coordinates,zoom});});map.on('error',()=>{$('map-selection').textContent='Map rendering is unavailable. Location totals and the table remain available.';});scope.cleanup(()=>map.remove());}catch(error){$('stats-map').append(node('p','Map rendering is unavailable on this device. Use the location list below.','stats-empty'));}}
  function renderGeography(){const g=result.geography;insights($('map-summary'),[[mapMode==='live'?'Online '+(source==='stream'?'connections':'browser sessions'):mapMode==='history'?'Session-hours':'Recorded sessions',number(g.total)],['Countries represented',number(g.countries)]]);if(g.truncated)$('map-summary').append(node('p','Showing the top 2,000 locations; totals include all places.','stats-footnote'));$('map-summary').append(node('p',number(g.located)+' located · '+number(g.total-g.located)+' unknown','stats-footnote'));if(!g.database.available)$('map-summary').append(node('p','Local location database is unavailable. New locations cannot be resolved; cached locations remain visible.','stats-footnote'));$('location-list').replaceChildren();for(const p of g.locations.slice(0,20)){const button=node('button'),copy=node('span',p.city||p.country);copy.append(node('small',p.city?p.country:p.region));button.append(copy,node('b',number(p.count)));button.onclick=()=>{if(map&&p.lat!==null)map.flyTo({center:[p.lon,p.lat],zoom:4,duration:matchMedia('(prefers-reduced-motion: reduce)').matches?0:700});$('map-selection').textContent=[p.city,p.region,p.country].filter(Boolean).join(', ')+' · First observed '+date(p.first_seen)+' · Last observed '+date(p.last_seen);};$('location-list').append(button);}if(!g.locations.length)empty($('location-list'),mapMode==='live'?'No active '+(source==='stream'?'stream connections':'player visitors')+' observed yet. Updates every 15 seconds.':'No locations recorded for this view yet.');table($('location-table'),['Place','Country',mapMode==='live'?'Online':mapMode==='history'?'Session-hours':'Sessions','Observed hours','First seen','Last seen'],g.locations.map(p=>[[p.city,p.region].filter(Boolean).join(', ')||p.country,p.country,number(p.count),number(p.seconds/3600,2),date(p.first_seen),date(p.last_seen)]));root.querySelectorAll('[data-map]').forEach(b=>b.setAttribute('aria-pressed',b.dataset.map===mapMode));mapData();}
  function renderResources(){const transfer=result.transfer[transferPeriod];$('transfer-total').textContent=bytes(transfer.bytes);$('transfer-note').textContent=transferPeriod==='total'?'Since tracking began: '+date(transfer.since):percent(transfer.coverage)+' observed transfer coverage. Counter resets and collection gaps can leave unmeasured usage.';chart($('transfer-chart'),result.stats.timeline,'transfer_bytes',bytes);const storage=result.storage;$('storage-total').textContent=bytes(storage?.total);$('storage-breakdown').replaceChildren();if(storage){const labels={recordings:'Show recordings',music:'Music audio',imaging:'Imaging & carts',artwork:'Album & song artwork',logos:'Logos & thumbnails',player_images:'Player & advertising images'};for(const [key,label] of Object.entries(labels)){const row=node('div',undefined,'stats-storage-row'),bar=node('div',undefined,'rank-bar'),fill=node('i');fill.style.width=((storage[key]||0)/Math.max(1,storage.total)*100)+'%';bar.append(fill);row.append(node('span',label),node('b',bytes(storage[key])),bar);$('storage-breakdown').append(row);}$('storage-note').textContent='Measured '+date(storage.at)+' · '+number(storage.missing)+' missing files · '+number(storage.errors)+' inaccessible paths';const values=[['Retained / unreferenced bytes',bytes(storage.retained)],['Staging',bytes(storage.staging)],['Stored files',number(storage.files)]];if(storage.disk)values.push(['Host disk free',bytes(storage.disk.free)],['Host disk total',bytes(storage.disk.total)]);if(storage.database_bytes)values.push(['PostgreSQL allocation',bytes(storage.database_bytes)]);insights($('storage-insights'),values);}else $('storage-note').textContent='Waiting for the first background inventory.';chart($('storage-chart'),result.storage_history,'bytes',bytes);}
  function musicTable(){const q=$('stats-song-search').value.toLowerCase();table($('music-table'),['Song','Artist','Confirmed plays'],result.music.songs.filter(s=>(s.title+' '+s.artist).toLowerCase().includes(q)).map(s=>[link(s.title,songURL(s)),s.artist,number(s.plays)]));}
  function render(){const t=result.stats.total,m=result.music;$('stats-live-dot').classList.toggle('fresh',result.fresh);$('stats-freshness').textContent=result.fresh?'Updated '+date(result.current.at):'Collector is not reporting';$('stats-origin').textContent=result.current.since?'Tracking since '+date(result.current.since):'Collection has not started';$('stats-message').classList.remove('error');$('stats-message').textContent=t.coverage<95?'History covers '+percent(t.coverage)+' of this period. Unobserved time stays empty.':'Showing observed activity for the selected period.';$('stats-coverage').textContent=percent(t.coverage)+' coverage';$('stats-range-label').textContent=date(result.period.start)+' – '+date(result.period.end)+' · '+result.timezone;$('stats-message').textContent+=' Updates every 15 seconds. The chart shows interval averages; choose Live · past hour to inspect short listening tests.';metrics();renderSessions();chart($('audience-chart'),result.stats.timeline,'average',number,result.previous_timeline);table($('audience-data'),['Time','Average listeners','Sampled peak','Observed seconds'],result.stats.timeline.map(p=>[sortable(p.at,date),number(p.average,2),number(p.peak),number(p.observed)]));renderGeography();table($('channel-table'),['Station','Listening now','Average','Peak','Listener hours','Coverage'],result.channels.map(c=>[link(c.name,'/admin/stations/'+c.slug+'/stats?'+new URLSearchParams(appliedFilters)),number(c.current),number(c.average,1),number(c.peak),number(c.listener_hours,1),percent(c.coverage)]));ranking($('top-songs'),m.songs,'plays');ranking($('top-artists'),m.artists,'plays',true);ranking($('top-liked'),m.liked.filter(s=>s.up),'up');ranking($('top-disliked'),m.disliked.filter(s=>s.down),'down');table($('approval-table'),['Song','Artist','Approval','Likes','Dislikes'],m.approval.map(s=>[link(s.title,songURL(s)),s.artist,percent(s.approval),number(s.up),number(s.down)]));insights($('music-insights'),[['Confirmed music starts',number(m.plays)],['Imaging / cart starts',number(m.imaging_plays)],['Different songs aired',number(m.unique_songs)],['Accessible library',number(m.library_count)],['Rotation coverage',percent(m.rotation_coverage)]]);insights($('feedback-insights'),[['Likes now',number(m.feedback.up)],['Dislikes now',number(m.feedback.down)],['Feedback activity in period',number(m.feedback.activity)],['Preference changes tracked',number(m.feedback.changes)],['Removals tracked',number(m.feedback.removals)]]);musicTable();renderResources();insights($('reliability-insights'),[['Observed mount availability',percent(t.uptime)],['Collection coverage',percent(t.coverage)],['Failed selections',number(result.failed_plays)],['Recorded incidents',number(result.incident_count)]]);insights($('outcome-insights'),[['Timed events started',number(result.outcomes.events.STARTED||0)],['Timed events missed / failed',number((result.outcomes.events.MISSED||0)+(result.outcomes.events.FAILED||0))],['Commercials aired',number(result.outcomes.commercials.AIRED||0)],['Commercials missed / failed',number((result.outcomes.commercials.MISSED||0)+(result.outcomes.commercials.FAILED||0))]]);$('incident-note').textContent=result.incident_count>result.incidents.length?'Showing the latest '+number(result.incidents.length)+' of '+number(result.incident_count)+' incidents.':'All incidents in the selected period are shown.';table($('incident-table'),['Station','Incident','Started','Ended'],result.incidents.map(i=>[i.station,i.detail,sortable(i.started_at,date),sortable(i.ended_at,value=>value?date(value):'Ongoing')]));}
  async function load(background=false){if(background&&loading)return;controller?.abort();const requestController=new AbortController();controller=requestController;loading=true;const query=updateURL();try{const response=await fetch(root.dataset.url+'?'+query,{signal:requestController.signal,cache:'no-store'});if(response.redirected||!response.headers.get('content-type')?.includes('application/json'))throw Error('Your session has expired. Sign in again.');const data=await response.json();if(!response.ok)throw Error(data.error||'Statistics are temporarily unavailable.');result=data;root.dataset.observedAt=data.current.at||'';render();}catch(error){if(error.name==='AbortError')return;$('stats-message').textContent=error.message;$('stats-message').classList.add('error');$('stats-freshness').textContent='Refresh unavailable';$('stats-live-dot').classList.remove('fresh');}finally{if(controller===requestController)loading=false;}}
  scope.listen(form,'submit',event=>{event.preventDefault();appliedFilters=new URLSearchParams(new FormData(form));load();});scope.listen($('stats-range'),'change',custom);scope.listen($('stats-scope'),'change',()=>{window.FreoWorkspace.navigate($('stats-scope').value+'?'+updateURL());});scope.listen($('map-source'),'change',()=>{source=$('map-source').value;load();});root.querySelectorAll('[data-map]').forEach(b=>scope.listen(b,'click',()=>{mapMode=b.dataset.map;load();}));root.querySelectorAll('[data-transfer]').forEach(b=>scope.listen(b,'click',()=>{transferPeriod=b.dataset.transfer;root.querySelectorAll('[data-transfer]').forEach(x=>x.setAttribute('aria-pressed',x===b));if(result)renderResources();}));scope.listen($('map-reset'),'click',resetMap);scope.listen($('stats-song-search'),'input',()=>result&&musicTable());scope.listen(document,'visibilitychange',()=>{if(!document.hidden)load();});scope.cleanup(()=>controller?.abort());scope.interval(()=>{if(!document.hidden)load(true);},15000);custom();selectTab(['overview','audience','music','engagement','resources','reliability'].includes(params.get('tab'))?params.get('tab'):'overview');initMap();load();
})();
