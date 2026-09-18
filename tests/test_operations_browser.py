"""Context switching and operation forms through persistent document navigation."""
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select, WebDriverWait
from tests.test_live_browser import booth, app_fixture, wait_text


def test_manual_connection_check_progress_and_version_result(booth, monkeypatch):
    from threading import Event, Thread
    from app.extensions import db
    from app.models import CentralConnectionCheck
    from app.services.central_api import Reporter
    from tests.test_central_api import FakeAPI
    app, driver, base, tmp_path = booth
    app.config['FREO_API_STATE_DIR'] = str(tmp_path / 'central-identity')
    monkeypatch.setattr('app.services.central_api.metrics.observation', lambda slug: (True, 4))
    api = FakeAPI()
    api.heartbeat_fields = {'latest_version': '0.2.0', 'update_available': True}
    entered, release = Event(), Event()
    errors = []
    def worker():
        try:
            with app.app_context():
                reporter = Reporter(api.factory)
                tick = reporter.tick
                def paused_tick(*args, **kwargs):
                    entered.set()
                    assert release.wait(15)
                    return tick(*args, **kwargs)
                reporter.tick = paused_tick
                with reporter.store.lock():
                    reporter.process_connection_check()
        except Exception as error:
            errors.append(error)
    driver.get(base + '/admin')
    driver.execute_script('window.connectionPageMarker = true')
    button = driver.find_element(By.CSS_SELECTOR, '#connection-check button')
    button.click()
    wait_text(driver, '#connection-check-status', 'Queued')
    assert not button.is_enabled()
    with app.app_context():
        check = db.session.get(CentralConnectionCheck, 1)
        assert check.status == 'queued'
        request_id = check.request_id
    thread = Thread(target=worker)
    thread.start()
    try:
        assert entered.wait(5)
        wait_text(driver, '#connection-check-status', 'Checking connection')
    finally:
        release.set()
        thread.join(timeout=20)
    assert not errors and not thread.is_alive()
    wait_text(driver, '#connection-check-status', 'Heartbeat accepted')
    wait_text(driver, '[data-connection="installed_version"]', '0.1.0')
    wait_text(driver, '[data-connection="latest_version"]', '0.2.0')
    wait_text(driver, '[data-connection="update_status"]', 'Update available')
    assert driver.execute_script('return window.connectionPageMarker === true')
    with app.app_context():
        assert db.session.get(CentralConnectionCheck, 1).request_id == request_id
    assert not button.is_enabled()  # Server cooldown remains visible after success.
    for width in (390, 820, 1440):
        driver.set_window_size(width, 1000)
        assert driver.execute_script('return document.documentElement.scrollWidth <= innerWidth + 1')


def test_manual_connection_check_without_javascript(booth):
    from app.extensions import db
    from app.models import CentralConnectionCheck
    app, driver, base, tmp_path = booth
    driver.execute_cdp_cmd('Emulation.setScriptExecutionDisabled', {'value': True})
    try:
        driver.get(base + '/admin')
        driver.find_element(By.CSS_SELECTOR, '#connection-check button').click()
        wait_text(driver, '#connection-check-status', 'Queued')
        assert driver.current_url == base + '/admin'
        with app.app_context():
            assert db.session.get(CentralConnectionCheck, 1).status == 'queued'
    finally:
        driver.execute_cdp_cmd('Emulation.setScriptExecutionDisabled', {'value': False})


