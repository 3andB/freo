"""Installation website content, publication and public station data."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import re
from zoneinfo import ZoneInfo

from flask import url_for
from sqlalchemy import func, or_
from sqlalchemy.orm import selectinload

from app.extensions import db
from app.models import (Station, StreamMount, Track, WebsiteSettings, WebsitePublication,
                        WebsiteAsset, StationPlayerAsset, PublicScheduleRevision, SelectionDecision,
                        LiveQueueSnapshot)
from app.services.availability import track_scope
from app.services.player import clean_text, safe_url, timestamp, settings as player_settings

SECTIONS = ('numbers', 'schedule', 'about', 'announcement')
ASSETS = ('hero', 'logo', 'about_image', 'favicon', 'share_image')
TEXT_FIELDS = dict(name=120, tagline=160, intro=600, about=5000, location=150, genre=100,
                   about_heading=160, channels_heading=160, schedule_heading=160,
                   announcement_title=160, announcement=1500, announcement_label=80,
                   contact_email=254, phone=60, copyright=200, seo_title=160, seo_description=300,
                   hero_alt=200, logo_alt=200, about_image_alt=200)
DEFAULTS = dict(name='Your station', tagline='A home for good music.',
    intro='A different rhythm. A fresh discovery. Find your frequency and make yourself at home.',
    about='Music brings us together. This is a place for the songs you love and the ones you haven’t met yet.',
    location='', genre='Independent radio', about_heading='Good music.\nGood company.',
    channels_heading='Find your frequency.', schedule_heading='Coming up on air.',
    announcement_title='', announcement='', announcement_label='Find out more', announcement_url='',
    announcement_start='', announcement_end='', contact_email='', phone='', publish_contact=False,
    copyright='', seo_title='', seo_description='', hero_alt='A sunlit listening room with records and a turntable',
    logo_alt='', about_image_alt='', hero='', logo='', about_image='', favicon='', share_image='',
    focal='center', overlay=45, font='editorial', theme='day', featured='', channel_order=[],
    sections=list(SECTIONS), show_songs=True, show_artists=True, show_channels=True, show_plays=False,
    background='#f5f3ed', surface='#ffffff', text='#242a23', accent='#365b38',
    night_background='#171d19', night_surface='#222b24', night_text='#f5f3ed', night_accent='#c5d5a8',
    socials=[])


def channels():
    return (Station.query.join(StreamMount).filter(Station.enabled.is_(True), Station.deleted_at.is_(None),
        Station.lifecycle_state == 'ready', StreamMount.enabled.is_(True))
        .options(selectinload(Station.logo), selectinload(Station.stream), selectinload(Station.player_settings))
        .order_by(Station.name, Station.id).all())


def defaults():
    config = deepcopy(DEFAULTS)
    rows = channels()
    station = next((s for s in rows if s.desired_state == 'running'), rows[0] if rows else None)
    if station:
        config.update(name=station.name, intro=station.description or config['intro'],
                      location=', '.join(filter(None, (station.city, station.region, station.country))),
                      genre=station.genre or config['genre'], featured=str(station.id))
    return config


def config(preview=False):
    row = db.session.get(WebsiteSettings, 1)
    return dict(deepcopy(DEFAULTS), **(row.draft if preview else row.published)) if row else defaults()


def asset_ids(values):
    return {value for key, value in values.items() if (key in ASSETS or re.fullmatch(r'channel_image_[0-9]+', key)) and isinstance(value, str) and value}


def contrast(a, b):
    def luminance(value):
        rgb = [int(value[i:i+2], 16) / 255 for i in (1, 3, 5)]
        rgb = [v/12.92 if v <= .04045 else ((v+.055)/1.055)**2.4 for v in rgb]
        return sum(v*w for v, w in zip(rgb, (.2126, .7152, .0722)))
    x, y = sorted((luminance(a), luminance(b)))
    return (y+.05)/(x+.05)


def validate(form, previous):
    output = deepcopy(previous)
    for field, limit in TEXT_FIELDS.items():
        output[field] = clean_text(form.get(field, ''), limit, required=field in ('name', 'tagline'), multiline=True)
    for key in ('show_songs', 'show_artists', 'show_channels', 'show_plays', 'publish_contact'):
        output[key] = form.get(key) == 'yes'
    for key, choices in dict(focal=('left', 'center', 'right'), font=('editorial', 'modern'), theme=('day', 'night', 'system')).items():
        output[key] = form.get(key, DEFAULTS[key])
        if output[key] not in choices:
            raise ValueError('Choose a valid ' + key)
    for prefix in ('', 'night_'):
        for color in ('background', 'surface', 'text', 'accent'):
            key = prefix + color
            value = form.get(key, DEFAULTS[key])
            if not re.fullmatch(r'#[0-9a-fA-F]{6}', value):
                raise ValueError('Colors must use six-digit hex values')
            output[key] = value.lower()
        for surface in ('background', 'surface'):
            if contrast(output[prefix+'text'], output[prefix+surface]) < 4.5 or contrast(output[prefix+'accent'], output[prefix+surface]) < 4.5:
                raise ValueError('Text and accent colors need at least 4.5:1 contrast against both background and surface colors.')
    try:
        output['overlay'] = int(form.get('overlay', 45))
        if not 35 <= output['overlay'] <= 80:
            raise ValueError()
    except (ValueError, TypeError):
        raise ValueError('Hero shading must be between 35 and 80')
    output['sections'] = form.getlist('sections')
    if len(set(output['sections'])) != len(output['sections']) or any(s not in SECTIONS for s in output['sections']):
        raise ValueError('Choose valid homepage sections')
    eligible = {str(row.id) for row in channels()}
    output['featured'] = form.get('featured', '')
    if output['featured'] and output['featured'] not in eligible:
        raise ValueError('Choose an available featured channel')
    order = form.getlist('channel_order')
    if len(order) != len(set(order)) or any(part not in eligible for part in order):
        raise ValueError('Choose each available channel at most once')
    output['channel_order'] = order
    output['announcement_url'] = safe_url(form.get('announcement_url', ''))
    for key in ('announcement_start', 'announcement_end'):
        output[key] = clean_text(form.get(key, ''), 40)
        timestamp(output[key])
    start, end = (timestamp(output[key]) for key in ('announcement_start', 'announcement_end'))
    if start and end and start >= end:
        raise ValueError('Announcement end must follow its start')
    if output['contact_email'] and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', output['contact_email']):
        raise ValueError('Enter a valid contact email')
    output['socials'] = []
    for index in range(6):
        label = clean_text(form.get(f'social_label_{index}', ''), 40)
        link = safe_url(form.get(f'social_url_{index}', ''))
        if link and not label:
            raise ValueError('Add a label to each social link')
        if link:
            output['socials'].append(dict(label=label, url=link))
    return output


def upload_assets(files, form, values):
    from app.routes.station_settings import decode_logo
    for kind in (*ASSETS, *(f'channel_image_{channel.id}' for channel in channels())):
        upload = files.get(kind)
        remove = form.get('remove_' + kind) == 'yes'
        if upload and upload.filename:
            if remove:
                raise ValueError('Choose replace or remove for each image')
            image, small = decode_logo(upload, output_limit=2000 if kind in ('hero', 'about_image', 'share_image') or kind.startswith('channel_image_') else 512)
            identifier = hashlib.sha256(image).hexdigest()
            if not db.session.get(WebsiteAsset, identifier):
                db.session.add(WebsiteAsset(id=identifier, image=image, small=small))
            values[kind] = identifier
        elif remove:
            values[kind] = ''
    return values


def publish(row, values):
    row.published = deepcopy(values)
    db.session.add(WebsitePublication(config=deepcopy(values)))
    db.session.flush()
    for old in WebsitePublication.query.order_by(WebsitePublication.id.desc()).offset(6).all():
        db.session.delete(old)
    db.session.flush()


def cleanup_assets(row):
    keep = asset_ids(row.draft) | asset_ids(row.published)
    for publication in WebsitePublication.query.all():
        keep |= asset_ids(publication.config)
    query = WebsiteAsset.query
    if keep:
        query = query.filter(WebsiteAsset.id.notin_(keep))
    query.delete(synchronize_session=False)


def image_url(values, kind, preview=False, small=False):
    if values.get(kind):
        return url_for('website.asset', identifier=values[kind], preview=1 if preview else None, small=1 if small else None)
    if kind in ('hero', 'about_image'):
        return url_for('static', filename='station/listening-room' + ('-800' if small else '') + '.webp')
    if kind in ('logo', 'favicon'):
        return url_for('static', filename='station/identity.svg')
    return image_url(values, 'hero', preview)


def presentation(values=None, preview=False):
    values = values or config(preview)
    rows = channels()
    order = values['channel_order']
    rows.sort(key=lambda s: (0 if str(s.id) == values['featured'] else 1,
                            order.index(str(s.id)) if str(s.id) in order else len(order), s.name, s.id))
    ids = [s.id for s in rows]
    covers = dict(db.session.query(StationPlayerAsset.station_id, StationPlayerAsset.version)
                  .filter(StationPlayerAsset.station_id.in_(ids), StationPlayerAsset.kind == 'cover').all()) if ids else {}
    snapshots = {s.station_id: s for s in LiveQueueSnapshot.query.filter(LiveQueueSnapshot.station_id.in_(ids)).all()} if ids else {}
    now = datetime.now(timezone.utc)
    from app.services.station_domains import preferred_url
    cards = []
    for station in rows:
        snapshot = snapshots.get(station.id)
        observed = snapshot.broadcast_observed_at if snapshot else None
        fresh = observed and 0 <= (now-observed.replace(tzinfo=observed.tzinfo or timezone.utc)).total_seconds() < 15
        online = snapshot.broadcast_online if fresh else None
        art = (url_for('player_experience.asset', slug=station.slug, kind='cover', v=covers[station.id]) if station.id in covers else
               url_for('station_settings.logo', slug=station.slug, v=station.logo.version) if station.logo else None)
        if values.get(f'channel_image_{station.id}'):
            art = image_url(values, f'channel_image_{station.id}', preview)
        cards.append(dict(station=station, artwork=art, url=preferred_url(station),
                          status='On air' if online else 'Off air' if online is False else 'Status unavailable',
                          online=online, state_url=url_for('player_experience.public_state', slug=station.public_slug or station.slug)))
    songs = artists = plays = 0
    if ids:
        scope = or_(*(track_scope(identifier) for identifier in ids))
        songs, artists = db.session.query(func.count(Track.id), func.count(func.distinct(Track.artist_id))).filter(
            scope, Track.enabled.is_(True), Track.ingest_status == 'accepted', Track.decommissioned_at.is_(None)).one()
        if values['show_plays']:
            plays = SelectionDecision.query.filter(SelectionDecision.station_id.in_(ids),
                SelectionDecision.status == 'started', SelectionDecision.track_id.isnot(None),
                SelectionDecision.started_at >= now-timedelta(days=30), SelectionDecision.started_at <= now).count()
    metrics = [(songs, 'Songs in the library', 'show_songs'), (artists, 'Artists to discover', 'show_artists'),
               (len(rows), 'Channels to explore', 'show_channels'), (plays, 'Plays in the last 30 days', 'show_plays')]
    metrics = [(number, label) for number, label, key in metrics if values[key]]
    schedule = []
    if 'schedule' in values['sections'] and ids:
        # One latest publication per channel; never query private planner entries.
        latest = db.session.query(func.max(PublicScheduleRevision.id)).filter(
            PublicScheduleRevision.station_id.in_(ids)).group_by(PublicScheduleRevision.station_id)
        publications = {p.station_id: p for p in PublicScheduleRevision.query.filter(PublicScheduleRevision.id.in_(latest)).all()}
        for card in cards:
            station = card['station']
            publication = publications.get(station.id)
            if not publication or not player_settings(station)['schedule_enabled']:
                continue
            for entry in publication.entries:
                begin, end = timestamp(entry['start']), timestamp(entry['end'])
                if end > now and begin < now+timedelta(days=7):
                    local = begin.astimezone(ZoneInfo(station.timezone))
                    schedule.append(dict(title=entry['title'], start=begin, date=local.strftime('%a %d %b'),
                        time=local.strftime('%H:%M'), timezone=station.timezone, channel=station.name,
                        station_id=station.id, url=card['url']+'#schedule-heading'))
        schedule.sort(key=lambda item: item['start'])
        schedule = schedule[:18]
    start, end = timestamp(values['announcement_start']), timestamp(values['announcement_end'])
    announcement_visible = bool(values['announcement_title'] and values['announcement'] and
                                (not start or start <= now) and (not end or now < end))
    return dict(site=values, cards=cards, featured=cards[0] if cards else None, metrics=metrics, schedule=schedule,
                announcement_visible=announcement_visible, preview=preview, year=now.year,
                site_image=lambda kind, small=False: image_url(values, kind, preview, small))
