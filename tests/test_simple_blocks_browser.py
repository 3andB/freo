from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from app.extensions import db
from app.models import Station, ChannelSchedule, ScheduleTransition
from app.services import visual_schedule as vs
from tests.test_live_browser import booth, app_fixture, wait_text
from tests.test_block_scheduler_browser import click, seed


def test_simple_block_click_drag_save_reload_and_activate(booth):
    app,driver,base,_=booth;playlist_id=seed(app)
    with app.app_context():
        station=Station.query.filter_by(slug='test-station').one()
        for name in ['Chill Night','Quiet Day']:
            vs.save_composition(station,dict(kind='BLOCK',name=name,sections=[dict(id='music',start=0,end=86400,source=dict(kind='playlist',id=playlist_id))]))
        db.session.commit()
    driver.get(base+'/admin/stations/test-station/schedule-studio/simple')
    click(driver,'#source-tabs button:first-child');wait_text(driver,'#source-results','Chill Night')
    click(driver,'button[aria-label="Add Chill Night"]')
    wait_text(driver,'#simple-selection','Chill Night')
    wait_text(driver,'#simple-playback-help','No day assignment is needed')
    click(driver,'#save-schedule');wait_text(driver,'#save-state','Saved')
    driver.refresh();wait_text(driver,'#simple-selection','Chill Night')
    click(driver,'#source-tabs button:first-child');wait_text(driver,'#source-results','Quiet Day')
    source=driver.find_element(By.XPATH,"//div[contains(@class,'source-card')][.//strong[text()='Quiet Day']]")
    target=driver.find_element(By.ID,'simple-selection')
    driver.execute_script("const data=new DataTransfer();arguments[0].dispatchEvent(new DragEvent('dragstart',{bubbles:true,dataTransfer:data}));arguments[1].dispatchEvent(new DragEvent('drop',{bubbles:true,dataTransfer:data}));arguments[0].dispatchEvent(new DragEvent('dragend',{bubbles:true,dataTransfer:data}));",source,target)
    wait_text(driver,'#simple-selection','Quiet Day')
    click(driver,'#save-schedule');wait_text(driver,'#save-state','Saved')
    driver.refresh();wait_text(driver,'#simple-selection','Quiet Day')
    click(driver,'#activate-mode');wait_text(driver,'#mode-confirm-play','Will play now: Playlist 1')
    assert driver.find_element(By.ID,'confirm-mode').is_enabled()
    click(driver,'#confirm-mode');wait_text(driver,'#studio-message','Waiting for the playback engine')
    with app.app_context():
        policy=ChannelSchedule.query.first();command=ScheduleTransition.query.one()
        assert policy.simple['kind']=='block' and policy.simple['name']=='Quiet Day'
        assert command.mode=='SIMPLE' and command.simple==policy.simple
        assert command.state=='PENDING' and policy.live_simple['kind']=='playlist'
        assert policy.assignments==[] and policy.default_playlist_id is None
