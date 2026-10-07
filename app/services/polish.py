"""Validated optional presentation data. Never controls audio playback."""
import re
import struct
from urllib.parse import urlsplit

from flask import url_for, has_request_context, current_app
from app.extensions import db
from app.models import AdminUser, DJStationAssignment, DJStationProfile, StationPlayerAsset

LINK_KINDS = {'spotify': 'Spotify', 'apple_music': 'Apple Music', 'purchase': 'Buy music',
              'website': 'Website', 'albums': 'Albums / music', 'social': 'Social profile',
              'merch': 'Merch'}
VISUAL_MODES = ('fractal', 'spectrum', 'waveform', 'particles', 'ambient', 'aurora', 'ethereal', 'space')
AD_DEFAULTS = dict(merch_url='', visual_mode='ambient')
for _prefix in ('ad_top', 'ad_bottom'):
    AD_DEFAULTS.update({_prefix+'_source': 'image', _prefix+'_unit': '',
        _prefix+'_iframe': '', _prefix+'_desktop_size': '728x90', _prefix+'_mobile_size': '320x50'})


def links(value):
    from app.services.player import safe_url, clean_text
    if not isinstance(value, list) or len(value) > 20:
        raise ValueError('Use at most 20 discovery links')
    result = []
    for item in value:
        if not isinstance(item, dict) or item.get('kind') not in LINK_KINDS:
            raise ValueError('Choose a supported link type')
        url = safe_url(item.get('url', ''))
        label = clean_text(item.get('label', ''), 80) or LINK_KINDS[item['kind']]
        if url and url not in {entry['url'] for entry in result}:
            result.append(dict(kind=item['kind'], label=label, url=url))
    return result


def form_links(form):
    kinds, urls, labels = (form.getlist(name) for name in ('link_kind', 'link_url', 'link_label'))
    if len(kinds) != len(urls) or len(urls) != len(labels):
        raise ValueError('Invalid discovery link fields')
    return links([dict(kind=k, url=u, label=l) for k, u, l in zip(kinds, urls, labels) if u.strip()])


def public_links(*values):
    result = []
    for value in values:
        try:
            valid = links(value or [])
        except ValueError:
            continue
        for entry in valid:
            if entry['url'] not in {x['url'] for x in result}:
                result.append(entry)
    return result[:40]


def track_links(track):
    if not track or track.deleted_at or track.audio_kind != 'MUSIC':
        return []
    return public_links(track.discovery_links,
                        track.catalog_artist.discovery_links if track.catalog_artist else [])


def require_owner(row, station_id):
    if row.station_id != station_id:
        raise ValueError('Only the owning station can change this shared source. Open its owning station to edit it.')


def sizes(prefix, mobile=False):
    result = [(320, 50)] if mobile else [(728, 90), (970, 90)]
    if prefix == 'ad_bottom':
        result.append((300, 250))
    return result


def png_size(data):
    if len(data) < 24 or data[:8] != b'\x89PNG\r\n\x1a\n':
        raise ValueError('Invalid decoded image')
    return struct.unpack('>II', data[16:24])


def validate_config(form):
    from app.services.player import safe_url, clean_text
    result = dict(AD_DEFAULTS)
    result['merch_url'] = safe_url(form.get('merch_url', ''))
    result['visual_mode'] = form.get('visual_mode', 'ambient')
    if result['visual_mode'] not in VISUAL_MODES:
        raise ValueError('Choose a valid visual mode')
    for prefix in ('ad_top', 'ad_bottom'):
        source = form.get(prefix+'_source', 'image')
        if source not in ('image', 'google', 'iframe'):
            raise ValueError('Choose image, Google Ad Manager or iframe advertising')
        result[prefix+'_source'] = source
        unit = clean_text(form.get(prefix+'_unit', ''), 200)
        if unit and not re.fullmatch(r'/[0-9]+(?:/[A-Za-z0-9_.-]+)+', unit):
            raise ValueError('Google ad unit must be a path such as /1234567/station/top')
        result[prefix+'_unit'] = unit
        iframe = safe_url(form.get(prefix+'_iframe', ''))
        if iframe and urlsplit(iframe).scheme != 'https':
            raise ValueError('Ad iframe URLs must use HTTPS')
        result[prefix+'_iframe'] = iframe
        for device in ('desktop', 'mobile'):
            key = prefix+'_'+device+'_size'
            size = form.get(key, AD_DEFAULTS[key])
            if size not in [f'{w}x{h}' for w, h in sizes(prefix, device == 'mobile')]:
                raise ValueError('Choose an accepted banner size')
            result[key] = size
    return result


