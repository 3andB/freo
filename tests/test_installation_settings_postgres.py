"""Real historical schema -> new schema -> encrypted backup -> isolated restore."""
import wave
import uuid
from psycopg2.extensions import make_dsn, parse_dsn
from sqlalchemy.engine import URL

from freo_ops import recovery
from tests.test_recovery import postgres


def test_upgrade_and_restored_application_preserve_settings_identity_and_audio(postgres, tmp_path, monkeypatch):
    from app import create_app
    from app.extensions import db
    from app.models import Station, Track, AdminUser, SoftwareLicense
    from app.services.installation_settings import get_setting

    target_url, new_database, created = postgres
    source_url = new_database()
    monkeypatch.setenv('FREO_ENV_FILE', '/dev/null')
    params = parse_dsn(source_url)
    source_uri = URL.create('postgresql+psycopg2', username=params['user'],
                           database=params['dbname'], query={'host': params['host']})
    monkeypatch.setenv('DATABASE_URL', source_uri.render_as_string(hide_password=False))
    monkeypatch.setenv('SECRET_KEY', 'isolated-fixture-only')
    monkeypatch.setenv('PUBLIC_BASE_URL', 'https://preserved.example')
    monkeypatch.setenv('FREO_MAX_STATIONS', '11')
    application = create_app('testing')
    runner = application.test_cli_runner()
    result = runner.invoke(args=['db', 'upgrade', 'a71d25b609ef'])
    assert result.exit_code == 0, result.output
    media = tmp_path / 'media'
    originals = media / 'preserved' / 'originals'
    originals.mkdir(parents=True)
    key = 'a' * 32 + '.wav'
    with wave.open(str(originals / key), 'wb') as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(8000)
        stream.writeframes(b'\0\0' * 800)
    original_hash = recovery.digest(originals / key)
    with application.app_context():
        station = Station(name='Keep this station', slug='preserved', timezone='Australia/Perth')
        db.session.add(station)
        db.session.flush()
        station_uuid = station.freo_station_id
        track = Track(station_id=station.id, uuid=str(uuid.uuid4()), title='Original audio', artist='Fixture',
                      original_filename='original.wav', storage_key=key, media_type='wav',
                      duration_ms=100, sample_rate_hz=8000, channels=1,
                      file_size_bytes=(originals / key).stat().st_size,
                      checksum_sha256=original_hash, enabled=False)
        db.session.add(track)
        db.session.commit()
        track_uuid = track.uuid
        public_id = track.freo_track_id
    # An old admin row must be preserved without silently granting root-upgrade access.
    con = recovery.connect(source_url)
    with con, con.cursor() as cursor:
        cursor.execute("INSERT INTO admin_users (email,password_hash,active,created_at) VALUES ('existing@example.test','unchanged-hash',true,now())")
    con.close()
    result = runner.invoke(args=['db', 'upgrade'])
    assert result.exit_code == 0, result.output
    result = runner.invoke(args=['settings', 'import-environment'])
    assert result.exit_code == 0, result.output
    application.config['FREO_MAX_STATIONS'] = 3
    assert runner.invoke(args=['settings', 'import-environment']).exit_code == 0
    assert runner.invoke(args=['db', 'upgrade']).exit_code == 0
    with application.app_context():
        assert AdminUser.query.one().password_hash == 'unchanged-hash'
        assert AdminUser.query.one().installation_admin is False
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        import base64
        from app.services.software_license import activate, signing_bytes
        issuer = Ed25519PrivateKey.generate()
        public_keys = {'fixture': base64.b64encode(issuer.public_key().public_bytes_raw()).decode()}
        application.config['FREO_LICENSE_PUBLIC_KEYS'] = public_keys
        payload = dict(license_id=str(uuid.uuid4()), owner='Restored purchaser', issued_at='2000-01-01T00:00:00+00:00', product='Freo', edition='unlimited', updates='all-future', installations='all-owned', expires=None)
        activate(dict(payload=payload, key_id='fixture', signature=base64.b64encode(issuer.sign(signing_bytes(payload))).decode()))
        assert get_setting('FREO_MAX_STATIONS') == 11
        assert db.session.get(Station, 1).freo_station_id == station_uuid
        db.session.remove()
        db.engine.dispose()
    backup = tmp_path / 'installation.gpg'
    recovery.create(source_url, [media], backup, b'recovery-fixture-passphrase', version='0.2.0', media_root=media)
    report = recovery.restore(backup, b'recovery-fixture-passphrase', target_url, tmp_path / 'restore')
    created.append(report['database'])
    params = parse_dsn(target_url)
    params['dbname'] = report['database']
    monkeypatch.setenv('DATABASE_URL', make_dsn(**params))
    # SQLAlchemy needs a URI, whereas psycopg2 also accepts keyword DSNs.
    restored_uri = URL.create('postgresql+psycopg2', username=params['user'],
                             database=report['database'], query={'host': params['host']})
    monkeypatch.setenv('DATABASE_URL', restored_uri.render_as_string(hide_password=False))
    monkeypatch.setenv('FREO_MEDIA_ROOT', str(tmp_path / 'restore/root-0'))
    restored_app = create_app('testing')
    restored_app.config['FREO_LICENSE_PUBLIC_KEYS'] = public_keys
    with restored_app.app_context():
        from app.services.software_license import status
        assert status()['owner'] == 'Restored purchaser'
        assert status()['expires'] is None
        assert AdminUser.query.one().password_hash == 'unchanged-hash'
        assert AdminUser.query.one().installation_admin is False
        assert get_setting('FREO_MAX_STATIONS') == 11
        assert get_setting('PUBLIC_BASE_URL') == 'https://preserved.example'
        restored_station = Station.query.one()
        restored_track = Track.query.one()
        assert restored_station.freo_station_id == station_uuid
        assert restored_station.timezone == 'Australia/Perth'
        assert restored_track.uuid == track_uuid and restored_track.freo_track_id == public_id
        assert restored_track.enabled is False
        from app.services.media_storage import LocalMediaStorage
        restored_file = LocalMediaStorage().regular_file(restored_station.slug, restored_track.storage_key)
        assert recovery.digest(restored_file) == original_hash
        db.session.remove()
        db.engine.dispose()
    restored_app.config['FREO_REQUIRE_SCHEMA_CHECK'] = True
    assert restored_app.test_client().get('/ready').status_code == 200
    with restored_app.app_context():
        db.session.remove()
        db.engine.dispose()
    from freo_ops.upgrade import verify_preservation
    verify_preservation(source_url, make_dsn(**params))
    connection = recovery.connect(source_url)
    try:
        with connection, connection.cursor() as cursor:
            cursor.execute("ALTER TABLE stations ADD COLUMN future_setting text NOT NULL DEFAULT 'new default'")
            cursor.execute("INSERT INTO audit_events (action,target_type,summary,created_at) VALUES ('fixture','installation','New audit row',now())")
        verify_preservation(source_url, make_dsn(**params))
        with connection, connection.cursor() as cursor:
            cursor.execute("UPDATE stations SET name='Unexpected data replacement'")
    finally:
        connection.close()
    import pytest
    with pytest.raises(recovery.RecoveryError, match='pre-existing records'):
        verify_preservation(source_url, make_dsn(**params))
    (originals / key).write_bytes(b'corrupted original')
    with pytest.raises(recovery.RecoveryError, match='referenced original'):
        recovery.create(source_url, [media], tmp_path / 'must-not-exist.gpg', b'fixture',
                        version='0.2.0', media_root=media)
    assert not (tmp_path / 'must-not-exist.gpg').exists()
