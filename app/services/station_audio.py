"""Validated station audio settings and durable, worker-applied changes."""
import math

from app.extensions import db
from app.models import Station, StreamMount
from app.services.admin_media import audit
from app.services.stations import allocation_lock

BITRATES = (64, 96, 128, 192)
DEFAULT_PROCESSING = dict(agc=False, multiband=False, eq=False, bass=0.0, mid=0.0, treble=0.0)


PRESETS = {'off': (-16.0, 1.0), 'light': (-18.0, 1.3), 'standard': (-16.0, 1.8), 'punchy': (-14.0, 2.5)}


def validate_settings(value):
    if not isinstance(value, dict) or set(value) - {'bitrate', 'codec', 'preset', 'target', 'ratio', *DEFAULT_PROCESSING}:
        raise ValueError('Invalid audio settings')
    bitrate = value.get('bitrate')
    if type(bitrate) is not int or bitrate not in BITRATES:
        raise ValueError('Choose 64, 96, 128 or 192 kbps')
    from freo_ops.hosting import check_bitrate
    check_bitrate(bitrate)
    result = dict(DEFAULT_PROCESSING, codec='mp3', target=-16.0, ratio=1.5, **{'bitrate':bitrate})
    result.update(value)
    result.setdefault('preset', 'custom' if any(result[k] for k in ('agc','multiband','eq')) else 'off')
    if result['codec'] not in ('mp3', 'aac') or result['preset'] not in (*PRESETS, 'custom'):
        raise ValueError('Choose a supported codec and processor preset')
    for key in ('agc', 'multiband', 'eq'):
        if type(result[key]) is not bool:
            raise ValueError('Invalid processing option')
    for key, low, high in [('bass',-6,6),('mid',-6,6),('treble',-6,6),('target',-22,-12),('ratio',1,3)]:
        number = result[key]
        if type(number) not in (int, float) or not math.isfinite(number) or not low <= number <= high:
            raise ValueError(f'{key} must be between {low} and {high}')
        result[key] = round(float(number), 1)
    if result['preset'] in PRESETS:
        result['target'], result['ratio'] = PRESETS[result['preset']]
        result.update(agc=result['preset'] != 'off', multiband=result['preset'] != 'off', eq=False, bass=0., mid=0., treble=0.)
    return result


def active_settings(stream):
    return validate_settings(dict(stream.audio_processing or {}, bitrate=stream.bitrate, codec=stream.format))


def from_form(form):
    try:
        values = dict(bitrate=int(form.get('bitrate', '')), codec=form.get('codec','mp3'),
            **{key: form.get(key) == 'yes' for key in ('agc', 'multiband', 'eq')},
            **{key: float(form.get(key, '0')) for key in ('bass', 'mid', 'treble')},
            target=float(form.get('target', '-16')), ratio=float(form.get('ratio', '1.5')))
        if 'preset' in form: values['preset'] = form['preset']
        return validate_settings(values)
    except (ValueError, TypeError) as error:
        raise ValueError('Choose supported audio settings and finite values within the displayed ranges') from error


def encoder_liquidsoap(values):
    values = validate_settings(values)
    if values['codec'] == 'mp3': return f"%mp3(bitrate={values['bitrate']})"
    return f'%ffmpeg(format="adts", %audio(codec="aac", b="{values["bitrate"]}k", ar=44100, ac=2))'


def processor_command(values):
    v = validate_settings(values)
    return 'freo_processor.apply ' + ' '.join(str(float(x)) for x in (
        int(v['agc']), int(v['multiband']), int(v['eq']), v['target'], v['ratio'], v['bass'], v['mid'], v['treble']))


