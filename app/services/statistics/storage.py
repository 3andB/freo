"""Read-only physical inventory and database image payload accounting."""
import os
from pathlib import Path
import shutil
import stat
from sqlalchemy import func, text
from flask import current_app
from app.extensions import db
from app.models import Station, Track, ImagingAsset, MusicArtwork, StationLogo, StationPlayerAsset, StorageSnapshot
from app.services.admin_media import upload_root


def scan(directory, referenced=None):
    size = count = retained = errors = 0
    found = set()
    try:
        if directory.is_symlink():
            return 0, 0, 0, 1, set()
        with os.scandir(directory) as entries:
            for entry in entries:
                try:
                    info = entry.stat(follow_symlinks=False)
                    if not stat.S_ISREG(info.st_mode):
                        continue
                    size += info.st_size
                    count += 1
                    found.add(entry.name)
                    if referenced is not None and entry.name not in referenced:
                        retained += info.st_size
                except OSError:
                    errors += 1
    except FileNotFoundError:
        pass
    except OSError:
        errors += 1
    return size, count, retained, errors, found


def inventory(now):
    root = Path(current_app.config['FREO_MEDIA_ROOT'] or '/var/lib/freo/media')
    at = now // 3600 * 3600
    totals = dict(music=0, imaging=0, artwork=0, logos=0, player_images=0, staging=0,
                  retained=0, missing=0, errors=0, files=0, audio_duration=0, library_count=0)
    for station in Station.query.order_by(Station.id):
        data = {key: 0 for key in totals}
        tracks = Track.query.filter_by(station_id=station.id, deleted_at=None).all()
        assets = ImagingAsset.query.filter_by(station_id=station.id).all()
        refs = dict(originals={t.storage_key for t in tracks}, imaging={a.storage_key for a in assets}, previews={t.preview_key for t in tracks if t.preview_key}, artwork=None, staging=None)
        base = root / station.slug
        if root.is_symlink() or base.is_symlink():
            data['errors'] += 1
        else:
            for directory, category in [('originals', 'music'), ('previews', 'music'), ('imaging', 'imaging'), ('artwork', 'artwork'), ('staging', 'staging')]:
                size, count, retained, errors, found = scan(base / directory, refs[directory])
                data[category] += size
                data['files'] += count
                data['retained'] += size if station.deleted_at else retained
                data['errors'] += errors
                if refs[directory] is not None:
                    data['missing'] += len(refs[directory] - found)
        for model, category, columns in [(MusicArtwork, 'artwork', ['image']),
                (StationLogo, 'logos', ['image', 'thumbnail']), (StationPlayerAsset, 'player_images', ['image'])]:
            for column in columns:
                size = db.session.query(func.coalesce(func.sum(func.length(getattr(model, column))), 0)).filter(model.station_id == station.id).scalar()
                data[category] += int(size)
                if station.deleted_at:
                    data['retained'] += int(size)
        data['audio_duration'] = sum(t.duration_ms for t in tracks)
        data['library_count'] = len(tracks)
        data['total'] = sum(data[k] for k in ('music', 'imaging', 'artwork', 'logos', 'player_images'))
        data['archived'] = bool(station.deleted_at)
        for key in totals:
            totals[key] += data[key]
        row = db.session.get(StorageSnapshot, (station.id, at))
        if row is None:
            row = StorageSnapshot(scope=station.id, at=at)
            db.session.add(row)
        row.data = data
    totals['total'] = sum(totals[k] for k in ('music', 'imaging', 'artwork', 'logos', 'player_images'))
    uploads = scan(upload_root())
    totals['staging'] += uploads[0]
    totals['errors'] += uploads[3]
    try:
        disk = shutil.disk_usage(root)
        totals['disk'] = dict(total=disk.total, used=disk.used, free=disk.free)
    except OSError:
        totals['disk'] = None
    if db.engine.dialect.name == 'postgresql':
        totals['database_bytes'] = db.session.execute(text('SELECT pg_database_size(current_database())')).scalar()
    row = db.session.get(StorageSnapshot, (0, at))
    if row is None:
        row = StorageSnapshot(scope=0, at=at)
        db.session.add(row)
    row.data = totals
    StorageSnapshot.query.filter(StorageSnapshot.at < now - 5 * 366 * 86400).delete()
    db.session.commit()
    return totals
