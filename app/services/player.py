"""Public presentation and schedule publication; never commands the audio engine."""
from copy import deepcopy
from datetime import date, datetime, time, timedelta, timezone
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo
import hashlib

from sqlalchemy import case, func
from app.extensions import db
from app.models import (StationPlayerSettings, StationPlayerAsset, PublicScheduleRevision,
                        ListenerVote, LiveQueueSnapshot, SelectionDecision)
from app.services.schedule import resolve, _wall_to_utc

PLATFORMS = ('Instagram', 'Facebook', 'TikTok', 'YouTube', 'X', 'SoundCloud', 'Mixcloud', 'Discord', 'Website')
ASSETS = ('cover', 'ad_top', 'ad_bottom', 'ad_top_mobile', 'ad_bottom_mobile')
DEFAULTS = dict(message='', message_enabled=False, message_start='', message_end='',
    social_enabled=False, socials=[], palette='aurora', motion=True, cover_position='center',
    schedule_enabled=False, schedule_mode='automatic', schedule_views=['day','week','month'],
    schedule_default='week', auto_publish=False, custom_entries=[],
    voting_enabled=False, comments_enabled=False, public_totals=False,
    ad_top_enabled=False, ad_top_url='', ad_top_alt='', ad_top_start='', ad_top_end='',
    ad_bottom_enabled=False, ad_bottom_url='', ad_bottom_alt='', ad_bottom_start='', ad_bottom_end='')


def clean_text(value, limit, required=False, multiline=False):
    if not isinstance(value,str):
        raise ValueError('Enter text for this field')
    value=''.join(char for char in value.strip() if char.isprintable() or (multiline and char in '\n\t'))
    if len(value)>limit or (required and not value):
        raise ValueError(f'Enter a valid value of at most {limit} characters')
    return value


def settings(station):
    return dict(deepcopy(DEFAULTS), **(station.player_settings.config if station.player_settings else {}))


def safe_url(value):
    value = clean_text(value, 1000)
    if not value:
        return ''
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in ('https','http') or not parsed.hostname or parsed.username or parsed.password or any(ord(c) < 33 for c in value):
            raise ValueError()
        parsed.port
    except ValueError:
        raise ValueError('Links must be complete http:// or https:// URLs without credentials')
    return value


