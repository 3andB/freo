"""Confirm the exact edited location without disrupting the single-save form."""
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from app.extensions import db
from app.models import Station
from tests.test_live_browser import booth, app_fixture, wait_text


def test_location_confirmation_drafts_rounding_and_normal_save(booth):
    app, driver, base, _ = booth
    driver.get(base + '/admin/stations/test-station/settings')

    def field(name, value):
        element = driver.find_element(By.NAME, name)
        element.clear()
        element.send_keys(value)

    def click(element):
        driver.execute_script('arguments[0].scrollIntoView({block:"center"})', element)
        element.click()

    def save():
        click(driver.find_element(By.CSS_SELECTOR, '.settings-save-bar button'))

    def confirm():
        click(driver.find_element(By.NAME, 'location_confirmation'))

    for name, value in [('city', 'New York'), ('region', 'NY'), ('country', 'US'),
                        ('latitude', '40.7128'), ('longitude', '-74.006')]:
        field(name, value)
    save()
    wait_text(driver, '#station-save-status', 'Confirm that these coordinates')
    with app.app_context():
        assert db.session.get(Station, 1).latitude is None
    confirm()
    save()
    wait_text(driver, '#station-save-status', 'All changes saved')
    assert driver.find_element(By.NAME, 'latitude').get_attribute('value') == '40.71'
    assert driver.find_element(By.NAME, 'longitude').get_attribute('value') == '-74.01'
    assert not driver.find_element(By.NAME, 'location_confirmation').is_selected()
    field('name', 'New station name')
    save()
    wait_text(driver, '#station-save-status', 'All changes saved')
    field('city', 'Albany')
    confirm()
    field('latitude', '42.65')
    assert not driver.find_element(By.NAME, 'location_confirmation').is_selected()
    field('longitude', '-73.75')
    confirm()
    # A server-side validation error leaves both stored location and UI draft intact.
    field('public_slug', 'second-station')
    save()
    WebDriverWait(driver, 10).until(lambda d: not d.find_element(By.ID, 'station-settings-form').get_property('inert'))
    assert 'All changes saved' not in driver.find_element(By.ID, 'station-save-status').text
    with app.app_context():
        station = db.session.get(Station, 1)
        assert station.city == 'New York' and station.latitude == 40.71
    field('region', 'New York')
    assert not driver.find_element(By.NAME, 'location_confirmation').is_selected()
    field('public_slug', 'test-station')
    save()
    wait_text(driver, '#station-save-status', 'Confirm that these coordinates')
    confirm()
    save()
    wait_text(driver, '#station-save-status', 'All changes saved')
    driver.refresh()
    assert driver.find_element(By.NAME, 'city').get_attribute('value') == 'Albany'
    assert driver.find_element(By.NAME, 'latitude').get_attribute('value') == '42.65'
    for width in (390, 820, 1440):
        driver.set_window_size(width, 1000)
        assert driver.execute_script('return document.documentElement.scrollWidth <= innerWidth + 1')
