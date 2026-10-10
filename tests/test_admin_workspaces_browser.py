"""Layout and interaction checks for the new station administration surfaces."""
from cryptography.fernet import Fernet
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select, WebDriverWait
from app.extensions import db
from app.models import AdminUser, DJStationAssignment, Station
from tests.test_live_browser import booth, app_fixture, wait_text


def test_forms_layout_and_bulletin_recurrence(booth):
    app, driver, base, folder = booth
    with app.app_context():
        AdminUser.query.one().installation_admin = True
        dj = AdminUser(email='evening@example.test', username='Evening presenter with a longer display name', role='DJ', password_hash='unused-test-hash')
        db.session.add(dj)
        db.session.flush()
        db.session.add(DJStationAssignment(admin_user_id=dj.id, station_id=Station.query.filter_by(slug='test-station').one().id))
        db.session.commit()
    pages = ['/admin/providers', '/admin/djs', '/admin/stations/test-station/broadcast-reports',
             '/admin/stations/test-station/external-bulletins', '/admin/stations/test-station/requests']
    for width in (1440, 390):
        driver.set_window_size(width, 1000)
        for theme in ('day', 'night'):
            for path in pages:
                driver.get(base + path)
                driver.execute_script('document.documentElement.dataset.theme=arguments[0]', theme)
                heading = driver.find_element(By.CSS_SELECTOR, '.ops-page-heading h1')
                assert heading.is_displayed()
                driver.execute_script("arguments[0].scrollIntoView({block:'start',behavior:'instant'})", heading)
                assert driver.execute_script('return document.documentElement.scrollWidth <= innerWidth'), (path, width, theme)
                if path.endswith('broadcast-reports'):
                    assert driver.find_element(By.NAME, 'start').rect['width'] >= 160
                    assert driver.find_element(By.CSS_SELECTOR, '.ops-metrics .sr-only').rect['width'] == 1
                driver.save_screenshot(str(folder / (path.rsplit('/', 1)[1]+f'-{width}-{theme}.png')))
    driver.get(base + '/admin/stations/test-station/external-bulletins')
    recurrence = Select(driver.find_element(By.NAME, 'recurrence_type'))
    assert not driver.find_element(By.NAME, 'local_date').is_displayed()
    recurrence.select_by_value('ONE_TIME')
    assert driver.find_element(By.NAME, 'local_date').is_displayed()
    assert driver.find_element(By.NAME, 'local_date').get_attribute('required')
    recurrence.select_by_value('WEEKLY')
    assert driver.find_element(By.NAME, 'weekday').is_displayed()
    assert not driver.find_element(By.NAME, 'local_date').is_enabled()


def test_provider_save_feedback_and_revisions(booth, monkeypatch):
    app, driver, base, folder = booth
    monkeypatch.setitem(app.config, 'FREO_PROVIDER_ENCRYPTION_KEY', Fernet.generate_key().decode())
    with app.app_context():
        AdminUser.query.one().installation_admin = True
        db.session.commit()
    driver.get(base + '/admin/providers')
    form = driver.find_element(By.CSS_SELECTOR, '.provider-form')
    form.find_element(By.NAME, 'key').send_keys('test-provider-key')
    form.find_element(By.CSS_SELECTOR, '[value=save]').click()
    wait_text(driver, '.provider-form [data-provider-message]', 'Provider configuration saved')
    assert form.find_element(By.NAME, 'key').get_attribute('value') == ''
    assert form.find_element(By.NAME, 'revision').get_attribute('value') == '1'
    form.find_element(By.CSS_SELECTOR, '[value=remove]').click()
    WebDriverWait(driver, 8).until(lambda d: form.find_element(By.NAME, 'revision').get_attribute('value') == '2')
    assert 'Not configured' in driver.find_element(By.CSS_SELECTOR, '.ops-provider .ops-badge').text


def test_show_elapsed_timeline_has_room_at_each_duration(booth):
    app, driver, base, folder = booth
    driver.get(base + '/admin/stations/test-station/schedule-studio/shows')
    wait_text(driver, '#workspace-title', 'Shows')
    duration = Select(driver.find_element(By.ID, 'show-duration'))
    for seconds, height in [('900', 480), ('3600', 480), ('86400', 5760)]:
        duration.select_by_value(seconds)
        actual = driver.execute_script("return document.querySelector('.time-column').getBoundingClientRect().height")
        assert abs(actual-height) <= 1
        viewport = driver.find_element(By.ID, 'timeline').rect['height']
        assert viewport >= 480 and viewport <= 622
    driver.save_screenshot(str(folder/'show-elapsed.png'))
