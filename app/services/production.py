"""Permission-checked production commands. External generation belongs to its worker."""
import math
import re
from uuid import UUID
from app.extensions import db
from app import models as m
from app.models.production import now
from app.services.admin_auth import can_access_station
from app.services.admin_media import audit
from app.services import production_providers as providers
from app.services import production_audio as audio

TYPES = ('station_id','sweeper','liner','show_intro','show_outro','promo','generic')
ACTIONS = ('script','voice','bed','fx','design','save_voice','upload','render','save')


def permitted(user, station, mode):
    if not can_access_station(user,station) or station.deleted_at or not station.enabled or station.lifecycle_state in ('pending_delete','delete_failed'):
        return False
    if mode == 'ai':
        config = db.session.get(m.StationProduction,station.id)
        if not config or not config.enabled:
            return False
    if user.role == 'ADMIN':
        return True
    grant = db.session.get(m.ProductionGrant,(user.id,station.id))
    return bool(grant and (grant.ai_generation if mode == 'ai' else grant.voice_tracking))


def authorize(draft, user, *, allow_admin_review=False):
    if allow_admin_review and user and user.active and user.role == 'ADMIN' and not draft.station.deleted_at:
        return
    if not permitted(user,draft.station,draft.mode) or (user.role != 'ADMIN' and draft.creator_id != user.id):
        raise PermissionError('Audio production access is not permitted.')


def create(station, user, mode, title, subtype):
    if mode not in ('voice','ai') or not permitted(user,station,mode):
        raise PermissionError('Audio production access is not permitted.')
    if mode == 'voice':
        subtype = 'voice_track'
    if subtype not in TYPES + ('voice_track',) or not isinstance(title,str) or not 1 <= len(title.strip()) <= 200:
        raise ValueError('Enter a title and valid station audio type.')
    config = db.session.get(m.StationProduction,station.id)
    row = m.ProductionDraft(station_id=station.id,creator_id=user.id,mode=mode,title=title.strip(),subtype=subtype,
        spec=dict(voice_id=config.voice_id if config else '',model_id=config.model_id if config else 'eleven_multilingual_v2',
                  script='',prompt='',seconds=10),components={})
    db.session.add(row);db.session.flush()
    audit('production_created',user_id=user.id,station_id=station.id,target_type='production',target_id=row.id)
    return row


def text(data, key, limit=5000, required=False):
    value = data.get(key,'')
    if not isinstance(value,str) or len(value) > limit or (required and not value.strip()):
        raise ValueError(f'Enter {key.replace("_"," ")} of at most {limit} characters.')
    return value.strip()


def number(data,key,low,high,default):
    try:
        value = float(data.get(key,default))
    except (ValueError,TypeError):
        raise ValueError('Invalid ' + key.replace('_',' ')) from None
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f'{key.replace("_"," ")} must be between {low} and {high}.')
    return value


