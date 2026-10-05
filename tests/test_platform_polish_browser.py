"""Real player playback stays independent of ads and Canvas failures."""
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select, WebDriverWait
from app.extensions import db
from app.models import Station, StationPlayerAsset, StationPlayerSettings
from app.services import player
from tests.test_live_browser import booth, app_fixture, wait_text
from tests.test_station_settings_flags import png
import hashlib


def seed_ads(app, source='image'):
    with app.app_context():
        station = Station.query.filter_by(slug='test-station').one()
        station.player_settings = StationPlayerSettings(config=dict(player.DEFAULTS,
            ad_top_enabled=True, ad_top_url='https://example.test/sponsor',
            ad_top_source=source, ad_top_unit='/1234/station/top',
            ad_top_iframe='https://example.test/adapter', merch_url='https://example.test/store'))
        for kind, width, height in [('ad_top',728,90), ('ad_top_mobile',320,50)]:
            data = png(width,height)
            db.session.add(StationPlayerAsset(station_id=station.id, kind=kind, width=width,
                height=height, image=data, version=hashlib.sha256(data).hexdigest()))
        db.session.commit()


def test_images_visual_modes_reduced_motion_and_audio_failure_isolation(booth):
    app, driver, base, tmp = booth
    seed_ads(app)
    driver.get(base+'/player/test-station')
    wait_text(driver, '#recent-history', 'Verified Test Track')
    WebDriverWait(driver, 10).until(lambda d: d.find_element(By.CSS_SELECTOR, '.phase9-ad').is_displayed())
    assert driver.find_element(By.CSS_SELECTOR,'.phase9-ad img').get_attribute('width') == '728'
    assert not driver.find_elements(By.CSS_SELECTOR, '[data-placement="ad_bottom"]')
    driver.find_element(By.ID,'play-button').click()
    WebDriverWait(driver, 8).until(lambda d: d.execute_script('return !document.getElementById("station-audio").paused'))
    for mode in ('fractal','spectrum','waveform','particles','ambient'):
        Select(driver.find_element(By.ID,'visual-mode')).select_by_value(mode)
        WebDriverWait(driver, 5).until(lambda d: d.find_element(By.ID,'player-visual').get_attribute('data-mode') == mode)
        assert driver.execute_script('return !document.getElementById("station-audio").paused')
    driver.set_window_size(390,844)
    WebDriverWait(driver, 5).until(lambda d: d.execute_script("return document.querySelector('.phase9-ad img')?.getAttribute('width')==='320'"))
    assert driver.execute_script('return document.documentElement.scrollWidth<=innerWidth+2')
    driver.execute_cdp_cmd('Emulation.setEmulatedMedia', {'features':[{'name':'prefers-reduced-motion','value':'reduce'}]})
    driver.execute_async_script('const done=arguments[0];requestAnimationFrame(()=>requestAnimationFrame(done))')
    driver.save_screenshot('/tmp/freo-phase9-player-mobile.png')
    # Reduced motion results in a stable Canvas while playback continues.
    before = driver.execute_script('return document.getElementById("player-visual").toDataURL()')
    driver.execute_async_script('const done=arguments[0];setTimeout(done,150)')
    assert before == driver.execute_script('return document.getElementById("player-visual").toDataURL()')
    assert driver.execute_script('return !document.getElementById("station-audio").paused')
    driver.execute_script("document.querySelector('.phase9-ad img').dispatchEvent(new Event('error'));CanvasRenderingContext2D.prototype.clearRect=()=>{throw new Error('simulated canvas failure')};document.getElementById('visual-mode').dispatchEvent(new Event('change'))")
    assert not driver.find_element(By.CSS_SELECTOR,'.phase9-ad').is_displayed()
    assert driver.execute_script('return !document.getElementById("station-audio").paused')
    driver.get(base+'/admin/stations/test-station/settings')
    assert not driver.execute_script('return !!window.googletag')


def test_iframe_fill_contract_rejects_spoofed_messages_and_times_out(booth):
    app, driver, base, tmp = booth
    seed_ads(app, 'iframe')
    driver.execute_cdp_cmd('Network.enable', {})
    driver.execute_cdp_cmd('Network.setBlockedURLs', {'urls':['https://example.test/*']})
    driver.get(base+'/player/test-station')
    wait_text(driver,'#recent-history','Verified Test Track')
    assert not driver.find_element(By.CSS_SELECTOR,'.phase9-ad').is_displayed()
    driver.execute_script("window.postMessage({type:'freo-ad-status',status:'filled',placement:'ad_top',nonce:'fake',width:728,height:90},'*')")
    assert not driver.find_element(By.CSS_SELECTOR,'.phase9-ad').is_displayed()
    driver.find_element(By.ID,'play-button').click()
    WebDriverWait(driver, 8).until(lambda d: d.execute_script('return !document.getElementById("station-audio").paused'))
    WebDriverWait(driver, 15).until(lambda d: not d.find_elements(By.CSS_SELECTOR,'.phase9-ad iframe'))
    assert not driver.find_element(By.CSS_SELECTOR,'.phase9-ad').is_displayed()
    assert driver.execute_script('return !document.getElementById("station-audio").paused')


def test_google_adapter_fill_empty_and_public_document_boundary(booth):
    app, driver, base, tmp = booth
    seed_ads(app, 'google')
    driver.execute_cdp_cmd('Network.enable', {})
    driver.execute_cdp_cmd('Network.setBlockedURLs', {'urls':['https://securepubads.g.doubleclick.net/*']})
    # Provider contract double. No live ad request, account or impression.
    driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {'source': """
      if(location.pathname.startsWith('/player/')) {
        const listeners=new Set();const service={addEventListener:(n,f)=>listeners.add(f),removeEventListener:(n,f)=>listeners.delete(f)};
        window.googletag={cmd:{push:f=>f()},pubads:()=>service,enableServices:()=>{},destroySlots:()=>{},
          defineSlot:(unit,size,id)=>{const slot={setConfig:c=>{window.testCollapse=c.collapseDiv},addService:()=>{}};window.testSlot=slot;window.testAdSize=size;window.testAdTarget=id;return slot;},
          display:()=>{window.testAdReady=true}};
        window.testFill=(empty=false)=>{document.getElementById(window.testAdTarget).textContent=empty?'':'Mock sponsor';for(const f of listeners)f({slot:window.testSlot,isEmpty:empty,size:window.testAdSize});};
      }
    """})
    driver.get(base+'/player/test-station')
    WebDriverWait(driver, 8).until(lambda d: d.execute_script('return window.testAdReady'))
    assert driver.execute_script('return window.testCollapse') == 'BEFORE_FETCH'
    assert not driver.find_element(By.CSS_SELECTOR,'.phase9-ad').is_displayed()
    driver.execute_script('window.testFill()')
    assert driver.find_element(By.CSS_SELECTOR,'.phase9-ad').is_displayed()
    driver.execute_script('window.testFill(true)')
    assert not driver.find_element(By.CSS_SELECTOR,'.phase9-ad').is_displayed()
    driver.find_element(By.CSS_SELECTOR,'.radio-site-header nav a:last-child').click()
    WebDriverWait(driver, 8).until(lambda d: '/admin' in d.current_url)
    assert not driver.execute_script('return !!window.googletag')
