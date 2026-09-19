"""Bounded offline analysis for accepted songs; failure never invalidates audio."""
from array import array
import logging, re, subprocess, uuid
from app.services.media_storage import LocalMediaStorage


def analyze_song(song, storage=None, timeout=120):
    import json, math
    storage = storage or LocalMediaStorage()
    song.analysis_status = 'processing'
    try:
        path = storage.regular_file(song.station.slug, song.storage_key)
        result = subprocess.run(['/usr/bin/nice','-n','10','/usr/bin/ffmpeg','-nostdin','-hide_banner',
            '-threads','1','-i',str(path),'-af','silencedetect=n=-45dB:d=0.15,loudnorm=I=-16:TP=-1.5:print_format=json',
            '-f','null','-'],capture_output=True,text=True,timeout=timeout,check=True)
        measurement = json.loads(result.stderr[result.stderr.rfind('{'):])
        loudness, peak = float(measurement['input_i']), float(measurement['input_tp'])
        if not math.isfinite(loudness) or not math.isfinite(peak):
            raise ValueError('No measurable audio loudness')
        song.loudness_lufs, song.true_peak_db = loudness, peak
        starts=[float(x) for x in re.findall(r'silence_end: ([0-9.]+)',result.stderr)]
        ends=[float(x) for x in re.findall(r'silence_start: ([0-9.]+)',result.stderr)]
        if song.cue_in_ms is None: song.cue_in_ms=round(starts[0]*1000) if starts and starts[0]<10 else 0
        if song.cue_out_ms is None: song.cue_out_ms=round(ends[-1]*1000) if ends and ends[-1]>song.duration_ms/1000-10 else song.duration_ms
        try: song.bpm = _estimate_bpm(path,min(timeout,60))
        except (OSError,subprocess.SubprocessError,ValueError): pass
        try: song.waveform = waveform(path, song.duration_ms, timeout)
        except (OSError,subprocess.SubprocessError,ValueError): pass
        song.analysis_status='complete';song.analysis_error=''
    except (OSError,subprocess.SubprocessError,ValueError,KeyError) as error:
        logging.getLogger(__name__).exception('Audio analysis failed for song=%s', song.uuid)
        song.analysis_status='failed'
        if isinstance(error, PermissionError) or (isinstance(error, subprocess.CalledProcessError) and 'Permission denied' in str(error.stderr)):
            song.analysis_error='The processing worker cannot read this audio file. Repair its file permissions, then retry.'
        elif isinstance(error, FileNotFoundError):
            song.analysis_error='The audio file is missing. Restore the file or delete and reimport this song.'
        elif isinstance(error, subprocess.TimeoutExpired):
            song.analysis_error='Audio processing timed out. Retry processing; if it repeats, check the source file.'
        else:
            song.analysis_error='Audio analysis failed. Check the file and retry.'
    return song


def _estimate_bpm(path,timeout):
    """Estimate tempo from a low-rate mono energy envelope without new dependencies."""
    result=subprocess.run(['/usr/bin/nice','-n','10','/usr/bin/ffmpeg','-nostdin','-hide_banner','-loglevel','error','-threads','1','-t','300','-i',str(path),'-ac','1','-ar','8000','-f','f32le','-'],capture_output=True,timeout=timeout,check=True)
    samples=array('f');samples.frombytes(result.stdout);frame=160
    energy=[sum(abs(x) for x in samples[n:n+frame])/frame for n in range(0,len(samples)-frame,frame)]
    if len(energy)<400:return None
    mean=sum(energy)/len(energy);onset=[max(0,energy[n]-energy[n-1]-mean*.02) for n in range(1,len(energy))]
    best=max(range(15,51),key=lambda lag:sum(onset[n]*onset[n-lag] for n in range(lag,len(onset))))
    return round(3000/best,1)


def extract_artwork(song, storage=None, timeout=30):
    storage=storage or LocalMediaStorage();source=storage.regular_file(song.station.slug,song.storage_key);key=uuid.uuid4().hex+'.jpg';target=storage.artwork_path(song.station.slug,key)
    try:
        subprocess.run(['/usr/bin/ffmpeg','-nostdin','-hide_banner','-loglevel','error','-i',str(source),'-map','0:v:0','-frames:v','1','-vf','scale=800:800:force_original_aspect_ratio=decrease',str(target)],timeout=timeout,check=True)
        target.chmod(0o640);song.artwork_key=key
        if song.catalog_album and not song.catalog_album.artwork_key: song.catalog_album.artwork_key=key
    except (OSError,subprocess.SubprocessError): target.unlink(missing_ok=True)
    return song.artwork_key


def waveform(path, duration_ms, timeout=120):
    """600 RMS bins from streaming decoded audio; no full-file PCM buffer."""
    import math, tempfile
    from pathlib import Path
    frame = max(1, math.ceil(max(1, duration_ms) * 8 / 600))
    with tempfile.TemporaryDirectory(prefix='freo-waveform-') as directory:
        output = Path(directory) / 'levels.txt'
        filters = f'aresample=8000,asetnsamples=n={frame}:p=0,astats=metadata=1:reset=1,ametadata=mode=print:key=lavfi.astats.Overall.RMS_level:file={output}'
        subprocess.run(['ffmpeg','-nostdin','-v','error','-threads','1','-i',str(path),'-vn','-af',filters,
                        '-f','null','-'],capture_output=True,timeout=timeout,check=True)
        levels = re.findall(r'lavfi.astats.Overall.RMS_level=([^\s]+)', output.read_text())
        values = [10 ** (float(level)/20) if math.isfinite(float(level)) else 0 for level in levels[:601]]
        maximum = max(values, default=0) or 1
        return [round(value/maximum,4) for value in values]
