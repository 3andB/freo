"""Bounded ffprobe inspection of staged regular files."""
import json
import math
import subprocess

SUPPORTED = {
    ('mp3', 'mp3'): ('mp3', '.mp3'),
    ('flac', 'flac'): ('flac', '.flac'),
    ('mov', 'aac'): ('m4a', '.m4a'),
    ('mov', 'alac'): ('m4a', '.m4a'),
    **{('wav', codec): ('wav', '.wav') for codec in
       ('pcm_u8', 'pcm_s16le', 'pcm_s24le', 'pcm_s32le', 'pcm_f32le', 'pcm_f64le')},
}
MIME_TYPES = {'mp3': 'audio/mpeg', 'wav': 'audio/wav', 'm4a': 'audio/mp4', 'flac': 'audio/flac'}


class MediaValidationError(ValueError):
    pass


def probe(path, timeout=30):
    try:
        result = subprocess.run(
            ['/usr/bin/ffprobe', '-v', 'error', '-show_entries', 'format=format_name,duration,bit_rate:format_tags:stream=index,codec_type,codec_name,sample_rate,channels:stream_tags:stream_disposition=attached_pic', '-of', 'json', str(path)],
            capture_output=True, text=True, timeout=timeout, check=True,
        )
        data = json.loads(result.stdout)
        fmt = data['format']
        audio = next(stream for stream in data['streams'] if stream.get('codec_type') == 'audio')
        if sum(s.get('codec_type') == 'audio' for s in data['streams']) != 1 or any(
            s.get('codec_type') == 'video' and not s.get('disposition', {}).get('attached_pic')
            for s in data['streams']
        ):
            raise MediaValidationError('Choose a single audio track without video')
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
            'tags': {str(k).lower(): v for k, v in {**audio.get('tags', {}), **fmt.get('tags', {})}.items()},
            'has_artwork': any(stream.get('codec_type') == 'video' and stream.get('disposition', {}).get('attached_pic') for stream in data['streams']),
        }
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError, OSError, ValueError, KeyError, StopIteration, TypeError) as error:
        if isinstance(error, MediaValidationError):
            raise
        raise MediaValidationError('Audio probe failed') from error
