"""Station lifecycle contracts; all runtime files and actions are isolated."""
import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from app.extensions import db
from app.models import AdminUser, Station, StationAlias, Track, MediaCategory, SelectionDecision
from app.services.stations import create_station, get_station, request_delete, update_station
from app.services.station_lifecycle import process_station, retry
from app.services import station_runtime as runtime
from tests.test_stations import station_app
from tests.test_web import admin_client

REAL_REMOVE = runtime.remove


@pytest.fixture
def app(station_app, monkeypatch, tmp_path):
    monkeypatch.setattr(runtime, 'ROOT', tmp_path)
    monkeypatch.setattr(runtime, 'require_root', lambda: None)
    monkeypatch.setattr(runtime, 'render', Mock())
    monkeypatch.setattr(runtime, 'remove', Mock())
    monkeypatch.setattr(runtime, 'run_checked', Mock())
    monkeypatch.setattr('app.services.media._prepare_dirs', Mock())
    with station_app.app_context():
        db.session.add(AdminUser(email='admin@example.test', password_hash='unused'))
        db.session.commit()
    return station_app


def test_zero_station_pages_and_worker(app):
    client = admin_client(app)
    for path in ('/', '/stations', '/admin', '/admin/stations', '/admin/media', '/admin/history'):
        assert client.get(path, follow_redirects=True).status_code == 200, path
    assert client.get('/api/stations').json == {'stations': []}
    assert b'Add station' in client.get('/admin').data
    with app.app_context():
        from app.services.station_lifecycle import process_pending
        process_pending()


def test_limit_counts_disabled_and_stopped_and_can_change(app):
    with app.app_context():
        for i in range(3):
            station = create_station(f'Station {i}', f'station-{i}')
            station.enabled = False
            db.session.commit()
        with pytest.raises(ValueError, match='maximum of 3'):
            create_station('Fourth', 'fourth')
        db.session.rollback()
        app.config['FREO_MAX_STATIONS'] = 1
        assert Station.query.count() == 3
        with pytest.raises(ValueError, match='maximum of 1'):
            create_station('Fourth', 'fourth')
        db.session.rollback()
        app.config['FREO_MAX_STATIONS'] = 4
        create_station('Fourth', 'fourth')


def test_create_checks_public_alias_collisions(app):
    with app.app_context():
        station = create_station('First', 'first')
        update_station(station, name='First', description='', public_slug='pretty', timezone_name='UTC', user=AdminUser.query.first())
        update_station(station, name='First', description='', public_slug='prettier', timezone_name='UTC', user=AdminUser.query.first())
        for slug in ('first', 'pretty', 'prettier'):
            with pytest.raises(ValueError, match='already exists'):
                create_station('Collision', slug)
            db.session.rollback()


def test_creation_failure_retry_is_one_station(app, monkeypatch):
    with app.app_context():
        station = create_station('New', 'new', pending=True)
        monkeypatch.setattr(runtime, 'render', Mock(side_effect=RuntimeError('private credentials')))
        with pytest.raises(RuntimeError):
            process_station(station)
        assert station.lifecycle_state == 'create_failed'
        assert 'private credentials' not in station.lifecycle_error
        monkeypatch.setattr(runtime, 'render', Mock())
        retry(station)
        process_station(station)
        assert station.lifecycle_state == 'ready'
        assert Station.query.count() == 1
        assert station.desired_state == 'stopped'


def test_failed_delete_holds_slot_retry_releases_it(app, monkeypatch):
    with app.app_context():
        app.config['FREO_MAX_STATIONS'] = 1
        station = create_station('Only', 'only')
        request_delete(station)
        monkeypatch.setattr(runtime, 'remove', Mock(side_effect=OSError('reload failed')))
        with pytest.raises(OSError):
            process_station(station)
        assert station.lifecycle_state == 'delete_failed'
        with pytest.raises(ValueError, match='maximum'):
            create_station('Next', 'next')
        db.session.rollback()
        monkeypatch.setattr(runtime, 'remove', Mock())
        retry(station)
        process_station(station)
        assert get_station('only') is None
        assert station.deleted_at is not None
        create_station('Next', 'next')
        process_station(station)  # no-op, including after restart
        assert runtime.remove.call_count == 1


def test_delete_last_station_retains_history_and_returns_to_empty(app):
    with app.app_context():
        station = create_station('Only', 'only')
        db.session.add(StationAlias(slug='alias',station_id=station.id))
        db.session.commit()
        request_delete(station)
        process_station(station)
    client = admin_client(app)
    for path in ('/player/only','/player/alias','/listen/alias','/api/stations/only','/admin/stations/only/media'):
        assert client.get(path).status_code == 404, path
    assert client.get('/api/stations').json['stations'] == []
    assert b'No managed stations yet' in client.get('/admin').data
    assert b'Only' not in client.get('/admin/stations').data


