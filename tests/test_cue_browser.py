from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import StaleElementReferenceException

from app.extensions import db
from app.models import BoothCue, SavedBoothCue, LiveControlCommand
from tests.test_live_browser import booth, app_fixture, wait_text, apply_browser_command


def test_cue_add_reorder_save_load_new_and_deck_binding(booth):
    app, driver, base, tmp_path = booth
    wait = WebDriverWait(driver, 10, ignored_exceptions=(StaleElementReferenceException,))
    def rows(): return driver.find_elements(By.CSS_SELECTOR, '#booth-cue-list [data-cue-entry]')
    for count in range(1, 4):
        wait.until(lambda d: d.find_elements(By.CSS_SELECTOR, '[data-add-cue]'))
        driver.find_element(By.CSS_SELECTOR, '[data-add-cue]').click()
        wait.until(lambda d: len(rows()) == count)
        wait_text(driver, '#cue-save-state', 'Saved')
    original = [row.get_attribute('data-cue-entry') for row in rows()]
    # Exercise the same pointer drag used by mouse/touch operators.
    handle = rows()[2].find_element(By.CSS_SELECTOR, '.cue-handle')
    ActionChains(driver).move_to_element(handle).click_and_hold().move_to_element_with_offset(rows()[0], 0, -20).pause(.15).release().perform()
    wait.until(lambda d: rows()[0].get_attribute('data-cue-entry') == original[2])
    driver.find_element(By.CSS_SELECTOR, '[data-cue-action="save"]').click()
    driver.find_element(By.CSS_SELECTOR, '#cue-dialog input').send_keys('Friday night')
    driver.find_element(By.CSS_SELECTOR, '#cue-dialog button[type="submit"]').click()
    wait_text(driver, '#cue-name', 'Friday night')
    driver.refresh()
    wait_text(driver, '#cue-name', 'Friday night')
    assert len(rows()) == 3
    entry = rows()[0].get_attribute('data-cue-entry')
    rows()[0].find_element(By.CSS_SELECTOR, '[data-load-deck="B"]').click()
    wait_text(driver, '#booth-notice', 'Deck command requested')
    with app.app_context():
        from app.models import CuePlayback
        command = LiveControlCommand.query.filter_by(status='pending').one()
        assert db.session.get(CuePlayback, command.target_decision_id).entry_id == entry
    apply_browser_command(app, 'LOAD', 'B')
    wait_text(driver, '#cue-title', 'Verified Test Track')
    driver.find_element(By.CSS_SELECTOR, '[data-cue-action="new"]').click()
    wait.until(lambda d: len(rows()) == 0)
    driver.find_element(By.CSS_SELECTOR, '[data-cue-action="load"]').click()
    wait.until(lambda d: d.find_elements(By.CSS_SELECTOR, '.cue-saved-sets button'))
    driver.find_element(By.CSS_SELECTOR, '.cue-saved-sets button').click()
    wait.until(lambda d: len(rows()) == 3)
    with app.app_context():
        assert len(BoothCue.query.one().entries) == 3
        assert SavedBoothCue.query.one().name == 'Friday night'
    driver.set_window_size(1440, 900)
    assert driver.execute_script('return document.documentElement.scrollWidth<=innerWidth')
    driver.save_screenshot('/tmp/freo-cue-desktop.png')
    driver.set_window_size(390, 844)
    assert driver.execute_script('return document.documentElement.scrollWidth<=innerWidth')
    driver.find_element(By.ID, 'cue-heading').location_once_scrolled_into_view
    driver.save_screenshot('/tmp/freo-cue-mobile.png')


def test_cue_auto_toggle_search_and_keyboard_reorder(booth):
    from selenium.webdriver.common.keys import Keys
    app, driver, base, tmp_path = booth
    wait = WebDriverWait(driver, 10, ignored_exceptions=(StaleElementReferenceException,))
    def rows(): return driver.find_elements(By.CSS_SELECTOR, '#booth-cue-list [data-cue-entry]')
    for count in (1, 2):
        wait.until(lambda d: d.find_elements(By.CSS_SELECTOR, '[data-add-cue]'))
        driver.find_element(By.CSS_SELECTOR, '[data-add-cue]').click()
        wait.until(lambda d: len(rows()) == count)
        wait_text(driver, '#cue-save-state', 'Saved')
    old_first = rows()[0].get_attribute('data-cue-entry')
    rows()[1].find_element(By.CSS_SELECTOR, '.cue-handle').send_keys(Keys.ALT, Keys.ARROW_UP, Keys.NULL)
    wait.until(lambda d: rows()[0].get_attribute('data-cue-entry') != old_first)
    driver.find_element(By.ID, 'cue-auto').click()
    wait.until(lambda d: d.find_element(By.ID, 'cue-auto').get_attribute('aria-pressed') == 'true')
    driver.refresh()
    wait.until(lambda d: d.find_element(By.ID, 'cue-auto').get_attribute('aria-pressed') == 'true')
    search = driver.find_element(By.CSS_SELECTOR, '.booth-search input')
    search.send_keys('no matches for this search')
    wait_text(driver, '.song-shelf', 'No enabled songs match')
    assert len(rows()) == 2
    driver.find_element(By.ID, 'cue-auto').click()
    wait.until(lambda d: d.find_element(By.ID, 'cue-auto').get_attribute('aria-pressed') == 'false')
    driver.find_element(By.CSS_SELECTOR, '[data-cue-action="new"]').click()
    wait_text(driver, '#cue-dialog', 'Keep your current set?')
    buttons = driver.find_elements(By.CSS_SELECTOR, '.cue-dialog-actions button')
    buttons[2].click()
    assert len(rows()) == 2