def test_operations_station_switch_back_and_mobile(booth):
    app, driver, base, tmp_path = booth
    driver.find_element(By.CSS_SELECTOR, '.master-monitor button').click()
    WebDriverWait(driver, 10).until(lambda d: d.execute_script('return !FreoMonitor.audio.paused'))
    driver.execute_script('window.originalMonitor = FreoMonitor.audio')
    driver.find_element(By.CSS_SELECTOR, '.admin-nav a[href="/admin"]').click()
    wait_text(driver, 'h1', 'Operations overview')
    assert driver.execute_script('return originalMonitor === FreoMonitor.audio && !FreoMonitor.audio.paused')
    nav = driver.find_element(By.CSS_SELECTOR, '.admin-nav')
    assert nav.get_attribute('data-context') == 'operations'
    assert 'DJ Booth' not in nav.text and 'Operations Statistics' in nav.text
    driver.find_element(By.CSS_SELECTOR, '.master-monitor button').click()
    Select(driver.find_element(By.ID, 'station-select')).select_by_value('second-station')
    assert driver.current_url == base + '/admin'
    assert driver.find_element(By.CSS_SELECTOR, '.admin-nav').get_attribute('data-context') == 'operations'
    driver.find_element(By.CSS_SELECTOR, '.station-picker button').click()
    WebDriverWait(driver, 10).until(lambda d: '/stations/second-station/schedule-studio/control' in d.current_url)
    wait_text(driver, '.admin-toolbar', 'SECOND STATION')
    nav = driver.find_element(By.CSS_SELECTOR, '.admin-nav')
    assert nav.get_attribute('data-context') == 'station'
    assert 'DJ Booth' in nav.text and 'Operations Statistics' not in nav.text
    driver.back()
    wait_text(driver, 'h1', 'Operations overview')
    driver.forward()
    wait_text(driver, '.admin-toolbar', 'SECOND STATION')
    driver.find_element(By.CSS_SELECTOR, '.admin-nav a[href="/admin"]').click()
    wait_text(driver, 'h1', 'Operations overview')
    driver.save_screenshot('/tmp/freo-operations-desktop.png')
    for width in (390, 820, 1440):
        driver.set_window_size(width, 1000)
        assert driver.execute_script('return document.documentElement.scrollWidth <= innerWidth + 1')
        assert driver.find_element(By.CSS_SELECTOR, '.station-picker button').is_displayed()
    driver.set_window_size(390, 1000)
    driver.save_screenshot('/tmp/freo-operations-mobile.png')
    errors = [r for r in driver.get_log('browser') if r['level'] == 'SEVERE' and 'favicon.ico' not in r['message']]
    assert not errors, errors


def test_operations_directory_navigation_and_switch_without_javascript(booth):
    app, driver, base, tmp_path = booth
    driver.get(base + '/admin')
    driver.find_element(By.CSS_SELECTOR, '.admin-nav a[href="/admin/player-settings"]').click()
    wait_text(driver, 'h1', 'Player settings')
    driver.find_element(By.CSS_SELECTOR, '.ops-player-directory a[href$="/test-station/player-settings"]').click()
    wait_text(driver, '.admin-toolbar', 'TEST STATION')
    driver.find_element(By.CSS_SELECTOR, '.admin-content a[href="/admin/player-settings"]').click()
    wait_text(driver, 'h1', 'Player settings')
    driver.find_element(By.CSS_SELECTOR, '.admin-nav a[href="/admin/listener-feedback"]').click()
    wait_text(driver, 'h1', 'Listener feedback')
    Select(driver.find_element(By.CSS_SELECTOR, '.ops-feedback-filter [name="station"]')).select_by_value('second-station')
    driver.find_element(By.CSS_SELECTOR, '.ops-feedback-filter button').click()
    WebDriverWait(driver, 10).until(lambda d: 'station=second-station' in d.current_url)
    assert driver.find_element(By.CSS_SELECTOR, '.admin-nav').get_attribute('data-context') == 'operations'
    # Native form submission must work independently of the workspace router.
    driver.execute_cdp_cmd('Emulation.setScriptExecutionDisabled', {'value': True})
    try:
        driver.get(base + '/admin')
        Select(driver.find_element(By.ID, 'station-select')).select_by_value('test-station')
        driver.find_element(By.CSS_SELECTOR, '.station-picker button').click()
        WebDriverWait(driver, 10).until(lambda d: '/stations/test-station/schedule-studio/control' in d.current_url)
        assert driver.find_element(By.CSS_SELECTOR, '.admin-nav').get_attribute('data-context') == 'station'
    finally:
        driver.execute_cdp_cmd('Emulation.setScriptExecutionDisabled', {'value': False})
