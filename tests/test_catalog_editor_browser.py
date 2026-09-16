"""Real browser and worker exercise import, listening, artwork, and editing."""
import subprocess
from pathlib import Path
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from app.extensions import db
from app.models import Track,MediaIngestJob,Artist,Album
from tests.test_live_browser import booth,wait_text
from tests.test_web import app as app_fixture


def test_import_and_edit_catalog(booth, request):
    app,driver,base,tmp_path=booth
    def click(selector):
        element=driver.find_element(By.CSS_SELECTOR,selector)
        driver.execute_script('arguments[0].scrollIntoView({block:"center"})',element)
        element.click()
    audio=tmp_path/'incoming.mp3';image=tmp_path/'cover.png'
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','sine=frequency=650:duration=12','-metadata','title=My imported song','-metadata','artist=File artist',str(audio)],check=True)
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=c=blue:s=900x700','-frames:v','1',str(image)],check=True)
    import tempfile,shutil
    browser_tmp=Path('/tmp/snap-private-tmp/snap.chromium/tmp')
    share=Path(tempfile.mkdtemp(prefix='freo-catalog-',dir=browser_tmp if browser_tmp.exists() else tmp_path))
    request.addfinalizer(lambda:shutil.rmtree(share))
    shutil.copy(audio,share/audio.name);shutil.copy(image,share/image.name)
    browser_dir=Path('/tmp')/share.name if browser_tmp.exists() else share
    driver.get(base+'/admin/stations/test-station/media/upload')
    driver.find_element(By.ID,'media-file').send_keys(str(browser_dir/audio.name))
    wait_text(driver,'.import-card','incoming.mp3')
    WebDriverWait(driver,8).until(lambda d:d.find_element(By.CSS_SELECTOR,'.import-song-fields input').get_attribute('value')=='My imported song')
    driver.find_element(By.XPATH,"//button[text()='▶ Listen']").click()
    WebDriverWait(driver,8).until(lambda d:d.execute_script('return !document.getElementById("music-audio").paused'))
    # Inline artist and album creation inside the import card.
    click('.import-card [aria-label="Add artist"]')
    driver.find_element(By.CSS_SELECTOR,'.import-card .inline-catalog-add input').send_keys('New browser artist')
    click('.import-card .inline-catalog-add button')
    WebDriverWait(driver,8).until(lambda d:not d.find_elements(By.CSS_SELECTOR,'.inline-catalog-add'))
    click('.import-card [aria-label="Add album"]')
    driver.find_element(By.CSS_SELECTOR,'.import-card .inline-catalog-add input').send_keys('New browser album')
    click('.import-card .inline-catalog-add button')
    WebDriverWait(driver,8).until(lambda d:not d.find_elements(By.CSS_SELECTOR,'.inline-catalog-add'))
    click('.import-card [aria-label=categories] button')
    click('.import-card>button')
    driver.find_element(By.CSS_SELECTOR,'.artwork-dialog input[type=file]').send_keys(str(browser_dir/image.name))
    save=driver.find_element(By.XPATH,"//button[text()='Save artwork']")
    WebDriverWait(driver,8).until(lambda d:save.is_enabled());save.click()
    WebDriverWait(driver,8).until(lambda d:not d.find_elements(By.CSS_SELECTOR,'.artwork-dialog'))
    click('#media-upload-form>button[type=submit]')
    WebDriverWait(driver,8).until(lambda d:'Uploading' not in d.find_element(By.CSS_SELECTOR,'.import-card p[role=status]').text)
    from app.ingest_worker import process_one
    from app.services.analysis_queue import process_analysis
    with app.app_context():
        assert process_one()
        job=MediaIngestJob.query.filter_by(kind='ingest').one();song=job.track
        assert song and song.artist=='New browser artist' and song.album=='New browser album'
        assert song.catalog_album.cover_id and not song.enabled
        Track.query.filter(Track.id!=song.id).update({'analysis_status':'complete'});db.session.commit()
        assert process_analysis();db.session.refresh(song);assert song.enabled and song.waveform
        identifier=song.uuid
    wait_text(driver,'.import-card','Enabled for broadcast')
    driver.get(base+'/admin/stations/test-station/media/'+identifier)
    wait_text(driver,'#broadcast-status','Enabled for broadcast')
    assert driver.find_element(By.ID,'editor-cover').is_displayed()
    click('.editor-listen [data-preview]')
    WebDriverWait(driver,8).until(lambda d:d.execute_script('return !document.getElementById("music-audio").paused'))
    click('#waveform-seek')
    WebDriverWait(driver,8).until(lambda d:d.execute_script('return document.getElementById("music-audio").currentTime > 1'))
    driver.save_screenshot('/tmp/freo-media-editor-desktop.png')
    click('.music-toggle[data-kind=category]')
    wait_text(driver,'#broadcast-status','choose an active category')
    driver.find_element(By.ID,'broadcast-toggle').click()
    wait_text(driver,'#broadcast-status','Disabled')
    title=driver.find_element(By.CSS_SELECTOR,'#song-details [name=title]');title.clear();title.send_keys('Edited in browser')
    click('#song-details button[type=submit]')
    wait_text(driver,'#editor-title','Edited in browser')
    click('#editor-catalog [aria-label="Add artist"]')
    driver.find_element(By.CSS_SELECTOR,'dialog[open] input').send_keys('Popup artist')
    click('dialog[open] button')
    WebDriverWait(driver,8).until(lambda d:not d.find_elements(By.CSS_SELECTOR,'dialog[open]'))
    click('#song-details button[type=submit]')
    wait_text(driver,'#editor-subtitle','Popup artist')
    driver.set_window_size(430,932)
    assert driver.execute_script('return document.documentElement.scrollWidth <= innerWidth')
    driver.save_screenshot('/tmp/freo-media-editor-mobile.png')
    with app.app_context():
        song=Track.query.filter_by(uuid=identifier).one();assert song.title=='Edited in browser' and not song.enabled and song.album_id is None
