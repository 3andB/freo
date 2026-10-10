"""Identification, private evidence, and reporting boundaries."""
import hashlib
import re
from urllib.parse import parse_qs, urlsplit
import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy import text
from app.extensions import db
from app.models import AuditEvent, DMCACase, Station, Track
from app.services.copyright import new_track_id, normalize_isrc
from tests.test_web import app, admin_client
from tests.test_media import media_app, fixture_audio


def form(client, **changes):
    client.get('/dmca')
    with client.session_transaction() as session:
        token = session['admin_csrf']
    data = dict(csrf=token, station_text='Test Station', copyrighted_work='My recording',
                material_location='Broadcast at noon', claimant_name='Claimant',
                claimant_email='claimant@example.test', signature='Claimant',
                good_faith='yes', authorized='yes')
    data.update(changes)
    return data


def test_hash_original_and_failure_cleanup(media_app, tmp_path, monkeypatch):
    from app.services import media
    app, storage = media_app
    with app.app_context():
        source = fixture_audio(tmp_path)
        track, _ = media.ingest('one', source, storage=storage)
        assert track.checksum_sha256 == hashlib.sha256(source.read_bytes()).hexdigest()
        before = set(storage.station_dir('one').rglob('*'))
        def fail(*args):
            raise OSError('hash failed')
        monkeypatch.setattr(media.hashlib, 'sha256', fail)
        with pytest.raises(OSError, match='hash failed'):
            media.ingest('one', source, storage=storage)
        assert Track.query.count() == 1
        assert set(storage.station_dir('one').rglob('*')) == before


def test_track_ids_unique_permanent_and_collision_retry(app, monkeypatch):
    values = {new_track_id() for _ in range(1000)}
    assert len(values) == 1000
    assert all(re.fullmatch(r'FR-[2-9A-HJ-NP-Z]{4}-[2-9A-HJ-NP-Z]{4}', value) for value in values)
    with app.app_context():
        first = Track.query.first()
        old = first.freo_track_id
        from app.services import copyright
        candidates = iter([old, 'FR-2345-6789'])
        monkeypatch.setattr(copyright, 'new_track_id', lambda: next(candidates))
        second = Track(station_id=first.station_id, uuid='another', title='Second', artist='Artist',
                       original_filename='x.mp3', storage_key='x.mp3', media_type='mp3',
                       duration_ms=10, sample_rate_hz=44100, channels=2, file_size_bytes=10)
        db.session.add(second); db.session.commit()
        assert second.freo_track_id == 'FR-2345-6789'
        first.title = 'New title'; db.session.commit()
        assert first.freo_track_id == old
        first.freo_track_id = 'FR-AAAA-BBBB'
        with pytest.raises(ValueError, match='permanent'):
            db.session.commit()
        db.session.rollback()
        with pytest.raises(IntegrityError):
            db.session.execute(text('UPDATE tracks SET freo_track_id=:value WHERE id=:id'), {'value': old, 'id': second.id})
        db.session.rollback()


@pytest.mark.parametrize('value,expected', [(None,None), ('',None), (' us-ab1-23-45678 ', 'USAB12345678'), ('ABC123DEF456', 'ABC123DEF456')])
def test_isrc_normalization(value, expected):
    assert normalize_isrc(value) == expected


@pytest.mark.parametrize('value', ['short', 'A'*13, 'USAB1234567!', 'é'*12, 123])
def test_isrc_validation(value):
    with pytest.raises(ValueError):
        normalize_isrc(value)


def test_isrc_editor(app):
    client = admin_client(app)
    with app.app_context():
        uuid = Track.query.first().uuid
    # Use the registered catalog editor route rather than an assumed URL.
    with app.test_request_context():
        from flask import url_for
        path = url_for('catalog_editor.song', slug='test-station', identifier=uuid)
    import json
    for value, status in [('us-ab1-23-45678', 200), ('bad', 409), ('', 200)]:
        result = client.post(path, data={'csrf': 'test-admin-csrf-token', 'data': json.dumps({'title': 'Verified Test Track', 'isrc': value})})
        assert result.status_code == status
    with app.app_context():
        assert Track.query.first().isrc is None


