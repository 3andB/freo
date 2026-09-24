"""Real browser dashboard, filters, navigation, map and narrow-screen layout."""
import time
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from app.extensions import db
from app.services.statistics import collect
from tests.test_live_browser import booth, app_fixture, wait_text


def test_statistics_dashboard_and_world_map(booth):
    app,driver,base,tmp_path=booth
    now=int(time.time())
    with app.app_context():
        collect.tick({1:dict(online=True,listeners=3,bytes=100,epoch='e',source_epoch='s',clients=[]),
                      2:dict(online=False,listeners=0,clients=[])},now-15)
        collect.tick({1:dict(online=True,listeners=4,bytes=30100,epoch='e',source_epoch='s',clients=[]),
                      2:dict(online=False,listeners=0,clients=[])},now)
        collect.presence(1,'website','browser',dict(place='perth',country='Australia',country_code='AU',city='Perth',region='Western Australia',lat=-31.95,lon=115.86),now)
        db.session.commit()
    driver.get(base+'/admin/stats')
    wait_text(driver,'#stats-freshness','Updated')
    assert len(driver.find_elements(By.CSS_SELECTOR,'.stats-metric'))==8
    assert 'Verified Test Track' in driver.find_element(By.ID,'top-songs').text
    WebDriverWait(driver,15).until(lambda d:d.find_element(By.ID,'statistics').get_attribute('data-map-ready')=='true')
    Select(driver.find_element(By.ID,'map-source')).select_by_value('website')
    wait_text(driver,'#location-list','Perth')
    driver.find_element(By.CSS_SELECTOR,'[data-map="all"]').click()
    wait_text(driver,'#map-summary','Recorded sessions')
    driver.execute_script('document.getElementById("stats-map").scrollIntoView({block:"center"})')
    driver.save_screenshot('/tmp/freo-statistics-map.png')
    driver.execute_script('window.scrollTo(0,0)')
    driver.save_screenshot('/tmp/freo-statistics-desktop.png')
    for tab in ('music','engagement','resources','reliability','audience'):
        button=driver.find_element(By.CSS_SELECTOR,f'[data-tab="{tab}"]')
        driver.execute_script('arguments[0].scrollIntoView({block:"center"})',button)
        button.click()
        assert driver.find_element(By.CSS_SELECTOR,f'[data-tab="{tab}"]').get_attribute('aria-selected')=='true'
    driver.set_window_size(390,844)
    driver.save_screenshot('/tmp/freo-statistics-mobile.png')
    assert driver.execute_script('return document.documentElement.scrollWidth <= window.innerWidth + 1')
    driver.set_window_size(1600,1200)
    Select(driver.find_element(By.ID,'stats-scope')).select_by_value('/admin/stations/test-station/stats')
    wait_text(driver,'#stats-freshness','Updated')
    assert 'Test Station' in driver.find_element(By.CSS_SELECTOR,'.stats-heading').text
    errors=[r for r in driver.get_log('browser') if r['level']=='SEVERE' and 'favicon.ico' not in r['message']]
    assert not errors,errors

    # Sign out before clearing the jar: an in-flight authenticated poll can
    # otherwise legitimately refresh the still-active login cookie.
    driver.find_element(By.CSS_SELECTOR,'form[action="/admin/logout"] button').click()
    WebDriverWait(driver,10).until(lambda d:d.current_url==base+'/')
    driver.delete_all_cookies()
    driver.get(base+'/player/test-station')
    def visitor_recorded(_):
        from app.models import AudiencePresence
        with app.app_context():
            return AudiencePresence.query.filter_by(scope=1,source='website').count()==2
    WebDriverWait(driver,10).until(visitor_recorded)


def test_stream_pin_and_chart_refresh_arrival_and_departure(booth, monkeypatch):
    app,driver,base,tmp_path=booth
    place=dict(place='perth',country='Australia',country_code='AU',city='Perth',region='WA',lat=-31.95,lon=115.86)
    monkeypatch.setattr('app.services.statistics.geo.lookup',lambda address:place)
    now=int(time.time())
    with app.app_context():
        collect.tick({1:dict(online=True,listeners=0,bytes=0,epoch='refresh',source_epoch='s',clients=[]),2:dict(online=False,listeners=0,clients=[])},now-15)
        collect.tick({1:dict(online=True,listeners=1,bytes=1000,epoch='refresh',source_epoch='s',clients=[dict(id='real-listener',ip='8.8.8.8',connected=1)]),2:dict(online=False,listeners=0,clients=[])},now)
        db.session.commit()
    driver.get(base+'/admin/stats?range=live&map=live&source=stream')
    wait=WebDriverWait(driver,25)
    wait.until(lambda d:d.find_element(By.ID,'statistics').get_attribute('data-map-locations')=='1')
    wait_text(driver,'#location-list','Perth')
    assert driver.find_elements(By.CSS_SELECTOR,'#audience-chart svg polyline')
    first=driver.find_element(By.ID,'statistics').get_attribute('data-observed-at')
    with app.app_context():
        # A later valid observation removes the departed client on the next poll.
        collect.tick({1:dict(online=True,listeners=0,bytes=2000,epoch='refresh',source_epoch='s',clients=[]),2:dict(online=False,listeners=0,clients=[])},int(time.time()))
        db.session.commit()
    wait.until(lambda d:d.find_element(By.ID,'statistics').get_attribute('data-observed-at')!=first)
    wait.until(lambda d:d.find_element(By.ID,'statistics').get_attribute('data-map-locations')=='0')
    wait_text(driver,'#location-list','No active stream connections')
    # Client-side navigation mounts a fresh map and refresh lifecycle.
    driver.execute_script("FreoWorkspace.navigate('/admin/stations/test-station/stats?range=live')")
    wait.until(lambda d:'/admin/stations/test-station/stats?range=live' in d.current_url and d.find_element(By.ID,'statistics').get_attribute('data-map-ready')=='true')
    assert driver.find_elements(By.CSS_SELECTOR,'#audience-chart svg polyline')
