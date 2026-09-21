"""A disposable normal-length music library and real local-time programme."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from werkzeug.security import generate_password_hash
from app.extensions import db
from app.models import (AdminUser, AutomationState, Playlist, PlaylistItem,
                        Station, StreamMount, Track)
from app.services import visual_schedule as vs
from app.services.timed_events import save_event
from tests.system_harness import SystemStack


class ProgrammeStack(SystemStack):
    def seed(self):
        self.smoke = os.environ.get('FREO_PROGRAMME_SMOKE') == '1'
        self.seconds = int(os.environ['FREO_PROGRAMME_SECONDS'])
        bundle = Path(os.environ['FREO_PROGRAMME_MEDIA_DIR'])
        manifest = json.loads((bundle/'manifest.json').read_text())
        assert len([r for r in manifest if r['role'] == 'music']) >= 12
        # Start the disposable station during local hour 22, so a real midnight
        # occurs inside three hours without changing any process/system clock.
        offset = (22-datetime.now(timezone.utc).hour+12) % 24 - 12
        self.zone = ZoneInfo(f'Etc/GMT{-offset:+d}') if offset else ZoneInfo('UTC')
        station = Station(name='Programme Shift Test', slug=self.slug, desired_state='running',
            timezone=self.zone.key, broadcast_status='ready')
        station.stream = StreamMount()
        station.automation = AutomationState(enabled=True, operator_mode='AUTO', hold=False)
        second = Station(name='Untouched station', slug='second-station', desired_state='stopped')
        second.stream = StreamMount()
        db.session.add_all([station, second, AdminUser(email='admin@example.test',
            password_hash=generate_password_hash('test-password-long-enough'))])
        db.session.flush()
        originals = self.media/self.slug/'originals'
        originals.mkdir(parents=True)
        self.music = []
        self.assets = {}
        for index, row in enumerate(manifest, 1):
            src = bundle/row['file']
            assert src.parent == bundle and src.is_file() and not src.is_symlink()
            assert hashlib.sha256(src.read_bytes()).hexdigest() == row['sha256']
            ext = src.suffix[1:]
            key = f'{index:032x}.{ext}'
            destination = originals/key
            duration = row['duration']
            if self.smoke and row['role'] == 'music':
                duration = 25 + index % 3 * 5
                subprocess.run(['ffmpeg', '-v', 'error', '-i', str(src), '-t', str(duration),
                    str(destination)], check=True, timeout=60)
            else:
                shutil.copyfile(src, destination)
            title = f'Programme {index:02d} - {row["title"]}'
            track = Track(station_id=station.id, uuid=f'10000000-0000-4000-8000-{index:012d}',
                title=title, artist='Private library copy', original_filename=src.name,
                storage_key=key, media_type=ext, duration_ms=round(duration*1000),
                sample_rate_hz=row['sample_rate'], channels=row['channels'],
                file_size_bytes=destination.stat().st_size,
                checksum_sha256=hashlib.sha256(destination.read_bytes()).hexdigest(),
                enabled=True, ingest_status='accepted')
            db.session.add(track)
            db.session.flush()
            self.assets[track.id] = dict(row, id=track.id, uuid=track.uuid,
                title=title, duration=duration, copied_sha256=track.checksum_sha256)
            if row['role'] == 'music':
                self.music.append(track.id)
            else:
                self.id_track = track.id
        self.rotations = []
        for index in range(3):
            ids = self.music[4*index:] + self.music[:4*index]
            playlist = Playlist(station_id=station.id,
                name=['Evening programme', 'Late programme', 'After midnight'][index], mode='STRAIGHT')
            playlist.items = [PlaylistItem(track_id=identifier, position=n+1) for n, identifier in enumerate(ids)]
            db.session.add(playlist)
            db.session.flush()
            self.rotations.append(dict(playlist=playlist.id, tracks=ids, name=playlist.name))
        db.session.commit()

    def configure_shift(self):
        """Schedule after fixture setup so the first event cannot expire during startup."""
        station = Station.query.filter_by(slug=self.slug).one()
        self.planned_start = datetime.now(timezone.utc)
        local = self.planned_start.astimezone(self.zone)
        assert local.hour == 22, 'Fixture crossed an hour during setup; retry to anchor the test safely'
        rule = dict(frequency='daily', anchor=local.date().isoformat())
        if self.smoke:
            second = local.hour*3600+local.minute*60+local.second
            intervals = [(0, second+85, 0), (second+85, second+170, 1), (second+170, 86400, 2)]
        else:
            intervals = [(0, 22*3600, 2), (22*3600, 23*3600, 0), (23*3600, 86400, 1)]
        self.intervals = intervals
        policy = vs.policy(station, True)
        policy.calendar = vs.clean_document(station, [dict(id=f'programme-{i}', start=start,
            end=end, source=dict(kind='playlist', id=self.rotations[rotation]['playlist']), rule=rule)
            for i, (start, end, rotation) in enumerate(intervals)])
        policy.default_playlist_id = self.rotations[0]['playlist']
        policy.mode = 'CALENDAR'
        policy.activated = policy.calendar_saved = True
        db.session.commit()
        self.activation = policy.activation
        end = self.planned_start + timedelta(seconds=self.seconds)
        events = []
        if self.smoke:
            events = [(self.planned_start+timedelta(seconds=45), 'SOFT'),
                      (self.planned_start+timedelta(seconds=180), 'SOFT')]
            self.takeovers = [110]
        else:
            hour = (local.replace(minute=0, second=0, microsecond=0)+timedelta(hours=1)).astimezone(timezone.utc)
            while hour < end-timedelta(seconds=30):
                events.append((hour, 'SOFT'))
                hour += timedelta(hours=1)
            events += [(self.planned_start+timedelta(minutes=n), 'SOFT') for n in (25,85,145)]
            self.takeovers = [40*60,100*60,160*60]
        self.expected_events = {}
        for index, (due, mode) in enumerate(sorted(events)):
            wall = due.astimezone(self.zone)
            event = save_event(self.slug, name=f'Shift {mode.lower()} ID {index+1}',
                timing_mode=mode, recurrence_type='ONE_TIME', content_type='TRACK',
                content_identifier=self.assets[self.id_track]['uuid'],
                local_date=wall.date().isoformat(), local_time=wall.strftime('%H:%M:%S'),
                late_tolerance_seconds=360, interrupt_policy='MUSIC_ONLY' if mode=='HARD' else 'NEVER',
                interrupt_dj=True)
            occurrence = event.occurrences[0]
            self.expected_events[occurrence.id] = dict(name=event.name, due=due.timestamp(), mode=mode)
        db.session.commit()
        self.plan = dict(start_utc=self.planned_start.isoformat(), station_timezone=self.zone.key,
            start_local=local.isoformat(), seconds=self.seconds, smoke=self.smoke,
            rotations=self.rotations, intervals=self.intervals, events=self.expected_events,
            dj_takeovers_seconds=self.takeovers, assets=list(self.assets.values()))
        (self.evidence/'programme-plan.json').write_text(json.dumps(self.plan, indent=2))

    def expected_rotation(self, instant):
        local = instant.astimezone(self.zone)
        second = local.hour*3600+local.minute*60+local.second
        return next(rotation for start,end,rotation in self.intervals if start<=second<end)

    def expected_occurrence(self, instant):
        local = instant.astimezone(self.zone)
        second = local.hour*3600+local.minute*60+local.second
        index = next(i for i,(start,end,_) in enumerate(self.intervals) if start<=second<end)
        key = f'{self.activation}:CALENDAR:programme-{index}:{local.date().isoformat()}'
        return 'visual:'+hashlib.sha256(key.encode()).hexdigest()
