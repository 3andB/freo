"""Real browser dashboard, filters, navigation, map and narrow-screen layout."""
import time
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from app.extensions import db
from app.services.statistics import collect
from tests.test_live_browser import booth, app_fixture, wait_text


def test_statistics_visuals_and_sort_survive_refresh(booth):
    from app.models import SessionBucket, StatsState, StatsBucket, StorageSnapshot
    from app.services.statistics.sessions import empty
    app, driver, base, tmp_path = booth
    now = int(time.time())
    with app.app_context():
        values = empty()
        values.update(starts=1400, completed=1200, interrupted=10, duration_seconds=1440000,
                      covered_seconds=3500, bands=[120, 180, 240, 300, 240, 120],
                      devices={'desktop': 1000, 'mobile': 200, 'tablet': 120, 'other/unknown': 80},
                      players={'Chrome': 1000, 'Safari': 320, 'VLC': 80})
        db.session.add(SessionBucket(scope=1, at=(now-3600)//3600*3600, data=values))
        db.session.add(StatsState(scope=1, data=dict(at=now, since=now-7200, listeners=42, online=True,
            sessions_since=now-7200, session_clients_at=now, session_clients_valid=True)))
        for index in range(24):
            at=(now-7200+index*180)//60*60
            count=20+index%8*3
            db.session.add(StatsBucket(scope=1,resolution='minute',at=at,observed_seconds=60,
                listener_seconds=count*60,online_seconds=60,peak=count+5,bytes_sent=count*1000,transfer_seconds=60))
        db.session.add(StorageSnapshot(scope=1,at=now//3600*3600,data=dict(total=64000000,music=60000000,
            recordings=3000000,artwork=1000000,missing=0,errors=0,files=120,retained=0,staging=0)))
        db.session.commit()
    driver.get(base+'/admin/stations/test-station/stats?range=24h&tab=audience')
    wait_text(driver,'#session-summary','20 min')
    assert len(driver.find_elements(By.CSS_SELECTOR,'#device-table .stats-share-track')) == 4
    assert len(driver.find_elements(By.CSS_SELECTOR,'#session-retention .stats-share-track')) == 5
    heading=driver.find_element(By.CSS_SELECTOR,'#device-table th:nth-child(3) button')
    driver.execute_script('arguments[0].scrollIntoView({block:"center"})',heading)
    heading.click()
    # Read one DOM snapshot: polling can replace rows between WebDriver calls.
    cells=lambda:driver.execute_script("return [...document.querySelectorAll('#device-table tbody td:nth-child(3)')].map(e=>e.textContent)")
    assert cells()==['80','120','200','1,000']
    previous_row=driver.find_element(By.CSS_SELECTOR,'#device-table tbody tr')
    driver.execute_script('document.getElementById("stats-filters").requestSubmit()')
    WebDriverWait(driver,15).until(EC.staleness_of(previous_row))
    assert heading == driver.find_element(By.CSS_SELECTOR,'#device-table th:nth-child(3) button')
    assert cells()==['80','120','200','1,000']
    assert driver.find_element(By.CSS_SELECTOR,'#device-table th:nth-child(3)').get_attribute('aria-sort')=='ascending'
    band_heading=driver.find_element(By.CSS_SELECTOR,'#session-bands th:first-child button')
    driver.execute_script('arguments[0].scrollIntoView({block:"center"})',band_heading)
    band_heading.click()
    bands=lambda:driver.execute_script("return [...document.querySelectorAll('#session-bands tbody td:first-child')].map(e=>e.textContent)")
    expected_bands=['Under 1 minute','1–5 minutes','5–15 minutes','15–30 minutes','30–60 minutes','60+ minutes']
    assert bands()==expected_bands
    band_heading.click()
    assert bands()==expected_bands[::-1]
    band_heading.click()
    driver.execute_script("document.getElementById('stats-range').value='7d'; document.dispatchEvent(new Event('visibilitychange'))")
    assert 'range=24h' in driver.find_element(By.ID,'stats-export').get_attribute('href')
    for width,theme in ((1440,'day'),(390,'day'),(1440,'night'),(390,'night')):
        driver.set_window_size(width,1100)
        driver.execute_script("document.querySelector('[data-appearance=\"' + arguments[0] + '\"]').click()",theme)
        assert driver.execute_script('return document.documentElement.dataset.theme') == theme
        for target in ('audience-chart','session-summary','session-bands','device-table','stats-map'):
            driver.execute_script('document.getElementById(arguments[0]).scrollIntoView({block:"center"})',target)
            assert driver.execute_script('return document.documentElement.scrollWidth <= innerWidth + 1')
            driver.save_screenshot(str(tmp_path/f'{target}-{width}-{theme}.png'))
    assert not [r for r in driver.get_log('browser') if r['level']=='SEVERE' and r.get('source')=='javascript']


def test_session_devices_retention_and_csv_in_browser(booth):
    from tests.test_statistics_sessions import tick
    app, driver, base, tmp_path = booth
    now = int(time.time())
    with app.app_context():
        for at in range(now - 90, now - 29, 15):
            tick(at, ['phone'])
        tick(now - 15, [])
        tick(now, ['desktop'], agent='Mozilla/5.0 (Windows NT 10.0) Chrome/130.0')
    driver.get(base + '/admin/stations/test-station/stats?range=live&compare=1')
    wait_text(driver, '#session-summary', '1 min')
    assert 'mobile' in driver.find_element(By.ID, 'device-table').text
    assert 'desktop' in driver.find_element(By.ID, 'device-table').text
    driver.find_element(By.CSS_SELECTOR, '[data-tab="audience"]').click()
    assert driver.find_elements(By.CSS_SELECTOR, '#session-duration-chart svg')
    assert '100%' in driver.find_element(By.ID, 'session-retention').text
    driver.find_element(By.CSS_SELECTOR, '#session-trend-data').find_element(By.XPATH, '../summary').click()
    assert '1 min' in driver.find_element(By.ID, 'session-trend-data').text
    exported = driver.execute_async_script('''
      const done = arguments[0];
      fetch(document.getElementById('stats-export').href).then(r => r.text()).then(done);
    ''')
    assert 'Devices,mobile,1,50.0,0' in exported
    assert 'Sessions,average_seconds,60.0' in exported
    assert 'Duration retention' in exported
    driver.set_window_size(390, 844)
    assert driver.execute_script('return document.documentElement.scrollWidth <= window.innerWidth + 1')
    assert not [r for r in driver.get_log('browser') if r['level'] == 'SEVERE' and 'favicon.ico' not in r['message']]


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
    # The screenshot/navigation exercise can exceed the 45-second freshness TTL.
    # Model the running collector before asking the new page for a fresh sample.
    with app.app_context():
        collect.tick({1:dict(online=True,listeners=4,bytes=60100,epoch='e',source_epoch='s',clients=[]),
                      2:dict(online=False,listeners=0,clients=[])},int(time.time()))
    previous=driver.find_element(By.ID,'statistics')
    Select(driver.find_element(By.ID,'stats-scope')).select_by_value('/admin/stations/test-station/stats')
    # The previous scope also says Updated until workspace navigation completes.
    WebDriverWait(driver,15).until(EC.staleness_of(previous))
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
