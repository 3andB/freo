"""Public listener flow, actual installability and Safari's non-capture path."""
import pytest
import json
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from app.extensions import db
from app.models import Station, ListenerRequest
from tests.test_live_browser import booth, app_fixture, wait_text
from tests.test_player_visualizer_browser import playing, js, long_player_stream


@pytest.fixture(autouse=True)
def eager_navigation():
    pass


def test_player_request_flow_preserves_playback(booth,long_player_stream):
    app,driver,base,tmp=booth
    with app.app_context():
        station=Station.query.filter_by(slug='test-station').one()
        station.request_settings={'enabled':True}
        db.session.commit()
    driver.get(base+'/player/test-station')
    driver.find_element(By.ID,'play-button').click();playing(driver)
    js(driver,'window.originalAudio=document.getElementById("station-audio")')
    driver.find_element(By.ID,'request-open').click()
    driver.switch_to.frame(driver.find_element(By.CSS_SELECTOR,'#request-dialog iframe'))
    wait_text(driver,'#songs','Verified Test Track')
    driver.find_element(By.ID,'query').send_keys('Verified')
    previous=driver.find_element(By.CSS_SELECTOR,'#songs button')
    driver.find_element(By.CSS_SELECTOR,'#search button').click()
    WebDriverWait(driver,10).until(EC.staleness_of(previous))
    wait_text(driver,'#songs','Verified Test Track')
    driver.find_element(By.CSS_SELECTOR,'#songs button').click()
    wait_text(driver,'#notice','Request received')
    driver.switch_to.default_content()
    playing(driver)
    driver.find_element(By.ID,'request-close').click()
    assert js(driver,'return originalAudio===document.getElementById("station-audio")')
    assert len(long_player_stream)==1
    with app.app_context():
        assert ListenerRequest.query.one().status=='pending'
        Station.query.filter_by(slug='test-station').one().request_settings={'enabled':False}
        db.session.commit()
    driver.refresh()
    assert not driver.find_elements(By.ID,'request-open')
    assert not driver.find_elements(By.ID,'request-dialog')


@pytest.mark.parametrize('failure',['none','context','analyser'])
def test_no_capture_audio_graph_and_failure_isolation(booth,long_player_stream,failure):
    app,driver,base,tmp=booth
    script='''HTMLMediaElement.prototype.captureStream=undefined;HTMLMediaElement.prototype.mozCaptureStream=undefined;
    window.audioProbe={peak:0,sources:0};const create=AudioContext.prototype.createMediaElementSource;
    AudioContext.prototype.createMediaElementSource=function(a){audioProbe.sources++;return create.call(this,a)};
    const sample=AnalyserNode.prototype.getByteFrequencyData;
    AnalyserNode.prototype.getByteFrequencyData=function(a){sample.call(this,a);audioProbe.peak=Math.max(audioProbe.peak,...a)};'''
    if failure=='context':script+='window.AudioContext=class{constructor(){throw Error("context unavailable")}};'
    if failure=='analyser':script+='AudioContext.prototype.createAnalyser=function(){throw Error("analyser unavailable")};'
    driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument',{'source':script})
    driver.get(base+'/player/test-station')
    # Open before playing, then start through the normal transport gesture.
    driver.find_element(By.ID,'visualizer-open').click()
    driver.find_element(By.ID,'visualizer-close').click()
    driver.find_element(By.ID,'play-button').click();playing(driver)
    js(driver,'window.originalAudio=document.getElementById("station-audio");window.originalSource=originalAudio.currentSrc')
    driver.find_element(By.ID,'visualizer-open').click()
    if failure=='none':
        WebDriverWait(driver,10).until(lambda d:js(d,'return audioProbe.peak>0'))
        for mode in ('fractal','spectrum','waveform','particles','ambient'):
            Select(driver.find_element(By.ID,'visual-mode')).select_by_value(mode)
            assert driver.find_element(By.ID,'player-visual').get_attribute('data-analysis')=='live'
        driver.find_element(By.ID,'visualizer-fullscreen').click()
        WebDriverWait(driver,5).until(lambda d:js(d,'return !!document.fullscreenElement'))
        driver.find_element(By.ID,'visualizer-fullscreen').click()
        js(driver,'CanvasRenderingContext2D.prototype.clearRect=()=>{throw Error("renderer failed")}')
        wait_text(driver,'#visual-status','Visualization unavailable')
    else:wait_text(driver,'#visual-status','unavailable')
    playing(driver)
    driver.find_element(By.ID,'visualizer-close').click();playing(driver)
    assert js(driver,'return originalAudio===document.getElementById("station-audio") && originalSource===originalAudio.currentSrc')
    assert len(long_player_stream)==1
    if failure=='none':
        assert js(driver,'return audioProbe.sources')==1
        assert js(driver,'return FreoAudioAnalysis.read(originalAudio).context.state')=='running'
        driver.find_element(By.ID,'play-button').click()
        driver.find_element(By.ID,'play-button').click();playing(driver)
        assert js(driver,'return audioProbe.sources')==2