def test_submission_resolution_snapshot_and_no_takedown(app):
    client = app.test_client()
    with app.app_context():
        track = Track.query.first(); identifier = track.freo_track_id
        track.isrc = 'USAB12345678'; db.session.commit()
        track_id, station_id = track.id, track.station_id
    result = client.post('/dmca', data=form(client, supplied_track_id=identifier.lower()))
    assert result.status_code == 201
    assert 'DMCA-' in result.text and 'a'*64 not in result.text
    assert result.headers['Cache-Control'] == 'private, no-store'
    assert result.headers['Referrer-Policy'] == 'no-referrer'
    with app.app_context():
        row = DMCACase.query.one()
        assert row.status == 'OPEN' and row.created_at
        assert (row.track_id, row.station_id, row.reported_station_id) == (track_id, station_id, station_id)
        assert row.supplied_track_id == identifier.lower()
        assert row.snapshot['sha256'] == 'a'*64 and row.snapshot['isrc'] == 'USAB12345678'
        track = db.session.get(Track, track_id)
        assert track.enabled and track.deleted_at is None and track.decommissioned_at is None
        assert db.session.get(Station, station_id).enabled
        track.title = 'Changed'; track.artist = 'Changed'; track.isrc = None
        db.session.commit()
        assert row.snapshot['title'] == 'Verified Test Track'
        assert row.snapshot['artist'] == 'Test Artist'
        reference = row.reference
    assert client.get('/admin/dmca').status_code == 302
    assert client.get('/admin/dmca/' + reference).status_code == 302
    assert client.post('/admin/dmca/' + reference + '/status', data={'status': 'ACTIONED'}).status_code == 302
    admin = admin_client(app)
    detail = admin.get('/admin/dmca/' + reference)
    assert detail.status_code == 200 and 'a'*64 in detail.text and 'USAB12345678' in detail.text
    assert admin.get('/admin/dmca').status_code == 200
    assert admin.post('/admin/dmca/' + reference + '/status', data={'status': 'ACTIONED'}).status_code == 400
    assert admin.post('/admin/dmca/' + reference + '/status', data={'csrf':'test-admin-csrf-token','status':'INVALID'}).status_code == 400
    for status in ('REVIEWING', 'ACTIONED', 'REJECTED', 'CLOSED', 'OPEN'):
        assert admin.post('/admin/dmca/' + reference + '/status', data={'csrf':'test-admin-csrf-token','status':status}).status_code == 302
    with app.app_context():
        assert AuditEvent.query.filter_by(action='dmca_status_changed').count() == 5
        assert db.session.get(Track, track_id).enabled


def test_unresolved_optional_id_validation_and_limits(app):
    client = app.test_client()
    assert client.post('/dmca', data={}).status_code == 400
    for changes in ({'claimant_email':'bad'}, {'good_faith':''}, {'authorized':''}, {'station_text':''}, {'signature':''}, {'copyrighted_work':'a'*5001}):
        assert client.post('/dmca', data=form(client, **changes)).status_code == 400
    for identifier in ['', 'FR-XXXX-XXXX', 'supplied unknown identifier']:
        assert client.post('/dmca', data=form(client, supplied_track_id=identifier)).status_code == 201
    with app.app_context():
        assert DMCACase.query.count() == 3
        assert all(row.track_id is None and row.station_id is None for row in DMCACase.query.all())
        assert len({row.reference for row in DMCACase.query.all()}) == 3
    app.config['DMCA_REPORTS_PER_HOUR'] = 3
    other_session = app.test_client()
    result = other_session.post('/dmca', data=form(other_session))
    assert result.status_code == 429 and result.headers['Retry-After'] == '3600'
    assert client.post('/dmca', data={'oversized': 'x'*33000}).status_code == 413


