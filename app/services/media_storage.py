"""Local station-scoped storage; never resolves a caller-supplied path."""
import os
from pathlib import Path
import re
import stat

MEDIA_ROOT = Path('/var/lib/freo/media')
KEY_PATTERN = re.compile(r'^[0-9a-f]{32}\.(mp3|flac|wav|ogg)$')


class LocalMediaStorage:
    def __init__(self, root=None):
        self.root = Path(root or os.environ.get('FREO_MEDIA_ROOT', MEDIA_ROOT))

    def station_dir(self, slug):
        from app.services.stations import validate_slug
        validate_slug(slug)
        return self.root / slug

    def approved_path(self, slug, key):
        return self._media_path(slug, key, 'originals')

    def imaging_path(self, slug, key):
        return self._media_path(slug, key, 'imaging')

    def _media_path(self, slug, key, directory):
        if not isinstance(key, str) or not KEY_PATTERN.fullmatch(key):
            raise ValueError('Invalid internal media key')
        station = self.station_dir(slug)
        parent = station / directory
        root = self.root.resolve()
        if self.root.is_symlink() or station.is_symlink() or parent.is_symlink():
            raise ValueError('Symlink media directory is forbidden')
        if not parent.resolve().is_relative_to(root):
            raise ValueError('Media path escapes storage root')
        path = parent / key
        if path.is_symlink():
            raise ValueError('Symlink media is forbidden')
        return path

    def regular_file(self, slug, key):
        return self._regular_file(slug, key, 'originals')

    def imaging_file(self, slug, key):
        return self._regular_file(slug, key, 'imaging')

    def _regular_file(self, slug, key, directory):
        path = self._media_path(slug, key, directory)
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode):
            raise ValueError('Media is not a regular file')
        if not path.resolve().is_relative_to((self.station_dir(slug) / directory).resolve()):
            raise ValueError('Media path escapes station')
        return path
