"""Worker-owned compatible previews; broadcast playback uses the original."""
import os
import subprocess
import tempfile
from pathlib import Path

from app.services.media_probe import MediaValidationError
from app.services.media_storage import grant_playout_read


def create_preview(source, target, timeout=300):
    from freo_ops.hosting_storage import run_media
    from app.services.media_probe import probe
    from freo_ops.hosting import read
    bound = int(probe(source)['duration_ms'] * 24 + 262144) if read()['hosted'] else 0
    fd, name = tempfile.mkstemp(prefix='.preview-', suffix='.mp3', dir=target.parent)
    os.close(fd)
    staged = Path(name)
    try:
        run_media([
            '/usr/bin/nice', '-n', '10', '/usr/bin/ffmpeg', '-nostdin', '-v', 'error',
            '-xerror', '-err_detect', 'explode', '-threads', '1', '-i', str(source),
            '-map', '0:a:0', '-vn', '-map_metadata', '-1', '-c:a', 'libmp3lame',
            '-b:a', '192k', '-ar', '44100', '-threads', '1', '-y', str(staged),
        ], max_output_bytes=bound, capture_output=True, check=True, timeout=timeout)
        grant_playout_read(staged)
        os.replace(staged, target)
    except (OSError, subprocess.SubprocessError) as error:
        raise MediaValidationError('Audio could not be decoded for preview and playback') from error
    finally:
        staged.unlink(missing_ok=True)
