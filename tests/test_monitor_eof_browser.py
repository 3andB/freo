"""A closed live stream must not leave the persistent monitor labelled active."""
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from tests.test_live_browser import booth, app_fixture

def test_monitor_stream_end_exposes_one_click_retry(booth):
    _, driver, _, _ = booth
    wait = WebDriverWait(driver, 20)
    button = driver.find_element(By.CSS_SELECTOR,'[data-monitor-station="test-station"] button')
    button.click()
    wait.until(lambda d:d.execute_script('return !FreoMonitor.audio.paused && FreoMonitor.audio.currentTime>.2'))
    # The fixture serves a finite WAV without byte ranges. Reach its real EOF
    # at accelerated playback rather than seeking on a nonseekable stream.
    driver.execute_script('FreoMonitor.audio.playbackRate=16')
    wait.until(lambda d:d.execute_script('return FreoMonitor.audio.ended && FreoMonitor.audio.paused'))
    wait.until(lambda d:d.find_element(By.CSS_SELECTOR,'.master-monitor > button').get_attribute('aria-pressed')=='false')
    assert 'retry' in driver.execute_script('return document.querySelector(".monitor-state").textContent').lower()
    driver.find_element(By.CSS_SELECTOR,'[data-monitor-station="test-station"] button').click()
    wait.until(lambda d:d.execute_script('return !FreoMonitor.audio.paused && !FreoMonitor.audio.ended && FreoMonitor.audio.currentTime>.2'))
    assert driver.find_element(By.CSS_SELECTOR,'.master-monitor > button').get_attribute('aria-pressed')=='true'
