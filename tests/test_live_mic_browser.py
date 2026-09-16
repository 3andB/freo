from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from app.models import Station, LiveControlCommand
from tests.test_live_browser import booth, app_fixture


def test_live_mic_board_preserves_feed_and_shares_carts(booth):
    app, driver, base, tmp_path = booth
    driver.find_element(By.ID, 'mic-tab').click()
    WebDriverWait(driver, 5).until(lambda d: d.find_element(By.ID,'mic-heading').is_displayed())
    assert driver.find_element(By.CSS_SELECTOR,'.cart-console').is_displayed()
    assert driver.find_element(By.CSS_SELECTOR,'.station-id-console').is_displayed()
    assert not driver.find_element(By.CSS_SELECTOR,'.deck-workspace').is_displayed()
    assert not driver.find_element(By.ID,'mic-go').is_enabled()
    with app.app_context():
        assert Station.query.filter_by(slug='test-station').one().automation.operator_mode == 'DJ_BOOTH'
        assert LiveControlCommand.query.count() == 0
    # Polling the engine must not replace the selected board.
    driver.execute_script("document.getElementById('mic-gain').value=6; document.getElementById('mic-gain').dispatchEvent(new Event('input'))")
    assert driver.find_element(By.ID,'mic-gain-value').text == '+6 dB'
    driver.set_window_size(390,844)
    assert driver.execute_script('return document.documentElement.scrollWidth<=innerWidth')
    driver.save_screenshot('/tmp/freo-live-mic-mobile.png')
    driver.set_window_size(1600,1200)
    driver.save_screenshot('/tmp/freo-live-mic-desktop.png')
    driver.find_element(By.CSS_SELECTOR,'button[data-mode=DJ_BOOTH]').click()
    WebDriverWait(driver,5).until(lambda d:not d.find_element(By.ID,'mic-heading').is_displayed())


def test_denied_microphone_permission_never_enables_go_live(booth, monkeypatch):
    app, driver, base, tmp_path = booth
    monkeypatch.setattr('app.services.live_mic.enabled', lambda: True)
    monkeypatch.setattr('app.routes.live_mic.gateway', lambda *args, **kwargs: {'phase':'OFF AIR'})
    driver.refresh()
    driver.find_element(By.ID,'mic-tab').click()
    driver.execute_script("navigator.mediaDevices.getUserMedia=async()=>{throw new DOMException('Microphone permission denied','NotAllowedError');}")
    driver.find_element(By.ID,'mic-connect').click()
    WebDriverWait(driver,5).until(lambda d:'permission denied' in d.find_element(By.ID,'mic-message').text)
    assert not driver.find_element(By.ID,'mic-go').is_enabled()
    assert driver.find_element(By.ID,'mic-connect').is_enabled()
    with app.app_context():
        assert Station.query.filter_by(slug='test-station').one().automation.operator_mode == 'DJ_BOOTH'
        assert LiveControlCommand.query.count() == 0
