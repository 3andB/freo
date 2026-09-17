"""Validated station audio settings and durable, worker-applied changes."""
import math

from app.extensions import db
from app.models import Station, StreamMount
from app.services.admin_media import audit
from app.services.stations import allocation_lock

BITRATES = (64, 96, 128)
DEFAULT_PROCESSING = dict(agc=False, multiband=False, eq=False, bass=0.0, mid=0.0, treble=0.0)


def validate_settings(value):
    if not isinstance(value, dict) or set(value) - {'bitrate', *DEFAULT_PROCESSING}:
        raise ValueError('Invalid audio settings')
    bitrate = value.get('bitrate')
    if type(bitrate) is not int or bitrate not in BITRATES:
        raise ValueError('Choose 64, 96 or 128 kbps')
    result = dict(DEFAULT_PROCESSING, **value)
    for key in ('agc', 'multiband', 'eq'):
        if type(result[key]) is not bool:
            raise ValueError('Invalid processing option')
    for key in ('bass', 'mid', 'treble'):
        number = result[key]
        if type(number) not in (int, float) or not math.isfinite(number) or not -6 <= number <= 6:
            raise ValueError('EQ must be between −6 and +6 dB')
        result[key] = round(float(number), 1)
    return result


def active_settings(stream):
    return validate_settings(dict(stream.audio_processing or {}, bitrate=stream.bitrate))


def from_form(form):
    try:
        return validate_settings(dict(bitrate=int(form.get('bitrate', '')),
            **{key: form.get(key) == 'yes' for key in ('agc', 'multiband', 'eq')},
            **{key: float(form.get(key, '0')) for key in ('bass', 'mid', 'treble')}))
    except (ValueError, TypeError) as error:
        raise ValueError('Choose 64, 96 or 128 kbps and EQ values between −6 and +6 dB') from error


def queue_settings(station, values, revision, user):
    values = validate_settings(values)
    allocation_lock()
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
    values = validate_settings(values)
    lines = []
    if values['agc']:
        lines.append('radio = normalize(target=-16.0, lufs=true, gain_min=-6.0, gain_max=6.0, threshold=-40.0, up=10.0, down=0.5, window=3.0, lookahead=0.0, track_sensitive=false, radio)')
    if values['eq']:
        for key, frequency in (('bass', 100.0), ('mid', 1000.0), ('treble', 8000.0)):
            if values[key]:
                lines.append(f'radio = filter.iir.eq.peak(frequency={frequency:.1f}, gain={values[key]:.1f}, q=0.7, radio)')
    if values['multiband']:
        lines.append('radio = compress.multiband(limit=false, radio, [\n' + ',\n'.join(
            f'  {{frequency={frequency}, attack=20.0, release=250.0, ratio=1.5, threshold=-18.0, gain=0.0}}'
            for frequency in ('200.0', '2500.0', '22050.0')) + '\n])')
    return '\n'.join(lines)


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
        values = validate_settings(stream.pending_audio)
        # Keep active values unchanged until runtime validation and restart succeed.
        stream.audio_status = 'applying'
        db.session.commit()
        try:
            runtime.apply_audio(station, values)
            stream.bitrate = values['bitrate']
            stream.audio_processing = {key: values[key] for key in DEFAULT_PROCESSING}
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
