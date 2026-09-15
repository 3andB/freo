"""Bounded ffprobe inspection of staged regular files."""
import json
import math
import subprocess

SUPPORTED = {
    ('mp3', 'mp3'): ('mp3', '.mp3'),
}


class MediaValidationError(ValueError):
    pass


def probe(path, timeout=30):
    try:
        result = subprocess.run(
            ['/usr/bin/ffprobe', '-v', 'error', '-show_entries', 'format=format_name,duration,bit_rate:format_tags=title,artist,album,album_artist,track,tracknumber,disc,discnumber,date,year,genre,isrc:stream=index,codec_type,codec_name,sample_rate,channels,disposition', '-of', 'json', str(path)],
            capture_output=True, text=True, timeout=timeout, check=True,
        )
        data = json.loads(result.stdout)
        fmt = data['format']
        audio = next(stream for stream in data['streams'] if stream.get('codec_type') == 'audio')
        containers = set(fmt['format_name'].split(','))
        match = next((value for (container, codec), value in SUPPORTED.items() if container in containers and codec == audio.get('codec_name')), None)
        if match is None:
            raise MediaValidationError('Unsupported audio codec or container')
        duration = float(fmt['duration'])
        if not math.isfinite(duration) or duration <= 0 or duration > 21600:
            raise MediaValidationError('Invalid audio duration')
        sample_rate = int(audio['sample_rate'])
        channels = int(audio['channels'])
        if sample_rate <= 0 or channels not in (1, 2):
            raise MediaValidationError('Invalid audio stream')
        return {
            'media_type': match[0], 'extension': match[1],
            'duration_ms': round(duration * 1000),
            'bitrate_kbps': round(int(fmt.get('bit_rate', 0)) / 1000) or None,
            'sample_rate_hz': sample_rate, 'channels': channels,
            'tags': {str(k).lower(): v for k, v in fmt.get('tags', {}).items()},
            'has_artwork': any(stream.get('codec_type') == 'video' and stream.get('disposition', {}).get('attached_pic') for stream in data['streams']),
        }
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError, OSError, ValueError, KeyError, StopIteration, TypeError) as error:
        if isinstance(error, MediaValidationError):
            raise
        raise MediaValidationError('Audio probe failed') from error
