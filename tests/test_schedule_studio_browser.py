"""Real browser coverage for the visual scheduler and scalable Event picker."""
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait, Select
from app.extensions import db
from app.models import Station, Track, Playlist, PlaylistItem, ScheduleComposition, ScheduleTransition
from tests.test_live_browser import booth, app_fixture, wait_text


def test_station_control_navigation_and_mode_switches(booth):
    from app.models import ChannelSchedule
    from app.services import visual_schedule as vs
    app, driver, base, tmp_path = booth
    with app.app_context():
        station = Station.query.filter_by(slug='test-station').one()
        track = Track.query.first()
        playlist = Playlist(station_id=station.id, name='Control fallback', mode='STRAIGHT')
        playlist.items.append(PlaylistItem(track_id=track.id, position=1))
        db.session.add(playlist); db.session.flush()
        policy = vs.policy(station, True)
        policy.default_playlist_id = playlist.id
        policy.simple = dict(kind='song', id=track.id)
        policy.activated = True
        db.session.commit()
    links = [link.text for link in driver.find_elements(By.CSS_SELECTOR, '.admin-nav > a')]
    assert links[links.index('Playlists') + 1] == 'Shows'
    assert 'Installation / freo.live' not in links
    assert links[0] == 'Overview'
    assert all(label not in links for label in ['Calendar', 'Blocks', 'Simple', 'Schedule'])
    assert not driver.find_elements(By.CSS_SELECTOR, '.admin-nav nav')
    driver.find_element(By.LINK_TEXT, 'Station Control').click()
    wait_text(driver, '#control-status-heading', 'Calendar mode')
    for mode in ['SIMPLE', 'BLOCKS', 'CALENDAR']:
        driver.find_element(By.CSS_SELECTOR, f'[data-switch-mode="{mode}"]').click()
        wait_text(driver, 'dialog[open]', 'Will play now:')
        if mode == 'SIMPLE':
            driver.find_element(By.XPATH, "//dialog[@open]//button[text()='Cancel']").click()
            with app.app_context():
                assert ScheduleTransition.query.count() == 0
            driver.find_element(By.CSS_SELECTOR, f'[data-switch-mode="{mode}"]').click()
            wait_text(driver, 'dialog[open]', 'Will play now:')
        driver.find_element(By.CSS_SELECTOR, 'dialog[open] .admin-primary').click()
        wait_text(driver, '#control-transition', 'Waiting for the playback engine')
        with app.app_context():
            command = ScheduleTransition.query.filter_by(state='PENDING').one()
            assert command.mode == mode
            policy = ChannelSchedule.query.filter_by(station_id=command.station_id).one()
            assert policy.mode != mode
            # Simulate the worker's acknowledgement; engine handoff has separate tests.
            policy.mode = mode
            command.state = 'APPLIED'
            db.session.commit()
        wait_text(driver, '#control-status-heading', f'{mode.title()} mode')
    driver.find_element(By.CSS_SELECTOR, '[data-switch-mode="BLOCKS"]').click()
    wait_text(driver, 'dialog[open]', 'Will play now:')
    driver.find_element(By.CSS_SELECTOR, 'dialog[open] .admin-primary').click()
    wait_text(driver, '#control-transition', 'Waiting for the playback engine')
    with app.app_context():
        command = ScheduleTransition.query.filter_by(state='PENDING').one()
        command.state = 'FAILED'
        command.error = 'Playback engine unavailable. Current mode retained.'
        db.session.commit()
    wait_text(driver, '#control-transition', 'Switch failed: Playback engine unavailable')
    wait_text(driver, '#control-status-heading', 'Calendar mode')
    driver.set_window_size(390, 844)
    assert driver.execute_script('return document.documentElement.scrollWidth <= innerWidth + 2')
    driver.save_screenshot('/tmp/freo-station-control-mobile.png')
    driver.set_window_size(1600, 1200)
    driver.save_screenshot('/tmp/freo-station-control.png')
    driver.find_element(By.LINK_TEXT, 'Open Blocks').click()
    wait_text(driver, '#workspace-title', 'Blocks')
    driver.find_element(By.LINK_TEXT, 'Station Control').click()
    wait_text(driver, '#control-status-heading', 'Calendar mode')


