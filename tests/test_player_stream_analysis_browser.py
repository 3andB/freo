"""A silent native media source can use real MP3 PCM without owning playback."""
import subprocess
import time
import pytest
from flask import Response, request
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select, WebDriverWait
from tests.test_live_browser import booth, app_fixture
from tests.test_player_visualizer_browser import long_player_stream, js, playing


def test_stream_fallback_is_real_bounded_and_playback_independent(booth, long_player_stream, monkeypatch):
    app, driver, base, tmp = booth
    original = app.view_functions['test_monitor_stream']
    mp3 = subprocess.run(['ffmpeg','-v','error','-i','pipe:0','-ar','44100','-ac','2','-b:a','64k','-f','mp3','pipe:1'],
                         input=original().get_data(),capture_output=True,check=True).stdout
    silent = subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','anullsrc=r=44100:cl=stereo','-t','120','-b:a','64k','-f','mp3','pipe:1'],
                            capture_output=True,check=True).stdout
    mode = {'fallback': 'music'}
    requests = []
    def stream():
        fallback = '_freo_visual' in request.args
        requests.append(fallback)
        if fallback and mode['fallback'] == 'stall':
            def stalled():
                yield mp3[:8192]
                time.sleep(20)
            return Response(stalled(),mimetype='audio/mpeg')
        if fallback and mode['fallback'] == 'http-error':
            return Response('unavailable',status=503)
        return Response(silent if fallback and mode['fallback'] == 'silence' else mp3,mimetype='audio/mpeg')
    monkeypatch.setitem(app.view_functions,'test_monitor_stream',stream)
    driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {'source': '''
      HTMLMediaElement.prototype.captureStream=undefined;HTMLMediaElement.prototype.mozCaptureStream=undefined;
      window.workerCounts={created:0,stopped:0};window.contexts=[];
      const NativeWorker=Worker,NativeContext=AudioContext;
      window.Worker=class extends NativeWorker{
        constructor(...args){if(window.denyDecoder)throw new Error('test worker blocked');super(...args);workerCounts.created++}
        terminate(){workerCounts.stopped++;super.terminate()}
      };
      window.AudioContext=class extends NativeContext{constructor(...args){super(...args);contexts.push(this)}};
      const connect=MediaElementAudioSourceNode.prototype.connect;
      MediaElementAudioSourceNode.prototype.connect=function(node,...args){
        if(window.dropNativeAnalysis && node instanceof AnalyserNode)return node;
        return connect.call(this,node,...args);
      };
    '''})
    driver.get(base+'/player/test-station?audio_debug=1')
    click=lambda name:driver.find_element(By.ID,name).click()
    def wait(body, seconds=15):return WebDriverWait(driver,seconds).until(lambda d:js(d,'return '+body))
    def report():
        click('audio-diagnostics-open')
        data=js(driver,'return JSON.parse(document.getElementById("audio-diagnostics-report").value)')
        click('audio-diagnostics-close');return data
    def reopen():
        click('visualizer-close');click('visualizer-open')
    click('play-button');playing(driver);click('visualizer-open')
    Select(driver.find_element(By.ID,'visual-mode')).select_by_value('spectrum')
    wait('document.getElementById("player-visual").dataset.signal==="present"')
    assert not any(requests) and js(driver,'return workerCounts.created')==0
    js(driver,'''window.keptAudio=document.getElementById('station-audio');window.keptGraph=FreoAudioAnalysis.read(keptAudio);
      window.keptSource=keptGraph.source;window.keptContext=keptGraph.context;window.dropNativeAnalysis=true;''')
    reopen()
    wait('!document.getElementById("visualizer-retry").hidden')
    click('visualizer-retry')
    wait('keptGraph.fallback?.samples>0 && document.getElementById("player-visual").dataset.signal==="present"',25)
    assert not driver.find_element(By.ID,'visualizer-retry').is_displayed()
    data=report()
    assert data['graph']['route']=='stream-decoder' and data['current']['rms']>0
    assert data['graph']['fallback']['outputGain']==0
    assert data['graph']['fallback']['queuedSeconds']<2.5 and data['graph']['fallback']['buffers']<=32
    assert js(driver,'return keptSource===keptGraph.source && keptContext===keptGraph.context && contexts.length===1')
    created=js(driver,'return workerCounts.created')
    for name in ['waveform','particles','spectrum']:
        Select(driver.find_element(By.ID,'visual-mode')).select_by_value(name)
        wait('document.getElementById("player-visual").dataset.signal==="present"')
    assert js(driver,'return workerCounts.created')==created
    playing(driver)
    # MP3 decoded silence must not make the visualizer pretend it has a signal.
    mode['fallback']='silence';reopen()
    wait('keptGraph.fallback?.samples>44100')
    wait('!document.getElementById("visualizer-retry").hidden')
    data=report()
    assert data['current']['rms']==0 and data['current']['frequencyPeak']==0
    assert data['current']['visualSignal']=='waiting'
    playing(driver)
    # HTTP/worker failures must release all optional resources and keep audio.
    for failure in ['http-error','stall']:
        mode['fallback']=failure;reopen()
        wait('keptGraph.fallback?.status==="error"',25)
        assert js(driver,'return workerCounts.created===workerCounts.stopped')
        playing(driver)
    mode['fallback']='music';click('visualizer-retry')
    wait('keptGraph.fallback?.samples>0 && document.getElementById("player-visual").dataset.signal==="present"',25)
    js(driver,'window.denyDecoder=true');reopen()
    wait('keptGraph.fallback?.status==="error"')
    assert js(driver,'return workerCounts.created===workerCounts.stopped')
    playing(driver)
    js(driver,'window.denyDecoder=false');click('visualizer-retry')
    wait('keptGraph.fallback?.samples>0',25)
    # Native reconnect replaces the decoder, retaining the audible source/context.
    previous=js(driver,'return workerCounts.created')
    js(driver,'''Object.defineProperty(keptAudio,'error',{configurable:true,value:{code:2}});keptAudio.dispatchEvent(new Event('error'));delete keptAudio.error;''')
    wait(f'workerCounts.created>{previous} && keptGraph.fallback?.samples>0',25)
    assert js(driver,'return keptSource===keptGraph.source && keptContext===keptGraph.context && contexts.length===1')
    click('visualizer-close');playing(driver)
    assert js(driver,'return workerCounts.created===workerCounts.stopped && !keptGraph.fallback')
    assert js(driver,'return keptAudio===document.getElementById("station-audio")')
