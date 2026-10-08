"""Hosted Liquidsoap encoded-audio sink; never buffers an unbounded recording."""
import os
from pathlib import Path
import re
import sys
from .hosting_storage import inventory, write
from .hosting import HostingError


def main():
    if len(sys.argv) != 3 or not re.fullmatch('[a-z0-9][a-z0-9-]{0,62}[a-z0-9]|[a-z0-9]', sys.argv[1]) or not re.fullmatch('[a-f0-9]{32}', sys.argv[2]):
        return 2
    config = inventory()
    directory = Path(config['media_root']) / sys.argv[1] / 'recordings'
    for parent in (directory, *directory.parents):
        if parent.is_symlink():
            return 2
    target = directory / (sys.argv[2] + '.mp3')
    try:
        fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o640)
        with os.fdopen(fd, 'wb', buffering=0) as stream:
            while data := sys.stdin.buffer.read(65536):
                write(stream, data)
            os.fsync(stream.fileno())
        return 0
    except HostingError as error:
        marker = Path('/run/freo/playout') / sys.argv[1] / ('recording-' + sys.argv[2] + '.error')
        try:
            marker.write_text(error.code)
        except OSError:
            pass
        print(error.code, file=sys.stderr)
        # The existing worker requests normal recorder closure after reading the
        # marker. Drain until that closure (or the engine's 15-second lease expiry)
        # so quota exhaustion cannot block audio or poison subsequent recordings.
        while sys.stdin.buffer.read(65536):
            pass
        return 0
    except OSError:
        print('recording_storage_unavailable', file=sys.stderr)
        return 5

if __name__ == '__main__':
    raise SystemExit(main())
