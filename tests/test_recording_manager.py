"""Fake-account acceptance tests: real creation/login, access matrix and MP3 management."""
import re
import subprocess
from pathlib import Path

import pytest
from app.extensions import db
from app.models import (AdminUser, DJStationAssignment, LiveSession, ShowRecording, Station,
                        StationLogo, StationPlayerAsset, AuditEvent, WebsiteAsset, WebsiteSettings)
from app.services.live_sessions import now
from app.services.recording_manager import process_deletions
from tests.test_web import app

PASSWORD = 'isolated-fake-DJ-password'


def login(app, identity, password=PASSWORD, expected=302):
    client = app.test_client()
    assert client.get('/admin/login').status_code == 200
    with client.session_transaction() as session:
        csrf = session['login_csrf']
    result = client.post('/admin/login', data=dict(csrf=csrf, email=identity, password=password))
    assert result.status_code == expected, result.text
    return client


def token(client):
    with client.session_transaction() as session:
        return session['admin_csrf']


@pytest.fixture
def accounts(app):
    admin = login(app, 'admin@example.test', 'test-password-long-enough')
    definitions = [('alpha', 'Night DJ', ['1'], True), ('peer', 'Peer DJ', ['1'], True),
                   ('beta', 'Second DJ', ['2'], True), ('none', 'Unassigned DJ', [], True),
                   ('disabled', 'Disabled DJ', ['1'], False)]
    for email, name, stations, active in definitions:
        result = admin.post('/admin/djs', data=dict(csrf=token(admin), email=email+'@example.test',
                username=name, password=PASSWORD, station_id=stations, active='yes' if active else 'no'))
        assert result.status_code == 302
    clients = {key: login(app, key+'@example.test') for key in ('alpha', 'peer', 'beta', 'none')}
    clients['admin'] = admin
    return clients


@pytest.fixture
def recording(app, accounts, monkeypatch, tmp_path):
    monkeypatch.setenv('FREO_MEDIA_ROOT', str(tmp_path))
    with app.app_context():
        owner = AdminUser.query.filter_by(email='alpha@example.test').one()
        station = Station.query.filter_by(slug='test-station').one()
        show = LiveSession(station_id=station.id, admin_user_id=owner.id, dj_name=owner.username,
                           started_at=now(), ended_at=now())
        row = ShowRecording(session=show, station_id=station.id, admin_user_id=owner.id,
                            storage_key='a'*32+'.mp3', status='complete', duration_ms=1000,
                            started_at=now(), ended_at=now())
        db.session.add(row); db.session.flush()
        path = tmp_path / station.slug / 'recordings' / row.storage_key
        path.parent.mkdir(parents=True)
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=1',
                        '-codec:a', 'libmp3lame', '-b:a', '192k', str(path)], check=True)
        row.file_size_bytes = path.stat().st_size
        identifier = row.id
        db.session.commit()
    return identifier, path


def test_fake_account_login_and_station_scope(app, accounts):
    alpha = accounts['alpha']
    assert 'DJ Booth' in alpha.get('/admin', follow_redirects=True).text
    assert alpha.get('/admin/stations/test-station/live').status_code == 200
    assert alpha.get('/admin/stations/second-station/live').status_code == 403
    assert accounts['beta'].get('/admin/stations/second-station/live').status_code == 200
    assert accounts['beta'].get('/admin/stations/test-station/live').status_code == 403
    assert 'No stations are assigned' in accounts['none'].get('/admin', follow_redirects=True).text
    assert accounts['none'].get('/admin/stations/test-station/live').status_code == 403
    assert login(app, 'Night DJ').get('/admin/stations/test-station/live').status_code == 200
    login(app, 'disabled@example.test', expected=401)
    login(app, 'alpha@example.test', password='wrong', expected=401)
    with app.app_context():
        owner = AdminUser.query.filter_by(email='alpha@example.test').one()
        owner.active = False; db.session.commit()
    assert alpha.get('/admin/stations/test-station/live').status_code == 302


def concrete_url(rule, slug='test-station'):
    def substitute(match):
        declaration = match.group(1)
        name = declaration.split(':')[-1]
        if name == 'slug': return slug
        return '1' if declaration.startswith('int:') else 'probe'
    return re.sub(r'<([^>]+)>', substitute, rule.rule)


