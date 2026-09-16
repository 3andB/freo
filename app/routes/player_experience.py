"""Station presentation, published listings, and anonymous song feedback."""
import hashlib
import hmac
import secrets
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlsplit

from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, Response, session, url_for, current_app
from sqlalchemy.exc import IntegrityError
from app.extensions import db
from app.models import (Station, StationPlayerSettings, StationPlayerAsset, PublicScheduleRevision,
                        SelectionDecision, ListenerVote, ListenerFeedbackEvent)
from app.routes.web import station_or_404, admin_stations
from app.services.admin_auth import admin_required, require_csrf, current_admin
from app.services.stations import public_station_for
from app.services import player as service
from app.services.admin_media import audit

player_experience=Blueprint('player_experience',__name__)


def public_station(slug):
    try:station=public_station_for(slug)
    except ValueError:station=None
    if not station or not station.enabled or station.lifecycle_state in ('pending_delete','delete_failed'):abort(404)
    return station


@player_experience.app_context_processor
def helpers():
    from zoneinfo import ZoneInfo
    return dict(player_context=service.public_context, player_time=lambda value,zone: service.timestamp(value).astimezone(ZoneInfo(zone)).strftime('%d %b %Y · %H:%M'))


@player_experience.route('/admin/stations/<slug>/player-settings',methods=['GET','POST'])
@admin_required
def settings(slug):
    station=station_or_404(request.args.get('station',slug) if request.method=='GET' else slug,require_enabled=False)
    if station.slug!=slug:return redirect(url_for('.settings',slug=station.slug))
    config=service.settings(station)
    error=None
    preview=None
    if request.method=='POST':
        require_csrf()
        try:
            db.session.query(Station.id).filter_by(id=station.id).with_for_update().first()
            row=StationPlayerSettings.query.filter_by(station_id=station.id).populate_existing().first()
            revision=row.revision if row else 0
            if int(request.form.get('revision','-1'))!=revision:raise ValueError('Settings changed in another window. Reload before saving.')
            action=request.form.get('action','save')
            if action in ('save','preview','publish','preview-player'):
                new_config=service.validate_config(request.form)
                new_config['custom_entries']=config['custom_entries']
                config=new_config
            elif action=='add-entry':
                if len(config['custom_entries'])>=200:raise ValueError('Use at most 200 custom listings')
                config['custom_entries']=[*config['custom_entries'],service.custom_entry(request.form)]
            elif action=='unpublish':
                config['schedule_enabled']=False
                config['auto_publish']=False
            elif action=='remove-entry':
                index=int(request.form.get('index','-1'))
                if not 0<=index<len(config['custom_entries']):raise ValueError('Listing is unavailable')
                config['custom_entries']=[item for i,item in enumerate(config['custom_entries']) if i!=index]
            else:raise ValueError('Unknown settings action')
            # Validate even outside the publication horizon, including recurring overlaps.
            if action=='add-entry':
                anchor=config['custom_entries'][-1].get('on_date')
                service.build_schedule(station,dict(config,schedule_mode='custom'),date.fromisoformat(anchor) if anchor else date(2026,1,5),14)
            if action=='preview-player':
                return render_template('player.html',station=station,player_preview=service.public_context(station,config))
            if action=='preview':
                preview=service.build_schedule(station,config)
            else:
                from app.routes.station_settings import decode_logo
                for kind in service.ASSETS:
                    upload=request.files.get(kind)
                    remove=request.form.get('remove_'+kind)=='yes'
                    if upload and upload.filename and remove:raise ValueError('Choose upload or remove for each image')
                    asset=StationPlayerAsset.query.filter_by(station_id=station.id,kind=kind).first()
                    if upload and upload.filename:
                        images=decode_logo(upload, output_limit=900 if kind.endswith('_mobile') else 2000)
                        asset=asset or StationPlayerAsset(station_id=station.id,kind=kind)
                        asset.image=images[0];asset.version=hashlib.sha256(images[0]).hexdigest()
                        db.session.add(asset)
                    elif remove and asset:db.session.delete(asset)
                if not row:
                    row=StationPlayerSettings(station_id=station.id,revision=0)
                    db.session.add(row)
                    station.player_settings=row
                row.config=config;row.revision+=1
                db.session.flush()
                if action=='publish' or config['auto_publish']:
                    service.publish(station,config)
                audit('player_settings_'+action,user_id=current_admin().id,station_id=station.id,target_type='station',target_id=station.id,summary='Player settings revision '+str(row.revision))
                db.session.commit()
                flash('Schedule published.' if action=='publish' else 'Player settings saved.','success')
                return redirect(url_for('.settings',slug=station.slug))
        except (ValueError,TypeError,IntegrityError) as exc:
            db.session.rollback()
            error=str(exc) if not isinstance(exc,IntegrityError) else 'Settings changed. Reload and try again.'
            config=service.settings(station)
            if request.form.get('action','save') in ('save','preview','publish','preview-player'):
                # Keep the draft editable on validation failure, without publishing it.
                for key,default in service.DEFAULTS.items():
                    if isinstance(default,bool):config[key]=request.form.get(key)=='yes'
                    elif isinstance(default,str):config[key]=request.form.get(key,default)
                config['schedule_views']=request.form.getlist('schedule_views')
                config['socials']=[dict(platform=platform,url=request.form.get('social_'+platform,''),visible=request.form.get('visible_'+platform)=='yes') for platform in service.PLATFORMS]

    publication=PublicScheduleRevision.query.filter_by(station_id=station.id).order_by(PublicScheduleRevision.id.desc()).first()
    return render_template('admin/player_settings.html',selected=station,stations=admin_stations(),page='player-settings',
        config=config,revision=request.form.get('revision','0') if error else (station.player_settings.revision if station.player_settings else 0),
        platforms=service.PLATFORMS,asset_kinds=service.ASSETS,error=error,preview=preview,publication=publication,
        **service.public_context(station)),400 if error else 200