@pytest.fixture
def pwa_desktop(monkeypatch,tmp_path):
    monkeypatch.setenv('XDG_DATA_HOME',str(tmp_path/'desktop-data'))
    monkeypatch.setenv('XDG_CONFIG_HOME',str(tmp_path/'desktop-config'))


def test_public_pwa_installability_and_offline(pwa_desktop,booth):
    app,driver,base,tmp=booth
    driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument',{'source':"window.installEvent=null;window.addEventListener('beforeinstallprompt',e=>window.installEvent=e)"})
    driver.get(base+'/player/test-station')
    assert driver.find_element(By.CSS_SELECTOR,'.radio-vinyl').is_displayed()
    driver.execute_async_script('navigator.serviceWorker.ready.then(()=>arguments[0](true))')
    WebDriverWait(driver,15).until(lambda d:not d.execute_cdp_cmd('Page.getInstallabilityErrors',{})['installabilityErrors'])
    WebDriverWait(driver,15).until(lambda d:d.find_element(By.ID,'install-freo').is_displayed())
    assert js(driver,'return installEvent.isTrusted')
    assert js(driver,'return document.querySelector("link[rel=manifest]").href').endswith('/player/test-station/manifest.webmanifest')
    # Browser reports a real install opportunity; synthetic events are never used here.
    WebDriverWait(driver,10).until(lambda d:js(d,'return !!navigator.serviceWorker.controller'))
    driver.execute_cdp_cmd('Network.enable',{})
    driver.execute_cdp_cmd('Network.setCacheDisabled',{'cacheDisabled':True})
    target=next(t for t in driver.execute_cdp_cmd('Target.getTargets',{})['targetInfos'] if t['type']=='service_worker' and t['url'].endswith('/player/sw.js'))
    session=driver.execute_cdp_cmd('Target.attachToTarget',{'targetId':target['targetId'],'flatten':False})['sessionId']
    def worker_network(identifier,offline):
        driver.execute_cdp_cmd('Target.sendMessageToTarget',{'sessionId':session,'message':json.dumps(dict(id=identifier,method='Network.emulateNetworkConditions',params=dict(offline=offline,latency=0,downloadThroughput=-1,uploadThroughput=-1)))})
    driver.execute_cdp_cmd('Target.sendMessageToTarget',{'sessionId':session,'message':json.dumps(dict(id=1,method='Network.enable',params={}))})
    worker_network(2,True)
    driver.execute_cdp_cmd('Network.emulateNetworkConditions',{'offline':True,'latency':0,'downloadThroughput':0,'uploadThroughput':0})
    try:
        driver.refresh();wait_text(driver,'body','You’re offline')
        assert not driver.find_elements(By.TAG_NAME,'audio') and not driver.find_elements(By.TAG_NAME,'button')
    finally:
        worker_network(3,False)
        driver.execute_cdp_cmd('Network.emulateNetworkConditions',{'offline':False,'latency':0,'downloadThroughput':-1,'uploadThroughput':-1})
    driver.refresh();WebDriverWait(driver,10).until(lambda d:d.find_elements(By.ID,'play-button'))
    keys=driver.execute_async_script('caches.keys().then(async keys=>arguments[0](await Promise.all(keys.filter(k=>k.startsWith("freo-player")).map(async k=>(await (await caches.open(k)).keys()).map(r=>r.url)))))')
    assert all('/player/offline.html' in u or '/static/studio-' in u for group in keys for u in group)

    manifest_id=base+'/player/test-station'
    original=driver.current_window_handle
    driver.execute_cdp_cmd('PWA.install',{'manifestId':manifest_id,'installUrlOrBundleUrl':manifest_id})
    try:
        # CDP's URL installer has a separate native Open-in-window preference.
        driver.execute_cdp_cmd('PWA.changeAppUserSettings',{'manifestId':manifest_id,'displayMode':'standalone'})
        target=driver.execute_cdp_cmd('PWA.launch',{'manifestId':manifest_id})['targetId']
        WebDriverWait(driver,10).until(lambda d:len(d.window_handles)>1)
        driver.switch_to.window(next(handle for handle in driver.window_handles if handle!=original))
        WebDriverWait(driver,10).until(lambda d:d.find_elements(By.ID,'play-button'))
        assert driver.current_url==manifest_id
        assert js(driver,'return matchMedia("(display-mode: standalone)").matches')
        assert not driver.find_element(By.ID,'install-freo').is_displayed()
        assert driver.find_element(By.CSS_SELECTOR,'.radio-vinyl').is_displayed()
    finally:
        driver.switch_to.window(original)
        driver.execute_cdp_cmd('PWA.uninstall',{'manifestId':manifest_id})


