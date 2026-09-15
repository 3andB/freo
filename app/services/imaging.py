"""First-class station imaging built on Freo's trusted probe and storage rules."""
import hashlib
import os
from pathlib import Path
import re
import stat
import tempfile
import uuid
from datetime import datetime, timedelta, timezone

from app.extensions import db
from app.models import IMAGING_TYPES, ImagingAsset, ImagingGroup, SelectionDecision
from app.services.automation import require_station
from app.services.media import MAX_MEDIA_FILE_BYTES, _prepare_dirs, normalize, require_ingest_identity
from app.services.media_probe import MediaValidationError, probe
from app.services.media_storage import LocalMediaStorage, grant_playout_read
from app.services.stations import validate_slug

CART_CODE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$')


def clean_type(value):
    value = (value or '').upper()
    if value not in IMAGING_TYPES:
        raise ValueError('Unsupported imaging type')
    return value


def clean_code(value):
    value = (value or '').strip().upper()
    if value and not CART_CODE.fullmatch(value):
        raise ValueError('Cart code may use letters, digits, hyphens and underscores only')
    return value or None


def asset_for(slug, identifier):
    station = require_station(slug)
    asset = ImagingAsset.query.filter(ImagingAsset.station_id == station.id,
        (ImagingAsset.uuid == identifier) | (ImagingAsset.cart_code == str(identifier).upper())).first()
    if asset is None:
        raise ValueError('Imaging asset not found in station')
    return asset


def group_for(slug, group_slug):
    station = require_station(slug)
    group = ImagingGroup.query.filter_by(station_id=station.id, slug=validate_slug(group_slug)).first()
    if group is None:
        raise ValueError('Imaging group not found in station')
    return group


def create_group(slug, name, group_slug, description='', minimum_separation_seconds=0, *, commit=True):
    station = require_station(slug)
    validate_slug(group_slug)
    name = normalize(name, 120)
    if not name:
        raise ValueError('Group name is required')
    minimum_separation_seconds = int(minimum_separation_seconds)
    if not 0 <= minimum_separation_seconds <= 86400:
        raise ValueError('Separation must be 0 to 86400 seconds')
    if ImagingGroup.query.filter_by(station_id=station.id, slug=group_slug).first():
        raise ValueError('Imaging group already exists')
    group = ImagingGroup(station_id=station.id, name=name, slug=group_slug,
                         description=normalize(description, 500),
                         minimum_separation_seconds=minimum_separation_seconds)
    db.session.add(group)
    if commit:
        db.session.commit()
    return group


def set_group_membership(slug, group_slug, asset_uuid, assigned, *, commit=True):
    group = group_for(slug, group_slug)
    asset = asset_for(slug, asset_uuid)
    if asset.station_id != group.station_id or asset.decommissioned_at:
        raise ValueError('Imaging asset does not belong to this station')
    if assigned and asset not in group.assets:
        group.assets.append(asset)
    elif not assigned and asset in group.assets:
        group.assets.remove(asset)
    if commit:
        db.session.commit()
    return asset


def update_group(group, name, description, minimum_separation_seconds, *, commit=True):
    name = normalize(name, 120)
    if not name:
        raise ValueError('Group name is required')
    separation = int(minimum_separation_seconds)
    if not 0 <= separation <= 86400:
        raise ValueError('Separation must be 0 to 86400 seconds')
    group.name = name
    group.description = normalize(description, 500)
    group.minimum_separation_seconds = separation
    if commit:
        db.session.commit()
    return group


def set_group_enabled(group, enabled, *, commit=True):
    group.enabled = bool(enabled)
    if commit:
        db.session.commit()
    return group


def decommission_asset(asset, *, active_request_ids=(), commit=True):
    from app.models import ClockSlot, CommercialCreative, EventBlockItem
    if ClockSlot.query.filter_by(imaging_asset_id=asset.id).count():
        raise ValueError('Remove clock references before decommissioning')
    if EventBlockItem.query.filter_by(imaging_asset_id=asset.id).count():
        raise ValueError('Remove event block references before decommissioning')
    if CommercialCreative.query.filter_by(imaging_asset_id=asset.id).count():
        raise ValueError('Commercial creative history prevents decommissioning')
    pending = SelectionDecision.query.filter(SelectionDecision.imaging_asset_id == asset.id,
        SelectionDecision.status.in_(('selected','queued'))).count()
    if pending:
        raise ValueError('Queued imaging cannot be decommissioned')
    if active_request_ids and SelectionDecision.query.filter(SelectionDecision.imaging_asset_id == asset.id,
        SelectionDecision.liquidsoap_request_id.in_(active_request_ids)).count():
        raise ValueError('Currently playing imaging cannot be decommissioned')
    asset.enabled = False
    asset.decommissioned_at = datetime.now(timezone.utc)
    if commit:
        db.session.commit()
    return asset


