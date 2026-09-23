"""RC6 layouts and edits are checked in a disposable browser installation."""
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from tests.test_live_browser import booth, app_fixture, wait_text


def test_settings_single_save_keeps_edits_and_layout(booth):
    app,driver,base,tmp_path=booth
    driver.get(base+'/admin/stations/test-station/settings')
    wait=WebDriverWait(driver,12)
    wait.until(lambda d:d.find_elements(By.ID,'station-settings-form'))
    driver.execute_script("const f=document.getElementById('station-settings-form');f.elements.name.value='RC6 Radio';f.elements.city.value='Fremantle';f.elements.bitrate.value='96';f.elements.name.dispatchEvent(new Event('input',{bubbles:true}));")
    wait_text(driver,'#station-save-status','Unsaved changes')
    driver.execute_script("document.querySelector('#station-settings-form .settings-save-bar button').click()")
    wait_text(driver,'#station-save-status','All changes saved')
    assert driver.find_element(By.NAME,'city').get_attribute('value')=='Fremantle'
    # Validation does not discard other edits or navigate away.
    driver.execute_script("const f=document.getElementById('station-settings-form');f.elements.city.value='Keep this draft';f.elements.country.value='X';f.elements.city.dispatchEvent(new Event('input',{bubbles:true}));f.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));")
    wait_text(driver,'#station-save-status','two-letter')
    assert driver.find_element(By.NAME,'city').get_attribute('value')=='Keep this draft'
    for width in (390,1280):
        driver.set_window_size(width,1000)
        assert driver.execute_script('return document.documentElement.scrollWidth<=innerWidth+1')
        driver.save_screenshot(f'/tmp/freo-rc6-settings-{width}.png')
    # Discard test draft explicitly before examining the other pages.
    driver.execute_script("window.FreoPage.beforeLeave=()=>true")
    for path in ('/admin/installation','/admin/listener-feedback','/admin/stations/test-station/tags','/admin/stations/test-station/categories'):
        driver.get(base+path)
        try: driver.switch_to.alert.accept()
        except Exception: pass
        wait.until(lambda d:d.find_elements(By.CSS_SELECTOR,'.admin-main'))
        for width in (390,1280):
            driver.set_window_size(width,1000)
            assert driver.execute_script('return document.documentElement.scrollWidth<=innerWidth+1'),path
        driver.save_screenshot('/tmp/freo-rc6-'+path.rsplit('/',1)[-1]+'.png')
    driver.get(base+'/admin/listener-feedback')
    sizes=driver.execute_script("return [...document.querySelectorAll('.ops-feedback-filter select,.ops-feedback-filter button')].map(e=>e.getBoundingClientRect().bottom)")
    assert max(sizes)-min(sizes)<3


def test_player_vinyl_lava_and_stationary_cover(booth):
    app,driver,base,tmp_path=booth
    from app.extensions import db
    from app.models import Track, MusicArtwork
    from tests.test_station_settings_flags import png
    with app.app_context():
        art=MusicArtwork(id='rc6-art',station_id=1,image=png())
        db.session.add(art);Track.query.first().cover_id=art.id;db.session.commit()
    driver.get(base+'/player/test-station')
    WebDriverWait(driver,12).until(lambda d:d.find_elements(By.CSS_SELECTOR,'.vinyl-lava'))
    assert len(driver.find_elements(By.CSS_SELECTOR,'.vinyl-lava>span'))==3
    assert not driver.find_elements(By.CSS_SELECTOR,'.radio-vinyl img')
    WebDriverWait(driver,12).until(lambda d:d.find_element(By.ID,'playing-artwork').is_displayed())
    assert driver.execute_script("const a=document.getElementById('playing-artwork'),t=document.getElementById('radio-transport');return a.getBoundingClientRect().top>=t.getBoundingClientRect().bottom && a.getBoundingClientRect().width<=160 && getComputedStyle(a).animationName==='none'")
    for width in (390,1280):
        driver.set_window_size(width,1000)
        assert driver.execute_script('return document.documentElement.scrollWidth<=innerWidth+1')
        driver.save_screenshot(f'/tmp/freo-rc6-player-{width}.png')
    driver.execute_cdp_cmd('Emulation.setEmulatedMedia',{'features':[{'name':'prefers-reduced-motion','value':'reduce'}]})
    assert driver.execute_script("return getComputedStyle(document.querySelector('.vinyl-lava>span')).animationName")=='none'
