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
        tracks=_tracks(station), imaging=_imaging(station), blocks=_blocks(station), modes=MODES, recurrences=RECURRENCES,
        missed=MISSED, interrupts=INTERRUPTS))


def _save(station, row=None):
    return save_event(station.slug, identifier=row.uuid if row else None,
        name=request.form.get('name'), description=request.form.get('description'),
        timing_mode=request.form.get('timing_mode'), recurrence_type=request.form.get('recurrence_type'),
        content_type=request.form.get('content_type'), content_identifier=request.form.get('content_identifier'),
        local_date=request.form.get('local_date'), local_time=request.form.get('local_time'), weekday=request.form.get('weekday'),
        weekdays=request.form.getlist('weekdays') if 'repeat_days_present' in request.form else None,
        early_tolerance_seconds=request.form.get('early_tolerance_seconds'), late_tolerance_seconds=request.form.get('late_tolerance_seconds'),
        missed_policy=request.form.get('missed_policy'), interrupt_policy=request.form.get('interrupt_policy'), priority=request.form.get('priority'))


def _tracks(station): return tracks_for(station.id).filter_by(enabled=True, ingest_status='accepted', decommissioned_at=None).order_by(Track.title).all()
def _imaging(station): return ImagingAsset.query.filter_by(station_id=station.id, enabled=True, ingest_status='accepted', decommissioned_at=None).order_by(ImagingAsset.name).all()
def _blocks(station): return EventBlock.query.filter_by(station_id=station.id, enabled=True).order_by(EventBlock.name).all()


@admin_events_blueprint.get('/admin/stations/<slug>/events/<identifier>')
@admin_required
def detail(slug, identifier):
    station = operator_station(slug)
    try: row = event_for(slug, identifier)
    except ValueError: abort(404)
    occurrences = TimedEventOccurrence.query.filter_by(timed_event_id=row.id).order_by(TimedEventOccurrence.scheduled_for_utc.desc()).limit(50).all()
    event_local = row.scheduled_at_utc.replace(tzinfo=row.scheduled_at_utc.tzinfo or timezone.utc).astimezone(ZoneInfo(station.timezone)) if row.scheduled_at_utc else None
    return render_template('admin/event_detail.html', **context(station, event=row, occurrences=occurrences,
        event_local=event_local,
        commercial_log=commercial_log(row), warnings=conflict_warnings(row), tracks=_tracks(station), imaging=_imaging(station), blocks=_blocks(station), modes=MODES,
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
    return redirect(url_for('.detail', slug=slug, identifier=identifier), code=303)
