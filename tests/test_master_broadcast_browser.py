"""Station master UI, multi-station monitors and responsive status displays."""
from datetime import datetime, timezone
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from app.extensions import db
from app.models import Station, LiveQueueSnapshot
from tests.test_live_browser import booth, wait_text
from tests.test_web import app as app_fixture


def test_master_switch_and_two_station_banner(booth):
    app, driver, base, tmp_path = booth
    with app.app_context():
        snapshot = LiveQueueSnapshot.query.first()
        snapshot.broadcast_observed_at = datetime.now(timezone.utc)
        snapshot.broadcast_online = True
        snapshot.mixer = dict(snapshot.mixer, tone=True)
        db.session.commit()
    driver.get(base + '/admin/stations/test-station/schedule-studio/control')
    wait_text(driver, '[data-live-label]', 'STATION LIVE')
    wait_text(driver, '#broadcast-message', 'Broadcasting tone')
    assert len(driver.find_elements(By.CSS_SELECTOR, '[data-station-monitor-toggle]')) == 2
    driver.find_element(By.ID, 'master-broadcast-toggle').click()
    wait_text(driver, '#broadcast-message', 'Stopping broadcast')
    assert driver.find_element(By.ID, 'master-broadcast-toggle').get_attribute('aria-checked') == 'false'
    with app.app_context():
        station = Station.query.filter_by(slug='test-station').one()
        assert station.desired_state == 'stopped'
        assert Station.query.filter_by(slug='second-station').one().desired_state == 'stopped'
        station.broadcast_status = 'ready'
        snapshot = LiveQueueSnapshot.query.first()
        snapshot.broadcast_observed_at = datetime.now(timezone.utc)
        snapshot.broadcast_online = False
        db.session.commit()
    wait_text(driver, '[data-live-label]', 'NOT LIVE')
    wait_text(driver, '#broadcast-message', 'Broadcast is OFF')
    for width in (390, 820, 1440):
        driver.set_window_size(width, 1000)
        assert driver.execute_script('return document.documentElement.scrollWidth <= innerWidth')
        assert all(button.is_displayed() for button in driver.find_elements(By.CSS_SELECTOR, '[data-station-monitor-toggle]'))
    driver.save_screenshot('/tmp/freo-master-broadcast.png')
    driver.find_element(By.ID, 'master-broadcast-toggle').click()
    wait_text(driver, '#broadcast-message', 'Starting broadcast')


def test_monitor_stays_on_chosen_station_when_workspace_changes(booth):
    app, driver, base, tmp_path = booth
    driver.find_element(By.CSS_SELECTOR, '[data-monitor-station="test-station"] button').click()
    WebDriverWait(driver, 10).until(lambda d: d.execute_script('return !FreoMonitor.audio.paused'))
    driver.execute_script('window.originalMonitor = FreoMonitor.audio')
    driver.execute_script("FreoWorkspace.navigate('/admin/stations/second-station/schedule-studio/control')")
    wait_text(driver, '#station-control .eyebrow', 'SECOND STATION')
    assert driver.execute_script("return originalMonitor === FreoMonitor.audio && !FreoMonitor.audio.paused && FreoMonitor.audio.src.endsWith('/stream/test-station')")
    assert driver.find_element(By.CSS_SELECTOR, '[data-monitor-station="test-station"] button').get_attribute('aria-pressed') == 'true'
    assert driver.find_element(By.CSS_SELECTOR, '[data-monitor-station="second-station"] button').get_attribute('aria-pressed') == 'false'
