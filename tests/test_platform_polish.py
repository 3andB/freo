"""Optional presentation, owner boundaries, and explicit stream upgrades."""
from datetime import datetime, timezone
from io import BytesIO
import json

import pytest
from werkzeug.datastructures import MultiDict
from app.extensions import db
from app.models import (AdminUser, Artist, DJStationAssignment, DJStationProfile, LiveSession,
                        LiveQueueSnapshot, Station, StationPlayerAsset, StationPlayerSettings, Track)
from app.services import polish, player
from app.services.stations import create_station
from tests.test_web import app, admin_client
from tests.test_player_experience import config_form, ADMIN, CSRF
from tests.test_station_settings_flags import png


def test_default_192_and_explicit_change_preserves_existing(app):
    client = admin_client(app)
    with app.app_context():
        station = create_station('New radio', 'new-radio')
        assert station.stream.bitrate == 192
        assert Station.query.filter_by(slug='test-station').one().stream.bitrate == 64
    response = client.post('/admin/stations/test-station/settings/audio', data=dict(csrf=CSRF, bitrate='192', revision='1'))
    assert response.status_code == 303
    state = client.get('/admin/stations/test-station/settings/audio').json
    assert state['active']['bitrate'] == 64
    assert state['pending']['bitrate'] == 192


@pytest.mark.parametrize('kind,size,accepted', [
    ('ad_top', (728,90), True), ('ad_top', (970,90), True), ('ad_top_mobile', (320,50), True),
    ('ad_bottom', (300,250), True), ('ad_bottom_mobile', (300,250), True),
    ('ad_top', (300,250), False), ('ad_top_mobile', (728,90), False), ('ad_bottom', (728,91), False)])
def test_creative_dimensions(app, kind, size, accepted):
    from tests.test_advertising import BASE, form
    from app.models import CampaignDisplayAsset
    client = admin_client(app)
    device='mobile' if kind.endswith('_mobile') else 'desktop'
    response=client.post(BASE+'/new',data=form(placement='bottom' if 'bottom' in kind else 'top',
        **{device:(BytesIO(png(*size)),'banner.png')}))
    assert response.status_code == (303 if accepted else 400)
    with app.app_context():
        row=CampaignDisplayAsset.query.first()
        assert bool(row)==accepted
        if row: assert (row.width,row.height)==size
    if not accepted: assert 'Accepted sizes:' in response.text


def test_independent_ads_optional_label_and_inert_admin_preview(app):
    from tests.test_advertising import BASE, form
    client=admin_client(app)
    assert client.post(BASE+'/new',data=form(mobile=(BytesIO(png(320,50)),'mobile.png'))).status_code==303
    public=app.test_client()
    assert public.get('/api/stations/test-station/advertising/player/top').json['ad']['source']=='image'
    assert public.get('/api/stations/test-station/advertising/player/bottom').json['ad'] is None
    assert client.post(BASE+'/new',data=form(source='google',placement='bottom',unit='/1234/station/bottom')).status_code==303
    assert public.get('/api/stations/test-station/advertising/player/bottom').json['ad']['source']=='google'
    preview=client.post(ADMIN,data=config_form(action='preview-player'))
    assert preview.status_code==200 and 'data-placement="ad_bottom"' not in preview.text
    assert 'securepubads.g.doubleclick.net' not in preview.headers['Content-Security-Policy']
    assert 'securepubads.g.doubleclick.net' not in client.get(BASE).headers['Content-Security-Policy']


def test_station_settings_preserves_unrelated_player_configuration(app):
    client = admin_client(app)
    assert client.post(ADMIN, data=config_form(message='Keep this', message_enabled='yes')).status_code == 302
    data = dict(csrf=CSRF, revision=1, action='save-polish', visual_mode='fractal', merch_url='https://example.test/store')
    assert client.post(ADMIN, data=data).status_code == 302
    with app.app_context():
        config = StationPlayerSettings.query.one().config
        assert config['message'] == 'Keep this' and config['message_enabled']
        assert config['visual_mode'] == 'fractal'
    assert 'https://example.test/store' in app.test_client().get('/player/test-station').text
    settings = client.get('/admin/stations/test-station/settings')
    assert settings.status_code == 200 and 'Manage Advertising' in settings.text
    assert 'Desktop Top Banner' not in settings.text


@pytest.mark.parametrize('values', [dict(visual_mode='broken'), dict(merch_url='javascript:alert(1)'),
    dict(ad_top_iframe='http://example.test/ad'), dict(ad_top_unit='<script>'),
    dict(ad_top_mobile_size='728x90')])
