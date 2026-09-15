"""Starter tags are created only during station setup, never on page reads."""
from app.extensions import db
from app.models import MusicTag

STARTER_TAGS = ('HIT', 'FAVORITE', 'SPONSORED', 'CHILL', 'NIGHT', 'DAY', 'DANCE')


def seed_starter_tags(station_id):
    existing = {tag.slug for tag in MusicTag.query.filter_by(station_id=station_id)}
    for name in STARTER_TAGS:
        if name.lower() not in existing:
            db.session.add(MusicTag(station_id=station_id, name=name, slug=name.lower()))
