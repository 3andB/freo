"""Regressions from the scheduling audit, exercised through the real editor."""
import json
from pathlib import Path
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from app.extensions import db
from app.models import Station, Track, ChannelSchedule
from app.services import visual_schedule as vs
from tests.test_live_browser import booth, app_fixture, wait_text


def test_overnight_series_stale_save_and_geometry(booth):
    app, driver, base, tmp_path = booth
    out = {}
    def seed(rows):
        with app.app_context():
            s=Station.query.filter_by(slug='test-station').one()
            p=vs.policy(s,True)
            ref=vs.source(s,dict(kind='song',id=Track.query.first().id))
            p.calendar=vs.clean_document(s,[dict(source=ref,**r) for r in rows]); p.calendar_saved=True
            p.revision+=1; db.session.commit()
        driver.execute_script('FreoPage.dispose();localStorage.clear()')
    def visit(day='2026-09-21',view='day'):
        driver.get(base+f'/admin/stations/test-station/schedule-studio/calendar?date={day}&view={view}')
        WebDriverWait(driver,10).until(lambda d:d.find_elements(By.CSS_SELECTOR,'.time-column'))
    def edit():
        driver.execute_script("document.querySelector('.timeline-section').click()")
        WebDriverWait(driver,5).until(lambda d:d.find_element(By.ID,'section-inspector').is_displayed())
    def draft():
        return driver.execute_script("return JSON.parse(localStorage.getItem('freo-schedule:test-station:calendar:draft'))")
    def row(start=82800,end=93600,freq='weekly',exceptions=None):
        return dict(id='audit',start=start,end=end,rule=dict(frequency=freq,anchor='2026-09-21',weekdays=[0],interval=1,exceptions=exceptions or []))
    seed([row()]);visit('2026-09-22');edit()
    out['overnight_inspector']={k:driver.find_element(By.ID,k).get_attribute('value') for k in ['section-start','section-end','section-date']}
    driver.find_element(By.ID,'delete-section').click()
    out['overnight_remove_exceptions']=draft()['entries'][0]['rule']['exceptions']
    assert out['overnight_remove_exceptions']==['2026-09-21']
    assert out['overnight_inspector']=={'section-start':'23:00:00','section-end':'02:00:00','section-date':'2026-09-21'}
    seed([row(start=32400,end=36000,exceptions=['2026-09-28'])]);visit('2026-10-05');edit()
    Select(driver.find_element(By.ID,'edit-scope')).select_by_value('series')
    driver.find_element(By.CSS_SELECTOR,'#section-form button[type=submit]').click()
    out['series_noop_rule']=draft()['entries'][0]['rule']
    assert out['series_noop_rule']['exceptions']==['2026-09-28'] and out['series_noop_rule']['anchor']=='2026-09-21'
    seed([row(start=32400,end=36000,freq='once')]);visit()
    with app.app_context():
        p=ChannelSchedule.query.first(); rows=json.loads(json.dumps(p.calendar));rows[0]['end']=39600
        p.calendar=rows;p.revision+=1; new_revision=p.revision;db.session.commit()
    # Wait through a real background polling cycle, then change the stale displayed row.
    import time
    time.sleep(4.5)
    edit();driver.execute_script("document.getElementById('section-start').value='08:00:00'")
    driver.find_element(By.CSS_SELECTOR,'#section-form button[type=submit]').click()
    out['stale_revision']={'draft_revision':draft()['revision'],'remote_revision':new_revision,'local_end':draft()['entries'][0]['end']}
    driver.find_element(By.ID,'save-schedule').click();wait_text(driver,'#studio-message','Another editor changed this schedule')
    with app.app_context():
        out['stale_saved_end']=ChannelSchedule.query.first().calendar[0]['end']
    assert out['stale_saved_end']==39600
    # Inspect responsive overflow for the Show duration slider and overview.
    driver.execute_script('FreoPage.dispose();localStorage.clear()')
    driver.get(base+'/admin/stations/test-station/schedule-studio/shows')
    WebDriverWait(driver,10).until(lambda d:d.find_elements(By.ID,'duration-slider'))
    Select(driver.find_element(By.ID,'show-duration')).select_by_value('86400')
    out['viewports']=[]
    for width in [320,390,750,768,1024,1280,1600]:
        driver.set_window_size(width,1000)
        WebDriverWait(driver,5).until(lambda d:d.execute_script('return innerWidth')==width)
        out['viewports'].append(driver.execute_script("""const d=document.documentElement; const slider=document.getElementById('duration-slider'), canvas=document.querySelector('.studio-canvas');return {width:innerWidth,pageWidth:d.scrollWidth,sliderRight:slider.getBoundingClientRect().right,canvasRight:canvas.getBoundingClientRect().right};"""))
    assert all(v['pageWidth']<=v['width'] and v['sliderRight']<=v['canvasRight'] for v in out['viewports']),out['viewports']
    # A minute-long section at the Show endpoint exceeds the time-column visual bounds.
    driver.set_window_size(1600,1200)
    Select(driver.find_element(By.ID,'show-duration')).select_by_value('900')
    driver.find_element(By.XPATH,"//nav[@id='source-tabs']/button[text()='Songs']").click();wait_text(driver,'#source-results','Verified Test Track')
    driver.find_element(By.CSS_SELECTOR,'.source-actions button').click()
    driver.execute_script("document.getElementById('section-start').value='00:14:00';document.getElementById('section-end').value='00:15:00'")
    driver.find_element(By.CSS_SELECTOR,'#section-form button[type=submit]').click()
    out['short_section']=driver.execute_script("const s=document.querySelector('.timeline-section').getBoundingClientRect(),c=document.querySelector('.time-column').getBoundingClientRect();return {sectionBottom:s.bottom,columnBottom:c.bottom,overflow:s.bottom-c.bottom,sectionHeight:s.height,columnHeight:c.height}")
    assert out['short_section']['overflow']<=1
    assert driver.find_element(By.CSS_SELECTOR,'#short-sections button').is_displayed()
    (tmp_path/'editor-observations.json').write_text(json.dumps(out,indent=2))
    print(json.dumps(out,indent=2))


