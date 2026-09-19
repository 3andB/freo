"""Execute explicit, retry-safe scheduling handoffs in the existing worker."""
from datetime import datetime, timezone
from app.extensions import db
from app.models import (ChannelSchedule, ScheduleTransition, SelectionDecision,
                        TimedEventOccurrence, EventBlockExecution, LiveControlCommand, Clock)
from app.services.visual_schedule import resolve_visual, select_visual
from app.services.media_storage import LocalMediaStorage
from app.services.playout_queue import (_command, push_decision, socket_identity,
                                       queued_ids, active_ids, request_decision_id, remove_future)


def expire_transition(station, command):
    """Stop retrying an uncertain handoff without inventing an engine acknowledgement."""
    command.state='FAILED'
    command.completed_at=datetime.now(timezone.utc)
    if command.decision_id:
        # The engine may already have switched. Preserve playback history and stop
        # filling under the old mode until the operator explicitly reconciles it.
        station.automation.hold=True
        command.error='Switch acknowledgement timed out. Automation is held. Check playback in Station Control and confirm a mode to resume.'
        try:
            requests=[rid for rid in queued_ids(station.slug) if request_decision_id(station.slug,rid)==command.decision_id]
            if requests:remove_future(station.slug,requests)
        except (OSError,RuntimeError):
            pass
    else:
        command.error='Engine is unavailable or needs the scheduling update. Current mode retained.'
    db.session.commit()
    return False


def process_transition(station, reader):
    command=ScheduleTransition.query.filter_by(station_id=station.id).filter(
        ScheduleTransition.state.in_(('PENDING','PREPARING','FADING'))).order_by(ScheduleTransition.created_at).first()
    if not command:return False
    schedule=db.session.get(ChannelSchedule,station.id)
    created=command.created_at.replace(tzinfo=command.created_at.tzinfo or timezone.utc)
    expired=(datetime.now(timezone.utc)-created).total_seconds() > (30 if command.state=='PENDING' else 120)
    try:
        reader.collect(station.slug)
        if expired and command.state in ('PENDING','PREPARING'):
            return expire_transition(station,command)
        if command.state=='PENDING':
            _command(station.slug,'freo_schedule.status')  # Capability check before putting any target audio in the queue.
            if schedule.revision!=command.revision:
                raise ValueError('Schedule changed before the switch. Review and confirm again.')
            resolved=resolve_visual(station,mode=command.mode,simple=command.simple,activation=command.id)
            if resolved['source'] and resolved['source']['kind']=='legacy':
                from app.services.automation import select_next
                from app.services.schedule import Resolution
                clock=Clock.query.filter_by(id=resolved['source']['id'],station_id=station.id,enabled=True).first()
                target=Resolution(resolved['local_time'],None,clock,resolved['key'],resolved['next_transition'])
                decision=select_next(station.slug,programming_override=target,commit=False)
            else:
                decision=select_visual(station,resolved,LocalMediaStorage(),datetime.now(timezone.utc))
            if not decision:raise ValueError('Selected content and default playlist are unavailable. Current playback retained.')
            db.session.flush();command.decision_id=decision.id;command.state='PREPARING';db.session.commit()
        decision=command.decision
        if command.state=='PREPARING':
            # Recover an accepted push if a worker died before saving its request ID.
            if decision.liquidsoap_request_id is None:
                for request_id in queued_ids(station.slug)|active_ids(station.slug):
                    if request_decision_id(station.slug,request_id)==decision.id:
                        decision.liquidsoap_request_id=request_id;break
                if decision.liquidsoap_request_id is None:
                    decision.liquidsoap_request_id=push_decision(decision)
                decision.socket_identity=socket_identity(station.slug);decision.status='queued';db.session.commit()
            # Commit intent before mutation; token makes replay safe inside the engine.
            command.interrupted_ids=[identifier for request_id in active_ids(station.slug)|queued_ids(station.slug) if (identifier:=request_decision_id(station.slug,request_id)) and identifier!=decision.id]
            command.state='FADING';db.session.commit()
        if decision.socket_identity != socket_identity(station.slug):
            raise ValueError('Playback engine restarted during the switch. Review the active mode and confirm again.')
        if expired:
            # Never start a previously unsent switch after its deadline. Only
            # reconcile the engine's existing token and confirmed playback.
            response=_command(station.slug,'freo_schedule.status')
            if response!=f'APPLIED|{command.id}':return expire_transition(station,command)
            response='APPLIED'
        else:
            response=_command(station.slug,f'freo_schedule.switch {command.id} {decision.liquidsoap_request_id}')
        if response not in ('FADING','APPLIED'):raise RuntimeError('Engine did not acknowledge mode switch')
        if response=='APPLIED':
            reader.collect(station.slug)
            if decision.status!='started':
                return expire_transition(station,command) if expired else True
            schedule.mode=command.mode;schedule.simple=command.simple;schedule.live_simple=command.simple;schedule.activation=command.id
            schedule.activated=True;schedule.revision+=1
            command.state='APPLIED';command.completed_at=datetime.now(timezone.utc);command.error=None
            state=station.automation;state.enabled=True;state.hold=False;state.operator_mode='AUTO'
            # The explicit handoff interrupts active Events and sequences. Keep confirmed
            # starts as historical facts and record the interruption without fabricated completion.
            for row in TimedEventOccurrence.query.filter_by(station_id=station.id).filter(TimedEventOccurrence.state.in_(('QUEUED','STARTED'))):
                row.state='FAILED'
                row.failure_reason='interrupted_by_mode_change'
            for row in EventBlockExecution.query.filter_by(station_id=station.id).filter(EventBlockExecution.state.in_(('PENDING','QUEUED','STARTED'))):
                row.state='ABORTED';row.aborted_at=command.completed_at;row.failure_reason='mode_change'
                for item in row.items:
                    if item.state in ('PENDING','QUEUED'):item.state='SKIPPED';item.failure_reason='mode_change'
                    elif item.state=='STARTED':
                        item.state='FAILED';item.failed_at=command.completed_at;item.failure_reason='mode_change'
            for row in SelectionDecision.query.filter_by(station_id=station.id).filter(SelectionDecision.status.in_(('selected','submitting','queued')),SelectionDecision.id!=decision.id):
                row.status='failed';row.reason='mode_change'
            for row in LiveControlCommand.query.filter_by(station_id=station.id,status='pending'):
                row.status='failed';row.error_code='mode_change'
            db.session.commit();reader.starved_until.pop(station.slug,None)
        if expired and command.state!='APPLIED':return expire_transition(station,command)
        return True
    except ValueError as error:
        if command.state in ('PREPARING','FADING'):
            expire_transition(station,command)
            command.error=f'{str(error)[:90]} Automation is held; confirm a mode in Station Control.'
            db.session.commit()
            return False
        command.state='FAILED';command.error=str(error)[:200];db.session.commit();return False
    except (OSError,RuntimeError):
        # Preserve durable intent while the socket is temporarily down. No fake success.
        if expired:return expire_transition(station,command)
        command.error='Waiting for the playback engine to acknowledge the switch.'
        db.session.commit();return True
