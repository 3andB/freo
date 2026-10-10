"""Optional, operator-supplied city coordinates; no geographic inference."""
import json
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


LOCATION_FIELDS = ('city', 'region', 'country', 'latitude', 'longitude')


def coordinates(latitude, longitude):
    values = []
    for raw, name, limit in ((latitude, 'Latitude', 90), (longitude, 'Longitude', 180)):
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            values.append(None)
            continue
        try:
            value = Decimal(str(raw))
        except InvalidOperation:
            raise ValueError(f'{name} must be a finite number.') from None
        if not value.is_finite() or not -limit <= value <= limit:
            raise ValueError(f'{name} must be a finite number between {-limit} and {limit}.')
        values.append(float(value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)))
    if (values[0] is None) != (values[1] is None):
        raise ValueError('Supply both latitude and longitude, or leave both empty.')
    return tuple(values)


def from_settings(station, place, form):
    changed = any(place[key] != (getattr(station, key) or '') for key in LOCATION_FIELDS[:3])
    # Older callers saving unrelated settings must not erase a saved location.
    if 'latitude' not in form and 'longitude' not in form:
        if changed and station.latitude is not None:
            raise ValueError('The station place changed. Confirm its coordinates or clear both coordinate fields.')
        return (None, None) if changed else (station.latitude, station.longitude)
    pair = coordinates(form.get('latitude'), form.get('longitude'))
    if changed and pair[0] is not None:
        try:
            confirmed = json.loads(form.get('location_confirmation', ''))
        except (ValueError, TypeError):
            confirmed = None
        # Bind consent to this exact submitted place AND coordinate pair. A
        # confirmation copied from an earlier edit cannot authorize a new one.
        if confirmed != [form.get(key, '') for key in LOCATION_FIELDS]:
            raise ValueError('The station place changed. Confirm that these coordinates match the new place, or clear both coordinate fields.')
    return pair