def enqueue(draft,user,action,data,request_id,revision):
    authorize(draft,user)
    if action not in ACTIONS:
        raise ValueError('Unknown production action.')
    try:
        request_id = str(UUID(request_id))
    except (ValueError,TypeError,AttributeError):
        raise ValueError('Invalid request identifier.') from None
    existing = m.ProductionAttempt.query.filter_by(draft_id=draft.id,request_id=request_id).first()
    if existing:
        return existing
    if revision != draft.revision or draft.state in ('saved','ingesting','deleted','expired'):
        raise ValueError('This production changed or is already saved. Refresh before continuing.')
    if m.ProductionAttempt.query.filter_by(draft_id=draft.id).filter(m.ProductionAttempt.status.in_(('pending','running'))).first():
        raise ValueError('Wait for this production operation to finish.')
    if action not in ('upload','render','save') and draft.mode != 'ai':
        raise PermissionError('AI generation permission is required.')
    if action == 'save_voice' and user.role != 'ADMIN':
        raise PermissionError('Only administrators can save voices to the shared account.')
    values, provider = {}, None
    if action == 'script':
        config = db.session.get(m.StationProduction,draft.station_id)
        provider = config.script_provider
        if provider not in ('openai','anthropic','xai'):
            raise ValueError('Ask the station administrator to select a script provider, or enter your own script.')
        _, credentials = providers.credential(provider)
        if not credentials.model:
            raise ValueError('Ask the installation administrator to configure a script model.')
        values = dict(prompt=text(data,'prompt',required=True),seconds=number(data,'seconds',1,60,10),model=credentials.model)
    elif action == 'voice':
        provider = 'elevenlabs'
        values = dict(script=text(data,'script',required=True),voice_id=text(data,'voice_id',120,True),model_id=text(data,'model_id',120,True))
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,120}',values['voice_id']):
            raise ValueError('Choose a valid voice.')
        available = {x['id']:x for x in providers.models()}
        if values['model_id'] not in available:
            raise ValueError('Choose an available speech model.')
        settings = dict(stability=number(data,'stability',0,1,.5),speed=number(data,'speed',.7,1.2,1))
        if values['model_id'] == 'eleven_v3' and settings['stability'] not in (0,.5,1):
            raise ValueError('This model supports stability 0, 0.5, or 1.')
        if available[values['model_id']]['similarity']:
            settings['similarity_boost'] = number(data,'similarity',0,1,.75)
        if available[values['model_id']]['style']:
            settings['style'] = number(data,'style',0,1,0)
        values['voice_settings'] = settings
    elif action in ('bed','fx'):
        provider = 'elevenlabs'
        values = dict(prompt=text(data,'prompt',4100,True),seconds=number(data,'seconds',3 if action=='bed' else .5,60 if action=='bed' else 30,10))
    elif action == 'design':
        provider = 'elevenlabs'
        values = dict(description=text(data,'description',1000,True))
        if len(values['description']) < 20:
            raise ValueError('Describe the voice in at least 20 characters.')
    elif action == 'save_voice':
        provider = 'elevenlabs'
        preview = next((x for x in draft.components.get('design',[]) if x['id'] == data.get('generated_voice_id')),None)
        if not preview:
            raise ValueError('Choose a generated voice preview.')
        values = dict(generated_voice_id=preview['id'],name=text(data,'name',100,True),description=text(data,'description',500))
    elif action == 'upload':
        if draft.mode != 'voice':
            raise ValueError('Use Record Voice Track for uploaded recordings.')
        values = dict(source=data['source'])
    elif action == 'render':
        if not draft.components.get('voice'):
            raise ValueError('Record or generate a voice first.')
        for component in ('voice','bed','fx'):
            values[component+'_level'] = number(data,component+'_level',-60,6,{'voice':0,'bed':-18,'fx':-12}[component])
            values[component+'_offset'] = number(data,component+'_offset',0,60,0)
        values['fade'] = number(data,'fade',0,10,1)
        values['use_bed'] = data.get('use_bed',True) is True
        values['use_fx'] = data.get('use_fx',True) is True
    elif action == 'save':
        if not draft.components.get('render'):
            raise ValueError('Render and preview the finished audio first.')
        values = dict(render=draft.components['render'])
    credential_revision = None
    if provider:
        _, credentials = providers.credential(provider)
        credential_revision = credentials.revision
    row = m.ProductionAttempt(draft_id=draft.id,actor_id=user.id,request_id=request_id,action=action,inputs=values,
        provider=provider,credential_revision=credential_revision)
    db.session.add(row)
    draft.revision += 1
    draft.updated_at = now()
    draft.error = None
    audit('production_'+action,user_id=user.id,station_id=draft.station_id,target_type='production',target_id=draft.id)
    return row


def allowed_playlists(station,user):
    rows = m.Playlist.query.filter_by(station_id=station.id,deleted_at=None,smart_enabled=False).all()
    rows = [r for r in rows if r.system_key not in ('STATION','COMMERCIALS')]
    if user.role != 'ADMIN':
        grant = db.session.get(m.ProductionGrant,(user.id,station.id))
        rows = [r for r in rows if grant and r.id in grant.playlists]
    return rows


def own_track(draft,user):
    authorize(draft,user,allow_admin_review=True)
    track = draft.track
    if not track or draft.state != 'saved' or track.station_id != draft.station_id or track.deleted_at:
        raise ValueError('This audio has not completed ingest.')
    return track