def test_cancel_overlap_and_edits_while_saving(booth):
    app,driver,base,tmp_path=booth
    with app.app_context():
        s=Station.query.filter_by(slug='test-station').one();p=vs.policy(s,True)
        ref=vs.source(s,dict(kind='song',id=Track.query.first().id))
        p.calendar=vs.clean_document(s,[dict(id='series',start=32400,end=36000,source=ref,rule=dict(frequency='weekly',anchor='2026-09-21',weekdays=[0])),dict(id='once',start=36000,end=39600,source=ref,rule=dict(frequency='once',anchor='2026-09-21'))]);p.calendar_saved=True;db.session.commit()
    driver.get(base+'/admin/stations/test-station/schedule-studio/calendar?date=2026-09-21&view=day')
    WebDriverWait(driver,10).until(lambda d:d.find_elements(By.CSS_SELECTOR,'[data-id="series"]'))
    driver.execute_script("document.querySelector('[data-id=series]').click()")
    driver.execute_script("document.getElementById('section-start').value='10:00:00';document.getElementById('section-end').value='11:00:00'")
    driver.find_element(By.CSS_SELECTOR,'#section-form button[type=submit]').click()
    WebDriverWait(driver,5).until(lambda d:d.switch_to.alert).dismiss()
    assert driver.find_element(By.ID,'save-state').text=='Saved'
    assert driver.find_element(By.ID,'undo-edit').get_attribute('disabled')
    driver.find_element(By.CSS_SELECTOR,'#section-inspector .dialog-close').click()
    # Delay the actual save response while permitting a newer edit in the UI.
    driver.execute_script("""const original=FreoPage.fetch.bind(FreoPage);window.releaseSave=null;FreoPage.fetch=async(...args)=>{const response=await original(...args);if(args[0].endsWith('/calendar')&&args[1]?.method==='POST')await new Promise(resolve=>window.releaseSave=resolve);return response;};document.querySelector('[data-id=series]').click();""")
    Select(driver.find_element(By.ID,'edit-scope')).select_by_value('series')
    driver.execute_script("document.getElementById('section-start').value='08:00:00'")
    driver.find_element(By.CSS_SELECTOR,'#section-form button[type=submit]').click()
    driver.find_element(By.ID,'save-schedule').click()
    WebDriverWait(driver,10).until(lambda d:d.execute_script('return !!window.releaseSave'))
    driver.execute_script("document.querySelector('[data-id=series]').click()")
    Select(driver.find_element(By.ID,'edit-scope')).select_by_value('series')
    driver.execute_script("document.getElementById('section-start').value='07:00:00'")
    driver.find_element(By.CSS_SELECTOR,'#section-form button[type=submit]').click()
    driver.execute_script('window.releaseSave()')
    wait_text(driver,'#studio-message','Newer edits still need saving')
    assert driver.find_element(By.ID,'save-state').text=='Unsaved changes'
    draft=driver.execute_script("return JSON.parse(localStorage.getItem('freo-schedule:test-station:calendar:draft'))")
    assert next(r for r in draft['entries'] if r['id']=='series')['start']==25200
    with app.app_context():
        rows=ChannelSchedule.query.first().calendar
        assert next(r for r in rows if r['id']=='series')['start']==28800
        assert next(r for r in rows if r['id']=='series')['rule']['exceptions']==[]


