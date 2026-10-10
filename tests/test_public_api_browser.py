"""One-time browser token creation and revocation, including mobile layout."""
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from tests.test_live_browser import booth, app_fixture, wait_text


def test_create_copy_leave_and_revoke(booth):
    app, driver, base, folder = booth
    driver.get(base + '/admin/api-credentials')
    driver.find_element(By.ID, 'credential-name').send_keys('Browser integration')
    driver.find_element(By.CSS_SELECTOR, 'input[name=stations]').click()
    driver.find_element(By.CSS_SELECTOR, 'form[action="/admin/api-credentials"] button').click()
    WebDriverWait(driver, 10).until(lambda d: d.find_elements(By.ID, 'created-token'))
    token = driver.find_element(By.ID, 'created-token').get_attribute('value')
    assert token.startswith('freo_v1_')
    client = app.test_client()
    auth = {'Authorization': 'Bearer ' + token}
    assert client.get('/api/v1/stations', headers=auth).status_code == 200
    driver.set_window_size(390, 844)
    assert driver.execute_script('return document.documentElement.scrollWidth <= innerWidth')
    # Do not put the one-time secret in a screenshot artifact.
    driver.get(base + '/admin/api-credentials')
    assert token not in driver.page_source
    driver.save_screenshot(str(folder / 'api-credentials-mobile.png'))
    driver.find_element(By.CSS_SELECTOR, 'form[action$="/revoke"] button').click()
    wait_text(driver, 'article', 'Revoked')
    assert client.get('/api/v1/stations', headers=auth).status_code == 401
