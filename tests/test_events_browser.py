"""Event creation through the real browser, with station-local previews."""
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select, WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from app.extensions import db
from app.models import Station, Track, TimedEvent
from app.services.audio_classification import classify
from tests.test_live_browser import booth
from tests.test_web import app as app_fixture


def test_playlist_event_editor_and_all_recurrence_controls(booth):
    app,driver,base,tmp_path=booth
    with app.app_context():
        station=Station.query.filter_by(slug='test-station').one();station.timezone='Pacific/Auckland'
        classify(Track.query.first(),'STATION','station_id');db.session.commit()
    driver.get(base+'/admin/stations/test-station/events/create')
    wait=WebDriverWait(driver,15)
    wait.until(lambda d:'STATION' in d.find_element(By.ID,'event-audio-results').text)
    assert Select(driver.find_element(By.NAME,'interrupt_dj')).first_selected_option.text=='No'
    assert 'Pacific/Auckland' in driver.find_element(By.CSS_SELECTOR,'.event-editor').text
    for value in ('QUARTER_HOUR','HOURLY','DAILY','WEEKLY','MONTHLY','ONE_TIME'):
        Select(driver.find_element(By.ID,'event-recurrence')).select_by_value(value)
        assert driver.find_element(By.NAME,'local_date').is_displayed()==(value=='ONE_TIME')
        assert driver.find_element(By.NAME,'month_day').is_displayed()==(value=='MONTHLY')
    Select(driver.find_element(By.ID,'event-recurrence')).select_by_value('QUARTER_HOUR')
    driver.find_element(By.NAME,'name').send_keys('Quarter-hour station ID')
    driver.find_element(By.ID,'event-preview').click()
    wait.until(lambda d:len(d.find_elements(By.CSS_SELECTOR,'#event-next-runs li'))==10)
    assert 'Pacific/Auckland' in driver.find_element(By.ID,'event-summary').text
    buttons=driver.find_elements(By.CSS_SELECTOR,'#event-audio-results article > button:first-child')
    assert buttons[0].text=='STATION';buttons[0].click()
    assert Select(driver.find_element(By.NAME,'playlist_playback')).first_selected_option.get_attribute('value')=='ONE'
    driver.find_element(By.CSS_SELECTOR,'.event-editor button[type="submit"]').click()
    wait.until(lambda d:'/events/create' not in d.current_url)
    with app.app_context():
        row=TimedEvent.query.filter_by(name='Quarter-hour station ID').one()
        assert row.recurrence_type=='QUARTER_HOUR' and row.content_type=='PLAYLIST' and not row.interrupt_dj
    driver.set_window_size(390,844)
    assert driver.execute_script('return document.documentElement.scrollWidth <= innerWidth+2')


def test_all_recurrences_save_reload_and_search_within(booth):
    app,driver,base,_=booth
    with app.app_context():
        station=Station.query.filter_by(slug='test-station').one()
        classify(Track.query.first(),'STATION','station_id');db.session.commit()
    wait=WebDriverWait(driver,15)
    for kind in ('ONE_TIME','QUARTER_HOUR','HOURLY','DAILY','WEEKLY','MONTHLY'):
        driver.get(base+'/admin/stations/test-station/events/create')
        wait.until(lambda d:'STATION' in d.find_element(By.ID,'event-audio-results').text)
        picker=Select(driver.find_element(By.ID,'event-recurrence'))
        if kind in ('DAILY','MONTHLY'):
            picker.select_by_value('WEEKLY')
            for box in driver.find_elements(By.NAME,'weekdays'):
                if box.is_selected():box.click()
        picker.select_by_value(kind)
        driver.find_element(By.NAME,'name').send_keys('Saved '+kind)
        if kind=='ONE_TIME':
            driver.execute_script("document.querySelector('[name=local_date]').value='2028-02-29'")
        driver.find_element(By.CSS_SELECTOR,'#event-audio-results article > button:first-child').click()
        driver.find_element(By.ID,'event-preview').click()
        wait.until(lambda d:len(d.find_elements(By.CSS_SELECTOR,'#event-next-runs li'))>0)
        driver.find_element(By.CSS_SELECTOR,'.event-editor button[type="submit"]').click()
        wait.until(lambda d:'/events/create' not in d.current_url)
        assert Select(driver.find_element(By.ID,'event-recurrence')).first_selected_option.get_attribute('value')==kind
        assert 'STATION' in driver.find_element(By.ID,'event-audio-selected').text
        with app.app_context():
            row=TimedEvent.query.filter_by(name='Saved '+kind).one()
            assert row.recurrence_type==kind and not row.interrupt_dj
    previous=driver.find_element(By.CSS_SELECTOR,'#event-audio-results article')
    query=driver.find_element(By.ID,'event-audio-search');query.send_keys('STATION')
    wait.until(EC.staleness_of(previous))
    wait.until(lambda d:'STATION' in d.find_element(By.ID,'event-audio-results').text)
    wait.until(lambda d:d.find_elements(By.XPATH,"//div[@id='event-audio-results']//button[text()='Search within']"))[0].click()
    wait.until(lambda d:'Verified Test Track' in d.find_element(By.ID,'event-audio-results').text)
    assert driver.find_element(By.ID,'event-audio-search').get_attribute('value')==''
    assert 'STATION' in driver.find_element(By.ID,'event-audio-scope').text
