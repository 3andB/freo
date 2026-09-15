"""Confirmed airplay totals preserve selection-time attribution."""
from datetime import datetime, timezone
from app.extensions import db
from app.models import MediaCategory, SelectionDecision, Station, Track
from app.services.automation import playback_started
from tests.test_web import app, admin_client


def test_counts_use_confirmed_starts_and_original_category(app):
    client = admin_client(app)
    with app.app_context():
        track = Track.query.first()
        station = track.station
        category = track.categories[0]
        extra = MediaCategory(station_id=station.id, name='Other', slug='other')
        track.categories.append(extra)
        db.session.add(extra)
        db.session.flush()
        # Membership changes do not rewrite the category credited by history.
        track.categories.remove(category)
        rows = [SelectionDecision(station_id=station.id, track_id=track.id,
                    category_id=extra.id, status=status) for status in ('selected', 'queued', 'failed')]
        manual = SelectionDecision(station_id=station.id, track_id=track.id, status='queued')
        db.session.add_all(rows + [manual])
        second = Station.query.filter_by(slug='second-station').one()
        db.session.add(SelectionDecision(station_id=second.id, track_id=track.id,
            category_id=category.id, status='started', started_at=datetime.now(timezone.utc)))
        db.session.commit()
        assert playback_started(manual.id, station.slug)
        assert not playback_started(manual.id, station.slug)
        uuid, category_id, extra_id = track.uuid, category.id, extra.id
    data = client.get('/admin/api/stations/test-station/music').json
    assert data['songs'][0]['play_count'] == 2
    counts = {row['id']: row['play_count'] for row in data['categories']}
    assert counts == {category_id: 1, extra_id: 0}
    assert client.get(f'/admin/api/stations/test-station/music/{uuid}').json['play_count'] == 2
    assert '2 plays' in client.get(f'/admin/stations/test-station/media/{uuid}').text
    assert '1 plays' in client.get('/admin/stations/test-station/categories/power').text
    assert '1 plays' in client.get('/admin/stations/test-station/categories').text
