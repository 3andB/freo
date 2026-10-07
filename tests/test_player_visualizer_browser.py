"""Real Chromium record, capture-only visualizer, and playback isolation proofs."""
import base64
import io
import wave
import pytest
from flask import jsonify, Response
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import Select, WebDriverWait
from tests.test_live_browser import booth, app_fixture, wait_text
from tests.test_station_settings_flags import png


def js(driver, source):
    return driver.execute_script(source)


def playing(driver):
    before = js(driver, 'return document.getElementById("station-audio").currentTime')
    WebDriverWait(driver, 5).until(lambda d: js(d, 'return !document.getElementById("station-audio").paused && document.getElementById("station-audio").currentTime') > before + .15)


def instrument(driver):
    driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {'source': '''
      window.visualProbe={contexts:[], captures:0, outputConnections:0, samples:0, peak:0};
      const capture=HTMLMediaElement.prototype.captureStream;
      HTMLMediaElement.prototype.captureStream=function(){visualProbe.captures++;return capture.call(this)};
      const NativeContext=AudioContext;
      window.AudioContext=class extends NativeContext {constructor(){super();visualProbe.contexts.push(this)}};
      const connect=AudioNode.prototype.connect;
      AudioNode.prototype.connect=function(node,...args){if(node instanceof AudioDestinationNode)visualProbe.outputConnections++;return connect.call(this,node,...args)};
      const sample=AnalyserNode.prototype.getByteFrequencyData;
      AnalyserNode.prototype.getByteFrequencyData=function(data){sample.call(this,data);visualProbe.samples++;visualProbe.peak=Math.max(visualProbe.peak,...data)};
    '''})


@pytest.fixture
def long_player_stream(booth, monkeypatch):
    app, driver, base, tmp = booth
    requests = []
    stream = app.view_functions['test_monitor_stream']
    # Mode screenshots/fullscreen on busy CI can outlast the shared 120s fixture.
    with wave.open(io.BytesIO(stream().get_data()), 'rb') as source:
        buffer = io.BytesIO()
        with wave.open(buffer, 'wb') as output:
            output.setparams(source.getparams())
            output.writeframes(source.readframes(source.getnframes()) * 5)
    def counted():
        requests.append(True)
        return Response(buffer.getvalue(), mimetype='audio/wav')
    monkeypatch.setitem(app.view_functions, 'test_monitor_stream', counted)
    return requests


