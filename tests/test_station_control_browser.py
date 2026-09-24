"""Station Control recovers from a request that stalls without disconnecting."""
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from tests.test_live_browser import booth, app_fixture
from app.models import Station


def test_stalled_station_status_times_out_and_recovers(booth):
    app, driver, base, tmp_path = booth
    driver.get(base + '/admin/stations/test-station/schedule-studio/control')
    # The rendered hint confirms the page script attached its control handlers.
    WebDriverWait(driver, 12).until(lambda d: d.find_element(By.ID, 'broadcast-hint').text)
    driver.execute_script('''
        window.originalStatusFetch = window.fetch;
        window.stalledStatusRequests = 0;
        window.fetch = (url, options = {}) => {
          if (String(url).endsWith('/schedule-studio/api/state')) {
            window.stalledStatusRequests++;
            return new Promise((resolve, reject) => {
              const fail = () => reject(new DOMException('Aborted', 'AbortError'));
              if (options.signal?.aborted) fail();
              else options.signal?.addEventListener('abort', fail, {once:true});
            });
          }
          return window.originalStatusFetch(url, options);
        };
    ''')
    try:
        WebDriverWait(driver, 15).until(lambda d: 'Unable to refresh station status' in
            d.find_element(By.ID, 'control-message').text)
        assert 'unavailable' in driver.find_element(By.ID, 'broadcast-message').text
    finally:
        driver.execute_script('window.fetch = window.originalStatusFetch')
    WebDriverWait(driver, 15).until(lambda d: d.find_element(By.ID, 'control-message').text == '')
    assert driver.execute_script('return window.stalledStatusRequests') >= 1


def test_lost_broadcast_response_recovers_without_duplicate_request(booth):
    app, driver, base, tmp_path = booth
    driver.get(base + '/admin/stations/test-station/schedule-studio/control')
    # The rendered hint confirms the page script attached its control handlers.
    WebDriverWait(driver, 12).until(lambda d: d.find_element(By.ID, 'broadcast-hint').text)
    with app.app_context():
        revision = Station.query.filter_by(slug='test-station').one().broadcast_revision
    driver.execute_script('''
        window.originalBroadcastFetch = window.fetch;
        window.broadcastRequests = 0;
        window.fetch = (url, options = {}) => {
          if (String(url).endsWith('/schedule-studio/api/broadcast') && options.method === 'POST') {
            window.broadcastRequests++;
            return window.originalBroadcastFetch(url, options).then(response => new Promise((resolve, reject) => {
              const fail = () => reject(new DOMException('Aborted', 'AbortError'));
              if (options.signal?.aborted) fail();
              else options.signal?.addEventListener('abort', fail, {once:true});
            }));
          }
          return window.originalBroadcastFetch(url, options);
        };
        const toggle = document.getElementById('master-broadcast-toggle');
        toggle.click(); toggle.click();
    ''')
    try:
        WebDriverWait(driver, 12).until(lambda d: 'Request timed out' in
            d.find_element(By.ID, 'control-message').text)
        WebDriverWait(driver, 12).until(lambda d: d.find_element(By.ID,
            'master-broadcast-toggle').get_attribute('aria-checked') == 'false')
        assert driver.find_element(By.ID, 'master-broadcast-toggle').is_enabled()
        assert driver.execute_script('return window.broadcastRequests') == 1
        with app.app_context():
            station = Station.query.filter_by(slug='test-station').one()
            assert station.desired_state == 'stopped'
            assert station.broadcast_revision == revision + 1
    finally:
        driver.execute_script('window.fetch = window.originalBroadcastFetch')
