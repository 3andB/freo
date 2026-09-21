"""Delayed page work and retained resources across real workspace navigation."""
import json
import os
from pathlib import Path

import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from tests.test_live_browser import booth, app_fixture


def navigate(driver, path):
    driver.execute_async_script('FreoWorkspace.navigate(arguments[0]).then(arguments[1])', path)


@pytest.mark.parametrize('result', ['success', 'error'])
@pytest.mark.parametrize('return_first', [False, True])
def test_booth_body_completion_after_navigation_is_discarded(booth, result, return_first):
    _, driver, base, _ = booth
    wait = WebDriverWait(driver, 15)
    wait.until(lambda d: d.find_element(By.ID, 'morph-text').text == 'Verified Test Track')
    driver.execute_script('''
      window.pageErrors = [];
      window.addEventListener('unhandledrejection', e => pageErrors.push(String(e.reason)));
      window.addEventListener('error', e => pageErrors.push(e.message));
      const scope = FreoPage, original = scope.fetch.bind(scope);
      scope.fetch = async (url, options) => {
        const response = await original(url, options);
        if (!String(url).endsWith('/live-status')) return response;
        const payload = await response.json();
        if (payload.current) payload.current.title = 'STALE OLD PAGE';
        return {ok:true, json:() => new Promise((resolve, reject) => {
          window.releaseOldBody = () => arguments[0] === 'error'
            ? reject(new Error('Delayed old page error')) : resolve(payload);
        })};
      };
    ''', result)
    wait.until(lambda d: d.execute_script('return !!window.releaseOldBody'))
    navigate(driver, base + '/admin/stations/test-station/schedule-studio/control')
    if return_first:
        navigate(driver, base + '/admin/stations/test-station/live')
        wait.until(lambda d: d.find_element(By.ID, 'morph-text').text == 'Verified Test Track')
        # The delayed old result must not paint a newly mounted Booth either.
        driver.execute_script('''
          window.sawOldPage = false;
          new MutationObserver(() => {if (document.getElementById('morph-text')?.textContent === 'STALE OLD PAGE') sawOldPage = true;})
            .observe(document.getElementById('morph-text'), {childList:true, subtree:true});
        ''')
    driver.execute_async_script('releaseOldBody(); setTimeout(arguments[0], 100)')
    assert driver.execute_script('return pageErrors') == []
    if return_first:
        assert not driver.execute_script('return sawOldPage')
    if not return_first:
        assert driver.find_elements(By.ID, 'station-control')
        navigate(driver, base + '/admin/stations/test-station/live')
    wait.until(lambda d: d.find_element(By.ID, 'morph-text').text == 'Verified Test Track')
    assert driver.execute_script('return pageErrors') == []


def test_accepted_cue_edit_response_after_departure_is_not_retried(booth):
    from app.models import BoothCue
    app, driver, base, _ = booth
    wait = WebDriverWait(driver, 15)
    wait.until(lambda d: d.find_elements(By.CSS_SELECTOR, '[data-add-cue]'))
    driver.execute_script('''
      window.pageErrors = []; window.cueRequests = 0;
      window.addEventListener('unhandledrejection', e => pageErrors.push(String(e.reason)));
      window.addEventListener('error', e => pageErrors.push(e.message));
      const scope = FreoPage, original = scope.fetch.bind(scope);
      scope.fetch = async (url, options) => {
        const response = await original(url, options);
        if (!String(url).endsWith('/cue-list') || options.method !== 'POST') return response;
        window.cueRequests++;
        const payload = await response.json();
        return {ok:response.ok, headers:response.headers, json:() => new Promise(resolve => {
          window.releaseCueBody = () => resolve(payload);
        })};
      };
    ''')
    driver.find_element(By.CSS_SELECTOR, '[data-add-cue]').click()
    wait.until(lambda d: d.execute_script('return !!window.releaseCueBody'))
    navigate(driver, base + '/admin/stations/test-station/schedule-studio/control')
    driver.execute_async_script('releaseCueBody(); setTimeout(arguments[0], 100)')
    assert driver.execute_script('return pageErrors') == []
    assert driver.execute_script('return cueRequests') == 1
    with app.app_context():
        assert len(BoothCue.query.one().entries) == 1
    navigate(driver, base + '/admin/stations/test-station/live')
    wait.until(lambda d: len(d.find_elements(By.CSS_SELECTOR, '#booth-cue-list [data-cue-entry]')) == 1)


@pytest.mark.skipif(not os.environ.get('FREO_NAVIGATION_ROUNDS'), reason='Opt-in navigation retention diagnostic')
def test_navigation_retained_resources(booth):
    _, driver, base, tmp_path = booth
    driver.execute_cdp_cmd('Performance.enable', {})
    driver.execute_script('window.navigationErrors=[]; window.addEventListener("unhandledrejection", e=>navigationErrors.push(String(e.reason))); window.addEventListener("error", e=>navigationErrors.push(e.message));')
    rounds = int(os.environ['FREO_NAVIGATION_ROUNDS'])
    samples = []
    output = Path(os.environ.get('FREO_NAVIGATION_EVIDENCE', str(tmp_path)))
    output.mkdir(parents=True, exist_ok=True)
    driver.execute_script('FreoMonitor.audio.loop = true; window.diagnosticMonitor = FreoMonitor.audio')
    driver.find_element(By.CSS_SELECTOR, '[data-monitor-station="test-station"] button').click()
    WebDriverWait(driver, 15).until(lambda d: d.execute_script('return !FreoMonitor.audio.paused && FreoMonitor.audio.currentTime > 0'))
    for n in range(rounds + 1):
        if n:
            navigate(driver, base + '/admin/stations/test-station/live')
        navigate(driver, base + '/admin/stations/test-station/schedule-studio/control')
        assert driver.execute_script('return FreoMonitor.audio === diagnosticMonitor && !FreoMonitor.audio.paused')
        if n % 10 == 0 or n == rounds:
            raw = driver.execute_cdp_cmd('Memory.getDOMCounters', {})
            driver.execute_cdp_cmd('HeapProfiler.collectGarbage', {})
            retained = driver.execute_cdp_cmd('Memory.getDOMCounters', {})
            metrics = {v['name']: v['value'] for v in driver.execute_cdp_cmd('Performance.getMetrics', {})['metrics']}
            samples.append(dict(round=n, raw=raw, retained=retained, heap=metrics['JSHeapUsedSize']))
            (output/'navigation-resources.json').write_text(json.dumps(samples, indent=2))
    (output/'browser-errors.json').write_text(json.dumps(driver.execute_script('return navigationErrors'), indent=2))
    assert driver.execute_script('return navigationErrors') == []
    if rounds >= 30:
        warm = samples[1]['retained']
        # Compare like-for-like pages after GC in this diagnostic only. Old
        # documents/listeners must be collectable; natural heap size is noisy.
        for sample in samples[2:]:
            assert sample['retained']['documents'] <= warm['documents'] + 2
            assert sample['retained']['jsEventListeners'] <= warm['jsEventListeners'] + 20
            assert sample['retained']['nodes'] <= warm['nodes'] + 1000
