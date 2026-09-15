"""Authenticated, CSRF-protected forms over the shared programming services."""
from app.services.availability import tracks_for
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo
from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from app.extensions import db
from app.models import Clock, EventBlock, MediaCategory, Rotation, ScheduleAssignment, ScheduleProgram, Track, ImagingAsset, ImagingGroup
from app.routes.web import admin_stations, station_or_404
from app.services.admin_auth import admin_required, current_admin, programming_mutation_required
from app.services.admin_media import audit
from app.services.admin_view import context as admin_context, DAY_NAMES
from app.services.automation import (activate, add_slot, category_create, category_for,
    move_rotation_slot, preview as rotation_preview, remove_rotation_slot,
    rotation_create, rotation_for, validate_rotation)
from app.services.clocks import (add_clock_slot, assign, clock_for, create_clock,
    current, move_clock_slot, preview_clock, remove_assignment, remove_clock_slot,
    set_timezone, update_assignment, validate_clock)
from app.services.programming import (category_usage, delete_category, assignment_for, candidate_warnings, clean_text, set_membership,
    set_resource_enabled, set_slot_enabled, update_resource)
from app.services.schedule import preview_transitions

admin_programming_blueprint = Blueprint('admin_programming', __name__)
KINDS = {'categories': 'category', 'rotations': 'rotation', 'clocks': 'clock'}


def page(station, section, **extra):
    from app.services.airplay import play_counts
    if section == 'categories':
        extra['play_counts'] = play_counts(station.id, 'category')
    return render_template('admin/programming.html', stations=admin_stations(), selected=station,
        page=section, section=section, kind=KINDS.get(section), data=admin_context(station, with_status=False), **extra)


def back(station, section, resource=None):
    if resource:
        return url_for('admin_programming.detail', slug=station.slug, section=section, resource=resource)
    return url_for('admin_programming.list_page', slug=station.slug, section=section)


def recorded(station, action, kind, resource, summary):
    audit(action, user_id=current_admin().id, station_id=station.id,
          target_type=kind, target_id=str(resource), summary=summary)
    db.session.commit()


def response(station, section, action, callback, *, resource=None, kind=None):
    try:
        event = audit(action, user_id=current_admin().id, station_id=station.id,
                      target_type=kind or section.rstrip('s'), target_id=resource,
                      summary='Programming change')
        target, summary = callback()
        event.target_id = str(target)
        event.summary = summary[:240]
        db.session.commit()
        flash(summary, 'success')
    except ValueError as error:
        db.session.rollback()
        flash(str(error), 'error')
    return redirect(back(station, section, resource), code=303)


def positive(value):
    try:
        n = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError('Use a valid positive position') from error
    if not 1 <= n <= 1000:
        raise ValueError('Use a valid positive position')
    return n


def weekday(value):
    try:
        day = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError('Choose a weekday') from error
    if not 0 <= day <= 6:
        raise ValueError('Choose a weekday')
    return day


@admin_programming_blueprint.get('/admin/stations/<slug>/<section>')
@admin_required
def list_page(slug, section):
    if section not in (*KINDS, 'schedule'):
        abort(404)
    station = station_or_404(slug, require_enabled=False)
    if section == 'categories':
        return page(station, section, rows=MediaCategory.query.filter_by(station_id=station.id).order_by(MediaCategory.name).all())
    if section == 'rotations':
        return page(station, section, rows=Rotation.query.filter_by(station_id=station.id).order_by(Rotation.name).all())
    if section == 'clocks':
        return page(station, section, rows=Clock.query.filter_by(station_id=station.id).order_by(Clock.name).all())
    rows = ScheduleAssignment.query.filter_by(station_id=station.id).order_by(ScheduleAssignment.weekday, ScheduleAssignment.start_time).all()
    clocks = Clock.query.filter_by(station_id=station.id, enabled=True).order_by(Clock.name).all()
    preview = None
    preview_error = None
    if request.args.get('date'):
        try:
            date = datetime.strptime(request.args['date'], '%Y-%m-%d').date()
            hours = int(request.args.get('hours', '24'))
            start = datetime.combine(date, time.min, ZoneInfo(station.timezone)).astimezone(timezone.utc)
            preview = preview_transitions(station, start, hours)
        except (ValueError, OverflowError) as error:
            preview_error = str(error)
    from app.services.planning import baseline_conversion
    try:
        conversion, conversion_token = baseline_conversion(station)
        conversion_error = None
    except ValueError as error:
        conversion, conversion_token, conversion_error = [], None, str(error)
    return page(station, section, rows=rows, clocks=clocks, days=DAY_NAMES,
                conversion=conversion, conversion_token=conversion_token, conversion_error=conversion_error,
                converted=ScheduleProgram.query.filter(ScheduleProgram.station_id == station.id,ScheduleProgram.baseline_assignment_id.isnot(None),ScheduleProgram.enabled.is_(True)).count(),
                programming=current(slug), preview=preview, preview_error=preview_error,
                default_categories=MediaCategory.query.filter_by(station_id=station.id,enabled=True).order_by(MediaCategory.name).all(),
                default_rotations=Rotation.query.filter_by(station_id=station.id,enabled=True).order_by(Rotation.name).all())


