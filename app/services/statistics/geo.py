"""Local approximate geolocation. Raw addresses are never persisted."""
import hashlib
import ipaddress
from pathlib import Path
import threading
from maxminddb import InvalidDatabaseError
from flask import current_app

_lock = threading.Lock()
_reader = None
_identity = None
UNKNOWN = dict(place='unknown', country='Unknown', country_code='XX', region='', city='', lat=None, lon=None)


def lookup(address):
    global _reader, _identity
    try:
        if not ipaddress.ip_address(address).is_global:
            return dict(UNKNOWN)
        path = Path(current_app.config['FREO_GEOIP_DATABASE'])
        identity = (str(path), path.stat().st_mtime_ns)
        with _lock:
            if identity != _identity:
                import maxminddb
                reader = maxminddb.open_database(str(path))
                if _reader:
                    _reader.close()
                _reader, _identity = reader, identity
            data = _reader.get(address) or {}
        country = data.get('country', {})
        region = (data.get('subdivisions') or [{}])[0]
        city = data.get('city', {})
        location = data.get('location', {})
        code = country.get('iso_code', 'XX')
        result = dict(country=country.get('names', {}).get('en', code), country_code=code,
            region=region.get('names', {}).get('en', ''), city=city.get('names', {}).get('en', ''),
            lat=location.get('latitude'), lon=location.get('longitude'))
        if code == 'XX':
            return dict(UNKNOWN)
        if result['lat'] is not None and result['lon'] is not None:
            result['lat'], result['lon'] = round(float(result['lat']), 2), round(float(result['lon']), 2)
        else:
            result['lat'] = result['lon'] = None
        result['place'] = hashlib.sha256('|'.join(str(result[k]) for k in result).encode()).hexdigest()[:32]
        return result
    except (OSError, ValueError, ImportError, InvalidDatabaseError):
        return dict(UNKNOWN)


def status():
    path = Path(current_app.config['FREO_GEOIP_DATABASE'])
    try:
        return dict(available=True, updated_at=int(path.stat().st_mtime), provider='DB-IP / local MMDB')
    except OSError:
        return dict(available=False, updated_at=None, provider='DB-IP / local MMDB')
