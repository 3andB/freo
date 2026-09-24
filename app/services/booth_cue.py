"""Cue editing is transactional; only the worker applies automatic deck commands."""
from datetime import datetime, timezone
import hashlib
import json
import uuid

from app.extensions import db
from app.models import (BoothCue, SavedBoothCue, CuePlayback, CueMutation,
                        Station, Track, SelectionDecision, LiveControlCommand)
from app.services.availability import tracks_for, playable
from app.services.media_storage import LocalMediaStorage

MAX_ENTRIES = 500


class CueChanged(ValueError):
    """A pending automatic request must be selected again from the latest order."""


def next_entry(station, cue):
    storage = LocalMediaStorage()
    for skipped, entry in enumerate(cue.entries):
        track = db.session.get(Track, entry['track_id'])
        if track and playable(track, station.id):
            try:
                storage.regular_file(track.station.slug, track.storage_key)
                return entry, skipped
            except (OSError, ValueError):
                pass
    return None, len(cue.entries)


def validate_automatic(station, cue, binding):
    if not cue.auto_enabled or not binding or binding.completed_at or binding.generation != cue.generation:
        raise CueChanged('Automatic Cue request was cancelled')
    entry, _ = next_entry(station, cue)
    if not entry or entry['id'] != binding.entry_id:
        raise CueChanged('Cue order changed before the automatic start')


def locked(station):
    from app.services.stations import allocation_lock
    allocation_lock()
    db.session.query(Station.id).filter_by(id=station.id).with_for_update().first()
    cue = BoothCue.query.filter_by(station_id=station.id).populate_existing().first()
    if cue is None:
        cue = BoothCue(station_id=station.id)
        db.session.add(cue)
        db.session.flush()
    return cue


def order(cue):
    return [entry['track_id'] for entry in cue.entries]


def describe(station, mixer=None):
    cue = db.session.get(BoothCue, station.id)
    saved = SavedBoothCue.query.filter_by(station_id=station.id).order_by(SavedBoothCue.name, SavedBoothCue.id).all()
    result = dict(revision=cue.revision if cue else 0, name=cue.name if cue else 'Untitled Cue',
        auto_enabled=bool(cue and cue.auto_enabled), message=cue.message if cue else '',
        dirty=bool(cue and (order(cue) != cue.saved_order)), saved_id=cue.saved_id if cue else None,
        entries=[], saved=[dict(id=row.id, name=row.name, count=len(row.tracks)) for row in saved])
    if not cue:
        return result
    tracks = {row.id: row for row in Track.query.filter(Track.id.in_(order(cue))).all()}
    mixer = mixer or {}
    deck_entries = {}
    for deck in ('a', 'b'):
        decision = mixer.get(deck+'_id') or (mixer.get(deck) or {}).get('decision_id')
        binding = db.session.get(CuePlayback, decision) if decision else None
        if binding and binding.station_id == station.id and binding.generation == cue.generation and not binding.completed_at:
            deck_entries.setdefault(binding.entry_id, []).append(dict(deck=deck.upper(), playing=bool(mixer.get(deck+'_playing'))))
    for entry in cue.entries:
        track = tracks.get(entry['track_id'])
        allowed = bool(track and playable(track, station.id))
        result['entries'].append(dict(id=entry['id'], uuid=track.uuid if allowed else None,
            title=track.title if track else 'Unavailable song', artist=track.artist if track else '',
            duration_ms=track.duration_ms if track else 0, available=allowed,
            decks=deck_entries.get(entry['id'], [])))
    return result


def disarm(station, message='AUTO_CUE is off.'):
    cue = db.session.get(BoothCue, station.id)
    if cue:
        cue = locked(station)
    if cue and (cue.auto_enabled or cue.start_pending):
        cue.auto_enabled = False
        cue.start_pending = False
        cue.message = message
        cue.revision += 1


