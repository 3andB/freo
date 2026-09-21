"""Real browser proof of reusable Blocks without an implicit fallback playlist."""
import copy
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait, Select
from app.extensions import db
from app.models import Station, Track, Playlist, PlaylistItem, ScheduleComposition, ChannelSchedule
from app.services import visual_schedule as vs
from tests.test_live_browser import booth, app_fixture, wait_text


def click(driver, selector):
    element=WebDriverWait(driver,8).until(lambda d:d.find_element(By.CSS_SELECTOR,selector))
    driver.execute_script("arguments[0].scrollIntoView({block:'center',behavior:'instant'})",element)
    element.click()


def seed(app):
    with app.app_context():
        station=Station.query.filter_by(slug='test-station').one();song=Track.query.first()
        playlist=Playlist(station_id=station.id,name='Playlist 1',mode='STRAIGHT')
        playlist.items.append(PlaylistItem(track_id=song.id,position=1));db.session.add(playlist);db.session.flush()
        policy=vs.policy(station,True);policy.mode='SIMPLE';policy.activated=True
        policy.simple=policy.live_simple=vs.source(station,dict(kind='playlist',id=playlist.id));db.session.commit()
        return playlist.id


def test_block_saved_unassigned_reopened_and_assigned_today(booth):
    app,driver,base,tmp_path=booth;seed(app)
    driver.get(base+'/admin/stations/test-station/schedule-studio/blocks')
    driver.find_element(By.ID,'composition-name').send_keys('Chill Night')
    wait_text(driver,'#source-results','Playlist 1');click(driver,'.source-actions button')
    click(driver,'#section-form button[type=submit]');click(driver,'#save-schedule')
    wait_text(driver,'#block-content-status','Saved · Chill Night')
    wait_text(driver,'#block-assignment-status','Not assigned')
    driver.refresh();wait_text(driver,'#block-content-status','Saved · Chill Night')
    assert driver.find_element(By.ID,'composition-name').get_attribute('value')=='Chill Night'
    click(driver,'#activate-mode');wait_text(driver,'#mode-confirm-play','No Block is assigned to today')
    assert not driver.find_element(By.ID,'confirm-mode').is_enabled()
    click(driver,'#mode-assign-block')
    WebDriverWait(driver,5).until(lambda d:d.find_element(By.ID,'assign-dialog').is_displayed())
    assert Select(driver.find_element(By.ID,'assign-frequency')).first_selected_option.get_attribute('value')=='once'
    click(driver,'#assign-form button[type=submit]')
    wait_text(driver,'#block-assignment-status','Assigned to today')
    with app.app_context():
        block=ScheduleComposition.query.filter_by(name='Chill Night').one();policy=ChannelSchedule.query.first()
        assert block.revision==1 and policy.assignments[0]['pattern'][0]['version']==1
        assert policy.default_playlist_id is None and policy.mode=='SIMPLE'
    click(driver,'#activate-mode');wait_text(driver,'#mode-confirm-play','Will play now: Playlist 1')
    assert driver.find_element(By.ID,'confirm-mode').is_enabled()
    click(driver,'#cancel-mode')
    # Reopening saved content reloads its persisted section bounds.
    click(driver,'#new-composition');click(driver,'.saved-block-card')
    wait_text(driver,'#block-content-status','Saved · Chill Night')
    driver.save_screenshot('/tmp/freo-block-scheduler-desktop.png')
    for width in [390,768]:
        driver.set_window_size(width,1000)
        assert driver.execute_script('return document.documentElement.scrollWidth<=innerWidth+2')
    driver.save_screenshot('/tmp/freo-block-scheduler-mobile.png')


