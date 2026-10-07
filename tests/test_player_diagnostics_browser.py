"""Diagnostics observe decoded audio without taking ownership of playback."""
import json
import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select, WebDriverWait
from tests.test_live_browser import booth, app_fixture
from tests.test_player_visualizer_browser import long_player_stream, js, playing


@pytest.mark.parametrize('media_source', [False, True])
def test_report_retry_silence_reconnect_and_clipboard(booth, long_player_stream, media_source):
    app, driver, base, tmp = booth
    if media_source:
        driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {'source': '''
          HTMLMediaElement.prototype.captureStream=undefined;
          HTMLMediaElement.prototype.mozCaptureStream=undefined;
        '''})
    driver.set_window_size(430, 932)
    driver.get(base + '/player/test-station?audio_debug=1&private=test-secret')
    click = lambda name: driver.find_element(By.ID, name).click()
    def report():
        click('audio-diagnostics-refresh')
        return json.loads(driver.find_element(By.ID, 'audio-diagnostics-report').get_attribute('value'))
    click('play-button'); playing(driver); click('visualizer-open')
    Select(driver.find_element(By.ID, 'visual-mode')).select_by_value('spectrum')
    WebDriverWait(driver, 8).until(lambda d: js(d, 'return document.getElementById("player-visual").dataset.signal==="present"'))
    request_count = len(long_player_stream)
    click('audio-diagnostics-open')
    initial = report()
    assert initial['current']['signal'] == 'present'
    assert initial['current']['frequencyPeak'] > 0
    assert initial['current']['rms'] > 0
    assert initial['graph']['route'] == ('media-element-source' if media_source else 'capture-stream')
    assert initial['current']['sourceContextMatches'] is True
    assert initial['current']['analyserContextMatches'] is True
    if media_source:
        assert initial['current']['sourceMatchesElement'] is True
    assert initial['media']['lastLoad']['crossOrigin'] is None
    assert 'test-secret' not in json.dumps(initial)
    assert '_freo=' not in json.dumps(initial)
    assert js(driver, 'return document.getElementById("audio-diagnostics").scrollWidth<=innerWidth')
    assert len(long_player_stream) == request_count
    playing(driver)
    # Both clipboard success and Safari's manual-selection fallback.
    js(driver, '''Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async text=>{window.copiedReport=text}}})''')
    click('audio-diagnostics-copy')
    assert json.loads(js(driver, 'return copiedReport'))['build'] == 'v1-iphone-debug-2'
    js(driver, '''navigator.clipboard.writeText=async()=>{throw new Error('denied')}''')
    click('audio-diagnostics-copy')
    WebDriverWait(driver, 3).until(lambda d: 'Touch and hold' in d.find_element(By.ID, 'audio-diagnostics-status').text)
    assert js(driver, 'const t=document.getElementById("audio-diagnostics-report");return t.selectionEnd===t.value.length && t.selectionStart===0')
    # A diagnostic-only read failure cannot detach analysis or stop playback.
    js(driver, '''window.nativeFloat=AnalyserNode.prototype.getFloatTimeDomainData;
      AnalyserNode.prototype.getFloatTimeDomainData=function(){throw new Error('diagnostic read failed')};''')
    assert 'diagnostic read failed' in report()['current']['readError']
    playing(driver)
    js(driver, 'AnalyserNode.prototype.getFloatTimeDomainData=nativeFloat')
    click('audio-diagnostics-close')
    # Deliberate test-only silence, including a running graph after Retry.
    js(driver, '''window.nativeFreq=AnalyserNode.prototype.getByteFrequencyData;
      window.nativeWave=AnalyserNode.prototype.getByteTimeDomainData;
      AnalyserNode.prototype.getByteFrequencyData=function(a){a.fill(0)};
      AnalyserNode.prototype.getByteTimeDomainData=function(a){a.fill(128)};
      AnalyserNode.prototype.getFloatTimeDomainData=function(a){a.fill(0)};''')
    WebDriverWait(driver, 10).until(lambda d:d.find_element(By.ID, 'visualizer-retry').is_displayed())
    assert js(driver, 'return document.getElementById("player-visual").dataset.analysis') == 'waiting'
    click('visualizer-retry')
    driver.execute_async_script('setTimeout(arguments[0],600)')
    assert driver.find_element(By.ID, 'visualizer-retry').is_displayed()
    click('audio-diagnostics-open')
    silent = report()
    assert silent['current']['signal'] == 'silent'
    assert silent['current']['rms'] == 0
    assert any(e['type'] == 'visualizer-retry' and e['gesture'] for e in silent['events'])
    js(driver, 'for(let i=0;i<90;i++)document.dispatchEvent(new Event("freo:analysis"))')
    bounded = report()
    assert len(bounded['samples']) <= 40 and len(bounded['events']) <= 60
    playing(driver)
    click('audio-diagnostics-close')
    js(driver, '''AnalyserNode.prototype.getByteFrequencyData=nativeFreq;
      AnalyserNode.prototype.getByteTimeDomainData=nativeWave;
      AnalyserNode.prototype.getFloatTimeDomainData=nativeFloat;''')
    WebDriverWait(driver, 8).until(lambda d:not d.find_element(By.ID, 'visualizer-retry').is_displayed())
    # Let the real player retry automatically on the same native element.
    old_src = js(driver, 'return document.getElementById("station-audio").src')
    js(driver, '''const a=document.getElementById('station-audio');
      Object.defineProperty(a,'error',{configurable:true,value:{code:2}});
      a.dispatchEvent(new Event('error'));delete a.error;''')
    WebDriverWait(driver, 10).until(lambda d:js(d, 'return document.getElementById("station-audio").src') != old_src)
    WebDriverWait(driver, 10).until(lambda d:js(d, 'return document.getElementById("player-visual").dataset.signal==="present"'))
    click('audio-diagnostics-open'); reconnected = report()
    assert reconnected['current']['audio'] == initial['current']['audio']
    assert reconnected['current']['context'] == initial['current']['context']
    assert reconnected['current']['signal'] == 'present'
    if media_source:
        assert reconnected['current']['source'] == initial['current']['source']
        assert reconnected['current']['sourceMatchesElement'] is True
    click('audio-diagnostics-close'); click('visualizer-close'); playing(driver)


