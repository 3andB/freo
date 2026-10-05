"""Show opt-in and DJ access in the existing booth UI."""
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from app.extensions import db
from app.models import AdminUser, DJStationAssignment, LiveSession, LiveQueueSnapshot, Station
from app.services.live_sessions import claim, now
from tests.test_live_browser import booth, app_fixture


def test_record_choice_and_end_show_use_existing_booth(booth):
    app,driver,base,_=booth
    record=driver.find_element(By.ID,'record-show')
    assert not record.is_selected()
    record.click()
    driver.find_element(By.CSS_SELECTOR,'.mode-button[data-mode="DJ_BOOTH"]').click()
    WebDriverWait(driver,10).until(lambda d:not d.find_element(By.ID,'record-show').is_enabled())
    with app.app_context():
        show=LiveSession.query.one()
        assert show.record_requested and show.recording and not show.started_at
    driver.find_element(By.ID,'end-show').click()
    def ended(_):
        with app.app_context():return LiveSession.query.one().end_requested
    WebDriverWait(driver,10).until(ended)
    WebDriverWait(driver,10).until(lambda d:'Waiting for engine confirmation' in d.find_element(By.ID,'booth-notice').text)
    with app.app_context():
        show=LiveSession.query.one();show.active_station_id=None;show.ended_at=now()
        snapshot=LiveQueueSnapshot.query.first();snapshot.show_observation={'source':'AUTO','observed_at':now().isoformat()}
        db.session.commit()
    WebDriverWait(driver,10).until(lambda d:d.find_element(By.ID,'record-show').is_enabled())
    assert not driver.find_element(By.ID,'record-show').is_selected()


def test_dj_navigation_and_other_owner_are_read_only(booth):
    app,driver,base,_=booth
    with app.app_context():
        user=AdminUser.query.first();station=Station.query.filter_by(slug='test-station').one()
        user.role='DJ';db.session.add(DJStationAssignment(admin_user_id=user.id,station_id=station.id))
        owner=AdminUser(email='owner@example.test',username='Other DJ',password_hash='unused')
        db.session.add(owner);db.session.commit();claim(station,owner);db.session.commit()
    driver.refresh()
    WebDriverWait(driver,10).until(lambda d:d.find_element(By.ID,'dj-booth').get_attribute('data-show-locked')=='true')
    links=[a.text for a in driver.find_elements(By.CSS_SELECTOR,'.admin-nav a')]
    assert 'DJ Booth' in links and 'My recordings' in links and 'Station settings' not in links
    assert not driver.find_element(By.ID,'end-show').is_enabled()
    assert not driver.find_element(By.CSS_SELECTOR,'.mode-button[data-mode="AUTO"]').is_enabled()
    assert not driver.find_element(By.CSS_SELECTOR,'[data-load-deck="A"]').is_enabled()
    with app.app_context():
        show=LiveSession.query.one();show.active_station_id=None;show.ended_at=now();db.session.commit()
    WebDriverWait(driver,10).until(lambda d:d.find_element(By.CSS_SELECTOR,'[data-load-deck="A"]').is_enabled())
    assert driver.find_element(By.CSS_SELECTOR,'[data-open-assign]').is_enabled()