def test_all_restricted_routes_and_unassigned_station_routes(app, accounts):
    from app.services.admin_auth import DJ_ENDPOINTS
    client = accounts['alpha']; anonymous = app.test_client()
    checked = 0
    for rule in app.url_map.iter_rules():
        if not (rule.rule.startswith('/admin') or rule.rule.startswith('/dashboard')):
            continue
        if rule.endpoint == 'web.login': continue
        if rule.endpoint in {'studio_pwa.manifest', 'studio_pwa.worker', 'studio_pwa.offline'}:
            # Installation assets are public and contain no account/station data.
            public = anonymous.get(rule.rule)
            assert public.status_code == 200
            assert client.get(rule.rule).data == public.data
            continue
        if rule.endpoint in DJ_ENDPOINTS and 'slug' not in rule.arguments: continue
        # Allowed station routes must deny an unassigned station, including POST.
        url = concrete_url(rule, 'second-station' if rule.endpoint in DJ_ENDPOINTS else 'test-station')
        for method in sorted(rule.methods - {'OPTIONS', 'HEAD'}):
            response = client.open(url, method=method, data={'csrf': token(client)})
            assert response.status_code == 403, (method, url, rule.endpoint, response.status_code)
            assert anonymous.open(url, method=method).status_code == 302, (method, url)
            checked += 1
    assert checked >= 132
    print(f'Access matrix: {checked} route/method pairs denied for DJ and anonymous sessions')


def test_private_previews_and_public_listener_access(app, accounts):
    with app.app_context():
        station = Station.query.filter_by(slug='second-station').one(); station.enabled = False
        db.session.add(WebsiteSettings(id=1,draft={'hero':'private-draft'},published={}))
        db.session.add(WebsiteAsset(id='private-draft',image=b'private draft',small=b'private small'))
        db.session.add(StationLogo(station_id=station.id, image=b'private', thumbnail=b'private', version='v1'))
        db.session.add(StationPlayerAsset(station_id=station.id, kind='cover', image=b'private', version='v1'))
        db.session.commit()
    for url in ('/website-theme.css?preview=1', '/website-assets/private-draft.png?preview=1',
                '/station-assets/second-station/logo.png', '/station-assets/second-station/player/cover.png'):
        assert accounts['alpha'].get(url).status_code == 404
        assert app.test_client().get(url).status_code == 404
    assert accounts['admin'].get('/website-theme.css?preview=1').status_code == 200
    assert accounts['admin'].get('/website-assets/private-draft.png?preview=1').data == b'private draft'
    assert accounts['admin'].get('/station-assets/second-station/player/cover.png').data == b'private'
    assert accounts['admin'].get('/station-assets/second-station/logo.png').status_code == 200
    assert accounts['beta'].get('/station-assets/second-station/logo.png').status_code == 200
    assert accounts['alpha'].get('/player/test-station').status_code == 200


def test_recording_manager_rename_download_search_and_delete(app, accounts, recording):
    identifier, path = recording; client = accounts['alpha']
    base = f'/admin/stations/test-station/recordings/{identifier}'
    assert identifier in client.get('/admin/stations/test-station/recordings?q=show-'+identifier+'.mp3').text
    assert client.get(base+'/audio').data == path.read_bytes()
    result = client.get(base+'/audio', headers={'Range': 'bytes=0-9'})
    assert result.status_code == 206 and len(result.data) == 10
    assert client.post(base+'/rename', data=dict(csrf=token(client), revision=0, name='Friday Night')).status_code == 303
    result = client.get(base+'/audio?download=1')
    assert 'Friday Night.mp3' in result.headers['Content-Disposition'] and result.mimetype == 'audio/mpeg'
    assert result.headers['Cache-Control'] == 'private, no-store'
    assert path.exists() and path.name == 'a'*32+'.mp3'
    listing = '/admin/stations/test-station/recordings'
    assert 'Friday Night.mp3' in client.get(listing+'?q=Friday&status=complete&sort=size').text
    assert 'No recordings found' in client.get(listing+'?q=absent').text
    assert 'No recordings found' in client.get(listing+'?status=failed').text
    assert client.post(base+'/delete', data=dict(csrf=token(client), revision=1, confirm='yes')).status_code == 303
    assert client.get(base+'/audio').status_code == 404
    assert 'Deletion queued' in client.get(listing).text and path.exists()
    with app.app_context():
        process_deletions()
        assert db.session.get(ShowRecording, identifier).deleted_at
        assert AuditEvent.query.filter_by(action='recording_deleted').count() == 1
        process_deletions()  # idempotent
    assert not path.exists() and 'No recordings found' in client.get(listing).text