@player_experience.get('/station-assets/<slug>/player/<kind>.png')
def asset(slug,kind):
    if kind not in service.ASSETS:abort(404)
    try:station=public_station_for(slug)
    except ValueError:station=None
    if not station or (not station.enabled and not current_admin()):abort(404)
    row=StationPlayerAsset.query.filter_by(station_id=station.id,kind=kind).first_or_404()
    response=Response(row.image,mimetype='image/png')
    response.set_etag(row.version)
    response.headers['Cache-Control']='public, max-age=300' if station.enabled else 'private, no-store'
    response.headers['X-Content-Type-Options']='nosniff'
    return response.make_conditional(request)


@player_experience.get('/api/stations/<slug>/player')
def public_state(slug):
    station=public_station(slug)
    response=jsonify(service.now_playing(station))
    response.headers['Cache-Control']='public, max-age=3'
    return response


@player_experience.get('/api/stations/<slug>/public-schedule')
def public_schedule(slug):
    station=public_station(slug)
    config=service.settings(station)
    if not config['schedule_enabled']:return jsonify(entries=[],timezone=station.timezone)
    try:
        start=date.fromisoformat(request.args.get('start',''))
        days=int(request.args.get('days','7'))
        if not 1<=days<=31:raise ValueError()
    except ValueError:abort(400)
    row=PublicScheduleRevision.query.filter_by(station_id=station.id).order_by(PublicScheduleRevision.id.desc()).first()
    from zoneinfo import ZoneInfo
    from datetime import time
    from app.services.schedule import _wall_to_utc
    zone=ZoneInfo(station.timezone)
    begin=_wall_to_utc(datetime.combine(start,time()),zone)
    finish=_wall_to_utc(datetime.combine(start+timedelta(days=days),time()),zone)
    entries=[entry for entry in row.entries if service.timestamp(entry['start'])<finish and service.timestamp(entry['end'])>begin] if row else []
    response=jsonify(entries=entries,timezone=station.timezone,revision=row.id if row else None,
                     published_until=row.end_date.isoformat() if row else None)
    response.headers['Cache-Control']='public, max-age=30'
    return response


