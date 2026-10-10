from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait

from app.extensions import db
from app.models import AuditEvent
from tests.test_live_browser import booth, app_fixture


def test_first_use_failure_retry_reopen_and_mobile(booth):
    app, driver, base, _ = booth
    with app.app_context():
        AuditEvent.query.filter_by(action='license.accept').delete()
        db.session.commit()
    driver.get(base + '/admin/stations/test-station/schedule-studio/control')
    wait = WebDriverWait(driver, 10)
    dialog = driver.find_element(By.ID, 'license-agreement')
    wait.until(lambda _: dialog.is_displayed())
    driver.find_element(By.ID, 'license-agreement-title').send_keys(Keys.ESCAPE)
    assert dialog.is_displayed()
    driver.find_element(By.CSS_SELECTOR, '#license-accept-form button').click()
    assert dialog.is_displayed()
    driver.find_element(By.CSS_SELECTOR, '#license-accept-form input[name=agree]').click()
    driver.execute_script('''
      window.realFetch = window.fetch;
      window.fetch = (url, options) => String(url).endsWith('/license-agreement/accept')
        ? Promise.reject(new Error('offline')) : window.realFetch(url, options);
    ''')
    driver.find_element(By.CSS_SELECTOR, '#license-accept-form button').click()
    wait.until(lambda d: d.find_element(By.CSS_SELECTOR, '[data-license-error]').is_displayed())
    assert dialog.is_displayed()
    driver.execute_script('window.fetch = window.realFetch')
    driver.find_element(By.CSS_SELECTOR, '#license-accept-form button').click()
    wait.until(lambda _: not dialog.is_displayed())
    driver.refresh()
    wait.until(lambda d: d.find_elements(By.CSS_SELECTOR, '[data-license-open]'))
    assert not driver.find_element(By.ID, 'license-agreement').is_displayed()
    driver.find_element(By.CSS_SELECTOR, '[data-license-open]').click()
    wait.until(lambda d: d.find_element(By.ID, 'license-agreement').is_displayed())
    assert not driver.find_element(By.ID, 'license-accept-form').is_displayed()
    assert int(driver.find_element(By.CSS_SELECTOR, '.license-copyright strong').value_of_css_property('font-weight')) >= 700
    driver.set_window_size(390, 844)
    assert driver.execute_script('const r=document.getElementById("license-agreement").getBoundingClientRect(); return r.left >= 0 && r.right <= innerWidth && r.height <= innerHeight;')
    driver.find_element(By.CSS_SELECTOR, '[data-license-close]').click()
    assert not driver.find_element(By.ID, 'license-agreement').is_displayed()
    driver.find_element(By.CSS_SELECTOR, '.admin-nav a[href="/admin"]').click()
    wait.until(lambda d: d.current_url == base + '/admin')
    wait.until(lambda d: d.execute_script('return !document.documentElement.classList.contains("is-navigating")'))
    driver.back()
    wait.until(lambda d: d.find_elements(By.CSS_SELECTOR, '[data-license-open]'))
    wait.until(lambda d: d.execute_script('return !document.documentElement.classList.contains("is-navigating")'))
    driver.find_element(By.CSS_SELECTOR, '[data-license-open]').click()
    wait.until(lambda d: d.find_element(By.ID, 'license-agreement').is_displayed())


def test_decline_signs_out_without_acceptance(booth):
    app, driver, base, _ = booth
    with app.app_context():
        AuditEvent.query.filter_by(action='license.accept').delete()
        db.session.commit()
    driver.get(base + '/admin')
    driver.find_element(By.CSS_SELECTOR, '[data-license-decline] button').click()
    WebDriverWait(driver, 10).until(lambda d: d.current_url == base + '/')
    with app.app_context():
        assert AuditEvent.query.filter_by(action='license.accept').count() == 0
