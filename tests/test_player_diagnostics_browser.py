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
    assert json.loads(js(driver, 'return copiedReport'))['build'] == 'v1-iphone-debug-1'
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