def test_record_modes_fullscreen_metadata_and_mobile(booth, monkeypatch, long_player_stream):
    app, driver, base, tmp = booth
    instrument(driver)
    requests = long_player_stream
    endpoint = next(r.endpoint for r in app.url_map.iter_rules() if r.rule == '/api/stations/<slug>/player')
    original = app.view_functions[endpoint]
    artwork = 'data:image/png;base64,' + base64.b64encode(png(40, 40)).decode()
    current = dict(title='First album', artwork=artwork)
    def metadata(**kwargs):
        response = original(**kwargs)
        data = response.get_json()
        data['fresh'] = True
        data['current'] = [dict(title=current['title'], artist='Test Artist', artwork=current['artwork'], votable=False)]
        return jsonify(data)
    monkeypatch.setitem(app.view_functions, endpoint, metadata)
    driver.get(base + '/player/test-station')
    wait_text(driver, '#playing-heading', 'First album')
    WebDriverWait(driver, 5).until(lambda d: d.find_elements(By.CSS_SELECTOR, '#record-artwork img'))
    assert driver.find_element(By.CSS_SELECTOR, '.radio-vinyl').is_displayed()
    assert not driver.find_element(By.ID, 'player-visual').is_displayed()
    assert not any(ad.is_displayed() for ad in driver.find_elements(By.CSS_SELECTOR, '.radio-ad'))
    assert js(driver, 'return visualProbe.captures') == 0
    driver.find_element(By.ID, 'play-button').click()
    wait_text(driver, '#audio-message', 'listening live')
    playing(driver)
    for selector in ('.vinyl-grooves', '#record-artwork', '.orbit-two'):
        before = js(driver, f'return getComputedStyle(document.querySelector("{selector}")).transform')
        WebDriverWait(driver, 3).until(lambda d: js(d, f'return getComputedStyle(document.querySelector("{selector}")).transform') != before)
    js(driver, 'window.keptAudio=document.getElementById("station-audio");window.keptSource=keptAudio.currentSrc')
    count = len(requests)
    driver.save_screenshot('/tmp/freo-v1-record-desktop.png')
    driver.find_element(By.ID, 'visualizer-open').click()
    try:
        WebDriverWait(driver, 8).until(lambda d: d.find_element(By.ID, 'player-visual').get_attribute('data-analysis') == 'live')
    except Exception:
        pytest.fail(str(js(driver, '''return {status:document.getElementById('visual-status').textContent,
          audio:{paused:keptAudio.paused,time:keptAudio.currentTime,duration:keptAudio.duration},
          contexts:visualProbe.contexts.map(c=>c.state),captures:visualProbe.captures}''')))
    WebDriverWait(driver, 5).until(lambda d: js(d, 'return visualProbe.peak') > 0)
    assert js(driver, 'return visualProbe.outputConnections') == 0
    images = set()
    for mode in ('fractal', 'spectrum', 'waveform', 'particles', 'ambient', 'aurora', 'ethereal', 'space'):
        Select(driver.find_element(By.ID, 'visual-mode')).select_by_value(mode)
        WebDriverWait(driver, 3).until(lambda d: d.find_element(By.ID, 'player-visual').get_attribute('data-mode') == mode)
        before = js(driver, 'return document.getElementById("player-visual").toDataURL()')
        WebDriverWait(driver, 3).until(lambda d: js(d, 'return document.getElementById("player-visual").toDataURL()') != before)
        images.add(before)
        driver.save_screenshot('/tmp/freo-v1-visual-' + mode + '.png')
        playing(driver)
    assert len(images) == 8
    assert Select(driver.find_element(By.ID,'visual-mode')).options[0].text=='Kai'
    for choice in ('sunset', 'electric', 'aurora','ocean','amethyst','rose_gold','emerald','solar'):
        Select(driver.find_element(By.ID, 'visual-palette')).select_by_value(choice)
    current.update(title='Second album', artwork=artwork + '#second')
    wait_text(driver, '#visualizer-title', 'Second album')
    WebDriverWait(driver, 6).until(lambda d: d.find_element(By.CSS_SELECTOR, '#visualizer-artwork img').get_attribute('src').endswith('#second'))
    assert driver.find_element(By.CSS_SELECTOR, '#record-artwork img').get_attribute('src').endswith('#second')
    driver.find_element(By.ID, 'visualizer-fullscreen').click()
    WebDriverWait(driver, 5).until(lambda d: js(d, 'return !!document.fullscreenElement'))
    driver.save_screenshot('/tmp/freo-v1-visual-fullscreen.png')
    driver.find_element(By.ID, 'visualizer-fullscreen').click()
    WebDriverWait(driver, 5).until(lambda d: not js(d, 'return !!document.fullscreenElement'))
    driver.find_element(By.ID, 'visualizer-close').click()
    WebDriverWait(driver, 5).until(lambda d: js(d, 'return visualProbe.contexts.every(c=>c.state==="closed")'))
    assert js(driver, 'return document.activeElement.id') == 'visualizer-open'
    assert js(driver, 'return keptAudio===document.getElementById("station-audio") && keptSource===keptAudio.currentSrc')
    assert len(requests) == count
    playing(driver)
    driver.set_window_size(390, 844)
    assert js(driver, 'return document.documentElement.scrollWidth <= innerWidth+1')
    driver.save_screenshot('/tmp/freo-v1-record-mobile.png')
    js(driver, 'document.getElementById("visualizer-open").scrollIntoView({block:"center"})')
    driver.find_element(By.ID, 'visualizer-open').click()
    assert js(driver, 'return document.getElementById("visualizer-dialog").scrollWidth <= innerWidth+1')
    driver.save_screenshot('/tmp/freo-v1-visual-mobile.png')
    current.update(title='No cover', artwork=base + '/missing-art.png')
    wait_text(driver, '#visualizer-title', 'No cover')
    assert not driver.find_element(By.ID, 'visualizer-artwork').is_displayed()
    assert not driver.find_element(By.ID, 'record-artwork').is_displayed()
    driver.find_element(By.ID, 'visualizer-close').send_keys(Keys.ESCAPE)
    WebDriverWait(driver, 5).until(lambda d: not js(d, 'return document.getElementById("visualizer-dialog").open'))
    assert driver.find_element(By.CSS_SELECTOR, '.vinyl-lava>span').is_displayed()
    # A normal player resume replaces its native element. Analysis must follow it.
    driver.find_element(By.ID, 'play-button').click()
    driver.find_element(By.ID, 'play-button').click()
    wait_text(driver, '#audio-message', 'listening live')
    driver.find_element(By.ID, 'visualizer-open').click()
    WebDriverWait(driver, 5).until(lambda d: d.find_element(By.ID, 'player-visual').get_attribute('data-analysis') == 'live')
    playing(driver)


