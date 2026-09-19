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
    def click(by,selector):
        node=driver.find_element(by,selector)
        driver.execute_script('arguments[0].scrollIntoView({block:"center"})',node)
        node.click()
    audio=tmp_path/'media'/'test-station'/'originals'/('a'*32+'.mp3')
    subprocess.run(['/usr/bin/ffmpeg','-y','-hide_banner','-loglevel','error','-f','lavfi','-i','sine=frequency=440:duration=30','-codec:a','libmp3lame',str(audio)],check=True)
    driver.get(base+'/admin/stations/test-station/media')
    wait_text(driver,'#room-songs','Verified Test Track')
    click(By.CSS_SELECTOR,'.room-song .preview-button')
    WebDriverWait(driver,8).until(lambda d:d.execute_script('return !document.getElementById("music-audio").paused && document.getElementById("music-audio").currentTime > 0'))
    click(By.CSS_SELECTOR,'[data-create=tag]')
    driver.find_element(By.CSS_SELECTOR,'#destination-form [name=name]').send_keys('HOT')
    click(By.CSS_SELECTOR,'#destination-form button')
    wait_text(driver,'#room-tags','HOT')
    source=driver.find_element(By.CSS_SELECTOR,'.song-row-copy b');target=driver.find_element(By.CSS_SELECTOR,'[data-drop-kind=tag]')
    ActionChains(driver).move_to_element(source).click_and_hold().move_to_element(target).pause(.2).release().perform()
    WebDriverWait(driver,8,ignored_exceptions=(StaleElementReferenceException,)).until(lambda d:d.find_element(By.CSS_SELECTOR,'.music-toggle[data-kind=tag]').get_attribute('aria-pressed')=='true')
    click(By.ID,'room-undo')
    WebDriverWait(driver,8,ignored_exceptions=(StaleElementReferenceException,)).until(lambda d:d.find_element(By.CSS_SELECTOR,'.music-toggle[data-kind=tag]').get_attribute('aria-pressed')=='false')
    # A tag can also be dragged onto one song.
    source=driver.find_element(By.CSS_SELECTOR,'.tag-drag');target=driver.find_element(By.CSS_SELECTOR,'.room-song')
    ActionChains(driver).move_to_element(source).click_and_hold().move_to_element(target).pause(.2).release().perform()
    WebDriverWait(driver,8,ignored_exceptions=(StaleElementReferenceException,)).until(lambda d:d.find_element(By.CSS_SELECTOR,'.music-toggle[data-kind=tag]').get_attribute('aria-pressed')=='true')
    click(By.CSS_SELECTOR,'#room-categories .destination-name')
    wait_text(driver,'#song-inspector','CATEGORY EDITOR')
    name=driver.find_element(By.CSS_SELECTOR,'.category-editor [name=name]');name.clear();name.send_keys('Evening')
    click(By.CSS_SELECTOR,'.category-editor button')
    wait_text(driver,'#room-categories','Evening')
    click(By.CSS_SELECTOR,'.music-toggle[data-kind=category]')
    WebDriverWait(driver,8).until(lambda d:not d.execute_script('return FreoMusicToggles.pending'))
    click(By.XPATH,"//button[text()='Browse songs to add']")
    wait_text(driver,'#room-songs','Verified Test Track')
    click(By.CSS_SELECTOR,'.music-toggle[data-kind=category]')
    WebDriverWait(driver,8).until(lambda d:not d.execute_script('return FreoMusicToggles.pending'))
    assert driver.find_element(By.CSS_SELECTOR,'.music-toggle[data-kind=category]').get_attribute('aria-pressed')=='true'
    click(By.CSS_SELECTOR,'.song-row-copy b')
    wait_text(driver,'#song-inspector','SELECTED SONG')
    driver.find_element(By.ID,'song-notes').send_keys('Great opener')
    click(By.XPATH,"//button[text()='Save notes']")
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
    driver.get(base+'/admin/stations/test-station/media')
    wait_text(driver,'#room-songs','Verified Test Track')
    driver.find_element(By.CSS_SELECTOR,'.room-song input').click()
    driver.find_element(By.ID,'process-selected').click()
    wait_text(driver,'#room-message-text','priority processing')
    with app.app_context():assert Track.query.first().analysis_requested
    WebDriverWait(driver,8,ignored_exceptions=(StaleElementReferenceException,)).until(lambda d: d.find_element(By.CSS_SELECTOR,'.song-menu summary').click() or True)
    driver.find_element(By.CSS_SELECTOR,'.song-menu .delete-song').click()
    driver.find_element(By.CSS_SELECTOR,'.freo-dialog .dialog-actions button').click()
    with app.app_context():assert MediaIngestJob.query.filter_by(kind='delete').count()==0
    assert not driver.find_elements(By.CSS_SELECTOR,'.song-menu[open]')
    driver.find_element(By.CSS_SELECTOR,'.song-menu summary').click()
    driver.find_element(By.CSS_SELECTOR,'.song-menu .delete-song').click()
    driver.find_element(By.CSS_SELECTOR,'.freo-dialog .admin-primary').click()
    wait_text(driver,'#room-message-text','Song removed from Music')
    with app.app_context():assert MediaIngestJob.query.filter_by(kind='delete').count()==1


def test_availability_shortcuts_save_and_editor_layout(booth):
    app,driver,base,tmp_path=booth
    def click(selector):
        node=driver.find_element(By.CSS_SELECTOR,selector)
        driver.execute_script('arguments[0].scrollIntoView({block:"center"})',node);node.click()
    driver.get(base+'/admin/stations/test-station/media')
    wait_text(driver,'#room-songs','Verified Test Track');click('.song-row-copy b')
    wait_text(driver,'#song-inspector','Channel availability');click('#song-inspector .availability-shortcut')
    click('.availability-dialog [name=available_to_all]');click('.availability-dialog [type=submit]')
    WebDriverWait(driver,8).until(lambda d:not d.find_elements(By.CSS_SELECTOR,'.availability-dialog'))
    with app.app_context():assert Track.query.first().available_to_all
    click('.song-menu summary');click('.song-menu a')
    wait_text(driver,'#editor-title','Verified Test Track')
    assert driver.execute_script('return document.getElementById("media-editor").lastElementChild.id')=='channel-availability'
    click('#editor-availability')
    assert driver.find_element(By.CSS_SELECTOR,'.availability-dialog [name=available_to_all]').is_selected()
    click('.availability-dialog [type=button]')
    assert not driver.find_elements(By.CSS_SELECTOR,'.availability-dialog')
    click('#channel-availability [name=available_to_all]');click('#channel-availability [type=submit]')
    wait_text(driver,'#channel-availability [role=status]','Channel availability saved')
    assert driver.find_elements(By.ID,'media-editor')
    with app.app_context():assert not Track.query.first().available_to_all
    driver.set_window_size(430,932)
    assert driver.execute_script('return document.documentElement.scrollWidth<=innerWidth')
    driver.execute_script('document.getElementById("channel-availability").scrollIntoView({block:"center"})')
    driver.save_screenshot('/tmp/freo-availability-mobile.png')
    click('#media-editor .section-title a')
    wait_text(driver,'#room-songs','Verified Test Track')
    assert not driver.find_elements(By.CSS_SELECTOR,'.freo-dialog[open]')
