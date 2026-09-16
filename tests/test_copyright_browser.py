"""Public reporting link and metadata editor in the existing browser fixture."""
from datetime import datetime, timezone
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from app.extensions import db
from app.models import DMCACase, LiveQueueSnapshot, Track
from tests.test_live_browser import booth, app_fixture, wait_text


def test_player_report_and_isrc_editor(booth):
    app, driver, base, tmp = booth
    with app.app_context():
        track = Track.query.first()
        public_id, uuid = track.freo_track_id, track.uuid
        LiveQueueSnapshot.query.first().observed_at = datetime.now(timezone.utc)
        db.session.commit()
    driver.get(base + '/player/test-station')
    wait_text(driver, '#freo-track-id', public_id)
    assert driver.find_element(By.ID, 'copyright-track').is_displayed()
    driver.find_element(By.ID, 'copyright-report').click()
    WebDriverWait(driver, 8).until(lambda d:d.find_elements(By.ID, 'supplied_track_id'))
    assert driver.find_element(By.ID, 'supplied_track_id').get_attribute('value') == public_id
    assert driver.find_element(By.ID, 'station_text').get_attribute('value') == 'Test Station'
    for key, value in dict(copyrighted_work='My recording', material_location='On air today',
                           claimant_name='Copyright owner', claimant_email='owner@example.test', signature='Copyright owner').items():
        driver.find_element(By.ID, key).send_keys(value)
    for key in ('good_faith', 'authorized'):
        driver.find_element(By.NAME, key).click()
    driver.find_element(By.CSS_SELECTOR, 'form.form-card button[type=submit]').click()
    wait_text(driver, '#main', 'Your report has been received')
    with app.app_context():
        assert DMCACase.query.one().snapshot['freo_track_id'] == public_id
        assert Track.query.first().enabled
    driver.get(base + f'/admin/stations/test-station/media/{uuid}')
    field = WebDriverWait(driver, 8).until(lambda d:d.find_element(By.CSS_SELECTOR, '#song-details [name=isrc]'))
    field.send_keys('us-ab1-23-45678')
    driver.find_element(By.CSS_SELECTOR, '#song-details button[type=submit]').click()
    wait_text(driver, '#editor-status', 'Saved')
    assert field.get_attribute('value') == 'USAB12345678'
    with app.app_context():
        assert Track.query.first().isrc == 'USAB12345678'
        assert Track.query.first().freo_track_id == public_id


def test_report_link_without_metadata_and_station_admin_navigation(booth):
    from datetime import timedelta
    app, driver, base, tmp = booth
    with app.app_context():
        snapshot = LiveQueueSnapshot.query.first()
        snapshot.observed_at = datetime.now(timezone.utc) - timedelta(minutes=2)
        # The shared browser fixture refreshes timestamps on admin polling.
        snapshot.error_code = 'observation_unavailable'
        db.session.commit()
    driver.get(base + '/player/test-station')
    WebDriverWait(driver, 8).until(lambda d:d.find_element(By.ID, 'playing-label').get_attribute('textContent') == 'WAITING FOR LIVE METADATA')
    for width in (390, 1440):
        driver.set_window_size(width, 1000)
        assert driver.find_element(By.ID, 'copyright-report').is_displayed()
        assert not driver.find_element(By.ID, 'copyright-identification').is_displayed()
    driver.find_element(By.ID, 'copyright-report').click()
    WebDriverWait(driver, 8).until(lambda d:d.find_elements(By.ID, 'station_text'))
    assert driver.find_element(By.ID, 'station_text').get_attribute('value') == 'Test Station'
    assert driver.find_element(By.ID, 'supplied_track_id').get_attribute('value') == ''
    for path in ('/admin/stations/test-station', '/admin/stations/test-station/settings'):
        driver.get(base + path)
        link = driver.find_element(By.CSS_SELECTOR, '.admin-nav a[href="/admin/dmca"]')
        assert link.text == 'DMCA reports'
        assert driver.find_elements(By.CSS_SELECTOR, '.admin-content a[href="/admin/dmca"]')
    driver.find_element(By.CSS_SELECTOR, '.admin-nav a[href="/admin/dmca"]').click()
    wait_text(driver, '.admin-content h1', 'Copyright reports')