def listener_key():
    if not session.get('listener_key'):session['listener_key']=secrets.token_hex(32)
    if not session.get('listener_csrf'):session['listener_csrf']=secrets.token_urlsafe(32)
    return session['listener_key']


def vote_data(row):
    return dict(value=row.value if row else 0,comment=row.comment if row else '',revision=row.revision if row else 0)


@player_experience.route('/api/stations/<slug>/feedback/<int:decision_id>',methods=['GET','POST'])
def feedback(slug,decision_id):
    station=public_station(slug)
    config=service.settings(station)
    if not config['voting_enabled']:abort(404)
    now=datetime.now(timezone.utc)
    decision=SelectionDecision.query.filter_by(id=decision_id,station_id=station.id,status='started').filter(
        SelectionDecision.started_at>=now-timedelta(hours=24),SelectionDecision.started_at<=now,
        SelectionDecision.track_id.isnot(None)).first_or_404()
    if not decision.track or decision.track.deleted_at:abort(404)
    key=listener_key()
    query=ListenerVote.query.filter_by(station_id=station.id,track_id=decision.track_id,listener_key=key)
    if request.method=='POST':
        origin=request.headers.get('Origin')
        if origin and origin.rstrip('/')!=request.host_url.rstrip('/'):abort(403)
        if request.headers.get('Sec-Fetch-Site')=='cross-site':abort(403)
        token=request.headers.get('X-Listener-CSRF','')
        if not token or not hmac.compare_digest(token,session['listener_csrf']):abort(400)
        data=request.get_json(silent=True)
        if not isinstance(data,dict):abort(400)
        try:
            # Serialize station feedback writes for uniqueness, revision checks, and rate limits.
            db.session.query(Station.id).filter_by(id=station.id).with_for_update().first()
            row=query.populate_existing().first()
            value=data.get('value')
            if type(value) is not int or value not in (-1,0,1):raise ValueError('Choose thumbs up, thumbs down, or remove vote')
            comment=service.clean_text(data.get('comment',row.comment if row else ''),500,multiline=True)
            if comment and value==0 and comment!=(row.comment if row else ''):raise ValueError('Choose a vote before adding a comment')
            if not config['comments_enabled'] and comment!=(row.comment if row else ''):raise ValueError('Comments are disabled')
            if row and row.value==value and row.comment==comment:
                pass  # Idempotent retries do not add events or consume the limit.
            else:
                if type(data.get('revision')) is not int or data['revision']!=(row.revision if row else 0):
                    return jsonify(error='Your vote changed in another window. Reopen feedback.'),409
                count=ListenerFeedbackEvent.query.filter_by(station_id=station.id,listener_key=key).filter(ListenerFeedbackEvent.created_at>now-timedelta(minutes=1)).count()
                network_key=hmac.new(current_app.secret_key.encode(),
                    (now.date().isoformat()+':'+(request.remote_addr or 'unknown')).encode(),hashlib.sha256).hexdigest()
                network_count=ListenerFeedbackEvent.query.filter_by(station_id=station.id,listener_key=network_key,action='rate').filter(ListenerFeedbackEvent.created_at>now-timedelta(minutes=1)).count()
                if count>=20 or network_count>=120:return jsonify(error='Please wait a minute before sending more feedback.'),429
                row=row or ListenerVote(station_id=station.id,track_id=decision.track_id,listener_key=key,revision=0)
                if row.comment!=comment:row.review_state='new'
                row.value=value;row.comment=comment;row.decision_id=decision_id;row.revision+=1;row.updated_at=now
                db.session.add(row)
                db.session.add(ListenerFeedbackEvent(station_id=station.id,listener_key=key,track_id=decision.track_id,action='vote',value=value))
                db.session.add(ListenerFeedbackEvent(station_id=station.id,listener_key=network_key,track_id=decision.track_id,action='rate',value=0))
                db.session.commit()
        except IntegrityError:
            db.session.rollback();return jsonify(error='Your vote changed. Reopen feedback.'),409
        except (ValueError,TypeError) as exc:
            db.session.rollback();return jsonify(error=str(exc)),400
    else:row=query.first()
    totals=service.vote_stats(station.id,[decision.track_id]).get(decision.track_id,service.EMPTY_STATS) if config['public_totals'] else None
    # Comments are returned only to their author, never in the public totals.
    response=jsonify(vote=vote_data(row),csrf=session['listener_csrf'],totals={k:v for k,v in totals.items() if k!='comments'} if totals else None)
    response.headers['Cache-Control']='private, no-store'
    return response