@pytest.mark.parametrize('failure', ['canvas', 'capture', 'analyser'])
def test_visual_failure_never_interrupts_audio(booth, failure):
    app, driver, base, tmp = booth
    instrument(driver)
    driver.get(base + '/player/test-station')
    driver.find_element(By.ID, 'play-button').click()
    wait_text(driver, '#audio-message', 'listening live')
    if failure == 'canvas':
        js(driver, 'HTMLCanvasElement.prototype.getContext=()=>{throw Error("canvas unavailable")}')
    elif failure == 'capture':
        js(driver, 'HTMLMediaElement.prototype.captureStream=()=>{throw Error("capture unavailable")}')
    else:
        js(driver, 'AnalyserNode.prototype.getByteFrequencyData=()=>{throw Error("analysis failed")}')
    driver.find_element(By.ID, 'visualizer-open').click()
    wait_text(driver, '#visual-status', 'unavailable')
    playing(driver)
    driver.find_element(By.ID, 'visualizer-close').click()
    playing(driver)
    assert js(driver, 'return visualProbe.outputConnections') == 0


def test_visualizers_ignore_retired_motion_preferences_and_isolate_failure(booth, long_player_stream):
    app, driver, base, tmp = booth
    from app.models import Station, StationPlayerSettings
    from app.extensions import db
    with app.app_context():
        station = Station.query.filter_by(slug='test-station').one()
        db.session.add(StationPlayerSettings(station_id=station.id, revision=1, config={'motion': False}))
        db.session.commit()
    instrument(driver)
    driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {'source': "localStorage.setItem('freo-motion','reduced')"})
    driver.execute_cdp_cmd('Emulation.setEmulatedMedia', {'features': [{'name': 'prefers-reduced-motion', 'value': 'reduce'}]})
    driver.get(base + '/player/test-station')
    driver.find_element(By.ID, 'play-button').click()
    wait_text(driver, '#audio-message', 'listening live')
    assert js(driver, 'return getComputedStyle(document.querySelector(".vinyl-grooves")).animationPlayState') == 'running'
    assert js(driver, 'return getComputedStyle(document.querySelector(".vinyl-grooves")).animationName') != 'none'
    driver.find_element(By.ID, 'visualizer-open').click()
    WebDriverWait(driver, 8).until(lambda d: js(d, 'return visualProbe.peak') > 0)
    for mode in ('fractal','spectrum','waveform','particles','ambient','aurora','ethereal','space'):
        Select(driver.find_element(By.ID, 'visual-mode')).select_by_value(mode)
        before = js(driver, 'return document.getElementById("player-visual").toDataURL()')
        WebDriverWait(driver, 5).until(lambda d: js(d, 'return document.getElementById("player-visual").toDataURL()') != before)
        assert driver.find_element(By.ID, 'player-visual').get_attribute('data-analysis') == 'live'
        assert 'Reduced motion' not in driver.find_element(By.ID, 'visual-status').text
    js(driver, 'CanvasRenderingContext2D.prototype.clearRect=()=>{throw Error("render failure")};document.getElementById("visual-mode").dispatchEvent(new Event("change"))')
    wait_text(driver, '#visual-status', 'Visualization unavailable')
    playing(driver)
    driver.find_element(By.ID, 'visualizer-close').click()
    assert js(driver, 'return getComputedStyle(document.querySelector(".vinyl-grooves")).animationPlayState') == 'running'
    assert js(driver, 'return getComputedStyle(document.querySelector(".vinyl-grooves")).animationName') != 'none'


