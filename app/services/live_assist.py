"""Station-scoped operator intent. Only the automation worker touches playout sockets."""
import uuid
from datetime import datetime, timedelta, timezone

from app.extensions import db
from app.models import (AuditEvent, AutomationState, EventBlock, EventBlockExecution, ImagingAsset, LiveCartSlot, LiveControlCommand, LiveQueueSnapshot,
                        SelectionDecision, Station, Track)
from app.services.admin_media import audit
from app.services.media_storage import LocalMediaStorage

MAX_LIVE_QUEUE_ITEMS = 20


def _nonce(value):
    try:
        return str(uuid.UUID(value))
    except (TypeError, ValueError, AttributeError) as error:
        raise ValueError('Invalid operation token') from error


def set_hold(station, user, held):
    state = db.session.get(AutomationState, station.id)
    if state is None or not state.enabled or not station.enabled or station.desired_state != 'running':
        raise ValueError('Station automation is unavailable')
    state.hold = held
    audit('automation_held' if held else 'automation_resumed', user_id=user.id,
          station_id=station.id, target_type='station', target_id=station.slug,
          summary='Automation refill held' if held else 'Automation refill resumed')
    db.session.commit()

def set_mode(station,user,mode):
    mode=(mode or '').upper()
    if mode not in ('AUTO','DJ_BOOTH'):raise ValueError('Invalid booth mode')
    state=db.session.get(AutomationState,station.id)
    if state is None or not station.enabled or station.desired_state!='running':raise ValueError('Station playout is unavailable')
    if state.operator_mode != mode and mode == 'AUTO':
        return return_to_schedule(station,user=user)
    if state.operator_mode != mode:
        state.cued_track_id = None
        state.deck_a_playing, state.deck_b_playing, state.crossfader = True, False, 0.0
    state.operator_mode=mode;state.hold=mode=='DJ_BOOTH'
    if mode == 'AUTO':
        state.enabled = True
    audit('live_mode_changed',user_id=user.id,station_id=station.id,target_type='station',target_id=station.slug,summary=f'DJ booth mode changed to {mode}')
    db.session.commit();return state


def return_to_schedule(station, user=None, reason='Returning to the schedule: DJ audio fades out over 3 seconds, then scheduled music fades in.'):
    state=station.automation
    state.operator_mode='AUTO';state.hold=False;state.enabled=True
    state.cued_track_id=None
    state.deck_a_playing=True;state.deck_b_playing=False;state.crossfader=0.0
    audit('live_auto_return',user_id=user.id if user else None,station_id=station.id,
          target_type='station',target_id=station.slug,summary=reason)
    db.session.commit()
    return state


def queue_playable(station, user, kind, identifier, nonce, *, bus='A', cart_mode='OVER', duck_percent=50):
    nonce = _nonce(nonce)
    if bus not in ('A','B','CART'):
        raise ValueError('Invalid broadcast destination')
    if bus != 'A':
        require_mixer(station)
    if cart_mode not in ('OVER','TAKEOVER') or not 0 <= duck_percent <= 100:
        raise ValueError('Invalid cart settings')
    # Serialize concurrent browser queue requests for this station. PostgreSQL
    # row locking keeps the 20-item cap meaningful across multiple operators.
    db.session.query(Station.id).filter_by(id=station.id).with_for_update().first()
    existing = SelectionDecision.query.filter_by(idempotency_key=nonce).first()
    if existing:
        if existing.station_id == station.id and existing.admin_user_id == user.id and existing.selection_method == f'manual_{kind}' and existing.playback_bus == bus and (existing.track and existing.track.uuid == identifier or existing.imaging_asset and existing.imaging_asset.uuid == identifier):
            return existing
        raise ValueError('Operation token was already used')
    if not station.enabled or station.desired_state != 'running':
        raise ValueError('Station is not running')
    if kind == 'track':
        playable = Track.query.filter_by(station_id=station.id, uuid=identifier).first()
    elif kind == 'imaging':
        playable = ImagingAsset.query.filter_by(station_id=station.id, uuid=identifier).first()
    else:
        raise ValueError('Invalid playable type')
    if playable is None or not playable.enabled or playable.ingest_status != 'accepted' or playable.decommissioned_at:
        raise ValueError('Playable is unavailable for this station')
    storage = LocalMediaStorage()
    try:
        if kind == 'track':
            storage.regular_file(station.slug, playable.storage_key)
        else:
            storage.imaging_file(station.slug, playable.storage_key)
    except (OSError, ValueError) as error:
        raise ValueError('Approved audio is unavailable') from error
    # This cap includes worker-submitted and browser-pending requests. The worker
    # checks actual Liquidsoap depth again before pushing.
    pending = SelectionDecision.query.filter(SelectionDecision.station_id == station.id,
        SelectionDecision.status.in_(('selected', 'submitting', 'queued'))).count()
    if pending >= MAX_LIVE_QUEUE_ITEMS:
        raise ValueError('Live queue is full')
    row = SelectionDecision(station_id=station.id, track_id=playable.id if kind == 'track' else None,
        imaging_asset_id=playable.id if kind == 'imaging' else None,
        selection_method=f'manual_{kind}', admin_user_id=user.id,
        idempotency_key=nonce, status='selected', reason='operator_queue_end', playback_bus=bus, cart_mode=cart_mode, duck_percent=duck_percent)
    db.session.add(row)
    db.session.flush()
    audit('manual_track_queued' if kind == 'track' else 'manual_imaging_queued',
          user_id=user.id, station_id=station.id, target_type=kind,
          target_id=identifier, summary='Operator requested Queue End')
    db.session.commit()
    return row


