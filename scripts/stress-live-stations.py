#!/usr/bin/env python3
"""Explicitly opt-in live station exercise, with durable restore data and audio evidence.

This operates real stations. Run only with the broadcast owner's authorization.
It preserves media and saved documents, temporarily installs test programming,
and restores the documents and starting modes in finally (or with --restore).
"""
import argparse
import copy
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import re
import secrets
import signal
import socket
import os
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import uuid
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import create_app
from app.extensions import db
from app.models import AdminUser, Station, Track, BoothCue, LiveControlCommand, LiveCartSlot, ScheduleComposition, SelectionDecision, TimedEvent, TimedEventOccurrence
from app.services import visual_schedule as vs
from app.services.availability import tracks_for
from app.services.playout_queue import mixer_state, program_decision_id


def utc():
    return datetime.now(timezone.utc).isoformat()


def write_json(path, value):
    pending = path.with_suffix('.tmp')
    pending.write_text(json.dumps(value, indent=2))
    pending.replace(path)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class LiveStress:
    def __init__(self, args):
        self.args = args
        self.root = args.output.resolve()
        self.app = create_app()
        self.base = self.app.config['PUBLIC_BASE_URL'].rstrip('/')
        self.csrf = secrets.token_urlsafe(32)
        with self.app.app_context():
            admin = AdminUser.query.filter_by(active=True).first()
            assert admin, 'An existing active administrator is required'
            self.admin_id = admin.id
        self.cookie_name = self.app.config.get('SESSION_COOKIE_NAME', 'session')
        self.driver = None
        self.cookie = None
        self.auth_until = 0
        self.browser_cookie = None
        self.opener = urllib.request.build_opener(NoRedirect())
        self.tabs = {}
        self.probes = {}
        self.sessions = {}
        self.last_tone = {}
        self.seen_commands = set()
        self.issue_keys = set()
        self.metrics = dict(status='preparing', started_at=utc(), actions={}, stations={}, issues=[], samples=0)
        self.originals = {}
        self.plan = {}
        self.recovery_until = 0
        self.restart_hours = set()
        self.stable = {}
        self.monitor_progress = {}
        self.last_resource = {}
        self.latest = {}
        self.conditions = {}
        self.programming = {}
        self.settled = set()

    def authenticate(self, browser=False):
        if time.monotonic() >= self.auth_until:
            with self.app.app_context():
                admin=db.session.get(AdminUser, self.admin_id)
                if admin is None or not admin.active:
                    raise RuntimeError('Stress administrator is no longer active')
                self.cookie = self.app.session_interface.get_signing_serializer(self.app).dumps(
                    dict(admin_user_id=self.admin_id, admin_csrf=self.csrf))
            self.auth_until = time.monotonic() + min(600, self.app.permanent_session_lifetime.total_seconds()/2)
            self.metrics['auth_renewals']=self.metrics.get('auth_renewals',0)+1
        if browser and self.driver and self.browser_cookie != self.cookie:
            self.driver.add_cookie(dict(name=self.cookie_name, value=self.cookie, path='/',
                secure=self.base.startswith('https'), httpOnly=True, sameSite='Lax'))
            self.browser_cookie = self.cookie

    def heartbeat(self):
        self.metrics['heartbeat_at'] = utc()
        write_json(self.root/'run.json', self.metrics)
        address = os.environ.get('NOTIFY_SOCKET')
        if address:
            with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as channel:
                channel.connect('\0'+address[1:] if address.startswith('@') else address)
                channel.sendall(b'READY=1\nWATCHDOG=1')

    def api(self, path, form=None):
        self.authenticate()
        data = urllib.parse.urlencode(dict(csrf=self.csrf, **form)).encode() if form is not None else None
        request = urllib.request.Request(self.base + path, data=data, headers={
            'Cookie': self.cookie_name + '=' + self.cookie, 'Accept': 'application/json'})
        try:
            with self.opener.open(request, timeout=20) as response:
                if response.url != request.full_url or 'application/json' not in response.headers.get('Content-Type', ''):
                    raise RuntimeError(f'{path}: unexpected HTTP {response.status} response; expected authenticated JSON')
                return json.load(response)
        except urllib.error.HTTPError as error:
            detail=''
            if 'application/json' in error.headers.get('Content-Type',''):
                try:detail=str(json.load(error).get('message',''))[:250]
                except (ValueError,AttributeError):pass
            raise RuntimeError(f'{path}: HTTP {error.code}; {detail}; request was not retried') from None

    def state(self, slug):
        return self.api(f'/admin/stations/{slug}/schedule-studio/api/state')

    def schedule(self, slug, action, **payload):
        return self.api(f'/admin/stations/{slug}/schedule-studio/api/{action}', {'payload': json.dumps(payload)})

    def live(self, slug, action, **fields):
        return self.api(f'/admin/stations/{slug}/live/{action}', fields)

    def status(self, slug):
        return self.api(f'/admin/api/stations/{slug}/live-status')

    def event(self, kind, **details):
        with (self.root/'actions.jsonl').open('a') as output:
            output.write(json.dumps(dict(at=utc(), kind=kind, **details))+'\n')
        self.metrics['actions'][kind] = self.metrics['actions'].get(kind, 0)+1

    def issue(self, key, message, **details):
        if key in self.issue_keys:
            return
        self.issue_keys.add(key)
        if details.get('station') in self.latest:
            details['observation']=self.latest[details['station']]
        row = dict(at=utc(), key=key, message=message, **details)
        self.metrics['issues'].append(row)
        with (self.root/'issues.jsonl').open('a') as output:
            output.write(json.dumps(row)+'\n')
        if key.startswith(('silence:','fallback:','decoder-stall:')) and len(self.issue_keys)<=24:
            probe=self.probes.get(details.get('station'))
            if probe:
                incident=self.root/f'audio-incident-{len(self.issue_keys)}'
                incident.mkdir()
                for recording in probe['directory'].glob('audio-*.wav'):
                    shutil.copyfile(recording,incident/recording.name)
        if self.driver:
            try:
                self.driver.save_screenshot(str(self.root/f'issue-{len(self.issue_keys)}.png'))
            except Exception:
                pass

    def preflight(self):
        with self.app.app_context():
            for slug in self.args.stations:
                station = Station.query.filter_by(slug=slug, enabled=True, desired_state='running').one()
                assert station.automation.operator_mode == 'AUTO', f'{slug}: must start in AUTO'
                assert station.automation.enabled and not station.automation.hold, f'{slug}: automatic playback must be enabled'
                cue = db.session.get(BoothCue, station.id)
                assert not cue or not cue.auto_enabled, f'{slug}: active AUTO_CUE must finish first'
                p = vs.policy(station)
                assert p and p.simple and p.simple['kind'] == 'playlist', f'{slug}: requires a saved playable Simple playlist'
                assert vs.source_tracks(station, p.simple), f'{slug}: Simple playlist is empty'
                tracks = tracks_for(station.id).filter(Track.audio_kind=='MUSIC', Track.enabled.is_(True),
                    Track.ingest_status=='accepted', Track.decommissioned_at.is_(None),
                    Track.duration_ms.between(60000, 360000)).order_by(Track.duration_ms,Track.id).limit(20).all()
                assert len(tracks) >= 2, f'{slug}: needs at least two approved music tracks'
                self.originals[slug] = dict(station_id=station.id, mode=p.mode,
                    calendar=copy.deepcopy(p.calendar), calendar_saved=p.calendar_saved,
                    assignments=copy.deepcopy(p.assignments), simple=copy.deepcopy(p.simple),
                    live_simple=copy.deepcopy(p.live_simple), activation=p.activation, activated=p.activated)
                event_track=tracks_for(station.id).filter(Track.enabled.is_(True), Track.ingest_status=='accepted',
                    Track.decommissioned_at.is_(None),Track.duration_ms.between(1000,180000)).order_by(Track.audio_kind=='MUSIC',Track.duration_ms).first()
                assert event_track, f'{slug}: needs approved event audio of at most three minutes'
                self.plan[slug] = dict(event_track=event_track.uuid, event_audio_kind=event_track.audio_kind, tracks=[dict(uuid=t.uuid, title=t.title, duration=t.duration_ms/1000) for t in tracks],
                    source=copy.deepcopy(p.simple), carts=[dict(role=c.role, position=c.position)
                        for c in LiveCartSlot.query.filter_by(station_id=station.id) if c.track_id or c.imaging_asset_id])
        return {'base': self.base, 'stations': {s: {'tracks': len(p['tracks']), 'carts': len(p['carts'])} for s,p in self.plan.items()}}

    def prepare(self):
        self.root.mkdir(parents=True, exist_ok=False, mode=0o700)
        write_json(self.root/'originals.json', self.originals)
        write_json(self.root/'plan.json', self.plan)
        for slug, plan in self.plan.items():
            # Persist each created fixture identity before installing references.
            block = self.schedule(slug, 'composition', kind='BLOCK', name='Live stress '+self.root.name,
                description='Temporary authorized endurance fixture; archived after restoration.',
                sections=[dict(id=str(uuid.uuid4()), start=i*900, end=(i+1)*900, source=plan['source']) for i in range(96)])
            self.originals[slug]['temporary_block_id'] = block['id']
            write_json(self.root/'originals.json', self.originals)
            rule = dict(frequency='daily', anchor='2026-01-01', interval=1)
            assignments = [dict(id=str(uuid.uuid4()), rule=rule,
                pattern=[dict(kind='block', id=block['id'], version=block['revision'])])]
            calendar = [dict(id=str(uuid.uuid4()), start=i*900, end=(i+1)*900,
                source=plan['source'], rule=rule) for i in range(96)]
            for field, items in [('assignments', assignments), ('calendar', calendar)]:
                state = self.state(slug)
                # Store expected ownership before POST so recovery also handles a lost response.
                with self.app.app_context():
                    station = Station.query.filter_by(slug=slug).one()
                    expected = vs.clean_document(station, items, assignments=field=='assignments')
                self.originals[slug]['installed_'+field] = expected
                write_json(self.root/'originals.json', self.originals)
                self.schedule(slug, field, revision=state['revision'], items=items)
            self.metrics['stations'][slug] = dict(actions=0, dj_returns=0, samples=0, metadata_matches=0)
        self.event('temporary_programming_installed')

    def install_events(self):
        from app.services.timed_events import save_event
        for slug in self.args.stations:
            names=[self.root.name+' '+slug+' '+mode for mode in ('HARD','SOFT')]
            self.originals[slug]['temporary_event_names']=names
            write_json(self.root/'originals.json',self.originals)
            with self.app.app_context():
                station=Station.query.filter_by(slug=slug).one()
                for name,mode,delay in zip(names,('HARD','SOFT'),(60,300)):
                    at=(datetime.now(timezone.utc)+timedelta(seconds=delay)).astimezone(ZoneInfo(station.timezone))
                    row=save_event(slug,name=name,timing_mode=mode,recurrence_type='ONE_TIME',content_type='TRACK',
                        content_identifier=self.plan[slug]['event_track'],local_date=at.date().isoformat(),
                        local_time=at.strftime('%H:%M:%S'),late_tolerance_seconds=600,missed_policy='PLAY_LATE',
                        interrupt_policy='MUSIC_ONLY' if mode=='HARD' else 'NEVER')
                    self.event('event_installed',station=slug,event_id=row.id,timing=mode,audio_kind=self.plan[slug]['event_audio_kind'])
            self.switch(slug,'BLOCKS')

    def protected_event(self, slug):
        # Deliberate station-mode changes must not cancel a due normal ID.
        with self.app.app_context():
            now=datetime.now(timezone.utc)
            return TimedEventOccurrence.query.filter(
                TimedEventOccurrence.station_id==self.originals[slug]['station_id'],
                TimedEventOccurrence.state.in_(('PENDING','READY','QUEUED','STARTED')),
                TimedEventOccurrence.scheduled_for_utc<=now+timedelta(seconds=30),
                TimedEventOccurrence.deadline_at_utc>=now).first() is not None

    def condition(self, slug, key, active, threshold=0):
        name=slug+':'+key
        if active:
            began=self.conditions.setdefault(name,time.monotonic())
            if time.monotonic()-began>=threshold:
                self.issue(key+':'+slug+':'+str(began),key.replace('-',' '),station=slug,
                    elapsed_seconds=round(time.monotonic()-began,2))
        elif name in self.conditions:
            self.event('condition_recovered',station=slug,condition=key,
                elapsed_seconds=round(time.monotonic()-self.conditions.pop(name),2))

    def browser(self):
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service
        options = Options()
        options.binary_location = '/usr/bin/chromium-browser'
        for flag in ['--headless=new', '--no-sandbox', '--disable-dev-shm-usage', '--window-size=1440,1100',
                     '--disable-background-timer-throttling', '--disable-renderer-backgrounding',
                     '--autoplay-policy=no-user-gesture-required', '--user-data-dir='+str(self.root/'chrome')]:
            options.add_argument(flag)
        options.set_capability('goog:loggingPrefs', {'browser':'ALL'})
        self.driver = webdriver.Chrome(service=Service('/usr/bin/chromedriver'), options=options)
        self.driver.set_page_load_timeout(30)
        self.driver.get(self.base+'/health')
        self.authenticate(browser=True)
        for index, slug in enumerate(self.args.stations):
            if index:
                self.driver.switch_to.new_window('tab')
            self.tabs[slug] = self.driver.current_window_handle
            self.driver.execute_cdp_cmd('Performance.enable', {})
            self.navigate(slug, 'control', first=True)
            self.monitor(slug)

    def navigate(self, slug, view, first=False):
        from selenium.webdriver.support.ui import WebDriverWait
        self.driver.switch_to.window(self.tabs[slug])
        self.authenticate(browser=True)
        path = f'/admin/stations/{slug}/'+('live' if view=='live' else 'schedule-studio/'+view)
        if first:
            self.driver.get(self.base+path)
        else:
            self.driver.execute_script('FreoWorkspace.navigate(arguments[0])', path)
        root = 'dj-booth' if view=='live' else 'station-control' if view=='control' else 'schedule-studio'
        WebDriverWait(self.driver, 30).until(lambda d: d.execute_script(
            'return !!document.getElementById(arguments[0]) && !document.documentElement.classList.contains("is-navigating")', root))
        self.event('ui_navigation', station=slug, view=view)

    def monitor(self, slug):
        self.driver.switch_to.window(self.tabs[slug])
        self.driver.execute_script('''
            if (FreoMonitor.audio.paused) {
              const button=document.querySelector('[data-monitor-station="'+arguments[0]+'"] button');
              if(button) button.click();
            }
        ''', slug)

    def switch(self, slug, mode, browser=True):
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        current = self.state(slug)
        visited=self.metrics.get('stations',{}).get(slug,{})
        if visited is not None:
            modes=visited.setdefault('schedule_modes',[])
            if mode not in modes:modes.append(mode)
        if current['mode'] == mode and self.status(slug)['mode']=='AUTO':
            return
        self.live(slug, 'mode', mode='AUTO')
        if browser and current['mode'] != mode:
            self.navigate(slug, 'control')
            wait = WebDriverWait(self.driver, 30)
            button = wait.until(lambda d: d.find_element(By.CSS_SELECTOR, f'[data-switch-mode="{mode}"]'))
            wait.until(lambda d: button.is_enabled())
            button.click()
            wait.until(lambda d: d.find_element(By.CSS_SELECTOR, 'dialog[open] .admin-primary')).click()
        elif current['mode'] != mode:
            self.schedule(slug, 'transition', id=str(uuid.uuid4()), mode=mode,
                          current=current['mode'], revision=current['revision'])
        deadline = time.monotonic()+40
        while time.monotonic() < deadline:
            state = self.state(slug)
            if state['mode']==mode and (state.get('transition') or {}).get('state') not in ('PENDING','PREPARING','FADING'):
                self.event('schedule_mode', station=slug, mode=mode)
                return
            time.sleep(.5)
        raise RuntimeError(f'{slug}: mode {mode} did not apply')

    def deck(self, slug, deck, operation, track=None):
        state = self.status(slug)
        mixer = state.get('mixer') or {}
        item = mixer.get(deck.lower()) or {}
        fields = dict(deck=deck, operation=operation, expected_decision_id=str(item.get('decision_id') or mixer.get(deck.lower()+'_id') or ''),
                      nonce=str(uuid.uuid4()), fade_seconds='1', play_on_load='true' if operation=='LOAD' else 'false')
        if track:
            fields['identifier'] = track['uuid']
        self.event('deck_requested',station=slug,deck=deck,operation=operation,
            expected_decision=fields['expected_decision_id'],nonce=fields['nonce'],track=track['uuid'] if track else None)
        self.live(slug, 'deck', **fields)
        with self.app.app_context():
            row = LiveControlCommand.query.filter_by(station_id=self.originals[slug]['station_id'],
                idempotency_key=fields['nonce']).one()
            command_id, target_id = row.id, row.target_decision_id
        deadline = time.monotonic()+25
        while time.monotonic()<deadline:
            observed = self.status(slug)
            command = observed.get('deck_command') or {}
            if command.get('id') != command_id:
                if command.get('id',0)>command_id:
                    raise RuntimeError('Deck command was replaced before confirmation')
                time.sleep(.25)
                continue
            if command.get('status') == 'failed':
                raise RuntimeError(f'Deck {operation} failed: {command.get("error")}')
            if command.get('status') == 'sent' and (operation != 'LOAD' or
                    (observed.get('mixer') or {}).get(deck.lower()+'_id') == target_id):
                observed['_target_decision_id'] = target_id
                self.event('deck_'+operation.lower(), station=slug, deck=deck, command=command)
                return observed
            time.sleep(.25)
        raise RuntimeError(f'Deck {operation} was not confirmed')

    def exercise(self, slug, phase):
        plan = self.plan[slug]
        kind = phase % 12
        if kind < 3:
            self.switch(slug, ['BLOCKS','CALENDAR','SIMPLE'][kind])
        elif kind == 3:
            current = self.status(slug).get('current')
            if current:
                self.live(slug, 'skip', expected_decision_id=str(current['decision_id']), nonce=str(uuid.uuid4()))
                self.event('skip', station=slug)
        elif kind in (4,5,6,7,8,10,11):
            track = plan['tracks'][phase % 2]
            deck = 'B' if kind==5 else 'A'
            self.navigate(slug, 'live')
            self.live(slug, 'mode', mode='DJ_BOOTH')
            deadline = time.monotonic()+20
            while time.monotonic()<deadline:
                entering = self.status(slug)
                engine = entering.get('mixer') or {}
                if entering.get('observation_fresh') and engine.get('mode')=='DJ_BOOTH' and not engine.get('a_id') and not engine.get('b_id'):
                    break
                time.sleep(.3)
            else:
                raise RuntimeError('Fresh empty decks were not observed after entering DJ mode')
            loaded = self.deck(slug, deck, 'LOAD', track)
            self.sessions[slug] = dict(kind=kind, began=time.monotonic(), track=track, deck=deck,
                seen_playing=False, modified=False, expected_decision=loaded['_target_decision_id'], deadline=time.monotonic()+track['duration']*(2 if kind==7 else 1)+90)
        else:
            state = self.status(slug)
            if plan['carts'] and not state['cart']['locked']:
                self.live(slug, 'fire-cart', nonce=str(uuid.uuid4()), **plan['carts'][0])
                self.event('cart', station=slug)
            else:
                self.live(slug, 'queue-track', identifier=plan['tracks'][phase%len(plan['tracks'])]['uuid'], nonce=str(uuid.uuid4()))
                self.event('queue_music', station=slug)
        self.metrics['stations'][slug]['actions'] += 1

    def session(self, slug, state):
        session = self.sessions.get(slug)
        if not session:
            return
        mixer = state.get('mixer') or {}
        if mixer.get(session['deck'].lower()+'_playing') and state.get('_rendered_decision_id')==session['expected_decision']:
            session['seen_playing'] = True
        if session.get('repeat_id') and state.get('_rendered_decision_id')==session['repeat_id'] and mixer.get('a_playing'):
            session['repeat_seen']=True
        if session['seen_playing'] and state['mode']=='AUTO':
            if session['kind']==7 and not session.get('repeat_seen'):
                self.issue('repeat-unconfirmed:'+slug+':'+str(session['began']), 'Repeated request was not observed playing',station=slug)
                del self.sessions[slug]
                return
            self.metrics['stations'][slug]['dj_returns'] += 1
            self.event('dj_return', station=slug, kind_id=session['kind'])
            coverage=self.metrics['stations'][slug].setdefault('scenarios',{})
            key=str(session['kind']);coverage[key]=coverage.get(key,0)+1
            del self.sessions[slug]
            return
        if time.monotonic()>session['deadline']:
            self.issue('dj-timeout:'+slug+':'+str(session['began']), 'DJ session did not return to Auto', station=slug)
            self.live(slug, 'mode', mode='AUTO')
            del self.sessions[slug]
            return
        if not session['seen_playing'] or session['modified'] or time.monotonic()-session['began'] < 20:
            return
        if session['kind']==6:
            track = self.plan[slug]['tracks'][1]
            self.deck(slug, 'B', 'LOAD', track)
            session['deadline'] = time.monotonic()+track['duration']+60
        elif session['kind']==7:
            repeated=self.deck(slug, 'A', 'REPEAT')
            session['repeat_id']=repeated['_target_decision_id']
        elif session['kind']==8:
            self.live(slug, 'mode', mode='AUTO')
            self.event('manual_auto_crossfade', station=slug)
        elif session['kind'] in (10,11):
            self.deck(slug,'A','PAUSE' if session['kind']==10 else 'CLEAR')
            session['deadline']=time.monotonic()+40
        session['modified'] = True

    def start_audio(self):
        for slug in self.args.stations:
            directory = self.root/slug
            directory.mkdir()
            log = (directory/'audio.log').open('w')
            process = subprocess.Popen(['ffmpeg','-nostdin','-nostats','-v','info','-y',
                '-reconnect','1','-reconnect_streamed','1','-reconnect_at_eof','1','-reconnect_delay_max','5',
                '-rw_timeout','15000000','-i','http://127.0.0.1:8001/'+slug,
                '-af','silencedetect=noise=-55dB:d=3','-ac','1','-ar','8000','-f','segment',
                '-segment_format_options','flush_packets=1','-segment_time','30','-segment_wrap','4',
                str(directory/'audio-%d.wav')],stdout=log,stderr=log)
            self.probes[slug] = dict(process=process, log=log, offset=0, directory=directory, last=time.monotonic())

    def wait_audio(self):
        deadline=time.monotonic()+40
        while time.monotonic()<deadline:
            if any(p['process'].poll() is not None for p in self.probes.values()):
                raise RuntimeError('Continuous decoder exited during startup')
            if all(any(f.stat().st_size>16044 for f in p['directory'].glob('audio-*.wav')) for p in self.probes.values()):
                return
            time.sleep(.25)
        raise RuntimeError('Both streams did not produce decoded audio before the test clock')

    def sample(self, slug):
        state = self.status(slug)
        now = time.monotonic()
        self.metrics['stations'][slug]['samples'] += 1
        self.latest[slug]={k:state.get(k) for k in ('observed_at','observation_fresh','mode','mixer','current','deck_command')}
        self.condition(slug,'worker-stale',not state['observation_fresh'] and now>self.recovery_until)
        with self.app.app_context():
            mixer = mixer_state(slug)
            actual = program_decision_id(slug)
        if self.stable.get(slug, (None,))[0] != actual:
            self.stable[slug] = (actual, now)
        if actual and state['observation_fresh'] and now-self.stable[slug][1]>15:
            if (state.get('current') or {}).get('decision_id') != actual:
                confirmed=self.status(slug)
                with self.app.app_context(): still=program_decision_id(slug)
                if confirmed['observation_fresh'] and still==actual and (confirmed.get('current') or {}).get('decision_id')!=actual:
                    self.issue('metadata:'+slug+':'+str(actual), 'Web status disagrees with stable rendered output', station=slug,actual_decision=actual)
            else:
                self.metrics['stations'][slug]['metadata_matches'] += 1
        self.condition(slug,'fallback',mixer.get('tone',True),5)
        for key in ['deck_command','skip_command']:
            command = state.get(key)
            if command and command['status']=='failed' and command['id'] not in self.seen_commands:
                self.seen_commands.add(command['id'])
                self.issue('command:'+str(command['id']), 'Operator command failed', station=slug, command=command)
        probe = self.probes[slug]
        if probe['process'].poll() is not None:
            raise RuntimeError(slug+': continuous decoder exited')
        with (probe['directory']/'audio.log').open() as source:
            source.seek(probe['offset']); text=source.read(); probe['offset']=source.tell()
        for end,duration in re.findall(r'silence_end: ([\d.]+) \| silence_duration: ([\d.]+)',text):
            self.event('silence_interval',station=slug,end_seconds=float(end),duration_seconds=float(duration))
        for stamp in re.findall(r'silence_start: ([\d.]+)',text):
            self.issue('silence:'+slug+':'+stamp, 'At least three seconds of decoded silence', station=slug, stream_seconds=stamp)
        files = list(probe['directory'].glob('audio-*.wav'))
        if files:
            age=time.time()-max(p.stat().st_mtime for p in files)
            if age>15:
                self.issue('decoder-stall:'+slug,'Decoded audio stopped advancing',station=slug,age=age)
            if age>90:
                raise RuntimeError(slug+': stream outage exceeded 90 seconds')
        state['_rendered_decision_id']=actual
        self.latest[slug]['rendered_decision_id']=actual
        self.latest[slug]['engine_mixer']=mixer
        self.session(slug,state)
        return state

    def browser_sample(self, slug, index):
        self.driver.switch_to.window(self.tabs[slug])
        self.navigate(slug, ['control','live','calendar','blocks','simple'][index%5])
        self.driver.set_window_size([390,820,1440][index%3],1100)
        if self.driver.execute_script('return document.documentElement.scrollWidth>innerWidth'):
            self.issue('overflow:'+slug+':'+str(index%5), 'Workspace exceeds viewport width', station=slug)
        state = self.driver.execute_script('return {paused:FreoMonitor.audio.paused,time:FreoMonitor.audio.currentTime}')
        if state['paused']:
            self.issue('monitor-paused:'+slug,'Browser monitor stopped',station=slug)
            self.monitor(slug)
        previous=self.monitor_progress.get(slug)
        if previous and abs(state['time']-previous)<.01:
            self.issue('monitor-stall:'+slug, 'Browser monitor stopped advancing', station=slug)
        self.monitor_progress[slug]=state['time']
        live=self.status(slug)
        current=live.get('current') or {}
        if current and self.stable.get(slug,(None,))[0]==current.get('decision_id') and time.monotonic()-self.stable[slug][1]>15:
            title=self.driver.execute_script('return document.querySelector("[data-now-title], #live-current h2")?.textContent?.trim() || null')
            if title and title==current['title']:
                self.metrics['stations'][slug]['ui_title_matches']=self.metrics['stations'][slug].get('ui_title_matches',0)+1
            elif title:
                # Navigation installs the DOM before the first status response.
                time.sleep(3)
                after=self.status(slug).get('current') or {}
                title=self.driver.execute_script('return document.querySelector("[data-now-title], #live-current h2")?.textContent?.trim() || null')
                if after.get('decision_id')==current['decision_id'] and title and title!=current['title']:
                    self.issue('ui-title:'+slug+':'+str(current['decision_id']), 'Displayed title disagrees with current music', station=slug,displayed=title,expected=current['title'])
        with self.app.app_context():
            identifier=self.originals[slug]['station_id']
            began=datetime.fromisoformat(self.metrics['monitor_started_at'])
            visual=vs.resolve_visual(Station.query.filter_by(slug=slug).one())
            old=self.programming.get(slug)
            if visual and old and visual['mode']==old['mode'] and visual['key']!=old['key']:
                count=self.metrics['stations'][slug].setdefault('boundaries',{})
                mode=visual['mode'];count[mode]=count.get(mode,0)+1
                self.event('programme_boundary',station=slug,mode=mode,key=visual['key'])
            if visual:self.programming[slug]={'mode':visual['mode'],'key':visual['key']}
            self.metrics['stations'][slug]['track_starts']=SelectionDecision.query.filter(
                SelectionDecision.station_id==identifier,SelectionDecision.status=='started',SelectionDecision.started_at>=began).count()
            occurrences=TimedEventOccurrence.query.filter(TimedEventOccurrence.station_id==identifier,
                TimedEventOccurrence.scheduled_for_utc>=began,TimedEventOccurrence.scheduled_for_utc<=datetime.now(timezone.utc)).all()
            self.metrics['stations'][slug]['events_completed']=sum(o.state=='COMPLETED' for o in occurrences)
            self.metrics['stations'][slug]['event_modes_completed']=sorted({o.event.timing_mode for o in occurrences if o.state=='COMPLETED'})
            for occurrence in occurrences:
                if occurrence.state in ('FAILED','MISSED'):
                    self.issue('event:'+str(occurrence.id),'Timed event did not complete',station=slug,state=occurrence.state,reason=occurrence.failure_reason)
        metrics = {r['name']:r['value'] for r in self.driver.execute_cdp_cmd('Performance.getMetrics',{})['metrics']}
        # Track service memory and restart loops across the observation period.
        services={}
        if time.monotonic()-self.last_resource.get(slug,0)>60:
            self.last_resource[slug]=time.monotonic()
            for unit in ['freo.service','freo-automation.service','freo-playout@'+slug+'.service']:
                raw=subprocess.check_output(['systemctl','show',unit,'--property=MainPID,MemoryCurrent,NRestarts,ActiveState'],text=True,timeout=10)
                services[unit]=dict(line.split('=',1) for line in raw.splitlines() if '=' in line)
        with (self.root/'resources.jsonl').open('a') as output:
            output.write(json.dumps(dict(at=utc(),station=slug,browser={k:metrics.get(k) for k in ['JSHeapUsedSize','Nodes','Documents','JSEventListeners']},monitor=state,services=services))+'\n')
        for entry in self.driver.get_log('browser'):
            if entry.get('level')=='SEVERE' and entry.get('source')=='javascript':
                self.issue('js:'+entry['message'][:160], 'Uncaught browser error', detail=entry)

    def restore(self):
        path = self.root/'originals.json'
        if not path.exists():
            return
        restored = self.root/'restoration.json'
        if restored.exists() and json.loads(restored.read_text()).get('status')=='restored':
            report=self.root/'run.json'
            if report.exists() and getattr(getattr(self,'args',None),'restore',False):
                outcome=json.loads(report.read_text())
                if outcome.get('status') in ('preparing','running'):
                    outcome.update(status='interrupted',failure='Runner stopped before recording completion',finished_at=utc())
                outcome['cleanup_status']='restored';write_json(report,outcome)
            return
        originals = json.loads(path.read_text())
        errors = []
        for slug, original in originals.items():
            try:
                with self.app.app_context():
                    owned_events=TimedEvent.query.filter(TimedEvent.station_id==original.get('station_id'),TimedEvent.name.in_(original.get('temporary_event_names',[]))).all()
                    if any(e.revision!=1 and e.enabled for e in owned_events):
                        raise RuntimeError('Temporary event was edited; preserving operator changes')
                    p = vs.policy(Station.query.filter_by(slug=slug).one())
                    for field in ('calendar','assignments'):
                        if getattr(p,field) not in (original[field], original.get('installed_'+field)):
                            raise RuntimeError(f'{slug}: {field} changed outside the test; preserving that edit')
                self.live(slug,'mode',mode='AUTO')
                self.switch(slug, original['mode'], browser=False)
                with self.app.app_context():
                    station = Station.query.filter_by(slug=slug).one()
                    p = vs.policy(station)
                    for field in ('calendar','assignments'):
                        current = getattr(p,field)
                        if current != original[field] and current != original.get('installed_'+field):
                            raise RuntimeError(f'{slug}: {field} changed outside the test; preserving that edit')
                        setattr(p,field,original[field])
                    p.calendar_saved = original['calendar_saved']
                    p.activation = original['activation']
                    p.live_simple = original['live_simple']
                    p.activated = original['activated']
                    p.revision += 1
                    from app.services.timed_events import set_enabled
                    for event in TimedEvent.query.filter(TimedEvent.station_id==station.id,TimedEvent.name.in_(original.get('temporary_event_names',[]))):
                        if event.enabled:set_enabled(event,False)
                    block = db.session.get(ScheduleComposition,original.get('temporary_block_id')) if original.get('temporary_block_id') else None
                    if block:
                        block.archived = True
                    db.session.commit()
                self.event('restored',station=slug,mode=original['mode'])
            except Exception as error:
                errors.append(dict(station=slug,error=str(error)))
        write_json(self.root/'restoration.json',dict(at=utc(),status='failed' if errors else 'restored',errors=errors))
        report = self.root/'run.json'
        if report.exists():
            outcome = json.loads(report.read_text())
            if getattr(getattr(self,'args',None),'restore',False) and outcome.get('status') in ('preparing','running'):
                outcome.update(status='interrupted',failure='Runner stopped before recording completion',finished_at=utc())
            outcome.update(cleanup_status='failed' if errors else 'restored', cleanup_at=utc())
            write_json(report, outcome)
        if errors:
            raise RuntimeError('Restoration needs review: '+json.dumps(errors))

    def verify_restored(self):
        import math
        import wave
        from array import array
        report={}
        for slug in self.args.stations:
            deadline=time.monotonic()+40
            while time.monotonic()<deadline:
                state=self.status(slug)
                if state['observation_fresh'] and state['mode']=='AUTO' and state.get('current') and not (state.get('mixer') or {}).get('tone',True):
                    break
                time.sleep(1)
            else:
                raise RuntimeError(slug+': restored station did not resume fresh AUTO music')
            output=self.root/(slug+'-restored.wav')
            subprocess.run(['ffmpeg','-nostdin','-v','error','-y','-rw_timeout','10000000',
                '-i','http://127.0.0.1:8001/'+slug,'-t','5','-ac','1','-ar','8000',str(output)],
                check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,timeout=20)
            with wave.open(str(output)) as audio:
                values=array('h',audio.readframes(audio.getnframes()))
                seconds=len(values)/audio.getframerate()
            rms=math.sqrt(sum(v*v for v in values)/max(1,len(values)))/32768
            if seconds<4 or rms<=.001:
                raise RuntimeError(slug+': restored stream did not decode audible audio')
            report[slug]={'decoded_seconds':seconds,'rms':round(rms,5),'fresh_auto':True}
        write_json(self.root/'restored-health.json',dict(at=utc(),stations=report))
        return report

    def run(self):
        self.preflight()
        if self.root.exists():
            raise RuntimeError('Use a new output directory; --restore is available for an interrupted run')
        try:
            self.prepare()
            self.browser()
            self.start_audio()
            self.wait_audio()
            for slug in self.args.stations:
                state=self.status(slug)
                for key in ('deck_command','skip_command'):
                    if state.get(key): self.seen_commands.add(state[key]['id'])
            if self.args.seconds>=7200:self.install_events()
            began=time.monotonic()
            started=datetime.now(timezone.utc)
            self.metrics.update(status='running',monitor_started_at=started.isoformat(),
                expected_finish_utc=(started+timedelta(seconds=self.args.seconds)).isoformat(),
                commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip())
            due={s:began+(920 if self.args.seconds>=7200 else 10)+i*20 for i,s in enumerate(self.args.stations)}
            phases={s:(1 if self.args.seconds>=7200 else 0) for s in self.args.stations}
            next_browser=began+20
            index=0
            checkpoint=0
            while time.monotonic()-began < self.args.seconds:
                for slug in self.args.stations:
                    try:
                        self.sample(slug)
                        settling=self.args.seconds>=7200 and time.monotonic()-began>=self.args.seconds-600
                        if settling and slug not in self.sessions and slug not in self.settled:
                            self.live(slug,'mode',mode='AUTO');self.settled.add(slug)
                            self.event('settled_auto',station=slug)
                        if not settling and slug not in self.sessions and time.monotonic()>=due[slug] and not self.protected_event(slug):
                            phase=phases[slug]
                            self.exercise(slug,phase);phases[slug]+=1;due[slug]=time.monotonic()+45
                            if self.args.seconds>=7200 and phase==1:
                                with self.app.app_context():
                                    visual=vs.resolve_visual(Station.query.filter_by(slug=slug).one())
                                until=(visual['next_transition']-datetime.now(timezone.utc)).total_seconds() if visual['next_transition'] else 900
                                due[slug]=time.monotonic()+max(45,min(930,until+15))
                    except Exception as error:
                        self.issue('operation:'+slug+':'+str(phases[slug]),str(error),station=slug)
                        if '90 seconds' in str(error) or 'decoder exited' in str(error):
                            raise
                        try:
                            self.live(slug,'mode',mode='AUTO')
                        except Exception as recovery_error:
                            self.metrics['recovery_error']=str(recovery_error)
                            raise error from recovery_error
                        self.sessions.pop(slug,None)
                        phases[slug]+=1;due[slug]=time.monotonic()+30
                if time.monotonic()>=next_browser:
                    slug=self.args.stations[index%len(self.args.stations)]
                    try:
                        self.browser_sample(slug,index//len(self.args.stations))
                    except Exception as error:
                        self.issue('browser:'+str(index),str(error),station=slug)
                    index+=1;next_browser=time.monotonic()+20
                hour=int((time.monotonic()-began)//2700)
                if hour in (1,2) and hour not in self.restart_hours:
                    # Preserve audio while exercising the actual worker's recovery.
                    self.restart_hours.add(hour)
                    self.recovery_until=time.monotonic()+40
                    subprocess.run(['systemctl','restart','freo-automation.service'],check=True,timeout=30)
                    self.event('worker_restart',elapsed_minutes=hour*45)
                self.metrics.update(elapsed_seconds=round(time.monotonic()-began,2),samples=self.metrics['samples']+1)
                self.heartbeat()
                reached=int((time.monotonic()-began)//900)
                if reached>checkpoint:
                    checkpoint=reached
                    self.event('checkpoint',elapsed_seconds=self.metrics['elapsed_seconds'],issues=len(self.metrics['issues']),stations=self.metrics['stations'])
                time.sleep(2)
            if self.args.seconds>=7200:
                for slug,stats in self.metrics['stations'].items():
                    missing=[f'DJ scenario {kind}' for kind in (4,5,6,7,8,10,11) if stats.get('scenarios',{}).get(str(kind),0)<(2 if kind in (4,5) else 1)]
                    missing += [f'{mode} mode' for mode in ('SIMPLE','BLOCKS','CALENDAR') if mode not in stats.get('schedule_modes',[])]
                    missing += [f'{mode} boundary' for mode in ('BLOCKS','CALENDAR') if not stats.get('boundaries',{}).get(mode)]
                    missing += [f'{mode} event' for mode in ('HARD','SOFT') if mode not in stats.get('event_modes_completed',[])]
                    if missing:self.issue('coverage:'+slug,'Required scenarios did not complete',station=slug,missing=missing)
            self.metrics['status']='completed_with_findings' if self.metrics['issues'] else 'passed'
            self.metrics['completed_duration']=True
        except BaseException as error:
            self.metrics.update(status='failed',failure=f'{type(error).__name__}: {error}')
            raise
        finally:
            try:
                self.restore()
                self.metrics['cleanup_status']='restored'
                self.metrics['cleanup_at']=utc()
                self.metrics['restored_health']=self.verify_restored()
            except Exception as error:
                self.metrics.update(exercise_status=self.metrics['status'],status='failed',cleanup_status='failed',restore_error=str(error))
            for probe in self.probes.values():
                probe['process'].terminate()
                try: probe['process'].wait(timeout=10)
                except subprocess.TimeoutExpired: probe['process'].kill();probe['process'].wait()
                probe['log'].close()
            if self.driver:
                self.driver.quit()
            self.metrics['finished_at']=utc()
            if self.root.exists():
                self.heartbeat()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live',action='store_true',help='Explicit acknowledgement that actual broadcasts will be exercised')
    parser.add_argument('--stations',nargs='+',required=True)
    parser.add_argument('--seconds',type=int,default=7200)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--preflight',action='store_true')
    parser.add_argument('--restore',action='store_true')
    args=parser.parse_args()
    if not args.live or args.seconds<60 or len(args.stations)!=len(set(args.stations)):
        parser.error('--live and a duration of at least 60 seconds are required')
    runner=LiveStress(args)
    if args.preflight:
        print(json.dumps(runner.preflight(),indent=2));return
    if args.restore:
        runner.restore();runner.verify_restored();return
    signal.signal(signal.SIGTERM,lambda *_: (_ for _ in ()).throw(KeyboardInterrupt('Service stopped')))
    runner.run()


if __name__=='__main__':
    main()
