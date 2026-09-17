#!/usr/bin/env python3
"""Capture real Freo screens using disposable, explicitly fictional demo data.

Run with venv/bin/python scripts/capture-homepage.py. Requires Selenium,
Chromium/ChromeDriver and ffmpeg. Never reads the installation .env,
connects to production services, or sends commands to an audio engine.
"""
import argparse
from collections import defaultdict
import hashlib
import json
import logging
import math
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def demo_app(directory):
    # Set before importing configuration; no ambient installation credentials.
    os.environ.update(FREO_ENV_FILE='/dev/null', DATABASE_URL=f'sqlite:///{directory}/demo.sqlite',
                      SECRET_KEY='isolated-homepage-demonstration-only',
                      FREO_MEDIA_ROOT=str(directory / 'media'), FLASK_ENV='testing')
    from app import create_app
    from app.extensions import db
    from app import models as m
    from app.services import player, visual_schedule as vs
    from app.services.statistics import collect
    from flask import request, Response
    from werkzeug.security import generate_password_hash

    app = create_app('testing')
    app.config.update(FREO_INSTALLATION_HOSTS='localhost,127.0.0.1', PUBLIC_BASE_URL='',
                      FREO_UPLOAD_ROOT=str(directory / 'uploads'), FREO_LIVE_MIC=False)
    media = directory / 'media' / 'sunroom-radio' / 'originals'
    media.mkdir(parents=True)
    tone = media / ('a' * 32 + '.mp3')
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                    'sine=frequency=330:duration=240', '-q:a', '9', str(tone)], check=True)
    now = datetime.now(timezone.utc)
    with app.app_context():
        db.create_all()
        station = m.Station(name='Sunroom Radio', slug='sunroom-radio', timezone='UTC',
            description='Independent sounds. Open windows. A little more sunshine.',
            city='Fremantle', country='AU', desired_state='running', enabled=True)
        station.stream = m.StreamMount()
        db.session.add(station)
        db.session.add(m.AdminUser(email='demo@example.test', password_hash=generate_password_hash('demo-only-password')))
        db.session.flush()
        categories = [m.MediaCategory(station_id=station.id, name=name, slug=slug) for name, slug in
                      [('Morning Light', 'morning-light'), ('Coastal Soul', 'coastal-soul'), ('After Hours', 'after-hours')]]
        tags = [m.MusicTag(station_id=station.id, name=name, slug=name.lower(), color=color) for name, color in
                [('Warm', '#b47b45'), ('Discovery', '#067476'), ('Mellow', '#745295')]]
        db.session.add_all(categories + tags)
        songs = []
        titles = ['Golden Hour', 'After the Rain', 'Open Windows', 'Coastline', 'Soft Landing', 'Still Water',
                  'Velvet Morning', 'The Long Way Home', 'Daybreak', 'In Slow Motion', 'Paper Satellites', 'Blue Sunday']
        for i, name in enumerate(['The Daydreams', 'Milo Coast', 'June & the Tides', 'Paper Moon']):
            artist = m.Artist(station_id=station.id, name=name, normalized_name=name.lower())
            album = m.Album(station_id=station.id, artist=artist, title=['A Little More Sunshine', 'Night Swimming', 'Open Water', 'Sunday People'][i],
                            normalized_title=f'demo-album-{i}', release_year=2026)
            db.session.add_all([artist, album]); db.session.flush()
            for j in range(3):
                n = i * 3 + j
                song = m.Track(station_id=station.id, uuid=str(uuid4()), title=titles[n], artist=name,
                    album=album.title, artist_id=artist.id, album_id=album.id, track_number=j + 1,
                    original_filename=f'demo-{n}.mp3', storage_key=tone.name, media_type='mp3',
                    duration_ms=240000, sample_rate_hz=44100, channels=1, file_size_bytes=tone.stat().st_size,
                    checksum_sha256=hashlib.sha256(f'fictional-song-{n}'.encode()).hexdigest(),
                    enabled=True, ingest_status='accepted', analysis_status='complete',
                    bpm=92 + n * 3, loudness_lufs=-17.5, true_peak_db=-3.5, release_year=2026,
                    notes='Fictional demonstration catalog.',
                    waveform=[round(.1 + .65 * abs(math.sin(k * .31) * math.cos(k * .13)), 3) for k in range(240)])
                song.categories = [categories[n % 3]]; song.tags = [tags[n % 3]]
                db.session.add(song); songs.append(song)
        db.session.flush()
        playlists = []
        for i, name in enumerate(['Golden Hour', 'Coastal Discoveries', 'After Dark']):
            row = m.Playlist(station_id=station.id, name=name, mode='STRAIGHT' if i == 0 else 'RANDOM',
                            description=['Warm records for wide-open afternoons.', 'New favorites from the coast and beyond.', 'The station slows down.'][i])
            row.items = [m.PlaylistItem(track_id=s.id, position=j + 1) for j, s in enumerate(songs[i:] + songs[:i])]
            db.session.add(row); playlists.append(row)
        db.session.flush()
        shows = []
        for name, start_index in [('Morning Ritual', 0), ('The Afternoon Edit', 1), ('Night Swimming', 2)]:
            show = vs.save_composition(station, dict(kind='SHOW', name=name, description='A little space for good music.', duration=7200,
                sections=[dict(id=str(uuid4()), start=k * 2400, end=(k + 1) * 2400,
                               source=dict(kind='playlist', id=playlists[(start_index + k) % 3].id)) for k in range(3)]))
            shows.append(show)
        db.session.flush()
        block = vs.save_composition(station, dict(kind='BLOCK', name='Sunroom Weekdays', description='A complete day, with its own rhythm.',
            sections=[dict(id=str(uuid4()), start=k * 21600, end=(k + 1) * 21600,
                           source=dict(kind='show', id=shows[k % 3].id)) for k in range(4)]))
        calendar = []
        for day in range(7):
            for index, (start, end) in enumerate([(0, 6), (6, 9), (9, 12), (12, 16), (16, 20), (20, 24)]):
                kind = 'playlist' if index in (0, 3, 5) else 'show'
                source = playlists[(index + day) % 3] if kind == 'playlist' else shows[(index + day) % 3]
                calendar.append(dict(id=str(uuid4()), start=start * 3600, end=end * 3600,
                    source=vs.source(station, dict(kind=kind, id=source.id)),
                    rule=vs.clean_rule(dict(frequency='weekly', anchor='2026-09-14', weekdays=[day]))))
        schedule = m.ChannelSchedule(station_id=station.id, mode='CALENDAR', activated=True, calendar_saved=True,
            calendar=calendar, default_playlist_id=playlists[0].id, simple=vs.source(station, dict(kind='playlist', id=playlists[0].id)))
        db.session.add(schedule)
        state = m.AutomationState(station_id=station.id, enabled=True, hold=True, operator_mode='DJ_BOOTH',
            cued_track_id=songs[3].id, worker_heartbeat_at=now, observed_queue_depth=1)
        db.session.add(state)
        for i in range(180):
            db.session.add(m.SelectionDecision(station_id=station.id, track_id=songs[i % 12].id,
                category_id=categories[i % 3].id, status='started', selected_at=now - timedelta(minutes=i * 6 + 3),
                started_at=now - timedelta(minutes=i * 6 + 3)))
        current = m.SelectionDecision(station_id=station.id, track_id=songs[0].id, category_id=categories[0].id,
            status='started', selected_at=now, started_at=now - timedelta(seconds=72), playback_bus='A')
        ready = m.SelectionDecision(station_id=station.id, track_id=songs[3].id, status='queued',
            selected_at=now, playback_bus='B')
        db.session.add_all([current, ready]); db.session.flush()
        db.session.add(m.LiveQueueSnapshot(station_id=station.id, current_decision_id=current.id,
            queued_decision_ids=[ready.id], observed_at=now, broadcast_online=True,
            broadcast_observed_at=now, listeners=128, program_rms=.14,
            mixer=dict(mode='DJ_BOOTH', a_id=current.id, b_id=ready.id, cart_id=None, a_playing=True,
                       b_playing=False, a_elapsed=72, b_elapsed=0, crossfader=0)))
        for i, name in enumerate(['Sunroom hello', 'New discoveries', 'Good morning', 'After hours', 'Weather bed', 'Coming up', 'Community', 'Golden hour']):
            db.session.add(m.LiveCartSlot(station_id=station.id, role='HOT', position=i + 1,
                track_id=songs[i].id, label=name, description='Demonstration cart', playback_mode='OVER', duck_percent=60))
        for i, name in enumerate(['This is Sunroom', 'Your daily escape', 'Stay curious', 'Independent sound']):
            db.session.add(m.LiveCartSlot(station_id=station.id, role='ID', position=i + 1,
                track_id=songs[i].id, label=name, description='Demonstration station ID', playback_mode='TAKEOVER'))
        station.player_settings = m.StationPlayerSettings(config=dict(player.DEFAULTS, voting_enabled=True,
            comments_enabled=True, public_totals=True, schedule_enabled=True, palette='ocean',
            message_enabled=True, message='A soundtrack for your little corner of the world. Welcome to Sunroom.'), revision=1)
        for i, song in enumerate(songs):
            for j in range(18 + i * 2):
                db.session.add(m.ListenerVote(station_id=station.id, track_id=song.id, listener_key=f'demo-{i}-{j}',
                    value=-1 if j % 13 == 12 else 1, decision_id=current.id))
        stamp = int(now.timestamp())
        for scope in (0, station.id):
            db.session.add(m.StatsState(scope=scope, data=dict(at=stamp, since=stamp - 48 * 3600,
                online=True, listeners=128, clients_at=stamp)))
            rollups = defaultdict(lambda: dict(observed_seconds=0, listener_seconds=0, online_seconds=0, peak=0, bytes_sent=0, transfer_seconds=0))
            for minute in range(48 * 60):
                at = (stamp // 60 - minute) * 60
                audience = int(82 + 29 * math.sin(minute / 140) + 16 * math.sin(minute / 37) + 7 * math.cos(minute / 8))
                db.session.add(m.StatsBucket(scope=scope, resolution='minute', at=at, observed_seconds=60,
                    listener_seconds=audience * 60, online_seconds=60, peak=audience + 4,
                    bytes_sent=audience * 16000 * 60, transfer_seconds=60))
                for resolution in ("hour", "month", "lifetime"):
                    point, _ = collect.bounds(at, resolution)
                    values = rollups[(resolution, point)]
                    for key, value in dict(observed_seconds=60, listener_seconds=audience * 60, online_seconds=60, bytes_sent=audience * 16000 * 60, transfer_seconds=60).items():
                        values[key] += value
                    values["peak"] = max(values["peak"], audience + 4)
            for (resolution, point), values in rollups.items():
                db.session.add(m.StatsBucket(scope=scope, resolution=resolution, at=point, **values))
            db.session.add(m.StorageSnapshot(scope=scope, at=stamp // 3600 * 3600,
                data=dict(total=3856000000, music=3800000000, imaging=42000000, artwork=14000000,
                          logos=0, player_images=0, missing=0, retained=0)))
        locations = [('Fremantle', 'Australia', 'AU', -32.05, 115.75), ('London', 'United Kingdom', 'GB', 51.5, -.1),
                     ('Berlin', 'Germany', 'DE', 52.52, 13.4), ('New York', 'United States', 'US', 40.71, -74),
                     ('Tokyo', 'Japan', 'JP', 35.68, 139.69), ('Cape Town', 'South Africa', 'ZA', -33.92, 18.42),
                     ('Melbourne', 'Australia', 'AU', -37.81, 144.96), ('São Paulo', 'Brazil', 'BR', -23.55, -46.63)]
        for i, (city, country, code, lat, lon) in enumerate(locations):
            geo = dict(place=city.lower(), city=city, country=country, country_code=code, region='', lat=lat, lon=lon)
            for j in range(3 + i):
                collect.presence(station.id, 'stream', f'demo-location-{i}-{j}', geo, stamp)
        db.session.flush(); player.publish(station); db.session.commit()
        identifiers = dict(station=station.id, current=current.id, ready=ready.id, show=shows[0].id, block=block.id)

    @app.before_request
    def demonstration_observations():
        if request.path.endswith(('/live-status', '/experience', '/stats/data')):
            observed = datetime.now(timezone.utc)
            m.LiveQueueSnapshot.query.update(dict(observed_at=observed, broadcast_observed_at=observed))
            m.AutomationState.query.update(dict(worker_heartbeat_at=observed))
            for row in m.StatsState.query.all():
                row.data = dict(row.data, at=int(observed.timestamp()))
            db.session.commit()

    app.add_url_rule('/stream/sunroom-radio', 'demonstration_stream', lambda: Response(tone.read_bytes(), mimetype='audio/mpeg'))
    return app, identifiers


def capture(output, masters):
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait, Select
    from werkzeug.serving import make_server
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    output.mkdir(parents=True, exist_ok=True); masters.mkdir(parents=True, exist_ok=True)
    manifest = dict(captured_at=datetime.now(timezone.utc).isoformat(), origin='Disposable fictional Sunroom Radio fixture',
                    disclosure='All music, audience numbers and playback observations are demonstration data.', screens=[])
    with tempfile.TemporaryDirectory(prefix='freo-product-') as directory:
        directory = Path(directory)
        app, ids = demo_app(directory)
        server = make_server('127.0.0.1', 0, app, threaded=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        options = Options(); options.binary_location = os.environ.get('CHROMIUM_BINARY', '/usr/bin/chromium-browser')
        for arg in ('--headless=new', '--no-sandbox', '--disable-dev-shm-usage', '--window-size=1600,1100',
                    '--force-device-scale-factor=1', '--enable-unsafe-swiftshader'):
            options.add_argument(arg)
        driver = webdriver.Chrome(service=Service(os.environ.get('CHROMEDRIVER', '/usr/bin/chromedriver')), options=options)
        driver.execute_cdp_cmd('Emulation.setDeviceMetricsOverride', dict(width=1600, height=1800, deviceScaleFactor=1, mobile=False))
        base = f'http://127.0.0.1:{server.server_port}'
        wait = WebDriverWait(driver, 20)
        def ready():
            wait.until(lambda d: d.execute_script('return document.readyState') == 'complete')
            driver.execute_async_script('document.fonts.ready.then(arguments[0])')

        def shot(name, selector=None, max_height=None):
            for theme in ('day', 'night'):
                driver.find_element(By.CSS_SELECTOR, f'[data-appearance={theme}]').click()
                driver.execute_script('window.scrollTo(0,0)')
                time.sleep(.35)
                target = driver.find_element(By.CSS_SELECTOR, selector) if selector else None
                if target:
                    # Capture the real element via CDP, without sticky chrome covering it.
                    rect = driver.execute_script('const r=arguments[0].getBoundingClientRect();return {x:r.left+scrollX,y:r.top+scrollY,width:r.width,height:r.height}', target)
                    if max_height: rect['height'] = min(rect['height'], max_height)
                    import base64
                    raw = base64.b64decode(driver.execute_cdp_cmd('Page.captureScreenshot', dict(format='png', captureBeyondViewport=False,
                        clip=dict(rect, scale=1)))['data'])
                else:
                    raw = driver.get_screenshot_as_png()
                stem = f'{name}-{theme}'
                (masters / (stem + '.png')).write_bytes(raw)
                image_width, image_height = struct.unpack('>II', raw[16:24])
                sizes = sorted(set([min(640, image_width), min(1100, image_width), image_width]))
                for width in sizes:
                    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', str(masters / (stem + '.png')),
                        '-vf', f'scale={width}:-1:flags=lanczos', '-c:v', 'libwebp', '-quality', '88',
                        '-compression_level', '6', str(output / f'{stem}-{width}.webp')], check=True)
                manifest['screens'].append(dict(name=name, theme=theme, width=image_width, height=image_height,
                    sizes=sizes, route=driver.current_url.replace(base, ''), element=selector, master=stem + '.png'))
                print(f'Captured {stem}: {image_width} × {image_height}', flush=True)
        try:
            driver.get(base + '/admin/login')
            driver.find_element(By.NAME, 'email').send_keys('demo@example.test')
            driver.find_element(By.NAME, 'password').send_keys('demo-only-password')
            driver.find_element(By.CSS_SELECTOR, 'button[type=submit]').click()
            driver.get(base + '/admin/stations/sunroom-radio/live'); ready()
            wait.until(lambda d: d.find_element(By.ID, 'deck-b-state').text == 'READY')
            shot('booth', '.deck-workspace')
            shot('carts', '.cart-console')
            driver.find_element(By.ID, 'mic-tab').click()
            shot('microphone', '.mic-console')
            from app.extensions import db
            from app import models as m
            with app.app_context():
                state = db.session.get(m.AutomationState, ids['station']); state.operator_mode = 'AUTO'; state.hold = False
                snapshot = db.session.get(m.LiveQueueSnapshot, ids['station'])
                snapshot.mixer = dict(snapshot.mixer, mode='AUTO', auto_id=ids['current'], auto_playing=True)
                db.session.commit()
            driver.get(base + '/admin/stations/sunroom-radio/live'); ready()
            wait.until(lambda d: 'Golden Hour' in d.find_element(By.ID, 'auto-song').text)
            shot('auto', '.booth-header')
            for name, path, selector, height in [
                ('music', 'media', '.admin-content', 900),
                ('playlists', 'playlists', '.admin-content', 900),
                ('schedule', 'schedule-studio/calendar', '#schedule-studio', 1050),
                ('shows', 'schedule-studio/shows', '#schedule-studio', 1100),
                ('blocks', 'schedule-studio/blocks', '#schedule-studio', 1100),
                ('statistics', 'stats', '#statistics', 1250),
            ]:
                driver.get(base + '/admin/stations/sunroom-radio/' + path); ready()
                if name == 'music': wait.until(lambda d: len(d.find_elements(By.CSS_SELECTOR, '.room-song')) >= 6)
                if name == 'playlists': wait.until(lambda d: len(d.find_elements(By.CSS_SELECTOR, '.playlist-song')) >= 6)
                if name in ('shows', 'blocks'):
                    wait.until(lambda d: len(d.find_elements(By.CSS_SELECTOR, '#composition-select option')) > 1)
                    Select(driver.find_element(By.ID, 'composition-select')).select_by_value(str(ids['show' if name == 'shows' else 'block']))
                if name in ('shows', 'blocks', 'schedule'):
                    wait.until(lambda d: d.find_elements(By.CSS_SELECTOR, '.timeline-section'))
                if name == 'statistics':
                    wait.until(lambda d: d.find_element(By.ID, 'statistics').get_attribute('data-map-ready') == 'true')
                    driver.find_element(By.CSS_SELECTOR, '[data-map=all]').click()
                time.sleep(.5); shot(name, selector, height)
                if name == 'statistics': shot('geography', '.stats-card:has(#stats-map)')
            driver.get(base + '/player/sunroom-radio'); ready()
            wait.until(lambda d: 'Golden Hour' in d.find_element(By.ID, 'recent-history').text)
            shot('player', '.radio-experience', 1000)
            driver.execute_cdp_cmd('Emulation.setDeviceMetricsOverride', dict(width=390, height=844, deviceScaleFactor=1, mobile=False)); driver.execute_script('window.scrollTo(0,0)')
            shot('player-mobile')
            (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
        finally:
            driver.quit(); server.shutdown(); thread.join(timeout=3)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'app/static/product')
    parser.add_argument('--masters', type=Path, default=Path('/tmp/freo-product-masters'))
    args = parser.parse_args()
    capture(args.output.resolve(), args.masters.resolve())