def test_recording_actions_reject_idor_csrf_stale_and_unsafe_names(app, accounts, recording):
    identifier, path = recording; base = f'/admin/stations/test-station/recordings/{identifier}'
    for key in ('peer', 'beta', 'none'):
        client = accounts[key]
        for action in ('audio', 'rename', 'delete'):
            result = client.get(base+'/'+action) if action == 'audio' else client.post(base+'/'+action,
                data=dict(csrf=token(client), revision=0, name='Stolen', confirm='yes'))
            assert result.status_code == 403
        assert identifier not in client.get('/admin/stations/test-station/recordings').text
    client = accounts['alpha']
    assert client.post(base+'/rename', data=dict(revision=0, name='No CSRF')).status_code == 400
    assert client.post(base+'/rename', data=dict(csrf=token(client), revision=99, name='Stale')).status_code == 409
    for name in ('../secret', '/tmp/secret', 'a\\b', 'bad\nname', '', 'a'*161):
        assert client.post(base+'/rename', data=dict(csrf=token(client), revision=0, name=name)).status_code == 400
    assert client.post(base+'/delete', data=dict(csrf=token(client), revision=0)).status_code == 400
    assert path.exists()
    with app.app_context():
        row = db.session.get(ShowRecording, identifier); row.status = 'recording'; db.session.commit()
    assert client.post(base+'/delete', data=dict(csrf=token(client), revision=0, confirm='yes')).status_code == 409
    assert client.get(base+'/audio').status_code == 404


@pytest.mark.parametrize('failure', ['revoked', 'symlink', 'missing', 'permissions'])
def test_deletion_rechecks_access_and_handles_storage_failure(app, accounts, recording, monkeypatch, failure):
    identifier, path = recording; client = accounts['alpha']; base = f'/admin/stations/test-station/recordings/{identifier}'
    assert client.post(base+'/delete', data=dict(csrf=token(client), revision=0, confirm='yes')).status_code == 303
    if failure == 'symlink':
        path.unlink(); path.symlink_to(path.parent.parent/'secret')
        (path.parent.parent/'secret').write_text('never delete')
    if failure == 'missing': path.unlink()
    original_unlink = Path.unlink
    if failure == 'permissions':
        monkeypatch.setattr(Path, 'unlink', lambda *a, **k: (_ for _ in ()).throw(PermissionError()))
    with app.app_context():
        if failure == 'revoked':
            user = AdminUser.query.filter_by(email='alpha@example.test').one()
            DJStationAssignment.query.filter_by(admin_user_id=user.id).delete(); db.session.commit()
        process_deletions()
        row = db.session.get(ShowRecording, identifier)
        assert bool(row.deleted_at) == (failure == 'missing')
        if failure != 'missing': assert row.deletion_error and not row.deletion_requested_at
    if failure == 'symlink': assert (path.parent.parent/'secret').read_text() == 'never delete'
    if failure == 'revoked': assert client.get(base+'/audio').status_code == 403 and path.exists()
    if failure == 'permissions':
        monkeypatch.setattr(Path, 'unlink', original_unlink)
        assert client.post(base+'/delete', data=dict(csrf=token(client), revision=2, confirm='yes')).status_code == 303
        with app.app_context():
            process_deletions()
            assert db.session.get(ShowRecording, identifier).deleted_at
        assert not path.exists()


def test_admin_can_manage_other_dj_recordings_and_stale_forms_fail(app, accounts, recording):
    identifier, path = recording; client = accounts['admin']; base = f'/admin/stations/test-station/recordings/{identifier}'
    assert client.post(base+'/rename', data=dict(csrf=token(client), revision=0, name='Administrator edit.mp3')).status_code == 303
    assert accounts['alpha'].post(base+'/delete', data=dict(csrf=token(accounts['alpha']), revision=0, confirm='yes')).status_code == 409
    assert client.get(base+'/audio').status_code == 200


