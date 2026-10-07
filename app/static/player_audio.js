/* Playback owns Safari's media-element route. Visualizer cleanup never owns it. */
(() => {
  const scope=window.FreoPage;
  if(!scope || !document.querySelector('.radio-experience'))return;
  let graph=null, generation=0;
  function release(){
    generation++;
    if(graph){graph.audio.pause();try{graph.source?.disconnect();graph.analyser?.disconnect();graph.gain?.disconnect();graph.context.close().catch(()=>{});}catch{}}
    graph=null;
  }
  function setVolume(audio,level,muted){
    if(graph?.audio!==audio)return false;
    if(level!==undefined)graph.level=Math.max(0,Math.min(1,level));
    if(muted!==undefined)graph.muted=muted;
    if(!graph.source)return false;
    graph.gain.gain.setTargetAtTime(graph.muted?0:graph.level,graph.context.currentTime,.015);
    return true;
  }
  function prepare(audio,level,muted){
    if(audio.captureStream || audio.mozCaptureStream)return;
    if(graph?.audio===audio){setVolume(audio,level,muted);if(graph.context.state==='suspended')graph.context.resume().catch(()=>{});return;}
    release();
    const token=generation;
    try{
      // Where supported, retain music playback behavior when the screen locks.
      try{if(navigator.audioSession)navigator.audioSession.type='playback';}catch{}
      const context=new (window.AudioContext || window.webkitAudioContext)();
      graph={audio,context,source:null,analyser:null,gain:null,level:level??.8,muted:muted??false,error:null};
      // Unlock during the Play gesture; do not reroute a media element until ready.
      context.resume().then(()=>{
        if(token!==generation || scope.signal.aborted || context.state!=='running')return;
        try{
          // Prepare the audible output before taking ownership of the element.
          const gain=context.createGain();gain.gain.value=graph.muted?0:graph.level;
          gain.connect(context.destination);graph.gain=gain;
          const source=context.createMediaElementSource(audio);
          source.connect(gain);graph.source=source;
          // iPhone ignores media.volume; use one software gain without doubling it.
          audio.volume=1;audio.muted=false;
          // Analysis is an optional branch, never in series with audible output.
          try{graph.analyser=context.createAnalyser();graph.analyser.fftSize=1024;graph.analyser.smoothingTimeConstant=.72;source.connect(graph.analyser);}catch(error){graph.error=error.name;}
        }catch(error){graph.error=error.name;}
      }).catch(error=>{if(token===generation)graph.error=error.name;});
    }catch{}
  }
  const api={prepare,setVolume,read(audio){return graph?.audio===audio?graph:null;}};
  window.FreoAudioAnalysis=api;
  scope.listen(document,'visibilitychange',()=>{if(!document.hidden && graph && !graph.audio.paused && graph.context.state==='suspended')graph.context.resume().catch(()=>{});});
  scope.cleanup(()=>{release();if(window.FreoAudioAnalysis===api)delete window.FreoAudioAnalysis;});
})();