@admin_programming_blueprint.get('/admin/stations/<slug>/<section>/<resource>')
@admin_required
def detail(slug, section, resource):
    if section not in KINDS:
        abort(404)
    station = station_or_404(slug, require_enabled=False)
    try:
        item = {'categories': category_for, 'rotations': rotation_for, 'clocks': clock_for}[section](slug, resource)
    except ValueError:
        abort(404)
    extra = {}
    if section == 'categories':
        search = request.args.get('q', '').strip()[:80]
        query = tracks_for(station.id).filter_by(ingest_status='accepted')
        if search:
            pattern = '%' + search.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
            query = query.filter(Track.title.ilike(pattern, escape='\\') | Track.artist.ilike(pattern, escape='\\'))
        extra['tracks'] = query.order_by(Track.title, Track.id).limit(100).all()
    else:
        extra['categories'] = MediaCategory.query.filter_by(station_id=station.id).order_by(MediaCategory.name).all()
        extra['rotations'] = Rotation.query.filter_by(station_id=station.id).order_by(Rotation.name).all()
        extra['imaging_assets'] = ImagingAsset.query.filter_by(station_id=station.id, enabled=True, ingest_status='accepted').order_by(ImagingAsset.name).all()
        extra['imaging_groups'] = ImagingGroup.query.filter_by(station_id=station.id, enabled=True).order_by(ImagingGroup.name).all()
        extra['event_blocks'] = EventBlock.query.filter_by(station_id=station.id, enabled=True).order_by(EventBlock.name).all()
        try:
            extra['validation'] = ('Valid: %d enabled slots' % len(validate_rotation(item) if section == 'rotations' else validate_clock(item)))
        except ValueError as error:
            extra['validation'] = str(error)
        extra['warnings'] = candidate_warnings(item)
        if request.args.get('preview') in ('10', '20', '50'):
            try:
                extra['preview'] = (rotation_preview(slug, int(request.args['preview']), rotation_slug=resource) if section == 'rotations'
                                    else preview_clock(slug, resource, int(request.args['preview'])))
            except ValueError as error:
                extra['preview_error'] = str(error)
    if section == 'categories':
        parts, clock_parts = category_usage(item)
        extra['usage_names'] = sorted({slot.rotation.name for slot in parts} | {slot.clock.name for slot in clock_parts})
        extra['replacement_categories'] = MediaCategory.query.filter(MediaCategory.station_id == station.id, MediaCategory.id != item.id, MediaCategory.enabled.is_(True)).order_by(MediaCategory.name).all()
    return page(station, section, item=item, **extra)


@admin_programming_blueprint.post('/admin/stations/<slug>/<section>/create')
@programming_mutation_required
def create(slug, section):
    if section not in KINDS:
        abort(404)
    station = station_or_404(slug, require_enabled=False)
    def action():
        name = clean_text(request.form.get('name'), 120, True)
        code = request.form.get('slug', '').strip()
        obj = {'categories': category_create, 'rotations': rotation_create, 'clocks': create_clock}[section](slug, name, code)
        return obj.slug, f'{KINDS[section].title()} {obj.name} created'
    return response(station, section, KINDS[section] + '_created', action)


@admin_programming_blueprint.post('/admin/stations/<slug>/<section>/<resource>/<operation>')
@programming_mutation_required
def resource_action(slug, section, resource, operation):
    if section not in KINDS:
        abort(404)
    station = station_or_404(slug, require_enabled=False)
    kind = KINDS[section]
    if section == 'categories' and operation == 'delete':
        try:
            name = delete_category(slug, resource, request.form.get('replacement'))
            recorded(station, 'category_deleted', 'category', resource, f'Category {name} deleted; songs retained')
            flash(f'{name} deleted. All songs were kept.', 'success')
        except ValueError as error:
            db.session.rollback()
            flash(str(error), 'error')
            return redirect(back(station, section, resource))
        return redirect(back(station, section))
    if operation == 'edit':
        def action():
            obj = update_resource(slug, kind, resource, name=request.form.get('name'), description=request.form.get('description'))
            return obj.slug, f'{kind.title()} {obj.name} updated'
        return response(station, section, kind + '_updated', action, resource=resource)
    if operation in ('enable', 'disable'):
        def action():
            obj = set_resource_enabled(slug, kind, resource, operation == 'enable')
            return obj.slug, f'{kind.title()} {obj.name} {operation}d'
        return response(station, section, kind + '_' + operation + 'd', action, resource=resource)
    if section == 'categories' and operation in ('assign', 'remove'):
        def action():
            tracks = set_membership(slug, resource, request.form.getlist('track_uuid'), operation == 'assign')
            return resource, f'{len(tracks)} track(s) {"assigned to" if operation == "assign" else "removed from"} {resource}'
        return response(station, section, 'track_category_' + ('assigned' if operation == 'assign' else 'removed'), action, resource=resource, kind='category')
    if section == 'rotations' and operation == 'activate':
        if request.form.get('confirm') != resource:
            abort(400)
        def action():
            activate(slug, resource)
            return resource, f'Rotation {resource} activated as station fallback'
        return response(station, section, 'rotation_activated', action, resource=resource)
    abort(404)


