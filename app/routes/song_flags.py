"""Review flags belong to the listening station, including shared songs."""
from datetime import datetime, timezone
from flask import Blueprint, jsonify, request, abort
from app.extensions import db
from app.models import SongFlag, SelectionDecision
from app.routes.web import station_or_404
from app.services.admin_auth import admin_required, require_csrf, current_admin
from app.services.admin_media import audit
from app.services.availability import tracks_for

song_flags = Blueprint('song_flags', __name__)


def flag_data(flag):
    if not flag:
        return None
    return dict(note=flag.note,revision=flag.revision,resolved=flag.resolved_at is not None,
                created_at=flag.created_at.replace(tzinfo=flag.created_at.tzinfo or timezone.utc).isoformat(),
                updated_at=flag.updated_at.replace(tzinfo=flag.updated_at.tzinfo or timezone.utc).isoformat())


@song_flags.route('/admin/api/stations/<slug>/flags/<identifier>', methods=['GET','POST'])
@admin_required
def flag(slug, identifier):
    station = station_or_404(slug, require_enabled=False)
    if request.method == 'POST':
        require_csrf()
    track = tracks_for(station.id).filter_by(uuid=identifier,deleted_at=None).first()
    # A captured on-air song remains flaggable if availability changed while typing.
    decision = request.form.get('decision_id','')
    if not track and request.method == 'POST' and decision.isdecimal():
        row = SelectionDecision.query.filter_by(id=int(decision),station_id=station.id,status='started').first()
        if row and row.started_at and row.track and row.track.uuid == identifier and not row.track.deleted_at:
            track = row.track
    if not track:
        abort(404)
    row = SongFlag.query.filter_by(station_id=station.id,track_id=track.id).first()
    if request.method == 'GET':
        response=jsonify(flag=flag_data(row));response.headers['Cache-Control']='private, no-store';return response
    try:
        action = request.form.get('action','save')
        if action not in ('save','resolve','reopen'):
            raise ValueError('Unknown flag action')
        note = request.form.get('note','').strip()
        if len(note)>2000 or '\x00' in note:
            raise ValueError('Flag note must be at most 2000 characters')
        expected = request.form.get('revision','0')
        if not expected.isdecimal() or int(expected) != (row.revision if row else 0):
            raise ValueError('This flag changed in another window. Close and reopen it before editing.')
        if not row:
            if action != 'save':
                raise ValueError('Flag this song first')
            row = SongFlag(station_id=station.id,track_id=track.id,revision=0,admin_user_id=current_admin().id)
            db.session.add(row)
        row.note = note
        row.revision += 1
        row.updated_at = datetime.now(timezone.utc)
        if action == 'resolve':row.resolved_at = row.updated_at
        elif action == 'reopen':row.resolved_at = None
        audit('song_flag_'+action,user_id=current_admin().id,station_id=station.id,
              target_type='track',target_id=track.uuid,summary='Song review flag '+action)
        db.session.commit()
        return jsonify(ok=True,flag=flag_data(row))
    except ValueError as error:
        db.session.rollback()
        return jsonify(ok=False,message=str(error)),409
