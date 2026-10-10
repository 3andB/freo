"""Actual layout, controls and ten-channel discovery for rc.4."""
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import Select, WebDriverWait
from app.extensions import db
from app.models import Station, StreamMount
from tests.test_live_browser import booth, app_fixture
from tests.test_homepage_browser import viewport


def test_ten_channels_listen_menu_monitor_prompt_and_artwork(booth):
    app,driver,base,tmp=booth
    with app.app_context():
        for index in range(3,11):
            station=Station(name=f'Channel {index} — Independent Music',slug=f'channel-{index}')
            station.stream=StreamMount();db.session.add(station)
        db.session.commit()
    wait=WebDriverWait(driver,12)
    driver.get(base+'/admin')
    wait.until(lambda d:'Select a station' in d.find_element(By.CSS_SELECTOR,'[data-now-label]').text)
    for width in (390,768,1440):
        viewport(driver,width)
        label=driver.find_element(By.CSS_SELECTOR,'[data-now-label]').rect
        monitors=driver.find_element(By.CSS_SELECTOR,'[data-station-monitors]').rect
        assert label['y']+label['height']<=monitors['y']
        assert abs(label['x']-monitors['x'])<2
        assert driver.execute_script('return document.documentElement.scrollWidth <= innerWidth+1')
    driver.get(base+'/')
    wait.until(lambda d:d.find_elements(By.CSS_SELECTOR,'.station-header.enhanced'))
    for width in (360,390,768,1440):
        viewport(driver,width)
        links=driver.find_elements(By.CSS_SELECTOR,'.channel-top-links a')
        assert len(links)==10 and all(link.is_displayed() for link in links)
        assert len(driver.find_elements(By.CSS_SELECTOR,'.channel-card'))==10
        assert driver.execute_script('return document.documentElement.scrollWidth <= innerWidth+1')
        menu=driver.find_element(By.CSS_SELECTOR,'.station-header .listen-menu summary');menu.click()
        options=driver.find_elements(By.CSS_SELECTOR,'.station-header .listen-options a')
        assert len(options)==10 and options[0].is_displayed()
        menu.click()
        if width in (390,1440):
            driver.save_screenshot(f'/tmp/freo-rc4-channels-{width}.png')
    driver.find_element(By.CSS_SELECTOR,'.hero-listen summary').click()
    driver.find_element(By.CSS_SELECTOR,'.hero-listen a[href$="/player/second-station"]').click()
    wait.until(lambda d:'/player/second-station' in d.current_url)
    vinyl=driver.find_element(By.CSS_SELECTOR,'.radio-vinyl').rect
    label=driver.find_element(By.CSS_SELECTOR,'.vinyl-label').rect
    assert label['width'] < vinyl['width'] * .5
    assert label['height'] < vinyl['height'] * .5
    assert driver.find_element(By.LINK_TEXT,'Learn more about Freo Free Radio').get_attribute('href')=='https://freo.live/'
    driver.get(base+'/admin/stations/test-station/settings')
    Select(driver.find_element(By.NAME,'timezone')).select_by_value('Australia/Perth')
    assert 'Perth' in Select(driver.find_element(By.NAME,'timezone')).first_selected_option.text
    driver.get(base+'/admin/stations/test-station/events/create?recurrence=hourly')
    assert Select(driver.find_element(By.ID,'event-recurrence')).first_selected_option.get_attribute('value')=='HOURLY'
    Select(driver.find_element(By.NAME,'hourly_minute')).select_by_value('10')
    driver.find_element(By.ID,'event-preview').click()
    wait.until(lambda d:len(d.find_elements(By.CSS_SELECTOR,'#event-next-runs li'))==10)
    assert all(':10:00' in el.text for el in driver.find_elements(By.CSS_SELECTOR,'#event-next-runs li'))
    driver.get(base+'/admin/website')
    wait.until(lambda d: len(d.find_elements(By.CSS_SELECTOR,'input[type=file][name^=channel_image_]')) == 10)