def request_skip(station, user, expected_decision_id, nonce):
    nonce = _nonce(nonce)
    existing = LiveControlCommand.query.filter_by(idempotency_key=nonce).first()
    if existing:
        if existing.station_id == station.id and existing.admin_user_id == user.id and existing.expected_decision_id == expected_decision_id:
            return existing
        raise ValueError('Operation token was already used')
    current = SelectionDecision.query.filter_by(id=expected_decision_id, station_id=station.id, status='started').first()
    if current is None or not station.enabled or station.desired_state != 'running':
        raise ValueError('Current item changed; refresh before skipping')
    row = LiveControlCommand(station_id=station.id, admin_user_id=user.id,action='SKIP',
        idempotency_key=nonce, expected_decision_id=current.id, status='pending')
    db.session.add(row)
    audit('manual_skip_requested', user_id=user.id, station_id=station.id,
          target_type='decision', target_id=str(current.id), summary='Operator requested skip of current item')
    db.session.commit()
    return row


def request_fade(station, user, expected_decision_id, nonce):
    nonce = _nonce(nonce)
    current = SelectionDecision.query.filter_by(id=expected_decision_id,
        station_id=station.id, status='started').first()
    if current is None:
        raise ValueError('Current item changed; refresh before fading')
    existing = LiveControlCommand.query.filter_by(idempotency_key=nonce).first()
    if existing:
        return existing
    row = LiveControlCommand(station_id=station.id, admin_user_id=user.id,
        action='FADE', idempotency_key=nonce, expected_decision_id=current.id,
        status='pending')
    db.session.add(row)
    audit('manual_fade_requested', user_id=user.id, station_id=station.id,
        target_type='decision', target_id=str(current.id),
        summary='Operator requested fixed three-second fade and advance')
    db.session.commit()
    return row


def cue_track(station, user, identifier):
    track = Track.query.filter_by(station_id=station.id, uuid=identifier,
        enabled=True, ingest_status='accepted', decommissioned_at=None).first()
    if track is None:
        raise ValueError('Song is unavailable for this station')
    if not station.automation or not station.enabled or station.desired_state != 'running':
        raise ValueError('Station is not running')
    try:
        LocalMediaStorage().regular_file(station.slug, track.storage_key)
    except (OSError, ValueError) as error:
        raise ValueError('Approved audio is unavailable') from error
    if station.automation.cued_track_id == track.id:
        return track
    station.automation.cued_track_id = track.id
    audit('live_cue_loaded', user_id=user.id, station_id=station.id,
        target_type='track', target_id=track.uuid, summary='Song loaded into cue deck')
    db.session.commit()
    return track


def clear_cue(station, user):
    state = station.automation
    if state.cued_track:
        audit('live_cue_cleared', user_id=user.id, station_id=station.id,
            target_type='track', target_id=state.cued_track.uuid,
            summary='Cue deck cleared')
    state.cued_track_id = None
    db.session.commit()