def test_gesture_unlock_reconnect_and_motion_preference_changes(booth, long_player_stream):
    app, driver, base, tmp = booth
    # Reproduce a context which exists but could not run on the first Play.
    driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {'source': '''
      HTMLMediaElement.prototype.captureStream=undefined;
      HTMLMediaElement.prototype.mozCaptureStream=undefined;
      window.allowResume=false;window.contexts=[];
      const Native=AudioContext;
      window.AudioContext=class extends Native {constructor(){super();contexts.push(this)}};
      const state=Object.getOwnPropertyDescriptor(BaseAudioContext.prototype,'state').get;
      Object.defineProperty(Native.prototype,'state',{get(){return allowResume?state.call(this):'suspended'}});
      const resume=Native.prototype.resume;
      Native.prototype.resume=function(){return allowResume?resume.call(this):Promise.resolve()};
    '''})
    driver.get(base+'/player/test-station')
    driver.find_element(By.ID,'play-button').click();playing(driver)
    assert js(driver,'return !FreoAudioAnalysis.read(document.getElementById("station-audio")).source')
    js(driver,'allowResume=true')
    driver.find_element(By.ID,'visualizer-open').click()
    WebDriverWait(driver,8).until(lambda d:js(d,'return !!FreoAudioAnalysis.read(document.getElementById("station-audio"))?.analyser'))
    for _ in range(3):
        for mode in ('space','spectrum','aurora','ethereal'):
            Select(driver.find_element(By.ID,'visual-mode')).select_by_value(mode)
    assert js(driver,'return contexts.filter(c=>c.state!=="closed").length')==1
    driver.execute_cdp_cmd('Emulation.setEmulatedMedia',{'features':[{'name':'prefers-reduced-motion','value':'reduce'}]})
    driver.execute_async_script('setTimeout(arguments[0],200)')
    before=js(driver,'return document.getElementById("player-visual").toDataURL()')
    driver.execute_async_script('setTimeout(arguments[0],200)')
    WebDriverWait(driver,5).until(lambda d:js(d,'return document.getElementById("player-visual").toDataURL()')!=before)
    driver.execute_cdp_cmd('Emulation.setEmulatedMedia',{'features':[{'name':'prefers-reduced-motion','value':'no-preference'}]})
    WebDriverWait(driver,5).until(lambda d:js(d,'return document.getElementById("player-visual").toDataURL()')!=before)
    # Retry on the same element must reattach the analyser to the new resource.
    js(driver,'document.getElementById("station-audio").dispatchEvent(new Event("ended"))')
    js(driver,'const a=document.getElementById("station-audio");a.src=a.currentSrc+"&reconnect=1";a.play()')
    WebDriverWait(driver,8).until(lambda d:js(d,'return document.getElementById("player-visual").dataset.analysis==="live"'))
    playing(driver)
    assert js(driver,'return contexts.filter(c=>c.state!=="closed").length')==1
    driver.find_element(By.ID,'visualizer-close').click();playing(driver)


