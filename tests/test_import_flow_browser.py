"""User-visible simplicity: ready-only import, rotation, preview, duplicates, results."""
import base64
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select, WebDriverWait
from app.extensions import db
from app.models import MediaCategory, MusicImportItem, Track
from tests.test_web import app as app_fixture
from tests.test_live_browser import booth, open_import, wait_text
from tests.test_import_sessions_browser import add_audio, work, click


def test_mobile_listen_import_rotation_duplicate_and_filtered_results(booth):
    app,driver,base,tmp_path=booth;open_import(driver,base)
    with app.app_context():category=MediaCategory.query.filter_by(station_id=1,enabled=True).first().id
    Select(driver.find_element(By.ID,'import-rotation')).select_by_value(str(category))
    add_audio(driver,tmp_path,artist='Flow artist');work(app,True);wait_text(driver,'.import-card','Ready to import')
    with app.app_context():assert MusicImportItem.query.one().choices['categories']==[category]
    driver.set_window_size(430,932)
    click(driver,'.import-card-head button')
    WebDriverWait(driver,8).until(lambda d:d.execute_script('return !document.getElementById("music-audio").paused'))
    WebDriverWait(driver,8).until(lambda d:d.execute_script('return document.querySelector(".import-action-bar").getBoundingClientRect().bottom<=document.getElementById("music-player").getBoundingClientRect().top'))
    assert driver.execute_script('return document.documentElement.scrollWidth<=innerWidth')
    driver.save_screenshot('/tmp/freo-import-flow-mobile-preview.png')
    click(driver,'#media-upload-form [type=submit]');wait_text(driver,'#import-message','Import started');work(app)
    wait_text(driver,'.import-card','Imported')
    click(driver,'#preview-close')
    assert driver.find_element(By.ID,'music-player').get_attribute('hidden')
    # Re-adding identical audio should identify it immediately and preserve metadata.
    path=tmp_path/'song-1.mp3'
    driver.execute_script('''const bytes=Uint8Array.from(atob(arguments[0]),c=>c.charCodeAt(0)),dt=new DataTransfer();
      dt.items.add(new File([bytes],'song-1.mp3',{type:'audio/mpeg'}));const input=document.getElementById('media-file');
      input.files=dt.files;input.dispatchEvent(new Event('change',{bubbles:true}));''',base64.b64encode(path.read_bytes()).decode())
    wait_text(driver,'.import-card:last-child','Already in library')
    duplicate=driver.find_elements(By.CSS_SELECTOR,'.import-card')[-1]
    assert not duplicate.find_element(By.CSS_SELECTOR,'input[type=checkbox]').is_enabled()
    assert not duplicate.find_element(By.CSS_SELECTOR,'input[type=checkbox]').is_selected()
    work(app,True)
    wait_text(driver,'#selection-summary','Imported · finishing audio processing')
    assert not driver.find_element(By.CSS_SELECTOR,'#media-upload-form [type=submit]').is_displayed()
    driver.save_screenshot('/tmp/freo-import-flow-mobile-complete.png')
    driver.set_window_size(1440,1000);driver.save_screenshot('/tmp/freo-import-flow-desktop.png')
    click(driver,'#view-imported')
    wait_text(driver,'#room-total','1 songs')
    assert driver.find_element(By.ID,'collection-title').text=='Imported songs'
    assert len(driver.find_elements(By.CSS_SELECTOR,'.room-song'))==1
    with app.app_context():
        song=Track.query.filter_by(artist='Flow artist').one()
        assert [c.id for c in song.categories]==[category]
    click(driver,'#room-all');wait_text(driver,'#room-total','2 songs')


def test_playlist_bubbles_defaults_and_success_resets_import(booth):
    from app.models import Playlist
    app,driver,base,tmp_path=booth
    with app.app_context():
        from app.services.playlists import seed_playlists
        seed_playlists(1)
        playlist=Playlist(station_id=1,name='New songs',mode='RANDOM')
        db.session.add(playlist);db.session.commit();identifier=playlist.id
        batch_identifier=Playlist.query.filter_by(station_id=1,name='Playlist 1').one().id
    open_import(driver,base)
    assert not driver.find_elements(By.ID,'import-playlists')
    add_audio(driver,tmp_path,artist='Reset artist');work(app,True);wait_text(driver,'.import-card','Ready to import')
    bubbles='.import-card [aria-label=playlists] button'
    assert any('Playlist 1' in b.text for b in driver.find_elements(By.CSS_SELECTOR,bubbles))
    assert any('Playlist 2' in b.text for b in driver.find_elements(By.CSS_SELECTOR,bubbles))
    selected=next(b for b in driver.find_elements(By.CSS_SELECTOR,bubbles) if 'New songs' in b.text)
    for width in (390,1440):
        driver.set_window_size(width,1000)
        driver.execute_script('arguments[0].scrollIntoView({block:"center"})',selected)
        assert selected.is_displayed()
        assert driver.execute_script('return document.documentElement.scrollWidth<=innerWidth')
    selected.click()
    assert selected.get_attribute('aria-pressed')=='true'
    # Import must flush this individual choice, while batch defaults carry over
    # to later files without overwriting the first song's playlist selection.
    click(driver,'#edit-selected')
    batch=next(b for b in driver.find_elements(By.CSS_SELECTOR,'#batch-classification [aria-label=playlists] button') if b.text=='+ Playlist 1')
    driver.execute_script('arguments[0].scrollIntoView({block:"center"})',batch);batch.click()
    click(driver,'#batch-future');click(driver,'#apply-batch');wait_text(driver,'#batch-status','Updated 1 songs')
    click(driver,'#close-batch')
    add_audio(driver,tmp_path,index=2,artist='Later artist');work(app,True)
    wait_text(driver,'.import-card:last-child','Ready to import')
    with app.app_context():
        first=MusicImportItem.query.filter_by(original_filename='song-1.mp3').one()
        later=MusicImportItem.query.filter_by(original_filename='song-2.mp3').one()
        assert set(first.choices['playlists'])=={identifier,batch_identifier}
        assert later.choices['playlists']==[batch_identifier]
    click(driver,'#media-upload-form [type=submit]');wait_text(driver,'#import-message','Import started');work(app)
    with app.app_context():
        song=Track.query.filter_by(artist='Reset artist').one()
        assert {p.id for p in song.playlists}=={identifier,batch_identifier}
        later=Track.query.filter_by(artist='Later artist').one()
        assert [p.id for p in later.playlists]==[batch_identifier]
        # Completion normally comes from the analysis worker, separately from ingest.
        song.analysis_status=later.analysis_status='complete';db.session.commit()
    wait_text(driver,'#import-success','imported successfully')
    assert not driver.find_elements(By.CSS_SELECTOR,'.import-card')
    assert driver.find_element(By.ID,'media-file').get_attribute('value')==''
    assert driver.find_element(By.ID,'import-done').is_displayed()
    assert driver.find_element(By.ID,'view-imported').is_displayed()
    add_audio(driver,tmp_path,index=3,artist='Next song');work(app,True)
    wait_text(driver,'.import-card','Ready to import')
    assert len(driver.find_elements(By.CSS_SELECTOR,'.import-card'))==1
    assert not [entry for entry in driver.get_log('browser') if entry['level']=='SEVERE']
