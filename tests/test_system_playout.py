"""UI commands verified against real worker events and private encoded audio."""
import json
import os
import time
import wave
from array import array

import pytest
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import StaleElementReferenceException

from app.models import (BoothCue, ChannelSchedule, LiveControlCommand, LiveQueueSnapshot,
                        ScheduleTransition, SelectionDecision, Station)
from app.services.playout_queue import mixer_state, program_decision_id
from tests.system_harness import system_stack, wait_for

pytestmark = pytest.mark.skipif(os.environ.get('FREO_SYSTEM_TEST') != '1',
    reason='Opt-in real browser/worker/stream test: FREO_SYSTEM_TEST=1')


def navigate(driver, path, root_id):
    driver.execute_script('FreoWorkspace.navigate(arguments[0])', path)
    # The DOM is replaced before the destination scripts finish loading.
    WebDriverWait(driver, 30).until(lambda d: d.find_elements(By.ID, root_id) and
        d.execute_script('return !document.documentElement.classList.contains("is-navigating")'))


@pytest.fixture
def system_browser(system_stack):
    stack = system_stack
    options = Options()
    options.binary_location = '/usr/bin/chromium-browser'
    for argument in ['--headless=new', '--no-sandbox', '--disable-dev-shm-usage',
                     '--window-size=1440,1100', f'--user-data-dir={stack.root}/chrome']:
        options.add_argument(argument)
    options.set_capability('goog:loggingPrefs', {'browser': 'ALL'})
    driver = webdriver.Chrome(service=Service('/usr/bin/chromedriver'), options=options)
    driver.set_page_load_timeout(30)
    driver.execute_cdp_cmd('Performance.enable', {})
    stack.driver = driver
    try:
        driver.get(stack.base + '/admin/login')
        driver.find_element(By.NAME, 'email').send_keys('admin@example.test')
        driver.find_element(By.NAME, 'password').send_keys('test-password-long-enough')
        driver.find_element(By.CSS_SELECTOR, '.login-card button[type=submit]').click()
        WebDriverWait(driver, 15).until(lambda d: d.find_elements(By.CSS_SELECTOR, '.admin-sidebar'))
        yield stack, driver
    finally:
        try:
            driver.save_screenshot(str(stack.evidence/'browser-final.png'))
            from tests.browser_evidence import drain_browser_console
            drain_browser_console(stack)
            log_path = stack.evidence/'browser-console.jsonl'
            logs = [json.loads(line) for line in log_path.read_text().splitlines()] if log_path.exists() else []
            (stack.evidence/'browser-console.json').write_text(json.dumps(logs, indent=2))
            (stack.evidence/'browser.html').write_text(driver.page_source)
            # Network errors are deliberate in the disconnect scenario. An
            # uncaught JavaScript exception is never an expected recovery step.
            assert not [entry for entry in logs if entry['level'] == 'SEVERE'
                        and entry.get('source') == 'javascript'], logs
        finally:
            driver.quit()