def test_block_time_sliders_resize_zoom_and_save_reload(booth):
    app,driver,base,tmp_path=booth;playlist_id=seed(app)
    with app.app_context():
        station=Station.query.filter_by(slug='test-station').one()
        block=vs.save_composition(station,dict(kind='BLOCK',name='Slider format',sections=[dict(id='music',start=0,end=86400,source=dict(kind='playlist',id=playlist_id))]));db.session.commit()
    driver.get(base+'/admin/stations/test-station/schedule-studio/blocks')
    click(driver,'.saved-block-card');wait_text(driver,'#block-content-status','Saved · Slider format');click(driver,'.timeline-section')
    slider=driver.find_element(By.ID,'block-end-slider')
    driver.execute_script("arguments[0].scrollIntoView({block:'center',behavior:'instant'})",slider)
    # An actual pointer interaction, not dispatching a synthetic input event.
    ActionChains(driver).move_to_element(slider).click().perform()
    end=driver.find_element(By.ID,'block-section-end').get_attribute('value')
    assert '11:' in end or '12:' in end,end
    assert not driver.find_element(By.ID,'block-section-midnight').is_selected()
    assert 'Unsaved' in driver.find_element(By.ID,'save-state').text
    click(driver,'#undo-edit');assert driver.find_element(By.ID,'block-section-midnight').is_selected()
    click(driver,'#redo-edit');assert not driver.find_element(By.ID,'block-section-midnight').is_selected()
    # Exact second precision stays synchronized with the range input.
    driver.execute_script("const input=document.getElementById('block-section-end');input.value='12:34:56';input.dispatchEvent(new Event('input'))")
    click(driver,'#block-apply-times')
    assert driver.find_element(By.ID,'block-end-slider').get_attribute('value')=='45296'
    # Zoom changes scale without changing the underlying schedule.
    zoom=driver.find_element(By.ID,'block-zoom');zoom.send_keys(Keys.END)
    assert zoom.get_attribute('value')=='180'
    handle=driver.find_element(By.CSS_SELECTOR,'.resize-grip.bottom')
    driver.execute_script("arguments[0].scrollIntoView({block:'center',behavior:'instant'})",handle)
    ActionChains(driver).move_to_element(handle).click_and_hold().move_by_offset(0,-45).release().perform()
    assert driver.find_element(By.ID,'block-end-slider').get_attribute('value')=='44396'
    # Cancel a drag with Escape: the saved draft must not move.
    handle=driver.find_element(By.CSS_SELECTOR,'.resize-grip.bottom')
    driver.execute_script("arguments[0].scrollIntoView({block:'center',behavior:'instant'})",handle)
    ActionChains(driver).move_to_element(handle).click_and_hold().move_by_offset(0,-45).send_keys(Keys.ESCAPE).release().perform()
    assert driver.find_element(By.ID,'block-end-slider').get_attribute('value')=='44396'
    click(driver,'#save-schedule');wait_text(driver,'#save-state','Saved')
    driver.refresh();wait_text(driver,'#block-content-status','Saved · Slider format')
    with app.app_context():assert ScheduleComposition.query.one().versions[-1].sections[0]['end']==44396


def test_three_blocks_drag_to_calendar_and_direct_add(booth):
    app,driver,base,tmp_path=booth;playlist_id=seed(app)
    with app.app_context():
        station=Station.query.filter_by(slug='test-station').one()
        for name in ['Chill Night','Bright Day','Weekend']:
            vs.save_composition(station,dict(kind='BLOCK',name=name,sections=[dict(id=name,start=0,end=86400,source=dict(kind='playlist',id=playlist_id))]))
        db.session.commit()
    driver.get(base+'/admin/stations/test-station/schedule-studio/calendar?date=2026-09-21&view=week')
    click(driver,'#source-tabs button:first-child');wait_text(driver,'#source-results','Chill Night')
    for index,name in enumerate(['Chill Night','Bright Day','Weekend']):
        source=driver.find_element(By.XPATH,f"//div[contains(@class,'source-card')][.//strong[text()='{name}']]")
        target=driver.find_element(By.CSS_SELECTOR,f'.time-column[data-date="2026-09-{21+index}"]')
        # Native HTML drag payload and drop coordinates exercise the same browser handlers.
        driver.execute_script("""const data=new DataTransfer();arguments[0].dispatchEvent(new DragEvent('dragstart',{bubbles:true,dataTransfer:data}));const r=arguments[1].getBoundingClientRect();arguments[1].dispatchEvent(new DragEvent('drop',{bubbles:true,dataTransfer:data,clientY:r.top+100,clientX:r.left+30}));arguments[0].dispatchEvent(new DragEvent('dragend',{bubbles:true,dataTransfer:data}));""",source,target)
        WebDriverWait(driver,5).until(lambda d:len(d.find_elements(By.CSS_SELECTOR,'.timeline-section'))==index+1)
        wait_text(driver,'#save-state','Saved')
    driver.refresh();wait_text(driver,'#timeline','Chill Night')
    with app.app_context():
        rows=ChannelSchedule.query.first().calendar
        assert len(rows)==3 and {r['source']['kind'] for r in rows}=={'block'}
        assert all(r['start']==0 and r['end']==86400 and r['source']['version']==1 for r in rows)
    # Direct Add to Calendar opens placement details, allowing date/repeat review.
    driver.get(base+'/admin/stations/test-station/schedule-studio/blocks?date=2026-09-24')
    click(driver,'.saved-block-card');wait_text(driver,'#block-content-status','Saved · Bright Day');click(driver,'#block-to-calendar')
    WebDriverWait(driver,8).until(lambda d:d.find_element(By.ID,'section-inspector').is_displayed())
    assert driver.find_element(By.ID,'section-start').get_attribute('value')=='00:00:00'
    assert Select(driver.find_element(By.ID,'section-end-day')).first_selected_option.get_attribute('value')=='1'
    click(driver,'#section-form button[type=submit]')
    WebDriverWait(driver,8).until(lambda d:not d.find_element(By.ID,'section-inspector').is_displayed())
    wait_text(driver,'#save-state','Saved')
    with app.app_context():assert len(ChannelSchedule.query.first().calendar)==4


