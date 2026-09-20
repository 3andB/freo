const {test}=require('node:test');
const assert=require('node:assert/strict');
const {webcrypto}=require('node:crypto');global.crypto=webcrypto;
const editor=require('../app/static/schedule_editor.js');
const rule={frequency:'weekly',anchor:'2026-09-21',weekdays:[0],interval:2,exceptions:['2026-10-19']};
const section=(extra={})=>({id:'a',start:0,end:3600,source:{kind:'song',id:1},...extra});
let id=0;const uid=()=>String(++id);

test('a proposed occurrence replacement does not mutate the document before confirmation',()=>{
 const original=[section({rule}),section({id:'occupied',rule:{...rule,frequency:'once'}})];const saved=structuredClone(original);
 const result=editor.edit(original,section({rule}),{scope:'occurrence',origin:'2026-09-21',day:'2026-09-21'},uid);
 assert.equal(result.conflicts.length,1);assert.deepEqual(original,saved);
 assert.deepEqual(result.items.find(r=>r.id==='a').rule.exceptions,['2026-10-19','2026-09-21']);
});
test('series edits preserve anchor and exceptions; following edits keep the original cycle phase',()=>{
 const original=[section({rule})];
 assert.deepEqual(editor.edit(original,section({rule}),{scope:'series',day:'2026-10-05',origin:'2026-10-05'},uid).items,original);
 const result=editor.edit(original,section({rule}),{scope:'following',day:'2026-10-05',origin:'2026-10-05'},uid).items;
 assert.equal(result[0].rule.until,'2026-10-04');assert.equal(result[1].rule.anchor,'2026-09-21');
 assert.equal(result[1].rule.starts_on,'2026-10-05');assert.deepEqual(result[1].rule.exceptions,rule.exceptions);
});
test('remove uses occurrence origin and first-occurrence following edits leave no inverted series',()=>{
 const original=[section({rule,start:82800,end:93600})];
 assert.deepEqual(editor.remove(original,'a',{scope:'occurrence',origin:'2026-09-21'})[0].rule.exceptions,['2026-10-19','2026-09-21']);
 assert.deepEqual(editor.remove(original,'a',{scope:'following',origin:'2026-09-21'}),[]);
 assert.equal(editor.edit(original,original[0],{scope:'following',origin:'2026-09-21',day:'2026-09-21'},uid).items.length,1);
});
test('split partitions inserts, move shifts them, resize removes only inserts outside the section',()=>{
 const original=section({inserts:[{id:'early',at:300},{id:'middle',at:1800},{id:'late',at:2700}]});
 const halves=editor.split(original,1800,uid);
 assert.deepEqual(halves.map(s=>s.inserts.map(i=>i.id)),[['early'],['middle','late']]);
 assert.deepEqual(editor.interval(original,3600,7200,true).inserts.map(i=>i.at),[3900,5400,6300]);
 assert.deepEqual(editor.interval(original,600,2400).inserts.map(i=>i.id),['middle']);
 assert.equal(original.inserts.length,3);
});
test('overnight overlap replacement preserves both outside intervals using normalized dates',()=>{
 const once={frequency:'once',anchor:'2026-09-21',exceptions:[]};
 const original=[section({start:82800,end:93600,rule:once})];
 const result=editor.edit(original,section({id:'b',start:1800,end:3600,rule:{...once,anchor:'2026-09-22'}}),{},uid);
 assert.equal(result.conflicts.length,1);
 const pieces=result.items.filter(s=>s.id!=='b');
 assert.deepEqual(pieces.map(s=>[s.start,s.end,s.rule.anchor]),[[82800,88200,'2026-09-21'],[3600,7200,'2026-09-22']]);
});
test('seeded interval transformations conserve duration and each insert over 2000 cases',()=>{
 let seed=12345;const random=()=>((seed=(1664525*seed+1013904223)>>>0)/2**32);
 for(let i=0;i<2000;i++){
  const start=Math.floor(random()*80000),end=start+2+Math.floor(random()*1000),at=start+1+Math.floor(random()*(end-start-1));
  const item=section({start,end,inserts:Array.from({length:10},(_,n)=>({id:String(n),at:start+Math.floor(random()*(end-start))}))});
  const snapshot=structuredClone(item),halves=editor.split(item,at,uid);
  assert.equal(halves.reduce((n,s)=>n+s.end-s.start,0),end-start);
  assert.deepEqual(halves.flatMap(s=>s.inserts).sort((a,b)=>a.id.localeCompare(b.id)),[...item.inserts].sort((a,b)=>a.id.localeCompare(b.id)));
  assert.ok(halves.every(s=>s.inserts.every(i=>i.at>=s.start&&i.at<s.end)));
  assert.deepEqual(item,snapshot);
 }
});

test('effective coverage matches dated override priority without mutating recurring definitions',()=>{
 const repeating=section({rule:{...rule,interval:1},start:0,end:86400});
 const override=section({id:'special',start:3600,end:7200,rule:{frequency:'once',anchor:'2026-09-21'}});
 const rows=editor.coverage([repeating,override],'2026-09-21');
 assert.deepEqual(rows.map(r=>[r.id,r.start,r.end]),[['a',0,3600],['special',3600,7200],['a',7200,86400]]);
 assert.equal(repeating.end,86400);
 assert.deepEqual(editor.coverage([repeating,override],'2026-09-28').map(r=>[r.start,r.end]),[[0,86400]]);
});
test('overnight overrides clip the next day and preserve the occurrence origin',()=>{
 const recurring=section({start:82800,end:93600,rule:{...rule,interval:1}});
 const one=section({id:'special',start:0,end:3600,rule:{frequency:'once',anchor:'2026-09-22'}});
 const rows=editor.coverage([recurring,one],'2026-09-22');
 assert.deepEqual(rows.map(r=>[r.id,r.start,r.end,r.origin]),[['special',0,3600,'2026-09-22'],['a',3600,7200,'2026-09-21']]);
});
test('cross-day series moves shift phase, weekdays, and exceptions together',()=>{
 const shifted=editor.movedRule(rule,'2026-10-05','2026-10-06','series');
 assert.equal(shifted.anchor,'2026-09-22');assert.deepEqual(shifted.weekdays,[1]);
 assert.deepEqual(shifted.exceptions,['2026-10-20']);
 assert.equal(editor.matches(shifted,'2026-10-06'),true);assert.equal(editor.matches(shifted,'2026-10-20'),false);
 assert.deepEqual(editor.movedRule(rule,'2026-10-05','2026-10-06','occurrence'),rule);
});

test('autosave rebases pending edits and undo without erasing unrelated saved items',()=>{
 const base=[{id:'a',start:1},{id:'b',start:2}],local=[{id:'a',start:0},base[1]],remote=[...base,{id:'c',start:3}];
 assert.deepEqual(editor.mergeItems(base,local,remote),[local[0],base[1],remote[2]]);
 assert.deepEqual(editor.mergeItems(base,[base[1]],remote),[base[1],remote[2]]);
 assert.throws(()=>editor.mergeItems(base,local,[{id:'a',start:4},base[1]]),/also changed/);
 assert.deepEqual(editor.mergeItems(base,local,[{id:'a',start:4},base[1]],true),local);
 assert.ok(editor.equal({a:1,b:2},{b:2,a:1}));
});
