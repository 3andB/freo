"""Real browser editing and audio-clock preview behavior."""
import json
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from app.extensions import db
from app.models import Track
from tests.test_live_browser import booth, wait_text
from tests.test_web import app as app_fixture, admin_client


def test_waveform_drafts_save_conflict_reset_and_preview(booth):
    app,driver,base,tmp_path=booth
    with app.app_context():
        song=Track.query.first();song.duration_ms=4000;song.cue_in_ms=100;song.cue_out_ms=3900;song.waveform=[.5]*100;db.session.commit();identifier=song.uuid
    driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument',{'source':'''const old=AudioContext.prototype.createGain;AudioContext.prototype.createGain=function(){const node=old.call(this);window.testPreviewGain=node;return node;};'''})
    driver.get(base+'/admin/stations/test-station/media/'+identifier)
    wait=WebDriverWait(driver,12)
    wait.until(lambda d:d.execute_script('return !document.getElementById("media-editor").inert'))
    wait_text(driver,'#audio-edit-status','inactive')
    def click(selector):
        el=driver.find_element(By.CSS_SELECTOR,selector);driver.execute_script('arguments[0].scrollIntoView({block:"center"})',el);el.click()
    def set_values(**values):
        driver.execute_script('''for(const [k,v] of Object.entries(arguments[0])){const input=document.querySelector('#audio-edits [name="'+k+'"]');input.value=v;input.dispatchEvent(new Event('input',{bubbles:true}));}''',values)
    set_values(cue_in_ms=500,cue_out_ms=3000,fade_in_ms=500,fade_out_ms=500,gain_trim_db=-6)
    wait_text(driver,'#audio-edit-summary','2.500 s')
    # Polling must preserve unsaved settings, including the revision they edit.
    driver.execute_async_script('setTimeout(arguments[arguments.length-1],3300)')
    assert driver.find_element(By.CSS_SELECTOR,'[name=cue_in_ms]').get_attribute('value')=='500'
    click('#audio-preview')
    wait.until(lambda d:d.execute_script('return !document.getElementById("music-audio").paused && document.getElementById("music-audio").currentTime > 1.1'))
    assert driver.execute_script('return testPreviewGain.gain.value') == __import__('pytest').approx(10**(-6/20),abs=.04)
    driver.execute_script('const seek=document.getElementById("preview-seek");seek.value=50;seek.dispatchEvent(new Event("input"));document.getElementById("music-audio").pause();')
    wait.until(lambda d:d.execute_script('return Math.abs(document.getElementById("music-audio").currentTime-1.75)<.1'))
    driver.execute_async_script('setTimeout(arguments[arguments.length-1],250)')
    assert driver.execute_script('return document.getElementById("music-audio").currentTime') == __import__('pytest').approx(1.75,abs=.1)
    assert float(driver.find_element(By.ID,'preview-seek').get_attribute('value')) == __import__('pytest').approx(50,abs=4)
    click('#preview-toggle')
    wait.until(lambda d:d.execute_script('return document.getElementById("music-audio").paused'))
    assert driver.execute_script('return document.getElementById("music-audio").currentTime') == __import__('pytest').approx(3,abs=.1)
    assert driver.execute_script('return testPreviewGain.gain.value') == 0
    click('#audio-original')
    wait.until(lambda d:d.execute_script('return document.getElementById("music-audio").currentTime > 3.2'))
    assert driver.execute_script('return testPreviewGain.gain.value') == 1
    click('#audio-edits [type=submit]');wait_text(driver,'#audio-edit-status','saved')
    driver.refresh();wait.until(lambda d:d.execute_script('return !document.getElementById("media-editor").inert'))
    assert driver.find_element(By.CSS_SELECTOR,'[name=cue_out_ms]').get_attribute('value')=='3000'
    # Keyboard marker edits update the same numeric draft.
    marker=driver.find_element(By.CSS_SELECTOR,'[aria-label="Cue in milliseconds"]');marker.send_keys(Keys.ARROW_RIGHT)
    assert driver.find_element(By.CSS_SELECTOR,'[name=cue_in_ms]').get_attribute('value')=='510'
    client=admin_client(app)
    result=client.post('/admin/api/stations/test-station/song/'+identifier+'/audio',data={'csrf':'test-admin-csrf-token','data':json.dumps(dict(revision=1,cue_in_ms=600,cue_out_ms=3000))})
    assert result.status_code==200
    click('#audio-edits [type=submit]');wait_text(driver,'#audio-edit-status','changed')
    click('#audio-reload');wait.until(lambda d:d.find_element(By.CSS_SELECTOR,'[name=cue_in_ms]').get_attribute('value')=='600')
    click('#audio-reset');click('#audio-edits [type=submit]');wait_text(driver,'#audio-edit-status','saved')
    click('#audio-preview')
    wait.until(lambda d:d.execute_script('return document.getElementById("music-audio").currentTime > 1.1 && !document.getElementById("music-audio").paused'))
    assert driver.execute_script('return testPreviewGain.gain.value') == 1  # Zero fades do not ramp across the whole track.
    driver.set_window_size(430,932)
    assert driver.execute_script('return document.documentElement.scrollWidth <= innerWidth')
    with app.app_context():
        song=Track.query.first();assert song.audio_edit_enabled and song.cue_in_ms is None and song.cue_out_ms is None and song.fade_in_ms==song.fade_out_ms==0 and song.gain_trim_db is None


def test_missing_waveform_numeric_edit_and_pointer_handle(booth):
    app,driver,base,tmp_path=booth
    with app.app_context():
        song=Track.query.first();song.duration_ms=4000;song.waveform=[];db.session.commit();identifier=song.uuid
    driver.get(base+'/admin/stations/test-station/media/'+identifier)
    WebDriverWait(driver,12).until(lambda d:d.execute_script('return !document.getElementById("media-editor").inert'))
    assert driver.find_element(By.ID,'waveform-status').is_displayed()
    from selenium.webdriver.common.action_chains import ActionChains
    marker=driver.find_element(By.CSS_SELECTOR,'[aria-label="Cue out milliseconds"]')
    from selenium.webdriver.common.keys import Keys
    marker.send_keys(Keys.ARROW_LEFT)
    assert driver.find_element(By.CSS_SELECTOR,'[name=cue_out_ms]').get_attribute('value')=='3990'
    driver.execute_script('arguments[0].scrollIntoView({block:"center"})',marker)
    ActionChains(driver).drag_and_drop_by_offset(marker,-100,0).perform()
    assert 0<int(driver.find_element(By.CSS_SELECTOR,'[name=cue_out_ms]').get_attribute('value'))<4000
    button=driver.find_element(By.CSS_SELECTOR,'#audio-edits [type=submit]');driver.execute_script('arguments[0].scrollIntoView({block:"center"})',button);button.click()
    wait_text(driver,'#audio-edit-status','saved')
