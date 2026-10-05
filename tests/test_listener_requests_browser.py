"""Real Chromium public embed, settings, and request-to-deck intent."""
from datetime import datetime, timezone
import threading
from werkzeug.serving import make_server
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from app.extensions import db
from app import models as m
from app.services import listener_requests as r
from tests.test_live_browser import booth, app_fixture, wait_text
from tests.test_playlists import setup_playlist


def test_public_embed_without_third_party_cookies_and_mobile(booth):
    app, driver, base, folder = booth
    with app.app_context():
        station = m.Station.query.filter_by(slug='test-station').one()
        station.request_settings = dict(r.DEFAULTS, enabled=True)
        db.session.commit()
    driver.execute_cdp_cmd('Network.setCookieControls', dict(enableThirdPartyCookieRestriction=True,
        disableThirdPartyCookieMetadata=True, disableThirdPartyCookieHeuristics=True))
    def outer(environ, start_response):
        start_response('200 OK', [('Content-Type', 'text/html')])
        return [f'<html><body><iframe title="Request" src="{base}/requests/test-station" width="350" height="700"></iframe></body></html>'.encode()]
    server = make_server('127.0.0.1', 0, outer)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        driver.get(f'http://localhost:{server.server_port}')
        driver.switch_to.frame(driver.find_element(By.TAG_NAME, 'iframe'))
        wait_text(driver, '#songs', 'Verified Test Track')
        driver.find_element(By.CSS_SELECTOR, '#songs button').click()
        wait_text(driver, '#notice', 'Request received')
        assert driver.execute_script('return document.documentElement.scrollWidth <= innerWidth')
        driver.save_screenshot(str(folder / 'request-widget.png'))
        with app.app_context(): assert m.ListenerRequest.query.one().status == 'pending'
    finally:
        driver.switch_to.default_content(); server.shutdown(); thread.join(timeout=3)


def test_settings_save_and_dj_request_load(booth, monkeypatch):
    app, driver, base, folder = booth
    monkeypatch.setattr('app.services.media_storage.LocalMediaStorage.regular_file', lambda *args: '/safe')
    driver.get(base + '/admin/stations/test-station/settings')
    WebDriverWait(driver, 10).until(lambda d: d.find_elements(By.NAME, 'request_enabled'))
    driver.execute_script("""const f=document.getElementById('station-settings-form');
      f.elements.request_enabled.checked=true;f.elements.request_delay_songs.value='0';
      f.elements.request_restrict_programming.checked=false;f.requestSubmit();""")
    wait_text(driver, '#station-save-status', 'All changes saved')
    with app.app_context():
        station, _, tracks = setup_playlist()
        assert r.settings(station)['enabled'] and r.settings(station)['delay_songs'] == 0
        request = r.submit(station, tracks[1].uuid, 'browser', 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa')
        db.session.commit(); identifier = request.id
    driver.get(base + '/admin/stations/test-station/requests')
    wait_text(driver, 'article', 'Song 2')
    from selenium.webdriver.support.ui import Select
    Select(driver.find_element(By.NAME, 'deck')).select_by_visible_text('B')
    driver.find_element(By.CSS_SELECTOR, 'form[action$="/load"] button').click()
    WebDriverWait(driver, 10).until(lambda d: 'Waiting for confirmed playback' in d.find_element(By.TAG_NAME, 'body').text)
    with app.app_context():
        command = m.LiveControlCommand.query.filter_by(action='DECK_LOAD').one()
        assert command.target_decision.listener_request_id == identifier and not command.play_on_load
    driver.set_window_size(390, 844)
    assert driver.execute_script('return document.documentElement.scrollWidth <= innerWidth')
    driver.save_screenshot(str(folder / 'requests-inbox-mobile.png'))