def test_player_prefill_and_public_privacy(app):
    client = app.test_client()
    result = client.get('/api/stations/test-station/player')
    song = result.json['recent'][0]
    assert re.fullmatch(r'FR-\w{4}-\w{4}', song['freo_track_id'])
    query = parse_qs(urlsplit(song['report_url']).query)
    assert query['supplied_track_id'] == [song['freo_track_id']]
    assert query['station_text'] == ['Test Station']
    page = client.get(song['report_url'])
    assert song['freo_track_id'] in page.text and 'Test Station' in page.text
    assert 'copyright-track' in client.get('/player/test-station').text
    for path in ['/api/stations/test-station/player', '/api/stations/test-station/media']:
        body = client.get(path).text
        for secret in ['checksum_sha256', 'sha256', 'claimant', 'dmca_cases', 'a'*64]:
            assert secret not in body
    # Claim text is escaped even when reflected after a validation error.
    response = client.post('/dmca', data=form(client, claimant_name='<script>alert(1)</script>', signature=''))
    assert '<script>alert(1)</script>' not in response.text
    assert '&lt;script&gt;' in response.text


def test_trusted_proxy_and_shared_station_reporting(app):
    app.config['DMCA_TRUSTED_PROXY_IPS'] = ('127.0.0.1',)
    app.config['DMCA_REPORTS_PER_HOUR'] = 1
    client = app.test_client()
    with app.app_context():
        track = Track.query.first(); track.available_to_all = True
        public_id, owner = track.freo_track_id, track.station_id
        second = Station.query.filter_by(slug='second-station').one().id
        db.session.commit()
    for address in ('192.0.2.1', '192.0.2.2'):
        assert client.post('/dmca', data=form(client, supplied_track_id=public_id, station_text='Second Station'),
                           headers={'X-Real-IP': address}).status_code == 201
    assert client.post('/dmca', data=form(client), headers={'X-Real-IP':'192.0.2.1'}).status_code == 429
    with app.app_context():
        for row in DMCACase.query.all():
            assert row.station_id == owner and row.reported_station_id == second
            assert row.snapshot['reported_station_name'] == 'Second Station'
    # An untrusted peer cannot choose another address by supplying proxy headers.
    for expected, spoofed in [(201, '192.0.2.3'), (429, '192.0.2.4')]:
        assert client.post('/dmca', data=form(client), headers={'X-Real-IP':spoofed},
                           environ_overrides={'REMOTE_ADDR':'198.51.100.1'}).status_code == expected


def test_custom_domain_and_unknown_station_prefill(app):
    from app.models import StationDomain
    from datetime import datetime, timezone
    client = app.test_client()
    with app.app_context():
        station = Station.query.first()
        db.session.add(StationDomain(station_id=station.id, hostname='radio.example.test',
            verification_token='a'*64, verified_at=datetime.now(timezone.utc), enabled=True))
        db.session.commit()
        station_id = station.id
    result = client.get('/dmca?station_text=https://radio.example.test/', base_url='https://radio.example.test')
    assert result.status_code == 200
    assert client.post('/dmca', data=form(client, station_text='https://radio.example.test/')).status_code == 201
    assert client.post('/dmca', data=form(client, station_text='https://not-local.example/')).status_code == 201
    with app.app_context():
        rows = DMCACase.query.order_by(DMCACase.id).all()
        assert rows[0].reported_station_id == station_id
        assert rows[1].reported_station_id is None


def test_invalid_embedded_isrc_cleans_up_and_legacy_edit_is_preserved(media_app, tmp_path, monkeypatch):
    from app.services import media
    from app.services.catalog_edit import apply_metadata
    app, storage = media_app
    with app.app_context():
        source = fixture_audio(tmp_path)
        real_probe = media.probe
        def invalid_probe(path):
            result = real_probe(path)
            result['tags']['isrc'] = 'invalid'
            return result
        monkeypatch.setattr(media, 'probe', invalid_probe)
        with pytest.raises(ValueError, match='ISRC'):
            media.ingest('one', source, storage=storage)
        assert Track.query.count() == 0
        assert not list((storage.station_dir('one') / 'originals').iterdir())
        monkeypatch.setattr(media, 'probe', real_probe)
        track, _ = media.ingest('one', source, storage=storage)
        track.isrc = 'legacy'; db.session.commit()
        apply_metadata(track, {'title':'Updated title', 'isrc':'legacy'})
        db.session.commit()
        assert track.isrc == 'legacy'
        with pytest.raises(ValueError, match='ISRC'):
            apply_metadata(track, {'isrc':'bad new value'})