def test_show_console_simple_confirmation_and_events(booth):
    app,driver,base,tmp_path=booth
    driver.find_element(By.CSS_SELECTOR,'.admin-nav a[href$="/schedule-studio/shows"]').click()
    WebDriverWait(driver,10).until(lambda d:d.find_elements(By.ID,'composition-name') and not d.execute_script('return document.documentElement.classList.contains("is-navigating")'))
    driver.find_element(By.ID,'composition-name').send_keys('Morning Study Monday')
    driver.find_element(By.ID,'composition-description').send_keys('A quiet start')
    driver.find_element(By.XPATH,"//nav[@id='source-tabs']/button[text()='Songs']").click()
    wait_text(driver,'#source-results','Verified Test Track')
    driver.find_element(By.CSS_SELECTOR,'.source-actions button').click()
    WebDriverWait(driver,5).until(lambda d:d.find_element(By.ID,'section-inspector').is_displayed())
    driver.execute_script("document.getElementById('section-start').value='00:00:00';document.getElementById('section-end').value='01:00:00';")
    driver.find_element(By.CSS_SELECTOR,'#section-form button[type=submit]').click()
    wait_text(driver,'#timeline','Verified Test Track')
    driver.find_element(By.ID,'save-schedule').click()
    wait_text(driver,'#save-state','Saved')
    with app.app_context():
        show=ScheduleComposition.query.filter_by(name='Morning Study Monday').one();assert show.versions[0].duration==3600
    Select(driver.find_element(By.ID,'show-duration')).select_by_value('7200')
    handle=driver.find_element(By.CSS_SELECTOR,'.timeline-section .resize-grip.bottom')
    driver.execute_script("document.getElementById('timeline').style.scrollBehavior='auto';arguments[0].scrollIntoView({block:'center',behavior:'instant'})",handle)
    ActionChains(driver).move_to_element(handle).click_and_hold().move_by_offset(0,84).pause(.1).release().perform()
    # Timeline dragging scrolls the document beneath the fixed station toolbar.
    driver.execute_script("window.scrollTo({top:0,behavior:'instant'})")
    driver.find_element(By.ID,'save-schedule').click()
    wait_text(driver,'#save-state','Saved')
    with app.app_context():
        show=ScheduleComposition.query.filter_by(name='Morning Study Monday').one()
        assert show.versions[-1].duration==7200 and show.versions[-1].sections[0]['end']==7200
    driver.find_element(By.ID,'accordion-toggle').click()
    assert driver.find_element(By.ID,'accordion-toggle').get_attribute('aria-pressed')=='true'
    driver.save_screenshot('/tmp/freo-shows-console.png')
    driver.get(base+'/admin/stations/test-station/schedule-studio/simple')
    wait_text(driver,'#source-results','Morning Study Monday')
    driver.find_element(By.CSS_SELECTOR,'.source-actions button').click()
    driver.find_element(By.ID,'save-schedule').click()
    wait_text(driver,'#save-state','Saved')
    driver.find_element(By.ID,'activate-mode').click()
    wait_text(driver,'#mode-confirm','Confirm & switch now')
    driver.find_element(By.ID,'cancel-mode').click()
    with app.app_context():assert ScheduleTransition.query.count()==0
    driver.find_element(By.ID,'activate-mode').click()
    WebDriverWait(driver,5).until(lambda d:d.find_element(By.ID,'mode-confirm').is_displayed())
    driver.find_element(By.ID,'confirm-mode').click()
    wait_text(driver,'#active-mode','Switching')
    with app.app_context():assert ScheduleTransition.query.count()==1
    driver.get(base+'/admin/stations/test-station/events/create')
    wait_text(driver,'#event-audio-results','Verified Test Track')
    driver.find_element(By.CSS_SELECTOR,'#event-audio-results button').click()
    wait_text(driver,'#event-audio-selected','Selected:')
    Select(driver.find_element(By.ID,'event-recurrence')).select_by_value('WEEKLY')
    assert driver.find_element(By.NAME,'hourly').is_displayed()
    driver.set_window_size(390,844)
    driver.get(base+'/admin/stations/test-station/schedule-studio/calendar')
    assert driver.execute_script('return document.documentElement.scrollWidth <= innerWidth + 2')
    driver.save_screenshot('/tmp/freo-schedule-mobile.png')


