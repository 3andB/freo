"""Real pointer workflows for the September music and scheduling changes."""
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import Select, WebDriverWait
from app.extensions import db
from app.models import Station, Track, Playlist, ChannelSchedule, MusicImportItem
from app.services import visual_schedule as vs
from tests.test_live_browser import booth, app_fixture, open_import, wait_text
from tests.test_import_sessions_browser import add_audio, work, click


def test_expanded_import_apply_all_organization_and_fresh_return(booth):
    app,driver,base,tmp_path=booth
    with app.app_context():
        playlist=Playlist(station_id=1,name='New arrivals');db.session.add(playlist);db.session.commit()
        playlist_id=playlist.id
    open_import(driver,base)
    add_audio(driver,tmp_path,index=1,artist='First artist',album='First album')
    work(app,True);wait_text(driver,'.import-card','Ready to import')
    add_audio(driver,tmp_path,index=2,artist='Second artist',album='Second album')
    work(app,True);wait_text(driver,'.import-card:last-child','Ready to import')
    assert driver.execute_script("return [...document.querySelectorAll('.import-row-editor')].every(el=>!el.hidden)")
    assert driver.execute_script("return [...document.querySelectorAll('.import-more')].every(el=>el.open)")
    assert driver.execute_script("return document.querySelector('.drop-zone').getBoundingClientRect().height>=220")
    driver.save_screenshot('/tmp/freo-import-expanded-desktop.png')
    first=driver.find_element(By.CSS_SELECTOR,'.import-card')
    apply=first.find_element(By.XPATH,".//button[text()='Apply artist & album to all']")
    driver.execute_script('arguments[0].scrollIntoView({block:"center"})',apply);apply.click()
    wait_text(driver,'#import-message','applied to 2 songs')
    with app.app_context():
        rows=MusicImportItem.query.all()
        assert all(row.choices['artist_name']=='First artist' and row.choices['album_name']=='First album' for row in rows)
        assert {row.detected['title'] for row in rows}=={'Song 1','Song 2'}
    click(driver,'#undo-batch');wait_text(driver,'#import-message','Shared changes undone')
    with app.app_context():assert all('artist_name' not in row.choices for row in MusicImportItem.query.all())
    click(driver,'#edit-selected')
    chip=driver.find_element(By.XPATH,"//*[@id='batch-classification']//button[contains(.,'New arrivals')]")
    chip.click();Select(driver.find_element(By.ID,'batch-sharing')).select_by_value('all')
    click(driver,'#apply-batch');wait_text(driver,'#batch-status','Updated 2 songs')
    click(driver,'#media-upload-form [type=submit]');wait_text(driver,'#import-message','Import started');work(app)
    wait_text(driver,'#import-completion','2 in your library')
    with app.app_context():
        songs=Track.query.filter(Track.title.in_(['Song 1','Song 2'])).all()
        assert len(songs)==2 and all(song.available_to_all for song in songs)
        assert all(playlist_id in [p.id for p in song.playlists] for song in songs)
    click(driver,'#view-imported');wait_text(driver,'#room-total','2')
    click(driver,'#room-select-all');click(driver,'#share-selected');wait_text(driver,'#room-message-text','2 song(s) available to all channels')
    with app.app_context():assert not Track.query.filter_by(title='Verified Test Track').one().available_to_all
    click(driver,'.studio-heading a[href$="/media/upload"]')
    WebDriverWait(driver,10).until(lambda d:d.execute_script("return !!document.querySelector('.drop-zone')?.ondrop"))
    assert driver.find_elements(By.CSS_SELECTOR,'.import-card')==[]
    assert 'Processing' in driver.find_element(By.ID,'import-sessions').text
    # An empty workspace is reused on reload.
    workspace=driver.find_element(By.ID,'import-sessions').get_attribute('value')
    driver.refresh();WebDriverWait(driver,10).until(lambda d:d.execute_script("return !!document.querySelector('.drop-zone')?.ondrop"))
    assert driver.find_element(By.ID,'import-sessions').get_attribute('value')==workspace
    driver.set_window_size(390,900)
    assert driver.execute_script('return document.documentElement.scrollWidth<=innerWidth')
    assert driver.execute_script("return document.querySelector('.drop-zone').getBoundingClientRect().height>=160")
    driver.save_screenshot('/tmp/freo-import-expanded-new.png')


