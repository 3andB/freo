"""Authenticated station-scoped timed-event management."""
from datetime import timezone
from zoneinfo import ZoneInfo

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from app.extensions import db
from app.models import TimedEvent, TimedEventOccurrence
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


def event_local_time(values):
    minute = values.get('hourly_minute', '')
    if values.get('recurrence_type') == 'HOURLY' and minute != '':
        if not minute.isdigit() or not 0 <= int(minute) <= 59:
            raise ValueError('Choose a minute from 00 to 59')
        return f'00:{int(minute):02d}:00'
    return values.get('local_time')


def _save(station, row=None):
    return save_event(station.slug, identifier=row.uuid if row else None,
        name=request.form.get('name'), description=request.form.get('description'),
        timing_mode='SOFT' if not row or request.form.get('use_soft') else row.timing_mode, recurrence_type=request.form.get('recurrence_type'),
        content_type=request.form.get('content_type'), content_identifier=request.form.get('content_identifier'),
        local_date=request.form.get('local_date'), local_time=event_local_time(request.form), weekday=request.form.get('weekday'),
        weekdays=request.form.getlist('weekdays') if 'repeat_days_present' in request.form else None,
        early_tolerance_seconds=0, late_tolerance_seconds=request.form.get('late_tolerance_seconds',300),
        missed_policy=request.form.get('missed_policy','SKIP'), interrupt_policy='NEVER' if not row or request.form.get('use_soft') else row.interrupt_policy, priority=request.form.get('priority',100),
        repeat_hours=request.form.getlist('repeat_hours') if request.form.get('hourly') or request.form.get('recurrence_type') in ('HOURLY','QUARTER_HOUR') else None,
        starts_on=request.form.get('starts_on'), ends_on=request.form.get('ends_on'),
        interrupt_dj=request.form.get('interrupt_dj','no')=='yes',playlist_playback=request.form.get('playlist_playback'),
        month_day=request.form.get('month_day'),month_nth=request.form.get('month_nth'),month_weekday=request.form.get('month_weekday'),revision=request.form.get('revision'))


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
    from app.services.timed_events import recurrence_rule, next_instants, recurrence_summary
    station=operator_station(slug)
    try:
        rule = recurrence_rule(station, request.args.get('recurrence_type','ONE_TIME'),
            local_time=event_local_time(request.args), local_date=request.args.get('local_date'),
            weekdays=request.args.getlist('weekdays') if 'repeat_days_present' in request.args or 'weekdays' in request.args else None,
            repeat_hours=request.args.getlist('repeat_hours') if request.args.get('hourly') or request.args.get('recurrence_type') in ('HOURLY','QUARTER_HOUR') else None,
            starts_on=request.args.get('starts_on'), ends_on=request.args.get('ends_on'),
            month_day=request.args.get('month_day'), month_nth=request.args.get('month_nth'),
            month_weekday=request.args.get('month_weekday'))
        values=next_instants(rule)
        note = '' if len(values)==10 else 'No future runs.' if not values else 'No more runs after these dates.'
        return jsonify(summary=recurrence_summary(rule)+' · '+station.timezone, note=note,
            times=[t.astimezone(ZoneInfo(station.timezone)).strftime('%a %d %b %Y %H:%M:%S %Z (%z)') for t in values])
    except (ValueError,TypeError,OverflowError) as error:return jsonify(error=str(error)),400



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
