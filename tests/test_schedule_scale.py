"""Opt-in search benchmark; 100k metadata rows, no media or live database."""
import os
import json
import time
import statistics
import pytest
from sqlalchemy import insert
from app.extensions import db
from app.models import Station, Track
from app.services.visual_schedule import search_sources
from tests.test_web import app

pytestmark=pytest.mark.skipif(os.environ.get('FREO_SCHEDULE_SCALE')!='1',reason='Explicit isolated 100,000-song benchmark')


def test_search_with_one_hundred_thousand_songs(app):
    with app.app_context():
        station=Station.query.filter_by(slug='test-station').one()
        for start in range(0,100000,5000):
            db.session.execute(insert(Track.__table__),[dict(station_id=station.id,uuid=f'bench-{i:032}',title=f'Library song {i:06}',artist=f'Artist {i%1000}',
                freo_track_id=f'B{i:011}',original_filename='benchmark.mp3',storage_key='benchmark.mp3',media_type='mp3',duration_ms=180000,
                sample_rate_hz=44100,channels=2,file_size_bytes=1000,checksum_sha256=None) for i in range(start,start+5000)])
        db.session.commit();durations=[]
        for index in range(20):
            began=time.perf_counter();result=search_sources(station,'song','Library song',index+1);durations.append((time.perf_counter()-began)*1000)
            assert len(result['items'])==40 and result['more']
            assert len(json.dumps(result).encode())<65536
        print(f'100k songs: median={statistics.median(durations):.1f}ms p95={sorted(durations)[18]:.1f}ms; 40 rows per response')


def test_thousand_calendar_definitions(app):
    from datetime import datetime,timezone,timedelta
    from app.services import visual_schedule as vs
    with app.app_context():
        station=Station.query.filter_by(slug='test-station').one();ref=dict(kind='song',id=Track.query.first().id)
        rows=[dict(id=str(i),start=i*60,end=(i+1)*60,source=ref,rule=dict(frequency='daily',anchor='2026-01-01')) for i in range(1000)]
        began=time.perf_counter();document=vs.clean_document(station,rows);validation=time.perf_counter()-began
        p=vs.policy(station,True);p.calendar=document;p.activated=True;db.session.commit()
        durations=[]
        for i in range(50):
            began=time.perf_counter();resolved=vs.resolve_visual(station,datetime(2026,9,21,tzinfo=timezone.utc)+timedelta(minutes=i*13));durations.append((time.perf_counter()-began)*1000)
            assert resolved['source']['kind']=='song' and not resolved['reason']
        print(f'1000 definitions: validation={validation:.3f}s resolver median={statistics.median(durations):.1f}ms p95={sorted(durations)[47]:.1f}ms')