def test_recurring_pointer_resize_move_cancel_and_visibility(booth):
    app,driver,base,tmp_path=booth
    with app.app_context():
        station=Station.query.filter_by(slug='test-station').one();policy=vs.policy(station,True)
        ref=vs.source(station,dict(kind='song',id=Track.query.first().id))
        policy.calendar=vs.clean_document(station,[dict(id='series',start=10800,end=18000,source=ref,rule=dict(frequency='weekly',anchor='2026-09-21',weekdays=[0]))]);policy.calendar_saved=True;db.session.commit()
    driver.get(base+'/admin/stations/test-station/schedule-studio/calendar?date=2026-09-21&view=week')
    wait_text(driver,'#timeline','Verified Test Track')
    click(driver,'[data-id="series"]')
    assert not driver.find_element(By.ID,'section-inspector').is_displayed()
    assert driver.find_element(By.ID,'edit-selected-section').is_displayed()
    def drag(selector,dx,dy):
        target=driver.find_element(By.CSS_SELECTOR,selector)
        driver.execute_script('arguments[0].scrollIntoView({block:"center"})',target)
        ActionChains(driver).move_to_element(target).click_and_hold().move_by_offset(dx,dy).pause(.1).release().perform()
    def scope():
        WebDriverWait(driver,5).until(lambda d:d.find_element(By.ID,'move-scope-dialog').is_displayed())
        assert not driver.find_element(By.ID,'section-inspector').is_displayed()
    drag('[data-id="series"] .resize-grip.bottom',0,42);scope()
    assert '05:30' in driver.find_element(By.ID,'move-scope-summary').text
    driver.find_element(By.ID,'cancel-move-scope').click()
    assert driver.execute_script("return localStorage.getItem('freo-schedule:test-station:calendar:draft')") is None
    drag('[data-id="series"] .resize-grip.top',0,-42);scope()
    assert '02:30' in driver.find_element(By.ID,'move-scope-summary').text
    # Cancel while conflict validation is in flight: the delayed response must not apply.
    driver.execute_script("""const original=FreoPage.fetch.bind(FreoPage);window.releasePreview=null;FreoPage.fetch=async(...args)=>{const response=await original(...args);if(args[0].endsWith('/calendar-preview')){FreoPage.fetch=original;await new Promise(resolve=>window.releasePreview=resolve);}return response;};""")
    driver.find_element(By.ID,'apply-move-scope').click()
    WebDriverWait(driver,5).until(lambda d:d.execute_script('return !!window.releasePreview'))
    driver.find_element(By.ID,'cancel-move-scope').click();driver.execute_script('window.releasePreview()')
    WebDriverWait(driver,5).until(lambda d:d.find_element(By.ID,'apply-move-scope').is_enabled())
    assert driver.execute_script("return localStorage.getItem('freo-schedule:test-station:calendar:draft')") is None
    drag('[data-id="series"] .resize-grip.top',0,-42);scope()
    Select(driver.find_element(By.ID,'move-scope')).select_by_value('series')
    driver.find_element(By.ID,'apply-move-scope').click();wait_text(driver,'#studio-message','Schedule updated')
    width=driver.execute_script("return document.querySelector('.time-column').getBoundingClientRect().width")
    drag('[data-id="series"]',round(width),0);scope()
    assert '2026-09-22' in driver.find_element(By.ID,'move-scope-summary').text
    driver.find_element(By.ID,'apply-move-scope').click();wait_text(driver,'#studio-message','Schedule updated')
    click(driver,'#save-schedule');wait_text(driver,'#save-state','Saved')
    with app.app_context():
        saved=ChannelSchedule.query.first().calendar
        repeating=next(row for row in saved if row['id']=='series');once=next(row for row in saved if row['id']!='series')
        assert repeating['start']==9000 and repeating['end']==18000
        assert repeating['rule']['exceptions']==['2026-09-21']
        assert once['rule']['anchor']=='2026-09-22' and (once['start'],once['end'])==(9000,18000)
    driver.refresh();wait_text(driver,'#timeline','Verified Test Track')
    assert '02:30–05:00' in driver.find_element(By.CSS_SELECTOR,'.timeline-section').text
    Select(driver.find_element(By.ID,'recurring-display')).select_by_value('hide')
    # The edited occurrence remains visible when its original series is hidden.
    assert len(driver.find_elements(By.CSS_SELECTOR,'.timeline-section'))==1
    driver.find_element(By.ID,'next-date').click();wait_text(driver,'#hidden-schedules','hidden')
    assert driver.find_elements(By.CSS_SELECTOR,'.timeline-section')==[]
    assert driver.find_elements(By.CSS_SELECTOR,'.hidden-coverage')
    driver.find_element(By.ID,'hidden-schedules').click()
    assert len(driver.find_elements(By.CSS_SELECTOR,'.timeline-section'))==1
    driver.execute_script("document.getElementById('timeline').scrollIntoView({block:'center'})")
    driver.save_screenshot('/tmp/freo-calendar-recurring-new.png')