def queue_settings(station, values, revision, user):
    values = validate_settings(values)
    allocation_lock()
    from freo_ops.hosting import check_bitrate, require_service
    require_service()
    check_bitrate(values['bitrate'])
    db.session.refresh(station)
    stream = station.stream
    db.session.refresh(stream)
    if not station.enabled or station.lifecycle_state != 'ready' or not stream.enabled:
        raise ValueError('The station must be enabled and ready before changing audio settings')
    if stream.audio_status in ('pending', 'applying'):
        raise ValueError('An audio change is already in progress. Wait for it to finish')
    if revision != stream.audio_revision:
        raise ValueError('Audio settings changed. Refresh and try again')
    if values == active_settings(stream) and stream.audio_status == 'ready':
        return False
    stream.pending_audio = values
    stream.audio_status = 'pending'
    stream.audio_error = ''
    stream.audio_revision += 1
    audit('station_audio_requested', user_id=user.id, station_id=station.id,
          target_type='station', target_id=station.slug, summary=f'Audio settings queued: {values["bitrate"]} kbps')
    return True


def processing_liquidsoap(values):
    v = validate_settings(values)
    from pathlib import Path
    template = (Path(__file__).resolve().parents[2] / 'deploy/liquidsoap/processor.liq').read_text()
    initial = ', '.join(str(float(x)) for x in (int(v['agc']), int(v['multiband']), int(v['eq']), v['target'], v['ratio'], v['bass'], v['mid'], v['treble']))
    return template.replace('__PROCESSOR_INITIAL__', '[' + initial + ']')


def process_audio(station):
    from app.services import station_runtime as runtime
    runtime.require_root()
    with runtime.operation_lock():
        allocation_lock()
        db.session.refresh(station)
        stream = station.stream
        db.session.refresh(stream)
        if stream.audio_status not in ('pending', 'applying'):
            db.session.rollback()
            return
        if not station.enabled or station.lifecycle_state != 'ready':
            stream.audio_status = 'failed'
            stream.audio_error = 'Audio change cancelled because the station is no longer ready.'
            db.session.commit()
            return
        try:
            values = validate_settings(stream.pending_audio)
        except ValueError:
            stream.audio_status = 'failed'
            stream.audio_error = 'Invalid audio settings. Existing output retained.'
            db.session.commit()
            return
        # Keep active values unchanged until runtime validation and restart succeed.
        stream.audio_status = 'applying'
        db.session.commit()
        try:
            runtime.apply_audio(station, values)
            stream.bitrate = values['bitrate']
            stream.format = values['codec']
            stream.audio_processing = {key: value for key, value in values.items() if key not in ('bitrate','codec')}
            stream.pending_audio = None
            stream.audio_status = 'ready'
            stream.audio_error = ''
            audit('station_audio_applied', station_id=station.id, target_type='station',
                  target_id=station.slug, summary=f'Audio settings applied: {values["bitrate"]} kbps')
            db.session.commit()
        except Exception as error:
            db.session.rollback()
            # Also restore when runtime succeeded but committing active values failed.
            if not isinstance(error, runtime.AudioRecoveryError):
                try:
                    runtime.restore_audio(station)
                except runtime.AudioRecoveryError as recovery_error:
                    error = recovery_error
            db.session.refresh(stream)
            stream.audio_status = 'failed'
            stream.audio_error = ('Audio change failed and the station could not be restored. Check station status before retrying.'
                if isinstance(error, runtime.AudioRecoveryError) else
                'Audio change failed. Previous settings were retained. Retry or check the provisioning service.')
            audit('station_audio_failed', station_id=station.id, target_type='station',
                  target_id=station.slug, summary=stream.audio_error)
            db.session.commit()
            raise
        else:
            # Active settings are already committed. A leftover backup is harmless.
            try:
                runtime.finish_audio(station)
            except OSError:
                from flask import current_app
                current_app.logger.warning('Could not remove audio backup for station id=%s', station.id)


def process_pending_audio():
    ids = [row.station_id for row in StreamMount.query.filter(StreamMount.audio_status.in_(('pending', 'applying'))).order_by(StreamMount.id).limit(1)]
    failures = []
    for identifier in ids:
        try:
            process_audio(db.session.get(Station, identifier))
        except Exception:
            failures.append(identifier)
    return failures
