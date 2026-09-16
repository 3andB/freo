"""Listening, calendar navigation, and feedback in an actual browser."""
from datetime import datetime, timezone
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from app.extensions import db
from app.models import Station, StationPlayerSettings, ListenerVote
from app.services import player as service
from tests.test_live_browser import booth, app_fixture, wait_text


def seed(app):
    with app.app_context():
        station=Station.query.filter_by(slug='test-station').one()
        row=StationPlayerSettings(station_id=station.id,revision=1,config=dict(service.DEFAULTS,
            voting_enabled=True,comments_enabled=True,public_totals=True,schedule_enabled=True,
            message_enabled=True,message='Welcome to the late-night frequency. Stay curious. Keep listening.',
            social_enabled=True,socials=[dict(platform='Instagram',url='https://example.test/radio',visible=True)]))
        station.player_settings=row;db.session.add(row);db.session.flush();service.publish(station);db.session.commit()


def test_player_listening_calendar_feedback_and_mobile(booth):
    app,driver,base,tmp=booth;seed(app)
    driver.get(base+'/player/test-station')
    wait_text(driver,'#recent-history','Verified Test Track')
    wait_text(driver,'#schedule-entries','Power')
    driver.find_element(By.ID,'play-button').click()
    WebDriverWait(driver,8).until(lambda d:d.execute_script('return !document.getElementById("station-audio").paused'))
    driver.find_element(By.CSS_SELECTOR,'[data-schedule-view="day"]').click()
    wait_text(driver,'#schedule-entries','Power')
    assert driver.execute_script('return !document.getElementById("station-audio").paused')
    driver.find_element(By.CSS_SELECTOR,'#recent-history .recent-vote').click()
    wait_text(driver,'#feedback-status','Choose a vote')
    driver.find_element(By.CSS_SELECTOR,'[data-vote="1"]').click()
    wait_text(driver,'#feedback-status','saved')
    driver.find_element(By.ID,'feedback-comment').send_keys('Keep this one in rotation')
    driver.find_element(By.ID,'feedback-save').click()
    wait_text(driver,'#feedback-status','saved')
    WebDriverWait(driver,8).until(lambda d:d.find_element(By.ID,'feedback-save').is_enabled())
    driver.find_element(By.CSS_SELECTOR,'.feedback-close').click()
    with app.app_context():
        assert ListenerVote.query.one().comment=='Keep this one in rotation'
    driver.find_element(By.ID,'motion-button').click()
    assert driver.find_element(By.CSS_SELECTOR,'.radio-experience.low-motion')
    driver.execute_script('window.scrollTo(0,0)')
    driver.save_screenshot('/tmp/freo-player-desktop.png')
    driver.set_window_size(390,844)
    driver.execute_script('window.scrollTo(0,0)')
    assert driver.execute_script('return document.documentElement.scrollWidth<=innerWidth+2')
    driver.save_screenshot('/tmp/freo-player-mobile.png')
    driver.find_element(By.ID,'dismiss-message').click()
    driver.refresh()
    assert not driver.find_element(By.CSS_SELECTOR,'.radio-announcement').is_displayed()
    driver.get(base+'/admin/stations/test-station/player-settings')
    assert driver.find_element(By.NAME,'message').get_attribute('value').startswith('Welcome')
    driver.find_element(By.NAME,'message').clear()
    driver.find_element(By.NAME,'message').send_keys('New studio message')
    driver.find_element(By.CSS_SELECTOR,'button[value="save"]').click()
    wait_text(driver,'.admin-notice','saved')
    driver.get(base+'/player/test-station')
    wait_text(driver,'.radio-announcement','New studio message')


def test_public_schedule_views_and_feedback_focus(booth):
    app,driver,base,tmp=booth;seed(app)
    driver.get(base+'/player/test-station')
    wait_text(driver,'#schedule-entries','Power')
    driver.find_element(By.CSS_SELECTOR,'[data-schedule-view="month"]').click()
    WebDriverWait(driver,8).until(lambda d:len(d.find_elements(By.CSS_SELECTOR,'.schedule-day-button'))>=28)
    driver.find_elements(By.CSS_SELECTOR,'.schedule-day-button')[0].click()
    WebDriverWait(driver,8).until(lambda d:d.find_element(By.CSS_SELECTOR,'[data-schedule-view="day"]').get_attribute('aria-pressed')=='true')
    driver.find_element(By.ID,'schedule-today').click()
    wait_text(driver,'#schedule-entries','Power')
    driver.find_element(By.CSS_SELECTOR,'#recent-history .recent-vote').click()
    wait_text(driver,'#feedback-status','Choose a vote')
    title=driver.find_element(By.ID,'feedback-song').text
    driver.find_element(By.ID,'feedback-comment').send_keys('Captured song')
    # Force a now-playing refresh while the comment dialog owns focus.
    driver.execute_script('document.dispatchEvent(new Event("visibilitychange"))')
    assert driver.find_element(By.ID,'feedback-song').text==title
    assert driver.find_element(By.ID,'feedback-comment').get_attribute('value')=='Captured song'


def test_ads_mobile_creatives_reduced_motion_and_draft_preview(booth):
    import hashlib
    from app.models import StationPlayerAsset
    from tests.test_station_settings_flags import png
    app,driver,base,tmp=booth;seed(app)
    with app.app_context():
        row=StationPlayerSettings.query.one()
        row.config=dict(row.config,ad_top_enabled=True,ad_bottom_enabled=True,
            ad_top_alt='Top sponsor',ad_bottom_alt='Bottom sponsor',ad_top_url='https://example.test/sponsor')
        for kind in ('cover','ad_top','ad_bottom','ad_top_mobile','ad_bottom_mobile'):
            raw=png(9,3) if kind.endswith('mobile') else png(20,4)
            db.session.add(StationPlayerAsset(station_id=row.station_id,kind=kind,image=raw,version=hashlib.sha256(raw).hexdigest()))
        db.session.commit()
    driver.set_window_size(390,844)
    driver.execute_cdp_cmd('Emulation.setEmulatedMedia',{'features':[{'name':'prefers-reduced-motion','value':'reduce'}]})
    driver.get(base+'/player/test-station')
    WebDriverWait(driver,8).until(lambda d:len(d.find_elements(By.CSS_SELECTOR,'.radio-ad'))==2)
    assert 'ad_top_mobile' in driver.find_element(By.CSS_SELECTOR,'.radio-ad img').get_property('currentSrc')
    assert driver.execute_script('return getComputedStyle(document.querySelector(".radio-vinyl")).animationName')=='none'
    assert driver.execute_script('return document.documentElement.scrollWidth<=innerWidth+2')
    driver.save_screenshot('/tmp/freo-player-ads-mobile.png')
    driver.get(base+'/admin/stations/test-station/player-settings')
    driver.find_element(By.NAME,'message').clear();driver.find_element(By.NAME,'message').send_keys('Private draft preview')
    driver.find_element(By.CSS_SELECTOR,'button[value="preview-player"]').click()
    WebDriverWait(driver,8).until(lambda d:len(d.window_handles)==2)
    original=driver.current_window_handle
    driver.switch_to.window(next(handle for handle in driver.window_handles if handle!=original))
    wait_text(driver,'.radio-announcement','Private draft preview')
    assert 'Unpublished preview' in driver.find_element(By.CSS_SELECTOR,'.radio-preview-notice').text
    driver.close();driver.switch_to.window(original)
    with app.app_context():assert StationPlayerSettings.query.one().config['message']!='Private draft preview'