@pytest.mark.parametrize('codec',['mp3','aac'])
def test_no_capture_compressed_streams(booth,monkeypatch,codec):
    import subprocess
    from flask import Response
    app,driver,base,tmp=booth
    audio=subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','sine=frequency=440:duration=90',
        '-c:a','libmp3lame' if codec=='mp3' else 'aac','-b:a','192k','-f','mp3' if codec=='mp3' else 'adts','pipe:1'],check=True,capture_output=True).stdout
    monkeypatch.setitem(app.view_functions,'test_monitor_stream',lambda:Response(audio,mimetype='audio/mpeg' if codec=='mp3' else 'audio/aac'))
    driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument',{'source':'HTMLMediaElement.prototype.captureStream=undefined;HTMLMediaElement.prototype.mozCaptureStream=undefined;'})
    driver.get(base+'/player/test-station')
    driver.find_element(By.ID,'play-button').click();playing(driver)
    driver.find_element(By.ID,'visualizer-open').click()
    WebDriverWait(driver,10).until(lambda d:js(d,'const g=FreoAudioAnalysis.read(document.getElementById("station-audio"));if(!g?.analyser)return false;const data=new Uint8Array(512);g.analyser.getByteFrequencyData(data);return Math.max(...data)>0'))
    driver.find_element(By.ID,'visualizer-close').click();playing(driver)


@pytest.mark.parametrize('unavailable', [False, True])
def test_iphone_hides_volume_preserves_mute_and_playback(booth, long_player_stream, unavailable):
    app,driver,base,tmp=booth
    script = """HTMLMediaElement.prototype.captureStream=undefined;HTMLMediaElement.prototype.mozCaptureStream=undefined;
    Object.defineProperty(HTMLMediaElement.prototype,'volume',{get(){return 1},set(value){},configurable:true});"""
    if unavailable: script += "window.AudioContext=class{constructor(){throw Error('unavailable')}};"
    driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument',{'source':script})
    driver.get(base+'/player/test-station')
    driver.set_window_size(390,844)
    assert not driver.find_element(By.ID,'volume').is_displayed()
    assert not driver.find_element(By.ID,'volume').is_enabled()
    assert driver.find_element(By.ID,'volume-help').is_displayed()
    driver.find_element(By.ID,'play-button').click();playing(driver)
    if not unavailable:
        WebDriverWait(driver,10).until(lambda d:js(d,'return !!FreoAudioAnalysis.read(document.getElementById("station-audio"))?.gain'))
        js(driver,'const g=FreoAudioAnalysis.read(document.getElementById("station-audio"));window.outputProbe=g.context.createAnalyser();g.gain.connect(outputProbe)')
    def rms():
        return driver.execute_async_script('const done=arguments[0];setTimeout(()=>{const a=new Float32Array(2048);outputProbe.getFloatTimeDomainData(a);done(Math.sqrt(a.reduce((s,v)=>s+v*v,0)/a.length))},300)')
    if not unavailable: assert rms()>0
    driver.find_element(By.ID,'mute-button').click()
    if not unavailable: assert rms()<.00001
    else: assert js(driver,'return document.getElementById("station-audio").muted')
    driver.find_element(By.ID,'play-button').click()
    driver.find_element(By.ID,'play-button').click();playing(driver)
    assert driver.find_element(By.ID,'mute-button').get_attribute('aria-pressed')=='true'
    driver.find_element(By.ID,'mute-button').click();playing(driver)
    assert not driver.find_element(By.ID,'volume').is_displayed()
    if not unavailable:
        assert js(driver,'return FreoAudioAnalysis.read(document.getElementById("station-audio")).gain.gain.value') > .99