@player_experience.route('/admin/stations/<slug>/listener-feedback',methods=['GET','POST'])
@admin_required
def inbox(slug):
    station=station_or_404(request.args.get('station',slug) if request.method=='GET' else slug,require_enabled=False)
    if station.slug!=slug:return redirect(url_for('.inbox',slug=station.slug))
    if request.method=='POST':
        require_csrf()
        db.session.query(Station.id).filter_by(id=station.id).with_for_update().first()
        row=ListenerVote.query.filter_by(id=request.form.get('id'),station_id=station.id).with_for_update().first_or_404()
        action=request.form.get('action')
        if request.form.get('revision')!=str(row.revision):
            flash('Feedback changed. Review the latest version before updating.','error')
        elif action not in ('reviewed','spam','exclude','restore','delete-comment'):abort(400)
        else:
            try:reason=service.clean_text(request.form.get('reason',''),200)
            except ValueError as exc:
                flash(str(exc),'error');return redirect(url_for('.inbox',slug=slug))
            if action=='exclude' and not reason:
                flash('Add a reason before excluding a vote.','error')
                return redirect(url_for('.inbox',slug=slug))
            if action in ('reviewed','spam'):row.review_state=action
            elif action=='delete-comment':row.comment='';row.review_state='reviewed'
            else:row.excluded=action=='exclude'
            row.revision+=1
            audit('listener_feedback_'+action,user_id=current_admin().id,station_id=station.id,target_type='listener_vote',target_id=row.id,summary=reason)
            db.session.commit();flash('Feedback updated.','success')
        return redirect(url_for('.inbox',slug=slug))
    query=ListenerVote.query.filter_by(station_id=station.id)
    track=request.args.get('track')
    if track:
        query=query.join(ListenerVote.track).filter_by(uuid=track)
    try:page=max(1,int(request.args.get('page','1')))
    except ValueError:abort(400)
    total=query.count()
    rows=query.order_by(ListenerVote.updated_at.desc(),ListenerVote.id.desc()).offset((page-1)*50).limit(50).all()
    return render_template('admin/listener_feedback.html',selected=station,stations=admin_stations(),page='listener-feedback',
                           rows=rows,number=page,more=page*50<total,track_filter=track or '')


@player_experience.cli.command('refresh-public-schedules')
def refresh_command():
    """Publish rolling public listings and expire old private feedback text."""
    import click
    results=service.refresh_public_schedules()
    click.echo(f'Refreshed {sum(ok for _,ok in results)} stations; {sum(not ok for _,ok in results)} failures.')
    if any(not ok for _,ok in results):raise click.ClickException('Some stations retained their previous publication; see service logs')


@player_experience.get('/station-assets/<slug>/song/<int:decision_id>.png')
def artwork(slug,decision_id):
    from app.models import MusicArtwork
    station=public_station(slug)
    row=SelectionDecision.query.filter_by(id=decision_id,station_id=station.id,status='started').filter(
        SelectionDecision.started_at>=datetime.now(timezone.utc)-timedelta(hours=24)).first_or_404()
    song=row.track
    if not song or song.deleted_at:abort(404)
    identifier=song.cover_id or (song.catalog_album.cover_id if song.catalog_album else None)
    art=db.session.get(MusicArtwork,identifier) if identifier else None
    if not art:abort(404)
    response=Response(art.image,mimetype='image/png')
    response.set_etag(hashlib.sha256(art.image).hexdigest())
    response.headers['Cache-Control']='public, max-age=300'
    return response.make_conditional(request)