def timestamp(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
        if not parsed.tzinfo:
            raise ValueError()
        return parsed.astimezone(timezone.utc)
    except (ValueError, TypeError):
        raise ValueError('Enter an ISO date/time with timezone, for example 2026-09-16T09:00+08:00')


def active(config, prefix, now=None):
    now = now or datetime.now(timezone.utc)
    start, end = timestamp(config.get(prefix+'_start')), timestamp(config.get(prefix+'_end'))
    return config.get(prefix+'_enabled', False) and (not start or now >= start) and (not end or now < end)


def validate_config(form):
    result = deepcopy(DEFAULTS)
    for key in DEFAULTS:
        if isinstance(DEFAULTS[key], bool):
            result[key] = form.get(key) == 'yes'
    result['message'] = clean_text(form.get('message',''),1000,multiline=True)
    for key, choices in [('palette',('aurora','sunset','ocean')),('cover_position',('top','center','bottom')),
                         ('schedule_mode',('automatic','custom','combined')),('schedule_default',('day','week','month'))]:
        result[key] = form.get(key, DEFAULTS[key])
        if result[key] not in choices:
            raise ValueError('Choose a valid '+key.replace('_',' '))
    views = form.getlist('schedule_views')
    if not views or any(x not in ('day','week','month') for x in views):
        raise ValueError('Choose at least one schedule view')
    result['schedule_views'] = list(dict.fromkeys(views))
    if result['schedule_default'] not in views:
        raise ValueError('The default schedule view must be enabled')
    for prefix in ('message','ad_top','ad_bottom'):
        for suffix in ('start','end'):
            key = prefix+'_'+suffix
            result[key] = clean_text(form.get(key,''),40)
        start, end = timestamp(result[prefix+'_start']), timestamp(result[prefix+'_end'])
        if start and end and start >= end:
            raise ValueError('End time must follow start time')
    for prefix in ('ad_top','ad_bottom'):
        result[prefix+'_url'] = safe_url(form.get(prefix+'_url',''))
        result[prefix+'_alt'] = clean_text(form.get(prefix+'_alt',''),200)
        if result[prefix+'_enabled'] and not result[prefix+'_alt']:
            raise ValueError('Add an accessible description for each enabled advertisement')
    for platform in PLATFORMS:
        url = safe_url(form.get('social_'+platform,''))
        if url:
            result['socials'].append(dict(platform=platform,url=url,visible=form.get('visible_'+platform)=='yes'))
    return result


def public_context(station, config=None):
    config = deepcopy(config or settings(station))
    config['message_version']=hashlib.sha256((config['message']+config['message_start']+config['message_end']).encode()).hexdigest()[:16]
    config['message_visible'] = active(config,'message') and bool(config['message'])
    assets = {row.kind:row.version for row in StationPlayerAsset.query.filter_by(station_id=station.id).all()}
    for prefix in ('ad_top','ad_bottom'):
        config[prefix+'_visible'] = active(config,prefix) and prefix in assets
    config['socials'] = [x for x in config['socials'] if x.get('visible')] if config['social_enabled'] else []
    return dict(player_config=config, player_assets=assets,
                player_revision=station.player_settings.revision if station.player_settings else 0)


def automatic_entries(station, start_day, days=31):
    zone = ZoneInfo(station.timezone)
    point = _wall_to_utc(datetime.combine(start_day,time()),zone)
    end = _wall_to_utc(datetime.combine(start_day+timedelta(days=days),time()),zone)
    output=[]
    # Bounded by a publication horizon and a defensive transition cap.
    while point < end:
        if len(output) >= 4096:
            raise ValueError('Too many schedule transitions to publish')
        resolution=resolve(station,point)
        finish=min(resolution.next_transition or end,end)
        if finish <= point:
            raise ValueError('Schedule transition did not advance')
        clock=resolution.clock
        sources=[slot for slot in clock.slots if slot.enabled] if clock else []
        target=None
        if len(sources)==1:
            target=sources[0].category or sources[0].playlist
        title=target.name if target else resolution.program.name if resolution.program else clock.name if clock else 'Station mix'
        if resolution.visual is not None:
            title=resolution.visual['label']
        output.append(dict(start=point.isoformat(),end=finish.isoformat(),title=title,
                           description='',source=resolution.visual['mode'].lower() if resolution.visual is not None and not resolution.visual['reason'] else 'automatic' if clock else 'fallback'))
        point=finish
    return output


def custom_entry(form):
    from app.services.calendar import minute
    title=clean_text(form.get('title',''),120,True)
    description=clean_text(form.get('description',''),500,multiline=True)
    begin,finish=minute(form.get('start','')),minute(form.get('end',''))
    if begin==1440:raise ValueError('Start before midnight')
    if finish<=begin:finish+=1440
    on_date=form.get('on_date','')
    weekday=form.get('weekday','')
    if on_date:
        on_date=date.fromisoformat(on_date).isoformat()
        weekday=None
    else:
        weekday=int(weekday)
        if weekday not in range(7):raise ValueError('Choose a weekday or date')
    return dict(title=title,description=description,start_minute=begin,end_minute=finish,
                on_date=on_date,weekday=weekday,hidden=form.get('hidden')=='yes')


def build_schedule(station, config, start_day=None, days=31):
    start_day=start_day or datetime.now(ZoneInfo(station.timezone)).date()
    zone=ZoneInfo(station.timezone)
    start=_wall_to_utc(datetime.combine(start_day,time()),zone)
    end=_wall_to_utc(datetime.combine(start_day+timedelta(days=days),time()),zone)
    output=automatic_entries(station,start_day,days) if config['schedule_mode']!='custom' else []
    custom=[]
    for item in config.get('custom_entries',[]):
        for offset in range(-1,days):
            day=start_day+timedelta(days=offset)
            if (day.isoformat()!=item['on_date']) if item['on_date'] else (day.weekday()!=item['weekday']):continue
            midnight=datetime.combine(day,time())
            begin=_wall_to_utc(midnight+timedelta(minutes=item['start_minute']),zone)
            finish=_wall_to_utc(midnight+timedelta(minutes=item['end_minute']),zone)
            begin,finish=max(begin,start),min(finish,end)
            if begin>=finish:continue
            custom.append(dict(start=begin.isoformat(),end=finish.isoformat(),title=item['title'],
                               description=item['description'],source='custom',hidden=item.get('hidden',False),dated=bool(item['on_date'])))
    if config['schedule_mode']=='automatic':custom=[]
    # Dated entries override weekly entries; ambiguous overlaps at equal priority fail.
    custom.sort(key=lambda row:(row['dated'],row['start']))
    for index,row in enumerate(custom):
        a,b=timestamp(row['start']),timestamp(row['end'])
        if any(other['dated']==row['dated'] and timestamp(other['start'])<b and timestamp(other['end'])>a for other in custom[:index]):
            raise ValueError('Custom listings overlap. Use a dated entry to override the recurring week.')
        trimmed=[]
        for old in output:
            c,d=timestamp(old['start']),timestamp(old['end'])
            if c>=b or d<=a:trimmed.append(old);continue
            if c<a:trimmed.append(dict(old,end=a.isoformat()))
            if d>b:trimmed.append(dict(old,start=b.isoformat()))
        output=trimmed+[row]
    return sorted([{k:v for k,v in row.items() if k not in ('hidden','dated')} for row in output if not row.get('hidden')],key=lambda row:row['start'])


def publish(station, config=None, only_if_changed=False):
    config=config or settings(station)
    start=datetime.now(ZoneInfo(station.timezone)).date()
    entries=build_schedule(station,config,start)
    if only_if_changed:
        last=PublicScheduleRevision.query.filter_by(station_id=station.id).order_by(PublicScheduleRevision.id.desc()).first()
        if last and last.start_date==start and last.entries==entries:
            return last
    row=PublicScheduleRevision(station_id=station.id,entries=entries,
        config_revision=station.player_settings.revision if station.player_settings else 0,
        start_date=start,end_date=start+timedelta(days=31))
    db.session.add(row)
    return row


def vote_stats(station_id, track_ids=None):
    query=db.session.query(ListenerVote.track_id,
        func.sum(case((ListenerVote.value==1,1),else_=0)),
        func.sum(case((ListenerVote.value==-1,1),else_=0)),
        func.sum(case((ListenerVote.comment!='',1),else_=0))).filter_by(station_id=station_id,excluded=False)
    if track_ids is not None:query=query.filter(ListenerVote.track_id.in_(track_ids))
    return {identifier:dict(up=up,down=down,total=up+down,net=up-down,
            approval=round(100*up/(up+down)) if up+down else None,comments=comments)
            for identifier,up,down,comments in query.group_by(ListenerVote.track_id).all()}


EMPTY_STATS=dict(up=0,down=0,total=0,net=0,approval=None,comments=0)


def now_playing(station):
    now=datetime.now(timezone.utc)
    snapshot=db.session.get(LiveQueueSnapshot,station.id)
    def fresh(value):return value and 0 <= (now-value.replace(tzinfo=value.tzinfo or timezone.utc)).total_seconds()<15
    reliable=bool(snapshot and fresh(snapshot.observed_at) and not snapshot.error_code)
    mode=station.automation.operator_mode if station.automation else 'AUTO'
    identifiers=[]
    if reliable:
        mixer=snapshot.mixer or {}
        mode=mixer.get('mode',mode)
        if mode=='DJ_BOOTH' and mixer:
            identifiers=[mixer.get(deck+'_id') for deck in ('a','b')
                         if mixer.get(deck+'_playing') and mixer.get('transition',{}).get(deck+'_gain',1)>0]
            if mixer.get('auto_standby') and mixer.get('auto_gain',0)>0:
                identifiers.append(mixer.get('auto_id'))
        elif snapshot.current_decision_id:
            identifiers=[snapshot.current_decision_id]
        if mixer.get('cart_id'):
            cart=SelectionDecision.query.filter_by(id=mixer['cart_id'],station_id=station.id,status='started').first()
            if cart:
                identifiers=[cart.id] if cart.cart_mode=='TAKEOVER' else identifiers+[cart.id]
        identifiers=list(dict.fromkeys(identifier for identifier in identifiers if identifier))
    def item(row):
        from flask import url_for
        art=row.track and (row.track.cover_id or (row.track.catalog_album and row.track.catalog_album.cover_id))
        return dict(freo_track_id=row.track.freo_track_id if row.track else None,
            report_url=url_for('dmca.report', supplied_track_id=row.track.freo_track_id, station_text=station.name) if row.track else None,
            artwork=url_for('player_experience.artwork',slug=station.slug,decision_id=row.id) if art else None, decision_id=row.id,track=row.track.uuid if row.track else None,
            title=row.track.title if row.track else row.imaging_asset.name if row.imaging_asset else 'Station audio',
            artist=row.track.artist if row.track else 'Station imaging',
            started_at=row.started_at.replace(tzinfo=row.started_at.tzinfo or timezone.utc).isoformat(),
            votable=bool(row.track and not row.track.deleted_at and now-row.started_at.replace(tzinfo=row.started_at.tzinfo or timezone.utc)<timedelta(hours=24)))
    current=SelectionDecision.query.filter(SelectionDecision.station_id==station.id,
        SelectionDecision.id.in_(identifiers),SelectionDecision.status=='started',SelectionDecision.started_at.isnot(None)).all() if identifiers else []
    current.sort(key=lambda row:identifiers.index(row.id))
    recent=SelectionDecision.query.filter_by(station_id=station.id,status='started').filter(SelectionDecision.started_at.isnot(None)).order_by(SelectionDecision.started_at.desc(),SelectionDecision.id.desc()).limit(8).all()
    resolution=resolve(station,now)
    publication=PublicScheduleRevision.query.filter_by(station_id=station.id).order_by(PublicScheduleRevision.id.desc()).first() if settings(station)['schedule_enabled'] else None
    next_program=next((entry for entry in publication.entries if timestamp(entry['start'])>now),None) if publication else None
    return dict(next_program=next_program,current=[item(row) for row in current],recent=[item(row) for row in recent],fresh=reliable,
        stream_online=snapshot.broadcast_online if snapshot and fresh(snapshot.broadcast_observed_at) else None,
        mode=mode,observed_at=snapshot.observed_at.isoformat() if snapshot else None,
        timezone=station.timezone,local_date=now.astimezone(ZoneInfo(station.timezone)).date().isoformat(),
        program='Live DJ' if mode=='DJ_BOOTH' else resolution.program.name if resolution.program else resolution.clock.name if resolution.clock else 'Station mix')


def refresh_public_schedules():
    """Called by a separate timer, never on the playout worker's timing path."""
    from app.models import Station, ListenerFeedbackEvent
    from flask import current_app
    results=[]
    identifiers=[row.station_id for row in StationPlayerSettings.query.all()
                 if row.config.get('auto_publish') and row.config.get('schedule_enabled')]
    for identifier in identifiers:
        try:
            station=Station.query.filter_by(id=identifier,enabled=True,deleted_at=None).with_for_update().first()
            if not station:continue
            publish(station,only_if_changed=True)
            db.session.commit()
            results.append((identifier,True))
        except Exception:
            db.session.rollback()
            current_app.logger.exception('Public schedule refresh failed for station=%s; previous publication retained',identifier)
            results.append((identifier,False))
    now=datetime.now(timezone.utc)
    ListenerVote.query.filter(ListenerVote.updated_at<now-timedelta(days=90),ListenerVote.comment!='').update({'comment':''})
    ListenerFeedbackEvent.query.filter(ListenerFeedbackEvent.created_at<now-timedelta(days=30)).delete()
    db.session.commit()
    return results
