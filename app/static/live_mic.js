(() => {
  const root=document.getElementById('dj-booth'), scope=window.FreoPage;
  if(!root)return;
  const panel=root.querySelector('.mic-console'), $=id=>root.querySelector('#mic-'+id);
  const available=panel.dataset.enabled==='true';
  let pc=null, stream=null, context=null, gain=null, analyser=null, token='', muted=false, busy=false, polling=false, disposed=false, phase='OFF AIR', lastReady=false;
  const active=()=>['FADING','LIVE','RETURNING'].includes(phase);
  const message=(value,error=false)=>{if(disposed)return;$('message').textContent=value;$('message').classList.toggle('error',error);};
  async function api(action,data={}){
    const response=await scope.fetch(panel.dataset.micUrl.replace('ACTION',action),{method:'POST',credentials:'same-origin',body:new URLSearchParams({csrf:root.dataset.csrf,token,...data})});
    if(!response.headers.get('content-type')?.includes('application/json'))throw new Error('Session expired. Sign in again; the station will return to AUTO.');
    const result=await response.json();if(!response.ok)throw new Error(result.message||'Microphone service unavailable');return result;
  }
  function paint(){
    if(disposed)return;
    root.dataset.micActive=String(active());
    if(active()&&['AUTO','DJ_BOOTH'].includes(root.dataset.board))root.className=`dj-booth booth-mode-${root.dataset.board.toLowerCase().replace('_','-')}`;
    panel.classList.toggle('is-live',phase==='LIVE');
    if(active()){
      document.getElementById('led-detail').textContent='LIVE MIC · '+phase;
      if(phase==='LIVE'){document.getElementById('morph-kicker').textContent='LIVE MIC';document.getElementById('morph-text').textContent='Live microphone';document.getElementById('morph-artist').textContent=muted?'MIC MUTED':'ON AIR';}
    }
    $('state').textContent=phase==='LIVE'?(muted?'ON AIR · MUTED':'ON AIR'):phase;
    $('go').textContent=phase==='LIVE'?'ON AIR':phase==='FADING'?'FADING FEED…':'GO LIVE';
    $('go').disabled=busy||!token||!lastReady||phase!=='READY';
    $('end').disabled=busy||!token||!['LIVE','FADING'].includes(phase);
    $('connect').disabled=!available||busy||!!pc; $('device').disabled=busy||!!pc;
    $('disconnect').disabled=busy||!pc||active(); $('mute').disabled=!stream;
    root.querySelectorAll('.mode-button').forEach(button=>button.classList.toggle('active',button.dataset.mode===(root.dataset.board==='LIVE_MIC'||active()?root.dataset.board:root.dataset.mode)));
  }
  scope.listen($('tab'),'click',()=>{root.dataset.board='LIVE_MIC';paint();});
  scope.listen(window,'freo-board-change',paint);
  scope.listen(window,'freo-booth-refreshed',paint);
  async function devices(){
    if(!navigator.mediaDevices?.enumerateDevices)return;
    const selected=$('device').value;
    const inputs=(await navigator.mediaDevices.enumerateDevices()).filter(item=>item.kind==='audioinput');
    if(disposed)return;
    $('device').replaceChildren(new Option('Default microphone / USB mixer',''),...inputs.filter(item=>item.deviceId!=='default').map((item,i)=>new Option(item.label||`Audio input ${i+1}`,item.deviceId)));
    if([...$('device').options].some(option=>option.value===selected))$('device').value=selected;
  }
  function closeLocal(){
    pc?.close();pc=null;stream?.getTracks().forEach(track=>track.stop());stream=null;
    context?.close();context=null;gain=null;analyser=null;token='';lastReady=false;muted=false;
    $('mute').textContent='MUTE MIC';$('mute').setAttribute('aria-pressed','false');$('level').value=0;
  }
  async function disconnect(){
    if(token)try{await api('disconnect');}catch(_){}
    closeLocal();phase='OFF AIR';paint();
  }
  function applyGain(){
    const db=Number($('gain').value);$('gain-value').textContent=`${db>0?'+':''}${db} dB`;
    if(gain)gain.gain.setTargetAtTime(muted?0:Math.pow(10,db/20),context.currentTime,.01);
  }
  scope.listen($('gain'),'input',applyGain);
  scope.listen($('fade'),'input',()=>{$('fade-value').textContent=`${$('fade').value} s`;});
  scope.listen($('mute'),'click',()=>{muted=!muted;applyGain();$('mute').textContent=muted?'UNMUTE MIC':'MUTE MIC';$('mute').setAttribute('aria-pressed',String(muted));paint();});
  scope.listen($('connect'),'click',async()=>{
    busy=true;phase='CONNECTING';paint();
    try{
      if(!navigator.mediaDevices?.getUserMedia||!window.RTCPeerConnection)throw new Error('Microphone capture requires HTTPS and a browser with WebRTC support.');
      // Resume AudioContext within the gesture, before network signaling.
      context=new AudioContext();await context.resume();
      const device=$('device').value;
      stream=await navigator.mediaDevices.getUserMedia({audio:{deviceId:device?{exact:device}:undefined,channelCount:{ideal:2},autoGainControl:false,noiseSuppression:false,echoCancellation:false}});
      if(disposed){closeLocal();return;}
      await devices();
      if(disposed){closeLocal();return;}
      stream.getAudioTracks()[0].addEventListener('ended',()=>{if(disposed)return;message('Audio input disconnected. Returning to AUTO.',true);disconnect();});
      const source=context.createMediaStreamSource(stream);gain=context.createGain();analyser=context.createAnalyser();analyser.fftSize=1024;
      const output=context.createMediaStreamDestination();source.connect(gain);gain.connect(analyser);analyser.connect(output);applyGain();
      const config=await api('config');if(disposed){closeLocal();return;}pc=new RTCPeerConnection(config);pc.addTrack(output.stream.getAudioTracks()[0],output.stream);
      const connection=pc;
      await pc.setLocalDescription(await pc.createOffer());
      await new Promise((resolve,reject)=>{
        if(connection.iceGatheringState==='complete'){resolve();return;}
        const timer=setTimeout(()=>{connection.removeEventListener('icegatheringstatechange',change);reject(new Error('Audio connection timed out. Check the network and retry.'));},12000);
        function change(){if(connection.iceGatheringState==='complete'){clearTimeout(timer);connection.removeEventListener('icegatheringstatechange',change);resolve();}}
        connection.addEventListener('icegatheringstatechange',change);
      });
      if(disposed)return;
      const answer=await api('offer',{sdp:pc.localDescription.sdp});token=answer.token;
      if(disposed){await disconnect();return;}
      await pc.setRemoteDescription({type:answer.type,sdp:answer.sdp});
      message('Checking the audio connection. Your microphone remains off air until GO LIVE.');
    }catch(error){await disconnect();message(error.message,true);}
    finally{busy=false;paint();}
  });
  for(const [id,action] of [['go','go'],['end','end']])scope.listen($(id),'click',async()=>{
    busy=true;paint();
    try{
      if(action==='go'){window.FreoMonitor?.stop();document.getElementById('booth-monitor').pause();document.getElementById('cue-monitor').pause();}
      await api(action,{fade:$('fade').value});lastReady=false;
      message(action==='go'?'GO LIVE requested. Wait for ON AIR before speaking.':'Returning to the interrupted feed…');
    }catch(error){message(error.message,true);}finally{busy=false;paint();}
  });
  scope.listen($('disconnect'),'click',()=>disconnect());
  async function poll(){
    if(!available||polling||busy||disposed)return;polling=true;
    try{
      const state=await api(token?'heartbeat':'status');
      if(disposed)return;
      phase=state.phase||'OFF AIR';lastReady=!!state.ready&&state.desired!=='LIVE';
      if(phase==='LIVE')message(muted?'Your mic is on air but muted.':'Your microphone is ON AIR. Carts and station IDs remain available.');
      else if(phase==='FAILED')message('Microphone connection lost. The station is returning to AUTO. Disconnect and reconnect to try again.',true);
      else if(phase==='READY'&&lastReady)message(token?'MIC READY · Check your level, then press GO LIVE.':'Another microphone session is connected to this station.');
      if(token&&!state.healthy&&phase==='LIVE')message('Audio connection interrupted. Returning to AUTO.',true);
      paint();
    }catch(error){lastReady=false;phase=token?'CONNECTION LOST':'UNAVAILABLE';paint();if(token||root.dataset.board==='LIVE_MIC')message(error.message,true);}
    finally{polling=false;}
  }
  scope.interval(poll,1000);
  scope.interval(()=>{
    if(!analyser)return;const samples=new Float32Array(analyser.fftSize);analyser.getFloatTimeDomainData(samples);
    let peak=0;for(const sample of samples)peak=Math.max(peak,Math.abs(sample));$('level').value=Math.min(1,peak);$('clip').textContent=peak>=.98?'CLIPPING — LOWER INPUT / GAIN':'';
  },80);
  const release=()=>{if(token)navigator.sendBeacon(panel.dataset.micUrl.replace('ACTION','disconnect'),new URLSearchParams({csrf:root.dataset.csrf,token}));closeLocal();};
  scope.listen(window,'pagehide',release);scope.cleanup(()=>{disposed=true;release();});
  if(!available){phase='UNAVAILABLE';message('Live microphone input is not available on this station yet.');}
  devices().catch(()=>{});paint();poll();
})();
