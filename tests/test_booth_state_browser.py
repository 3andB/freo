from datetime import datetime,timezone
import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from app.extensions import db
from app.models import Station,SelectionDecision,LiveCartSlot,LiveQueueSnapshot,Track
from tests.test_live_browser import booth,app_fixture,wait_text


def test_auto_context_persistent_status_and_message_expiry(booth):
    app,driver,base,tmp_path=booth
    with app.app_context():
        station=Station.query.filter_by(slug='test-station').one();station.automation.operator_mode='AUTO';station.automation.hold=False
        snapshot=LiveQueueSnapshot.query.first();snapshot.mixer={};snapshot.broadcast_online=True;snapshot.listeners=12;snapshot.broadcast_observed_at=datetime.now(timezone.utc)
        db.session.commit()
    driver.refresh()
    wait_text(driver,'#auto-category','Power')
    wait_text(driver,'#auto-song','Test Artist — Verified Test Track')
    assert not driver.find_elements(By.ID,'auto-clock')
    assert driver.find_element(By.ID,'booth-notice').is_displayed()
    driver.find_element(By.ID,'auto-skip').click()
    wait_text(driver,'#booth-notice','Fade requested')
    bar=driver.find_element(By.ID,'booth-notice');before=bar.rect
    WebDriverWait(driver,18).until(lambda d:d.find_element(By.ID,'booth-notice').get_attribute('data-message')=='system')
    assert bar.is_displayed() and bar.rect['height']==before['height']
    with app.app_context():
        snapshot=LiveQueueSnapshot.query.first();snapshot.error_code='Connection lost';db.session.commit()
    wait_text(driver,'#booth-notice','Connection lost')
    assert not driver.find_element(By.ID,'auto-skip').is_enabled()
    driver.set_window_size(390,844)
    assert driver.execute_script('return document.documentElement.scrollWidth<=innerWidth')
    driver.save_screenshot('/tmp/freo-auto-state.png')


@pytest.mark.parametrize('delayed_status', [False, True])
def test_cart_glow_global_lock_and_completion_in_both_modes(booth, delayed_status):
    app,driver,base,tmp_path=booth
    with app.app_context():
        station=Station.query.filter_by(slug='test-station').one();track=Track.query.first()
        for role,pos in [('HOT',1),('HOT',2),('ID',1)]:db.session.add(LiveCartSlot(station_id=station.id,role=role,position=pos,track_id=track.id,label=f'{role} {pos}'))
        db.session.commit()
    driver.refresh()
    first='[data-role="HOT"][data-position="1"]'
    # The initial HTML has an enabled cart before the first live observation.
    # This regression delays a post-command response, not initial readiness.
    wait_text(driver,'#morph-text','Verified Test Track')
    WebDriverWait(driver,8).until(lambda d:d.find_element(By.CSS_SELECTOR,first+' [data-fire-cart]').is_enabled())
    if delayed_status:
        driver.execute_script('''
            const original = window.fetch;
            let commandComplete = false, firstHeld = false, restored = false;
            const pending = [];
            window.restoreCartFetch = () => {restored = true; window.fetch = original; pending.forEach(resolve => resolve());};
            window.fetch = async function(url, options) {
                // The persistent header also polls this endpoint. Hold only
                // booth requests, which explicitly include credentials.
                const holdStatus = String(url).endsWith('/live-status') &&
                    options?.credentials === 'same-origin' && commandComplete;
                const response = await original.call(this, url, options);
                if (String(url).endsWith('/fire-cart') && options?.method === 'POST') commandComplete = true;
                // A response already in flight may arrive after restoration.
                else if (holdStatus && !restored) {
                    await new Promise(resolve => {
                        if (!firstHeld) {firstHeld = true; window.releaseCartStatus = resolve;}
                        else pending.push(resolve);
                    });
                }
                return response;
            };
        ''')
    driver.find_element(By.CSS_SELECTOR,first+' [data-fire-cart]').click()
    wait_text(driver,first,'QUEUED')
    if delayed_status:
        WebDriverWait(driver,8).until(lambda d:d.execute_script('return typeof window.releaseCartStatus === "function"'))
        # Let multiple 250 ms background-poll opportunities pass while the
        # command's own authoritative status response is held back.
        driver.execute_async_script('const done=arguments[0];setTimeout(done,1100)')
        driver.execute_script('window.releaseCartStatus()')
        WebDriverWait(driver,8).until(lambda d:d.find_element(By.ID,'dj-booth').get_attribute('aria-busy')!='true')
        assert all(not button.is_enabled() for button in driver.find_elements(By.CSS_SELECTOR,'[data-fire-cart]'))
        driver.execute_script('window.restoreCartFetch()')
    assert all(not button.is_enabled() for button in driver.find_elements(By.CSS_SELECTOR,'[data-fire-cart]'))
    assert 'cart-queued' in driver.find_element(By.CSS_SELECTOR,first).get_attribute('class')
    with app.app_context():
        cart=SelectionDecision.query.filter_by(playback_bus='CART').one();cart.status='started';cart.started_at=datetime.now(timezone.utc)
        snapshot=LiveQueueSnapshot.query.first();snapshot.mixer={**snapshot.mixer,'cart_id':cart.id};db.session.commit()
    wait_text(driver,first,'PLAYING')
    assert 'cart-playing' in driver.find_element(By.CSS_SELECTOR,first).get_attribute('class')
    assert driver.find_element(By.CSS_SELECTOR,'[data-role="HOT"][data-position="2"] [data-fire-cart]').text=='PLAY'
    assert all(not button.is_enabled() for button in driver.find_elements(By.CSS_SELECTOR,'[data-fire-cart]'))
    driver.save_screenshot('/tmp/freo-cart-playing.png')
    with app.app_context():
        station=Station.query.filter_by(slug='test-station').one();station.automation.operator_mode='AUTO'
        snapshot=LiveQueueSnapshot.query.first();snapshot.mixer={**snapshot.mixer,'mode':'AUTO'};db.session.commit()
    WebDriverWait(driver,8).until(lambda d:d.find_element(By.ID,'dj-booth').get_attribute('data-mode')=='AUTO')
    wait_text(driver,first,'PLAYING')
    with app.app_context():
        snapshot=LiveQueueSnapshot.query.first();snapshot.mixer={**snapshot.mixer,'cart_id':None};db.session.commit()
    WebDriverWait(driver,8).until(lambda d:all(button.is_enabled() for button in d.find_elements(By.CSS_SELECTOR,'[data-fire-cart]')))
    assert driver.find_element(By.CSS_SELECTOR,first+' [data-fire-cart]').text=='PLAY'
    assert 'cart-playing' not in driver.find_element(By.CSS_SELECTOR,first).get_attribute('class')