def test_source_drop_and_short_resize_handles_do_not_open_details(booth):
    app,driver,base,tmp_path=booth
    with app.app_context():
        station=Station.query.filter_by(slug='test-station').one();policy=vs.policy(station,True)
        policy.calendar=[];policy.calendar_saved=True;db.session.commit()
    driver.get(base+'/admin/stations/test-station/schedule-studio/calendar?date=2026-09-21&view=day')
    driver.find_element(By.XPATH,"//nav[@id='source-tabs']/button[text()='Categories']").click()
    wait_text(driver,'#source-results','Power')
    driver.execute_script("const t=document.getElementById('timeline');t.scrollIntoView({block:'center'});t.scrollTop=0")
    source=driver.find_element(By.CSS_SELECTOR,'.source-card')
    position=driver.execute_script("const c=document.querySelector('.time-column').getBoundingClientRect();return {x:c.left+c.width/2,y:c.top+126}")
    actions=ActionChains(driver);actions.move_to_element(source).click_and_hold().pause(.2)
    actions.w3c_actions.pointer_action.move_to_location(round(position['x']),round(position['y']))
    actions.pause(.3).release().perform()
    WebDriverWait(driver,8).until(lambda d:d.find_elements(By.CSS_SELECTOR,'.timeline-section'))
    assert not driver.find_element(By.ID,'section-inspector').is_displayed()
    draft=driver.execute_script("return JSON.parse(localStorage.getItem('freo-schedule:test-station:calendar:draft'))")
    assert (draft['entries'][0]['start'],draft['entries'][0]['end'])==(5400,9000)
    # Exact-time keyboard editing creates a short block with selectable edge handles.
    block=driver.find_element(By.CSS_SELECTOR,'.timeline-section')
    from selenium.webdriver.common.keys import Keys
    block.send_keys(Keys.ENTER)
    driver.execute_script("document.getElementById('section-start').value='01:30:00';document.getElementById('section-end').value='01:31:00'")
    driver.find_element(By.CSS_SELECTOR,'#section-form button[type=submit]').click()
    WebDriverWait(driver,5).until(lambda d:not d.find_element(By.ID,'section-inspector').is_displayed())
    assert driver.find_element(By.CSS_SELECTOR,'.is-short.is-selected .resize-grip.top').is_displayed()
    assert driver.find_element(By.CSS_SELECTOR,'.is-short.is-selected .resize-grip.bottom').is_displayed()
    assert driver.execute_script("return document.querySelector('.timeline-section').getBoundingClientRect().height<2")
    # Closing details also cancels an Apply awaiting server validation.
    driver.find_element(By.CSS_SELECTOR,'.timeline-section').send_keys(Keys.ENTER)
    driver.execute_script("""document.getElementById('section-end').value='01:32:00';const original=FreoPage.fetch.bind(FreoPage);window.releasePreview=null;FreoPage.fetch=async(...args)=>{const response=await original(...args);if(args[0].endsWith('/calendar-preview')){FreoPage.fetch=original;await new Promise(resolve=>window.releasePreview=resolve);}return response;};""")
    driver.find_element(By.CSS_SELECTOR,'#section-form button[type=submit]').click()
    WebDriverWait(driver,5).until(lambda d:d.execute_script('return !!window.releasePreview'))
    driver.find_element(By.CSS_SELECTOR,'#section-inspector .dialog-close').click()
    driver.execute_script('window.releasePreview()')
    WebDriverWait(driver,5).until(lambda d:d.find_element(By.ID,'save-schedule').is_enabled())
    draft=driver.execute_script("return JSON.parse(localStorage.getItem('freo-schedule:test-station:calendar:draft'))")
    assert draft['entries'][0]['end']==5460
