"""Bounded offline analysis for accepted songs; failure never invalidates audio."""
from array import array
import re, subprocess, uuid
from app.services.media_storage import LocalMediaStorage


def analyze_song(song, storage=None, timeout=120):
    storage=storage or LocalMediaStorage();path=storage.regular_file(song.station.slug,song.storage_key)
    song.analysis_status='processing'
    try:
        result=subprocess.run(['/usr/bin/ffmpeg','-nostdin','-hide_banner','-i',str(path),'-af','ebur128=peak=true,silencedetect=n=-45dB:d=0.15','-f','null','-'],capture_output=True,text=True,timeout=timeout,check=False)
        text=result.stderr
        loud=re.findall(r'I:\s*(-?[0-9.]+) LUFS',text);peak=re.findall(r'Peak:\s*(-?[0-9.]+) dBFS',text)
        starts=[float(x) for x in re.findall(r'silence_end: ([0-9.]+)',text)];ends=[float(x) for x in re.findall(r'silence_start: ([0-9.]+)',text)]
        song.loudness_lufs=float(loud[-1]) if loud else None;song.true_peak_db=float(peak[-1]) if peak else None
        song.cue_in_ms=round(starts[0]*1000) if starts and starts[0]<10 else 0
        song.cue_out_ms=round(ends[-1]*1000) if ends and ends[-1]>song.duration_ms/1000-10 else song.duration_ms
        song.bpm=_estimate_bpm(path,min(timeout,60))
        song.analysis_status='complete'
    except (OSError,subprocess.TimeoutExpired,ValueError): song.analysis_status='failed'
    return song


def _estimate_bpm(path,timeout):
    """Estimate tempo from a low-rate mono energy envelope without new dependencies."""
    result=subprocess.run(['/usr/bin/ffmpeg','-nostdin','-hide_banner','-loglevel','error','-t','300','-i',str(path),'-ac','1','-ar','8000','-f','f32le','-'],capture_output=True,timeout=timeout,check=True)
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
