"""Real-time programme playback with music, hour boundaries, events and DJ use."""
import json
import os
import time
from datetime import datetime, timedelta, timezone

import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

from app.extensions import db
from app.models import SelectionDecision, Station, TimedEventOccurrence
from app.services.playout_queue import program_decision_id
from tests.programme_harness import ProgrammeStack
from tests.system_harness import wait_for
from tests.test_system_playout import system_browser, navigate
from tests.soak_probe import SoakProbe

pytestmark = pytest.mark.skipif(os.environ.get('FREO_PROGRAMME_SECONDS', '0') == '0',
    reason='Opt-in real-time programme shift')


@pytest.fixture
def system_stack(monkeypatch, tmp_path):
    stack = ProgrammeStack(monkeypatch, tmp_path)
    try:
        with stack.app.app_context():
            stack.configure_shift()
        stack.start()
        yield stack
        assert not stack.errors, stack.errors
    finally:
        stack.close()


def aware(value):
    return value.replace(tzinfo=value.tzinfo or timezone.utc)


def test_three_hour_programme(system_browser):
    stack, driver = system_browser
    wait = WebDriverWait(driver, 20)
    driver.get(stack.base+'/admin/stations/test-station/schedule-studio/control')
    wait_for(lambda: stack.query(lambda: program_decision_id(stack.slug)), description='programme starts')
    driver.find_element(By.CSS_SELECTOR, '[data-monitor-station="test-station"] button').click()
    wait.until(lambda d: d.execute_script('return !FreoMonitor.audio.paused && FreoMonitor.audio.currentTime > 0'))
    probe = SoakProbe(stack, collect_issues=True)
    monitor_started = datetime.now(timezone.utc)
    probe.metrics.update(status='running', requested_seconds=stack.seconds, scenario='programme_shift',
        monitor_started_at=monitor_started.isoformat(),
        expected_finish_utc=(monitor_started+timedelta(seconds=stack.seconds)).isoformat(),
        events_completed=0, dj_takeovers_completed=0, metadata_checks=0, starts=0,
        programme_rotations_seen=[], local_dates_seen=[], local_hours_seen=[])
    began = time.monotonic()
    seen = set()
    seen_occurrences = set()
    previous = None
    stable_id = None
    stable_since = began
    rotations, dates, hours = set(), set(), set()
    takeovers = iter(stack.takeovers)
    next_dj = next(takeovers, None)
    dj_id = None
    dj_started = None
    completed_events = set()
    starts_log = stack.evidence/'programme-starts.jsonl'

    def audit():
        nonlocal previous
        with stack.app.app_context():
            for decision in SelectionDecision.query.filter_by(status='started').order_by(SelectionDecision.started_at, SelectionDecision.id):
                if decision.id in seen:
                    continue
                seen.add(decision.id)
                probe.check(decision.track_id in stack.assets, f'source:{decision.id}',
                            'Unexpected programme source', track_id=decision.track_id)
                if decision.track_id not in stack.assets:
                    previous = None
                    continue
                row = dict(id=decision.id, track_id=decision.track_id, title=decision.track.title,
                    method=decision.selection_method, occurrence=decision.schedule_occurrence,
                    selected=aware(decision.selected_at).isoformat(), started=aware(decision.started_at).isoformat())
                with starts_log.open('a') as output:
                    output.write(json.dumps(row)+'\n')
                if decision.selection_method == 'visual_schedule':
                    probe.check(decision.reason != 'default_playlist', f'default:{decision.id}',
                                'Programme fell back to default playlist', decision=row)
                    rotation = stack.expected_rotation(aware(decision.selected_at))
                    probe.check(decision.schedule_occurrence == stack.expected_occurrence(aware(decision.selected_at)),
                                f'occurrence:{decision.id}', 'Wrong scheduled programme/date', decision=row)
                    order = stack.rotations[rotation]['tracks']
                    probe.check(decision.track_id in order, f'membership:{decision.id}',
                                'Track outside scheduled playlist', decision=row)
                    if decision.schedule_occurrence not in seen_occurrences:
                        probe.check(decision.track_id == order[0], f'first:{decision.id}',
                                    'Programme did not begin with its configured first track', decision=row, expected=order[0])
                        seen_occurrences.add(decision.schedule_occurrence)
                    rotations.add(rotation)
                    if previous and previous['method']=='visual_schedule' and previous['occurrence']==row['occurrence'] and previous['track_id'] in order:
                        expected = order[(order.index(previous['track_id'])+1) % len(order)]
                        probe.check(decision.track_id == expected, f'order:{decision.id}',
                                    'Unexpected repeat/skip', previous=previous, decision=row, expected=expected)
                previous = row
            for identifier, expected in stack.expected_events.items():
                occurrence = db.session.get(TimedEventOccurrence, identifier)
                probe.check(occurrence.state not in ('FAILED','MISSED','CANCELLED'), f'event:{identifier}',
                            'Timed event failed', event=expected, state=occurrence.state, reason=occurrence.failure_reason)
                due = expected['due']
                if occurrence.started_at:
                    lag = aware(occurrence.started_at).timestamp()-due
                    limit = 15 if expected['mode']=='HARD' else (50 if stack.smoke else 330)
                    probe.check(-1 <= lag <= limit, f'event_timing:{identifier}',
                                'Event start outside tolerance', event=expected, lag=lag)
                if occurrence.state == 'COMPLETED':
                    probe.check(bool(occurrence.started_at and occurrence.completed_at), f'event_dates:{identifier}',
                                'Completed event missing actual start/end', event=expected)
                    completed_events.add(identifier)
                elif time.time() > due + (80 if stack.smoke else 390):
                    probe.check(False, f'event_overdue:{identifier}', 'Event did not complete', event=expected, state=occurrence.state)
            return program_decision_id(stack.slug)

    try:
        while time.monotonic()-began < stack.seconds:
            probe.sample()
            assert not stack.errors, stack.errors
            current = stack.query(audit)
            now = datetime.now(timezone.utc)
            local = now.astimezone(stack.zone)
            dates.add(local.date().isoformat())
            hours.add(local.strftime('%Y-%m-%d %H'))
            if current != stable_id:
                stable_id, stable_since = current, time.monotonic()
            if current and time.monotonic()-stable_since > 15:
                title = stack.query(lambda: db.session.get(SelectionDecision, current).track.title)
                displayed = driver.find_element(By.CSS_SELECTOR, '[data-now-title]').get_attribute('textContent')
                probe.check(displayed == title, f'metadata:{current}', 'Now playing disagrees with real engine',
                            displayed=displayed, expected=title)
                probe.metrics['metadata_checks'] += 1
            elapsed_plan = (now-stack.planned_start).total_seconds()
            if next_dj is not None and elapsed_plan >= next_dj and dj_id is None:
                navigate(driver, '/admin/stations/test-station/live', 'dj-booth')
                driver.find_element(By.CSS_SELECTOR, '.mode-button[data-mode="DJ_BOOTH"]').click()
                wait.until(lambda d: d.find_element(By.ID, 'dj-booth').get_attribute('data-mode')=='DJ_BOOTH')
                driver.find_element(By.CSS_SELECTOR, '.cue-picker-button[data-target="A"]').click()
                chosen = stack.assets[stack.music[-1]]
                driver.find_element(By.ID, 'song-picker-search').send_keys(chosen['title'])
                wait.until(lambda d: chosen['title'] in d.find_element(By.ID, 'song-picker-results').text)
                driver.find_element(By.CSS_SELECTOR, '#song-picker-results button').click()
                wait.until(lambda d: d.find_element(By.ID, 'deck-a-state').text == 'READY')
                driver.find_element(By.CSS_SELECTOR, '[data-deck="A"][data-operation="PLAY"]').click()
                def on_air():
                    identifier = program_decision_id(stack.slug)
                    decision = db.session.get(SelectionDecision, identifier) if identifier else None
                    return identifier if decision and decision.track_id==chosen['id'] and decision.selection_method!='visual_schedule' else None
                dj_id = wait_for(lambda: stack.query(on_air), timeout=20, description='DJ song on actual output')
                dj_started = time.monotonic()
                next_dj = next(takeovers, None)
            if dj_id is not None:
                mode = stack.query(lambda: Station.query.filter_by(slug=stack.slug).one().automation.operator_mode)
                if mode == 'AUTO':
                    probe.metrics['dj_takeovers_completed'] += 1
                    dj_id = None
                    navigate(driver, '/admin/stations/test-station/schedule-studio/control', 'station-control')
                else:
                    assert time.monotonic()-dj_started < stack.assets[stack.music[-1]]['duration']+45, 'DJ track did not return to AUTO'
            probe.metrics.update(starts=len(seen), events_completed=len(completed_events),
                programme_rotations_seen=sorted(rotations), local_dates_seen=sorted(dates), local_hours_seen=sorted(hours))
            time.sleep(1)
        stack.query(audit)
        probe.metrics.update(completed_duration=True, elapsed_seconds=round(time.monotonic()-began, 2),
                             starts=len(seen), events_completed=len(completed_events))
        assert completed_events == set(stack.expected_events), 'Not all scheduled events completed'
        assert probe.metrics['dj_takeovers_completed'] == len(stack.takeovers), 'Not all DJ takeovers completed'
        assert rotations == {0,1,2}, f'Missing programme sections: {rotations}'
        assert probe.metrics['metadata_checks'] > 20
        if not stack.smoke:
            assert len(dates) >= 2 and len(hours) >= 4, 'Did not cross real local midnight/hour boundaries'
            assert len(seen) >= 25, 'Unexpectedly few starts in a three-hour shift'
        assert stack.query(lambda: Station.query.filter_by(slug='second-station').one().desired_state)=='stopped'
        assert not probe.issues, f'Programme completed with {len(probe.issues)} recorded issues; see programme-issues.jsonl'
        probe.metrics['status'] = 'passed'
    except BaseException as error:
        probe.metrics.update(status='failed', failure=f'{type(error).__name__}: {error}')
        raise
    finally:
        probe.close()