def test_browser_creation_deletion_csrf_and_pending_states(app):
    client = admin_client(app)
    url = '/admin/stations/create'
    assert app.test_client().post(url).status_code == 302
    assert client.post(url, data={'name':'One','slug':'one'}).status_code == 400
    form={'csrf':'test-admin-csrf-token','name':'One','slug':'one','timezone':'UTC'}
    assert client.post(url,data=form).status_code == 303
    with app.app_context():
        station=get_station('one')
        assert station.lifecycle_state == 'pending_create'
        process_station(station)
    assert b'Delete station' in client.get('/admin/stations').data
    assert client.post('/admin/stations/one/delete',data={'csrf':form['csrf'],'confirm':'wrong'}).status_code == 303
    with app.app_context(): assert get_station('one').enabled
    assert client.post('/admin/stations/one/delete',data={'csrf':form['csrf'],'confirm':'one'}).status_code == 303
    assert client.get('/admin/stations/one/media').status_code == 404
    assert client.get('/admin').status_code == 200
    with app.app_context(): process_station(get_station('one'))
    assert client.get('/api/stations').json['stations'] == []


def test_scripted_setup_idempotent_json_and_delete(app,monkeypatch):
    runner=app.test_cli_runner()
    args=['station','create','scripted','--name','Scripted','--if-not-exists','--json']
    result=runner.invoke(args=args)
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)['slug']=='scripted'
    assert runner.invoke(args=args).exit_code == 0
    assert runner.invoke(args=['station','create','scripted','--name','Different','--if-not-exists']).exit_code != 0
    with app.app_context(): assert Station.query.count()==1
    assert runner.invoke(args=['station','delete','scripted']).exit_code != 0
    for _ in range(2):
        result=runner.invoke(args=['station','delete','scripted','--yes','--json'])
        assert result.exit_code == 0, result.output
        assert json.loads(result.output)['status']=='deleted'


def test_many_create_delete_cycles_preserve_other_station(app):
    with app.app_context():
        survivor=create_station('Survivor','survivor');survivor.desired_state='running';db.session.commit()
        for i in range(12):
            station=create_station(f'Test {i}',f'test-{i}',pending=True)
            process_station(station);request_delete(station);process_station(station)
            assert get_station('survivor').desired_state=='running'
            assert Station.query.filter_by(deleted_at=None).count()==1
        assert runtime.remove.call_count==12
        assert all(call.args[0].slug!='survivor' for call in runtime.remove.call_args_list)


@pytest.mark.parametrize('failure_at', [0,1,2,3])
def test_runtime_cleanup_failure_can_resume_without_touching_neighbors(app,tmp_path,monkeypatch,failure_at):
    # Exercise the real cleanup with fake system commands and isolated paths.
    module=runtime
    monkeypatch.setattr(module,'ROOT',tmp_path)
    monkeypatch.setattr(module,'PLAYLISTS',tmp_path/'playlists')
    for name in ('SNIPPETS','CONFIGS','SECRETS'):
        parent=tmp_path/name;parent.mkdir()
        monkeypatch.setattr(module,name,parent)
    monkeypatch.setattr(module,'require_root',lambda:None)
    actions=[]
    monkeypatch.setattr(module,'service_action',lambda slug,action: actions.append((slug,action)) or False)
    calls=[]
    def run(args):
        calls.append(args)
        if len(calls)==failure_at+1: raise OSError('injected')
    monkeypatch.setattr(module,'run_checked',run)
    for slug in ('delete-me','survivor'):
        for name,suffix in [('SNIPPETS','.conf'),('CONFIGS','.liq'),('SECRETS','.json')]:
            (getattr(module,name)/(slug+suffix)).write_text('safe test fixture')
    from types import SimpleNamespace
    station=SimpleNamespace(slug='delete-me')
    with pytest.raises(OSError):REAL_REMOVE(station)
    monkeypatch.setattr(module,'run_checked',lambda args:None)
    REAL_REMOVE(station)
    for name,suffix in [('SNIPPETS','.conf'),('CONFIGS','.liq'),('SECRETS','.json')]:
        assert (getattr(module,name)/('survivor'+suffix)).read_text()=='safe test fixture'
        assert not (getattr(module,name)/('delete-me'+suffix)).exists()
    assert all(slug=='delete-me' for slug,action in actions)


def test_delete_requested_during_creation_is_not_overwritten(app,monkeypatch):
    with app.app_context():
        station=create_station('New','new',pending=True)
        def request_during_render(row):
            request_delete(row)
        monkeypatch.setattr(runtime,'render',request_during_render)
        process_station(station)
        assert station.lifecycle_state=='pending_delete' and not station.enabled
        process_station(station)
        assert station.deleted_at


def test_station_deletion_releases_domains_only_after_success(app, monkeypatch):
    from datetime import datetime, timezone
    from app.models import StationDomain
    from app.services.station_domains import add_domain
    with app.app_context():
        station = create_station('Domain owner', 'domain-owner')
        other = create_station('Next owner', 'next-owner')
        row = add_domain(station, 'reusable.example.test')
        row.enabled = True
        row.verified_at = datetime.now(timezone.utc)
        row.is_primary = True
        db.session.commit()
        token = row.verification_token
        request_delete(station, AdminUser.query.first().id)
        monkeypatch.setattr(runtime, 'remove', Mock(side_effect=RuntimeError('retry deletion')))
        with pytest.raises(RuntimeError):
            process_station(station)
        assert StationDomain.query.count() == 1
        monkeypatch.setattr(runtime, 'remove', Mock())
        retry(station)
        process_station(station)
        assert station.deleted_at and StationDomain.query.count() == 0
        replacement = add_domain(other, 'reusable.example.test')
        db.session.commit()
        assert replacement.verification_token != token
        assert not replacement.enabled and replacement.verified_at is None
