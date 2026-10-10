"""One station save must preserve drafts, reject stale edits, and commit atomically."""
import re
from app.extensions import db
from app.models import Station
from tests.test_web import app, admin_client
from tests.test_station_settings_flags import settings, BASE


def combined(client, **changes):
    html = client.get(BASE).text
    return settings(combined='yes', settings_token=re.search(r'name="settings_token" value="([^"]+)"',html)[1],
                    revision=re.search(r'name="revision" value="([^"]+)"',html)[1], default_playlist='', **changes)


def test_combined_audio_and_identity_are_atomic(app):
    client = admin_client(app)
    payload = combined(client, bitrate='96', bass='0', mid='0', treble='0')
    invalid = dict(payload, country='bad')
    response = client.post(BASE, data=invalid, headers={'Accept':'application/json'})
    assert response.status_code == 400
    with app.app_context():
        station = Station.query.filter_by(slug='test-station').one()
        assert station.name == 'Test Station'
        assert station.stream.pending_audio is None
    response = client.post(BASE, data=payload, headers={'Accept':'application/json'})
    assert response.status_code == 200, response.json
    with app.app_context():
        station = Station.query.filter_by(slug='test-station').one()
        assert station.name == 'Coast FM'
        assert station.stream.pending_audio['bitrate'] == 96
    stale = client.post(BASE, data=dict(payload, name='Stale tab'), headers={'Accept':'application/json'})
    assert stale.status_code == 400 and 'another window' in stale.json['error']
    # Repeating a current save does not enqueue a second restart.
    payload.update(settings_token=response.json['token'], revision=response.json['audio_revision'])
    assert client.post(BASE, data=payload, headers={'Accept':'application/json'}).status_code == 200


def test_invalid_playback_rolls_back_identity_and_audio(app):
    client = admin_client(app)
    payload = combined(client, bitrate='96')
    payload['default_playlist'] = '999999'
    assert client.post(BASE, data=payload, headers={'Accept':'application/json'}).status_code == 400
    with app.app_context():
        station = Station.query.filter_by(slug='test-station').one()
        assert station.name == 'Test Station' and station.stream.pending_audio is None


def test_category_directory_and_music_views(app):
    client = admin_client(app)
    response = client.get('/admin/stations/test-station/categories')
    assert response.status_code == 200
    assert 'category-table' in response.text and 'Used in programming' in response.text
    for view in ('songs', 'artists', 'albums'):
        assert client.get('/admin/stations/test-station/media?view='+view).status_code == 200


def test_library_playlist_summaries_match_without_loading_tracks(app):
    from sqlalchemy import event
    from app.services.playlists import summaries, listing, summary, seed_playlists
    from app.models import PlaylistItem, Track
    with app.app_context():
        seed_playlists(1)
        row=listing(1)[0];song=Track.query.first()
        row.items.append(PlaylistItem(track_id=song.id,position=1))
        db.session.commit()
        expected=[summary(p) for p in listing(1)]
        db.session.remove()
        queries=[]
        def record(*args):queries.append(args[2])
        event.listen(db.engine,'before_cursor_execute',record)
        try:
            assert summaries(1)==expected
            assert len(queries)==1
            assert not any(isinstance(item,Track) for item in db.session.identity_map.values())
        finally:event.remove(db.engine,'before_cursor_execute',record)


def test_import_catalog_allows_music_defaults_but_protects_audio_collections(app):
    import pytest
    from app.services.playlists import seed_playlists, listing
    from app.services.catalog_edit import validate_metadata
    # Validate through the same service used for uploads and edits.
    with app.app_context():
        seed_playlists(1);db.session.commit()
        rows={p.system_key:p for p in listing(1)}
        assert validate_metadata(1,{'playlists':[rows['PLAYLIST_1'].id]})['playlists']==[rows['PLAYLIST_1'].id]
        with pytest.raises(ValueError,match='Audio type'):
            validate_metadata(1,{'playlists':[rows['STATION'].id]})


def test_pending_directory_change_does_not_block_other_settings(app):
    client=admin_client(app)
    with app.app_context():
        station=Station.query.filter_by(slug='test-station').one()
        station.internet_radio_pending=True;station.internet_radio_status='pending'
        db.session.commit()
    payload=combined(client,directory_enabled='yes')
    response=client.post(BASE,data=payload,headers={'Accept':'application/json'})
    assert response.status_code==200,response.json
    with app.app_context():
        station=Station.query.filter_by(slug='test-station').one()
        assert station.name=='Coast FM' and station.internet_radio_pending
