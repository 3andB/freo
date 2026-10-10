"""Durable, optional production queue, isolated from ingest and station playback."""
import base64
import hashlib
import logging
from datetime import timedelta
from urllib.parse import quote
from werkzeug.datastructures import FileStorage
from app.extensions import db
from app import models as m
from app.models.production import now
from app.services import production as service, production_audio as audio, production_providers as providers

logger = logging.getLogger('freo.production')


def ingest_draft(identifier, station_id=None):
    from app.services.media_probe import MediaValidationError
    draft = db.session.get(m.ProductionDraft,identifier)
    if not draft or draft.state != 'ingesting' or (station_id is not None and draft.station_id != station_id):
        raise MediaValidationError('Production is no longer available for ingest')
    user = db.session.get(m.AdminUser,draft.creator_id)
    try:
        service.authorize(draft,user)
    except PermissionError:
        raise MediaValidationError('Production permission was revoked') from None
    return draft


def generate(job):
    draft, values = job.draft, job.inputs
    components, spec = dict(draft.components), dict(draft.spec)
    usage = {}
    action = job.action
    if action == 'script':
        script, usage = providers.write_script(job.provider,values['model'],values['prompt'],values['seconds'],job.credential_revision)
        spec.update(script=script,prompt=values['prompt'],seconds=values['seconds'])
    elif action in ('voice','bed','fx'):
        if action == 'voice':
            endpoint = '/v1/text-to-speech/' + quote(values['voice_id'],safe='') + '?output_format=mp3_44100_128'
            payload = dict(text=values['script'],model_id=values['model_id'],voice_settings=values['voice_settings'])
        elif action == 'bed':
            endpoint = '/v1/music?output_format=mp3_44100_128'
            payload = dict(prompt=values['prompt'],music_length_ms=round(values['seconds']*1000),force_instrumental=True)
        else:
            endpoint = '/v1/sound-generation?output_format=mp3_44100_128'
            payload = dict(text=values['prompt'],duration_seconds=values['seconds'])
        raw, usage = providers.call('elevenlabs',endpoint,payload,binary=True,revision=job.credential_revision)
        key = audio.store(raw)
        audio.inspect(key,60 if action != 'fx' else 30)
        components[action] = key
        components.pop('render',None)
        spec[action] = values
        if action == 'voice':
            spec.update(script=values['script'],voice_id=values['voice_id'],model_id=values['model_id'])
    elif action == 'design':
        result, usage = providers.call('elevenlabs','/v1/text-to-voice/design',
            dict(voice_description=values['description'],auto_generate_text=True),revision=job.credential_revision)
        previews = []
        for preview in result.get('previews',[])[:3]:
            key = audio.store(base64.b64decode(preview['audio_base_64'],validate=True))
            audio.inspect(key,60)
            previews.append(dict(id=preview['generated_voice_id'],key=key))
        if not previews:
            raise ValueError('No voice previews were returned.')
        components['design'] = previews
    elif action == 'save_voice':
        result, usage = providers.call('elevenlabs','/v1/text-to-voice',dict(voice_name=values['name'],
            voice_description=values['description'],generated_voice_id=values['generated_voice_id']),revision=job.credential_revision)
        spec['voice_id'] = result['voice_id']
    elif action == 'upload':
        key, duration = audio.render({'voice':values['source']},{},300)
        components = dict(voice=key,render=key)
        spec['duration_ms'] = duration
    elif action == 'render':
        key, duration = audio.render(components,values,300 if draft.mode=='voice' else 60)
        components['render'] = key
        spec.update(mix=values,duration_ms=duration)
    elif action == 'save':
        from app.services.admin_media import stage_upload
        source = audio.path(values['render'])
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        existing = m.Track.query.filter_by(station_id=draft.station_id,checksum_sha256=digest).first()
        if existing and (existing.id != draft.track_id or existing.deleted_at):
            raise ValueError('This audio already exists in the catalog. Use the existing asset or create a new take.')
        with source.open('rb') as stream:
            ingest = stage_upload(draft.station,db.session.get(m.AdminUser,job.actor_id),
                FileStorage(stream=stream,filename='station-audio.mp3'),commit=False,
                import_metadata=dict(title=draft.title,audio_kind='STATION',audio_subtype=draft.subtype,
                                     artist_name=draft.station.name,keep_disabled=True,production_id=draft.id))
        draft.ingest_job_id = ingest.id
        draft.state = 'ingesting'
    # Recheck after a slow provider call; do not publish results for revoked users.
    db.session.flush()
    db.session.expire_all()
    draft = job.draft
    service.authorize(draft,db.session.get(m.AdminUser,job.actor_id))
    if job.provider:
        providers.credential(job.provider,job.credential_revision)
    draft.components = components
    draft.spec = spec
    draft.updated_at = now()
    draft.revision += 1
    job.usage = usage


