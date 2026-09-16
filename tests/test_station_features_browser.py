"""Actual browser interactions against an isolated database and observer."""
from datetime import datetime, timezone
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from app.extensions import db
from app.models import Station, Track, SelectionDecision, LiveQueueSnapshot, LiveControlCommand, SongFlag
from tests.test_live_browser import booth, app_fixture, wait_text


def test_auto_header_capture_flags_music_and_mobile(booth):
    app,driver,base,tmp_path=booth
    with app.app_context():
        station=Station.query.filter_by(slug='test-station').one()
        station.automation.operator_mode='AUTO';station.automation.hold=False
        track=Track.query.first()
        next_item=SelectionDecision(station_id=station.id,track_id=track.id,status='queued')
        db.session.add(next_item);db.session.flush();next_id=next_item.id
        snapshot=LiveQueueSnapshot.query.first();snapshot.queued_decision_ids=[next_id];snapshot.mixer={}
        db.session.commit()
    driver.refresh()
    wait_text(driver,'#auto-next','Test Artist — Verified Test Track')
    driver.save_screenshot('/tmp/freo-auto-controls.png')
    assert driver.find_element(By.ID,'auto-skip').is_displayed()
    assert driver.find_element(By.ID,'auto-flag').is_enabled()
    driver.find_element(By.ID,'auto-flag').click()
    WebDriverWait(driver,8).until(lambda d:d.find_element(By.ID,'song-flag-note').is_enabled() and d.find_element(By.ID,'song-flag-save').is_enabled())
    driver.find_element(By.ID,'song-flag-note').send_keys('Intro needs review')
    # Changing the observer while typing must not change the captured song.
    with app.app_context():
        snapshot=LiveQueueSnapshot.query.first();snapshot.current_decision_id=None;db.session.commit()
    driver.find_element(By.ID,'song-flag-save').click()
    WebDriverWait(driver,8).until(lambda d:not d.find_element(By.ID,'song-flag-dialog').is_displayed())
    with app.app_context():
        flag=SongFlag.query.one();assert flag.note=='Intro needs review' and flag.track_id==Track.query.first().id
        snapshot=LiveQueueSnapshot.query.first();snapshot.current_decision_id=SelectionDecision.query.filter_by(status='started').one().id;db.session.commit()
    WebDriverWait(driver,8).until(lambda d:d.find_element(By.ID,'auto-skip').is_enabled())
    driver.find_element(By.ID,'auto-skip').click()
    wait_text(driver,'#auto-skip','FADE REQUESTED')
    assert not driver.find_element(By.ID,'auto-skip').is_enabled()
    with app.app_context():
        assert LiveControlCommand.query.filter_by(action='SKIP').count()==1
        snapshot=LiveQueueSnapshot.query.first();snapshot.queued_decision_ids=[];db.session.commit()
    wait_text(driver,'#auto-next','Queue is empty')
    driver.set_window_size(390,844)
    assert driver.find_element(By.ID,'auto-next').is_displayed()
    assert driver.execute_script('return document.documentElement.scrollWidth <= innerWidth + 2')
    driver.save_screenshot('/tmp/freo-auto-mobile.png')
    driver.set_window_size(1600,1200)
    driver.get(base+'/admin/stations/test-station/media')
    wait_text(driver,'#flagged-count','1')
    driver.find_element(By.ID,'room-flagged').click()
    wait_text(driver,'#collection-title','Flagged songs')
    wait_text(driver,'#room-songs','💬 Flagged')
    driver.find_element(By.CSS_SELECTOR,'.song-flag-button').click()
    WebDriverWait(driver,8).until(lambda d:d.find_element(By.ID,'song-flag-resolve').is_displayed())
    driver.find_element(By.ID,'song-flag-resolve').click()
    wait_text(driver,'#room-total','0 songs')
    driver.find_element(By.ID,'room-resolved').click()
    wait_text(driver,'#room-songs','💬 Resolved')
    driver.find_element(By.CSS_SELECTOR,'.song-flag-button').click()
    WebDriverWait(driver,8).until(lambda d:d.find_element(By.ID,'song-flag-reopen').is_displayed())
    driver.find_element(By.ID,'song-flag-reopen').click()
    wait_text(driver,'#room-total','0 songs')
    driver.find_element(By.ID,'room-all').click()
    wait_text(driver,'#room-songs','1 plays')
    driver.find_element(By.CSS_SELECTOR,'.song-row-copy b').click()
    wait_text(driver,'#song-inspector','Confirmed plays')


def test_settings_navigation_and_persistence(booth):
    app,driver,base,tmp_path=booth
    driver.find_element(By.LINK_TEXT,'Station settings').click()
    WebDriverWait(driver,8).until(lambda d:d.find_elements(By.NAME,'city'))
    for name,value in [('name','Harbour Radio'),('city','Fremantle'),('region','WA'),('contact_email','private@example.test'),('phone','08 1234 5678'),('description','Music by the sea'),('public_slug','harbour-radio')]:
        field=driver.find_element(By.NAME,name);field.clear();field.send_keys(value)
    driver.find_element(By.CSS_SELECTOR,'.station-settings button[type=submit]').click()
    wait_text(driver,'.admin-notice','Station settings saved')
    assert driver.find_element(By.ID,'station-public-url').get_attribute('value').endswith('/player/harbour-radio')
    driver.save_screenshot('/tmp/freo-station-settings.png')
    driver.find_element(By.LINK_TEXT,'Overview').click()
    wait_text(driver,'.hero-title-line','Harbour Radio')
    wait_text(driver,'.admin-hero-copy','Fremantle, WA')
    driver.find_element(By.LINK_TEXT,'Stations').click()
    wait_text(driver,'.admin-station-grid','Harbour Radio')
    driver.get(base+'/player/harbour-radio')
    wait_text(driver,'.radio-description','Music by the sea')
    assert 'private@example.test' not in driver.page_source