def request_takeover(station,user,identifier,expected_decision_id,nonce):
    nonce = _nonce(nonce)
    current = SelectionDecision.query.filter_by(id=expected_decision_id, station_id=station.id, status='started').first() if expected_decision_id is not None else None
    if expected_decision_id is not None and current is None:
        raise ValueError('Current item changed; refresh before takeover')
    track=Track.query.filter_by(station_id=station.id,uuid=identifier,enabled=True,ingest_status='accepted',decommissioned_at=None).first()
    if not track:raise ValueError('Song is unavailable for this station')
    if not station.enabled or station.desired_state != 'running':
        raise ValueError('Station is not running')
    existing = LiveControlCommand.query.join(SelectionDecision, LiveControlCommand.target_decision_id == SelectionDecision.id).filter(SelectionDecision.idempotency_key == nonce).first()
    if existing:
        if existing.station_id == station.id and existing.admin_user_id == user.id and existing.expected_decision_id == expected_decision_id and existing.target_decision.track_id == track.id:
            return existing
        raise ValueError('Operation token was already used')
    if current is None:
        observed = status(station)
        if observed['playout_error']:
            raise ValueError('Station observation is unavailable. Reconnect before starting Deck A.')
        deck_current = observed['mixer'].get('a_id') if observed.get('mixer') else observed['current']
        if deck_current or observed['queue'] or observed['unknown_queue_items']:
            raise ValueError('Station audio changed. Review the current song before taking air.')
    try:
        LocalMediaStorage().regular_file(station.slug, track.storage_key)
    except (OSError, ValueError) as error:
        raise ValueError('Approved audio is unavailable') from error
    target=SelectionDecision(station_id=station.id,track_id=track.id,selection_method='manual_track',admin_user_id=user.id,idempotency_key=nonce,status='selected',reason='operator_takeover');db.session.add(target);db.session.flush()
    command=LiveControlCommand(station_id=station.id,admin_user_id=user.id,idempotency_key=str(uuid.uuid4()),expected_decision_id=current.id if current else None,target_decision_id=target.id,action='TAKEOVER',status='pending');db.session.add(command)
    audit('manual_takeover_requested',user_id=user.id,station_id=station.id,target_type='track',target_id=track.uuid,summary='Operator requested controlled current-song takeover');db.session.commit();return command


def assign_cart(station, user, role, position, identifier, label='', description='', playback_mode='OVER', duck_percent=50):
    from app.services.programming import clean_text
    role = (role or '').upper()
    maximum = 8 if role == 'HOT' else 4 if role == 'ID' else 0
    if not 1 <= position <= maximum:
        raise ValueError('Invalid cart position')
    if playback_mode not in ('OVER','TAKEOVER') or not 0 <= int(duck_percent) <= 100:
        raise ValueError('Choose play over or take over and a volume reduction from 0 to 100%')
    identifier = (identifier or '').removeprefix('track:').removeprefix('imaging:')
    asset = ImagingAsset.query.filter_by(station_id=station.id, uuid=identifier, enabled=True, ingest_status='accepted', decommissioned_at=None).first()
    track = Track.query.filter_by(station_id=station.id, uuid=identifier, enabled=True, ingest_status='accepted', decommissioned_at=None).first() if not asset else None
    if not asset and not track:
        raise ValueError('Cart audio is unavailable for this station')
    try:
        if track:
            LocalMediaStorage().regular_file(station.slug, track.storage_key)
        else:
            LocalMediaStorage().imaging_file(station.slug, asset.storage_key)
    except (OSError, ValueError) as error:
        raise ValueError('Cart audio is unavailable') from error
    slot = LiveCartSlot.query.filter_by(station_id=station.id, role=role, position=position).first()
    if slot is None:
        slot = LiveCartSlot(station_id=station.id, role=role, position=position)
    slot.imaging_asset_id, slot.track_id = asset.id if asset else None, track.id if track else None
    slot.label = clean_text(label, 40)
    slot.description = clean_text(description, 500)
    slot.playback_mode, slot.duck_percent = playback_mode, int(duck_percent)
    db.session.add(slot)
    audit('live_cart_assigned', user_id=user.id, station_id=station.id,
        target_type='track' if track else 'imaging_asset', target_id=identifier, summary=f'{role} cart {position} assigned')
    db.session.commit()
    return slot


def require_mixer(station):
    snapshot = db.session.get(LiveQueueSnapshot, station.id)
    if not snapshot or not snapshot.mixer or snapshot.error_code or (datetime.now(timezone.utc)-snapshot.observed_at.replace(tzinfo=snapshot.observed_at.tzinfo or timezone.utc)).total_seconds() > 15:
        raise ValueError('The broadcast mixer is not connected yet. Check station status before using this control.')
    return snapshot.mixer


