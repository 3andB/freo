"""Calendar persistence through failed requests, navigation, and conflicting edits."""
import copy
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from app.extensions import db
from app.models import ChannelSchedule, Station, Track
from app.services import visual_schedule as vs
from tests.test_live_browser import booth, app_fixture, wait_text
from tests.test_schedule_editor_browser import saved_calendar


def visit_calendar(app, driver, base):
    with app.app_context():
        station=Station.query.filter_by(slug='test-station').one();row=vs.policy(station,True)
        ref=vs.source(station,dict(kind='song',id=Track.query.first().id))
        row.calendar=vs.clean_document(station,[dict(id='entry',start=32400,end=36000,source=ref,rule=dict(frequency='once',anchor='2026-09-21'))])
        row.calendar_saved=True;db.session.commit()
    driver.get(base+'/admin/stations/test-station/schedule-studio/calendar?date=2026-09-21&view=day')
    WebDriverWait(driver,10).until(lambda d:d.find_elements(By.CSS_SELECTOR,'[data-id="entry"]'))
    assert not driver.find_elements(By.ID,'save-schedule')
    assert not driver.find_element(By.ID,'save-conflict').is_displayed()


def edit_start(driver, time, apply=True):
    driver.execute_script("document.querySelector('[data-id=entry]').dispatchEvent(new MouseEvent('dblclick',{bubbles:true}))")
    WebDriverWait(driver,5).until(lambda d:d.find_element(By.ID,'section-inspector').is_displayed())
    driver.execute_script("document.getElementById('section-start').value=arguments[0]",time)
    if apply:apply_edit(driver)


def apply_edit(driver):
    driver.find_element(By.CSS_SELECTOR,'#section-form button[type=submit]').click()
    WebDriverWait(driver,5).until(lambda d:not d.find_element(By.ID,'section-inspector').is_displayed())


def test_calendar_retries_outage_and_lost_response_then_flushes_navigation(booth):
    app,driver,base,_=booth
    visit_calendar(app,driver,base)
    driver.execute_script("""
      const original=FreoPage.fetch.bind(FreoPage);window.saveAttempts=0;
      FreoPage.fetch=async(...args)=>{
        if(args[0].endsWith('/calendar')&&args[1]?.method==='POST'){
          window.saveAttempts++;
          if(saveAttempts===1)return new Response('Temporary outage',{status:503});
          const response=await original(...args);
          if(saveAttempts===2)throw new TypeError('Connection lost after saving');
          return response;
        }
        return original(...args);
      };
    """)
    edit_start(driver,'08:00:00')
    saved_calendar(app,driver,lambda rows:rows[0]['start']==28800)
    assert driver.execute_script('return saveAttempts')==3
    assert driver.execute_script("return localStorage.getItem('freo-schedule:test-station:calendar:draft')") is None
    driver.execute_script("""
      const original=FreoPage.fetch.bind(FreoPage);window.releaseSave=null;
      FreoPage.fetch=async(...args)=>{
        const response=await original(...args);
        if(args[0].endsWith('/calendar')&&args[1]?.method==='POST'){
          FreoPage.fetch=original;await new Promise(resolve=>window.releaseSave=resolve);
        }
        return response;
      };
    """)
    edit_start(driver,'07:00:00')
    WebDriverWait(driver,8).until(lambda d:d.execute_script('return !!window.releaseSave'))
    driver.find_element(By.LINK_TEXT,'Music').click()
    assert '/schedule-studio/calendar' in driver.current_url
    driver.execute_script('window.releaseSave()')
    WebDriverWait(driver,10).until(lambda d:'/schedule-studio/calendar' not in d.current_url)
    with app.app_context():assert ChannelSchedule.query.one().calendar[0]['start']==25200


def test_calendar_same_item_conflict_preserves_edits_and_resolves_explicitly(booth):
    app,driver,base,_=booth
    visit_calendar(app,driver,base)
    for keep in (False,True):
        edit_start(driver,'07:00:00',apply=False)
        with app.app_context():
            row=ChannelSchedule.query.one();entries=copy.deepcopy(row.calendar)
            entries[0]['end']+=3600;row.calendar=entries;row.revision+=1;db.session.commit()
        apply_edit(driver)
        wait_text(driver,'#save-state','Not saved')
        assert driver.find_element(By.ID,'save-conflict').is_displayed()
        assert driver.execute_script("return !!localStorage.getItem('freo-schedule:test-station:calendar:draft')")
        with app.app_context():assert ChannelSchedule.query.one().calendar[0]['start']==32400
        driver.find_element(By.ID,'keep-schedule-edits' if keep else 'use-latest-schedule').click()
        saved=saved_calendar(app,driver,lambda rows:rows[0]['start']==(25200 if keep else 32400))
        assert not driver.find_element(By.ID,'save-conflict').is_displayed()
        assert saved['entries'][0]['end']==39600
