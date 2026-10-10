"""Local file identifiers; these do not establish ownership or licensing."""
import re
import secrets

ALPHABET = '23456789ABCDEFGHJKLMNPQRSTUVWXYZ'


def new_track_id():
    value = ''.join(secrets.choice(ALPHABET) for _ in range(8))
    return f'FR-{value[:4]}-{value[4:]}'


def normalize_isrc(value):
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > 64:
        raise ValueError('ISRC must contain 12 letters or digits')
    value = re.sub(r'[\s-]', '', value).upper()
    if not value:
        return None
    if not re.fullmatch(r'[A-Z0-9]{12}', value):
        raise ValueError('ISRC must contain 12 letters or digits')
    return value