def test_station_control_booth_audio_and_recovery(system_browser):
    stack, driver = system_browser
    wait = WebDriverWait(driver, 25, ignored_exceptions=(StaleElementReferenceException,))
    def click(selector):
        wait.until(lambda d: d.find_element(By.CSS_SELECTOR, selector).is_enabled())
        driver.find_element(By.CSS_SELECTOR, selector).click()
    def text(selector, value):
        wait.until(lambda d: value in d.find_element(By.CSS_SELECTOR, selector).text)
    def current():
        return stack.query(lambda: program_decision_id(stack.slug))
    def mode(value):
        return stack.query(lambda: ChannelSchedule.query.one().mode == value)
    wait_for(current, description='initial automatic playback')
    driver.get(stack.base + '/admin/stations/test-station/schedule-studio/control')
    for target in ('BLOCKS', 'CALENDAR', 'SIMPLE'):
        click(f'[data-switch-mode="{target}"]')
        text('dialog[open]', 'Will play now:')
        click('dialog[open] .admin-primary')
        wait_for(lambda: mode(target), description=f'worker-applied {target} mode')
        text('#control-status-heading', target.title() + ' mode')
        assert stack.query(lambda: ScheduleTransition.query.order_by(
            ScheduleTransition.created_at.desc()).first().decision.status) == 'started'
    assert stack.query(lambda: ScheduleTransition.query.count()) == 3

    # A real streamed source drives the persistent browser monitor.
    click('[data-monitor-station="test-station"] button')
    wait.until(lambda d: d.execute_script('return FreoMonitor.audio.currentTime > 0 && !FreoMonitor.audio.paused'))
    driver.execute_script('window.originalMonitor = FreoMonitor.audio')
    navigate(driver, '/admin/stations/test-station/live', 'dj-booth')
    assert driver.execute_script('return originalMonitor === FreoMonitor.audio && !FreoMonitor.audio.paused')
    click('.mode-button[data-mode="DJ_BOOTH"]')
    wait.until(lambda d: d.find_element(By.ID, 'dj-booth').get_attribute('data-mode') == 'DJ_BOOTH')
    # Load the 180-second fixture using the actual music picker and deck binding.
    click('.cue-picker-button[data-target="A"]')
    driver.find_element(By.ID, 'song-picker-search').send_keys('System Tone 880')
    text('#song-picker-results', 'System Tone 880')
    click('#song-picker-results button')
    text('#deck-a-state', 'READY')
    click('[data-deck="A"][data-operation="PLAY"]')
    wait_for(lambda: stack.query(lambda: mixer_state(stack.slug)['a_playing']), description='deck A playing')
    expected = stack.query(lambda: LiveControlCommand.query.filter_by(action='DECK_LOAD').order_by(
        LiveControlCommand.id.desc()).first().target_decision_id)
    wait_for(lambda: current() == expected, description='deck A on program')
    audio = stack.capture(name='deck-a.wav')
    with wave.open(str(audio)) as recording:
        samples = array('h', recording.readframes(recording.getnframes()))
        rate = recording.getframerate()
    # Distinct tones identify actual audio, not just a nonzero meter or metadata.
    segment = samples[rate:2*rate]
    crossings = sum(a < 0 <= b for a, b in zip(segment, segment[1:]))
    assert abs(crossings - 880) < 15, f'Expected deck A tone, heard {crossings} Hz'

    click('[data-fire-cart]')
    wait_for(lambda: stack.query(lambda: SelectionDecision.query.filter_by(
        playback_bus='CART', status='started').count()) == 1, description='real cart start')
    wait.until(lambda d: d.find_element(By.CSS_SELECTOR, '[data-fire-cart]').is_enabled())
    wait_for(lambda: current() == expected, description='program returns after cart')

    # Reload and restart the real worker without changing the audible deck.
    stack.stop_worker()
    before = current()
    stack.start_worker()
    driver.refresh()
    text('#live-current h2', 'System Tone 880')
    assert current() == before
    # An offline browser must not stop server-side playback; status recovers.
    driver.execute_cdp_cmd('Network.enable', {})
    driver.execute_cdp_cmd('Network.emulateNetworkConditions', dict(
        offline=True, latency=0, downloadThroughput=-1, uploadThroughput=-1))
    try:
        text('#booth-notice', 'Connection')
        assert current() == expected
    finally:
        driver.execute_cdp_cmd('Network.emulateNetworkConditions', dict(
            offline=False, latency=0, downloadThroughput=-1, uploadThroughput=-1))
    wait.until(lambda d: d.find_element(By.CSS_SELECTOR, '[data-deck="A"][data-operation="PAUSE"]').is_enabled())

    # The existing workflow deliberately returns to AUTO after DJ audio stops.
    click('[data-deck="A"][data-operation="PAUSE"]')
    wait_for(lambda: stack.query(lambda: Station.query.filter_by(slug=stack.slug).one().automation.operator_mode) == 'AUTO',
             description='existing automatic return after paused DJ audio')
    wait_for(lambda: current() not in (None, expected), description='automatic playback after DJ pause')

    driver.get(stack.base + '/admin/stations/test-station/schedule-studio/control')
    click('[data-switch-mode="BLOCKS"]')
    text('dialog[open]', 'Will play now:')
    click('dialog[open] .admin-primary')
    wait_for(lambda: mode('BLOCKS'), description='return from DJ to schedule')
    wait_for(lambda: current() not in (None, expected), description='scheduled audio resumed')
    # OFF/ON uses the production broadcast handler with a private process adapter.
    click('#master-broadcast-toggle')
    wait_for(lambda: not stack.online(), description='private stream stopped')
    text('#broadcast-message', 'Broadcast is OFF')
    click('#master-broadcast-toggle')
    wait_for(stack.online, timeout=120, description='private stream restarted')
    wait_for(current, timeout=30, description='automatic playback after engine restart')
    text('#broadcast-message', 'Station is broadcasting')
    assert stack.query(lambda: Station.query.filter_by(slug='second-station').one().desired_state) == 'stopped'
    assert stack.query(lambda: LiveControlCommand.query.filter_by(status='pending').count()) == 0
    for width in (390, 820, 1440):
        driver.set_window_size(width, 1000)
        assert driver.execute_script('return document.documentElement.scrollWidth <= innerWidth')
    (stack.evidence/'journey.json').write_text(json.dumps(dict(
        switches=4, deck_frequency_hz=crossings, worker_ticks=stack.tick_count,
        worker_restart=True, engine_restart=True, browser_disconnect=True), indent=2))


