"""Header discovery without reload, including pending and stopped stations."""
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from app.extensions import db
from app.models import Station
from app.services.stations import create_station
from tests.test_live_browser import booth, app_fixture


def test_header_discovers_station_and_readiness_without_reload(booth):
    app, driver, base, tmp_path = booth
    driver.get(base+'/admin')
    driver.execute_script('window.sameDocumentMarker=true')
    with app.app_context():
        create_station('New station <test>', 'new-station', pending=True)
        db.session.commit()
    wait = WebDriverWait(driver, 12)
    selector = '[data-monitor-station="new-station"]'
    wait.until(lambda d: d.find_elements(By.CSS_SELECTOR, selector))
    assert 'New station <test>' in driver.find_element(By.CSS_SELECTOR, selector).text
    assert not driver.find_element(By.CSS_SELECTOR, selector+' button').is_enabled()
    with app.app_context():
        Station.query.filter_by(slug='new-station').one().lifecycle_state = 'ready'
        db.session.commit()
    wait.until(lambda d: d.find_element(By.CSS_SELECTOR, selector+' button').is_enabled())
    assert driver.execute_script('return sameDocumentMarker')
    assert 'Stopped' in driver.find_element(By.CSS_SELECTOR, selector).text
    for width in (390, 820, 1440):
        driver.set_window_size(width, 1100)
        assert all(button.is_displayed() for button in driver.find_elements(By.CSS_SELECTOR, '[data-station-monitor-toggle]'))
        assert driver.execute_script('return document.documentElement.scrollWidth <= innerWidth+1')
        driver.save_screenshot(f'/tmp/freo-rc5-monitors-{width}.png')
