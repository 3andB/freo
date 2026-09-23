"""Configuration stays in the existing admin UI, without starting a reporter."""
from selenium.webdriver.common.by import By
from app.extensions import db
from app.models import CentralInstallation, Station
from tests.test_live_browser import booth, app_fixture, wait_text


def test_installation_setup_and_station_location(booth):
    app, driver, base, tmp = booth
    driver.find_element(By.CSS_SELECTOR, '.admin-nav a[href="/admin"]').click()
    wait_text(driver, 'h1', 'Operations overview')
    driver.find_element(By.CSS_SELECTOR, '.admin-nav a[href="/admin/installation"]').click()
    wait_text(driver, '.admin-content h1', 'Freo installation')
    wait_text(driver, '.admin-content', 'Freo automatically contacts api.freo.live')
    assert not driver.find_elements(By.NAME, 'manager_email')
    driver.find_element(By.NAME, 'activation_code').send_keys('FREO-7K4P-M9Q2')
    driver.find_element(By.CSS_SELECTOR, '.admin-content button[type=submit]').click()
    wait_text(driver, '.admin-content', 'An activation code is queued')
    with app.app_context():
        assert db.session.get(CentralInstallation, 1).registration_state == 'activation_queued'
        assert db.session.get(CentralInstallation, 1).installation_id is None
        identity = db.session.get(Station, 1).freo_station_id
    driver.get(base + '/admin/stations/test-station/settings')
    for name, value in [('city', 'Perth'), ('region', 'Western Australia'), ('country', 'au'),
                        ('genre', 'Rock'), ('directory_categories', 'Independent, Community')]:
        field = driver.find_element(By.NAME, name)
        field.clear()
        field.send_keys(value)
    driver.find_element(By.NAME, 'directory_opt_in').click()
    driver.find_element(By.CSS_SELECTOR, '#station-settings-form .settings-save-bar button').click()
    wait_text(driver, '#station-save-status', 'All changes saved')
    driver.refresh()
    assert driver.find_element(By.NAME, 'country').get_attribute('value') == 'AU'
    assert identity in driver.find_element(By.CSS_SELECTOR, '.station-settings').text
    driver.set_window_size(390, 1000)
    assert driver.execute_script('return document.documentElement.scrollWidth <= innerWidth + 2')
    with app.app_context():
        station = db.session.get(Station, 1)
        assert station.country == 'AU' and station.directory_opt_in
        assert station.freo_station_id == identity
