"""Real-browser station creation/deletion and all-channel library controls."""
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from app.extensions import db
from app.models import Station, Track
from app.services.music_catalog import organize_song
from tests.test_live_browser import booth, wait_text
from tests.test_web import app as app_fixture


def test_add_limit_delete_and_share_in_browser(booth):
    app,driver,base,tmp_path=booth
    driver.get(base+'/admin/stations')
    form=driver.find_element(By.CSS_SELECTOR,'form[action="/admin/stations/create"]')
    form.find_element(By.NAME,'name').send_keys('Browser station')
    form.find_element(By.NAME,'slug').send_keys('browser-station')
    form.find_element(By.CSS_SELECTOR,'button').click()
    wait_text(driver,'.admin-station-grid','Browser station')
    wait_text(driver,'.admin-card','Station limit reached')
    for width in (430,820,1440):
        driver.set_window_size(width,1000)
        assert driver.execute_script('return document.documentElement.scrollWidth <= innerWidth')
    driver.find_element(By.XPATH,"//article[h2='Browser station']//summary[.='Delete station']").click()
    form=driver.find_element(By.CSS_SELECTOR,'form[action="/admin/stations/browser-station/delete"]')
    form.find_element(By.NAME,'confirm').send_keys('browser-station')
    form.find_element(By.CSS_SELECTOR,'button').click()
    wait_text(driver,'.admin-station-grid','pending delete')
    with app.app_context():
        station=Station.query.filter_by(slug='browser-station').one()
        assert station.lifecycle_state=='pending_delete' and not station.enabled
        song=Track.query.first();organize_song(song);db.session.commit();identifier=song.uuid
    driver.get(base+f'/admin/stations/test-station/media/{identifier}')
    sharing=driver.find_element(By.CSS_SELECTOR,'form[action*="/media/sharing/song/"]')
    sharing.find_element(By.NAME,'available_to_all').click()
    sharing.find_element(By.CSS_SELECTOR,'button').click()
    WebDriverWait(driver,10).until(lambda d:'/media' in d.current_url and '/'+identifier not in d.current_url)
    driver.get(base+'/admin/stations/second-station/media')
    wait_text(driver,'body','Verified Test Track')


def test_deleted_monitor_station_is_cleared_on_station_list(booth):
    from app.services.stations import request_delete
    app,driver,base,tmp_path=booth
    driver.find_element(By.CSS_SELECTOR,'.master-monitor button').click()
    WebDriverWait(driver,10).until(lambda d:d.execute_script('return !FreoMonitor.audio.paused'))
    with app.app_context():
        request_delete(Station.query.filter_by(slug='test-station').one())
    driver.find_element(By.CSS_SELECTOR,'.admin-nav a[href="/admin/stations"]').click()
    WebDriverWait(driver,10).until(lambda d:d.execute_script('return FreoMonitor.audio.paused'))
    assert driver.find_element(By.CSS_SELECTOR,'.master-monitor button').get_attribute('disabled')
    assert 'Select a station' in driver.find_element(By.CSS_SELECTOR,'.monitor-state').text
