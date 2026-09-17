"""Appearance persists independently of navigation, edits and audio playback."""
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from tests.test_live_browser import booth
from tests.test_web import app as app_fixture


def choose(driver, theme):
    driver.find_element(By.CSS_SELECTOR, f'[data-appearance="{theme}"]').click()
    assert driver.execute_script('return document.documentElement.dataset.theme') == theme


def test_appearance_persistence_navigation_and_audio(booth):
    app, driver, base, tmp_path = booth
    choose(driver, 'day')
    driver.find_element(By.CSS_SELECTOR, '.master-monitor button').click()
    WebDriverWait(driver, 10).until(lambda d: d.execute_script('return !FreoMonitor.audio.paused'))
    driver.execute_script('window.originalMonitor = FreoMonitor.audio')
    choose(driver, 'night')
    assert driver.execute_script('return originalMonitor === FreoMonitor.audio && !FreoMonitor.audio.paused')
    driver.find_element(By.CSS_SELECTOR, '.admin-nav a[href$="/categories"]').click()
    WebDriverWait(driver, 10).until(lambda d: '/categories' in d.current_url and d.find_elements(By.CSS_SELECTOR, '.list-card'))
    assert driver.find_element(By.CSS_SELECTOR, '[data-appearance=night]').get_attribute('aria-pressed') == 'true'
    assert driver.execute_script('return originalMonitor === FreoMonitor.audio && !FreoMonitor.audio.paused')
    driver.refresh()
    assert driver.execute_script('return document.documentElement.dataset.theme') == 'night'
    for path in ('/player/test-station', '/admin/stations/test-station/playlists', '/admin/stations/test-station/calendar', '/admin/stations/test-station/live', '/admin/stations/test-station/media'):
        driver.get(base + path)
        for theme in ('day', 'night'):
            choose(driver, theme)
            assert driver.execute_script('return getComputedStyle(document.body).backgroundColor') in ('rgb(247, 248, 244)', 'rgb(255, 255, 255)', 'rgb(16, 31, 41)', 'rgb(23, 45, 54)')
            driver.save_screenshot(str(tmp_path / (path.replace('/', '_') + theme + '.png')))
        driver.set_window_size(430, 1000)
        assert driver.execute_script('return document.documentElement.scrollWidth <= innerWidth')
        assert driver.find_element(By.CSS_SELECTOR, '[data-appearance]').is_displayed()
        driver.save_screenshot(str(tmp_path / (path.replace('/', '_') + '-mobile.png')))
        driver.set_window_size(1600, 1200)


def test_legacy_preference_storage_and_unsaved_input(booth):
    app, driver, base, tmp_path = booth
    driver.execute_script("localStorage.setItem('freo.appearance','system')")
    driver.execute_cdp_cmd('Emulation.setEmulatedMedia', {'features': [{'name': 'prefers-color-scheme', 'value': 'dark'}]})
    driver.refresh()
    assert driver.execute_script('return document.documentElement.dataset.theme') == 'day'
    assert not driver.find_elements(By.CSS_SELECTOR, '[data-appearance=system]')
    choose(driver, 'night')
    driver.execute_cdp_cmd('Emulation.setEmulatedMedia', {'features': [{'name': 'prefers-color-scheme', 'value': 'light'}]})
    assert driver.execute_script('return document.documentElement.dataset.theme') == 'night'
    driver.find_element(By.CSS_SELECTOR, '.booth-search input').send_keys('Still here')
    choose(driver, 'day')
    assert driver.find_element(By.CSS_SELECTOR, '.booth-search input').get_attribute('value') == 'Still here'
    driver.execute_script("localStorage.setItem('freo.appearance','night');window.dispatchEvent(new StorageEvent('storage',{key:'freo.appearance'}))")
    assert driver.execute_script('return document.documentElement.dataset.theme') == 'night'
    driver.execute_script("localStorage.setItem('freo.appearance','invalid')")
    driver.refresh()
    assert driver.find_element(By.CSS_SELECTOR, '[data-appearance=day]').get_attribute('aria-pressed') == 'true'


def test_unavailable_storage_and_dynamic_dialog(booth):
    app, driver, base, tmp_path = booth
    driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {'source': "Object.defineProperty(window,'localStorage',{get(){throw new DOMException('Blocked','SecurityError')}})"})
    driver.refresh()
    choose(driver, 'day')
    driver.execute_script("FreoDialog.notify({title:'Appearance check',message:'This dialog follows your appearance.'})")
    dialog = driver.find_element(By.CSS_SELECTOR, 'dialog[open]')
    assert driver.execute_script('return getComputedStyle(arguments[0]).backgroundColor', dialog) == 'rgb(255, 255, 255)'
    driver.find_element(By.CSS_SELECTOR, 'dialog[open] button.admin-primary').click()
    choose(driver, 'night')
    driver.execute_script("FreoDialog.notify({title:'Appearance check',message:'This dialog follows your appearance.'})")
    dialog = driver.find_element(By.CSS_SELECTOR, 'dialog[open]')
    assert driver.execute_script('return getComputedStyle(arguments[0]).backgroundColor', dialog) == 'rgb(23, 45, 54)'