def mutate(station, user, data):
    from app.services.live_assist import _nonce, require_mixer
    nonce = _nonce(data.get('nonce'))
    fingerprint = hashlib.sha256(json.dumps(dict(data), sort_keys=True).encode()).hexdigest()
    # All writers, including completions, use the station lock.
    cue = locked(station)
    prior = db.session.get(CueMutation, nonce)
    if prior:
        if prior.station_id != station.id or prior.fingerprint != fingerprint:
            raise ValueError('Operation token was already used')
        db.session.commit()
        return 'Cue already saved.'
    expected = str(data.get('revision', ''))
    if expected != str(cue.revision) and not (expected == '0' and cue.revision == 1 and not cue.entries):
        raise ValueError('Cue changed in another window or after playback. Review the refreshed list and try again.')
    operation = data.get('operation')
    entries = list(cue.entries)
    message = 'Cue saved.'
    if operation == 'add':
        track = tracks_for(station.id).filter_by(uuid=data.get('identifier')).first()
        if not track or not playable(track, station.id):
            raise ValueError('Song is unavailable for this station')
        if len(entries) >= MAX_ENTRIES:
            raise ValueError('Cue is full (500 songs). Save this set and start another.')
        position = next((i for i, item in enumerate(entries) if item['id'] == data.get('before')), len(entries))
        entries.insert(position, dict(id=str(uuid.uuid4()), track_id=track.id))
        cue.entries = entries
    elif operation in ('remove', 'move'):
        entry = next((item for item in entries if item['id'] == data.get('entry_id')), None)
        if entry is None:
            raise ValueError('Cue entry changed. Refresh and try again.')
        entries.remove(entry)
        if operation == 'move':
            before = data.get('before')
            if before == entry['id']:
                raise ValueError('Choose another position')
            position = next((i for i, item in enumerate(entries) if item['id'] == before), len(entries))
            entries.insert(position, entry)
        cue.entries = entries
    elif operation in ('save', 'save-as', 'rename'):
        name = (data.get('name') or '').strip()
        if not name or len(name) > 120:
            raise ValueError('Choose a Cue name from 1 to 120 characters')
        saved = SavedBoothCue.query.filter_by(station_id=station.id, id=cue.saved_id).first() if cue.saved_id and operation != 'save-as' else None
        if saved is None:
            saved = SavedBoothCue(station_id=station.id, name=name)
            db.session.add(saved)
        saved.name = name
        saved.tracks = order(cue)
        saved.updated_at = datetime.now(timezone.utc)
        db.session.flush()
        cue.saved_id, cue.name, cue.saved_order = saved.id, name, order(cue)
        message = 'Named Cue saved.'
    elif operation in ('load', 'new'):
        if order(cue) != cue.saved_order and data.get('discard') != 'true':
            raise ValueError('Save this Cue or choose Discard before replacing it')
        saved = None
        if operation == 'load':
            identifier = str(data.get('saved_id', ''))
            if not identifier.isascii() or not identifier.isdecimal() or len(identifier) > 9:
                raise ValueError('Choose a saved Cue')
            saved = SavedBoothCue.query.filter_by(station_id=station.id, id=int(identifier)).first()
            if saved is None:
                raise ValueError('Saved Cue is unavailable for this station')
        cue.entries = [dict(id=str(uuid.uuid4()), track_id=identifier) for identifier in saved.tracks] if saved else []
        cue.saved_id = saved.id if saved else None
        cue.name = saved.name if saved else 'Untitled Cue'
        cue.saved_order = list(saved.tracks) if saved else []
        cue.generation = str(uuid.uuid4())
        cue.auto_enabled = cue.start_pending = False
        cue.message = 'AUTO_CUE is off.'
        message = 'Cue loaded.' if saved else 'New Cue ready.'
    elif operation == 'auto':
        enabled = data.get('enabled') == 'true'
        if enabled:
            mixer = require_mixer(station)
            if station.automation.operator_mode != 'DJ_BOOTH' or not station.enabled or station.desired_state != 'running':
                raise ValueError('Take DJ control on a running station first')
            from app.services.live_mic import enabled as mic_enabled, gateway
            if mic_enabled():
                mic = gateway(station.slug, 'status')
                if mic.get('leaving') or (mic.get('desired') == 'LIVE' and mic.get('phase') != 'FAILED') or mic.get('phase') in ('FADING', 'LIVE', 'RETURNING'):
                    raise ValueError('End the live microphone broadcast before arming AUTO_CUE')
            if not entries:
                raise ValueError('Add a song to Cue first')
            cue.start_pending = not any(mixer.get(key+'_id') for key in ('a', 'b'))
            cue.message = 'AUTO_CUE armed · waiting for the song to finish.'
        else:
            cue.start_pending = False
            cue.message = 'AUTO_CUE is off.'
        cue.auto_enabled = enabled
        message = cue.message
    else:
        raise ValueError('Unknown Cue action')
    cue.revision += 1
    db.session.add(CueMutation(token=nonce, station_id=station.id, fingerprint=fingerprint))
    db.session.commit()
    return message


def bind(station, decision, entry_id=None, previous=None):
    cue = locked(station)
    if entry_id:
        entry = next((item for item in cue.entries if item['id'] == entry_id), None)
        if not entry or entry['track_id'] != decision.track_id:
            raise ValueError('This Cue entry changed. Load it again from the updated list.')
    prior = db.session.get(CuePlayback, previous.id) if previous else None
    db.session.add(CuePlayback(decision_id=decision.id, station_id=station.id,
        generation=prior.generation if prior else cue.generation,
        entry_id=prior.entry_id if prior else entry_id))