def test_create_fake_dj_login_and_manage_local_mp3(booth):
    import shutil
    from app.models import ShowRecording
    from app.services.recording_manager import process_deletions
    app, driver, base, directory = booth
    driver.get(base+'/admin/djs')
    driver.find_element(By.NAME,'username').send_keys('Browser DJ')
    driver.find_element(By.NAME,'email').send_keys('browser-dj@example.test')
    driver.find_element(By.NAME,'password').send_keys('browser-isolated-password')
    form = driver.find_element(By.NAME,'email').find_element(By.XPATH,'ancestor::form')
    form.find_element(By.CSS_SELECTOR,'input[name=station_id][value="1"]').click()
    form.find_element(By.CSS_SELECTOR,'button').click()
    WebDriverWait(driver,10).until(lambda d:'DJ access saved' in d.find_element(By.TAG_NAME,'body').text)
    with app.app_context():
        user=AdminUser.query.filter_by(email='browser-dj@example.test').one()
        assert user.active and user.role=='DJ'
        show=LiveSession(station_id=1,admin_user_id=user.id,dj_name=user.username,started_at=now(),ended_at=now())
        recording=ShowRecording(session=show,station_id=1,admin_user_id=user.id,storage_key='b'*32+'.mp3',
                                status='complete',duration_ms=4000,started_at=now(),ended_at=now())
        path=directory/'media'/'test-station'/'recordings'/recording.storage_key;path.parent.mkdir()
        shutil.copyfile(directory/'media'/'test-station'/'originals'/('a'*32+'.mp3'),path)
        recording.file_size_bytes=path.stat().st_size
        db.session.add(recording);db.session.commit();identifier=recording.id
    driver.find_element(By.CSS_SELECTOR,'form[action="/admin/logout"] button').click()
    WebDriverWait(driver,10).until(lambda d:d.current_url.rstrip('/')==base)
    driver.get(base+'/admin/login')
    driver.find_element(By.NAME,'email').send_keys('Browser DJ')
    driver.find_element(By.NAME,'password').send_keys('browser-isolated-password')
    driver.find_element(By.CSS_SELECTOR,'.login-card button[type=submit]').click()
    WebDriverWait(driver,10).until(lambda d:d.find_elements(By.ID,'dj-booth'))
    driver.find_element(By.CSS_SELECTOR,'#license-accept-form input[name=agree]').click()
    driver.find_element(By.CSS_SELECTOR,'#license-accept-form button[type=submit]').click()
    WebDriverWait(driver,10).until(lambda d:not d.find_element(By.ID,'license-agreement').is_displayed())
    driver.get(base+'/admin/stations/second-station/live')
    assert 'Forbidden' in driver.find_element(By.TAG_NAME,'body').text
    driver.get(base+'/admin/djs')
    assert 'Forbidden' in driver.find_element(By.TAG_NAME,'body').text
    listing=base+'/admin/stations/test-station/recordings'
    driver.get(listing)
    field=driver.find_element(By.NAME,'name');field.clear();field.send_keys('Browser Friday')
    driver.find_element(By.CSS_SELECTOR,'form[action$="/rename"] button').click()
    WebDriverWait(driver,10).until(lambda d:'Browser Friday.mp3' in d.find_element(By.TAG_NAME,'h2').text)
    audio=driver.find_element(By.TAG_NAME,'audio')
    driver.execute_script('arguments[0].load()',audio)
    WebDriverWait(driver,10).until(lambda d:d.execute_script('return arguments[0].readyState',audio)>=2)
    assert driver.execute_script('return arguments[0].duration',audio)>3
    download=driver.find_element(By.LINK_TEXT,'Download MP3').get_attribute('href')
    result=driver.execute_async_script('const done=arguments[arguments.length-1];fetch(arguments[0]).then(async r=>done({status:r.status,name:r.headers.get("Content-Disposition"),size:(await r.blob()).size}));',download)
    assert result['status']==200 and 'Browser Friday.mp3' in result['name'] and result['size']==path.stat().st_size
    driver.save_screenshot(str(directory/'recording-manager.png'))
    driver.set_window_size(390,844)
    assert driver.execute_script('return document.documentElement.scrollWidth <= innerWidth')
    driver.save_screenshot(str(directory/'recording-manager-mobile.png'))
    driver.set_window_size(1600,1200)
    driver.find_element(By.NAME,'confirm').click()
    driver.find_element(By.CSS_SELECTOR,'form[action$="/delete"] button').click()
    WebDriverWait(driver,10).until(lambda d:'Deletion queued' in d.find_element(By.TAG_NAME,'body').text)
    with app.app_context():process_deletions()
    driver.refresh()
    assert 'No recordings found' in driver.find_element(By.TAG_NAME,'body').text and not path.exists()


import pytest


@pytest.mark.parametrize('scenario', ['decks', 'cue', 'carts', 'mic'])
def test_existing_booth_workflows_with_real_dj_login(booth, scenario):
    from tests.test_recording_manager import login, token, PASSWORD
    from tests import test_live_browser, test_cue_browser, test_booth_state_browser, test_live_mic_browser
    app,driver,base,_=booth
    admin=login(app,'admin@example.test','test-password-long-enough')
    assert admin.post('/admin/djs',data=dict(csrf=token(admin),email='booth-dj@example.test',
        username='Booth DJ',password=PASSWORD,station_id='1',active='yes')).status_code==302
    driver.find_element(By.CSS_SELECTOR,'form[action="/admin/logout"] button').click()
    WebDriverWait(driver,10).until(lambda d:d.current_url.rstrip('/')==base)
    driver.get(base+'/admin/login')
    driver.find_element(By.NAME,'email').send_keys('booth-dj@example.test')
    driver.find_element(By.NAME,'password').send_keys(PASSWORD)
    driver.find_element(By.CSS_SELECTOR,'.login-card button[type=submit]').click()
    WebDriverWait(driver,10).until(lambda d:d.find_elements(By.ID,'dj-booth'))
    driver.find_element(By.CSS_SELECTOR,'#license-accept-form input[name=agree]').click()
    driver.find_element(By.CSS_SELECTOR,'#license-accept-form button[type=submit]').click()
    WebDriverWait(driver,10).until(lambda d:not d.find_element(By.ID,'license-agreement').is_displayed())
    # Reuse the established behavior assertions with a real DJ session instead
    # of giving the browser administrator powers for these acceptance checks.
    if scenario=='decks':test_live_browser.test_picker_load_clear_and_artwork_drag(booth)
    elif scenario=='cue':test_cue_browser.test_cue_add_reorder_save_load_new_and_deck_binding(booth)
    elif scenario=='carts':test_booth_state_browser.test_cart_glow_global_lock_and_completion_in_both_modes(booth,False)
    else:test_live_mic_browser.test_live_mic_board_preserves_feed_and_shares_carts(booth)
