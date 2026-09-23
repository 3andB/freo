/* Shared source browser, composition console, and scheduling timeline. */
(() => {
'use strict';
const root=document.getElementById('schedule-studio');if(!root)return;
const page=window.FreoPage, editor=window.FreoScheduleEditor;
const $=id=>document.getElementById(id), clone=value=>structuredClone(value), uid=()=>FreoUUID();
const view=root.dataset.view, composing=['shows','blocks'].includes(view), autosave=view==='calendar';
let state=JSON.parse($('schedule-initial').value), compositions=[], composition={kind:view==='blocks'?'BLOCK':'SHOW',name:'',description:'',duration:view==='blocks'?86400:3600,sections:[]};
let entries=clone(state.calendar), assignments=clone(state.assignments), simple=clone(state.simple), dirty=false, undo=[],redo=[],libraryKind=composing?'playlist':'show',sourcePage=1,dragged=null,editing=null,accordion=false,expanded=new Set(composing?[0]:[9,10,11]),events=[],pattern=[];
let searchController,searchTimer,hoverTimer,hoverHour,selectedDate=new Intl.DateTimeFormat('en-CA',{timeZone:state.timezone,year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date()),layout='Week';
const requested=new URLSearchParams(location.search);if(/^\d{4}-\d{2}-\d{2}$/.test(requested.get('date')||''))selectedDate=requested.get('date');const requestedView=requested.get('view');if(['day','week','month','agenda'].includes(requestedView))layout=requestedView[0].toUpperCase()+requestedView.slice(1);
const localKey='freo-schedule:'+root.dataset.station+':'+view;
const stored=key=>{try{return JSON.parse(localStorage.getItem(localKey+':'+key)||'[]');}catch{return [];}};
let favorites=stored('favorites'),recent=stored('recent');
let selectedSection=null,repeatDisplay='compact',filterText='',filterKind='',suppressClick=false,scopeProposal=null;
try{repeatDisplay=localStorage.getItem(localKey+':recurring')||'compact';}catch{}
let baseRevision=state.revision, editGeneration=0, saving=false, validations=0, eventRequest=0, dragActive=false, renderPending=false;
let saveTimer,savePromise,saveBlocked=false,saveConflict=null,retryDelay=1000,refreshing=false;
const saveButton=$('save-schedule'), same=editor.equal;
function message(value,error=false){$('studio-message').textContent=value;$('studio-message').classList.toggle('error',error);}
async function api(action,data){
    const options=data===undefined?{}:{method:'POST',body:new URLSearchParams({csrf:root.dataset.csrf,payload:JSON.stringify(data)})};
    const response=await page.fetch(root.dataset.api+action,options);
    if(!response.headers.get('content-type')?.includes('application/json')){
        if(response.status>=500)throw Object.assign(Error('Server temporarily unavailable. Your changes will retry automatically.'),{status:response.status,retryable:true});
        throw Object.assign(Error('Sign in again to save. Your changes are kept in this browser.'),{status:401});
    }
    const result=await response.json();
    if(!response.ok)throw Object.assign(Error(result.error||'Unable to save'),{status:response.status,retryable:result.retryable||response.status>=500,conflict:result.conflict,latest:result.state});
    return result;
}
function dateObj(day){return new Date(day+'T12:00:00Z');}
function iso(day){return day.toISOString().slice(0,10);}
function shift(day,n){const d=dateObj(day);d.setUTCDate(d.getUTCDate()+n);return iso(d);}
function weekday(day){return (dateObj(day).getUTCDay()+6)%7;}
function seconds(value){const p=value.split(':').map(Number);return p[0]*3600+p[1]*60+(p[2]||0);}
function clock(value){value=((value%86400)+86400)%86400;return [Math.floor(value/3600),Math.floor(value/60)%60,Math.floor(value)%60].map(n=>String(n).padStart(2,'0')).join(':');}
function timeLabel(value){return value===86400?'24:00':clock(value).slice(0,5);}
function node(tag,text,className){const el=document.createElement(tag);if(text!==undefined)el.textContent=text;if(className)el.className=className;return el;}
function button(text,fn){const el=node('button',text);el.type='button';el.addEventListener('click',fn);return el;}
function snapshot(){return {entries:clone(entries),assignments:clone(assignments),simple:clone(simple),composition:clone(composition)};}
function restore(saved){({entries,assignments,simple,composition}=clone(saved));syncComposition();render();markDirty();}
function before(){undo.push(snapshot());if(undo.length>50)undo.shift();redo=[];}
function rememberDraft(){try{localStorage.setItem(localKey+':draft',JSON.stringify({revision:baseRevision,base:{calendar:state.calendar,assignments:state.assignments,simple:state.simple},...snapshot()}));}catch{}}
function queueSave(delay=400){
    clearTimeout(saveTimer);saveTimer=null;
    if(autosave&&dirty&&!saveBlocked&&!page.signal.aborted)saveTimer=setTimeout(()=>{saveTimer=null;save();},delay);
}
function markDirty(){
    editGeneration++;dirty=true;if(!saveConflict)saveBlocked=false;
    $('save-state').textContent=saveConflict?'Not saved':autosave?'Saving…':'Unsaved changes';
    $('undo-edit').disabled=!undo.length;$('redo-edit').disabled=!redo.length;
    updateBlockSummary();rememberDraft();queueSave();
}
$('undo-edit').onclick=()=>{if(!undo.length)return;redo.push(snapshot());restore(undo.pop());};$('redo-edit').onclick=()=>{if(!redo.length)return;undo.push(snapshot());restore(redo.pop());};
function updateStatus(){const pending=state.transition&&['PENDING','PREPARING','FADING'].includes(state.transition.state);$('active-mode').textContent=pending?`Switching ${state.mode} → ${state.transition.mode}…`:`Active mode: ${state.mode.charAt(0)+state.mode.slice(1).toLowerCase()}`;$('mode-detail').textContent=`${state.timezone} · ${state.playing_fallback?'Playing default playlist: '+(state.fallback?.name||'Unavailable'):state.activated?'Following your saved programming':'Existing programming retained until activation'}`;document.querySelectorAll('[data-mode-badge]').forEach(el=>{const active=el.dataset.modeBadge===state.mode;el.textContent=active?'● Active':'Open workspace';el.classList.toggle('is-active',active);});const activate=$('activate-mode');if(activate){activate.disabled=pending||saving||validations>0;activate.textContent=state.mode===view.toUpperCase()&&state.activated?(view==='simple'?'Change what plays':'Active mode'):'Use '+view[0].toUpperCase()+view.slice(1);if(state.held&&state.activated)activate.textContent='Resume '+view[0].toUpperCase()+view.slice(1);if(view!=='simple'&&state.mode===view.toUpperCase()&&state.activated&&!state.held)activate.disabled=true;}document.querySelectorAll('.schedule-mode-status').forEach(el=>el.textContent=$('active-mode').textContent);if(state.transition?.state==='FAILED')message(state.transition.error,true);}
const matches=editor.matches;
function dayEntries(day){return editor.coverage(entries,day);}
function assigned(day){const rows=assignments.filter(a=>matches(a.rule,day)),dated=rows.filter(a=>['once','dates'].includes(a.rule.frequency));return (dated.length?dated:rows).map(a=>({...a,source:a.pattern[Math.round((dateObj(day)-dateObj(a.rule.anchor))/86400000)%a.pattern.length]}));}
function duration(){return composing?composition.duration:86400;}
let blockHourHeight=48;
function fallbackLabel(){return state.fallback?'Default: '+state.fallback.name:'No default playlist configured';}
function height(hour){if(composing&&duration()<3600)return 180*3600/duration();return accordion?(expanded.has(hour)?180:28):(view==='blocks'?blockHourHeight:84);}
function yFor(second){let y=0;for(let h=0;h<Math.floor(second/3600);h++)y+=height(h);return y+(second%3600)/3600*height(Math.floor(second/3600));}
function secondFor(y){y=Math.max(0,y);let h=0;while(y>height(h)&&h<23){y-=height(h);h++;}return Math.min(duration(),h*3600+y/height(h)*3600);}
function snap(second){const step=Number($('timeline-snap')?.value||900);return Math.round(second/step)*step;}
function overview(){const el=$('time-overview');if(!el)return;el.replaceChildren();for(let hour=0;hour<Math.ceil(duration()/3600);hour++){const b=button(String(hour).padStart(2,'0'),()=>{accordion=true;expanded.has(hour)?expanded.delete(hour):expanded.add(hour);$('accordion-toggle').setAttribute('aria-pressed','true');render();});b.setAttribute('aria-label',`Expand hour ${hour}`);b.setAttribute('aria-pressed',String(accordion&&expanded.has(hour)));el.append(b);}}
function filterMatches(name,kind){return (!filterText||name.toLocaleLowerCase().includes(filterText))&&(!filterKind||kind===filterKind);}
function isSelected(item){return selectedSection?.id===item.id&&selectedSection?.origin===(item.origin||selectedDate);}
function visibleItem(item){return isSelected(item)||(filterMatches(item.source.name,item.source.kind)&&(repeatDisplay!=='hide'||!editor.recurring(item)));}
function visibleEvent(event){return filterMatches(event.name,'event')&&(repeatDisplay!=='hide'||!event.recurring);}
function selectSection(item,day){selectedSection={id:item.id,origin:item.origin||day,day};updateSelection();document.querySelectorAll('.timeline-section').forEach(el=>el.classList.toggle('is-selected',el.dataset.id===item.id&&el.dataset.origin===selectedSection.origin));}
function updateSelection(){
    const item=selectedSection&&(composing?composition.sections:entries).find(row=>row.id===selectedSection.id);
    $('selected-section').hidden=false;$('edit-selected-section').disabled=$('clear-selected-section').disabled=!item;
    $('selected-section-label').textContent=item?`${item.source.name} · ${composing?'':selectedSection.origin+' · '}${timeLabel(item.start)}–${timeLabel(item.end)}${item.end>86400?' (+1 day)':''}`:'Select a schedule to edit its details';
    syncBlockTiming(item);
}
function render(){
    if(dragActive){renderPending=true;return;}renderPending=false;updateStatus();updateBlockSummary();
    if(view==='simple'){const el=$('simple-selection');el.textContent=simple?`${simple.name} · repeats continuously`:'Drop a Block, Show, playlist, category, artist, album, or song here';el.classList.toggle('is-selected',!!simple);$('simple-playback-help').textContent=simple?.kind==='block'?'Starts at the beginning when activated and repeats every 24 hours. No day assignment is needed.':'Pick a source from the library. It plays continuously until you change it.';return;}
    const timeline=$('timeline'),top=timeline.scrollTop,left=timeline.scrollLeft;
    overview();updateSelection();timeline.replaceChildren();$('short-sections').replaceChildren();$('overridden-schedules').replaceChildren();
    if(!composing){
        const first=layout==='Month'?shift(selectedDate.slice(0,8)+'01',-weekday(selectedDate.slice(0,8)+'01')):layout==='Week'?shift(selectedDate,-weekday(selectedDate)):selectedDate;
        let hidden=0;for(let i=0;i<(layout==='Month'?42:layout==='Day'?1:7);i++){const day=shift(first,i);const raw=editor.occurrences(entries,day),effective=dayEntries(day);hidden+=raw.filter(item=>!visibleItem(item)).length;for(const item of raw.filter(row=>editor.recurring(row)&&visibleItem(row))){const shown=effective.filter(row=>row.id===item.id&&row.origin===item.origin).reduce((total,row)=>total+row.end-row.start,0);if(shown<item.end-item.start)$('overridden-schedules').append(button(`${day} · ${item.source.name} · overridden${shown?' in part':''}`,()=>openInspector(item,day)));}hidden+=events.filter(event=>event.date===day&&!visibleEvent(event)).length;}
        $('hidden-schedules').hidden=!hidden;$('hidden-schedules').textContent=`${hidden} hidden · Show all`;
    }
    if(!composing&&layout==='Month')renderMonth(timeline);
    else if(!composing&&layout==='Agenda')renderAgenda(timeline);
    else renderGrid(timeline);
    timeline.scrollTop=top;timeline.scrollLeft=left;
}
function renderGrid(timeline){
    const first=!composing&&layout==='Week'?shift(selectedDate,-weekday(selectedDate)):selectedDate,days=composing||layout==='Day'?1:7;
    const grid=node('div',undefined,'time-grid');grid.style.setProperty('--days',days);grid.append(node('div',composing?'ELAPSED':state.timezone,'time-day-header'));
    for(let i=0;i<days;i++){const day=shift(first,i),header=node('div',composing?(view==='blocks'?'24-hour format':'Show composition'):dateObj(day).toLocaleDateString(undefined,{weekday:'short',timeZone:'UTC'}),'time-day-header');if(!composing)header.append(node('strong',dateObj(day).getUTCDate()));grid.append(header);}
    const ruler=node('div',undefined,'time-ruler');ruler.style.height=yFor(duration())+'px';
    for(let hour=0;hour<=duration()/3600;hour++){const label=node('span',timeLabel(hour*3600),'time-label');label.style.top=yFor(hour*3600)+'px';ruler.append(label);}grid.append(ruler);
    for(let i=0;i<days;i++){
        const day=shift(first,i),column=node('div',undefined,'time-column');column.dataset.date=day;column.style.height=yFor(duration())+'px';
        for(let hour=0;hour<duration()/3600;hour++){const line=node('div',undefined,'hour-line');line.style.top=yFor(hour*3600)+'px';column.append(line);}
        const all=composing?composition.sections:dayEntries(day);let covered=0;
        const band=(start,end,text,className='fallback-band')=>{const el=node('div',text,className);el.style.top=yFor(start)+'px';el.style.height=(yFor(end)-yFor(start))+'px';column.append(el);};
        for(const item of [...all].sort((a,b)=>a.start-b.start)){
            if(item.start>covered)band(covered,item.start,`${timeLabel(covered)}–${timeLabel(item.start)} · ${fallbackLabel()}`);
            covered=Math.max(covered,item.end);
            if(!composing&&!visibleItem(item))band(item.start,item.end,'Scheduled · hidden','hidden-coverage');
        }
        if(covered<duration())band(covered,duration(),`${timeLabel(covered)}–${timeLabel(duration())} · ${fallbackLabel()}`);
        for(const item of all.filter(item=>composing||visibleItem(item))){
            column.append(sectionElement(item,day));
            if(yFor(item.end)-yFor(item.start)<30)$('short-sections').append(button(`${composing?'':day+' · '}${timeLabel(item.start)}–${timeLabel(item.end)} · ${item.source.name}`,()=>{selectSection(item,day);openInspector(item,day);}));
        }
        if(!composing){
            const dayEvents=events.filter(event=>event.date===day&&visibleEvent(event));
            if(dayEvents.length){
                column.classList.add('has-events');const lane=node('div',undefined,'timeline-event-lane');lane.setAttribute('aria-label','Timed events');
                const groups=new Map();for(const event of dayEvents){if(!groups.has(event.second))groups.set(event.second,[]);groups.get(event.second).push(event);}
                for(const [second,list] of groups){const group=node('details',undefined,'timeline-event-group');group.style.top=yFor(second)+'px';group.append(node('summary',`${timeLabel(second)} · ${list.length===1?list[0].name:list.length+' events'}`));for(const event of list)group.append(eventLink(event));lane.append(group);}column.append(lane);
            }
            const today=new Intl.DateTimeFormat('en-CA',{timeZone:state.timezone,year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
            if(today===day){const p=new Intl.DateTimeFormat('en-GB',{timeZone:state.timezone,hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(new Date()),line=node('div',undefined,'now-marker');line.style.top=yFor(seconds(p))+'px';column.append(line);}
        }
        column.addEventListener('dragover',e=>{if(!dragged)return;e.preventDefault();e.dataTransfer.dropEffect='copy';column.classList.add('drop-target');});
        column.addEventListener('dragleave',e=>{if(!column.contains(e.relatedTarget))column.classList.remove('drop-target');});
        column.addEventListener('drop',e=>{
            if(!dragged)return;e.preventDefault();column.classList.remove('drop-target');
            const ref=dragged;dragged=null;const target=e.target.closest('.timeline-section');
            if(composing&&ref.kind==='artist'&&target){const host=composition.sections.find(s=>s.id===target.dataset.id);if(host?.source.kind==='artist'){before();host.source.artists=[...new Set([host.source.id,...(host.source.artists||[]),ref.id])];host.source.name+='+ '+ref.name;markDirty();render();return;}}
            const start=Math.min(duration()-60,Math.max(0,snap(secondFor(e.clientY-column.getBoundingClientRect().top))));placeSource(ref,day,start);
        });
        grid.append(column);
    }
    timeline.append(grid);
}
async function placeSource(ref,day,start){
    if(!composing&&ref.kind==='block')start=0;
    const end=composing&&!composition.sections.length&&ref.kind!=='song'?duration():Math.min(duration(),start+(ref.duration||3600));
    const item={id:uid(),start,end,source:clone(ref)};if(!composing)item.rule={frequency:'once',anchor:day,interval:1,exceptions:[]};
    if(await applyItem(item,day)){selectSection(item,day);message(`${ref.name} added. Use Edit details for exact times or repeats.`);}
}
function canonical(item){return clone((composing?composition.sections:entries).find(r=>r.id===item.id)||item);}
function placeSection(el,start,end){
    el.style.top=yFor(start)+'px';
    const pixels=Math.max(0,yFor(end)-yFor(start));
    el.style.height=pixels+'px';
    el.classList.toggle('is-short',pixels<30);
}
function sectionElement(item,day){
    const el=node('div',undefined,'timeline-section');el.dataset.id=item.id;el.dataset.origin=item.origin||day;el.classList.toggle('is-selected',isSelected(item));if(!composing&&editor.recurring(item)&&repeatDisplay==='compact')el.classList.add('is-recurring');el.tabIndex=0;el.setAttribute('role','button');
    el.setAttribute('aria-label',`${item.source.name}, ${timeLabel(item.start)} to ${timeLabel(item.end)}. Enter to edit.`);
    placeSection(el,item.start,item.end);
    el.append(node('strong',item.source.name),node('small',`${timeLabel(item.start)}–${timeLabel(item.end)}${!composing&&editor.recurring(item)?' · ↻ '+item.rule.frequency:''}`));
    for(const insert of item.inserts||[])el.append(node('span',`◆ ${timeLabel(insert.at)} ${insert.source.name}`,'insert-marker'));
    for(const edge of ['top','bottom']){const original=canonical(item),offset=!composing&&item.origin!==day?86400:0;if((edge==='top'?item.start+offset!==original.start:item.end+offset!==original.end))continue;const handle=node('span',undefined,'resize-grip '+edge);handle.dataset.edge=edge;el.append(handle);}
    el.addEventListener('click',()=>{if(!suppressClick)selectSection(item,day);});
    el.addEventListener('dblclick',()=>{if(!suppressClick)openInspector(item,day);});
    el.addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();openInspector(item,day);}else if(e.key===' '){e.preventDefault();selectSection(item,day);}});
    el.addEventListener('pointerdown',e=>startDrag(e,el,item,day));return el;
}
function startDrag(event,el,fragment,day){
    if(event.button!==0||scopeProposal)return;
    selectSection(fragment,day);dragActive=true;
    const item=canonical(fragment),origin=fragment.origin||day,edge=event.target.closest('[data-edge]')?.dataset.edge;
    const originX=event.clientX,originY=event.clientY,column=el.parentElement,timeline=$('timeline');
    const initialSecond=secondFor(originY-column.getBoundingClientRect().top);
    const offset=origin===day?0:86400,length=item.end-item.start;
    let moved=false,targetDay=day,candidate=clone(item),last=event,frame;
    el.setPointerCapture(event.pointerId);
    function position(e){
        const delta=snap(secondFor(e.clientY-column.getBoundingClientRect().top)-initialSecond);
        if(edge==='top')candidate=editor.interval(item,Math.max(0,Math.min(item.end-1,86399,item.start+delta)),item.end);
        else if(edge==='bottom')candidate=editor.interval(item,item.start,Math.min(composing?duration():item.start+86400,Math.max(item.start+1,item.end+delta)));
        else{
            const start=Math.max(0,Math.min(composing?duration()-length:86399,item.start+delta));
            candidate=editor.interval(item,start,start+length,true);
        }
        placeSection(el,Math.max(0,candidate.start-offset),Math.min(duration(),candidate.end-offset));
        el.querySelector('small').textContent=`${timeLabel(candidate.start)}–${timeLabel(candidate.end)}${candidate.end>86400?' (+1 day)':''}`;message(`${item.source.name}: ${timeLabel(candidate.start)}–${timeLabel(candidate.end)}${candidate.end>86400?' (+1 day)':''}`);
    }
    const scroll=()=>{
        if(!moved)return;
        const bounds=timeline.getBoundingClientRect(),prior=timeline.scrollTop;
        if(last.clientY>bounds.bottom-45)timeline.scrollTop+=12;
        else if(last.clientY<bounds.top+45)timeline.scrollTop-=12;
        if(timeline.scrollTop!==prior)position(last);
        frame=requestAnimationFrame(scroll);
    };
    const move=e=>{
        if(e.pointerId!==event.pointerId)return;last=e;if(Math.hypot(e.clientX-originX,e.clientY-originY)<4&&!moved)return;
        e.preventDefault();if(!moved){moved=true;el.dataset.moved='1';el.classList.add('dragging');frame=requestAnimationFrame(scroll);}
        if(!composing&&!edge){
            // Pointer capture keeps the dragged element under the pointer; inspect the column below it.
            el.style.pointerEvents='none';const target=document.elementFromPoint(e.clientX,e.clientY)?.closest('.time-column');el.style.pointerEvents='';
            if(target&&target!==el.parentElement){targetDay=target.dataset.date;target.append(el);el.setPointerCapture(event.pointerId);}
        }
        position(e);
    };
    const finish=()=>{
        cancelAnimationFrame(frame);el.removeEventListener('pointermove',move);el.removeEventListener('pointerup',finish);el.removeEventListener('pointercancel',cancel);el.removeEventListener('lostpointercapture',cancel);document.removeEventListener('keydown',escape);
        if(el.hasPointerCapture(event.pointerId))el.releasePointerCapture(event.pointerId);
        dragActive=false;page.signal.removeEventListener('abort',cancel);
        if(!moved){if(renderPending)setTimeout(render,0);return;}
        suppressClick=true;setTimeout(()=>suppressClick=false,0);
        const targetOrigin=shift(origin,Math.round((dateObj(targetDay)-dateObj(day))/86400000));
        render();
        if(candidate.start===item.start&&candidate.end===item.end&&targetOrigin===origin)return;
        if(!composing&&item.rule.frequency!=='once'){
            scopeProposal={candidate,origin,day:targetOrigin};$('move-scope').value='occurrence';$('move-scope-summary').textContent=`${candidate.source.name} · ${origin}${origin!==targetOrigin?' → '+targetOrigin:''} · ${timeLabel(candidate.start)}–${timeLabel(candidate.end)}${candidate.end>86400?' (+1 day)':''}`;$('move-scope-error').textContent='';$('move-scope-dialog').showModal();
        }else{
            if(!composing)candidate.rule.anchor=targetOrigin;
            applyItem(candidate,targetOrigin,'series',origin);
        }
    };
    const cancel=()=>{suppressClick=true;setTimeout(()=>suppressClick=false,0);moved=false;finish();render();};
    const escape=e=>{if(e.key==='Escape')cancel();};
    el.addEventListener('pointermove',move);el.addEventListener('pointerup',finish);el.addEventListener('pointercancel',cancel);el.addEventListener('lostpointercapture',cancel);document.addEventListener('keydown',escape);page.signal.addEventListener('abort',cancel,{once:true});
}
function renderMonth(timeline){
    const grid=node('div',undefined,'month-grid'),first=selectedDate.slice(0,8)+'01',start=shift(first,-weekday(first));
    for(const label of ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'])grid.append(node('div',label,'month-weekday'));
    for(let i=0;i<42;i++){
        const day=shift(start,i),el=node('div',undefined,'month-day');el.tabIndex=0;el.append(node('b',dateObj(day).getUTCDate()));
        const rows=dayEntries(day).filter(visibleItem),dayEvents=events.filter(event=>event.date===day&&visibleEvent(event));
        const compact=repeatDisplay==='compact'?rows.filter(editor.recurring):[],shown=rows.filter(row=>!compact.includes(row));
        for(const row of shown.slice(0,3))el.append(node('span',timeLabel(row.start)+' '+row.source.name));
        if(compact.length)el.append(node('span',`↻ ${new Set(compact.map(row=>row.id)).size} recurring schedules`,'recurring-summary'));
        for(const event of dayEvents.slice(0,Math.max(1,3-shown.length)))el.append(eventLink(event));
        const extra=Math.max(0,shown.length-3)+Math.max(0,dayEvents.length-Math.max(1,3-shown.length));if(extra)el.append(node('span',`+${extra} more`));
        el.onclick=e=>{if(e.target.closest('a'))return;selectedDate=day;layout='Day';$('calendar-date').value=day;$('calendar-view').value='Day';loadEvents();render();};
        el.onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();el.click();}};
        el.ondragover=e=>{if(dragged)e.preventDefault();};el.ondrop=e=>{e.preventDefault();if(dragged)placeSource(dragged,day,9*3600);dragged=null;};grid.append(el);
    }timeline.append(grid);
}
function renderAgenda(timeline){
    const recurring=new Map();
    for(let i=0;i<7;i++){
        const day=shift(selectedDate,i),all=dayEntries(day),rows=all.filter(visibleItem);
        if(!all.length){const el=node('div',undefined,'agenda-row');el.append(node('b',day),node('span',fallbackLabel()+' · all day'));timeline.append(el);}
        for(const row of rows){
            if(repeatDisplay==='compact'&&editor.recurring(row)&&!isSelected(row)){if(!recurring.has(row.id))recurring.set(row.id,[]);recurring.get(row.id).push({row,day});continue;}
            const el=node('div',undefined,'agenda-row');el.append(node('b',day+' '+timeLabel(row.start)),node('span',row.source.name),button('Edit',()=>openInspector(row,day)));timeline.append(el);
        }
        for(const event of events.filter(e=>e.date===day&&visibleEvent(e))){
            if(repeatDisplay==='compact'&&event.recurring){const key='event:'+event.id;if(!recurring.has(key))recurring.set(key,[]);recurring.get(key).push({event,day});continue;}
            const el=node('div',undefined,'agenda-row');el.append(node('b',day+' '+timeLabel(event.second)),eventLink(event));timeline.append(el);
        }
    }
    for(const list of recurring.values()){
        const group=node('details',undefined,'agenda-series');group.append(node('summary',`↻ ${list[0].row?.source.name||list[0].event.name} · ${list.length} occurrences`));
        for(const {row,event,day} of list){const el=node('div',undefined,'agenda-row');el.append(node('b',day+' '+timeLabel(row?.start??event.second)),row?button('Edit occurrence',()=>openInspector(row,day)):eventLink(event));group.append(el);}timeline.append(group);
    }
}
function recurrenceFromForm(){
    const day=$('section-date').value,prior=editing.item?.rule,scope=$('edit-scope').value;
    const anchor=prior&&day===editing.formDate?prior.anchor:day;
    const d=dateObj(anchor),choice=$('repeat-monthly').value;
    const samePattern=prior&&choice===(prior.nth===-1?'last':prior.nth?'nth':'date')&&day===editing.formDate;
    return {...clone(prior||{}),starts_on:scope==='series'&&prior&&anchor!==prior.anchor?null:prior?.starts_on,frequency:$('repeat-frequency').value,anchor,until:$('repeat-until').value||null,
        interval:Number($('repeat-interval').value),weekdays:[...$('repeat-weekdays').querySelectorAll('input:checked')].map(el=>Number(el.value)),
        month_day:samePattern?prior.month_day:d.getUTCDate(),nth:samePattern?prior.nth:choice==='last'?-1:choice==='nth'?Math.floor((d.getUTCDate()-1)/7)+1:0,
        weekday:samePattern?prior.weekday:weekday(anchor),dates:$('repeat-dates').value.split(',').map(date=>date.trim()).filter(Boolean),exceptions:clone(prior?.exceptions||[])};
}
function openInspector(item,day,ref,start=0,proposed=false){if(!item&&ref?.kind==='block'&&!composing)start=0;const origin=item?.origin||day;if(item&&!proposed)item=canonical(item);day=origin;editing={item:clone(item),day,origin,formDate:day,ref:clone(ref||item.source)};const end=item?.end||(composing&&!composition.sections.length&&ref.kind!=='song'?duration():Math.min(duration(),start+(ref.duration||3600)));$('inspector-title').textContent=item?'Edit scheduled content':'Add to schedule';$('section-source').value=editing.ref.name;$('section-start').value=clock(item?.start??start);$('section-end').value=clock(end);$('section-end-day').value=end>=86400?'1':'0';$('section-time-error').textContent='';$('section-order').value=editing.ref.order||'default';$('placement-recurrence').hidden=composing;$('section-date').required=!composing;const rule=item?.rule||{frequency:'once',anchor:day,interval:1,weekdays:[weekday(day)]};$('section-date').value=day;$('repeat-frequency').value=rule.frequency;$('repeat-dates').value=(rule.dates||[]).join(', ');$('repeat-dates-label').hidden=rule.frequency!=='dates';$('repeat-interval').value=rule.interval||1;$('repeat-until').value=rule.until||'';$('repeat-weekdays').querySelectorAll('input').forEach(input=>input.checked=(rule.weekdays||[]).includes(Number(input.value)));$('repeat-monthly').value=rule.nth===-1?'last':rule.nth?'nth':'date';$('edit-scope-label').hidden=!item||rule.frequency==='once';$('edit-scope').value='occurrence';$('song-insert-label').hidden=!composing||!!item||editing.ref.kind!=='song';$('song-insert').checked=false;$('artist-group-label').hidden=editing.ref.kind!=='artist';$('artist-group').textContent=editing.ref.name;for(const id of ['delete-section','duplicate-section','split-section'])$(id).hidden=!item;$('section-inspector').showModal();}
async function applyItem(value,day,scope='series',origin=day,accept=()=>true){
    const list=composing?composition.sections:entries;
    const prior=list.find(r=>r.id===value.id);
    if(composing&&prior&&!value.inserts)value=editor.interval({...value,inserts:prior.inserts},value.start,value.end);
    const proposal=editor.edit(list,value,{composing,scope,origin,day});
    if(proposal.conflicts.length&&!confirm('Replace the occupied interval? Content before and after this interval will stay.'))return false;
    const lost=prior&&(prior.inserts||[]).length>(value.inserts||[]).length;
    if(lost&&!confirm('Remove the inserted songs outside the new section bounds? This can be undone.'))return false;
    const generation=editGeneration;
    if(!composing){
        validations++;if(saveButton)saveButton.disabled=true;
        try{
            const checked=await api('calendar-preview',{items:proposal.items});
            if(!accept()||page.signal.aborted)return false;
            if(generation!==editGeneration){message('The draft changed while checking this edit. Try again.',true);return false;}
            proposal.items=checked.items;
        }catch(error){
            if(!accept()||page.signal.aborted)return false;
            message(error.message,true);$('move-scope-error').textContent=error.message;$('section-time-error').textContent=error.message;return false;
        }finally{validations--;if(saveButton)saveButton.disabled=saving||validations>0;if(!validations&&dirty&&!saving)queueSave();}
    }
    if(!accept()||page.signal.aborted)return false;
    before();if(composing)composition.sections=proposal.items;else entries=proposal.items;selectedSection={id:proposal.value.id,origin:day,day};
    markDirty();render();return true;
}
$('section-form').onsubmit=async e=>{e.preventDefault();const context=editing,accept=()=>editing===context&&$('section-inspector').open;let start=seconds($('section-start').value),end=seconds($('section-end').value)+Number($('section-end-day').value)*86400;if(!(end>start&&end-start<=86400)){$('section-time-error').textContent='Choose an end after the start, no more than 24 hours later. Use Next day for overnight schedules.';return;}if(composing&&end>duration()){message('This section extends beyond the composition. Increase its duration first.',true);return;}const ref={...editing.ref,order:$('section-order').value};if($('song-insert').checked&&composing){const host=composition.sections.find(s=>s.start<=start&&start<s.end);if(!host){message('Drop the song inside a collection section to insert it.',true);return;}before();host.inserts=[...(host.inserts||[]),{id:uid(),at:start,source:ref}];markDirty();render();}else{let value={...editing.item,id:editing.item?.id||uid(),start,end,source:ref};if(composing&&editing.item)value={...editor.interval(editing.item,start,end,end-start===editing.item.end-editing.item.start),source:ref};if(!composing){value.rule=recurrenceFromForm();if(value.rule.frequency==='dates'&&!value.rule.dates.length){$('section-time-error').textContent='Enter at least one date.';return;}}if(!await applyItem(value,$('section-date').value,$('edit-scope').value,editing.origin||editing.day,accept))return;}$('section-inspector').close();};
$('delete-section').onclick=()=>{const list=composing?composition.sections:entries;const revised=editor.remove(list,editing.item.id,{composing,scope:$('edit-scope').value,origin:editing.origin});before();if(composing)composition.sections=revised;else entries=revised;markDirty();render();$('section-inspector').close();};
$('duplicate-section').onclick=async()=>{const context=editing,accept=()=>editing===context&&$('section-inspector').open;const prior=editing.item,length=prior.end-prior.start;const item=editor.interval(prior,prior.end,prior.end+length,true);item.id=uid();if(composing&&item.end>duration()){message('There is not enough time after this section. Choose a different start.',true);return;}if(!composing){item.rule={...item.rule,frequency:'once',anchor:editing.origin,until:null,starts_on:null,exceptions:[]};if(item.start>=86400){item.start-=86400;item.end-=86400;item.rule.anchor=shift(item.rule.anchor,1);}}if(await applyItem(item,item.rule?.anchor||editing.day,'series',editing.day,accept))$('section-inspector').close();};
$('split-section').onclick=()=>{const item=editing.item;if(item.end-item.start<2){message('This section is too short to split.',true);return;}let list=composing?composition.sections:entries;let splitItem=clone(item);if(!composing){const prepared=editor.edit(list,splitItem,{scope:$('edit-scope').value,origin:editing.origin,day:$('section-date').value});if(prepared.conflicts.length&&!confirm('Replace the occupied interval before splitting?'))return;list=prepared.items;splitItem=prepared.value;}const halves=editor.split(splitItem,Math.floor((splitItem.start+splitItem.end)/2));if(!composing)for(const half of halves){if(half.start>=86400){if(half.rule.frequency!=='once'){message('Choose This occurrence to split the part after midnight.',true);return;}half.start-=86400;half.end-=86400;half.rule.anchor=shift(half.rule.anchor,1);half.rule.until=null;half.rule.starts_on=null;}}before();list=list.filter(r=>r.id!==splitItem.id).concat(halves);if(composing)composition.sections=list;else entries=list;markDirty();render();$('section-inspector').close();};
$('edit-scope').onchange=()=>{const series=$('edit-scope').value==='series';$('section-date').value=series?editing.item.rule.anchor:editing.day;editing.formDate=$('section-date').value;};
$('repeat-frequency').onchange=()=>{$('repeat-dates-label').hidden=$('repeat-frequency').value!=='dates';};
$('preview-recurrence').onclick=async()=>{try{const result=await api('recurrence',recurrenceFromForm());$('recurrence-preview').textContent=result.dates.join(' · ');}catch(error){message(error.message,true);}};
async function loadSources(append=false){searchController?.abort();searchController=new AbortController();if(!append)sourcePage=1;const results=$('source-results');try{let data;if($('library-filter').value!=='all')data={items:($('library-filter').value==='recent'?recent:favorites).filter(s=>s.kind===libraryKind&&s.name.toLowerCase().includes($('source-search').value.toLowerCase())),more:false};else{const response=await fetch(root.dataset.api+'sources?'+new URLSearchParams({kind:libraryKind,q:$('source-search').value,page:sourcePage}),{signal:searchController.signal});data=await response.json();if(!response.ok)throw Error(data.error);}results.replaceChildren();for(const item of data.items){const card=node('div',undefined,'source-card');card.draggable=true;card.setAttribute('role','listitem');card.append(node('span',{block:'▤',show:'◉',category:'▦',playlist:'≋',artist:'♬',album:'▣',song:'♪'}[item.kind],'source-art'));if(item.artwork){const art=document.createElement('img');art.src=item.artwork;art.alt='';art.className='source-art';card.firstChild.replaceWith(art);}const copy=node('div');copy.append(node('strong',item.name),node('small',item.kind+(item.count!==undefined?' · '+item.count+' songs':['show','block'].includes(item.kind)?' · '+Math.round(item.duration/60)+' min':'')));const actions=node('div',undefined,'source-actions');const add=button('+',()=>chooseSource(item));add.setAttribute('aria-label','Add '+item.name);const star=button(favorites.some(f=>f.kind===item.kind&&f.id===item.id)?'★':'☆',()=>{const index=favorites.findIndex(f=>f.kind===item.kind&&f.id===item.id);if(index>=0)favorites.splice(index,1);else favorites.push(item);localStorage.setItem(localKey+':favorites',JSON.stringify(favorites));loadSources();});star.setAttribute('aria-label','Favorite '+item.name);actions.append(add,star);if(item.identifier&&item.kind==='song'){const preview=button('▶',()=>previewSong(item));preview.setAttribute('aria-label','Preview '+item.name);actions.append(preview);}card.append(copy,actions);card.ondragstart=e=>{dragged=item;e.dataTransfer.setData('application/json',JSON.stringify(item));};card.ondragend=()=>{dragged=null;clearTimeout(hoverTimer);hoverHour=null;};results.append(card);}if(!data.items.length)results.textContent='No sources found. Try another search or tab.';$('source-more').hidden=!data.more;$('source-prev').hidden=sourcePage<=1;}catch(error){if(error.name!=='AbortError')results.textContent='Unable to load sources. Change your search to retry.';}}
let previewAudio;
function previewSong(item){previewAudio?.pause();previewAudio=new Audio(`/admin/stations/${root.dataset.station}/media/${item.identifier}/audition`);window.FreoMonitor?.stop();previewAudio.play().catch(()=>message('Audio preview unavailable.',true));}
function chooseSource(item){recent=[item,...recent.filter(r=>r.kind!==item.kind||r.id!==item.id)].slice(0,30);localStorage.setItem(localKey+':recent',JSON.stringify(recent));if(view==='simple'){before();simple=clone(item);markDirty();render();}else openInspector(null,selectedDate,item,composing?0:9*3600);}
const types=[['block','Blocks'],['show','Shows'],['category','Categories'],['playlist','Playlists'],['artist','Artists'],['album','Albums'],['song','Songs']];for(const [kind,label] of types){if((kind==='block'&&!['calendar','simple'].includes(view))||(view==='shows'&&kind==='show'))continue;const tab=button(label,()=>{libraryKind=kind;[...$('source-tabs').children].forEach(t=>t.setAttribute('aria-selected',String(t===tab)));loadSources();});tab.setAttribute('role','tab');tab.setAttribute('aria-selected',String(kind===libraryKind));$('source-tabs').append(tab);}
$('source-search').oninput=()=>{clearTimeout(searchTimer);searchTimer=setTimeout(()=>loadSources(),200);};$('library-filter').onchange=()=>loadSources();$('source-more').onclick=()=>{sourcePage++;loadSources(true);};$('source-prev').onclick=()=>{sourcePage=Math.max(1,sourcePage-1);loadSources(true);};
function resetHistory(){dirty=false;undo=[];redo=[];editGeneration++;localStorage.removeItem(localKey+':draft');$('save-state').textContent='Saved';$('undo-edit').disabled=true;$('redo-edit').disabled=true;}
function syncComposition(){if(!composing)return;$('composition-name').value=composition.name;$('composition-description').value=composition.description;if(view==='shows'){$('duration-minutes').value=composition.duration/60;$('duration-slider').step=composition.duration%60?1:60;$('duration-slider').value=composition.duration;const presets=$('show-duration');presets.querySelector('[data-custom]')?.remove();if(![...presets.options].some(o=>Number(o.value)===composition.duration)){const option=new Option(`${composition.duration/60} minutes`,composition.duration);option.dataset.custom='true';presets.append(option);}presets.value=composition.duration;}}
let compositionPage=1;async function loadCompositions(append=false){if(!composing)return;if(!append)compositionPage=1;const result=await api('compositions?'+new URLSearchParams({kind:view==='shows'?'SHOW':'BLOCK',q:$('composition-search').value,page:compositionPage}));compositions=append?[...compositions,...result.items]:result.items;if(composition.id&&!compositions.some(c=>c.id===composition.id))compositions.push(clone(composition));$('compositions-more').hidden=!result.more;const select=$('composition-select');select.replaceChildren(new Option('New '+(view==='shows'?'Show':'Block'),''));for(const item of compositions)select.append(new Option(item.name,item.id));select.value=composition.id||'';renderSavedBlocks();}
if(composing){let savedSearchTimer;$('composition-search').oninput=()=>{clearTimeout(savedSearchTimer);savedSearchTimer=setTimeout(()=>loadCompositions().catch(e=>message(e.message,true)),200);};$('compositions-more').onclick=()=>{compositionPage++;loadCompositions(true).catch(e=>message(e.message,true));};$('apply-composition').onclick=async()=>{if(dirty||!composition.id){message('Save this composition first.',true);return;}try{const preview=await api('apply-revision-preview',{id:composition.id,version:composition.revision});if(!confirm(preview.message))return;const result=await api('apply-revision',{id:composition.id,version:composition.revision,effective_on:preview.effective_on,revision:baseRevision});baseRevision=result.revision;state.revision=result.revision;message(preview.message);}catch(error){message(error.message,true);}};$('composition-select').onchange=()=>openComposition($('composition-select').value);$('new-composition').onclick=()=>openComposition('');$('duplicate-composition').onclick=()=>{before();delete composition.id;delete composition.revision;composition.name+=' copy';localStorage.removeItem(localKey+':opened');syncComposition();markDirty();render();};for(const id of ['composition-name','composition-description'])$(id).oninput=()=>{before();composition[id==='composition-name'?'name':'description']=$(id).value;markDirty();};$('calendar-controls').hidden=true;}
function renderSavedBlocks(){
    if(view!=='blocks')return;
    const list=$('saved-blocks');list.replaceChildren();
    for(const item of compositions){
        const card=button('',()=>openComposition(item.id));card.className='saved-block-card';
        card.setAttribute('aria-pressed',String(item.id===composition.id));
        card.append(node('strong',item.name),node('span',`24 hours · ${item.sections.length} sections · v${item.revision}`));list.append(card);
    }
    if(!compositions.length)list.append(node('p','Your saved Blocks will appear here.'));
}
let compositionRequest=0;
async function openComposition(id,ask=true){
    if(saving)return;
    if(ask&&dirty&&!confirm('Discard unsaved content edits and open another item? Pending day assignments will be kept.')){$('composition-select').value=composition.id||'';return;}
    const generation=editGeneration,request=++compositionRequest;
    try{
        const loaded=id?await api('composition?id='+encodeURIComponent(id)):{kind:view==='blocks'?'BLOCK':'SHOW',name:'',description:'',duration:view==='blocks'?86400:3600,sections:[]};
        if(request!==compositionRequest||page.signal.aborted)return;
        if(generation!==editGeneration){message('Your edits changed while loading. Save them before opening another item.',true);return;}
        if(loaded.kind!==(view==='blocks'?'BLOCK':'SHOW'))throw Error('This item belongs to a different workspace.');
        composition=loaded;selectedSection=null;
        if(loaded.id){compositions=compositions.filter(item=>item.id!==loaded.id).concat(clone(loaded));if(![...$('composition-select').options].some(option=>Number(option.value)===loaded.id))$('composition-select').append(new Option(loaded.name,loaded.id));}
        const pendingAssignments=!same(assignments,state.assignments);resetHistory();if(pendingAssignments)markDirty();
        if(id)localStorage.setItem(localKey+':opened',id);else localStorage.removeItem(localKey+':opened');
        syncComposition();$('composition-select').value=composition.id||'';renderSavedBlocks();render();
        message(id?`${composition.name} loaded. Existing scheduled uses retain their saved version.`:'New '+(view==='blocks'?'Block':'Show')+'. Add a name and content.');
    }catch(error){message(error.message,true);$('composition-select').value=composition.id||'';}
}
function updateBlockSummary(){
    if(view!=='blocks')return;
    $('block-content-status').textContent=composition.id?`${dirty?'Unsaved edits':'Saved'} · ${composition.name} · v${composition.revision}`:'New Block · not saved';
    const covered=composition.sections.reduce((total,item)=>total+item.end-item.start,0),gap=86400-covered;
    $('block-coverage-status').textContent=gap?`${Math.round(covered/60)} min filled · ${Math.round(gap/60)} min ${state.fallback?'use fallback':'without fallback'}`:'Full day covered';
    const uses=assignments.filter(item=>item.pattern.some(ref=>ref.id===composition.id));
    const today=new Intl.DateTimeFormat('en-CA',{timeZone:state.timezone,year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
    const active=assigned(today).find(item=>item.source?.id===composition.id);
    $('block-assignment-status').textContent=active?`Assigned to today · v${active.source.version}`:uses.length?`${uses.length} day assignment${uses.length===1?'':'s'} · not today`:'Not assigned to any days';
    $('block-assignment-status').classList.toggle('needs-assignment',!uses.length);
}
function syncBlockTiming(item){
    if(view!=='blocks')return;
    for(const id of ['block-section-start','block-section-end','block-section-midnight','block-start-slider','block-end-slider','block-apply-times'])$(id).disabled=!item;
    $('block-section-name').textContent=item?.source.name||'Section timing';$('block-time-error').textContent='';
    if(!item){$('block-section-duration').textContent='Select a section on the timeline';return;}
    $('block-section-start').value=clock(item.start);$('block-section-end').value=clock(item.end);$('block-section-midnight').checked=item.end===86400;
    syncTimingSliders();
}
function blockTimes(){return {start:seconds($('block-section-start').value),end:$('block-section-midnight').checked?86400:seconds($('block-section-end').value)};}
function syncTimingSliders(){
    const {start,end}=blockTimes();
    for(const [id,value] of [['block-start-slider',start],['block-end-slider',end]]){const slider=$(id);slider.step=value%60?1:60;slider.value=Number.isFinite(value)?value:0;slider.setAttribute('aria-valuetext',timeLabel(value));}
    $('block-section-duration').textContent=Number.isFinite(start)&&end>start?`${timeLabel(start)}–${timeLabel(end)} · ${Math.round((end-start)/60*100)/100} minutes`:'End must be after start';
}
async function applyBlockTimes(){
    const item=composition.sections.find(row=>row.id===selectedSection?.id);if(!item)return;
    const {start,end}=blockTimes();
    if(!Number.isInteger(start)||!Number.isInteger(end)||start<0||end>86400||end<=start){$('block-time-error').textContent='Choose an end after the start, within this 24-hour Block.';return;}
    if(start===item.start&&end===item.end)return;
    if(!await applyItem(editor.interval(item,start,end,end-start===item.end-item.start),selectedDate))syncBlockTiming(item);
}
if(view==='blocks'){
    $('block-apply-times').onclick=applyBlockTimes;
    $('block-section-start').oninput=syncTimingSliders;
    $('block-section-end').oninput=()=>{$('block-section-midnight').checked=false;syncTimingSliders();};
    $('block-section-midnight').onchange=()=>{if($('block-section-midnight').checked)$('block-section-end').value='00:00:00';syncTimingSliders();};
    for(const [id,edge] of [['block-start-slider','start'],['block-end-slider','end']]){
        $(id).oninput=e=>{
            const old=blockTimes();let value=Number(e.target.value);
            value=edge==='start'?Math.max(0,Math.min(old.end-1,value)):Math.min(86400,Math.max(old.start+1,value));
            $('block-section-'+edge).value=clock(value);
            if(edge==='end')$('block-section-midnight').checked=value===86400;
            syncTimingSliders();
        };
        $(id).onchange=applyBlockTimes;
    }
}

function setDuration(value){value=Number(value);if(!Number.isInteger(value)||value<900||value>86400){syncComposition();message('Enter a duration from 15 to 1,440 minutes.',true);return;}const crossed=composition.sections.some(s=>s.end>value);if(crossed&&!confirm('Trim sections beyond the new Show end? This can be undone.')){syncComposition();return;}before();composition.duration=value;composition.sections=composition.sections.filter(s=>s.start<value).map(s=>({...s,end:Math.min(s.end,value),inserts:(s.inserts||[]).filter(i=>i.at<value)}));syncComposition();markDirty();render();}
if(view==='shows'){$('show-duration').onchange=e=>setDuration(e.target.value);$('duration-minutes').onchange=e=>setDuration(Number(e.target.value)*60);$('duration-slider').onchange=e=>setDuration(e.target.value);$('duration-slider').oninput=e=>{$('duration-minutes').value=Number(e.target.value)/60;};}
if(view==='simple'){const stage=$('simple-selection');stage.ondragover=e=>e.preventDefault();stage.ondrop=e=>{e.preventDefault();if(dragged)chooseSource(dragged);dragged=null;};}
function documentKey(){return view==='calendar'?'calendar':view==='simple'?'simple':'assignments';}
function adoptState(latest){
    if(latest.revision<baseRevision)return;
    const key=documentKey(),changed=!same(state[key],latest[key]);
    const editingDetails=$('section-inspector').open||scopeProposal||dragActive||validations||$('mode-confirm').open;
    if(!saving&&!editingDetails&&!saveConflict&&(!dirty||!changed)){
        if(!dirty){
            if(view==='calendar')entries=clone(latest.calendar);
            if(view==='simple')simple=clone(latest.simple);
            if(view==='blocks')assignments=clone(latest.assignments);
            if(changed){undo=[];redo=[];$('undo-edit').disabled=$('redo-edit').disabled=true;}
        }
        state=latest;baseRevision=latest.revision;
        if(changed&&!dirty)render();
    }else{
        for(const key of ['mode','activated','held','transition','playing_fallback','fallback','broadcast'])state[key]=latest[key];
    }
    updateStatus();
}
function showConflict(error,base){
    saveConflict={base:clone(base),latest:error.latest};saveBlocked=true;
    $('save-conflict').hidden=false;$('retry-save').hidden=true;$('save-state').textContent='Not saved';
    message(error.message+' Your edits are kept here.',true);rememberDraft();
}
function save(){
    clearTimeout(saveTimer);saveTimer=null;
    if(savePromise)return savePromise;
    if(!dirty||validations||saveBlocked)return Promise.resolve(!dirty);
    savePromise=performSave().finally(()=>{savePromise=null;});
    return savePromise;
}
async function performSave(){
    saving=true;if(saveButton)saveButton.disabled=true;$('save-state').textContent='Saving…';$('retry-save').hidden=true;
    const sent=snapshot(),generation=editGeneration,base=clone({calendar:state.calendar,assignments:state.assignments,simple:state.simple});
    const controls=['composition-select','new-composition','duplicate-composition','apply-composition','activate-mode','assign-block','block-to-calendar'];
    for(const id of controls)if($(id))$(id).disabled=true;
    let retry=false;
    try{
        let result;
        if(composing){
            result=await api(view==='blocks'?'block-workspace':'composition',view==='blocks'?{composition:sent.composition,items:sent.assignments,revision:baseRevision,base:base.assignments}:sent.composition);
            const saved=view==='blocks'?result.composition:result;
            if(editGeneration===generation)composition=saved;
            else{composition.id=saved.id;composition.revision=saved.revision;}
            for(const stack of [undo,redo])for(const snapshot of stack){snapshot.composition.id=saved.id;snapshot.composition.revision=saved.revision;}
            if(view==='blocks'){
                baseRevision=result.revision;
                try{assignments=editor.mergeItems(sent.assignments,assignments,result.items);}
                catch(error){showConflict(Object.assign(error,{latest:{...state,revision:result.revision,assignments:result.items}}),{...base,assignments:sent.assignments});return false;}
                for(const stack of [undo,redo])for(const item of stack)item.assignments=editor.mergeItems(sent.assignments,item.assignments,result.items,true);
                state.assignments=clone(result.items);
            }
            compositions=compositions.filter(c=>c.id!==saved.id).concat(saved);syncComposition();
        }else{
            result=await api(view==='simple'?'simple':'calendar',view==='simple'?{revision:baseRevision,source:sent.simple,base:base.simple}:{revision:baseRevision,items:sent.entries,base:base.calendar});
            baseRevision=result.revision;
            if(view==='calendar'){
                try{entries=editor.mergeItems(sent.entries,entries,result.items);}
                catch(error){showConflict(Object.assign(error,{latest:{...state,revision:result.revision,calendar:result.items}}),{...base,calendar:sent.entries});return false;}
                // Rebase Undo/Redo as well, so an undo cannot erase someone else's unrelated entry.
                for(const stack of [undo,redo])for(const item of stack)item.entries=editor.mergeItems(sent.entries,item.entries,result.items,true);
                state.calendar=clone(result.items);
            }else{state.simple=clone(result.source);if(editGeneration===generation)simple=clone(result.source);}
        }
        state.revision=baseRevision;retryDelay=1000;if(composing&&composition.id)localStorage.setItem(localKey+':opened',composition.id);
        if(editGeneration===generation){
            dirty=false;localStorage.removeItem(localKey+':draft');$('save-state').textContent='Saved';
            if(!autosave){undo=[];redo=[];$('undo-edit').disabled=$('redo-edit').disabled=true;}
        }else{rememberDraft();$('save-state').textContent=autosave?'Saving…':'Unsaved changes';}
        message(autosave?(dirty?'Saving latest changes…':'Changes saved automatically.'):dirty?'Saved submitted changes. Newer edits still need saving.':view==='shows'?'Show saved. Add it to Calendar, a Block, or Simple.':view==='blocks'?'Block saved. Assign days for Blocks mode, add it to Calendar, or select it in Simple.':'Saved.');
        render();if(composing)await loadCompositions();return true;
    }catch(error){
        if(error.conflict)showConflict(error,base);
        else{
            retry=autosave&&(error.retryable||!error.status);saveBlocked=!retry;
            $('save-state').textContent=retry?'Not saved · retrying…':'Not saved';$('retry-save').hidden=false;
            message(error.message||'Could not save. Your edits are kept here.',true);rememberDraft();
        }
        return false;
    }finally{
        saving=false;if(saveButton)saveButton.disabled=validations>0;for(const id of controls)if($(id))$(id).disabled=false;updateStatus();
        if(dirty&&autosave&&!saveBlocked){queueSave(retry?retryDelay:100);if(retry)retryDelay=Math.min(retryDelay*2,15000);}
    }
}
if(saveButton)saveButton.onclick=()=>{saveBlocked=false;save();};
$('retry-save').onclick=()=>{saveBlocked=false;save();};
async function resolveConflict(keep){
    if(!saveConflict||saving)return;
    try{
        const latest=await api('state'),prior=saveConflict.base;
        if(keep&&view!=='simple'){
            const key=view==='calendar'?'entries':'assignments',document=view==='calendar'?'calendar':'assignments';
            for(const stack of [undo,redo])for(const item of stack)item[key]=editor.mergeItems(prior[document],item[key],latest[document],true);
        }
        if(view==='calendar')entries=keep?editor.mergeItems(prior.calendar,entries,latest.calendar,true):clone(latest.calendar);
        if(view==='blocks')assignments=keep?editor.mergeItems(prior.assignments,assignments,latest.assignments,true):clone(latest.assignments);
        if(view==='simple'&&!keep)simple=clone(latest.simple);
        state=latest;baseRevision=latest.revision;saveConflict=null;saveBlocked=false;$('save-conflict').hidden=true;
        if(keep||composing){markDirty();await save();}else{resetHistory();render();message('Latest saved schedule loaded.');}
    }catch(error){message(error.message,true);}
}
$('use-latest-schedule').onclick=()=>resolveConflict(false);$('keep-schedule-edits').onclick=()=>resolveConflict(true);
async function flushCalendar(){
    clearTimeout(saveTimer);
    // A drag's preview validation may still be returning when navigation begins.
    while(validations)await new Promise(resolve=>setTimeout(resolve,30));
    while(dirty&&!saveBlocked){if(!await save())break;}
    return !dirty;
}
if(autosave)page.beforeLeave=flushCalendar;
else if(composing)page.beforeLeave=()=>!dirty||confirm('Leave without saving these edits? A recovery draft will be kept in this browser.');

if(view!=='simple'){
    $('edit-selected-section').onclick=()=>{const item=selectedSection&&(composing?composition.sections:entries).find(row=>row.id===selectedSection.id);if(item)openInspector({...item,origin:selectedSection.origin},selectedSection.day);};
    $('clear-selected-section').onclick=()=>{selectedSection=null;render();};
    const cancelScope=()=>{scopeProposal=null;$('move-scope-dialog').close();render();};
    $('cancel-move-scope').onclick=cancelScope;$('move-scope-dialog').oncancel=e=>{e.preventDefault();cancelScope();};
    $('apply-move-scope').onclick=async()=>{
        if(!scopeProposal)return;const proposal=scopeProposal,scope=$('move-scope').value,value=clone(proposal.candidate);$('apply-move-scope').disabled=true;
        try{value.rule=editor.movedRule(value.rule,proposal.origin,proposal.day,scope);if(await applyItem(value,proposal.day,scope,proposal.origin,()=>scopeProposal===proposal)){scopeProposal=null;$('move-scope-dialog').close();message(autosave?'Schedule updated. Saving automatically…':'Schedule updated in draft. Save to publish.');}}
        finally{$('apply-move-scope').disabled=false;}
    };
    $('section-start').oninput=$('section-end').oninput=()=>{if(seconds($('section-end').value)<=seconds($('section-start').value))$('section-end-day').value='1';};
}
if(view==='calendar'){
    $('focus-calendar').onclick=()=>{const focused=root.classList.toggle('calendar-focused');$('focus-calendar').setAttribute('aria-pressed',String(focused));$('focus-calendar').textContent=focused?'Show library':'Expand calendar';render();$('calendar-controls').scrollIntoView({block:'start',behavior:'instant'});};
    $('recurring-display').value=repeatDisplay;
    $('recurring-display').onchange=e=>{repeatDisplay=e.target.value;try{localStorage.setItem(localKey+':recurring',repeatDisplay);}catch{}render();};
    $('schedule-search').oninput=e=>{filterText=e.target.value.trim().toLocaleLowerCase();render();};
    $('schedule-kind').onchange=e=>{filterKind=e.target.value;render();};
    $('hidden-schedules').onclick=()=>{repeatDisplay='all';filterText=filterKind='';$('recurring-display').value='all';$('schedule-search').value='';$('schedule-kind').value='';render();};
}

if(!composing&&view!=='simple'){$('calendar-date').value=selectedDate;$('calendar-view').value=layout;$('calendar-date').onchange=e=>{selectedDate=e.target.value;loadEvents();render();};$('calendar-view').onchange=e=>{layout=e.target.value;loadEvents();render();};for(const [id,direction] of [['previous-date',-1],['next-date',1]])$(id).onclick=()=>{if(layout==='Month'){const d=dateObj(selectedDate);selectedDate=iso(new Date(Date.UTC(d.getUTCFullYear(),d.getUTCMonth()+direction,1,12)));}else selectedDate=shift(selectedDate,direction*(layout==='Day'?1:7));$('calendar-date').value=selectedDate;loadEvents();render();};$('today-date').onclick=()=>{selectedDate=new Intl.DateTimeFormat('en-CA',{timeZone:state.timezone,year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());$('calendar-date').value=selectedDate;loadEvents();render();};}
if($('accordion-toggle'))$('accordion-toggle').onclick=()=>{accordion=!accordion;$('accordion-toggle').setAttribute('aria-pressed',String(accordion));render();};
function eventLink(event){const a=node('a','◆ '+timeLabel(event.second)+' '+event.name,'calendar-event');a.href=`/admin/stations/${root.dataset.station}/events/${event.id}`;return a;}
async function loadEvents(){
    if(view!=='calendar')return;
    const request=++eventRequest;
    const first=layout==='Month'?shift(selectedDate.slice(0,8)+'01',-weekday(selectedDate.slice(0,8)+'01')):layout==='Week'?shift(selectedDate,-weekday(selectedDate)):selectedDate;
    events=[];
    try{const result=await api('events?'+new URLSearchParams({date:first,days:layout==='Month'?42:layout==='Day'?1:7}));if(request!==eventRequest)return;events=result.items;render();}catch(error){if(request===eventRequest)message(error.message,true);}
}
let copiedSection=null;
root.addEventListener('keydown',e=>{if(/INPUT|TEXTAREA|SELECT/.test(e.target.tagName))return;const block=e.target.closest('.timeline-section');if((e.ctrlKey||e.metaKey)&&e.key==='c'&&block){const list=composing?composition.sections:entries;copiedSection=clone(list.find(r=>r.id===block.dataset.id));e.preventDefault();message('Section copied. Navigate to a day and paste.');}if((e.ctrlKey||e.metaKey)&&e.key==='v'&&copiedSection){e.preventDefault();const copy=clone(copiedSection);copy.id=uid();if(!composing)copy.rule={...copy.rule,frequency:'once',anchor:selectedDate,until:null,starts_on:null,exceptions:[]};applyItem(copy,selectedDate);}});
let transitionId;
if($('activate-mode'))$('activate-mode').onclick=async()=>{
    if(autosave&&!await flushCalendar())return;
    if(dirty){message('Save your changes before activating this mode.',true);return;}
    try{
        adoptState(await api('state'));
        const preview=await api('transition-preview',{mode:view.toUpperCase(),simple});
        $('mode-confirm-title').textContent=state.mode===view.toUpperCase()?'Change what Simple plays?':`Switch from ${state.mode} to ${view.toUpperCase()}?`;
        $('mode-confirm-detail').textContent=`Current mode: ${state.mode}. New mode: ${view.toUpperCase()}. This also interrupts any current Event or live audio.`;
        $('mode-confirm-play').textContent=preview.message;
        $('mode-assign-block').hidden=!(view==='blocks'&&preview.code==='unassigned'&&composition.id);
        $('confirm-mode').disabled=!preview.playable;transitionId={id:uid(),current:state.mode,mode:view.toUpperCase(),revision:baseRevision,simple:clone(simple)};$('mode-confirm').showModal();
    }catch(error){message(error.message,true);}
};
$('mode-assign-block').onclick=()=>{$('mode-confirm').close();$('assign-block')?.click();};
$('cancel-mode').onclick=()=>$('mode-confirm').close();
$('confirm-mode').onclick=async()=>{const b=$('confirm-mode');b.disabled=true;try{await api('transition',transitionId);$('mode-confirm').close();adoptState(await api('state'));message('Switch requested. Waiting for the playback engine.');}catch(error){message(error.message,true);b.disabled=false;}};
function renderPattern(){const list=$('assign-pattern');list.replaceChildren();pattern.forEach((ref,index)=>{const chip=node('span',undefined,'pattern-chip');chip.append(node('span',`${index+1}. ${ref.name}`),button('←',()=>{if(index>0)[pattern[index-1],pattern[index]]=[pattern[index],pattern[index-1]];renderPattern();}),button('×',()=>{pattern.splice(index,1);renderPattern();}));list.append(chip);});}
if(view==='blocks'){
    let assignTimer,assignmentDraftId;
    $('assign-search').oninput=()=>{clearTimeout(assignTimer);assignTimer=setTimeout(async()=>{try{const data=await api('sources?'+new URLSearchParams({kind:'block',q:$('assign-search').value}));$('assign-options').replaceChildren();for(const item of data.items){const option=new Option(item.name,item.id);option.dataset.version=item.version;$('assign-options').append(option);}}catch(error){message(error.message,true);}},200);};
    $('assign-block').onclick=async()=>{
        if(dirty&&!await save())return;
        if(!composition.id){message('Name your Block and add content, then save it before assigning days.',true);return;}
        assignmentDraftId=uid();pattern=[{kind:'block',id:composition.id,version:composition.revision,name:composition.name}];
        $('assign-options').replaceChildren();for(const item of compositions){const option=new Option(item.name,item.id);option.dataset.version=item.revision;$('assign-options').append(option);}
        $('assign-start').value=selectedDate;$('assign-end').value='';$('assign-error').textContent='';
        $('assign-weekdays').querySelectorAll('input').forEach(el=>el.checked=Number(el.value)===weekday(selectedDate));
        updateAssignmentFields();renderPattern();$('assign-dialog').showModal();
    };
    $('assign-frequency').onchange=updateAssignmentFields;
    $('add-pattern-block').onclick=()=>{const option=$('assign-options').selectedOptions[0];if(option)pattern.push({kind:'block',id:Number(option.value),version:Number(option.dataset.version),name:option.textContent});renderPattern();};
    $('assign-form').onsubmit=async e=>{
        e.preventDefault();if(!pattern.length){$('assign-error').textContent='Add at least one Block to the pattern.';return;}
        const frequency=$('assign-frequency').value,day=$('assign-start').value;
        const weekdays=[...$('assign-weekdays').querySelectorAll('input:checked')].map(i=>Number(i.value));
        const dates=$('assign-dates').value.split(',').map(s=>s.trim()).filter(Boolean);
        if(frequency==='weekly'&&!weekdays.length){$('assign-error').textContent='Select at least one weekday.';return;}
        if(frequency==='dates'&&!dates.length){$('assign-error').textContent='Enter at least one date.';return;}
        const candidate={id:assignmentDraftId,pattern:clone(pattern),rule:{frequency,anchor:day,until:frequency==='once'?null:$('assign-end').value||null,interval:1,weekdays,dates:frequency==='dates'?dates:[],exceptions:[]}};
        const submit=e.submitter;submit.disabled=true;$('assign-error').textContent='';
        try{
            const result=await api('assignments',{revision:baseRevision,base:clone(state.assignments),items:[...assignments.filter(item=>item.id!==candidate.id),candidate]});
            assignments=clone(result.items);state.assignments=clone(result.items);baseRevision=state.revision=result.revision;
            selectedDate=day;resetHistory();$('assign-dialog').close();render();renderAssignments();
            message('Assignment saved. Use Blocks to activate these day assignments.');
        }catch(error){$('assign-error').textContent=error.message;}
        finally{submit.disabled=false;}
    };
    $('block-dates').onclick=()=>{if($('assignment-list').hidden)renderAssignments();else $('assignment-list').hidden=true;};
    $('block-to-calendar').onclick=async()=>{
        if(dirty&&!await save())return;
        if(!composition.id){message('Save your Block before adding it to Calendar.',true);return;}
        location.href=`/admin/stations/${root.dataset.station}/schedule-studio/calendar?view=day&date=${selectedDate}&block=${composition.id}`;
    };
    $('block-zoom').oninput=e=>{
        const timeline=$('timeline'),second=secondFor(timeline.scrollTop);
        blockHourHeight=Number(e.target.value);accordion=false;$('accordion-toggle').setAttribute('aria-pressed','false');
        render();timeline.scrollTop=yFor(second);
    };
}
function updateAssignmentFields(){
    const frequency=$('assign-frequency').value;
    $('assign-weekdays').hidden=frequency!=='weekly';$('assign-dates-label').hidden=frequency!=='dates';
    $('assign-end').disabled=frequency==='once';
}
function renderAssignments(){const list=$('assignment-list');list.replaceChildren();list.hidden=false;list.append(node('h3','Block assignments'));const browse=document.createElement('input');browse.type='date';browse.value=selectedDate;browse.setAttribute('aria-label','Preview Block assignments from date');browse.onchange=()=>{selectedDate=browse.value;renderAssignments();};list.append(browse);for(const row of assignments){const el=node('article');el.append(node('b',row.pattern.map(p=>`${p.name} (revision ${p.version})`).join(' → ')),node('p',`${row.rule.frequency} from ${row.rule.anchor}${row.rule.until?' until '+row.rule.until:''}`),button('Remove',()=>{before();assignments=assignments.filter(a=>a.id!==row.id);markDirty();renderAssignments();}));list.append(el);}const grid=node('div',undefined,'month-grid');for(let i=0;i<28;i++){const day=shift(selectedDate,i),el=node('div',undefined,'month-day');el.append(node('b',day.slice(5)));const rows=assigned(day);for(const row of rows)el.append(node('span',row.source.name));if(!rows.length)el.append(node('span',fallbackLabel()));grid.append(el);}list.append(grid);}
page.listen(window,'beforeunload',e=>{if(dirty){e.preventDefault();e.returnValue='';}});
page.cleanup(()=>{searchController?.abort();clearTimeout(searchTimer);clearTimeout(hoverTimer);clearTimeout(saveTimer);previewAudio?.pause();});
async function refreshState(){
    if(refreshing||saving||page.signal.aborted)return;refreshing=true;
    try{adoptState(await api('state'));}catch{}finally{refreshing=false;}
}
page.interval(refreshState,4000);
page.listen(window,'online',()=>{if(autosave&&dirty&&!saveConflict){saveBlocked=false;queueSave(0);}refreshState();});
async function init(){
    updateStatus();syncComposition();render();await Promise.all([loadSources(),loadCompositions(),loadEvents()]);
    if(composing&&!dirty){const opened=localStorage.getItem(localKey+':opened');if(opened)await openComposition(opened,false);}
    if(view==='calendar'&&/^\d+$/.test(requested.get('block')||'')){
        try{const block=await api('composition?id='+requested.get('block'));if(block.kind!=='BLOCK')throw Error('Choose a saved Block.');openInspector(null,selectedDate,{kind:'block',id:block.id,version:block.revision,name:block.name,duration:block.duration},0);}
        catch(error){message(error.message,true);}
    }
    try{
        const draft=JSON.parse(localStorage.getItem(localKey+':draft')||'null');
        if(draft){const restoreButton=button('Restore unsaved changes',()=>{
            const legacyConflict=!draft.base&&draft.revision!==state.revision;
            const current=clone(state);
            if(draft.base)Object.assign(state,clone(draft.base));
            baseRevision=draft.revision;restore(draft);restoreButton.remove();
            if(legacyConflict)showConflict(Object.assign(Error('Review these older unsaved changes before replacing the saved schedule.'),{latest:current}),current);
        });$('studio-message').append(restoreButton);}
    }catch{}
    await refreshState();
}
init();
})();