def test_browser_cue_cycles_through_event_and_worker_restart(system_browser):
    from datetime import datetime, timedelta, timezone
    from selenium.webdriver.common.keys import Keys
    from app.extensions import db
    from app.models import CuePlayback, TimedEventOccurrence
    from app.services.timed_events import save_event
    stack, driver = system_browser
    wait = WebDriverWait(driver, 20, ignored_exceptions=(StaleElementReferenceException,))
    driver.get(stack.base + '/admin/stations/test-station/live')
    driver.find_element(By.CSS_SELECTOR, '.mode-button[data-mode="DJ_BOOTH"]').click()
    wait.until(lambda d: d.find_element(By.ID, 'dj-booth').get_attribute('data-mode') == 'DJ_BOOTH')
    def rows():
        return driver.find_elements(By.CSS_SELECTOR, '#booth-cue-list [data-cue-entry]')
    for count, identifier in enumerate(stack.track_uuids[:2], 1):
        selector = f'.song-card[data-id="{identifier}"] [data-add-cue]'
        wait.until(lambda d: d.find_element(By.CSS_SELECTOR, selector).is_enabled())
        driver.find_element(By.CSS_SELECTOR, selector).click()
        wait.until(lambda d: len(rows()) == count)
    first = rows()[0].get_attribute('data-cue-entry')
    rows()[1].find_element(By.CSS_SELECTOR, '.cue-handle').send_keys(Keys.ALT, Keys.ARROW_UP, Keys.NULL)
    wait.until(lambda d: rows()[0].get_attribute('data-cue-entry') != first)
    driver.find_element(By.ID, 'cue-auto').click()
    def starts():
        return stack.query(lambda: SelectionDecision.query.filter_by(selection_method='cue_auto', status='started').count())
    wait_for(lambda: starts() >= 2, timeout=40, description='real AUTO_CUE cycling')
    assert stack.query(lambda: CuePlayback.query.filter(CuePlayback.completed_at.isnot(None)).count()) >= 1
    with stack.app.app_context():
        due = datetime.now(timezone.utc) + timedelta(seconds=1)
        event = save_event(stack.slug, name='System cue event', recurrence_type='ONE_TIME',
            content_type='TRACK', content_identifier=stack.track_uuids[3],
            local_date=due.date().isoformat(), local_time=due.strftime('%H:%M:%S'),
            late_tolerance_seconds=45, interrupt_dj=True)
        occurrence_id = event.occurrences[0].id
        db.session.commit()
    # Leaving the booth must not stop the server-owned cue or upcoming event.
    navigate(driver, '/admin/stations/test-station/schedule-studio/control', 'station-control')
    wait_for(lambda: stack.query(lambda: db.session.get(TimedEventOccurrence, occurrence_id).state) == 'COMPLETED',
             timeout=40, description='event completes during unattended cue playback')
    before = starts()
    stack.stop_worker()
    stack.start_worker()
    wait_for(lambda: starts() > before, timeout=30, description='cue progresses after worker restart')
    assert stack.query(lambda: BoothCue.query.one().auto_enabled)
    navigate(driver, '/admin/stations/test-station/live', 'dj-booth')
    wait.until(lambda d: d.find_element(By.ID, 'cue-auto').get_attribute('aria-pressed') == 'true')
    assert len(rows()) == 2
    assert stack.query(lambda: Station.query.filter_by(slug=stack.slug).one().automation.operator_mode) == 'DJ_BOOTH'