def test_cue_light_follows_playback_and_connection(booth):
    app, driver, base, tmp_path = booth
    wait = WebDriverWait(driver, 12, ignored_exceptions=(StaleElementReferenceException,))
    panel = driver.find_element(By.CSS_SELECTOR, '.cue-panel')
    def activity(value):
        wait.until(lambda d: panel.get_attribute('data-cue-activity') == value)
    def glow_style(property):
        return driver.execute_script('return getComputedStyle(arguments[0], "::before").getPropertyValue(arguments[1])', panel, property)
    activity('idle')
    driver.find_element(By.CSS_SELECTOR, '[data-add-cue]').click()
    wait.until(lambda d: d.find_elements(By.CSS_SELECTOR, '#booth-cue-list [data-cue-entry]'))
    wait_text(driver, '#cue-save-state', 'Saved')
    driver.find_element(By.CSS_SELECTOR, '#booth-cue-list [data-load-deck="B"]').click()
    apply_browser_command(app, 'LOAD', 'B')
    wait_text(driver, '#cue-title', 'Verified Test Track')
    activity('idle')  # Preparing a deck is not playback.
    driver.find_element(By.CSS_SELECTOR, '[data-deck="B"][data-operation="PLAY"]').click()
    apply_browser_command(app, 'PLAY', 'B')
    activity('playing')
    wait.until(lambda d: float(glow_style('opacity')) > .95)
    assert glow_style('animation-name') == 'cue-warm-light'
    assert glow_style('animation-duration') == '9s'
    assert glow_style('pointer-events') == 'none'
    driver.set_window_size(1440, 1000)
    for theme in ('day', 'night'):
        driver.execute_script('document.documentElement.dataset.theme=arguments[0]', theme)
        assert driver.execute_script('return document.documentElement.scrollWidth <= innerWidth')
        driver.save_screenshot('/tmp/freo-cue-glow-' + theme + '.png')
    driver.set_window_size(390, 844)
    panel.location_once_scrolled_into_view
    assert driver.execute_script('return document.documentElement.scrollWidth <= innerWidth')
    driver.save_screenshot('/tmp/freo-cue-glow-mobile.png')
    driver.execute_cdp_cmd('Emulation.setEmulatedMedia', {'features': [{'name': 'prefers-reduced-motion', 'value': 'reduce'}]})
    assert glow_style('animation-name') == 'none'
    assert float(glow_style('opacity')) == 1
    driver.execute_cdp_cmd('Emulation.setEmulatedMedia', {'features': []})
    driver.set_window_size(1440, 1000)
    # Reset the mobile scroll before clicking beneath the fixed desktop header.
    driver.execute_script('window.scrollTo(0, 0)')
    driver.find_element(By.CSS_SELECTOR, '[data-deck="B"][data-operation="PAUSE"]').click()
    apply_browser_command(app, 'PAUSE', 'B')
    activity('idle')
    driver.find_element(By.ID, 'cue-auto').click()
    activity('armed')
    wait.until(lambda d: abs(float(glow_style('opacity')) - .4) < .01)
    # A failed request must extinguish the glow and recover automatically.
    driver.execute_cdp_cmd('Network.enable', {})
    driver.execute_cdp_cmd('Network.emulateNetworkConditions', {'offline': True, 'latency': 0, 'downloadThroughput': -1, 'uploadThroughput': -1})
    activity('idle')
    driver.execute_cdp_cmd('Network.emulateNetworkConditions', {'offline': False, 'latency': 0, 'downloadThroughput': -1, 'uploadThroughput': -1})
    activity('armed')
    # A request that never settles must also lose its active indication.
    driver.execute_script('''
      window.cueOriginalFetch = window.fetch; window.cuePendingFetches = [];
      window.fetch = (...args) => String(args[0]).includes('/live-status')
        ? new Promise(resolve => window.cuePendingFetches.push(() => resolve(window.cueOriginalFetch(...args))))
        : window.cueOriginalFetch(...args);
    ''')
    activity('idle')
    driver.execute_script('window.fetch=window.cueOriginalFetch; window.cuePendingFetches.forEach(resume => resume());')
    activity('armed')
    driver.find_element(By.ID, 'cue-auto').click()
    activity('idle')
    wait.until(lambda d: float(glow_style('opacity')) < .01)
