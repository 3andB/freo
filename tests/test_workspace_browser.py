"""Persistent audio and modern station workflows in a real browser."""
from datetime import datetime, timezone
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.common.exceptions import StaleElementReferenceException
from app.extensions import db
from app.models import Station, Track, SelectionDecision, LiveQueueSnapshot, LiveCartSlot
from tests.test_live_browser import booth, wait_text
from tests.test_web import app as app_fixture


def test_monitor_survives_navigation_and_preview_requires_reactivation(booth):
    app,driver,base,tmp_path=booth
    driver.find_element(By.CSS_SELECTOR,'.master-monitor button').click()
    WebDriverWait(driver,10).until(lambda d:d.execute_script('return !FreoMonitor.audio.paused'))
    driver.execute_script('window.originalMonitor=FreoMonitor.audio')
    driver.find_element(By.CSS_SELECTOR,'.admin-nav a[href$="/categories"]').click()
    WebDriverWait(driver,10).until(lambda d:'/categories' in d.current_url and d.find_elements(By.CSS_SELECTOR,'.list-card'))
    assert driver.execute_script('return originalMonitor===FreoMonitor.audio && !FreoMonitor.audio.paused')
    driver.back()
    WebDriverWait(driver,10).until(lambda d:d.find_elements(By.ID,'dj-booth'))
    assert driver.execute_script('return originalMonitor===FreoMonitor.audio && !FreoMonitor.audio.paused')
    driver.execute_script("const preview=document.createElement('audio');preview.src='/stream/test-station';document.body.append(preview);preview.play()")
    WebDriverWait(driver,8).until(lambda d:d.execute_script('return FreoMonitor.audio.paused'))
    driver.execute_script("document.querySelectorAll('audio').forEach(audio=>audio.pause())")
    assert driver.find_element(By.CSS_SELECTOR,'.master-monitor button').get_attribute('aria-pressed')=='false'


def test_song_cart_assignment_description_and_modes_in_custom_dialog(booth):
    app,driver,base,tmp_path=booth
    driver.find_element(By.CSS_SELECTOR,'[data-role="HOT"] [data-assign]').click()
    form=driver.find_element(By.ID,'cart-assign-form')
    form.find_element(By.NAME,'label').send_keys('Morning hello')
    form.find_element(By.NAME,'description').send_keys('Welcome to the morning show')
    Select(form.find_element(By.NAME,'playback_mode')).select_by_value('TAKEOVER')
    assert 'resumes from the same position' in driver.find_element(By.ID,'cart-mode-explanation').text
    form.find_element(By.CSS_SELECTOR,'button[type=submit]').click()
    WebDriverWait(driver,10,ignored_exceptions=(StaleElementReferenceException,)).until(lambda d:not d.find_element(By.ID,'cart-assign-dialog').is_displayed())
    wait_text(driver,'[data-role="HOT"]','Morning hello')
    with app.app_context():
        slot=LiveCartSlot.query.filter_by(role='HOT',position=1).first()
        assert slot.track_id==Track.query.first().id and slot.description=='Welcome to the morning show'
        assert slot.playback_mode=='TAKEOVER'


def test_calendar_create_edit_and_mobile_layout(booth):
    app,driver,base,tmp_path=booth
    driver.get(base+'/admin/stations/test-station/calendar?date=2026-09-14')
    driver.find_element(By.XPATH,"//nav[@id='source-tabs']/button[text()='Songs']").click()
    wait_text(driver,'#source-results','Verified Test Track')
    driver.find_element(By.CSS_SELECTOR,'.source-actions button').click()
    driver.find_element(By.CSS_SELECTOR,'#section-form button[type=submit]').click()
    driver.find_element(By.ID,'save-schedule').click()
    wait_text(driver,'#save-state','Saved')
    wait_text(driver,'#timeline','Verified Test Track')
    driver.find_element(By.CSS_SELECTOR,'.timeline-section[aria-label^="Verified Test Track"]').click()
    assert 'Verified Test Track' in driver.find_element(By.ID,'section-source').get_attribute('value')
    driver.find_element(By.CSS_SELECTOR,'#section-inspector .dialog-close').click()
    for width in (430,820,1440):
        driver.set_window_size(width,1000)
        assert driver.execute_script('return document.documentElement.scrollWidth<=innerWidth')


def test_capture_demonstration_screens_when_requested(booth):
    import os
    import pytest
    if os.environ.get('FREO_CAPTURE_PRODUCT') != '1':
        pytest.skip('Product screenshots are captured explicitly from demonstration fixtures')
    from pathlib import Path
    from datetime import timedelta
    from app.services.calendar import create_program
    app,driver,base,tmp_path=booth
    with app.app_context():
        station=Station.query.filter_by(slug='test-station').first();station.name='Sunroom Radio'
        track=Track.query.first();track.title='Golden Hour';track.artist='The Daydreams';track.album='A Little More Sunshine';track.duration_ms=260000;track.bpm=112
        current=SelectionDecision.query.filter_by(status='started').first();current.started_at=datetime.now(timezone.utc)-timedelta(seconds=72)
        import uuid
        cue=Track(station_id=station.id,uuid=str(uuid.uuid4()),title='After the Rain',artist='Milo Coast',album='Night Swimming',duration_ms=230000,bpm=118,original_filename='demo.mp3',storage_key='b'*32+'.mp3',media_type='mp3',sample_rate_hz=44100,channels=2,file_size_bytes=1000,checksum_sha256='b'*64,enabled=True,ingest_status='accepted')
        db.session.add(cue);db.session.flush();station.automation.cued_track_id=cue.id
        prepared=SelectionDecision(station_id=station.id,track=cue,playback_bus='B',status='queued',selection_method='manual_track');db.session.add(prepared);db.session.flush()
        snapshot=LiveQueueSnapshot.query.first();snapshot.observed_at=datetime.now(timezone.utc)
        snapshot.program_rms=.18;snapshot.mixer={'mode':'DJ_BOOTH','crossfader':0,'a_playing':True,'b_playing':False,'a_id':current.id,'b_id':prepared.id,'cart_id':None,'a_elapsed':72,'b_elapsed':0}
        for name,start,end in [('Morning discoveries','06:00','12:00'),('Afternoon sunshine','12:00','18:00'),('After hours','22:00','02:00')]:
            create_program(station,name=name,weekdays=[str(i) for i in range(7)],start=start,end=end,category_slug='power')
        db.session.commit()
    driver.set_window_size(1440,1240)
    driver.get(base+'/admin/stations/test-station/live')
    try:
        wait_text(driver,'#morph-text','Golden Hour')
    except Exception:
        print(driver.execute_script('return {title:document.getElementById("morph-text").textContent,status:document.getElementById("live-playout").textContent,body:document.getElementById("dj-booth").className}'))
        print(driver.get_log('browser'))
        raise
    driver.save_screenshot('/opt/freo/app/static/product-dj.png')
    driver.get(base+'/admin/stations/test-station/calendar?date=2026-09-14')
    wait_text(driver,'.calendar-grid','Morning discoveries')
    driver.save_screenshot('/opt/freo/app/static/product-schedule.png')
    assert Path('/opt/freo/app/static/product-dj.png').stat().st_size>10000