def test_open_before_play_and_capture_is_unlocked_in_gesture(booth):
    app,driver,base,tmp=booth
    driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument',{'source': '''
      window.resumeGestures=[];window.contextGestures=[];const Native=AudioContext;
      window.AudioContext=class extends Native {constructor(){super();contextGestures.push(navigator.userActivation.isActive)}};
      const resume=Native.prototype.resume;
      AudioContext.prototype.resume=function(){resumeGestures.push(navigator.userActivation.isActive);return resume.call(this)};
    '''})
    driver.get(base+'/player/test-station')
    driver.find_element(By.ID,'visualizer-open').click()
    assert js(driver,'return contextGestures[0]') is True
    assert js(driver,'return resumeGestures.every(Boolean)') is True
    driver.find_element(By.ID,'visualizer-close').click()
    driver.find_element(By.ID,'play-button').click();playing(driver)
    driver.find_element(By.ID,'visualizer-open').click()
    WebDriverWait(driver,8).until(lambda d:js(d,'return document.getElementById("player-visual").dataset.analysis==="live"'))
    driver.find_element(By.ID,'visualizer-close').click();playing(driver)


def test_real_frequency_bands_silence_and_external_fallback(booth, monkeypatch):
    import math
    import struct
    app, driver, base, tmp = booth
    buffer=io.BytesIO()
    with wave.open(buffer,'wb') as output:
        output.setnchannels(1);output.setsampwidth(2);output.setframerate(48000)
        for hz in (80,1000,6000,0):
            output.writeframes(b''.join(struct.pack('<h',int(7000*math.sin(2*math.pi*hz*n/48000))) for n in range(48000*4)))
    from flask import send_file
    monkeypatch.setitem(app.view_functions,'test_monitor_stream',lambda:send_file(io.BytesIO(buffer.getvalue()),mimetype='audio/wav',conditional=True))
    driver.get(base+'/player/test-station')
    js(driver, '''const create=FreoVisualScenes.create;window.sceneBands=null;
      FreoVisualScenes.create=(...args)=>{const api=create(...args),render=api.render;
        api.render=(mode,p)=>{sceneBands={bass:p.bass,mids:p.mids,treble:p.treble,energy:p.energy,measured:p.measured};return render(mode,p)};return api};''')
    driver.find_element(By.ID,'play-button').click();playing(driver)
    driver.find_element(By.ID,'visualizer-open').click()
    WebDriverWait(driver,8).until(lambda d:js(d,'return !!FreoAudioAnalysis.read(document.getElementById("station-audio"))?.analyser'))
    for position, hz in ((.5,80),(4.5,1000),(8.5,6000),(12.5,0)):
        js(driver,f'document.getElementById("station-audio").currentTime={position}')
        def sample(d):
            return js(d,'''const g=FreoAudioAnalysis.read(document.getElementById('station-audio'));
              if(!g?.analyser)return null;const data=new Uint8Array(g.analyser.frequencyBinCount);g.analyser.getByteFrequencyData(data);
              const peak=Math.max(...data);return {peak,hz:data.indexOf(peak)*g.context.sampleRate/g.analyser.fftSize};''')
        try:
            WebDriverWait(driver,8).until(lambda d:(lambda v:v and (v['peak']==0 if not hz else v['peak']>50 and abs(v['hz']-hz)<65))(sample(d)))
        except Exception:
            pytest.fail(str(dict(position=position,expected_hz=hz,sample=sample(driver),audio=js(driver,'const a=document.getElementById("station-audio");return {time:a.currentTime,paused:a.paused,duration:a.duration,seekable:a.seekable.length}'))))
        if hz:
            band={80:'bass',1000:'mids',6000:'treble'}[hz]
            WebDriverWait(driver,8).until(lambda d:js(d,f'return sceneBands?.measured && sceneBands.{band}>.05 && sceneBands.{band}>=Math.max(...Object.entries(sceneBands).filter(([k])=>["bass","mids","treble"].includes(k)).map(([,v])=>v))'))
        else:
            WebDriverWait(driver,8).until(lambda d:js(d,'return sceneBands?.measured && sceneBands.energy<.005'))
    driver.find_element(By.ID,'visualizer-close').click()
    # Unknown cross-origin media must never be attached to Safari's audible graph.
    js(driver,'''window.externalAudio=new Audio('https://example.invalid/radio.mp3');
      externalAudio.captureStream=undefined;externalAudio.mozCaptureStream=undefined;
      FreoAudioAnalysis.prepare(externalAudio);''')
    assert js(driver,'return !FreoAudioAnalysis.read(externalAudio).source && !FreoAudioAnalysis.read(externalAudio).context')



@pytest.fixture
def software_graphics():
    """Exercise actual WebGL in headless Chromium using its software GPU."""


def test_rich_scene_variation_uses_live_audio_and_releases_resources(booth, long_player_stream, software_graphics):
    """Accelerate only choreography; analyser data and playback remain real."""
    app, driver, base, tmp = booth
    instrument(driver)
    driver.get(base+'/player/test-station')
    js(driver, '''window.richProbe={frames:0,offset:0,gl:[],params:[]};
      const get=HTMLCanvasElement.prototype.getContext;
      HTMLCanvasElement.prototype.getContext=function(kind,...args){const result=get.call(this,kind,...args);if(kind==='webgl'&&result)richProbe.gl.push(result);return result};
      const create=FreoVisualScenes.create;
      FreoVisualScenes.create=(...args)=>{const api=create(...args),render=api.render;
        api.render=(mode,params)=>{if(['fractal','particles','ambient','ethereal','space'].includes(mode)){
          richProbe.frames++;richProbe.params.push({mode,energy:params.energy,bass:params.bass,mids:params.mids,treble:params.treble,measured:params.measured});
          params={...params,time:params.time+richProbe.offset,fractalTime:(params.fractalTime??params.time)+richProbe.offset};}
          return render(mode,params)};return api};''')
    driver.find_element(By.ID,'play-button').click();playing(driver)
    driver.find_element(By.ID,'visualizer-open').click()
    WebDriverWait(driver,8).until(lambda d:js(d,'return visualProbe.peak')>0)
    initial=len(long_player_stream)
    cases = {
        'fractal': [(0,'fractalVisit','0'),(20,'fractalVisit','1'),(40,'fractalVisit','2')],
        'particles': [(0,'formation','galaxy'),(9,'formation','vortex'),(18,'formation','torus'),(27,'formation','ribbons'),(36,'formation','constellation')],
        'ambient': [(0,'formation','mandala'),(10,'formation','polyhedra'),(20,'formation','lattice'),(30,'formation','ribbons')],
        'ethereal': [(0,None,None),(8,None,None),(16,None,None)],
        'space': [(0,'comet','visible'),(12,'comet','visible'),(24,'ufo','visible')]
    }
    for mode, moments in cases.items():
        images=set()
        for moment,field,expected in moments:
            js(driver,f'richProbe.offset={moment}')
            Select(driver.find_element(By.ID,'visual-mode')).select_by_value(mode)
            # Re-selecting the current mode must also reset its local scene clock.
            js(driver,"document.getElementById('visual-mode').dispatchEvent(new Event('change'))")
            if field:
                WebDriverWait(driver,8).until(lambda d:d.find_element(By.ID,'player-visual').get_attribute('data-'+''.join('-'+c.lower() if c.isupper() else c for c in field))==expected)
            images.add(js(driver,'return document.getElementById("player-visual").toDataURL()'))
            assert driver.find_element(By.ID,'player-visual').get_attribute('data-analysis')=='live'
            playing(driver)
        assert len(images)==len(moments), mode
    assert js(driver,'return richProbe.params.some(p=>p.measured&&p.energy>0&&p.mids>0)')
    assert js(driver,'return richProbe.gl.length')<=1
    assert js(driver,'return visualProbe.contexts.filter(c=>c.state!=="closed").length')==1
    assert len(long_player_stream)==initial
    # Visibility pauses rendering without changing native audio playback.
    js(driver, "Object.defineProperty(document,'hidden',{configurable:true,get:()=>true});document.dispatchEvent(new Event('visibilitychange'))")
    before=js(driver,'return richProbe.frames')
    driver.execute_async_script('setTimeout(arguments[0],300)')
    assert js(driver,'return richProbe.frames')==before
    playing(driver)
    js(driver,"Object.defineProperty(document,'hidden',{configurable:true,get:()=>false});document.dispatchEvent(new Event('visibilitychange'))")
    WebDriverWait(driver,8).until(lambda d:js(d,'return richProbe.frames')>before)
    driver.find_element(By.ID,'visualizer-close').click()
    before=js(driver,'return richProbe.frames')
    driver.execute_async_script('setTimeout(arguments[0],300)')
    assert js(driver,'return richProbe.frames')==before
    playing(driver)
    js(driver,'FreoPage.dispose()')
    assert js(driver,'return richProbe.gl.every(gl=>gl.isContextLost())')


@pytest.mark.parametrize('failure',['unavailable','shader','draw','context-loss'])
def test_fractal_graphics_failure_falls_back_without_changing_audio(booth, long_player_stream, failure, software_graphics):
    app, driver, base, tmp = booth
    instrument(driver)
    driver.get(base+'/player/test-station')
    assert js(driver, "const c=document.createElement('canvas'),gl=c.getContext('webgl');if(!gl)return false;gl.getExtension('WEBGL_lose_context')?.loseContext();return true"), 'WebGL must be available to exercise these failure paths'
    if failure=='unavailable':
        js(driver, "const get=HTMLCanvasElement.prototype.getContext;HTMLCanvasElement.prototype.getContext=function(kind,...args){return kind==='webgl'?null:get.call(this,kind,...args)}")
    elif failure=='shader':
        js(driver, "WebGLRenderingContext.prototype.compileShader=()=>{throw Error('shader unavailable')}")
    elif failure=='draw':
        js(driver, "WebGLRenderingContext.prototype.drawArrays=()=>{throw Error('GPU draw failure')}")
    else:
        js(driver, "const draw=WebGLRenderingContext.prototype.drawArrays;WebGLRenderingContext.prototype.drawArrays=function(...args){this.getExtension('WEBGL_lose_context')?.loseContext();return draw.apply(this,args)}")
    driver.find_element(By.ID,'play-button').click();playing(driver)
    driver.find_element(By.ID,'visualizer-open').click()
    Select(driver.find_element(By.ID,'visual-mode')).select_by_value('fractal')
    WebDriverWait(driver,8).until(lambda d:d.find_element(By.ID,'player-visual').get_attribute('data-fractal-renderer')=='canvas')
    assert driver.find_element(By.ID,'player-visual').is_displayed()
    assert 'Visualization unavailable' not in driver.find_element(By.ID,'visual-status').text
    before=js(driver,'return document.getElementById("player-visual").toDataURL()')
    WebDriverWait(driver,8).until(lambda d:js(d,'return document.getElementById("player-visual").toDataURL()')!=before)
    playing(driver)
    Select(driver.find_element(By.ID,'visual-mode')).select_by_value('ethereal')
    playing(driver)
    driver.find_element(By.ID,'visualizer-close').click();playing(driver)
    assert js(driver,'return visualProbe.outputConnections')==0



def test_pending_safari_resume_can_retry_in_a_new_gesture(booth, long_player_stream):
    app,driver,base,tmp=booth
    driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {'source': '''
      HTMLMediaElement.prototype.captureStream=undefined;HTMLMediaElement.prototype.mozCaptureStream=undefined;
      window.resumeCalls=0;window.allowContext=false;
      const Native=AudioContext,state=Object.getOwnPropertyDescriptor(BaseAudioContext.prototype,'state').get;
      Object.defineProperty(Native.prototype,'state',{get(){return allowContext?state.call(this):'interrupted'}});
      const resume=Native.prototype.resume;
      Native.prototype.resume=function(){resumeCalls++;if(!allowContext)return new Promise(()=>{});return resume.call(this)};
    '''})
    driver.get(base+'/player/test-station')
    driver.find_element(By.ID,'play-button').click();playing(driver)
    assert js(driver,'return resumeCalls')>=1
    assert js(driver,'return FreoAudioAnalysis.read(document.getElementById("station-audio")).resuming')
    driver.find_element(By.ID,'visualizer-open').click()
    assert driver.find_element(By.ID,'visualizer-retry').is_displayed()
    js(driver,'allowContext=true')
    driver.find_element(By.ID,'visualizer-retry').click()
    WebDriverWait(driver,8).until(lambda d:js(d,'return document.getElementById("player-visual").dataset.signal==="present"'))
    assert js(driver,'return resumeCalls')>=2
    graph=js(driver,'const g=FreoAudioAnalysis.read(document.getElementById("station-audio"));return {sink:g.sink.gain.value,source:!!g.source}')
    assert graph=={'sink':0,'source':True}
    before=js(driver,'return document.getElementById("player-visual").toDataURL()')
    WebDriverWait(driver,5).until(lambda d:js(d,'return document.getElementById("player-visual").toDataURL()')!=before)
    driver.find_element(By.ID,'visualizer-close').click();playing(driver)
    assert js(driver,'return !FreoAudioAnalysis.read(document.getElementById("station-audio")).sink')


def test_spectrum_equal_level_tones_have_distinct_bands_and_heights(booth, monkeypatch):
    import math,struct
    app,driver,base,tmp=booth
    buffer=io.BytesIO();rate=44100
    with wave.open(buffer,'wb') as wav:
        wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(rate)
        for hz in (80,1000,6000,0):
            wav.writeframes(b''.join(struct.pack('<h',int(7000*math.sin(2*math.pi*hz*i/rate))) for i in range(rate*5)))
    from flask import send_file
    monkeypatch.setitem(app.view_functions,'test_monitor_stream',lambda:send_file(io.BytesIO(buffer.getvalue()),mimetype='audio/wav',conditional=True))
    driver.get(base+'/player/test-station')
    js(driver,'''window.spectrumHeights={};const fill=CanvasRenderingContext2D.prototype.fillRect;
      CanvasRenderingContext2D.prototype.fillRect=function(x,y,w,h){const c=document.getElementById('player-visual');
        if(this.canvas===c && c.dataset.mode==='spectrum' && Math.abs(w-c.width*.82/64*.62)<.01 && y<c.height*.77 && h>2){spectrumHeights[Math.round((x-c.width*.09)/(c.width*.82/64))]=h/c.height/.57;}
        return fill.call(this,x,y,w,h)};''')
    driver.find_element(By.ID,'play-button').click();playing(driver)
    driver.find_element(By.ID,'visualizer-open').click();Select(driver.find_element(By.ID,'visual-mode')).select_by_value('spectrum')
    maxima=[];positions=[]
    for position in (1,6,11):
        js(driver,f'document.getElementById("station-audio").currentTime={position};spectrumHeights={{}}')
        driver.execute_async_script('setTimeout(arguments[0],1400)')
        data=js(driver,'return spectrumHeights')
        assert data
        best=max(data,key=lambda k:data[k]);positions.append(int(best));maxima.append(data[best])
        assert sum(v>maxima[-1]-.08 for v in data.values())<=4, data
    assert positions==sorted(set(positions)),positions
    assert max(maxima)-min(maxima)<.08,maxima
    js(driver,'document.getElementById("station-audio").currentTime=16;spectrumHeights={}')
    driver.execute_async_script('setTimeout(arguments[0],1800)')
    js(driver,'spectrumHeights={}')
    driver.execute_async_script('setTimeout(arguments[0],500)')
    assert max(js(driver,'return Object.values(spectrumHeights)') or [0])<.05



def test_kai_zoom_detects_tempo_from_decoded_music_pulses(booth, monkeypatch):
    import math,struct
    app,driver,base,tmp=booth
    rate=22050;buffer=io.BytesIO();frequencies=(80,150,300,450,700,1000)
    with wave.open(buffer,'wb') as wav:
        wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(rate)
        pulse=b''.join(struct.pack('<h',int(1600*math.exp(-(i/rate)*24)*sum(math.sin(2*math.pi*hz*i/rate) for hz in frequencies))) for i in range(rate//2))
        wav.writeframes(pulse*240)
    from flask import send_file
    monkeypatch.setitem(app.view_functions,'test_monitor_stream',lambda:send_file(io.BytesIO(buffer.getvalue()),mimetype='audio/wav',conditional=True))
    driver.get(base+'/player/test-station')
    driver.find_element(By.ID,'play-button').click();playing(driver)
    driver.find_element(By.ID,'visualizer-open').click();Select(driver.find_element(By.ID,'visual-mode')).select_by_value('spectrum')
    try:
        WebDriverWait(driver,15).until(lambda d:(lambda bpm:bpm and abs(float(bpm)-120)<8)(d.find_element(By.ID,'player-visual').get_attribute('data-bpm')))
    except Exception:
        pytest.fail(str(js(driver,'return {...document.getElementById("player-visual").dataset,time:document.getElementById("station-audio").currentTime}')))
    Select(driver.find_element(By.ID,'visual-mode')).select_by_value('fractal')
    first=float(driver.find_element(By.ID,'player-visual').get_attribute('data-fractal-zoom'))
    driver.execute_async_script('setTimeout(arguments[0],700)')
    assert float(driver.find_element(By.ID,'player-visual').get_attribute('data-fractal-zoom'))<first
    playing(driver)