def set_mixer(station, user, control, value):
    import math
    require_mixer(station)
    state = station.automation
    if state.operator_mode != 'DJ_BOOTH':
        raise ValueError('Take DJ control before operating the decks')
    if control == 'crossfader':
        number = float(value)
        if not math.isfinite(number) or not 0 <= number <= 1:
            raise ValueError('Fader position must be between 0 and 1')
        state.crossfader = number
    elif control in ('a_playing','b_playing') and value in ('true','false'):
        setattr(state, 'deck_' + control, value == 'true')
    else:
        raise ValueError('Invalid mixer control')
    audit('live_mixer_changed', user_id=user.id, station_id=station.id, target_type='station', target_id=station.slug, summary=f'Operator changed {control}')
    db.session.commit()


def fire_cart(station, user, role, position, nonce):
    slot = LiveCartSlot.query.filter_by(station_id=station.id, role=role, position=position).first()
    if not slot or not slot.playable:
        raise ValueError('Assign audio to this cart first')
    return queue_playable(station, user, 'track' if slot.track else 'imaging', slot.playable.uuid, nonce,
                          bus='CART', cart_mode=slot.playback_mode, duck_percent=slot.duck_percent)


def play_cue_on_b(station, user, nonce):
    observed = require_mixer(station)
    if station.automation.operator_mode != 'DJ_BOOTH':
        raise ValueError('Take DJ control before starting Deck B')
    if observed.get('b_id'):
        raise ValueError('Deck B already has audio. Pause it or let it finish before loading another song.')
    track = station.automation.cued_track
    if not track:
        raise ValueError('Load a song into Cue first')
    if SelectionDecision.query.filter_by(station_id=station.id, playback_bus='B').filter(SelectionDecision.status.in_(('selected','submitting','queued'))).first():
        raise ValueError('Deck B is already starting')
    row = queue_playable(station, user, 'track', track.uuid, nonce, bus='B')
    station.automation.deck_b_playing = True
    db.session.commit()
    return row


def queue_block(station, user, identifier):
    from app.services.event_blocks import block_for, create_execution, active_execution
    if active_execution(station.id): raise ValueError('A block is already active')
    try: block=block_for(station.slug,identifier)
    except ValueError as error: raise ValueError('Block is unavailable for this station') from error
    execution=create_execution(block,'MANUAL',admin_user_id=user.id)
    audit('event_block_queued',user_id=user.id,station_id=station.id,target_type='event_block',target_id=block.slug,summary='Operator queued ordered block')
    db.session.commit(); return execution

def request_abort_block(station, user, execution_id):
    execution=EventBlockExecution.query.filter_by(id=execution_id,station_id=station.id).filter(EventBlockExecution.state.in_(('PENDING','QUEUED','STARTED'))).first()
    if execution is None: raise ValueError('Active block changed; refresh first')
    execution.abort_requested=True
    audit('event_block_abort_requested',user_id=user.id,station_id=station.id,target_type='event_block_execution',target_id=str(execution.id),summary='Operator requested block abort')
    db.session.commit(); return execution


def safe_item(row):
    source = 'BLOCK' if row.selection_method == 'event_block' else 'EVENT' if row.selection_method == 'timed_event' else 'MANUAL' if row.admin_user_id else 'AUTO'
    if row.track:
        return dict(decision_id=row.id, kind='track', title=row.track.title,
                    artist=row.track.artist,album=row.track.album,category=row.category.name if row.category else None,source=source,
                    started_at=row.started_at.isoformat() if row.started_at else None,
                    duration_ms=row.track.duration_ms, uuid=row.track.uuid,
                    bpm=row.track.bpm, genre=row.track.genre,
                    year=row.track.release_year, loudness_lufs=row.track.loudness_lufs,
                    album_id=row.track.album_id, bitrate_kbps=row.track.bitrate_kbps,
                    deck=row.playback_bus or 'A')
    if row.imaging_asset:
        asset = row.imaging_asset
        return dict(decision_id=row.id, kind='imaging', title=asset.name,
                    artist=asset.asset_type.replace('_', ' ').title(), cart_code=asset.cart_code,
                    source=source,
                    started_at=row.started_at.isoformat() if row.started_at else None,
                    duration_ms=asset.duration_ms, uuid=asset.uuid)
    return dict(decision_id=row.id, kind='unavailable', title='Unavailable item', artist='', source='UNKNOWN')