def test_revoked_prepared_microphone_is_not_admitted(app, accounts, monkeypatch):
    from app.services.live_mic import sync_live_mic
    monkeypatch.setattr('app.services.live_mic.enabled', lambda: True)
    commands=[];calls=[]
    monkeypatch.setattr('app.services.playout_queue._command', lambda slug, cmd: commands.append(cmd) or '|IDLE|false')
    with app.app_context():
        user=AdminUser.query.filter_by(email='alpha@example.test').one()
        identifier=user.id
        DJStationAssignment.query.filter_by(admin_user_id=identifier).delete();db.session.commit()
        def gateway(slug, action, **kwargs):
            calls.append(action)
            return dict(token='a'*32, owner=identifier, healthy=True, desired='LIVE', fade=3)
        monkeypatch.setattr('app.services.live_mic.gateway', gateway)
        assert not sync_live_mic(Station.query.filter_by(slug='test-station').one())
    assert calls==['worker','disconnect']
    assert commands==['freo_mic.state']


def test_assignment_revocation_and_deactivation_via_admin_forms(app, accounts):
    admin=accounts['admin'];client=accounts['alpha']
    with app.app_context():
        identifier=AdminUser.query.filter_by(email='alpha@example.test').one().id
    assert admin.post('/admin/djs',data=dict(csrf=token(admin),user_id=identifier,active='yes')).status_code==302
    assert client.get('/admin/stations/test-station/live').status_code==403
    assert admin.post('/admin/djs',data=dict(csrf=token(admin),user_id=identifier,active='yes',station_id='2')).status_code==302
    assert client.get('/admin/stations/second-station/live').status_code==200
    assert client.get('/admin/stations/test-station/live').status_code==403
    cookie=client.get_cookie(app.config['SESSION_COOKIE_NAME']).value
    assert admin.post('/admin/djs',data=dict(csrf=token(admin),user_id=identifier,station_id='2')).status_code==302
    assert client.get('/admin/stations/second-station/live').status_code==302
    login(app,'alpha@example.test',expected=401)

    assert admin.post('/admin/djs',data=dict(csrf=token(admin),user_id=identifier,active='yes',station_id='2')).status_code==302
    replay=app.test_client();replay.set_cookie(app.config['SESSION_COOKIE_NAME'],cookie)
    assert replay.get('/admin/stations/second-station/live').status_code==302
    assert login(app,'alpha@example.test').get('/admin/stations/second-station/live').status_code==200


def test_deleted_recordings_do_not_count_as_missing_storage(app, accounts, recording, tmp_path):
    from app.services.statistics.storage import inventory
    identifier,path=recording
    app.config['FREO_MEDIA_ROOT']=str(tmp_path)
    app.config['FREO_UPLOAD_ROOT']=str(tmp_path/'uploads')
    with app.app_context():
        before=inventory(int(now().timestamp()))
        assert before['recordings']==path.stat().st_size
        row=db.session.get(ShowRecording,identifier)
        row.deleted_at=now();db.session.commit();path.unlink()
        after=inventory(int(now().timestamp()))
        assert after['recordings']==0 and after['missing']==before['missing']


def test_manager_pagination_and_sorting_preserve_filters(app, accounts):
    import uuid
    with app.app_context():
        user=AdminUser.query.filter_by(email='alpha@example.test').one()
        for index in range(35):
            identifier=uuid.uuid4().hex
            show=LiveSession(station_id=1,admin_user_id=user.id,dj_name=user.username)
            db.session.add(ShowRecording(id=identifier,session=show,station_id=1,admin_user_id=user.id,
                storage_key=identifier+'.mp3',name=f'Friday {index:02}.mp3',status='complete',
                duration_ms=1000+index,file_size_bytes=100+index))
        db.session.commit()
    client=accounts['alpha'];base='/admin/stations/test-station/recordings'
    page=client.get(base+'?q=Friday&status=complete&sort=size').text
    assert page.count('data-recording=')==30
    assert page.index('Friday 34.mp3') < page.index('Friday 33.mp3')
    assert 'q=Friday' in page and 'status=complete' in page and 'sort=size' in page
    assert client.get(base+'?q=Friday&status=complete&sort=size&page=2').text.count('data-recording=')==5
    page=client.get(base+'?sort=name').text
    assert page.index('Friday 00.mp3') < page.index('Friday 01.mp3')


def test_download_handles_file_removed_after_validation(app, accounts, recording, monkeypatch):
    def removed(*args,**kwargs):raise FileNotFoundError()
    monkeypatch.setattr('app.routes.dj.send_file',removed)
    identifier,_=recording
    assert accounts['alpha'].get(f'/admin/stations/test-station/recordings/{identifier}/audio').status_code==404
