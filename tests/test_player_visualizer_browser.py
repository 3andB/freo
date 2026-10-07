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
    for choice in ('sunset', 'electric', 'aurora'):
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


def test_visualizer_reduced_motion_and_render_failure(booth):
    app, driver, base, tmp = booth
    driver.get(base + '/player/test-station')
    driver.find_element(By.ID, 'play-button').click()
    wait_text(driver, '#audio-message', 'listening live')
    driver.find_element(By.ID, 'visualizer-open').click()
    driver.execute_cdp_cmd('Emulation.setEmulatedMedia', {'features': [{'name': 'prefers-reduced-motion', 'value': 'reduce'}]})
    driver.execute_async_script('const done=arguments[0];setTimeout(done,200)')
    before = js(driver, 'return document.getElementById("player-visual").toDataURL()')
    driver.execute_async_script('const done=arguments[0];setTimeout(done,200)')
    assert before == js(driver, 'return document.getElementById("player-visual").toDataURL()')
    js(driver, 'CanvasRenderingContext2D.prototype.clearRect=()=>{throw Error("render failure")};document.getElementById("visual-mode").dispatchEvent(new Event("change"))')
    wait_text(driver, '#visual-status', 'Visualization unavailable')
    playing(driver)
    driver.find_element(By.ID, 'visualizer-close').click()
    assert js(driver, 'return getComputedStyle(document.querySelector(".vinyl-grooves")).animationName') == 'none'


def test_gesture_unlock_reconnect_and_motion_resume(booth, long_player_stream):
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
    assert before==js(driver,'return document.getElementById("player-visual").toDataURL()')
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
    driver.find_element(By.ID,'visualizer-close').click()
    # Unknown cross-origin media must never be attached to Safari's audible graph.
    js(driver,'''window.externalAudio=new Audio('https://example.invalid/radio.mp3');
      externalAudio.captureStream=undefined;externalAudio.mozCaptureStream=undefined;
      FreoAudioAnalysis.prepare(externalAudio);''')
    assert js(driver,'return !FreoAudioAnalysis.read(externalAudio).source && !FreoAudioAnalysis.read(externalAudio).context')
