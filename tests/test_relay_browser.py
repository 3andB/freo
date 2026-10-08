from datetime import datetime, timezone
from selenium.common.exceptions import StaleElementReferenceException
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from app.extensions import db
from app.models import StationRelay, Station
from tests.test_live_browser import booth, app_fixture


def test_relay_settings_status_and_safe_metadata(booth):
    app,driver,base,folder=booth
    app.config['FREO_RELAY_PRIVATE_NETWORKS']='127.0.0.1/32'
    driver.get(base+'/admin/stations/test-station/settings')
    assert driver.execute_script("return !!document.querySelector('#relay-settings').closest('.settings-workspace')")
    driver.find_element(By.NAME,'relay_url').send_keys('http://127.0.0.1:9000/audio')
    driver.find_element(By.NAME,'relay_enabled').click()
    driver.find_element(By.CSS_SELECTOR,'#relay-settings button').click()
    WebDriverWait(driver,10).until(lambda d:'Enabled' in d.find_element(By.ID,'relay-status').text)
    with app.app_context():
        row=StationRelay.query.one();row.applied_revision=row.revision;row.observed_at=datetime.now(timezone.utc)
        row.observation=dict(connected=True,ready=True,selected=True,source='relay',title='<img src=x onerror=alert(1)>',artist='Stream artist')
        db.session.commit()
    WebDriverWait(driver,10).until(lambda d:'Connected' in d.find_element(By.ID,'relay-status').text)
    assert '<img' in driver.find_element(By.ID,'relay-metadata').text
    assert not driver.find_elements(By.CSS_SELECTOR,'#relay-metadata img')
    driver.set_window_size(390,844)
    assert driver.execute_script('return document.documentElement.scrollWidth <= innerWidth')
    driver.execute_script("document.querySelector('#relay-settings').scrollIntoView()")
    driver.save_screenshot(str(folder/'relay-settings-mobile.png'))
    driver.find_element(By.NAME,'relay_enabled').click()
    driver.find_element(By.CSS_SELECTOR,'#relay-settings button').click()
    WebDriverWait(driver,10,ignored_exceptions=(StaleElementReferenceException,)).until(lambda d:'Disabled' in d.find_element(By.ID,'relay-status').text)