def process_one():
    job = m.ProductionAttempt.query.filter_by(status='pending').order_by(m.ProductionAttempt.created_at,m.ProductionAttempt.id).with_for_update(skip_locked=True).first()
    if not job:
        db.session.rollback()
        return False
    identifier = job.id
    job.status = 'running';job.started_at = now()
    db.session.commit()
    try:
        service.authorize(job.draft,db.session.get(m.AdminUser,job.actor_id))
        if job.provider:
            providers.credential(job.provider,job.credential_revision)
        generate(job)
        job.status = 'complete';job.finished_at = now()
        db.session.commit()
    except Exception as error:
        db.session.rollback()
        job = db.session.get(m.ProductionAttempt,identifier)
        # Only messages generated by our validation/providers are safe for clients.
        message = str(error)[:240] if type(error) in (ValueError,PermissionError,providers.ProviderError) else 'Production failed. Check provider usage before retrying.'
        job.status = 'failed';job.error = message;job.finished_at = now()
        job.draft.error = message;job.draft.updated_at = now();job.draft.revision += 1
        db.session.commit()
        logger.warning('Production failed job=%s error_type=%s',identifier,type(error).__name__)
    return True


def reconcile():
    for draft in m.ProductionDraft.query.filter_by(state='ingesting').all():
        job = db.session.get(m.MediaIngestJob,draft.ingest_job_id)
        if not job or job.status in ('error','rejected'):
            draft.state = 'draft';draft.error = 'Ingest failed. Your rendered preview is retained; try Save again.'
        elif job.status in ('accepted','duplicate'):
            track = job.track
            if not track or draft.track_id != track.id or track.audio_kind != 'STATION' or track.station_id != draft.station_id or track.deleted_at:
                draft.state = 'draft';draft.error = 'Ingest did not produce a new station-owned asset.'
            else:
                try:
                    service.authorize(draft,db.session.get(m.AdminUser,draft.creator_id))
                    if track.analysis_status == 'complete':
                        from app.services.media import set_enabled_db
                        set_enabled_db(track,True)
                        draft.state = 'saved';draft.error = None
                    elif track.analysis_status == 'failed':
                        # Retain the accepted asset, disabled, for normal catalog recovery.
                        draft.state = 'saved';draft.error = 'Audio was saved disabled because analysis failed. An administrator can retry processing in the track editor.'
                except PermissionError:
                    draft.state = 'saved';draft.error = 'Access was revoked; audio remains disabled for administrator review.'
        draft.updated_at = now()
    db.session.commit()


def recover():
    # A single service owns this queue. Never repeat ambiguous paid operations.
    for job in m.ProductionAttempt.query.filter_by(status='running'):
        job.status = 'failed';job.finished_at = now()
        job.error = 'Production was interrupted. Check provider usage before explicitly retrying.'
        job.draft.error = job.error;job.draft.revision += 1
    db.session.commit()


def cleanup():
    cutoff = now()-timedelta(days=7)
    for saved in m.ProductionDraft.query.filter_by(state='saved'):
        if not saved.track or saved.track.deleted_at:
            saved.state='deleted';saved.components={};saved.revision+=1
    for draft in m.ProductionDraft.query.filter(m.ProductionDraft.updated_at < cutoff,m.ProductionDraft.state=='draft'):
        if not m.ProductionAttempt.query.filter_by(draft_id=draft.id).filter(m.ProductionAttempt.status.in_(('pending','running'))).first():
            draft.state = 'expired';draft.components = {};draft.revision += 1
    db.session.commit()
    protected = set()
    for draft in m.ProductionDraft.query.filter(m.ProductionDraft.state.notin_(('expired','deleted'))):
        for key,value in draft.components.items():
            if isinstance(value,str):protected.add(value)
            elif key=='design':protected.update(x['key'] for x in value)
    for job in m.ProductionAttempt.query.filter(m.ProductionAttempt.status.in_(('pending','running'))):
        if job.inputs.get('source'):protected.add(job.inputs['source'])
    for file in audio.root().iterdir():
        if audio.KEY.fullmatch(file.name) and file.name not in protected and not file.is_symlink() and file.is_file() and file.stat().st_mtime < cutoff.timestamp():
            file.unlink()