def test_source_control_cors_and_failures_preserve_playback(booth, long_player_stream, monkeypatch):
    import io
    import wave
    from flask import request, Response
    app, driver, base, tmp = booth
    original_stream = app.view_functions['test_monitor_stream']
    probes = []
    failure = {'http': False}
    def stream():
        response = original_stream()
        if not request.args.get('_freo_probe'):
            return response
        probes.append(True)
        if failure['http']:
            return Response('unavailable', status=503)
        # Complete, finite excerpt of the same actual decoded fixture audio.
        output = io.BytesIO()
        with wave.open(io.BytesIO(response.get_data()), 'rb') as source:
            with wave.open(output, 'wb') as target:
                target.setparams(source.getparams())
                target.writeframes(source.readframes(source.getframerate() * 3))
        return Response(output.getvalue(), mimetype='audio/wav')
    monkeypatch.setitem(app.view_functions, 'test_monitor_stream', stream)
    driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {'source': '''
      HTMLMediaElement.prototype.captureStream=undefined;
      HTMLMediaElement.prototype.mozCaptureStream=undefined;
    '''})
    driver.get(base + '/player/test-station?audio_debug=1&audio_cors=1')
    click = lambda name: driver.find_element(By.ID, name).click()
    def result():
        return js(driver, 'return JSON.parse(document.getElementById("audio-diagnostics-report").value)')
    def wait_status(value):
        WebDriverWait(driver, 15).until(lambda d: (result().get('sourceCheck') or {}).get('status') == value)
        return result()['sourceCheck']
    click('play-button'); playing(driver); click('visualizer-open')
    Select(driver.find_element(By.ID, 'visual-mode')).select_by_value('spectrum')
    WebDriverWait(driver, 8).until(lambda d: js(d, 'return document.getElementById("player-visual").dataset.signal==="present"'))
    click('audio-diagnostics-open')
    assert result()['media']['lastLoad']['crossOrigin'] == 'anonymous'
    assert result()['media']['requestMode'] == 'cors-comparison'
    assert not probes
    js(driver, '''window.keptGraph=FreoAudioAnalysis.read(document.getElementById('station-audio'));
      window.keptAnalyser=keptGraph.analyser;
      keptAnalyser.getFloatTimeDomainData=a=>a.fill(0);
      keptAnalyser.getByteFrequencyData=a=>a.fill(0);
      keptAnalyser.getByteTimeDomainData=a=>a.fill(128);''')
    click('audio-source-check'); checked = wait_status('complete')
    assert checked['outcome'] == 'native-signal-original-analyser-silent'
    assert checked['nativeTap']['peak'] > 0
    assert checked['decoded']['channels'][0]['peak'] > 0
    assert checked['control']['peak'] > 0 and checked['control']['maxRms'] > 0
    assert checked['nativeBefore']['peak'] == checked['nativeAfter']['peak'] == 0
    assert checked['response']['sameOrigin'] and checked['response']['status'] == 200
    assert checked['playbackGraphUnchanged'] and checked['mediaTimeAdvanced']
    assert checked['bytes'] <= checked['byteLimit'] and len(probes) == 1
    # Simulate absent delivery from the live source into the fresh tap, leaving
    # its existing audible output connected. Only this test overrides methods.
    js(driver, 'keptGraph.source.connect=target=>target;keptGraph.source.disconnect=()=>{}')
    click('audio-source-check'); checked = wait_status('complete')
    assert checked['outcome'] == 'decoded-signal-native-silent'
    assert checked['nativeTap']['peak'] == 0 and checked['control']['peak'] > 0
    assert checked['playbackGraphUnchanged'] and checked['mediaTimeAdvanced']
    js(driver, 'delete keptGraph.source.connect;delete keptGraph.source.disconnect')
    js(driver, '''delete keptAnalyser.getFloatTimeDomainData;delete keptAnalyser.getByteFrequencyData;delete keptAnalyser.getByteTimeDomainData;''')
    click('audio-diagnostics-refresh')
    assert result()['current']['signal'] == 'present'
    playing(driver)
    # HTTP and decoder failures leave the original source and analyser intact.
    failure['http'] = True
    click('audio-source-check'); failed = wait_status('error')
    assert failed['response']['status'] == 503
    playing(driver); failure['http'] = False
    js(driver, '''window.originalDecode=keptGraph.context.decodeAudioData;
      keptGraph.context.decodeAudioData=()=>Promise.reject(new DOMException('test decode failure','EncodingError'));''')
    click('audio-source-check'); failed = wait_status('error')
    assert failed['error']['name'] == 'EncodingError'
    playing(driver)
    js(driver, 'keptGraph.context.decodeAudioData=originalDecode')
    # Schedule the real Cancel action inside the page, so slow WebDriver calls
    # cannot consume the six-second capture deadline before clicking Cancel.
    def cancel_at(stage):
        driver.execute_script('''
          const stage=arguments[0];
          const listener=e=>{if(e.detail.status===stage){
            document.removeEventListener('freo:source-check',listener);
            setTimeout(()=>document.getElementById('audio-source-check').click(),100);
          }};
          document.addEventListener('freo:source-check',listener);
        ''', stage)
    # Cancellation while a probe is actually attached removes only its edge.
    cancel_at('checking')
    click('audio-source-check'); wait_status('cancelled')
    click('audio-diagnostics-refresh')
    assert result()['current']['signal'] == 'present'
    playing(driver)
    # A stalled sample request can be cancelled without touching the live stream.
    js(driver, '''window.originalFetch=window.fetch;
      window.fetch=(input,options)=>String(input).includes('_freo_probe')?
        new Promise((resolve,reject)=>options.signal.addEventListener('abort',()=>reject(new DOMException('cancelled','AbortError')),{once:true})):
        originalFetch(input,options);''')
    count = len(probes)
    cancel_at('capturing')
    click('audio-source-check'); wait_status('cancelled')
    js(driver, 'window.fetch=originalFetch')
    assert len(probes) == count
    assert js(driver, 'return FreoAudioAnalysis.read(document.getElementById("station-audio"))===keptGraph && keptGraph.analyser===keptAnalyser')
    playing(driver)
    # Automatic retries keep the pre-load CORS setting and actual audio samples.
    click('audio-diagnostics-close')
    old_src = js(driver, 'return document.getElementById("station-audio").src')
    js(driver, '''const a=document.getElementById('station-audio');Object.defineProperty(a,'error',{configurable:true,value:{code:2}});a.dispatchEvent(new Event('error'));delete a.error;''')
    WebDriverWait(driver, 10).until(lambda d: js(d, 'return document.getElementById("station-audio").src') != old_src)
    WebDriverWait(driver, 10).until(lambda d: js(d, 'return document.getElementById("player-visual").dataset.signal==="present"'))
    click('audio-diagnostics-open')
    assert result()['media']['lastLoad']['crossOrigin'] == 'anonymous'
    assert result()['current']['signal'] == 'present'
    click('audio-diagnostics-close'); click('visualizer-close'); playing(driver)