def status(station):
    from app.services.schedule import resolve
    state = station.automation
    snapshot = db.session.get(LiveQueueSnapshot, station.id)
    fresh = bool(snapshot and (datetime.now(timezone.utc) - snapshot.observed_at.replace(
        tzinfo=snapshot.observed_at.tzinfo or timezone.utc)).total_seconds() < 10)
    live_error = snapshot.error_code if fresh else 'Worker observation unavailable'
    reliable = fresh and not live_error
    last_row = db.session.get(SelectionDecision, snapshot.current_decision_id) if snapshot and snapshot.current_decision_id else None
    last_known = safe_item(last_row) if last_row and last_row.station_id == station.id else None
    ids = ([snapshot.current_decision_id] if reliable and snapshot.current_decision_id else []) + (snapshot.queued_decision_ids if reliable else [])
    rows = SelectionDecision.query.filter(SelectionDecision.station_id == station.id,
        SelectionDecision.id.in_(ids)).all() if ids else []
    by_id = {row.id: row for row in rows}
    current = safe_item(by_id[snapshot.current_decision_id]) if reliable and snapshot.current_decision_id in by_id else None
    queue = [safe_item(by_id[identifier]) for identifier in snapshot.queued_decision_ids if identifier in by_id] if reliable else []
    unknown = snapshot.unknown_count if fresh else 0
    recent = SelectionDecision.query.filter_by(station_id=station.id, status='started').order_by(
        SelectionDecision.started_at.desc(), SelectionDecision.id.desc()).limit(10).all()
    programming = resolve(station)
    from app.services.timed_events import upcoming
    events = upcoming(station, limit=1)
    next_event = events[0] if events else None
    overrun_seconds = None
    if next_event and current and current.get('started_at') and current.get('duration_ms'):
        estimated_end = datetime.fromisoformat(current['started_at']) + timedelta(milliseconds=current['duration_ms'])
        scheduled = next_event.scheduled_for_utc.replace(tzinfo=next_event.scheduled_for_utc.tzinfo or timezone.utc)
        overrun_seconds = round((estimated_end - scheduled).total_seconds())
    active_block=EventBlockExecution.query.filter_by(station_id=station.id).filter(EventBlockExecution.state.in_(('PENDING','QUEUED','STARTED'))).first()
    cue = safe_item(SelectionDecision(station_id=station.id, track=state.cued_track,
        selection_method='manual_track')) if state and state.cued_track else None
    if cue:
        cue['uuid'] = state.cued_track.uuid
        cue['bpm'] = state.cued_track.bpm
        cue['album_id'] = state.cued_track.album_id
    if snapshot and snapshot.mixer and reliable:
        mixer = dict(snapshot.mixer)
        for deck in ('a','b','cart'):
            row = deck_item(station,mixer,deck.upper()) if deck in ('a','b') else (db.session.get(SelectionDecision, mixer.get(deck+'_id')) if mixer.get(deck+'_id') else None)
            mixer[deck] = safe_item(row) if row and row.station_id == station.id else None
            if deck in ('a','b'):
                if not row or not mixer.get(deck+'_id'):
                    mixer[deck+'_playing'] = False
                    mixer[deck+'_elapsed'] = 0
                elif not row.started_at and not mixer.get(deck+'_playing'):
                    mixer[deck+'_elapsed'] = 0
        snapshot_mixer = mixer
    else:
        snapshot_mixer = None
    deck_command = LiveControlCommand.query.filter_by(station_id=station.id).filter(LiveControlCommand.action.like('DECK_%')).order_by(LiveControlCommand.id.desc()).first()
    mode_notice=AuditEvent.query.filter_by(station_id=station.id,action='live_auto_return').order_by(AuditEvent.id.desc()).first()
    return dict(mode_notice=dict(id=mode_notice.id,message=mode_notice.summary) if mode_notice else None,station=station.slug, automation='HELD' if state and state.hold else 'RUNNING' if state and state.enabled else 'DISABLED',mode=state.operator_mode if state else 'AUTO',cue=cue,
        current=current, mixer=snapshot_mixer, deck_command=(dict(id=deck_command.id,status=deck_command.status,deck=deck_command.deck,operation=deck_command.action.removeprefix('DECK_'),error=deck_command.error_code) if deck_command else None), last_known_current=last_known, observation_fresh=reliable, observed_at=snapshot.observed_at.isoformat() if snapshot else None, queue=queue, unknown_queue_items=unknown,
        program_rms=snapshot.program_rms if fresh else None,
        fallback='Possible' if not current and not live_error and station.desired_state == 'running' else 'Not observed',
        playout_error=live_error, recent=[safe_item(row) for row in recent],
        clock=programming.clock.name if programming.clock else None,
        next_transition=programming.next_transition.isoformat() if programming.next_transition else None,
        local_time=programming.local_time.isoformat(), timed_events='PAUSED' if state and state.operator_mode == 'DJ_BOOTH' else 'ACTIVE',
        active_block=(dict(id=active_block.id,name=active_block.block.name,state=active_block.state,
            source=active_block.source,completed_items=len([i for i in active_block.items if i.state in ('COMPLETED','SKIPPED')]),total_items=len(active_block.items)) if active_block else None),
        next_event=(dict(id=next_event.id, name=next_event.event.name,
            timing_mode=next_event.event.timing_mode, state=next_event.state,
            scheduled_for=next_event.scheduled_for_utc.isoformat(), estimated_current_overrun_seconds=overrun_seconds) if next_event else None))


