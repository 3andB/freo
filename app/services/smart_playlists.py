"""Small, validated AND filter set; lists within a filter match ANY value."""
import random
from app.models import Track, MediaCategory, MusicTag
from app.services.availability import tracks_for

TEXT_FIELDS = ('artist', 'title', 'album', 'genre')
RANGES = {'bpm': (0, 1000), 'release_year': (1, 9999), 'duration_ms': (1, 86400000)}


def validate_rules(value, station_id):
    if not isinstance(value, dict) or set(value) - set(TEXT_FIELDS) - set(RANGES) - {'tags', 'categories'}:
        raise ValueError('Use supported smart playlist filters')
    for key, spec in value.items():
        if key in TEXT_FIELDS:
            if not isinstance(spec, str) or not spec.strip() or len(spec) > 200:
                raise ValueError('Text filters need 1–200 characters')
        elif key in RANGES:
            low, high = RANGES[key]
            if not isinstance(spec, dict) or not spec or set(spec) - {'min', 'max'}:
                raise ValueError('Numeric filters need min and/or max')
            if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not low <= v <= high for v in spec.values()):
                raise ValueError('Numeric filter is out of range')
            if spec.get('min', low) > spec.get('max', high):
                raise ValueError('Minimum must not exceed maximum')
        else:
            if not isinstance(spec, list) or not spec or len(spec) > 100 or any(type(i) is not int or not 1 <= i <= 2147483647 for i in spec):
                raise ValueError('Choose tags or categories')
            model = MusicTag if key == 'tags' else MediaCategory
            if model.query.filter(model.station_id == station_id, model.id.in_(spec)).count() != len(set(spec)):
                raise ValueError('Tag or category is unavailable for this station')
    return value


def validate_weights(value, station_id):
    if not isinstance(value, dict) or set(value) - {'tags', 'categories'}:
        raise ValueError('Weights must specify tags or categories')
    cleaned = {}
    for key, mapping in value.items():
        if not isinstance(mapping, dict) or len(mapping) > 100:
            raise ValueError('Choose up to 100 weights')
        if not mapping:
            continue
        ids = []
        for identifier, weight in mapping.items():
            if not str(identifier).isdecimal() or isinstance(weight, bool) or not isinstance(weight, (float, int)) or not 0 < weight <= 100:
                raise ValueError('Weights must be greater than 0 and at most 100')
            ids.append(int(identifier))
        validate_rules({key: ids}, station_id)
        cleaned[key] = {str(int(i)): w for i, w in mapping.items()}
    return cleaned


def members(row):
    if not row.smart_enabled:
        return [i.track for i in sorted(row.items, key=lambda i: i.position)]
    query = tracks_for(row.station_id).filter_by(audio_kind='MUSIC')
    for key, spec in (row.smart_rules or {}).items():
        if key in TEXT_FIELDS:
            # Literal substring matching, including literal % and _ characters.
            query = query.filter(getattr(Track, key).ilike('%' + spec.strip().replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%', escape='\\'))
        elif key in RANGES:
            if 'min' in spec: query = query.filter(getattr(Track, key) >= spec['min'])
            if 'max' in spec: query = query.filter(getattr(Track, key) <= spec['max'])
        elif key == 'tags': query = query.filter(Track.tags.any(MusicTag.id.in_(spec)))
        elif key == 'categories': query = query.filter(Track.categories.any(MediaCategory.id.in_(spec)))
    from sqlalchemy.orm import selectinload
    for key in (row.selection_weights or {}):
        query = query.options(selectinload(getattr(Track, key)))
    return query.order_by(Track.id).all()


def weighted_choice(tracks, weights):
    if not weights:
        return random.choice(tracks)
    def weight(track):
        matches = [mapping.get(str(item.id)) for key, mapping in weights.items() if mapping for item in getattr(track, key)]
        return sum(v for v in matches if v is not None) if any(v is not None for v in matches) else 1
    return random.choices(tracks, weights=[weight(t) for t in tracks], k=1)[0]
