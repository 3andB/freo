"""Station-scoped production UI and installation-only provider configuration."""
import json
from io import BytesIO
from flask import Blueprint, abort, jsonify, render_template, request, send_file, url_for
from app.extensions import db
from app import models as m
from app.routes.web import admin_stations
from app.routes.admin_live import station_for_operator
from app.routes.distribution import installation_admin_required
from app.services.admin_auth import admin_required, current_admin, require_csrf, csrf_token
from app.services import production as service, production_audio as audio, production_providers as providers
from app.services.admin_media import audit

production = Blueprint('production',__name__)


@production.after_request
def private(response):
    response.headers['Cache-Control'] = 'private, no-store'
    return response


@production.errorhandler(ValueError)
def invalid(error):
    db.session.rollback()
    return jsonify(error=str(error)),400


@production.errorhandler(PermissionError)
def denied(error):
    db.session.rollback()
    return jsonify(error='Audio production access is not permitted.'),403


def payload():
    try:
        value = json.loads(request.form.get('data','{}'))
        if not isinstance(value,dict):raise ValueError()
        return value
    except (ValueError,TypeError):
        raise ValueError('Invalid production form.') from None


def owned(slug,identifier,lock=False):
    station = station_for_operator(slug)
    query = m.ProductionDraft.query.filter_by(id=identifier,station_id=station.id)
    row = (query.with_for_update() if lock else query).first_or_404()
    service.authorize(row,current_admin(),allow_admin_review=True)
    return row


def describe(row):
    track = row.track
    from app.services.availability import playable
    attempts = m.ProductionAttempt.query.filter_by(draft_id=row.id).order_by(m.ProductionAttempt.created_at.desc()).limit(30).all()
    components = {name:url_for('.preview',slug=row.station.slug,identifier=row.id,component=name) + '?v=' + str(row.revision)
                  for name in ('voice','bed','fx','render') if row.components.get(name)}
    designs = [dict(id=x['id'],url=url_for('.preview',slug=row.station.slug,identifier=row.id,component='design-'+str(i)))
               for i,x in enumerate(row.components.get('design',[]))]
    return dict(id=row.id,title=row.title,mode=row.mode,subtype=row.subtype,revision=row.revision,state=row.state,error=row.error,
        spec=row.spec,components=components,designs=designs,track_id=row.track_id,playable=playable(track,row.station_id),
        track_url=url_for('admin_media.track_detail',slug=row.station.slug,track_uuid=track.uuid) if track and current_admin().role=='ADMIN' else None,
        busy=any(a.status in ('pending','running') for a in attempts),
        attempts=[dict(id=a.id,action=a.action,status=a.status,error=a.error,created_at=a.created_at.isoformat(),
                       usage=a.usage if current_admin().role=='ADMIN' else None) for a in attempts])


@production.get('/admin/stations/<slug>/production')
@admin_required
def page(slug):
    station = station_for_operator(slug)
    voice = service.permitted(current_admin(),station,'voice')
    ai = service.permitted(current_admin(),station,'ai')
    if not voice and not ai and current_admin().role != 'ADMIN':abort(403)
    return render_template('admin/production.html',selected=station,stations=admin_stations(),page='production',
        voice_allowed=voice,ai_allowed=ai,csrf=csrf_token(),types=service.TYPES)


@production.route('/admin/stations/<slug>/production/drafts',methods=['GET','POST'])
@admin_required
def drafts(slug):
    station = station_for_operator(slug)
    if request.method == 'POST':
        require_csrf();data=payload()
        row=service.create(station,current_admin(),data.get('mode'),data.get('title',''),data.get('subtype','generic'))
        db.session.commit()
        return jsonify(describe(row)),201
    query = m.ProductionDraft.query.filter_by(station_id=station.id).filter(m.ProductionDraft.state.notin_(('deleted','expired')))
    if current_admin().role != 'ADMIN':
        query = query.filter_by(creator_id=current_admin().id)
    rows = [row for row in query.order_by(m.ProductionDraft.updated_at.desc()).limit(100) if current_admin().role=='ADMIN' or service.permitted(current_admin(),station,row.mode)]
    return jsonify(drafts=[describe(row) for row in rows],playlists=[dict(id=p.id,name=p.name,revision=p.revision,
        items=[dict(id=i.track_id,title=i.track.title) for i in sorted(p.items,key=lambda x:x.position)])
        for p in service.allowed_playlists(station,current_admin())])


@production.get('/admin/stations/<slug>/production/<identifier>')
@admin_required
def detail(slug,identifier):
    return jsonify(describe(owned(slug,identifier)))


@production.post('/admin/stations/<slug>/production/<identifier>/<action>')
@admin_required
def action(slug,identifier,action):
    require_csrf()
    row=owned(slug,identifier,True);data=payload()
    if action == 'place':service.place(row,current_admin(),data)
    elif action == 'delete':service.delete(row,current_admin())
    else:
        if action == 'upload':
            # Check idempotency and state before consuming/staging another upload.
            existing = m.ProductionAttempt.query.filter_by(draft_id=row.id,request_id=request.form.get('request_id')).first()
            if existing:return jsonify(describe(row))
            upload = request.files.get('audio')
            if not upload:raise ValueError('Choose an audio file.')
            from app.services.installation_settings import get_setting
            data['source'] = audio.upload(upload,get_setting('MAX_MEDIA_UPLOAD_BYTES'))
        try:
            service.enqueue(row,current_admin(),action,data,request.form.get('request_id'),request.form.get('revision',type=int))
        except Exception:
            if action=='upload':audio.path(data['source']).unlink(missing_ok=True)
            raise
    db.session.commit()
    return jsonify(describe(row))


