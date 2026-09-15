"""User gestures exercise the actual workspace and preview player."""
import subprocess
from pathlib import Path
from selenium.webdriver.common.by import By
from selenium.common.exceptions import StaleElementReferenceException
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from app.extensions import db
from app.models import Track, Station, MusicTag, MediaCategory, MediaIngestJob
from tests.test_live_browser import booth, wait_text
from tests.test_web import app as app_fixture


def test_sound_room_preview_tag_drag_category_editor_notes_and_undo(booth):
    app,driver,base,tmp_path=booth
    audio=tmp_path/'media'/'test-station'/'originals'/('a'*32+'.mp3')
    subprocess.run(['/usr/bin/ffmpeg','-y','-hide_banner','-loglevel','error','-f','lavfi','-i','sine=frequency=440:duration=30','-codec:a','libmp3lame',str(audio)],check=True)
    driver.get(base+'/admin/stations/test-station/media')
    wait_text(driver,'#room-songs','Verified Test Track')
    driver.find_element(By.CSS_SELECTOR,'.room-song .preview-button').click()
    WebDriverWait(driver,8).until(lambda d:d.execute_script('return !document.getElementById("music-audio").paused && document.getElementById("music-audio").currentTime > 0'))
    driver.find_element(By.CSS_SELECTOR,'[data-create=tag]').click()
    driver.find_element(By.CSS_SELECTOR,'#destination-form [name=name]').send_keys('HOT')
    driver.find_element(By.CSS_SELECTOR,'#destination-form button').click()
    wait_text(driver,'#room-tags','HOT')
    source=driver.find_element(By.CSS_SELECTOR,'.song-row-copy b');target=driver.find_element(By.CSS_SELECTOR,'[data-drop-kind=tag]')
    ActionChains(driver).move_to_element(source).click_and_hold().move_to_element(target).pause(.2).release().perform()
    WebDriverWait(driver,8,ignored_exceptions=(StaleElementReferenceException,)).until(lambda d:d.find_element(By.CSS_SELECTOR,'.music-toggle[data-kind=tag]').get_attribute('aria-pressed')=='true')
    driver.find_element(By.ID,'room-undo').click()
    WebDriverWait(driver,8,ignored_exceptions=(StaleElementReferenceException,)).until(lambda d:d.find_element(By.CSS_SELECTOR,'.music-toggle[data-kind=tag]').get_attribute('aria-pressed')=='false')
    # A tag can also be dragged onto one song.
    source=driver.find_element(By.CSS_SELECTOR,'.tag-drag');target=driver.find_element(By.CSS_SELECTOR,'.room-song')
    ActionChains(driver).move_to_element(source).click_and_hold().move_to_element(target).pause(.2).release().perform()
    WebDriverWait(driver,8,ignored_exceptions=(StaleElementReferenceException,)).until(lambda d:d.find_element(By.CSS_SELECTOR,'.music-toggle[data-kind=tag]').get_attribute('aria-pressed')=='true')
    driver.find_element(By.CSS_SELECTOR,'#room-categories .destination-name').click()
    wait_text(driver,'#song-inspector','CATEGORY EDITOR')
    name=driver.find_element(By.CSS_SELECTOR,'.category-editor [name=name]');name.clear();name.send_keys('Evening')
    driver.find_element(By.CSS_SELECTOR,'.category-editor button').click()
    wait_text(driver,'#room-categories','Evening')
    driver.find_element(By.CSS_SELECTOR,'.music-toggle[data-kind=category]').click()
    WebDriverWait(driver,8).until(lambda d:not d.execute_script('return FreoMusicToggles.pending'))
    driver.find_element(By.XPATH,"//button[text()='Browse songs to add']").click()
    wait_text(driver,'#room-songs','Verified Test Track')
    driver.find_element(By.CSS_SELECTOR,'.music-toggle[data-kind=category]').click()
    WebDriverWait(driver,8).until(lambda d:not d.execute_script('return FreoMusicToggles.pending'))
    assert driver.find_element(By.CSS_SELECTOR,'.music-toggle[data-kind=category]').get_attribute('aria-pressed')=='true'
    driver.find_element(By.CSS_SELECTOR,'.song-row-copy b').click()
    wait_text(driver,'#song-inspector','SELECTED SONG')
    driver.find_element(By.ID,'song-notes').send_keys('Great opener')
    driver.find_element(By.XPATH,"//button[text()='Save notes']").click()
    wait_text(driver,'#room-message-text','Notes saved')
    with app.app_context():
        song=Track.query.first();assert song.notes=='Great opener' and song.tags[0].name=='HOT' and song.categories[0].name=='Evening'
    driver.save_screenshot('/tmp/freo-sound-room.png')
    driver.set_window_size(430,932)
    assert driver.execute_script('return document.documentElement.scrollWidth <= innerWidth')
    driver.save_screenshot('/tmp/freo-sound-room-mobile.png')


def test_sound_room_processing_and_delete_menu(booth):
    app,driver,base,tmp_path=booth
    with app.app_context():
        station=Station.query.filter_by(slug='test-station').first();station.desired_state='stopped';db.session.commit()
    driver.get(base+'/admin/stations/test-station/sound-room')
    wait_text(driver,'#room-songs','Verified Test Track')
    driver.find_element(By.CSS_SELECTOR,'.room-song input').click()
    driver.find_element(By.ID,'process-selected').click()
    wait_text(driver,'#room-message-text','priority processing')
    with app.app_context():assert Track.query.first().analysis_requested
    WebDriverWait(driver,8,ignored_exceptions=(StaleElementReferenceException,)).until(lambda d: d.find_element(By.CSS_SELECTOR,'.song-menu summary').click() or True)
    driver.find_element(By.CSS_SELECTOR,'.song-menu .delete-song').click()
    driver.find_element(By.CSS_SELECTOR,'.freo-dialog .dialog-actions button').click()
    with app.app_context():assert MediaIngestJob.query.filter_by(kind='delete').count()==0
    driver.find_element(By.CSS_SELECTOR,'.song-menu .delete-song').click()
    driver.find_element(By.CSS_SELECTOR,'.freo-dialog .admin-primary').click()
    wait_text(driver,'#room-message-text','Permanent deletion queued')
    with app.app_context():assert MediaIngestJob.query.filter_by(kind='delete').count()==1
