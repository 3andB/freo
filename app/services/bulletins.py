"""External audio preparation and reconciliation inside the timed-event worker."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from pathlib import Path
import os
import re
import subprocess
import time
from flask import current_app
from app.extensions import db
from app.models import TimedEventOccurrence, SelectionDecision
from app.services.relay_transport import validate_url, open_upstream, RelayTransport
from app.services.timed_events import aware, _integer
from app.services.availability import tracks_for, playable
from app.services.playout_queue import _command, push_decision, socket_identity

ROOT = Path('/var/lib/freo/bulletins')
POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix='bulletin-fetch')


def validate(station, value):
    if not isinstance(value, dict): raise ValueError('Configure a bulletin source')
    kind = value.get('kind', 'FILE')
    if kind not in ('FILE','LIVE'): raise ValueError('Choose an audio file or live stream')
    url = str(value.get('url','')).strip()
    validate_url(url)
    result = dict(kind=kind, url=url, duration=_integer(value.get('duration',180),5,600,'Duration'))
    for key in ('intro','outro'):
        identifier = value.get(key) or None
        track = tracks_for(station.id).filter_by(uuid=identifier, audio_kind='STATION').first() if identifier else None
        if identifier and (not track or not playable(track,station.id)):
            raise ValueError('Intro and outro must be available STATION audio')
        if track:
            from app.services.track_audio import duration_ms
            if not 0 < duration_ms(track) <= 60000: raise ValueError('STATION intro and outro must each be at most 60 seconds')
        result[key] = identifier
    return result


def root():
    return Path(current_app.config.get('FREO_BULLETIN_ROOT', ROOT))


def fetch_file(url, networks, folder, identifier):
    """Bounded download/decode away from the playout loop; returns only local facts."""
    folder.mkdir(parents=True, exist_ok=True, mode=0o2750)
    # Keep the inherited playout group on files created by the automation account.
    os.chmod(folder,0o2750)
    source, target = folder / f'{identifier}.download', folder / f'{identifier}.wav'
    connection = response = None
    try:
        deadline = time.monotonic()+20
        connection, response, _ = open_upstream(url, networks)
        connection._relay_socket.settimeout(2)
        if response.getheader('icy-metaint'): raise ValueError('Use Live stream for ICY sources')
        total = 0
        with source.open('xb') as output:
            while True:
                if time.monotonic() > deadline: raise ValueError('Download timed out')
                data = response.read1(65536)
                if not data: break
                total += len(data)
                if total > 100*1024*1024: raise ValueError('Bulletin exceeds 100 MB')
                output.write(data)
        # No network-capable demuxers: the downloader is the sole network boundary.
        subprocess.run(['ffmpeg','-nostdin','-v','error','-protocol_whitelist','file,pipe',
            '-format_whitelist','mp3,aac,ogg,flac,wav,mov','-i',str(source),'-map','0:a:0','-vn','-t','601','-ac','2','-ar','44100','-c:a','pcm_s16le',
            '-threads','1','-y',str(target)],check=True,capture_output=True,timeout=20)
        from app.services.media_probe import probe
        duration = probe(target,timeout=5)['duration_ms']/1000
        if not 0 < duration <= 600: raise ValueError('Bulletin exceeds ten minutes')
        os.chmod(target,0o640)
        return dict(path=str(target), duration=duration)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    finally:
        source.unlink(missing_ok=True)
        if response is not None: response.close()
        if connection is not None: connection.close()


def fail(occurrence, reason):
    occurrence.state = 'FAILED'; occurrence.failure_reason = reason
    db.session.commit()


def cleanup(occurrence, reader, *, revoke=True):
    transport = getattr(reader,'relay_transport',None)
    if transport and revoke: transport.configure(-occurrence.id,'')
    folder = root()/str(occurrence.station_id)
    for extension in ('wav','download'):
        (folder/f'{occurrence.id}.{extension}').unlink(missing_ok=True)


def sequence_uri(occurrence, spec, key):
    if not spec.get(key): return '-'
    song = tracks_for(occurrence.station_id).filter_by(uuid=spec[key],audio_kind='STATION').first()
    if not song or not playable(song,occurrence.station_id): raise ValueError('Station audio unavailable')
    decision = SelectionDecision(station_id=occurrence.station_id, track=song, status='selected',
        selection_method='bulletin', reason=f'bulletin:{occurrence.id}:{key}')
    db.session.add(decision); db.session.flush()
    uri = push_decision(decision,prepare_only=True)
    decision.status = 'queued'; decision.socket_identity = socket_identity(occurrence.station.slug)
    return uri


def prepare(occurrence, reader, now):
    runtime = dict(occurrence.runtime or {})
    if 'bulletin' not in runtime:
        runtime['bulletin'] = validate(occurrence.station,occurrence.event.bulletin)
        runtime['title'] = occurrence.event.name
        occurrence.runtime = runtime; db.session.commit()
    spec = runtime['bulletin']
    source = None
    if spec['kind'] == 'FILE':
        jobs = getattr(reader,'bulletin_jobs',{})
        reader.bulletin_jobs = jobs
        job = jobs.get(occurrence.id)
        if job is None:
            # Bound queued downloads as well as active threads.
            if len(jobs) >= 2: return False
            folder = root()/str(occurrence.station_id)
            if runtime.get('fetch_started'):
                fail(occurrence,'bulletin_preparation_interrupted'); cleanup(occurrence,reader); return False
            runtime['fetch_revision'] = occurrence.revision
            runtime['fetch_started'] = now.isoformat(); occurrence.runtime = runtime; db.session.commit()
            jobs[occurrence.id] = POOL.submit(fetch_file,spec['url'],current_app.config['FREO_RELAY_PRIVATE_NETWORKS'],folder,occurrence.id)
            return False
        if not job.done(): return False
        try: result = job.result()
        except Exception:
            jobs.pop(occurrence.id,None); fail(occurrence,'bulletin_download_failed'); return False
        jobs.pop(occurrence.id,None)
        if runtime.get('fetch_revision') != occurrence.revision:
            cleanup(occurrence,reader,revoke=False)
            occurrence.runtime = {k:v for k,v in runtime.items() if not k.startswith('fetch_')}
            db.session.commit(); return False
        source, duration = result['path'], result['duration']
    else:
        transport = getattr(reader,'relay_transport',None)
        if transport is None:
            transport = reader.relay_transport = RelayTransport(int(current_app.config['FREO_RELAY_TRANSPORT_PORT']),current_app.config['FREO_RELAY_PRIVATE_NETWORKS'])
        source = transport.configure(-occurrence.id,spec['url'])
        duration = spec['duration']
    intro, outro = sequence_uri(occurrence,spec,'intro'), sequence_uri(occurrence,spec,'outro')
    runtime.update(prepared_at=now.isoformat(), duration=duration, identity=socket_identity(occurrence.station.slug))
    occurrence.runtime = runtime
    # Commit intent before issuing an idempotent engine command.
    occurrence.state = 'READY'; db.session.commit()
    _command(occurrence.station.slug, f'freo_bulletin.prepare {occurrence.id}|{spec["kind"]}|{source}|{duration:.3f}|{intro}|{outro}')
    return True


def reconcile(station, reader, now=None, allow_new=True):
    """Never wait on remote I/O. Engine leases recover worker loss independently."""
    now = now or datetime.now(timezone.utc)
    from app.models import TimedEvent
    if not TimedEvent.query.filter_by(station_id=station.id,content_type='BULLETIN').first(): return False
    from app.services.timed_events import generate_occurrences
    generate_occurrences(station,now)
    observed = _command(station.slug,'freo_bulletin.state').split('|')
    if observed[0].isdigit():
        old = db.session.get(TimedEventOccurrence,int(observed[0]))
        if old and (old.state in ('FAILED','MISSED','CANCELLED') or old.state=='PENDING' and not old.runtime.get('prepared_at')) and observed[1] not in ('FAILED','COMPLETED','IDLE'):
            _command(station.slug,f'freo_bulletin.cancel {old.id}'); cleanup(old,reader)
    rows = TimedEventOccurrence.query.filter_by(station_id=station.id).filter(
        TimedEventOccurrence.event.has(content_type='BULLETIN'),
        TimedEventOccurrence.scheduled_for_utc <= now+timedelta(seconds=60),
        TimedEventOccurrence.state.in_(('PENDING','READY','QUEUED','STARTED'))).order_by(
            TimedEventOccurrence.scheduled_for_utc,TimedEventOccurrence.id).all()
    # Reap finished abandoned downloads without letting them be played later.
    for identifier, job in list(getattr(reader,'bulletin_jobs',{}).items()):
        row = db.session.get(TimedEventOccurrence,identifier)
        if job.done() and (not row or row.state not in ('PENDING','READY')):
            try: job.result()
            except Exception: pass
            reader.bulletin_jobs.pop(identifier,None)
            if row: cleanup(row,reader,revoke=False)
    active = next((r for r in rows if r.state in ('READY','QUEUED','STARTED')),None)
    if active is None:
        if not allow_new: return False
        active = next((r for r in rows if r.state == 'PENDING' and r.event.enabled and aware(r.deadline_at_utc)>=now),None)
    if not active: return False
    try:
        if active.state == 'PENDING':
            if not prepare(active,reader,now): return False
        state = _command(station.slug,'freo_bulletin.state').split('|')
        if len(state)!=3 or state[0]!=str(active.id) or active.runtime.get('identity')!=socket_identity(station.slug):
            fail(active,'bulletin_engine_restarted'); cleanup(active,reader); return False
        phase = state[1]
        _command(station.slug,f'freo_bulletin.lease {active.id}')
        if float(state[2])>0 and not active.started_at:
            began=float(state[2]); active.started_at=datetime.fromtimestamp(began,timezone.utc)
            decision=SelectionDecision(station_id=station.id,status='started',started_at=active.started_at,
                selection_method='bulletin',reason=f'bulletin:{active.id}:body',
                performance_snapshot=dict(track_uuid='',title=active.runtime.get('title',active.event.name),artist='',album='',isrc=None,kind='BULLETIN',duration_ms=round(active.runtime['duration']*1000)))
            db.session.add(decision)
        if phase in ('FAILED','COMPLETED'):
            active.state = phase; active.failure_reason = 'bulletin_source_failed' if phase=='FAILED' else None
            active.completed_at = now if phase=='COMPLETED' else None
            db.session.commit(); cleanup(active,reader); return False
        if phase in ('INTRO','BODY','OUTRO'):
            active.state='STARTED'
            db.session.commit(); return True
        if (now-aware(datetime.fromisoformat(active.runtime['prepared_at']))).total_seconds()>10 and phase=='PREPARING':
            _command(station.slug,f'freo_bulletin.cancel {active.id}');fail(active,'bulletin_connection_timeout');cleanup(active,reader);return False
        if aware(active.deadline_at_utc)<now:
            _command(station.slug,f'freo_bulletin.cancel {active.id}');fail(active,'bulletin_deadline_exceeded');cleanup(active,reader);return False
        if allow_new and phase=='READY' and now>=aware(active.scheduled_for_utc):
            if active.state != 'QUEUED':
                from app.services.event_blocks import active_execution
                if active_execution(station.id):return False
                if TimedEventOccurrence.query.filter_by(station_id=station.id).filter(TimedEventOccurrence.id!=active.id,TimedEventOccurrence.state.in_(('QUEUED','STARTED'))).first():return False
                if active.event.timing_mode=='HARD':
                    from app.services.playout_queue import active_ids
                    ids = active_ids(station.slug)
                    current = SelectionDecision.query.filter_by(station_id=station.id,status='started',socket_identity=socket_identity(station.slug)).filter(SelectionDecision.liquidsoap_request_id.in_(ids)).order_by(SelectionDecision.started_at.desc()).first() if ids else None
                    if ids and (not current or not current.track or current.track.audio_kind != 'MUSIC' or current.admin_user_id or active.event.interrupt_policy != 'MUSIC_ONLY'): return False
                    from app.services.playout_queue import interrupt_for_event
                    interrupt_for_event(station.slug)
                _command(station.slug,f'freo_event.arm {active.id}')
                active.state='QUEUED';active.queued_at=now;db.session.commit()
        return active.state in ('QUEUED','STARTED')
    except (OSError,ValueError,RuntimeError):
        try: _command(station.slug,f'freo_bulletin.cancel {active.id}')
        except (OSError,ValueError,RuntimeError): pass
        fail(active,'bulletin_prepare_failed');cleanup(active,reader);return False


def housekeeping(reader):
    """Bound abandoned private staging after crashes or station removal."""
    if time.monotonic() < getattr(reader,'bulletin_cleanup_at',0): return
    reader.bulletin_cleanup_at = time.monotonic()+3600
    folder = root()
    if not folder.is_dir() or folder.is_symlink(): return
    cutoff = time.time()-86400
    for station in folder.iterdir():
        if not station.name.isdigit() or station.is_symlink() or not station.is_dir(): continue
        for path in station.iterdir():
            if re.fullmatch(r'[1-9][0-9]*\.(wav|download)',path.name) and not path.is_symlink() and path.is_file() and path.stat().st_mtime<cutoff:
                path.unlink(missing_ok=True)
