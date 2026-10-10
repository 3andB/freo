const {test}=require('node:test');
const assert=require('node:assert/strict');
const {readFileSync}=require('node:fs');
const vm=require('node:vm');

function fixture(){
  class Element extends EventTarget {
    constructor(){super();this.style={setProperty(){},removeProperty(){}};this.hidden=true;this.checked=true;this.value=0;}
    setAttribute(){}
    getBoundingClientRect(){return {height:40};}
  }
  const elements=new Map(),element=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id);};
  const audio=element('music-audio');
  Object.assign(audio,{paused:true,currentTime:0,duration:10,playbackRate:1,readyState:4,
    pause(){this.paused=true;this.dispatchEvent(new Event('pause'));},
    async play(){this.paused=false;this.dispatchEvent(new Event('play'));this.dispatchEvent(new Event('playing'));}});
  const calls=[],gain={gain:{cancelScheduledValues(t){calls.length=0;calls.push(['cancel',t]);},
    setValueAtTime(v,t){calls.push(['set',v,t]);},linearRampToValueAtTime(v,t){calls.push(['ramp',v,t]);}},connect(){}};
  let context,fetches=0;
  class AudioContext {
    constructor(){context=this;this.currentTime=0;}
    createGain(){return gain;}
    createMediaElementSource(){return {connect(){}};}
    async resume(){}
  }
  const document=new Element();Object.assign(document,{getElementById:element,querySelectorAll:()=>[],documentElement:new Element()});
  const state={policy:{enabled:true,effective:{cue_in_ms:1000,cue_out_ms:5000,fade_in_ms:1000,fade_out_ms:1000},gain:{factor:.5,db:-6}}};
  const scope={listen:(target,event,fn)=>target.addEventListener(event,fn),interval(){},cleanup(){},
    async fetch(){fetches++;if(state.fail)throw Error('offline');return {ok:true,json:async()=>({audio:state.policy})};}};
  const window={FreoPage:scope,AudioContext};
  const sandbox={window,document,FreoMonitor:{stop(){}},ResizeObserver:class{observe(){} disconnect(){}}};
  vm.runInNewContext(readFileSync('app/static/music_preview.js','utf8'),sandbox);
  const song={uuid:'test',title:'Test',artist:'Artist',audition:'/admin/stations/test/media/song/audition'};
  return {audio,calls,state,song,play:window.FreoPreview.play,context:()=>context,fetches:()=>fetches};
}

test('buffering holds the envelope until source playback resumes',async()=>{
  const f=fixture();await f.play(f.song);
  f.audio.currentTime=1.5;f.context().currentTime=10;
  f.audio.dispatchEvent(new Event('waiting'));
  assert.deepEqual(f.calls,[['cancel',10],['set',.25,10]]);
  f.context().currentTime=20;f.audio.dispatchEvent(new Event('playing'));
  assert.deepEqual(f.calls,[['cancel',20],['set',.25,20],['ramp',.5,20.5],['ramp',.5,22.5],['ramp',0,23.5]]);
});

test('seeking and playback rate rebuild the envelope from the source position',async()=>{
  const f=fixture();await f.play(f.song);f.audio.currentTime=3;f.audio.playbackRate=2;
  f.audio.dispatchEvent(new Event('seeking'));assert.equal(f.calls.length,2);
  f.audio.dispatchEvent(new Event('seeked'));
  assert.deepEqual(f.calls,[['cancel',0],['set',.5,0],['ramp',.5,.5],['ramp',0,1]]);
  f.audio.currentTime=0;f.audio.dispatchEvent(new Event('seeked'));
  assert.equal(f.audio.currentTime,1);
});

test('a fresh library audition reloads saved policy for the same track',async()=>{
  const f=fixture();await f.play(f.song);f.audio.pause();
  f.state.policy={...f.state.policy,effective:{...f.state.policy.effective,cue_in_ms:2000}};
  await f.play(f.song);
  assert.equal(f.fetches(),2);assert.equal(f.audio.currentTime,2);
});

test('failed policy fetch can be retried without caching an incomplete song',async()=>{
  const f=fixture();f.state.fail=true;await f.play(f.song);assert.equal(f.audio.paused,true);
  f.state.fail=false;await f.play(f.song);
  assert.equal(f.fetches(),2);assert.equal(f.audio.src,f.song.audition);assert.equal(f.audio.currentTime,1);
});

test('zero fade-out holds full gain until cue out',async()=>{
  const f=fixture();f.state.policy.effective.fade_in_ms=0;f.state.policy.effective.fade_out_ms=0;
  await f.play(f.song);
  assert.deepEqual(f.calls,[['cancel',0],['set',.5,0],['ramp',.5,4],['set',0,4]]);
});
