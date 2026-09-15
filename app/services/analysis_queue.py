"""Low-priority offline work, independent of browser activity."""
from datetime import datetime, timedelta, timezone
from sqlalchemy import or_
from app.extensions import db
from app.models import Track
from app.services.audio_analysis import analyze_song, extract_artwork


def process_analysis(requested=False):
    now=datetime.now(timezone.utc)
    query=Track.query.filter_by(ingest_status='accepted',decommissioned_at=None,analysis_requested=requested)
    query=query.filter(Track.analysis_status.in_(('pending','failed')),Track.analysis_attempts<3,
        or_(Track.analysis_retry_at.is_(None),Track.analysis_retry_at<=now))
    song=query.order_by(Track.created_at,Track.id).with_for_update(skip_locked=True).first()
    if song is None:
        db.session.rollback();return False
    song.analysis_status='processing';song.analysis_started_at=now
    song.analysis_attempts+=1;song.analysis_requested=False
    db.session.commit()
    analyze_song(song)
    cue_in, cue_out = song.cue_in_ms, song.cue_out_ms
    # Do not overwrite edits made while ffmpeg was running.
    with db.session.no_autoflush:
        db.session.refresh(song, attribute_names=['cue_in_ms','cue_out_ms','notes'])
    if song.cue_in_ms is None: song.cue_in_ms=cue_in
    if song.cue_out_ms is None: song.cue_out_ms=cue_out
    if song.analysis_status=='complete':
        song.analyzed_at=datetime.now(timezone.utc);song.analysis_retry_at=None
        if not song.artwork_key:
            try: extract_artwork(song)
            except (OSError,ValueError): pass
    else: song.analysis_retry_at=now+timedelta(minutes=5*song.analysis_attempts)
    db.session.commit()
    return True


def request_analysis(song):
    if song.decommissioned_at or song.ingest_status!='accepted':
        raise ValueError('Only accepted library songs can be processed')
    if song.analysis_status=='processing' or song.analysis_requested:return False
    song.analysis_status='pending';song.analysis_requested=True
    song.analysis_attempts=0;song.analysis_retry_at=None;song.analysis_error=''
    return True


def recover_analysis():
    # The single ingest service owns this queue. Recovery runs once on startup.
    Track.query.filter_by(analysis_status='processing').filter(Track.analysis_attempts>=3).update({'analysis_status':'failed','analysis_error':'Processing was interrupted repeatedly. Use Process song to retry.'})
    Track.query.filter_by(analysis_status='processing').update({
        'analysis_status':'pending','analysis_retry_at':None})
    db.session.commit()
