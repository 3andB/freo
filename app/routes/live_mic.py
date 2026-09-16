"""Same-origin authenticated signaling. Audio uses encrypted WebRTC directly."""
import json
import os
from flask import Blueprint, jsonify, request
from app.routes.admin_live import station_for_operator
from app.services.admin_auth import admin_required, current_admin, require_csrf
from app.services.live_mic import gateway
from app.services.admin_media import audit
from app.extensions import db

live_mic = Blueprint('live_mic', __name__)


@live_mic.post('/admin/api/stations/<slug>/live-mic/<action>')
@admin_required
def control(slug, action):
    require_csrf()
    station = station_for_operator(slug)
    if not station.enabled or station.desired_state != 'running':
        return jsonify(message='Station is not running'), 409
    if action not in ('status', 'offer', 'heartbeat', 'go', 'end', 'disconnect', 'config'):
        return jsonify(message='Unknown microphone action'), 404
    if action == 'config':
        return jsonify(iceServers=json.loads(os.environ.get('FREO_MIC_BROWSER_ICE_SERVERS', '[]')))
    try:
        data = dict(owner=current_admin().id, token=request.form.get('token', ''))
        if action == 'offer':
            sdp = request.form.get('sdp', '')
            if not sdp or len(sdp) > 65536:
                raise ValueError('Invalid microphone offer')
            data['sdp'] = sdp
        if action == 'go':
            from app.models import LiveControlCommand
            if LiveControlCommand.query.filter_by(station_id=station.id, status='pending').first():
                raise ValueError('Wait for the pending broadcast command before going live.')
        if action in ('go', 'end'):
            data['fade'] = request.form.get('fade', '3')
        result = gateway(slug, action, timeout=20 if action == 'offer' else 2, **data)
        if action != 'offer':
            result.pop('token', None)
            result['owned'] = result.pop('owner', None) == current_admin().id
            result.get('engine', {}).pop('token', None)
        if action in ('go', 'end', 'disconnect'):
            audit('live_mic_' + action, user_id=current_admin().id, station_id=station.id,
                  target_type='station', target_id=slug, summary='Live microphone: ' + action)
            db.session.commit()
        return jsonify(result)
    except ValueError as error:
        return jsonify(message=str(error)), 409
