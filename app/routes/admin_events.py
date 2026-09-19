"""Authenticated station-scoped timed-event management."""
from app.services.availability import tracks_for
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from app.extensions import db
from app.models import EventBlock, ImagingAsset, TimedEvent, TimedEventOccurrence, Track
from app.routes.web import admin_stations, station_or_404
from app.services.admin_auth import admin_required, can_manage_events, current_admin, require_csrf
from app.services.admin_media import audit
from app.services.timed_events import (INTERRUPTS, MISSED, MODES, RECURRENCES,
    commercial_log, conflict_warnings, event_for, save_event, set_enabled, upcoming)

admin_events_blueprint = Blueprint('admin_events', __name__)


def operator_station(slug):
    station = station_or_404(slug, require_enabled=False)
    if not can_manage_events(current_admin(), station): abort(403)
    return station


def context(station, **extra):
    return dict(stations=admin_stations(), selected=station, page='events', **extra)


@admin_events_blueprint.get('/admin/stations/<slug>/events')
@admin_required
def list_page(slug):
    station = operator_station(slug)
    rows = TimedEvent.query.filter_by(station_id=station.id).order_by(TimedEvent.enabled.desc(), TimedEvent.name).all()
    return render_template('admin/events.html', **context(station, events=rows, upcoming=upcoming(station, limit=20)))


@admin_events_blueprint.route('/admin/stations/<slug>/events/create', methods=['GET','POST'])
@admin_required
def create(slug):
    station = operator_station(slug)
    if request.method == 'POST':
        require_csrf()
        try:
            row = _save(station)
            audit('timed_event_created', user_id=current_admin().id, station_id=station.id,
                  target_type='timed_event', target_id=row.uuid, summary=f'Created {row.timing_mode} event {row.name}')
            db.session.commit(); flash('Timed event created.', 'success')
            return redirect(url_for('.detail', slug=slug, identifier=row.uuid), code=303)
        except ValueError as error:
            db.session.rollback(); flash(str(error), 'error')
    return render_template('admin/event_form.html', **context(station, event=None,
        tracks=[], imaging=[], blocks=[], modes=MODES, recurrences=RECURRENCES,
        missed=MISSED, interrupts=INTERRUPTS))


def _save(station, row=None):
    return save_event(station.slug, identifier=row.uuid if row else None,
        name=request.form.get('name'), description=request.form.get('description'),
        timing_mode='SOFT' if request.form.get('use_soft') else request.form.get('timing_mode','SOFT'), recurrence_type=request.form.get('recurrence_type'),
        content_type=request.form.get('content_type'), content_identifier=request.form.get('content_identifier'),
        local_date=request.form.get('local_date'), local_time=request.form.get('local_time'), weekday=request.form.get('weekday'),
        weekdays=request.form.getlist('weekdays') if 'repeat_days_present' in request.form else None,
        early_tolerance_seconds=request.form.get('early_tolerance_seconds',0), late_tolerance_seconds=request.form.get('late_tolerance_seconds',300),
        missed_policy=request.form.get('missed_policy','SKIP'), interrupt_policy='NEVER' if request.form.get('use_soft') else request.form.get('interrupt_policy','NEVER'), priority=request.form.get('priority',100),
        repeat_hours=request.form.getlist('repeat_hours') if request.form.get('hourly') or request.form.get('recurrence_type') in ('HOURLY','QUARTER_HOUR') else None,
        starts_on=request.form.get('starts_on'), ends_on=request.form.get('ends_on'),
        interrupt_dj=request.form.get('interrupt_dj','no')=='yes',playlist_playback=request.form.get('playlist_playback'),
        month_day=request.form.get('month_day'),month_nth=request.form.get('month_nth'),month_weekday=request.form.get('month_weekday'),revision=request.form.get('revision'))


def _tracks(station): return tracks_for(station.id).filter_by(enabled=True, ingest_status='accepted', decommissioned_at=None).order_by(Track.title).all()
def _imaging(station): return ImagingAsset.query.filter_by(station_id=station.id, enabled=True, ingest_status='accepted', decommissioned_at=None).order_by(ImagingAsset.name).all()
def _blocks(station): return EventBlock.query.filter_by(station_id=station.id, enabled=True).order_by(EventBlock.name).all()


@admin_events_blueprint.get('/admin/stations/<slug>/events/<identifier>')
@admin_required
def detail(slug, identifier):
    station = operator_station(slug)
    try: row = event_for(slug, identifier)
    except ValueError: abort(404)
    from app.services.timed_events import _integer
    try:page=_integer(request.args.get('page',1),1,100000,'Page')
    except ValueError:abort(400)
    view=request.args.get('view','upcoming')
    if view not in ('upcoming','history'):abort(400)
    query=TimedEventOccurrence.query.filter_by(timed_event_id=row.id)
    active=TimedEventOccurrence.state.in_(('PENDING','READY','QUEUED','STARTED'))
    query=query.filter(active if view=='upcoming' else ~active).order_by(TimedEventOccurrence.scheduled_for_utc if view=='upcoming' else TimedEventOccurrence.scheduled_for_utc.desc(),TimedEventOccurrence.id)
    occurrences=query.offset((page-1)*50).limit(51).all()
    event_local = row.scheduled_at_utc.replace(tzinfo=row.scheduled_at_utc.tzinfo or timezone.utc).astimezone(ZoneInfo(station.timezone)) if row.scheduled_at_utc else None
    return render_template('admin/event_detail.html', **context(station, event=row, occurrences=occurrences[:50],occurrence_view=view,occurrence_page=page,occurrence_more=len(occurrences)>50,
        event_local=event_local,
        commercial_log=commercial_log(row), warnings=conflict_warnings(row), tracks=[], imaging=[], blocks=[], modes=MODES,
        recurrences=RECURRENCES, missed=MISSED, interrupts=INTERRUPTS))