@production.get('/admin/stations/<slug>/production/<identifier>/preview/<component>')
@admin_required
def preview(slug,identifier,component):
    row=owned(slug,identifier)
    if row.state in ('deleted','expired'):abort(404)
    if row.state=='saved':
        if not row.track or row.track.deleted_at or row.track.decommissioned_at:abort(404)
        if component=='render':
            from app.services.media_storage import LocalMediaStorage
            try:
                return send_file(LocalMediaStorage().regular_file(row.station.slug,row.track.storage_key),mimetype='audio/mpeg',conditional=True,max_age=0)
            except (ValueError,OSError):abort(404)
    if component.startswith('design-'):
        try:key=row.components['design'][int(component[7:])]['key']
        except (KeyError,IndexError,ValueError):abort(404)
    elif component in ('voice','bed','fx','render'):key=row.components.get(component)
    else:abort(404)
    try:return send_file(audio.path(key),mimetype='audio/mpeg',conditional=True,max_age=0)
    except (ValueError,OSError):abort(404)


def ai_access(slug):
    station=station_for_operator(slug)
    if not service.permitted(current_admin(),station,'ai'):abort(403)
    return station


@production.get('/admin/stations/<slug>/production/voices')
@admin_required
def voices(slug):
    ai_access(slug)
    return jsonify(providers.voices(request.args.get('q',''),request.args.get('cursor','')))


@production.get('/admin/stations/<slug>/production/models')
@admin_required
def models(slug):
    ai_access(slug)
    return jsonify(models=providers.models())


@production.get('/admin/stations/<slug>/production/voices/<voice_id>/preview')
@admin_required
def voice_preview(slug,voice_id):
    ai_access(slug)
    return send_file(BytesIO(providers.voice_preview(voice_id)),mimetype='audio/mpeg',max_age=0)


@production.route('/admin/providers',methods=['GET','POST'])
@installation_admin_required
def settings():
    if request.method=='POST':
        require_csrf()
        provider=request.form.get('provider')
        if provider not in providers.PROVIDERS:raise ValueError('Unknown provider.')
        if request.form.get('action')=='test':
            providers.test_connection(provider)
            return jsonify(message='Connection succeeded. Generation capabilities depend on account and key permissions.')
        from app.services.stations import allocation_lock
        allocation_lock()
        providers.save_credential(provider,request.form.get('key',''),request.form.get('model',''),
            request.form.get('revision',0),request.form.get('action')=='remove')
        audit('provider_configuration',user_id=current_admin().id,target_type='provider',target_id=provider,summary='Provider configuration updated')
        db.session.commit()
        return jsonify(message='Provider configuration saved.')
    rows={r.provider:r for r in m.ProviderCredential.query.all()}
    values=[dict(provider=p,configured=bool(rows.get(p) and rows[p].ciphertext),revision=rows[p].revision if p in rows else 0,
        model=rows[p].model if p in rows else '') for p in providers.PROVIDERS]
    return render_template('admin/production_providers.html',selected=None,stations=admin_stations(),page='providers',values=values,csrf=csrf_token())


@production.route('/admin/stations/<slug>/production/settings',methods=['GET','POST'])
@admin_required
def station_settings(slug):
    station=station_for_operator(slug)
    if current_admin().role!='ADMIN':abort(403)
    row=db.session.get(m.StationProduction,station.id)
    if request.method=='POST':
        require_csrf()
        from app.services.stations import allocation_lock
        allocation_lock()
        row=m.StationProduction.query.filter_by(station_id=station.id).with_for_update().populate_existing().first()
        data=payload()
        if data.get('revision') != (row.revision if row else 0):raise ValueError('Settings changed. Refresh first.')
        provider=data.get('script_provider','')
        if provider not in ('','anthropic','openai','xai'):raise ValueError('Choose a script provider.')
        row=row or m.StationProduction(station_id=station.id,revision=0)
        row.enabled=data.get('enabled') is True;row.script_provider=provider
        row.voice_id=service.text(data,'voice_id',120);row.model_id=service.text(data,'model_id',120) or 'eleven_multilingual_v2'
        row.revision+=1;db.session.add(row)
        allowed={p.id for p in service.allowed_playlists(station,current_admin())}
        grants=data.get('grants',[])
        if not isinstance(grants,list) or len(grants)>500:raise ValueError('Invalid DJ permissions.')
        for item in grants:
            if not isinstance(item,dict) or type(item.get('user_id')) is not int:
                raise ValueError('Choose a valid DJ.')
            user_id=item['user_id']
            if not db.session.get(m.DJStationAssignment,(user_id,station.id)):raise ValueError('DJ is not assigned to this station.')
            playlists=item.get('playlists',[])
            if not isinstance(playlists,list) or not all(type(x) is int for x in playlists) or not set(playlists)<=allowed:raise ValueError('Choose editable station playlists.')
            grant=db.session.get(m.ProductionGrant,(user_id,station.id)) or m.ProductionGrant(user_id=user_id,station_id=station.id)
            grant.voice_tracking=item.get('voice_tracking') is True;grant.ai_generation=item.get('ai_generation') is True
            grant.playlists=playlists;db.session.add(grant)
        audit('production_permissions',user_id=current_admin().id,station_id=station.id,summary='Station production permissions updated')
        db.session.commit()
        return jsonify(message='Station production settings saved.')
    users=m.AdminUser.query.join(m.DJStationAssignment,m.DJStationAssignment.admin_user_id==m.AdminUser.id).filter(m.DJStationAssignment.station_id==station.id).all()
    grants={g.user_id:g for g in m.ProductionGrant.query.filter_by(station_id=station.id)}
    return render_template('admin/production_settings.html',selected=station,stations=admin_stations(),page='production-settings',
        config=row,users=users,grants=grants,playlists=service.allowed_playlists(station,current_admin()),csrf=csrf_token())