@pytest.mark.skipif(int(os.environ.get('FREO_SYSTEM_SOAK_SECONDS', '0')) < 120,
    reason='Endurance test requires FREO_SYSTEM_SOAK_SECONDS >= 120')
def test_system_endurance(system_browser):
    """Continuous UI-driven switching with real encoded audio and worker state."""
    from tests.soak_probe import SoakProbe
    seconds = int(os.environ['FREO_SYSTEM_SOAK_SECONDS'])
    stack, driver = system_browser
    wait = WebDriverWait(driver, 15, ignored_exceptions=(StaleElementReferenceException,))
    driver.get(stack.base + '/admin/stations/test-station/schedule-studio/control')
    wait_for(lambda: stack.query(lambda: program_decision_id(stack.slug)), description='soak initial playback')
    driver.find_element(By.CSS_SELECTOR, '[data-monitor-station="test-station"] button').click()
    wait.until(lambda d: d.execute_script('return !FreoMonitor.audio.paused && FreoMonitor.audio.currentTime > 0'))
    probe = SoakProbe(stack)
    probe.metrics.update(requested_seconds=seconds, switches=0, directed_switches=[],
                         maximum_handoff_seconds=0, maximum_ui_seconds=0, status='running')
    began = time.monotonic()
    next_switch = began
    modes = ['BLOCKS', 'CALENDAR', 'BLOCKS', 'SIMPLE', 'CALENDAR', 'SIMPLE']
    pairs = set()
    try:
        while time.monotonic()-began < seconds:
            probe.sample()
            assert not stack.errors, stack.errors
            if time.monotonic() >= next_switch:
                before = stack.query(lambda: ChannelSchedule.query.one().mode)
                target = modes[probe.metrics['switches'] % len(modes)]
                selector = f'[data-switch-mode="{target}"]'
                wait.until(lambda d: d.find_element(By.CSS_SELECTOR, selector).is_enabled())
                driver.find_element(By.CSS_SELECTOR, selector).click()
                wait.until(lambda d: d.find_elements(By.CSS_SELECTOR, 'dialog[open] .admin-primary'))
                started = time.monotonic()
                driver.find_element(By.CSS_SELECTOR, 'dialog[open] .admin-primary').click()
                def applied():
                    def query():
                        command = ScheduleTransition.query.order_by(ScheduleTransition.created_at.desc()).first()
                        assert command is None or command.state != 'FAILED', command.error
                        if command and command.mode == target and command.state == 'APPLIED':
                            assert command.decision.status == 'started'
                            return command.decision_id
                    return stack.query(query)
                identifier = wait_for(applied, timeout=10, description='soak handoff')
                handoff = time.monotonic()-started
                wait.until(lambda d: target.title()+' mode' in d.find_element(By.ID, 'control-status-heading').text)
                ui_elapsed = time.monotonic()-started
                assert ui_elapsed <= 15, 'Station Control did not converge on applied mode'
                # A short target may already have ended by the next observation.
                # Require real start evidence; current-ID equality is not history.
                events = (stack.runtime/stack.slug/'events.log').read_text().splitlines()
                assert any(line.startswith(str(identifier)+' ') for line in events)
                probe.metrics['maximum_handoff_seconds'] = max(probe.metrics['maximum_handoff_seconds'], handoff)
                probe.metrics['maximum_ui_seconds'] = max(probe.metrics['maximum_ui_seconds'], ui_elapsed)
                probe.metrics['switches'] += 1
                pairs.add((before, target))
                probe.metrics['directed_switches'] = sorted(pairs)
                probe.metrics['started'] = stack.query(lambda: SelectionDecision.query.filter_by(status='started').count())
                next_switch = started + 15
                # Repeated workspace mounting exposes accumulated timers/listeners.
                if probe.metrics['switches'] % 6 == 0:
                    navigate(driver, '/admin/stations/test-station/live', 'dj-booth')
                    navigate(driver, '/admin/stations/test-station/schedule-studio/control', 'station-control')
            time.sleep(.5)
        assert pairs == {(a, b) for a in modes for b in modes if a != b}
        probe.sample()
        probe.metrics['status'] = 'passed'
    except BaseException as error:
        probe.metrics.update(status='failed', failure=f'{type(error).__name__}: {error}')
        raise
    finally:
        probe.close()
