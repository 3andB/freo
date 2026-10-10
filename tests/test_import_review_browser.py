"""Browser reproductions for recovery and editing gaps found in importer review."""
import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from werkzeug.wrappers import Response
from app.extensions import db
from app.models import MusicImportItem, MusicImportSession
from tests.test_web import app as app_fixture
from tests.test_live_browser import booth, open_import, wait_text
from tests.test_import_sessions_browser import add_audio, work, click, choose


def test_expired_session_during_polling_has_actionable_message(booth,monkeypatch):
    app,driver,base,tmp_path=booth;open_import(driver,base)
    add_audio(driver,tmp_path);work(app,True);wait_text(driver,'.import-card','Ready to import')
    with app.app_context():identifier=MusicImportSession.query.one().id
    original=app.wsgi_app
    blocked=True
    def expired(environ,start_response):
        if blocked and environ['REQUEST_METHOD']=='GET' and environ['PATH_INFO'].endswith('/imports/'+identifier):
            return Response(status=302,headers={'Location':'/admin/login'})(environ,start_response)
        return original(environ,start_response)
    monkeypatch.setattr(app,'wsgi_app',expired)
    # Returning to the tab polls immediately; idle imports otherwise poll every
    # 30 seconds. The opening instruction is already nonempty before expiry.
    driver.execute_script("document.dispatchEvent(new Event('visibilitychange'))")
    WebDriverWait(driver,10).until(lambda d:d.find_element(By.ID,'import-auth').is_displayed())
    message=driver.find_element(By.ID,'import-message').text
    assert 'sign in' in message.lower() and 'Unexpected token' not in message, message
    assert driver.find_element(By.ID,'import-auth').is_displayed()
    blocked=False
    # Signing in rotates the CSRF token. Simulate the resulting signed cookie.
    serializer=app.session_interface.get_signing_serializer(app)
    values=serializer.loads(driver.get_cookie('session')['value'])
    values['admin_csrf']='rotated-after-sign-in'
    driver.add_cookie({'name':'session','value':serializer.dumps(values),'path':'/'})
    click(driver,'#resume-import');wait_text(driver,'#import-message','Import resumed')
    assert not driver.find_element(By.ID,'import-auth').is_displayed()
    choose(driver,'.import-card','Artist','Artist after sign in',True)
    wait_text(driver,'#import-message','Artist selected')


def test_cleared_track_number_stays_blank_after_refresh(booth):
    app,driver,base,tmp_path=booth;open_import(driver,base)
    add_audio(driver,tmp_path,track='4',date='2024');work(app,True);wait_text(driver,'.import-card','Ready to import')
    field=driver.find_element(By.CSS_SELECTOR,'.import-card input[aria-label^="Track number"]')
    driver.execute_script('arguments[0].closest("details").open=true;arguments[0].value="";arguments[0].dispatchEvent(new Event("input",{bubbles:true}));',field)
    def saved(_):
        with app.app_context():
            values=MusicImportItem.query.one().choices
            return 'track_number' in values and values['track_number'] is None
    WebDriverWait(driver,8).until(saved)
    driver.refresh();wait_text(driver,'.import-card','Ready to import')
    field=driver.find_element(By.CSS_SELECTOR,'.import-card input[aria-label^="Track number"]')
    assert field.get_attribute('value')==''


def test_failed_session_switch_keeps_local_file_available(booth,monkeypatch):
    app,driver,base,tmp_path=booth;open_import(driver,base)
    original=app.wsgi_app
    def unavailable(environ,start_response):
        path=environ['PATH_INFO']
        if environ['REQUEST_METHOD']=='POST' and (path.endswith('/files') or path.endswith('/imports')):
            environ['wsgi.input'].read(int(environ.get('CONTENT_LENGTH','0')))
            status=413 if path.endswith('/files') else 502
            return Response('<html>Unavailable</html>',status=status,mimetype='text/html')(environ,start_response)
        return original(environ,start_response)
    monkeypatch.setattr(app,'wsgi_app',unavailable)
    driver.execute_script("""const dt=new DataTransfer();dt.items.add(new File([new Uint8Array(100)],'retained.mp3'));
      const input=document.getElementById('media-file');input.files=dt.files;input.dispatchEvent(new Event('change',{bubbles:true}));""")
    wait_text(driver,'.import-row-status','server upload limit')
    WebDriverWait(driver,8).until(lambda d:d.find_element(By.ID,'new-import').is_enabled())
    click(driver,'#new-import');wait_text(driver,'#import-message','HTTP 502')
    assert len(driver.find_elements(By.CSS_SELECTOR,'.import-card'))==1
    monkeypatch.setattr(app,'wsgi_app',original)
    retry=next(b for b in driver.find_elements(By.CSS_SELECTOR,'.import-card > button') if b.text=='Retry')
    driver.execute_script('arguments[0].click()',retry)
    wait_text(driver,'.import-row-status','Uploaded')
    with app.app_context():assert MusicImportItem.query.one().original_filename=='retained.mp3'


