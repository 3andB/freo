"""Tag lifecycle and single-assignment updates preserve station boundaries."""
from app.extensions import db
from app.models import MusicTag, Station, Track
from app.services.stations import create_station
from app.services.music_tags import STARTER_TAGS
from tests.test_web import app, admin_client
from tests.test_sound_room import action


def test_new_station_starters_and_deleted_tags_stay_deleted(app):
    with app.app_context():
        station = create_station('New Station', 'new-station')
        assert {tag.name for tag in MusicTag.query.filter_by(station_id=station.id)} == set(STARTER_TAGS)
        tag_id = MusicTag.query.filter_by(station_id=station.id, slug='hit').one().id
    client = admin_client(app)
    assert action(client, 'delete-tag', {'id': tag_id}, 'new-station').status_code == 409
    assert action(client, 'delete-tag', {'id': tag_id, 'confirm': tag_id}, 'new-station').status_code == 200
    for _ in range(2):
        assert client.get('/admin/stations/new-station/tags').status_code == 200
        assert len(client.get('/admin/api/stations/new-station/music').json['tags']) == 6


def test_tag_description_edit_delete_and_independent_assignments(app):
    client = admin_client(app)
    assert client.get('/admin/stations/test-station/tags').status_code == 200
    result = action(client, 'create-tag', {'name': 'HIT', 'description': 'Big songs', 'color': '#123456'})
    tag_id = result.json['tag_id']
    catalog = client.get('/admin/api/stations/test-station/music').json
    song = catalog['songs'][0]
    assert catalog['tags'][0]['description'] == 'Big songs'
    other = action(client, 'create-tag', {'name': 'CHILL'}).json['tag_id']
    for target in [tag_id, other, tag_id]:
        assert action(client, 'assign', {'songs': [song['uuid']], 'kind': 'tag', 'target': target, 'operation': 'add'}).status_code == 200
    assert action(client, 'assign', {'songs': [song['uuid']], 'kind': 'tag', 'target': other, 'operation': 'remove'}).status_code == 200
    saved = client.get('/admin/api/stations/test-station/music/' + song['uuid']).json
    assert saved['tags'] == [tag_id] and saved['categories'] == song['categories']
    assert action(client, 'edit-tag', {'id': tag_id, 'name': 'ANTHEM', 'description': 'Sing along'}).status_code == 200
    assert action(client, 'edit-tag', {'id': tag_id, 'name': 'CHILL'}).status_code == 409
    assert action(client, 'edit-tag', {'id': tag_id, 'name': 'ANTHEM', 'description': 'x' * 501}).status_code == 409
    for operation in ['edit-tag', 'delete-tag']:
        assert action(client, operation, {'id': tag_id, 'confirm': tag_id, 'name': 'Foreign'}, 'second-station').status_code == 409
    assert action(client, 'delete-tag', {'id': tag_id, 'confirm': tag_id}).status_code == 200
    saved = client.get('/admin/api/stations/test-station/music/' + song['uuid']).json
    assert not saved['tags'] and saved['categories'] == song['categories']
    assert app.test_client().get('/admin/stations/test-station/tags').status_code == 302
    assert client.post('/admin/api/stations/test-station/music/actions/delete-tag', data={'data': '{}'}).status_code == 400


def test_migration_seeds_existing_stations_without_overwriting_tags(tmp_path):
    import importlib.util
    import sqlalchemy as sa
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    spec = importlib.util.spec_from_file_location('tag_migration', 'migrations/versions/e20a6b7c9012_music_tag_descriptions_and_starters.py')
    migration = importlib.util.module_from_spec(spec);spec.loader.exec_module(migration)
    engine = sa.create_engine('sqlite:///' + str(tmp_path / 'migration.sqlite'))
    with engine.begin() as connection:
        connection.exec_driver_sql('CREATE TABLE stations (id INTEGER PRIMARY KEY)')
        connection.exec_driver_sql('CREATE TABLE music_tags (id INTEGER PRIMARY KEY, station_id INTEGER, name TEXT, slug TEXT, color TEXT)')
        connection.exec_driver_sql('INSERT INTO stations VALUES (1), (2)')
        connection.exec_driver_sql("INSERT INTO music_tags VALUES (1, 1, 'Hit picks', 'hit', '#112233')")
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
        assert connection.exec_driver_sql('SELECT count(*) FROM music_tags').scalar() == 14
        assert connection.exec_driver_sql("SELECT name, color, description FROM music_tags WHERE id=1").one() == ('Hit picks', '#112233', '')
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
        assert connection.exec_driver_sql('SELECT count(*) FROM music_tags').scalar() == 14
