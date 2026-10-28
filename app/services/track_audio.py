"""Non-destructive track editing policy shared by playback and audition."""
import math

FIELDS = ('cue_in_ms', 'cue_out_ms', 'fade_in_ms', 'fade_out_ms', 'gain_trim_db')


def validate(data, duration):
    if not isinstance(data, dict) or set(data) - {*FIELDS, 'revision'}:
        raise ValueError('Invalid audio settings')
    result = {}
    for name in FIELDS:
        value = data.get(name)
        if value in (None, ''):
            result[name] = 0 if name.startswith('fade_') else None
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)) or (isinstance(value, float) and not math.isfinite(value)):
            raise ValueError('Audio settings must be finite numbers')
        if name == 'gain_trim_db':
            if not -12 <= value <= 12:
                raise ValueError('Gain trim must be between −12 and +12 dB')
            result[name] = round(value, 3)
        else:
            if value != int(value) or not 0 <= value <= duration:
                raise ValueError('Cue points and fades must be whole milliseconds within the file')
            result[name] = int(value)
    start = result['cue_in_ms'] or 0
    end = duration if result['cue_out_ms'] is None else result['cue_out_ms']
    if start >= end:
        raise ValueError('Cue out must be after cue in')
    if result['fade_in_ms'] + result['fade_out_ms'] > end - start:
        raise ValueError('Combined fades must fit within the playable audio')
    return result


def effective(song):
    duration = song.duration_ms
    neutral = dict(cue_in_ms=0, cue_out_ms=duration, fade_in_ms=0, fade_out_ms=0, gain_trim_db=0)
    if not getattr(song, 'audio_edit_enabled', False):
        return neutral
    try:
        values = validate({name: getattr(song, name, None) for name in FIELDS}, duration)
    except ValueError:
        # Malformed imported/legacy settings must not silence broadcast playback.
        return neutral
    values['cue_in_ms'] = values['cue_in_ms'] or 0
    values['cue_out_ms'] = duration if values['cue_out_ms'] is None else values['cue_out_ms']
    values['gain_trim_db'] = values['gain_trim_db'] or 0
    return values


def duration_ms(song):
    values = effective(song)
    return values['cue_out_ms'] - values['cue_in_ms']


def state(song, station=None):
    from app.services.loudness import gain_for
    return dict(enabled=bool(song.audio_edit_enabled), revision=song.audio_edit_revision,
                source_duration_ms=song.duration_ms, duration_ms=duration_ms(song),
                saved={name: getattr(song, name) for name in FIELDS},
                effective=effective(song), gain=gain_for(song, station))


def annotations(song):
    return snapshot_annotations(dict(enabled=song.audio_edit_enabled, effective=effective(song)))


def snapshot(song, station, *, cart=False):
    from app.services.loudness import gain_for
    return dict(enabled=bool(song.audio_edit_enabled), effective=effective(song),
                duration_ms=duration_ms(song),
                gain_db=0 if cart and not song.audio_edit_enabled else gain_for(song, station)['db'])


def prepare_snapshot(decision):
    """Caller commits with submission intent before any engine mutation."""
    if decision.track and decision.audio_snapshot is None:
        item = decision.block_item_execution
        decision.audio_snapshot = (item.audio_snapshot if item and item.audio_snapshot else
                                   snapshot(decision.track, decision.station,
                                            cart=decision.playback_bus == 'CART'))
    return decision.audio_snapshot


def decision_duration_ms(decision):
    saved = decision.audio_snapshot
    return saved['duration_ms'] if saved else duration_ms(decision.track or decision.imaging_asset)


def snapshot_annotations(saved):
    if not saved['enabled']:
        return ''
    values = saved['effective']
    keys = {'cue_in_ms': 'liq_cue_in', 'cue_out_ms': 'liq_cue_out',
            'fade_in_ms': 'freo_fade_in', 'fade_out_ms': 'freo_fade_out'}
    return ''.join(f',{key}="{values[name] / 1000:.3f}"' for name, key in keys.items())
