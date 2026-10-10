"""The calendar edits programming definitions; it never controls an engine socket."""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from app.extensions import db
from app.models import Clock, MediaCategory, Rotation, ScheduleProgram
from app.routes.web import admin_stations, station_or_404
from app.services.admin_auth import admin_required, current_admin, require_csrf
from app.services.admin_media import audit
from app.services.calendar import calendar_days, create_program
from app.services.playlists import listing as playlist_listing
from app.services.schedule import resolve

admin_calendar = Blueprint('admin_calendar', __name__)


@admin_calendar.get('/admin/stations/<slug>/calendar')
@admin_required
def page(slug):
    from app.routes.schedule_studio import render_workspace
    return render_workspace(slug, 'calendar')


@admin_calendar.post('/admin/stations/<slug>/calendar/<action>')
@admin_required
def action(slug, action):
    require_csrf()
    station = station_or_404(slug, require_enabled=False)
    try:
        if action=='create':
            if request.form.get('program_id'):
                previous=ScheduleProgram.query.filter_by(station_id=station.id,id=request.form.get('program_id'),enabled=True).with_for_update().first()
                if not previous:
                    raise ValueError('This program was changed by another editor. Reload the calendar.')
                if previous.baseline_assignment_id:
                    raise ValueError('Restore the weekly baseline in Defaults before editing its times')
                previous.enabled=False
                db.session.flush()
            kind=request.form.get('kind','category')
            if kind not in ('category','clock','rotation','playlist'):
                raise ValueError('Choose a category, show, rotation, or playlist')
            rows=create_program(station,name=request.form.get('name'),weekdays=request.form.getlist('weekday'),
                start=request.form.get('start'),end=request.form.get('end'),on_date=request.form.get('on_date'),
                **{('playlist_id' if kind=='playlist' else kind+'_slug'):request.form.get(kind)})
            summary=f'Published {len(rows)} calendar program block(s)'
        elif action=='remove':
            row=ScheduleProgram.query.filter_by(station_id=station.id,id=request.form.get('id')).first()
            if not row:
                abort(404)
            if row.baseline_assignment_id:
                raise ValueError('Restore the weekly baseline in Defaults before removing its times')
            row.enabled=False
            summary=f'Removed future occurrences of {row.name}; current audio may finish'
        else:
            abort(404)
        audit('calendar_'+action,user_id=current_admin().id,station_id=station.id,target_type='station',target_id=station.slug,summary=summary)
        db.session.commit()
        flash(summary,'success')
    except (ValueError,TypeError) as error:
        db.session.rollback()
        flash(str(error) or 'Enter a valid program','error')
    return redirect(url_for('.page',slug=slug,date=request.form.get('return_date') or None))
