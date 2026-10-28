"""Opt-in wall-clock statistics soak with private Icecast, playout and browser.

FREO_STATISTICS_SOAK_SECONDS=7200 runs two actual hours. All generated media,
observations, database and screenshots remain in temporary test directories.
"""
import csv
import io
import json
import math
import os
import threading
import time
from collections import Counter
from datetime import datetime, timezone
from urllib.request import Request

import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from app.extensions import db
from app.models import StatsBucket, SessionBucket, SelectionDecision
from app.services.statistics import collect, dashboard, geo
from app.services.statistics.storage import inventory
from tests.system_harness import SystemStack
from tests.test_system_playout import system_browser
from tests.browser_evidence import drain_browser_console

SECONDS = int(os.environ.get('FREO_STATISTICS_SOAK_SECONDS', '0'))
pytestmark = pytest.mark.skipif(SECONDS < 60, reason='Opt-in real-time statistics soak')
AGENTS = {
    'desktop': ('Mozilla/5.0 (Windows NT 10.0) Chrome/130.0 FreoSoakDesktop', 'desktop', 'Chrome'),
    'mobile': ('Mozilla/5.0 (iPhone) Version/18.0 Mobile Safari/605.1 FreoSoakMobile', 'mobile', 'Safari'),
    'tablet': ('Mozilla/5.0 (iPad) Version/18.0 Mobile Safari/605.1 FreoSoakTablet', 'tablet', 'Safari'),
    'player': ('VLC/3.0.20 FreoSoakPlayer', 'other/unknown', 'VLC'),
}