def test_block_keyboard_touch_and_assignment_retry(booth):
    from selenium.webdriver.common.actions.action_builder import ActionBuilder
    from selenium.webdriver.common.actions.pointer_input import PointerInput
    app,driver,base,tmp_path=booth;playlist_id=seed(app)
    with app.app_context():
        station=Station.query.filter_by(slug='test-station').one()
        vs.save_composition(station,dict(kind='BLOCK',name='Touch format',sections=[dict(id='music',start=0,end=86400,source=dict(kind='playlist',id=playlist_id))]));db.session.commit()
    driver.get(base+'/admin/stations/test-station/schedule-studio/blocks')
    click(driver,'.saved-block-card');wait_text(driver,'#block-content-status','Saved · Touch format');click(driver,'.timeline-section')
    slider=driver.find_element(By.ID,'block-start-slider')
    driver.execute_script("arguments[0].scrollIntoView({block:'center',behavior:'instant'})",slider)
    slider.send_keys(Keys.ARROW_RIGHT)
    assert driver.find_element(By.ID,'block-section-start').get_attribute('value')=='00:01:00'
    click(driver,'#undo-edit')
    driver.set_window_size(390,1000)
    slider=driver.find_element(By.ID,'block-end-slider')
    driver.execute_script("arguments[0].scrollIntoView({block:'center',behavior:'instant'})",slider)
    x,y=driver.execute_script('const r=arguments[0].getBoundingClientRect();return [Math.round(r.left+r.width/2),Math.round(r.top+r.height/2)]',slider)
    touch=ActionBuilder(driver,mouse=PointerInput('touch','finger'))
    touch.pointer_action.move_to_location(x,y);touch.pointer_action.pointer_down();touch.pointer_action.pause(.1);touch.pointer_action.pointer_up();touch.perform()
    assert 35000<int(slider.get_attribute('value'))<50000
    assert not driver.find_element(By.ID,'block-section-midnight').is_selected()
    click(driver,'#undo-edit')
    assert driver.find_element(By.ID,'block-section-midnight').is_selected()
    click(driver,'#save-schedule');wait_text(driver,'#save-state','Saved')
    click(driver,'#assign-block')
    driver.execute_script("""
        const original=FreoPage.fetch.bind(FreoPage);window.assignmentAttempts=0;
        FreoPage.fetch=async(...args)=>{
            const response=await original(...args);
            if(args[0].endsWith('/assignments')&&args[1]?.method==='POST'&&++assignmentAttempts===1)throw Error('Response lost after saving');
            return response;
        };
    """)
    click(driver,'#assign-form button[type=submit]');wait_text(driver,'#assign-error','Response lost after saving')
    click(driver,'#assign-form button[type=submit]');wait_text(driver,'#block-assignment-status','Assigned to today')
    with app.app_context():assert len(ChannelSchedule.query.first().assignments)==1
