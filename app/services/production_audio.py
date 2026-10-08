"""Private draft audio, bounded decoding, and a three-input FFmpeg mix."""
from freo_ops.hosting_storage import write as hosting_write

import json
import math
import os
from pathlib import Path
import re
import stat
import subprocess
from uuid import uuid4
from flask import current_app
from app.services.admin_media import upload_root
from app.services.media_probe import probe

KEY = re.compile(r'^[0-9a-f]{32}$')


def root():
    value = Path(current_app.config.get('FREO_PRODUCTION_ROOT') or upload_root() / 'production')
    if not value.is_dir() or value.is_symlink():
        raise ValueError('Audio production storage is unavailable. Ask the administrator.')
    return value


def path(key):
    if not isinstance(key,str) or not KEY.fullmatch(key):
        raise ValueError('Invalid production audio identifier.')
    value = root() / key
    if value.is_symlink():
        raise ValueError('Invalid production audio file.')
    return value


def store(raw):
    key = uuid4().hex
    with os.fdopen(os.open(path(key), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o640), 'wb') as stream:
        hosting_write(stream, raw); stream.flush(); os.fsync(stream.fileno())
    return key


def upload(file, limit):
    key = uuid4().hex
    try:
        with os.fdopen(os.open(path(key), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o640), 'wb') as out:
            size = 0
            while chunk := file.stream.read(65536):
                size += len(chunk)
                if size > limit:
                    raise ValueError('Recording exceeds the upload size limit.')
                hosting_write(out, chunk)
            if not size:
                raise ValueError('Choose a nonempty audio file.')
        return key
    except Exception:
        path(key).unlink(missing_ok=True)
        raise


def inspect(key, maximum):
    source = path(key)
    if not stat.S_ISREG(source.stat().st_mode):
        raise ValueError('Choose a regular audio file.')
    try:
        result = subprocess.run(['/usr/bin/ffprobe','-v','error','-protocol_whitelist','file,pipe',
            '-format_whitelist','mp3,wav,flac,mov,matroska,webm,ogg','-show_entries','format=format_name,duration:stream=codec_type,codec_name','-of','json',str(source)],
            capture_output=True, check=True, timeout=20)
        data = json.loads(result.stdout)
        duration = data['format'].get('duration')
        if duration is None:
            # Streaming MediaRecorder WebM often has no container duration.
            decoded = subprocess.run(['/usr/bin/ffmpeg','-nostdin','-v','error','-threads','1',
                '-protocol_whitelist','file,pipe','-format_whitelist','mp3,wav,flac,mov,matroska,webm,ogg',
                '-i',str(source),'-t',str(maximum+1),'-map','0:a:0','-f','null','-',
                '-progress','pipe:1'],capture_output=True,check=True,timeout=180)
            progress = [line.split('=',1)[1] for line in decoded.stdout.decode().splitlines() if line.startswith('out_time_us=')]
            duration = float(progress[-1])/1000000
        seconds = float(duration)
        streams = data['streams']
        # MediaRecorder WebM/Opus and Ogg recordings are accepted only here.
        containers = set(data['format']['format_name'].split(','))
        if not containers & {'mp3','wav','flac','mov','mp4','m4a','matroska','webm','ogg'}:
            raise ValueError()
        if len(streams) != 1 or streams[0]['codec_type'] != 'audio' or not math.isfinite(seconds) or not 0 < seconds <= maximum:
            raise ValueError()
        return seconds
    except (subprocess.SubprocessError, KeyError, IndexError, ValueError, OSError):
        raise ValueError(f'Choose valid audio without video, at most {maximum} seconds long.') from None


def render(components, settings, maximum):
    if not components.get('voice'):
        raise ValueError('Record or generate a voice first.')
    chosen = [(name, components[name]) for name in ('voice','bed','fx') if components.get(name) and settings.get('use_' + name, True)]
    if chosen[0][0] != 'voice':
        raise ValueError('A voice is required.')
    args = ['/usr/bin/nice','-n','10','/usr/bin/ffmpeg','-nostdin','-v','error','-threads','1']
    filters, ends = [], []
    for index, (name, key) in enumerate(chosen):
        duration = inspect(key, maximum)
        offset = float(settings.get(name + '_offset',0))
        gain = float(settings.get(name + '_level', {'voice':0,'bed':-18,'fx':-12}[name]))
        fade = float(settings.get('fade',1)) if name != 'voice' else 0
        if not all(math.isfinite(v) for v in (offset,gain,fade)) or not 0 <= offset <= maximum or not -60 <= gain <= 6 or not 0 <= fade <= 10:
            raise ValueError('Invalid mix levels, timing, or fade.')
        if duration + offset > maximum + .05:
            raise ValueError(f'The mix exceeds {maximum} seconds. Shorten the audio or reduce its start offset.')
        args += ['-protocol_whitelist','file,pipe','-format_whitelist','mp3,wav,flac,mov,matroska,webm,ogg','-i',str(path(key))]
        fade = min(fade,duration/2)
        chain = f'aresample=44100,aformat=channel_layouts=stereo,volume={gain}dB'
        if fade:
            chain += f',afade=t=in:d={fade},afade=t=out:st={duration-fade}:d={fade}'
        filters.append(f'[{index}:a]{chain},adelay={round(offset*1000)}:all=1[a{index}]')
        ends.append(duration+offset)
    filters.append(''.join(f'[a{i}]' for i in range(len(chosen))) +
        f'amix=inputs={len(chosen)}:normalize=0:duration=longest,alimiter=limit=0.891:level=0:latency=1[out]')
    key = uuid4().hex
    target = path(key)
    try:
        from freo_ops.hosting_storage import run_media
        run_media(args + ['-filter_complex_threads','1','-filter_complex',';'.join(filters),'-map','[out]',
            '-map_metadata','-1','-t',str(maximum+.25),'-c:a','libmp3lame','-b:a','192k','-ar','44100','-threads','1','-f','mp3','-y',str(target)],
            max_output_bytes=int((maximum+1)*24000+262144),capture_output=True,check=True,timeout=180)
        os.chmod(target,0o640)
        details = probe(target)
        if details['duration_ms'] > maximum*1000+100:
            raise ValueError('Rendered audio is too long.')
        return key, details['duration_ms']
    except (OSError,subprocess.SubprocessError):
        target.unlink(missing_ok=True)
        raise ValueError('Audio could not be rendered. Check the source audio and mix settings.') from None
    except Exception:
        target.unlink(missing_ok=True)
        raise