def asset_url(endpoint, **values):
    if has_request_context():
        return url_for(endpoint, **values)
    return current_app.url_map.bind('localhost', script_name=current_app.config.get('APPLICATION_ROOT', '/')).build(endpoint, values)


def ad_context(station, config):
    from app.services.player import active, safe_url
    assets = {row.kind: row for row in StationPlayerAsset.query.filter_by(station_id=station.id)}
    result = {}
    for prefix in ('ad_top', 'ad_bottom'):
        if not active(config, prefix):
            continue
        source = config.get(prefix+'_source', 'image')
        ad = dict(source=source, label=config.get(prefix+'_alt') or 'Advertisement',
                  destination=config.get(prefix+'_url', ''), variants={})
        if source == 'image':
            try:
                if not safe_url(ad['destination']):
                    continue
            except ValueError:
                continue
            for device, kind in [('desktop', prefix), ('mobile', prefix+'_mobile')]:
                row = assets.get(kind)
                if row:
                    try:
                        width, height = (row.width, row.height) if row.width and row.height else png_size(row.image)
                    except ValueError:
                        continue
                    ad['variants'][device] = dict(width=width, height=height,
                        url=asset_url('player_experience.asset', slug=station.slug, kind=kind, v=row.version))
            if not ad['variants']:
                continue
        elif source in ('google', 'iframe'):
            unit, iframe = config.get(prefix+'_unit', ''), config.get(prefix+'_iframe', '')
            if source == 'google' and not re.fullmatch(r'/[0-9]+(?:/[A-Za-z0-9_.-]+)+', unit):
                continue
            if source == 'iframe':
                try:
                    if not iframe or safe_url(iframe) != iframe or urlsplit(iframe).scheme != 'https':
                        continue
                except ValueError:
                    continue
            ad.update(unit=unit, iframe=iframe)
            for device in ('desktop', 'mobile'):
                size = config.get(prefix+'_'+device+'_size', AD_DEFAULTS[prefix+'_'+device+'_size'])
                allowed = [f'{w}x{h}' for w, h in sizes(prefix, device == 'mobile')]
                if size not in allowed:
                    break
                ad['variants'][device] = dict(zip(('width', 'height'), map(int, size.split('x'))))
            if len(ad['variants']) != 2:
                continue
        else:
            continue
        result[prefix] = ad
    return result


def dj_profile(station, user_id):
    if not user_id:
        return None
    user = db.session.get(AdminUser, user_id)
    if not user or not user.active or not db.session.get(DJStationAssignment, (user_id, station.id)):
        return None
    row = db.session.get(DJStationProfile, (user_id, station.id))
    if not row or not (row.bio or row.links or row.image_version):
        return None
    return dict(name=user.username or 'DJ', bio=row.bio, links=public_links(row.links),
        image=url_for('platform_polish.dj_image', slug=station.slug, user_id=user_id,
                      v=row.image_version) if row.image_version else None)


def live_profile(station, reliable):
    from app.services.live_sessions import active_session, describe
    if not reliable:
        return None
    state = describe(station)
    if not state['fresh'] or state['source'] not in ('DJ', 'MIC'):
        return None
    show = active_session(station)
    return dj_profile(station, show.admin_user_id) if show else None