def test_programming_event_series_and_content_picker(booth):
    app,driver,base,tmp_path=booth
    driver.get(base+'/admin/stations/test-station/events/create?date=2027-01-04')
    form=driver.find_element(By.CSS_SELECTOR,'.event-editor form')
    Select(form.find_element(By.NAME,'recurrence_type')).select_by_value('WEEKLY')
    form.find_element(By.NAME,'name').send_keys('Weekday announcement')
    for day in ('0','2','4'):
        form.find_element(By.CSS_SELECTOR,f'[name="weekdays"][value="{day}"]').click()
    driver.execute_script("arguments[0].value='10:15:00'",form.find_element(By.NAME,'local_time'))
    with app.app_context():
        identifier=Track.query.first().uuid
    wait_text(driver,'#event-audio-results','Verified Test Track')
    driver.find_element(By.CSS_SELECTOR,'#event-audio-results button').click()
    assert form.find_element(By.NAME,'content_identifier').get_attribute('value')==identifier
    assert form.find_element(By.NAME,'late_tolerance_seconds').get_attribute('value')=='300'
    form.find_element(By.CSS_SELECTOR,'button[type=submit]').click()
    WebDriverWait(driver,10).until(lambda d:'/events/create' not in d.current_url)
    assert 'Weekday announcement' in driver.find_element(By.TAG_NAME,'h1').text
    driver.get(base+'/admin/stations/test-station/calendar?date=2027-01-04')
    WebDriverWait(driver,10).until(lambda d:len(d.find_elements(By.CSS_SELECTOR,'.timeline-event'))==3)
    for width in (430,820,1440):
        driver.set_window_size(width,1000)
        assert driver.execute_script('return document.documentElement.scrollWidth<=innerWidth')
    driver.save_screenshot('/tmp/freo-programming-calendar.png')


def test_now_playing_persists_without_monitor_and_handles_stale_state(booth):
    app, driver, base, tmp_path = booth
    wait_text(driver, '[data-now-title]', 'Verified Test Track')
    wait_text(driver, '[data-now-artist]', 'Test Artist')
    assert driver.execute_script('return FreoMonitor.audio.paused')
    driver.find_element(By.CSS_SELECTOR, '.admin-nav a[href$="/categories"]').click()
    wait_text(driver, '[data-now-title]', 'Verified Test Track')
    with app.app_context():
        snapshot = LiveQueueSnapshot.query.first()
        snapshot.error_code = 'Connection unavailable'
        db.session.commit()
    wait_text(driver, '[data-now-label]', 'Last known')
    wait_text(driver, '[data-now-title]', 'Verified Test Track')
    with app.app_context():
        snapshot = LiveQueueSnapshot.query.first()
        snapshot.error_code = None
        snapshot.current_decision_id = None
        snapshot.mixer = {}
        db.session.commit()
    wait_text(driver, '[data-now-label]', 'Nothing playing')
    assert driver.find_element(By.CSS_SELECTOR, '[data-now-title]').text == '—'
    driver.set_window_size(390, 844)
    assert driver.find_element(By.CSS_SELECTOR, '[data-now-playing]').is_displayed()
    assert driver.execute_script('return document.documentElement.scrollWidth <= innerWidth')
    driver.set_window_size(1600, 1200)
    with app.app_context():
        snapshot = LiveQueueSnapshot.query.first()
        current = SelectionDecision.query.filter_by(status='started').first()
        snapshot.mixer = dict(a_id=current.id, a_playing=False, b_id=None, b_playing=False)
        db.session.commit()
    wait_text(driver, '[data-now-label]', 'Paused')
    wait_text(driver, '[data-now-title]', 'Verified Test Track')
    driver.find_element(By.CSS_SELECTOR, '.admin-nav a[href*="/media"]').click()
    wait_text(driver, '.song-row-copy', '1 plays')
    wait_text(driver, '#room-categories', '1 plays')
    Select(driver.find_element(By.ID, 'station-select')).select_by_visible_text('Second Station')
    driver.find_element(By.CSS_SELECTOR, '.station-picker button').click()
    WebDriverWait(driver, 10).until(lambda d:'second-station' in d.current_url)
    wait_text(driver, '[data-now-label]', 'Playback unavailable')
    assert driver.find_element(By.CSS_SELECTOR, '[data-now-title]').text == '—'
