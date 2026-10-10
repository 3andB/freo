"""Display campaign policy and convenience audio links. Never schedules playback."""
import random
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from app.extensions import db
from app.models import Campaign, Track, MediaIngestJob
from app.services import player, polish

SURFACES = ('homepage', 'player', 'visualizer')
DEFAULTS = dict(active=True, start='', end='', priority=100, weight=1, placement='top',
    surfaces=[], source='image', destination='', label='', unit='', iframe='',
    desktop_size='728x90', mobile_size='320x50', audio_track_id=None, audio_job_id=None)


def settings(campaign):
    return dict(DEFAULTS, **(campaign.advertising or {'active': False, 'priority': campaign.priority}))


def status(config, now=None):
    now = now or datetime.now(timezone.utc)
    if config.get('deleted') or not config.get('active'): return 'Disabled'
    start, end = player.timestamp(config.get('start', '')), player.timestamp(config.get('end', ''))
    if end and now >= end: return 'Expired'
    if start and now < start: return 'Scheduled'
    return 'Active'


def timestamp(value, station):
    if not value: return ''
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        from app.services.schedule import _wall_to_utc
        parsed = _wall_to_utc(parsed, ZoneInfo(station.timezone))
    return parsed.astimezone(timezone.utc).isoformat()


def validate(form, station, previous=None):
    value = dict(DEFAULTS, **(previous or {}))
    value.update(active=form.get('active') == 'yes', start=timestamp(form.get('start', ''), station),
        end=timestamp(form.get('end', ''), station), priority=int(form.get('priority', '100')),
        weight=int(form.get('weight', '1')), placement=form.get('placement', 'top'),
        surfaces=form.getlist('surfaces'), destination=player.safe_url(form.get('destination', '')),
        label=player.clean_text(form.get('label', ''), 200))
    if not -2147483648 <= value['priority'] <= 2147483647: raise ValueError('Priority is out of range')
    if not 1 <= value['weight'] <= 1000000: raise ValueError('Weight must be between 1 and 1000000')
    if value['placement'] not in ('top', 'bottom') or any(s not in SURFACES for s in value['surfaces']):
        raise ValueError('Choose a supported surface and placement')
    if value['start'] and value['end'] and player.timestamp(value['start']) >= player.timestamp(value['end']):
        raise ValueError('End time must follow start time')
    prefix = 'ad_' + value['placement']
    network = polish.validate_config({prefix+'_'+key: form.get(key, DEFAULTS[key])
        for key in ('source', 'unit', 'iframe', 'desktop_size', 'mobile_size')})
    for key in ('source', 'unit', 'iframe', 'desktop_size', 'mobile_size'): value[key] = network[prefix+'_'+key]
    if value['surfaces']:
        if value['source'] == 'image' and not value['destination']: raise ValueError('Add a destination URL for display images')
        if value['source'] == 'google' and not value['unit']: raise ValueError('Add a Google ad-unit path')
        if value['source'] == 'iframe' and not value['iframe']: raise ValueError('Add an HTTPS adapter URL')
    return value


def audio_link(campaign):
    config = settings(campaign)
    job = db.session.get(MediaIngestJob, config.get('audio_job_id')) if config.get('audio_job_id') else None
    if job and job.station_id != campaign.station_id: job = None
    identifier = job.track_id if job else config.get('audio_track_id')
    if not campaign.advertising or not any(key in campaign.advertising for key in ('audio_track_id', 'audio_job_id')):
        creative = next((c for c in campaign.creatives if c.track_id), None)
        identifier = creative.track_id if creative else None
    track = db.session.get(Track, identifier) if identifier else None
    if track and (track.station_id != campaign.station_id or track.deleted_at or track.audio_kind != 'COMMERCIALS'): track = None
    return track, job


def payload(campaign, config):
    source = config['source']
    result = dict(source=source, label=config['label'] or 'Advertisement', destination=config['destination'],
        variants={}, campaign_id=campaign.id, end=config['end'])
    prefix = 'ad_' + config['placement']
    if source == 'image':
        if not player.safe_url(config['destination']): return None
        for asset in campaign.display_assets:
            if (asset.width, asset.height) not in polish.sizes(prefix, asset.device == 'mobile'): continue
            result['variants'][asset.device] = dict(width=asset.width, height=asset.height,
                url=polish.asset_url('advertising.asset', slug=campaign.station.slug, campaign_id=campaign.id,
                    device=asset.device, v=asset.version))
        if not result['variants']: return None
    elif source in ('google', 'iframe'):
        validated = polish.validate_config({prefix+'_'+key: config[key] for key in
            ('source', 'unit', 'iframe', 'desktop_size', 'mobile_size')})
        if not config['unit' if source == 'google' else 'iframe']: return None
        result.update(unit=config['unit'], iframe=config['iframe'])
        for device in ('desktop', 'mobile'):
            result['variants'][device] = dict(zip(('width', 'height'), map(int, validated[prefix+'_'+device+'_size'].split('x'))))
    else: return None
    return result


def select(station, surface, placement, now=None, rng=None, current=None):
    if surface not in SURFACES or placement not in ('top', 'bottom'): raise ValueError('Invalid advertising location')
    candidates = []
    for campaign in Campaign.query.filter_by(station_id=station.id).filter(Campaign.advertising.isnot(None)).order_by(Campaign.id):
        config = settings(campaign)
        try:
            if status(config, now) != 'Active' or surface not in config['surfaces'] or config['placement'] != placement: continue
            creative = payload(campaign, config)
            if creative: candidates.append((campaign.id, config, creative))
        except (ValueError, TypeError, KeyError):
            continue  # An invalid optional advertisement cannot break a public page.
    if not candidates: return None
    priority = max(c[1]['priority'] for c in candidates)
    candidates = [c for c in candidates if c[1]['priority'] == priority]
    # Revalidation keeps a still-eligible creative; it is not an impression rotation.
    existing = next((c for c in candidates if str(c[0]) == str(current)), None)
    chosen = existing or (rng or random).choices(candidates, weights=[c[1]['weight'] for c in candidates], k=1)[0]
    return chosen[2]


def context(station, surface='player'):
    return {key: value for placement in ('top', 'bottom')
        if (value := select(station, surface, placement)) is not None
        for key in ('ad_'+placement,)}