class Ledger:
    """Input ledger checks retained rollups against independently accumulated facts."""
    def __init__(self, evidence):
        self.evidence, self.previous = evidence, None
        self.totals = {s: dict(seconds=0, listeners=0, online=0, peak=0, transfer=0) for s in (0, 1, 2)}
        self.connections, self.closed = {}, []
        self.starts, self.devices, self.players = Counter(), Counter(), Counter()
        self.checks = self.samples = 0
        self.lock = threading.Lock()

    def observe(self, observations, now):
        if self.previous:
            at, previous = self.previous
            gap = now - at
            if 0 < gap <= 45:
                for scope in (1, 2):
                    before, after = previous[scope], observations[scope]
                    if before.get('listeners') is not None and after.get('listeners') is not None:
                        self.totals[scope]['seconds'] += gap
                        self.totals[scope]['listeners'] += gap * before['listeners']
                        self.totals[scope]['online'] += gap * bool(before.get('online'))
                    if (after.get('epoch') and after.get('source_epoch') and
                            (after.get('epoch'), after.get('source_epoch')) == (before.get('epoch'), before.get('source_epoch')) and
                            before.get('bytes') is not None and after.get('bytes') is not None and after['bytes'] >= before['bytes']):
                        self.totals[scope]['transfer'] += after['bytes'] - before['bytes']
                if all(previous[s].get('listeners') is not None and observations[s].get('listeners') is not None for s in (1, 2)):
                    self.totals[0]['seconds'] += gap
                    self.totals[0]['listeners'] += gap * sum(previous[s]['listeners'] for s in (1, 2))
                    self.totals[0]['online'] += gap * bool(previous[1].get('online'))
        for scope in (1, 2):
            value = observations[scope].get('listeners')
            if value is not None:
                self.totals[scope]['peak'] = max(self.totals[scope]['peak'], value)
        if all(observations[s].get('listeners') is not None for s in (1, 2)):
            self.totals[0]['peak'] = max(self.totals[0]['peak'], sum(observations[s]['listeners'] for s in (1, 2)))
        self.totals[0]['transfer'] = sum(self.totals[s]['transfer'] for s in (1, 2))
        for scope, observation in observations.items():
            listed = observation.get('clients')
            epoch = (observation.get('epoch'), observation.get('source_epoch'))
            present = {(scope, *epoch, str(c['id'])): c for c in listed or []}
            for identity, state in list(self.connections.items()):
                if identity[0] != scope:
                    continue
                reset = (observation.get('epoch') is not None and identity[1] != observation['epoch']) or (
                    observation.get('online') and identity[1:3] != epoch)
                interrupted = now - state['last'] > 45 or reset
                if interrupted or (listed is not None and identity not in present):
                    self.closed.append(dict(state, scope=scope, interrupted=interrupted))
                    del self.connections[identity]
            for identity, client in present.items():
                if identity not in self.connections:
                    category = next((v for v in AGENTS.values() if v[0] == client.get('agent')), ('', 'other/unknown', 'Other/unknown'))
                    self.connections[identity] = dict(last=now, seconds=0, device=category[1], player=category[2])
                    self.starts[scope] += 1
                    self.devices[scope, category[1]] += 1
                    self.players[scope, category[2]] += 1
                else:
                    state = self.connections[identity]
                    state['seconds'] += now - state['last']
                    state['last'] = now
        self.previous = now, observations
        self.samples += 1
        with (self.evidence/'observations.jsonl').open('a') as file:
            file.write(json.dumps(dict(at=now, stations=observations))+'\n')

    def verify(self, now):
        for scope, expected in self.totals.items():
            for resolution in ('minute', 'hour', 'month', 'lifetime'):
                rows = StatsBucket.query.filter_by(scope=scope, resolution=resolution).all()
                for field, key in [('observed_seconds', 'seconds'), ('listener_seconds', 'listeners'), ('online_seconds', 'online'), ('bytes_sent', 'transfer')]:
                    assert sum(getattr(r, field) for r in rows) == pytest.approx(expected[key]), (scope, resolution, field, expected)
                    self.checks += 1
                assert max((r.peak for r in rows), default=0) == expected['peak']
                self.checks += 1
            rows = SessionBucket.query.filter_by(scope=scope).all() if scope else SessionBucket.query.all()
            finished = [r for r in self.closed if not scope or r['scope'] == scope]
            complete = [r for r in finished if not r['interrupted']]
            expected_starts = self.starts[scope] if scope else sum(self.starts.values())
            assert sum(r.data['starts'] for r in rows) == expected_starts
            assert sum(r.data['completed'] for r in rows) == len(complete)
            assert sum(r.data['interrupted'] for r in rows) == len(finished)-len(complete)
            assert sum(r.data['duration_seconds'] for r in rows) == sum(r['seconds'] for r in complete)
            for index, (low, high) in enumerate(zip((0, 60, 300, 900, 1800, 3600), (60, 300, 900, 1800, 3600, math.inf))):
                assert sum(r.data['bands'][index] for r in rows) == sum(low <= r['seconds'] < high for r in complete)
            for category in ('desktop', 'mobile', 'tablet', 'other/unknown'):
                count = sum(v for (station, name), v in self.devices.items() if name == category and (not scope or station == scope))
                assert sum(r.data['devices'].get(category, 0) for r in rows) == count
            for category in {v[2] for v in AGENTS.values()} | {'Other/unknown'}:
                count = sum(v for (station, name), v in self.players.items() if name == category and (not scope or station == scope))
                assert sum(r.data['players'].get(category, 0) for r in rows) == count
            result = dashboard(scope, {'range': '24h'}, now=now + 1)
            assert result['stats']['total']['listener_hours'] == pytest.approx(expected['listeners']/3600)
            assert result['stats']['total']['peak'] == expected['peak']
            assert result['stats']['total']['average'] == (pytest.approx(expected['listeners']/expected['seconds']) if expected['seconds'] else None)
            assert result['sessions']['average_seconds'] == (pytest.approx(sum(r['seconds'] for r in complete)/len(complete)) if complete else None)
            if complete:
                assert sum(r['count'] for r in result['sessions']['bands']) == len(complete)
                for row in result['sessions']['retention']:
                    assert row['share'] == pytest.approx(100 * sum(r['seconds'] >= row['seconds'] for r in complete)/len(complete))
            _, observations = self.previous
            selected = [observations[s] for s in ((scope,) if scope else (1, 2))]
            if all(o.get('listeners') is not None for o in selected):
                assert result['current']['listeners'] == sum(o['listeners'] for o in selected)
            if all(o.get('clients') is not None for o in selected):
                active = [value for identity, value in self.connections.items() if not scope or identity[0] == scope]
                assert result['sessions']['active'] == len(active)
                assert result['geography']['total'] == sum(len(o['clients']) for o in selected if o.get('online'))
                for row in result['devices']['groups']:
                    assert row['current'] == sum(value['device'] == row['name'] for value in active)
                for row in result['devices']['players']:
                    assert row['current'] == sum(value['player'] == row['name'] for value in active)
            if scope:
                assert all(c['id'] == scope for c in result['channels'])
            query = SelectionDecision.query.filter_by(status='started').filter(
                SelectionDecision.track_id.isnot(None),
                SelectionDecision.started_at >= datetime.fromtimestamp(now + 1 - 86400, timezone.utc),
                SelectionDecision.started_at < datetime.fromtimestamp(now + 1, timezone.utc))
            if scope:
                query = query.filter_by(station_id=scope)
            assert result['music']['plays'] == query.count()
            self.checks += 20