def test_invalid_presentation_configuration(app, values):
    assert admin_client(app).post(ADMIN, data=config_form(**values)).status_code == 400


def test_shared_track_source_edits_denied_but_station_categories_allowed(app):
    client = admin_client(app)
    with app.app_context():
        song = Track.query.one(); song.available_to_all = True; song.analysis_status = 'complete'
        db.session.commit(); identifier, numeric = song.uuid, song.id
    other = '/admin/stations/second-station'
    for action in ('disable', 'enable', 'decommission', 'delete', 'process', 'edit'):
        assert client.post(f'{other}/media/{identifier}/{action}', data=dict(csrf=CSRF, confirm=identifier)).status_code == 403
    assert client.post(f'{other}/media/sharing/song/{numeric}', data=dict(csrf=CSRF), headers={'Accept':'application/json'}).status_code == 409
    api = f'/admin/api/stations/second-station/song/{identifier}'
    assert client.post(api, data=dict(csrf=CSRF, data=json.dumps(dict(title='Attack')))).status_code == 403
    assert client.post(api+'/audio', data=dict(csrf=CSRF, data='{}')).status_code == 403
    for action in ('share-all', 'process', 'notes', 'delete'):
        result = client.post(f'/admin/api/stations/second-station/music/actions/{action}',
            data=dict(csrf=CSRF, data=json.dumps(dict(songs=[identifier], confirm=identifier))))
        assert result.status_code == 409
    from app.models import MediaCategory
    from app.services.automation import assign_track
    with app.app_context():
        other_station = Station.query.filter_by(slug='second-station').one()
        category = MediaCategory(station_id=other_station.id, name='Shared rotation', slug='shared')
        db.session.add(category); db.session.flush()
        assign_track(other_station.slug, identifier, category.slug)
        db.session.commit()
        assert Track.query.one().categories[-1].station_id == other_station.id


def link_form(**extra):
    data = MultiDict(dict(csrf=CSRF, **extra))
    for kind, label, url in [('spotify', '', 'https://open.spotify.com/artist/test'),
                             ('merch', 'Artist store', 'https://example.test/store')]:
        data.add('link_kind', kind); data.add('link_label', label); data.add('link_url', url)
    return data


def test_discovery_edit_permissions_public_data_and_escaping(app):
    client = admin_client(app)
    with app.app_context():
        song = Track.query.one(); song.available_to_all = True; identifier = song.id
    path = f'/admin/stations/test-station/discovery/track/{identifier}'
    assert client.post(path, data=link_form()).status_code == 303
    assert client.post(path.replace('test-station', 'second-station'), data=link_form()).status_code == 404
    data = app.test_client().get('/api/stations/test-station/player').json
    assert data['recent'][0]['discovery_links'][0]['label'] == 'Spotify'
    assert 'storage_key' not in str(data)
    invalid = link_form(); invalid.setlist('link_url', ['javascript:alert(1)', 'https://example.test'])
    assert client.post(path, data=invalid).status_code == 400
    with app.app_context():
        song = Track.query.one()
        assert len(song.discovery_links) == 2
        artist = Artist(station_id=song.station_id, name='Artist', normalized_name='artist', discovery_links=song.discovery_links)
        song.catalog_artist = artist; db.session.add(artist); db.session.commit()
        assert len(polish.track_links(song)) == 2
        song.audio_kind = 'STATION'
        assert polish.track_links(song) == []


def test_dj_profiles_station_scope_live_and_revocation(app):
    client = admin_client(app)
    with app.app_context():
        station = Station.query.filter_by(slug='test-station').one()
        other = Station.query.filter_by(slug='second-station').one()
        dj = AdminUser(username='DJ Example', email='private@example.test', password_hash='unused', role='DJ')
        db.session.add(dj); db.session.flush(); user_id = dj.id
        db.session.add_all([DJStationAssignment(admin_user_id=dj.id, station_id=s.id) for s in (station, other)])
        db.session.commit()
    path = '/admin/stations/test-station/dj-profiles'
    data = link_form(user_id=user_id, revision=0, bio='A short <b>bio</b>')
    data['image'] = (BytesIO(png(40,40)), 'dj.png')
    assert client.post(path, data=data).status_code == 303
    assert client.get(path).status_code == 200
    with app.test_request_context():
        station = Station.query.filter_by(slug='test-station').one()
        other = Station.query.filter_by(slug='second-station').one()
        assert polish.dj_profile(other, user_id) is None
        public = polish.dj_profile(station, user_id)
        assert public['bio'] == 'A short <b>bio</b>' and 'private@example.test' not in str(public)
        decision = station.id
        now = datetime.now(timezone.utc)
        from app.models import SelectionDecision
        db.session.add(LiveQueueSnapshot(station_id=station.id, observed_at=now,
            current_decision_id=SelectionDecision.query.one().id,
            show_observation=dict(source='DJ', observed_at=now.isoformat())))
        db.session.add(LiveSession(station_id=station.id, active_station_id=station.id,
                                  admin_user_id=user_id, dj_name='DJ Example', started_at=now))
        db.session.commit()
    state = app.test_client().get('/api/stations/test-station/player').json
    assert state['dj_profile']['name'] == 'DJ Example'
    assert app.test_client().get(public['image']).status_code == 200
    with app.app_context():
        DJStationAssignment.query.filter_by(admin_user_id=user_id, station_id=decision).delete()
        db.session.commit()
    assert app.test_client().get('/api/stations/test-station/player').json['dj_profile'] is None
    assert app.test_client().get(public['image']).status_code == 404