def test_horizontal_drag_and_exact_duration(booth):
    from selenium.webdriver.common.action_chains import ActionChains
    app,driver,base,tmp_path=booth
    with app.app_context():
        s=Station.query.filter_by(slug='test-station').one();p=vs.policy(s,True)
        ref=vs.source(s,dict(kind='song',id=Track.query.first().id))
        p.calendar=vs.clean_document(s,[dict(id='move',start=3600,end=7200,source=ref,rule=dict(frequency='once',anchor='2026-09-21'))]);p.calendar_saved=True;db.session.commit()
    driver.get(base+'/admin/stations/test-station/schedule-studio/calendar?date=2026-09-21&view=week')
    WebDriverWait(driver,10).until(lambda d:d.find_elements(By.CSS_SELECTOR,'[data-id="move"]'))
    el=driver.find_element(By.CSS_SELECTOR,'[data-id="move"]')
    driver.execute_script("arguments[0].scrollIntoView({block:'center'})",el)
    width=driver.execute_script("return document.querySelector('.time-column').getBoundingClientRect().width")
    ActionChains(driver).move_to_element(el).click_and_hold().move_by_offset(round(width),0).pause(.15).release().perform()
    WebDriverWait(driver,5).until(lambda d:d.execute_script("const raw=localStorage.getItem('freo-schedule:test-station:calendar:draft');return raw&&JSON.parse(raw).entries[0].rule.anchor==='2026-09-22'"))
    driver.execute_script("document.getElementById('save-schedule').scrollIntoView({block:'center'})")
    driver.find_element(By.ID,'save-schedule').click();wait_text(driver,'#save-state','Saved')
    driver.get(base+'/admin/stations/test-station/schedule-studio/shows')
    WebDriverWait(driver,10).until(lambda d:d.find_elements(By.ID,'duration-minutes'))
    driver.execute_script("const input=document.getElementById('duration-minutes');input.value=16;input.dispatchEvent(new Event('change'))")
    assert driver.find_element(By.ID,'duration-slider').get_attribute('value')=='960'
    assert Select(driver.find_element(By.ID,'show-duration')).first_selected_option.text=='16 minutes'
    driver.find_element(By.ID,'undo-edit').click()
    assert driver.find_element(By.ID,'duration-minutes').get_attribute('value')=='60'
    driver.execute_script("const input=document.getElementById('duration-minutes');input.value=16.5;input.dispatchEvent(new Event('change'))")
    assert driver.find_element(By.ID,'duration-slider').get_attribute('value')=='990'
    assert Select(driver.find_element(By.ID,'show-duration')).first_selected_option.text=='16.5 minutes'


