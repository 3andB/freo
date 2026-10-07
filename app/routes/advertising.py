"""Station advertising management; audio links never create scheduling work."""
import hashlib
import uuid
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo
from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, Response, url_for
from sqlalchemy.exc import IntegrityError
from app.extensions import db
from app.models import Advertiser, Campaign, CampaignDisplayAsset, Track
from app.routes.web import station_or_404, admin_stations
from app.routes.player_experience import public_station
from app.services.admin_auth import admin_required, require_csrf, current_admin
from app.services.admin_media import audit, stage_upload, staged_path
from app.services import advertising as service
from app.services import player, polish

advertising = Blueprint('advertising', __name__)


def owned(station, identifier):
    row = Campaign.query.filter_by(station_id=station.id, id=identifier).first_or_404()
    if service.settings(row).get('deleted'): abort(404)
    return row


@advertising.get('/admin/stations/<slug>/advertising')
@admin_required
def page(slug):
    station = station_or_404(slug, require_enabled=False)
    rows = Campaign.query.filter_by(station_id=station.id).order_by(Campaign.name, Campaign.id).all()
    rows = [row for row in rows if not service.settings(row).get('deleted')]
    return render_template('admin/advertising.html', selected=station, stations=admin_stations(),
        page='advertising', campaigns=rows, ad_settings=service.settings, ad_status=service.status,
        audio_link=service.audio_link)


@advertising.route('/admin/stations/<slug>/advertising/new', methods=['GET', 'POST'])
@advertising.route('/admin/stations/<slug>/advertising/<int:campaign_id>', methods=['GET', 'POST'])
@admin_required
def editor(slug, campaign_id=None):
    station = station_or_404(slug, require_enabled=False)
    campaign = owned(station, campaign_id) if campaign_id else None
    values = service.settings(campaign) if campaign else dict(service.DEFAULTS)
    error = None
    job = None
    if request.method == 'POST':
        require_csrf()
        try:
            # Serialize editing with other advertising mutations on this station.
            from app.models import Station
            db.session.query(Station.id).filter_by(id=station.id).with_for_update().first()
            if campaign:
                db.session.refresh(campaign)
                if request.form.get('revision') != campaign.updated_at.isoformat():
                    raise ValueError('Campaign changed in another window. Reload before saving.')
            name = player.clean_text(request.form.get('name', ''), 120)
            if not name: raise ValueError('Enter a campaign name')
            previous = dict(campaign.advertising or {}) if campaign else {}
            if campaign and not any(key in previous for key in ('audio_track_id', 'audio_job_id')):
                existing_audio, _ = service.audio_link(campaign)
                previous['audio_track_id'] = existing_audio.id if existing_audio else None
            values = service.validate(request.form, station, previous)
            if campaign is None:
                identifier = uuid.uuid4().hex
                advertiser = Advertiser(station_id=station.id, name=name, slug='ad-'+identifier)
                db.session.add(advertiser); db.session.flush()
                # DRAFT with no traffic rules: creating a display campaign cannot schedule audio.
                campaign = Campaign(station_id=station.id, advertiser_id=advertiser.id, name=name,
                    slug='ad-'+identifier, status='DRAFT', start_date=date.today(), end_date=date(9999, 12, 31))
                db.session.add(campaign); db.session.flush()
            campaign.name = name
            prefix = 'ad_'+values['placement']
            for device in ('desktop', 'mobile'):
                asset = db.session.get(CampaignDisplayAsset, (campaign.id, device))
                upload = request.files.get(device)
                remove = request.form.get('remove_'+device) == 'yes'
                if upload and upload.filename:
                    if remove: raise ValueError('Choose upload or remove for each image')
                    from app.routes.station_settings import decode_logo
                    image = decode_logo(upload, output_limit=None, accepted_sizes=polish.sizes(prefix, device == 'mobile'))[0]
                    asset = asset or CampaignDisplayAsset(campaign_id=campaign.id, device=device)
                    asset.image = image; asset.version = hashlib.sha256(image).hexdigest()
                    asset.width, asset.height = polish.png_size(image)
                    db.session.add(asset)
                elif remove and asset:
                    db.session.delete(asset)
                elif asset and (asset.width, asset.height) not in polish.sizes(prefix, device == 'mobile'):
                    raise ValueError('Replace or remove the image before changing its placement')
            audio = request.files.get('audio')
            audio_id = request.form.get('audio_track_id', '')
            remove_audio = request.form.get('remove_audio') == 'yes'
            if remove_audio:
                if audio and audio.filename or audio_id: raise ValueError('Choose audio or remove its link')
                values.update(audio_track_id=None, audio_job_id=None)
            elif audio and audio.filename:
                if audio_id: raise ValueError('Choose an upload or an existing audio file')
                job = stage_upload(station, current_admin(), audio,
                    import_metadata=dict(audio_kind='COMMERCIALS', audio_subtype='', cart_code='', keep_disabled=True), commit=False)
                values.update(audio_job_id=job.id, audio_track_id=None)
            elif audio_id:
                track = Track.query.filter_by(id=int(audio_id), station_id=station.id, audio_kind='COMMERCIALS',
                    ingest_status='accepted', deleted_at=None, decommissioned_at=None).first()
                if not track: raise ValueError('Choose available commercial audio owned by this station')
                values.update(audio_track_id=track.id, audio_job_id=None)
            campaign.advertising = values
            campaign.updated_at = datetime.now(timezone.utc)
            audit('advertising_saved', user_id=current_admin().id, station_id=station.id,
                target_type='campaign', target_id=campaign.id, summary=name)
            db.session.commit()
            flash('Advertising saved. Linked audio is scheduled separately in Scheduler or Traffic.', 'success')
            return redirect(url_for('.page', slug=slug), code=303)
        except (ValueError, TypeError, IntegrityError) as exc:
            db.session.rollback()
            if job: staged_path(job.id).unlink(missing_ok=True)
            error = str(exc) if not isinstance(exc, IntegrityError) else 'Unable to save. Reload and try again.'
            campaign = owned(station, campaign_id) if campaign_id else None
            values = service.settings(campaign) if campaign else dict(service.DEFAULTS)
    track, linked_job = service.audio_link(campaign) if campaign else (None, None)
    def local_time(value):
        return player.timestamp(value).astimezone(ZoneInfo(station.timezone)).strftime('%Y-%m-%dT%H:%M') if value else ''
    return render_template('admin/advertising_editor.html', selected=station, stations=admin_stations(),
        page='advertising', campaign=campaign, values=values, error=error, linked_audio=track, linked_job=linked_job,
        local_time=local_time, commercials=Track.query.filter_by(station_id=station.id, audio_kind='COMMERCIALS',
            ingest_status='accepted', deleted_at=None, decommissioned_at=None).order_by(Track.title).all()), 400 if error else 200