@pytest.fixture
def system_stack(monkeypatch, tmp_path):
    stack = SystemStack(monkeypatch, tmp_path)
    stack.ledger = Ledger(tmp_path)
    stack.collector_paused_until = stack.last_collect = 0
    original = collect.tick
    def record(observations, now):
        if time.monotonic() < stack.collector_paused_until or now - stack.last_collect < 15:
            return
        stack.last_collect = now
        with stack.ledger.lock:
            original(observations, now)
            stack.ledger.observe(observations, now)
            stack.ledger.verify(now)
    monkeypatch.setattr(collect, 'tick', record)
    place = dict(geo.UNKNOWN, place='soak-perth', country='Australia', country_code='AU', city='Perth', lat=-31.95, lon=115.86)
    monkeypatch.setattr(geo, 'lookup', lambda _: dict(place))
    stack.app.config['FREO_GEOIP_DATABASE'] = str(stack.root/'fixture-geography-unavailable.mmdb')
    try:
        stack.start()
        yield stack
    finally:
        stack.close()


class Listener:
    def __init__(self, stack, name):
        self.response = stack.opener.open(Request(stack.icecast_url+'/'+stack.slug, headers={'User-Agent': AGENTS[name][0]}), timeout=10)
        self.bytes = 0
        self.stopped = threading.Event()
        def consume():
            try:
                while not self.stopped.is_set():
                    data = self.response.read(4096)
                    if not data:
                        return
                    self.bytes += len(data)
            except (OSError, ValueError):
                pass
        self.thread = threading.Thread(target=consume, daemon=True)
        self.thread.start()

    def close(self):
        self.stopped.set()
        self.response.close()
        self.thread.join(timeout=3)