def test_blocks_default_playlist_and_full_day_calendar_song(booth):
    from app.models import ChannelSchedule
    app,driver,base,tmp_path=booth
    with app.app_context():
        station=Station.query.filter_by(slug='test-station').one();track=Track.query.first()
        playlist=Playlist(station_id=station.id,name='Always available',mode='STRAIGHT')
        playlist.items.append(PlaylistItem(track_id=track.id,position=1));db.session.add(playlist);db.session.commit()
    driver.get(base+'/admin/stations/test-station/settings')
    wait_text(driver,'#fallback-results','Always available')
    driver.find_element(By.CSS_SELECTOR,'#fallback-results button').click()
    wait_text(driver,'#fallback-status','Default playlist saved')
    driver.get(base+'/admin/stations/test-station/schedule-studio/blocks')
    driver.find_element(By.ID,'composition-name').send_keys('Weekday format')
    driver.find_element(By.XPATH,"//nav[@id='source-tabs']/button[text()='Playlists']").click()
    wait_text(driver,'#source-results','Always available')
    driver.find_element(By.CSS_SELECTOR,'.source-actions button').click()
    WebDriverWait(driver,5).until(lambda d:d.find_element(By.ID,'section-inspector').is_displayed())
    driver.find_element(By.CSS_SELECTOR,'#section-form button[type=submit]').click()
    WebDriverWait(driver,5).until(lambda d:not d.find_element(By.ID,'section-inspector').is_displayed())
    driver.find_element(By.ID,'save-schedule').click();wait_text(driver,'#save-state','Saved')
    driver.find_element(By.ID,'assign-block').click()
    WebDriverWait(driver,5).until(lambda d:d.find_element(By.ID,'assign-dialog').is_displayed())
    driver.execute_script("document.getElementById('assign-start').value='2026-09-21'")
    driver.find_element(By.CSS_SELECTOR,'#assign-form button[type=submit]').click()
    WebDriverWait(driver,5).until(lambda d:not d.find_element(By.ID,'section-inspector').is_displayed())
    driver.find_element(By.ID,'save-schedule').click();wait_text(driver,'#save-state','Saved')
    with app.app_context():
        policy=ChannelSchedule.query.first();assert policy.assignments[0]['rule']['weekdays']==[0,1,2,3,4]
        assert policy.default_playlist_id is not None
    driver.get(base+'/admin/stations/test-station/schedule-studio/calendar?date=2026-09-21&view=day')
    driver.find_element(By.XPATH,"//nav[@id='source-tabs']/button[text()='Songs']").click()
    wait_text(driver,'#source-results','Verified Test Track')
    driver.find_element(By.CSS_SELECTOR,'.source-actions button').click()
    driver.execute_script("document.getElementById('section-start').value='00:00:00';document.getElementById('section-end').value='00:00:00';document.getElementById('section-end-day').value='1';")
    driver.find_element(By.CSS_SELECTOR,'#section-form button[type=submit]').click()
    WebDriverWait(driver,5).until(lambda d:not d.find_element(By.ID,'section-inspector').is_displayed())
    driver.find_element(By.ID,'save-schedule').click();wait_text(driver,'#save-state','Saved')
    with app.app_context():
        rows=[r for r in ChannelSchedule.query.first().calendar if r['source']['kind']=='song']
        assert len(rows)==1 and rows[0]['end']-rows[0]['start']==86400
    driver.find_element(By.ID,'timeline').location_once_scrolled_into_view
    driver.save_screenshot('/tmp/freo-calendar-timeline.png')