def test_album_reassignment_cannot_change_another_stations_artwork(app):
    from app.models import Album, MusicArtwork
    from app.services.catalog_edit import apply_metadata
    with app.app_context():
        song = Track.query.one()
        artist = Artist(station_id=2, name='Shared artist', normalized_name='shared artist', available_to_all=True)
        db.session.add(artist); db.session.flush()
        album = Album(station_id=2, artist_id=artist.id, title='Shared album', normalized_title='shared album', available_to_all=True)
        artwork = MusicArtwork(id='local-artwork', station_id=1, image=png())
        db.session.add_all([album, artwork]); db.session.commit()
        with pytest.raises(ValueError, match='owning station'):
            apply_metadata(song, dict(artist_id=artist.id, album_id=album.id, cover_id=artwork.id), station_id=1)
        db.session.rollback()
        assert Album.query.one().cover_id is None


def test_schedule_profile_is_resolved_at_read_time_and_hides_account_ids(app):
    from app.models import PublicScheduleRevision
    from datetime import date, timedelta
    client = admin_client(app)
    with app.app_context():
        user = AdminUser(username='Schedule DJ', email='schedule-private@example.test', password_hash='unused', role='DJ')
        db.session.add(user); db.session.flush()
        db.session.add(DJStationAssignment(admin_user_id=user.id, station_id=1))
        db.session.flush()
        db.session.add(DJStationProfile(user_id=user.id, station_id=1, bio='Public schedule bio'))
        user_id = user.id
        station = db.session.get(Station, 1)
        station.player_settings = StationPlayerSettings(config=dict(player.DEFAULTS, schedule_enabled=True), revision=1)
        db.session.add(PublicScheduleRevision(station_id=1, config_revision=1,
            start_date=date.today(), end_date=date.today()+timedelta(days=1), entries=[dict(
                title='Show', start=date.today().isoformat()+'T00:00:00+00:00',
                end=date.today().isoformat()+'T23:59:00+00:00', dj_id=user_id)]))
        db.session.commit()
    path = '/api/stations/test-station/public-schedule?start='+date.today().isoformat()+'&days=1'
    entry = app.test_client().get(path).json['entries'][0]
    assert entry['dj_profile']['bio'] == 'Public schedule bio'
    assert 'dj_id' not in entry and 'schedule-private@example.test' not in str(entry)
    # Saving unchanged account assignments must preserve presentation data.
    assert client.post('/admin/djs', data=MultiDict([('csrf',CSRF),('user_id',str(user_id)),('active','yes'),('station_id','1')])).status_code == 302
    assert app.test_client().get(path).json['entries'][0]['dj_profile'] is not None
    with app.app_context():
        user = db.session.get(AdminUser, user_id); user.active = False; db.session.commit()
    assert app.test_client().get(path).json['entries'][0]['dj_profile'] is None


def test_custom_domain_player_uses_public_ad_policy_and_scopes_dj_images(app):
    from tests.test_station_domains import add
    app.config.update(FREO_DOMAIN_TARGET_HOST='', FREO_DOMAIN_TARGET_IPS='',
                      FREO_INSTALLATION_HOSTS='', PUBLIC_BASE_URL='', FREO_DOMAIN='')
    add(app, verified=True)
    client = app.test_client()
    response = client.get('/', headers={'Host':'rock.example.test'})
    assert response.status_code == 200 and 'player-page' in response.text
    assert 'securepubads.g.doubleclick.net' in response.headers['Content-Security-Policy']
    assert client.get('/station-assets/second-station/dj/1.png', headers={'Host':'rock.example.test'}).status_code == 404
