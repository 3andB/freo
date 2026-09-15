import shutil
import tempfile
import threading
from werkzeug.serving import make_server
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.common.exceptions import StaleElementReferenceException
from selenium.webdriver.support.ui import WebDriverWait
from app.extensions import db
from app.models import AutomationState, SelectionDecision, Station
from tests.test_web import app as app_fixture


def test_real_chromium_pointer_drag_cues_deck_b(app_fixture, monkeypatch):
    app=app_fixture
    monkeypatch.setattr('app.services.media_storage.LocalMediaStorage.regular_file',lambda *args:'/safe')
    server=make_server('127.0.0.1',0,app,threaded=True);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    profile_dir = tempfile.mkdtemp(prefix='freo-chromium-', dir='/tmp')
    options=Options();options.binary_location='/usr/bin/chromium-browser';options.add_argument('--headless=new');options.add_argument('--no-sandbox');options.add_argument('--disable-dev-shm-usage');options.add_argument('--window-size=1600,1200');options.add_argument(f'--user-data-dir={profile_dir}')
    driver=webdriver.Chrome(service=Service('/usr/bin/chromedriver'),options=options)
    try:
        with app.app_context():
            station = Station.query.filter_by(slug='test-station').first()
            automation = db.session.get(AutomationState, station.id)
            automation.operator_mode = 'DJ_BOOTH'
            automation.hold = True
            db.session.commit()
        base=f'http://127.0.0.1:{server.server_port}'
        driver.get(base+'/admin/login')
        driver.find_element(By.NAME,'email').send_keys('admin@example.test');driver.find_element(By.NAME,'password').send_keys('test-password-long-enough');driver.find_element(By.CSS_SELECTOR,'.login-card button[type=submit]').click()
        driver.get(base+'/admin/stations/test-station/live')
        WebDriverWait(driver,5).until(lambda d:d.find_element(By.CSS_SELECTOR,'.song-card').is_displayed())
        driver.find_elements(By.CSS_SELECTOR,'.cue-picker-button')[1].click()
        search = WebDriverWait(driver,5).until(lambda d:d.find_element(By.ID,'song-picker-search'))
        search.send_keys('Verified Test')
        WebDriverWait(driver,5).until(
            lambda d:'Verified Test Track' in d.find_element(By.ID,'song-picker-results').text)
        driver.execute_script("document.getElementById('song-picker-dialog').close()")
        song=driver.find_element(By.CSS_SELECTOR,'.song-card');deck=driver.find_element(By.ID,'cue-drop')
        ActionChains(driver).move_to_element(song).click_and_hold().pause(.3).move_to_element(deck).pause(.8).release().perform()
        WebDriverWait(driver,8,ignored_exceptions=(StaleElementReferenceException,)).until(
            lambda d:d.find_element(By.ID,'cue-title').text=='Verified Test Track')
        with app.app_context():
            station=Station.query.filter_by(slug='test-station').first()
            assert station.automation.cued_track.title=='Verified Test Track'
            assert SelectionDecision.query.filter_by(station_id=station.id,reason='operator_cue').count()==1
    finally:
        driver.quit();server.shutdown();thread.join(timeout=3);shutil.rmtree(profile_dir, ignore_errors=True)