def ingest_imaging(slug, source, asset_type, name=None, cart_code=None, storage=None, *,
                   original_filename=None, enabled=False):
    """Copy untrusted bytes into controlled staging, then use the shared ffprobe rules."""
    require_ingest_identity()
    station = require_station(slug)
    if not station.enabled:
        raise ValueError('Station is disabled')
    kind = clean_type(asset_type)
    code = clean_code(cart_code)
    storage = storage or LocalMediaStorage()
    _prepare_dirs(storage, slug)
    source = Path(source)
    fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= MAX_MEDIA_FILE_BYTES:
        os.close(fd)
        raise MediaValidationError('Source must be a nonempty regular file within size limit')
    staging = storage.station_dir(slug) / 'staging'
    temp_fd, temp_name = tempfile.mkstemp(prefix='.imaging-', dir=staging)
    temp = Path(temp_name)
    final = None
    committed = False
    try:
        checksum = hashlib.sha256()
        total = 0
        with os.fdopen(fd, 'rb') as input_stream, os.fdopen(temp_fd, 'wb') as output:
            while chunk := input_stream.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_MEDIA_FILE_BYTES:
                    raise MediaValidationError('File exceeds size limit')
                checksum.update(chunk)
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        digest = checksum.hexdigest()
        existing = ImagingAsset.query.filter_by(station_id=station.id, checksum_sha256=digest).first()
        if existing:
            return existing, True
        if code and ImagingAsset.query.filter_by(station_id=station.id, cart_code=code).first():
            raise MediaValidationError('Cart code already exists in this station')
        details = probe(temp)
        original = normalize(original_filename or source.name, 255, 'unnamed')
        display = normalize(name, 200, normalize(Path(original).stem, 200, 'Untitled imaging'))
        asset_uuid = uuid.uuid4()
        key = asset_uuid.hex + details['extension']
        final = storage.imaging_path(slug, key)
        playout_gid = __import__('grp').getgrnam('freo-playout').gr_gid
        if os.geteuid() == 0:
            os.chown(temp, 0, playout_gid)
        elif temp.stat().st_gid != playout_gid:
            raise PermissionError('Staged imaging lacks the playout-read group')
        grant_playout_read(temp)
        os.replace(temp, final)
        asset = ImagingAsset(station_id=station.id, uuid=str(asset_uuid), name=display,
            cart_code=code, asset_type=kind, original_filename=original, storage_key=key,
            media_type=details['media_type'], duration_ms=details['duration_ms'],
            bitrate_kbps=details['bitrate_kbps'], sample_rate_hz=details['sample_rate_hz'],
            channels=details['channels'], file_size_bytes=total, checksum_sha256=digest,
            enabled=enabled, ingest_status='accepted')
        db.session.add(asset)
        db.session.commit()
        committed = True
        return asset, False
    except Exception:
        db.session.rollback()
        if final is not None and not committed:
            final.unlink(missing_ok=True)
        raise
    finally:
        temp.unlink(missing_ok=True)


def verify_imaging(asset, storage=None):
    storage = storage or LocalMediaStorage()
    path = storage.imaging_file(asset.station.slug, asset.storage_key)
    checksum = hashlib.sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(1024 * 1024):
            checksum.update(chunk)
    if checksum.hexdigest() != asset.checksum_sha256:
        raise MediaValidationError('Stored checksum mismatch')
    details = probe(path)
    if details['media_type'] != asset.media_type:
        raise MediaValidationError('Stored audio type changed')
    return True


def set_asset_enabled(asset, enabled, *, commit=True):
    if asset.ingest_status != 'accepted' or asset.decommissioned_at:
        raise ValueError('Only accepted active imaging can be enabled')
    asset.enabled = bool(enabled)
    if commit:
        db.session.commit()
    return asset


def update_asset(asset, name, asset_type, cart_code, description, *, commit=True):
    name = normalize(name, 200)
    if not name:
        raise ValueError('Imaging name is required')
    code = clean_code(cart_code)
    if code:
        duplicate = ImagingAsset.query.filter_by(station_id=asset.station_id, cart_code=code).first()
        if duplicate and duplicate.id != asset.id:
            raise ValueError('Cart code already exists in this station')
    asset.name = name
    asset.asset_type = clean_type(asset_type)
    asset.cart_code = code
    asset.description = normalize(description, 500)
    if commit:
        db.session.commit()
    return asset


def eligible_asset(asset, station_id, storage):
    if not asset or asset.station_id != station_id or not asset.enabled or asset.ingest_status != 'accepted' or asset.decommissioned_at:
        return False
    try:
        storage.imaging_file(asset.station.slug, asset.storage_key)
        return True
    except (OSError, ValueError):
        return False


def choose_group(group, station_id, storage=None, now=None, recent=None):
    """Least recently confirmed, with queued/selected holds and bounded relaxation."""
    storage = storage or LocalMediaStorage()
    now = now or datetime.now(timezone.utc)
    if not group or group.station_id != station_id or not group.enabled:
        return None, 'unavailable_group', 0
    candidates = [asset for asset in group.assets if eligible_asset(asset, station_id, storage)]
    if not candidates:
        return None, 'empty_group', 0
    if recent is None:
        recent = (SelectionDecision.query.filter(SelectionDecision.station_id == station_id,
            SelectionDecision.imaging_asset_id.isnot(None),
            SelectionDecision.status.in_(('started','queued','selected')))
            .order_by(SelectionDecision.id.desc()).limit(500).all())
    last_confirmed = {}
    held = set()
    for decision in recent:
        if getattr(decision, 'imaging_asset_id', None) is None:
            continue
        if decision.status == 'started' and decision.started_at:
            started = decision.started_at.replace(tzinfo=decision.started_at.tzinfo or timezone.utc)
            previous = last_confirmed.get(decision.imaging_asset_id)
            if previous is None or started > previous:
                last_confirmed[decision.imaging_asset_id] = started
        elif decision.status in ('queued', 'selected'):
            held.add(decision.imaging_asset_id)
    candidates.sort(key=lambda asset: (last_confirmed.get(asset.id, datetime.min.replace(tzinfo=timezone.utc)), asset.id))
    window = group.minimum_separation_seconds
    eligible = [asset for asset in candidates if asset.id not in held and
        (asset.id not in last_confirmed or now - last_confirmed[asset.id] >= timedelta(seconds=window))]
    if eligible:
        return eligible[0], 'none', len(eligible)
    unheld = [asset for asset in candidates if asset.id not in held]
    if unheld:
        return unheld[0], 'imaging_separation', len(unheld)
    return candidates[0], 'pending_hold', len(candidates)