def test_events_in_month_agenda_and_clicked_day(booth):
    from app.services.timed_events import save_event
    app,driver,base,tmp_path=booth
    with app.app_context():
        save_event('test-station',name='Boundary announcement',timing_mode='SOFT',recurrence_type='ONE_TIME',content_type='TRACK',content_identifier=Track.query.first().uuid,local_date='2026-08-31',local_time='10:00')
    driver.get(base+'/admin/stations/test-station/schedule-studio/calendar?date=2026-09-15&view=month')
    wait_text(driver,'.month-grid','Boundary announcement')
    driver.execute_script("const link=[...document.querySelectorAll('.month-day .calendar-event')].find(el=>el.textContent.includes('Boundary announcement'));link.parentElement.querySelector('b').click()")
    wait_text(driver,'.time-column','Boundary announcement')
    assert driver.find_element(By.ID,'calendar-date').get_attribute('value')=='2026-08-31'
    Select(driver.find_element(By.ID,'calendar-view')).select_by_visible_text('Agenda')
    wait_text(driver,'.agenda-row .calendar-event','Boundary announcement')


def test_drag_auto_scroll_keeps_elapsed_time_in_delta(booth):
    from selenium.webdriver.common.action_chains import ActionChains
    app,driver,base,tmp_path=booth
    with app.app_context():
        s=Station.query.filter_by(slug='test-station').one();p=vs.policy(s,True)
        ref=vs.source(s,dict(kind='song',id=Track.query.first().id))
        p.calendar=vs.clean_document(s,[dict(id='scroll',start=32400,end=36000,source=ref,rule=dict(frequency='once',anchor='2026-09-21'))]);p.calendar_saved=True;db.session.commit()
    driver.get(base+'/admin/stations/test-station/schedule-studio/calendar?date=2026-09-21&view=day')
    WebDriverWait(driver,10).until(lambda d:d.find_elements(By.CSS_SELECTOR,'[data-id="scroll"]'))
    driver.execute_script("const t=document.getElementById('timeline');t.style.maxHeight='400px';t.scrollIntoView({block:'center'});t.scrollTop=600;document.getElementById('timeline-snap').value='60'")
    el=driver.find_element(By.CSS_SELECTOR,'[data-id="scroll"]')
    delta=driver.execute_script("return document.getElementById('timeline').getBoundingClientRect().bottom-15-(arguments[0].getBoundingClientRect().top+arguments[0].getBoundingClientRect().height/2)",el)
    driver.execute_script("window.dragProbe=[];for(const kind of ['pointerdown','pointermove','pointercancel'])document.addEventListener(kind,e=>dragProbe.push({kind,y:e.clientY,target:e.target.className,bottom:document.getElementById('timeline').getBoundingClientRect().bottom}))")
    ActionChains(driver).move_to_element(el).click_and_hold().move_by_offset(0,round(delta)).pause(.5).perform()
    scrolled=driver.execute_script("return document.getElementById('timeline').scrollTop")
    assert scrolled>650,driver.execute_script('return {probe:dragProbe,message:document.getElementById("studio-message").textContent}')
    ActionChains(driver).release().perform()
    draft=driver.execute_script("return JSON.parse(localStorage.getItem('freo-schedule:test-station:calendar:draft'))")
    assert draft['entries'][0]['start']>=32400+(delta+scrolled-600)*3600/84-120