@advertising.post('/admin/stations/<slug>/advertising/<int:campaign_id>/<action>')
@admin_required
def mutate(slug, campaign_id, action):
    require_csrf()
    station = station_or_404(slug, require_enabled=False)
    campaign = owned(station, campaign_id)
    values = service.settings(campaign)
    if action == 'toggle': values['active'] = not values['active']
    elif action == 'delete': values.update(deleted=True, active=False)
    else: abort(404)
    campaign.advertising = values
    audit('advertising_'+action, user_id=current_admin().id, station_id=station.id,
        target_type='campaign', target_id=campaign.id, summary=campaign.name)
    db.session.commit()
    return redirect(url_for('.page', slug=slug), code=303)


@advertising.get('/station-assets/<slug>/advertising/<int:campaign_id>/<device>.png')
def asset(slug, campaign_id, device):
    from app.services.stations import public_station_for
    from app.services.admin_auth import can_access_station
    try: station = public_station_for(slug)
    except ValueError: station = None
    if not station or (not station.enabled and not can_access_station(current_admin(), station)): abort(404)
    owned(station, campaign_id)
    row = db.session.get(CampaignDisplayAsset, (campaign_id, device))
    if not row: abort(404)
    response = Response(row.image, mimetype='image/png')
    response.set_etag(row.version)
    response.headers['Cache-Control'] = 'public, max-age=300' if station.enabled else 'private, no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response.make_conditional(request)


@advertising.get('/api/stations/<slug>/advertising/<surface>/<placement>')
def selection(slug, surface, placement):
    station = public_station(slug)
    if surface not in service.SURFACES or placement not in ('top', 'bottom'): abort(404)
    response = jsonify(ad=service.select(station, surface, placement, current=request.args.get('current')))
    response.headers['Cache-Control'] = 'no-store'
    return response


@advertising.app_context_processor
def helpers():
    return dict(advertising_context=service.context)
