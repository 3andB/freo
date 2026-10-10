"""Configuration stays in the existing admin UI, without starting a reporter."""
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from app.extensions import db
from app.models import CentralInstallation, Station
from tests.test_live_browser import booth, app_fixture, wait_text


def test_installation_setup_and_station_location(booth):
    app, driver, base, tmp = booth
    driver.find_element(By.CSS_SELECTOR, '.admin-nav a[href="/admin"]').click()
    wait_text(driver, 'h1', 'Operations overview')
    WebDriverWait(driver, 10).until(lambda d: d.execute_script(
        "return !document.documentElement.classList.contains('is-navigating')"))
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
    directory = driver.find_element(By.NAME, 'directory_opt_in')
    driver.execute_script('arguments[0].scrollIntoView({block:"center"})', directory)
    directory.click()
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


def test_version_statuses_release_link_and_first_release_in_browser(booth):
    import time
    from app.services.central_api import installation
    from app.version import VERSION
    from tests.test_central_api import iso
    app, driver, base, tmp = booth
    for status, available, label in [('CURRENT', False, 'Current'),
            ('UPDATE_AVAILABLE', True, 'Update Available'), ('AHEAD', False, 'Ahead'),
            ('UNKNOWN', None, 'Unknown')]:
        with app.app_context():
            row = installation()
            latest = None if status == 'UNKNOWN' else '1.0.0'
            row.state = dict(last_heartbeat=dict(freo_version=VERSION, installed_version=VERSION,
                latest_version=latest, version_status=status, update_available=available,
                server_time=iso(time.time()), next_heartbeat_seconds=3600),
                release_discovery=dict(latest_version=latest, checked_at='2026-09-23T12:00:00Z',
                    release_url='https://github.com/3andB/freo/releases/tag/v1.0.0' if latest else None))
            db.session.commit()
        driver.get(base + '/admin/installation')
        wait_text(driver, '.installation-settings', VERSION)
        rows = driver.find_elements(By.CSS_SELECTOR, '.installation-settings .detail-list div')
        assert next(r for r in rows if r.find_element(By.TAG_NAME, 'dt').text == 'Version status').find_element(By.TAG_NAME, 'dd').text == label
        assert ('An update is available' in driver.find_element(By.CSS_SELECTOR, '.installation-settings').text) is (available is True)
        driver.get(base + '/admin')
        wait_text(driver, '[data-connection="update_status"]', label)
        assert driver.find_element(By.CSS_SELECTOR, '[data-version-notice]').is_displayed() is (available is True)
        link = driver.find_element(By.CSS_SELECTOR, '[data-release-link]')
        assert link.is_displayed() is (latest is not None)
        if latest:
            assert link.get_attribute('href') == 'https://github.com/3andB/freo/releases/tag/v1.0.0'
        else:
            assert driver.find_element(By.CSS_SELECTOR, '[data-connection="latest_version"]').text == 'Unknown'
        for width in (390, 820, 1440):
            driver.set_window_size(width, 1000)
            assert driver.execute_script('return document.documentElement.scrollWidth <= innerWidth + 1')