def deck_item(station, mixer, deck):
    """A paused prepared request may not have emitted its on-track callback yet."""
    identifier = mixer.get(deck.lower()+'_id')
    row = db.session.get(SelectionDecision, identifier) if identifier else None
    if row is None:
        row = SelectionDecision.query.filter_by(station_id=station.id, playback_bus=deck, status='queued').order_by(SelectionDecision.id).first()
    return row if row and row.station_id == station.id else None


def request_deck(station, user, deck, action, identifier, expected, nonce, fade_seconds=3, play_on_load=False):
    if deck not in ('A','B') or action not in ('LOAD','PLAY','PAUSE','CLEAR','FADE','REPEAT'):
        raise ValueError('Choose a valid deck button')
    try:
        fade_seconds = float(fade_seconds)
    except (ValueError, TypeError):
        raise ValueError('Choose a fade between 0 and 10 seconds')
    if not 0 <= fade_seconds <= 10:
        raise ValueError('Choose a fade between 0 and 10 seconds')
    if not isinstance(play_on_load, bool) or (play_on_load and action != 'LOAD'):
        raise ValueError('Invalid play-on-load option')
    nonce = _nonce(nonce)
    db.session.query(Station.id).filter_by(id=station.id).with_for_update().first()
    prior = LiveControlCommand.query.filter_by(idempotency_key=nonce).first()
    if prior:
        if prior.station_id == station.id and prior.admin_user_id == user.id and prior.deck == deck and prior.action == 'DECK_'+action:
            return prior
        raise ValueError('Operation token was already used')
    mixer = require_mixer(station)
    if station.automation.operator_mode != 'DJ_BOOTH' or not station.enabled or station.desired_state != 'running':
        raise ValueError('Take DJ control on a running station first')
    if LiveControlCommand.query.filter_by(station_id=station.id,status='pending').first():
        raise ValueError('A deck change is still being applied. Wait for the deck to update.')
    current = deck_item(station,mixer,deck)
    if (str(current.id) if current else '') != (expected or ''):
        raise ValueError('This deck changed. Review its song and try again.')
    if action == 'LOAD' and mixer.get(deck.lower()+'_playing') and current and not play_on_load:
        raise ValueError('This deck is playing. Confirm replacement and go live first.')
    if action != 'LOAD' and current is None:
        raise ValueError('Load a song on this deck first')
    target = None
    if action in ('LOAD','REPEAT'):
        track = Track.query.filter_by(station_id=station.id,uuid=identifier,enabled=True,ingest_status='accepted',decommissioned_at=None).first() if action=='LOAD' else current.track
        if not track or not track.enabled or track.decommissioned_at:
            raise ValueError('Choose an available song for this deck')
        try:
            LocalMediaStorage().regular_file(station.slug,track.storage_key)
        except (OSError,ValueError) as error:
            raise ValueError('The song audio is unavailable') from error
        target=SelectionDecision(station_id=station.id,track=track,playback_bus=deck,selection_method='manual_track',admin_user_id=user.id,idempotency_key=str(uuid.uuid4()),status='selected',reason='deck_'+action.lower())
        db.session.add(target);db.session.flush()
    command=LiveControlCommand(station_id=station.id,admin_user_id=user.id,deck=deck,action='DECK_'+action,fade_seconds=fade_seconds,play_on_load=play_on_load,idempotency_key=nonce,expected_decision_id=current.id if current else None,target_decision_id=target.id if target else None,status='pending')
    db.session.add(command)
    audit('deck_button_requested',user_id=user.id,station_id=station.id,target_type='deck',target_id=deck,summary=f'{action} requested for Deck {deck}')
    db.session.commit()
    return command