@admin_events_blueprint.post('/admin/stations/<slug>/events/<identifier>/<operation>')
@admin_required
def mutate(slug, identifier, operation):
    station = operator_station(slug); require_csrf()
    try: row = event_for(slug, identifier)
    except ValueError: abort(404)
    try:
        if operation == 'edit':
            row = _save(station, row); action='timed_event_updated'; message='Timed event updated.'
        elif operation in ('enable','disable'):
            set_enabled(row, operation == 'enable'); action=f'timed_event_{operation}d'; message=f'Timed event {operation}d.'
        else: abort(404)
        audit(action, user_id=current_admin().id, station_id=station.id, target_type='timed_event', target_id=row.uuid, summary=message)
        db.session.commit(); flash(message, 'success')
    except ValueError as error:
        db.session.rollback(); flash(str(error), 'error')
        if operation == 'edit': return detail(slug,identifier)
    return redirect(url_for('.detail', slug=slug, identifier=identifier), code=303)


@admin_events_blueprint.get('/admin/stations/<slug>/events/audio')
@admin_required
def audio_search(slug):
    from flask import jsonify
    from app.services.event_search import search
    station=operator_station(slug)
    try:return jsonify(search(station,request.args.get('q',''),request.args.get('kind','ALL'),request.args.get('page',1),request.args.get('playlist')))
    except ValueError as error:return jsonify(error=str(error)),400


@admin_events_blueprint.get('/admin/stations/<slug>/events/preview')
@admin_required
def preview(slug):
    from flask import jsonify
    from datetime import timedelta
    from types import SimpleNamespace
    from app.services.timed_events import _date, _integer, _instants, parse_event_time, recurrence_summary
    from app.services.schedule import _wall_to_utc
    station=operator_station(slug)
    try:
        kind=request.args.get('recurrence_type','ONE_TIME')
        if kind not in RECURRENCES:raise ValueError('Choose a recurrence')
        local_day=_date(request.args.get('local_date'))
        at=parse_event_time(request.args.get('local_time'))
        days=[_integer(v,0,6,'Weekday') for v in request.args.getlist('weekdays')]
        if kind in ('WEEKLY','HOURLY','QUARTER_HOUR') and not days:raise ValueError('Choose repeat days')
        hours=[_integer(v,0,23,'Hour') for v in request.args.getlist('repeat_hours')] if request.args.get('hourly') or kind in ('HOURLY','QUARTER_HOUR') else None
        if hours==[]:raise ValueError('Choose repeat hours')
        first,last=_date(request.args.get('starts_on')),_date(request.args.get('ends_on'))
        if first and last and last<first:raise ValueError('End date is before start date')
        if kind=='ONE_TIME' and not local_day:raise ValueError('Choose a date')
        event=SimpleNamespace(station=station,recurrence_type=kind,local_time=at,starts_on=first,ends_on=last,repeat_days=days,repeat_hours=hours,
            month_day=_integer(request.args.get('month_day',1),1,31,'Day of month'),month_nth=_integer(request.args.get('month_nth',0),-2,5,'Week of month'),month_weekday=_integer(request.args.get('month_weekday',0),0,6,'Weekday'))
        event.scheduled_at_utc=_wall_to_utc(datetime.combine(local_day,at),ZoneInfo(station.timezone)) if kind=='ONE_TIME' else None
        now=datetime.now(timezone.utc)
        if first:now=max(now,_wall_to_utc(datetime.combine(first,datetime.min.time()),ZoneInfo(station.timezone)))
        values=[t for t in _instants(event,now,now+timedelta(days=370)) if t>=now][:10]
        return jsonify(summary=recurrence_summary(event)+' · '+station.timezone,times=[t.astimezone(ZoneInfo(station.timezone)).strftime('%a %d %b %Y %H:%M:%S %Z (%z)') for t in values])
    except (ValueError,TypeError) as error:return jsonify(error=str(error)),400


@admin_events_blueprint.post('/admin/stations/<slug>/events/<identifier>/occurrences/<int:occurrence_id>/cancel')
@admin_required
def cancel(slug,identifier,occurrence_id):
    from app.services.timed_events import cancel_occurrence
    station=operator_station(slug);require_csrf()
    try:event=event_for(slug,identifier)
    except ValueError:abort(404)
    if commercial_log(event):abort(409)
    row=TimedEventOccurrence.query.filter_by(id=occurrence_id,timed_event_id=event.id,station_id=station.id).first_or_404()
    cancel_occurrence(row,user=True)
    audit('event_occurrence_cancelled',user_id=current_admin().id,station_id=station.id,target_type='timed_event',target_id=event.uuid,summary='Occurrence cancelled')
    db.session.commit()
    return redirect(url_for('.detail',slug=slug,identifier=identifier),code=303)