def test_statistics_wall_clock_soak(system_browser):
    stack, driver = system_browser
    wait = WebDriverWait(driver, 25)
    listeners = {}
    timed_listeners = {}
    # Longer runs also generate deliberate completed sessions in every band.
    duration_plan = (35, 600, 1200, 2100, 4200) if SECONDS >= 7200 else ()
    duration_finished = set()
    started = time.monotonic()
    metrics = dict(status='running', requested_seconds=SECONDS, started_utc=datetime.now(timezone.utc).isoformat(), checks=0,
                   cycles=0, browser_checks=0, csv_checks=0, screenshots=[], faults=[], elapsed_seconds=0)
    driver.get(stack.base+'/admin/stats?range=live&tab=audience')
    wait.until(lambda d: d.find_element(By.ID, 'statistics').get_attribute('data-map-ready') == 'true')
    next_cycle = 0
    try:
        while time.monotonic()-started < SECONDS:
            elapsed = time.monotonic()-started
            assert not stack.errors, '\n'.join(stack.errors)
            assert stack.engine.poll() is None and stack.icecast.poll() is None
            for duration in duration_plan:
                if elapsed >= 600 + duration and duration in timed_listeners:
                    timed_listeners.pop(duration).close()
                    duration_finished.add(duration)
                elif 600 <= elapsed < 600 + duration and duration not in duration_finished:
                    listener = timed_listeners.get(duration)
                    if listener and not listener.thread.is_alive():
                        timed_listeners.pop(duration).close()
                        listener = None
                    if listener is None:
                        timed_listeners[duration] = Listener(stack, 'tablet')
            if elapsed >= next_cycle:
                cycle = metrics['cycles']
                desired = {'desktop'}
                if cycle == 75:
                    desired.clear()  # A completed 75-minute session exercises the 60+ band.
                if cycle % 4 != 3:
                    desired.add('mobile')
                if cycle % 6 in (1, 2, 3):
                    desired.add('tablet')
                if cycle % 10 in (2, 3, 4, 5, 6):
                    desired.add('player')
                if elapsed >= SECONDS - 75:
                    desired = set()
                # Real source resets can close readers; preserve the requested
                # load after recording the interrupted session in the ledger.
                for name in list(listeners):
                    if not listeners[name].thread.is_alive():
                        listeners.pop(name).close()
                        metrics['listener_reconnects'] = metrics.get('listener_reconnects', 0) + 1
                for name in set(listeners)-desired:
                    listeners.pop(name).close()
                for name in desired-set(listeners):
                    listeners[name] = Listener(stack, name)
                if cycle == 90 and elapsed < SECONDS-120:
                    stack.collector_paused_until = time.monotonic()+65
                    metrics['faults'].append(dict(kind='collector_gap', at=round(elapsed, 1), seconds=65))
                with stack.ledger.lock, stack.app.app_context():
                    inventory(int(time.time()))
                    db.session.remove()
                    totals = stack.ledger.totals[1]
                    metrics.update(samples=stack.ledger.samples, checks=stack.ledger.checks,
                                   listener_hours=totals['listeners']/3600, starts=stack.ledger.starts[1], completed=sum(not r['interrupted'] for r in stack.ledger.closed))
                target = ('overview', 'audience', 'music', 'engagement', 'resources', 'reliability')[cycle % 6]
                driver.execute_script("document.querySelector('[data-tab=\"' + arguments[0] + '\"]').click()", target)
                assert driver.find_element(By.CSS_SELECTOR, f'[data-tab="{target}"]').get_attribute('aria-selected') == 'true'
                assert not drain_browser_console(stack)
                assert 'error' not in driver.find_element(By.ID, 'stats-message').get_attribute('class').split()
                assert driver.execute_script('return document.documentElement.scrollWidth <= innerWidth + 1')
                metrics['browser_checks'] += 1
                metrics['browser_resources'] = {m['name']: m['value'] for m in driver.execute_cdp_cmd('Performance.getMetrics', {})['metrics']
                                                if m['name'] in ('Nodes', 'JSEventListeners', 'JSHeapUsedSize')}
                if cycle % 5 == 0:
                    exported = driver.execute_async_script("const done=arguments[0];fetch(document.getElementById('stats-export').href).then(r=>r.text()).then(done)")
                    rows = list(csv.reader(io.StringIO(exported)))
                    assert any(row[0] == 'Session trend' for row in rows if row)
                    assert any(row[0] == 'Devices' for row in rows if row)
                    metrics['csv_checks'] += 1
                    driver.set_window_size(390 if cycle % 10 == 5 else 1440, 1000)
                if cycle % 10 == 0:
                    path = stack.evidence/f'statistics-{cycle:03d}-{target}.png'
                    driver.save_screenshot(str(path))
                    metrics['screenshots'].append(path.name)
                metrics.update(cycles=cycle+1, elapsed_seconds=round(elapsed, 2))
                (stack.evidence/'statistics-soak.json').write_text(json.dumps(metrics, indent=2))
                print('STATISTICS_SOAK '+json.dumps(metrics), flush=True)
                next_cycle += 60
            time.sleep(min(1, max(.01, SECONDS-(time.monotonic()-started))))
        with stack.ledger.lock, stack.app.app_context():
            assert not stack.errors, stack.errors
            stack.ledger.verify(stack.ledger.previous[0])
            metrics.update(samples=stack.ledger.samples, checks=stack.ledger.checks,
                           starts=stack.ledger.starts[1], completed=sum(not r['interrupted'] for r in stack.ledger.closed),
                           listener_hours=stack.ledger.totals[1]['listeners']/3600)
        metrics.update(elapsed_seconds=round(time.monotonic()-started, 2))
        assert metrics['elapsed_seconds'] >= SECONDS
        assert metrics['samples'] >= SECONDS/20
        assert metrics['completed'] > 0
        metrics['status'] = 'passed'
    finally:
        for listener in listeners.values():
            listener.close()
        for listener in timed_listeners.values():
            listener.close()
        with stack.ledger.lock:
            metrics.update(elapsed_seconds=round(time.monotonic()-started, 2),
                           finished_utc=datetime.now(timezone.utc).isoformat(),
                           samples=stack.ledger.samples, checks=stack.ledger.checks)
        if metrics['status'] != 'passed':
            metrics['status'] = 'failed'
        (stack.evidence/'statistics-soak.json').write_text(json.dumps(metrics, indent=2))