def test_repeated_album_category_additions_apply_to_later_songs(booth):
    app,driver,base,tmp_path=booth
    from app.models import MediaCategory
    with app.app_context():
        category=MediaCategory(station_id=1,name='Additional',slug='additional',enabled=True)
        db.session.add(category);db.session.commit()
        expected={row.id for row in MediaCategory.query.filter_by(station_id=1)}
    open_import(driver,base)
    add_audio(driver,tmp_path,album='Review album',track='1');work(app,True);wait_text(driver,'.import-card','Ready to import')
    for name in ('Power','Additional'):
        click(driver,'.import-group-head button')
        button=next(b for b in driver.find_elements(By.CSS_SELECTOR,'#batch-classification [aria-label=categories] button') if name in b.text)
        driver.execute_script('arguments[0].click()',button)
        click(driver,'#apply-batch');wait_text(driver,'#batch-status','Updated 1 songs')
        click(driver,'#close-batch')
    add_audio(driver,tmp_path,2,album='Review album',track='2');work(app,True);wait_text(driver,'.import-card:last-child','Ready to import')
    with app.app_context():
        first=MusicImportItem.query.filter_by(original_filename='song-1.mp3').one()
        later=MusicImportItem.query.filter_by(original_filename='song-2.mp3').one()
        assert set(first.choices['categories'])==expected
        assert set(later.choices['categories'])==expected


def test_mixed_valid_and_invalid_files_import_ready_songs_without_deselecting_failure(booth):
    app,driver,base,tmp_path=booth;open_import(driver,base)
    add_audio(driver,tmp_path,artist='Review artist',album='Review album',track='1')
    driver.execute_script("""const dt=new DataTransfer();dt.items.add(new File(['not audio'],'broken.mp3'));
      const input=document.getElementById('media-file');input.files=dt.files;input.dispatchEvent(new Event('change',{bubbles:true}));""")
    WebDriverWait(driver,8).until(lambda d:len(d.find_elements(By.CSS_SELECTOR,'.import-card'))==2)
    wait_text(driver,'.import-card:last-child','Uploaded')
    work(app,True)
    WebDriverWait(driver,8).until(lambda d:any('Audio probe failed' in c.text for c in d.find_elements(By.CSS_SELECTOR,'.import-card')))
    submit=driver.find_element(By.CSS_SELECTOR,'#media-upload-form [type=submit]')
    assert submit.is_enabled()
    driver.execute_script('document.querySelector("#selected-files").scrollIntoView({block:"center"})')
    driver.save_screenshot('/tmp/freo-import-review-mixed-desktop.png')
    driver.set_window_size(430,932)
    driver.execute_script('document.querySelector("#selected-files").scrollIntoView({block:"start"})')
    assert driver.execute_script('return document.documentElement.scrollWidth<=innerWidth')
    driver.save_screenshot('/tmp/freo-import-review-mixed-mobile.png')
    broken=next(c for c in driver.find_elements(By.CSS_SELECTOR,'.import-card') if 'Audio probe failed' in c.text)
    assert broken.find_element(By.CSS_SELECTOR,'.import-card-head input[type=checkbox]').is_selected()
    assert submit.is_enabled()
    submit.click()
    wait_text(driver,'#import-message','Import started')
    work(app)
    with app.app_context():
        from app.models import Track
        assert Track.query.filter_by(artist='Review artist').count()==1