@admin_programming_blueprint.post('/admin/stations/<slug>/<section>/<resource>/slots/<operation>')
@programming_mutation_required
def slot_action(slug, section, resource, operation):
    if section not in ('rotations', 'clocks'):
        abort(404)
    station = station_or_404(slug, require_enabled=False)
    kind = KINDS[section]
    def action():
        if operation == 'add':
            if section == 'rotations':
                slot = add_slot(slug, resource, request.form.get('category', ''))
            else:
                slot_type = request.form.get('slot_type', '')
                if slot_type not in ('CATEGORY', 'ROTATION', 'CART', 'IMAGING_GROUP', 'EVENT_BLOCK'):
                    raise ValueError('Unsupported clock slot type')
                slot = add_clock_slot(slug, resource, slot_type, request.form.get('target', ''))
            return resource, f'Slot {slot.position} added to {resource}'
        position = positive(request.form.get('position'))
        if operation == 'move':
            to = positive(request.form.get('to'))
            (move_rotation_slot if section == 'rotations' else move_clock_slot)(slug, resource, position, to)
            return resource, f'Slot {position} moved to {to} in {resource}'
        if operation == 'remove':
            (remove_rotation_slot if section == 'rotations' else remove_clock_slot)(slug, resource, position)
            return resource, f'Slot {position} removed from {resource}'
        if operation in ('enable', 'disable'):
            set_slot_enabled(slug, kind, resource, position, operation == 'enable')
            return resource, f'Slot {position} {operation}d in {resource}'
        abort(404)
    suffix = {'add': 'added', 'move': 'reordered', 'remove': 'removed', 'enable': 'enabled', 'disable': 'disabled'}.get(operation)
    if suffix is None:
        abort(404)
    return response(station, section, f'{kind}_slot_{suffix}', action, resource=resource)


@admin_programming_blueprint.post('/admin/stations/<slug>/schedule/<operation>')
@programming_mutation_required
def schedule_action(slug, operation):
    station = station_or_404(slug, require_enabled=False)
    def action():
        if operation == 'convert':
            from app.services.planning import convert_baseline
            count = convert_baseline(station, request.form.get('conversion_token'))
            return slug, f'Converted baseline into {count} calendar blocks; clock progress preserved'
        if operation == 'restore':
            from app.services.planning import restore_baseline
            count = restore_baseline(station)
            return slug, f'Restored weekly assignments from {count} baseline blocks'
        if operation == 'default':
            from app.services.planning import set_station_default
            clock = set_station_default(station, request.form.get('choice'))
            return clock.slug, f'Station default set to {clock.name}'
        if operation == 'timezone':
            if request.form.get('confirm') != station.timezone:
                raise ValueError('Confirm the current timezone before changing it')
            old = station.timezone
            new = set_timezone(slug, request.form.get('timezone', ''))
            return slug, f'Station timezone changed from {old} to {new.timezone}'
        if operation in ('create', 'edit'):
            day = weekday(request.form.get('weekday'))
            at = request.form.get('time', '')
            clock_slug = request.form.get('clock', '')
            if operation == 'create':
                row = assign(slug, day, at, clock_slug)
            else:
                row = update_assignment(slug, positive(request.form.get('assignment_id')), day, at, clock_slug)
            return row.id, f'{DAY_NAMES[row.weekday]} {row.start_time:%H:%M} assigned to {row.clock.name}'
        if operation == 'remove':
            row = assignment_for(slug, positive(request.form.get('assignment_id')))
            if request.form.get('confirm') != str(row.id):
                raise ValueError('Confirm the assignment before removing it')
            summary = f'{DAY_NAMES[row.weekday]} {row.start_time:%H:%M} assignment removed'
            remove_assignment(slug, row.id)
            return row.id, summary
        abort(404)
    actions = {'convert': 'baseline_converted', 'restore': 'baseline_restored', 'default': 'station_default_changed', 'timezone': 'station_timezone_changed', 'create': 'schedule_assignment_created',
               'edit': 'schedule_assignment_updated', 'remove': 'schedule_assignment_removed'}
    if operation not in actions:
        abort(404)
    return response(station, 'schedule', actions[operation], action, kind='schedule_assignment')


@admin_programming_blueprint.get('/admin/stations/<slug>/tags')
@admin_required
def tags(slug):
    from app.models import MusicTag
    station = station_or_404(slug, require_enabled=False)
    return render_template('admin/tags.html', selected=station, stations=admin_stations(), page='tags',
                           tags=MusicTag.query.filter_by(station_id=station.id).order_by(MusicTag.name).all())
