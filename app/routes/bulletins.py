"""A small editor over ordinary timed events and their occurrence history."""
from flask import Blueprint, request, render_template, redirect, url_for, flash, abort
from app.extensions import db
from app.models import TimedEvent
from app.routes.admin_events import operator_station
from app.routes.web import admin_stations
from app.services.admin_auth import admin_required, require_csrf, current_admin
from app.services.admin_media import audit
from app.services.availability import tracks_for
from app.services.timed_events import save_event, event_for

bulletins = Blueprint('bulletins',__name__)


@bulletins.route('/admin/stations/<slug>/external-bulletins',methods=['GET','POST'])
@bulletins.route('/admin/stations/<slug>/external-bulletins/<identifier>',methods=['GET','POST'])
@admin_required
def page(slug,identifier=None):
    station = operator_station(slug)
    try: row = event_for(slug,identifier) if identifier else None
    except ValueError: abort(404)
    if row and row.content_type != 'BULLETIN':abort(404)
    if request.method=='POST':
        require_csrf()
        try:
            row = save_event(slug,identifier=identifier,name=request.form.get('name'),
                recurrence_type=request.form.get('recurrence_type','HOURLY'),local_time=request.form.get('local_time','00:00'),
                local_date=request.form.get('local_date'),weekday=request.form.get('weekday',0) if request.form.get('recurrence_type')=='WEEKLY' else None,
                timing_mode=request.form.get('timing_mode','SOFT'),
                interrupt_policy='MUSIC_ONLY' if request.form.get('timing_mode')=='HARD' else 'NEVER',
                content_type='BULLETIN',content_identifier='',revision=request.form.get('revision') if row else None,
                late_tolerance_seconds=300,bulletin={key:request.form.get(key) for key in ('url','kind','duration','intro','outro')})
            audit('bulletin_saved',user_id=current_admin().id,station_id=station.id,target_type='timed_event',target_id=row.uuid,summary='External Bulletin saved')
            db.session.commit()
            return redirect(url_for('admin_events.detail',slug=slug,identifier=row.uuid),code=303)
        except ValueError as error:
            db.session.rollback();flash(str(error),'error')
    return render_template('admin/bulletins.html',selected=station,stations=admin_stations(),page='events',event=row,
        bulletins=TimedEvent.query.filter_by(station_id=station.id,content_type='BULLETIN').order_by(TimedEvent.name).all(),
        audio=tracks_for(station.id).filter_by(audio_kind='STATION',enabled=True,ingest_status='accepted',decommissioned_at=None).order_by('title').all())