def place(draft,user,data):
    from app.services.playlists import ordered_ids, replace_order
    from app.services.availability import playable
    from app.services.stations import allocation_lock
    allocation_lock()
    db.session.expire_all()
    track = own_track(draft,user)
    if not playable(track,draft.station_id):
        raise ValueError('Wait for media analysis and enablement before placing this audio.')
    playlist_id = int(data.get('playlist_id',0))
    row = m.Playlist.query.filter_by(id=playlist_id,station_id=draft.station_id).with_for_update().populate_existing().first()
    if not row or row.id not in {r.id for r in allowed_playlists(draft.station,user)}:
        raise PermissionError('This playlist is not granted for voice tracking.')
    if int(data.get('revision',0)) != row.revision:
        raise ValueError('Playlist changed. Refresh before trying again.')
    ids = ordered_ids(row)
    old_id = int(data.get('replace_id',0))
    action = data.get('operation','insert')
    if action not in ('insert','remove','replace'):
        raise ValueError('Choose insert, remove, or replace.')
    if action == 'replace':
        old = m.ProductionDraft.query.filter_by(station_id=draft.station_id,track_id=old_id,state='saved').first()
        if not old or old_id not in ids:
            raise ValueError('Choose an existing production track in this playlist.')
        authorize(old,user)
        if track.id in ids and track.id != old_id:
            raise ValueError('The replacement is already in this playlist.')
        ids = [track.id if x == old_id else x for x in ids]
    else:
        ids = [x for x in ids if x != track.id]
        if action == 'insert':
            index = int(data.get('position',len(ids)))
            if not 0 <= index <= len(ids):
                raise ValueError('Choose a position within this playlist.')
            ids.insert(index,track.id)
    replace_order(row,ids)
    audit('production_placed',user_id=user.id,station_id=draft.station_id,target_type='playlist',target_id=str(row.id))


def delete(draft,user):
    from app.services.stations import allocation_lock
    allocation_lock()
    db.session.expire_all()
    authorize(draft,user,allow_admin_review=True)
    if draft.state == 'ingesting' or m.ProductionAttempt.query.filter_by(draft_id=draft.id).filter(m.ProductionAttempt.status.in_(('pending','running'))).first():
        raise ValueError('Wait for the current operation to finish.')
    if draft.track:
        track = own_track(draft,user)
        if user.role != 'ADMIN':
            # A DJ may not invoke catalog-wide cleanup of other programming.
            allowed = {r.id for r in allowed_playlists(draft.station,user)}
            for row in m.Playlist.query.filter_by(leader_track_id=track.id):
                raise ValueError('An administrator must remove this playlist leader.')
            for row in m.Playlist.query.join(m.PlaylistItem).filter(m.PlaylistItem.track_id==track.id):
                if row.system_key != 'STATION' and row.id not in allowed:
                    raise ValueError('An administrator must remove this audio from other playlists.')
            if m.SelectionDecision.query.filter(m.SelectionDecision.track_id==track.id,m.SelectionDecision.status.in_(('selected','submitting','queued'))).first():
                raise ValueError('This audio is queued or playing. Ask an administrator to delete it.')
            snapshot = db.session.get(m.LiveQueueSnapshot,draft.station_id)
            if draft.station.desired_state == 'running':
                if not snapshot or snapshot.error_code or snapshot.unknown_count or not snapshot.observed_at or (now()-snapshot.observed_at.replace(tzinfo=snapshot.observed_at.tzinfo or now().tzinfo)).total_seconds() > 15:
                    raise ValueError('Playback status is stale. Ask an administrator to delete this audio.')
                active = {snapshot.current_decision_id}
                active.update(snapshot.queued_decision_ids or [])
                active.update((snapshot.mixer or {}).get(name) for name in ('a_id','b_id','cart_id'))
                if m.SelectionDecision.query.filter(m.SelectionDecision.track_id==track.id,m.SelectionDecision.id.in_([x for x in active if x])).first():
                    raise ValueError('This audio is queued or playing. Ask an administrator to delete it.')
            for cue in m.BoothCue.query.all():
                if track.id in cue.saved_order or any(x.get('track_id')==track.id for x in cue.entries):
                    raise ValueError('An administrator must remove this audio from booth programming.')
            for cue in m.SavedBoothCue.query.all():
                if track.id in cue.tracks:
                    raise ValueError('An administrator must remove this saved booth cue.')
            # Conservatively reject any non-playlist programming reference.
            for model in (m.TimedEvent,m.EventBlockItem,m.LiveCartSlot,m.CommercialCreative,m.TrafficStopsetItem):
                if model.query.filter_by(track_id=track.id).first():
                    raise ValueError('An administrator must remove this audio from programming.')
            from app.services.music_delete import _prune_source
            for model,fields in ((m.ChannelSchedule,('calendar','simple','live_simple')),(m.ScheduleCompositionRevision,('sections',)),(m.ScheduleTransition,('simple',))):
                for row in model.query.all():
                    if any(_prune_source(getattr(row,f),track.id) != getattr(row,f) for f in fields):
                        raise ValueError('An administrator must remove this scheduled audio.')
        from app.services.music_delete import queue_delete
        queue_delete(track,user,draft.station)
    draft.state = 'deleted';draft.updated_at = now();draft.revision += 1
    audit('production_deleted',user_id=user.id,station_id=draft.station_id,target_type='production',target_id=draft.id)
