"""Domain settings controls in the existing browser fixture."""
from types import SimpleNamespace
from selenium.common.exceptions import StaleElementReferenceException
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from app.extensions import db
from app.models import StationDomain
from app.services import station_domains as domains
from tests.test_live_browser import booth, app_fixture


def test_domain_settings_add_verify_primary_remove(booth, monkeypatch):
    app, driver, base, _ = booth
    wait = WebDriverWait(driver, 8, ignored_exceptions=(StaleElementReferenceException,))
    app.config.update(FREO_DOMAIN_TARGET_HOST='', FREO_DOMAIN_TARGET_IPS='192.0.2.1')
    driver.get(base + '/admin/stations/test-station/settings')
    driver.find_element(By.NAME, 'hostname').send_keys('ROCK.example.test')
    driver.find_element(By.CSS_SELECTOR, '#domains form button').click()
    wait.until(lambda d: 'Pending verification' in d.find_element(By.ID, 'domains').text)
    driver.set_window_size(390, 844)
    assert driver.execute_script('return document.documentElement.scrollWidth <= innerWidth')
    driver.set_window_size(1600, 1200)
    with app.app_context():
        row = StationDomain.query.one()
        assert row.hostname == 'rock.example.test' and not row.enabled
        token = row.verification_token
    def records(host, kind):
        if kind == 'TXT':
            return [SimpleNamespace(strings=[('freo-verification=' + token).encode()])]
        return [SimpleNamespace(address='192.0.2.1')] if kind == 'A' else []
    monkeypatch.setattr(domains, 'dns_records', records)
    driver.find_element(By.CSS_SELECTOR, '#domains article button').click()
    wait.until(lambda d: 'Verified · Enabled' in d.find_element(By.ID, 'domains').text)
    driver.find_element(By.CSS_SELECTOR, '#domains button[formaction$="/primary"]').click()
    wait.until(lambda d: d.find_element(By.ID, 'station-public-url').get_attribute('value') == 'https://rock.example.test/')
    driver.find_element(By.CSS_SELECTOR, '#domains button[formaction$="/remove"]').click()
    wait.until(lambda d: 'No custom domains added.' in d.find_element(By.ID, 'domains').text)
    with app.app_context():
        assert StationDomain.query.count() == 0