def interrupt(station, decision_id):
    binding = db.session.get(CuePlayback, decision_id) if decision_id else None
    if binding and binding.station_id == station.id:
        binding.interrupted = True


def completed(station, decision_id, observed_at, engine_identity=None):
    """Consume an engine EOF once. A list replacement invalidates old bindings."""
    cue = locked(station)
    decision = db.session.get(SelectionDecision, decision_id)
    binding = db.session.get(CuePlayback, decision_id)
    if not decision or decision.station_id != station.id or decision.playback_bus not in ('A', 'B'):
        db.session.commit()
        return False
    if not binding:
        # Historical log lines and plays from before this feature are never triggers.
        db.session.commit()
        return False
    if binding.completed_at:
        db.session.commit()
        return False
    binding.completed_at = observed_at
    if binding.interrupted or binding.generation != cue.generation or not decision.started_at or (engine_identity and decision.socket_identity != engine_identity):
        db.session.commit()
        return False
    entries = list(cue.entries)
    entry = next((item for item in entries if item['id'] == binding.entry_id), None)
    if entry:
        entries.remove(entry)
        entries.append(entry)
        cue.entries = entries
    if cue.auto_enabled and station.automation.operator_mode == 'DJ_BOOTH':
        cue.start_pending = True
        cue.last_deck = decision.playback_bus
    cue.revision += 1
    db.session.commit()
    return True


def advance(station, mixer, reader):
    """Run before the booth's return-to-schedule check; browser presence is irrelevant."""
    from app.services.playout_queue import socket_identity
    from app.automation_worker import process_deck_command
    cue = db.session.get(BoothCue, station.id)
    if not cue or not cue.auto_enabled:
        return False
    cue = locked(station)
    if station.automation.operator_mode != 'DJ_BOOTH' or mixer.get('mode') != 'DJ_BOOTH':
        disarm(station)
        db.session.commit()
        return False
    if not cue.start_pending:
        db.session.commit()
        return False
    if mixer.get('cart_id') or mixer.get('transition', {}).get('incoming') or LiveControlCommand.query.filter_by(station_id=station.id, status='pending').first():
        db.session.commit()
        return True
    if any(mixer.get(key+'_id') for key in ('a', 'b')):
        # Never overwrite a prepared song or advance over a still-audible deck.
        # When one deck is empty and the other is paused, reuse the empty deck.
        if any(mixer.get(key+'_id') and mixer.get(key+'_playing') for key in ('a', 'b')):
            db.session.commit()
            return True
    deck = next((key for key in (cue.last_deck, 'B' if cue.last_deck == 'A' else 'A') if not mixer.get(key.lower()+'_id')), None)
    if deck is None:
        cue.message = 'AUTO_CUE waiting · both decks have prepared songs.'
        db.session.commit()
        return True
    target_entry, unavailable = next_entry(station, cue)
    if target_entry is None:
        disarm(station, 'AUTO_CUE paused · no playable songs. Check the Cue or load another set.')
        db.session.commit()
        return False
    decision = SelectionDecision(station_id=station.id, track_id=target_entry['track_id'],
        playback_bus=deck, selection_method='cue_auto', reason='deck_load', status='selected', idempotency_key=str(uuid.uuid4()))
    db.session.add(decision)
    db.session.flush()
    db.session.add(CuePlayback(decision_id=decision.id, station_id=station.id, generation=cue.generation, entry_id=target_entry['id']))
    command = LiveControlCommand(station_id=station.id, deck=deck, action='DECK_LOAD',
        fade_seconds=0, play_on_load=True, target_decision_id=decision.id,
        status='pending', idempotency_key=str(uuid.uuid4()))
    db.session.add(command)
    cue.start_pending = False
    cue.message = f'AUTO_CUE · playing on Deck {deck}' + (f' · skipped {unavailable} unavailable song(s).' if unavailable else '')
    cue.revision += 1
    db.session.commit()
    try:
        process_deck_command(station, command, socket_identity(station.slug))
    except (OSError, RuntimeError, ValueError) as error:
        db.session.rollback()
        command.status, command.error_code = 'failed', 'cue_changed' if isinstance(error, CueChanged) else 'auto_cue_failed'
        decision.status = 'failed'
        cue = locked(station)
        if isinstance(error, CueChanged):
            cue.start_pending = cue.auto_enabled
        else:
            disarm(station, 'AUTO_CUE paused · the next song could not start. Check the deck and re-arm.')
        db.session.commit()
        return cue.auto_enabled
    reader.dj_stopped_since.pop(station.slug, None)
    return True
