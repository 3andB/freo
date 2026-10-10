"""Real Chromium regressions for incremental music import and album review."""
import subprocess
import shutil
import tempfile
from pathlib import Path
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from app.extensions import db
from app.models import MusicImportItem, Track, Artist
from tests.test_live_browser import booth, open_import, wait_text
from tests.test_web import app as app_fixture


def click(driver,selector):
    element=driver.find_element(By.CSS_SELECTOR,selector)
    driver.execute_script('arguments[0].scrollIntoView({block:"center"})',element);element.click()


def add_audio(driver,tmp_path,index=1,**tags):
    path=tmp_path/f'song-{index}.mp3'
    command=['ffmpeg','-v','error','-f','lavfi','-i',f'sine=frequency={500+index}:duration=2']
    for key,value in {'title':f'Song {index}','artist':'File artist',**tags}.items():command+=['-metadata',f'{key}={value}']
    subprocess.run(command+['-y',str(path)],check=True)
    # Browser file injection reads actual audio without depending on snap's /tmp mapping.
    import base64
    driver.execute_script("""const raw=atob(arguments[0]), bytes=Uint8Array.from(raw,c=>c.charCodeAt(0));
      const dt=new DataTransfer();dt.items.add(new File([bytes],arguments[1],{type:'audio/mpeg'}));
      const input=document.getElementById('media-file');input.files=dt.files;input.dispatchEvent(new Event('change',{bubbles:true}));""",base64.b64encode(path.read_bytes()).decode(),path.name)
    wait_text(driver,'.import-card:last-child','Uploaded')


def work(app,prepare_only=False):
    with app.app_context():
        if prepare_only:
            from app.services.import_sessions import prepare_one
            while prepare_one():pass
        else:
            from app.ingest_worker import process_one
            while process_one():pass


def choose(driver,host,label,name,create=False):
    field=driver.find_element(By.CSS_SELECTOR,f'{host} input[aria-label="{label}"]')
    driver.execute_script('arguments[0].scrollIntoView({block:"center"})',field)
    from selenium.webdriver.common.keys import Keys
    field.click();field.send_keys(Keys.CONTROL,'a');field.send_keys(name)
    options=driver.find_elements(By.CSS_SELECTOR,f'{host} .catalog-options:not([hidden]) button')
    matches=[b for b in options if b.text==(f'Create “{name}”' if create else name) or (not create and b.text.startswith(name+' · '))]
    assert matches, (field.get_attribute('value'),[(b.text,b.get_attribute('textContent')) for b in options],driver.execute_script('return document.activeElement.outerHTML'))
    target=matches[0]
    target.click()
    WebDriverWait(driver,8).until(lambda d:field.get_attribute('value')==name and field.get_attribute('aria-expanded')=='false')


def wait_saved(app,title=None,artist=None):
    def saved(_):
        with app.app_context():
            rows=MusicImportItem.query.all()
            return any((not title or r.choices.get('title')==title) and (not artist or (r.choices.get('artist_id') and db.session.get(Artist,r.choices['artist_id']).name==artist)) for r in rows)
    WebDriverWait(app,10).until(saved)


def test_amber_state_incremental_upload_and_edit_in_place(booth):
    app,driver,base,tmp_path=booth;open_import(driver,base)
    add_audio(driver,tmp_path,1);work(app,True);wait_text(driver,'.import-card','Ready to import')
    choose(driver,'.import-card:first-child','Artist','Amber State',True)
    wait_saved(app,artist='Amber State')
    add_audio(driver,tmp_path,2);work(app,True);wait_text(driver,'.import-card:last-child','Ready to import')
    assert driver.find_element(By.CSS_SELECTOR,'.import-card:last-child .import-row-editor').is_displayed()
    choose(driver,'.import-card:last-child','Artist','Amber State')
    wait_saved(app,artist='Amber State')
    click(driver,'#media-upload-form [type=submit]');wait_text(driver,'#import-message','Import started')
    work(app);wait_text(driver,'.import-card:last-child','Imported')
    with app.app_context():
        songs=Track.query.filter(Track.title.in_(['Song 1','Song 2'])).all()
        assert len(songs)==2 and all(s.artist=='Amber State' for s in songs)
    # Editing after upload stays in this workspace, and creates no second upload.
    if not driver.find_element(By.CSS_SELECTOR,'.import-card:last-child .import-row-editor').is_displayed():click(driver,'.import-card:last-child .import-card-head button[aria-label^="Edit"]')
    choose(driver,'.import-card:last-child','Artist','Corrected Artist',True)
    def corrected(_):
        with app.app_context():return Track.query.filter_by(title='Song 2',artist='Corrected Artist').count()==1
    WebDriverWait(driver,10).until(corrected)
    workspace=driver.find_element(By.ID,'import-sessions').get_attribute('value')
    driver.get(base+'/admin/stations/test-station/media/upload?import_session='+workspace)
    WebDriverWait(driver,10).until(lambda d:len(d.find_elements(By.CSS_SELECTOR,'.import-card'))==2)
    wait_text(driver,'.import-card:last-child','Corrected Artist')
    with app.app_context():assert Track.query.count()==3
    driver.save_screenshot('/tmp/freo-import-workspace-desktop.png')
    driver.set_window_size(430,932)
    assert driver.execute_script('return document.documentElement.scrollWidth <= innerWidth')
    driver.save_screenshot('/tmp/freo-import-workspace-mobile.png')


def test_album_bulk_artist_preserves_category_and_later_track_inherits(booth):
    app,driver,base,tmp_path=booth;open_import(driver,base)
    for index in (1,2):add_audio(driver,tmp_path,index,album='My Album',track=str(index))
    work(app,True);wait_text(driver,'.import-card:last-child','Ready to import')
    assert driver.find_element(By.CSS_SELECTOR,'.import-card:first-of-type .import-row-editor').is_displayed()
    assert driver.find_element(By.CSS_SELECTOR,'.import-card:first-of-type .import-more').get_attribute('open')
    click(driver,'.import-card:first-of-type [aria-label=categories] button')
    click(driver,'.import-group-head button')
    choose(driver,'#batch-catalog','Artist','Amber State',True)
    click(driver,'#apply-batch');wait_text(driver,'#batch-status','Updated 2 songs')
    with app.app_context():
        rows=MusicImportItem.query.order_by(MusicImportItem.original_filename).all()
        assert rows[0].choices['categories'] and 'categories' not in rows[1].choices
        assert all(db.session.get(Artist,r.choices['artist_id']).name=='Amber State' for r in rows)
    add_audio(driver,tmp_path,3,album='My Album',track='3');work(app,True)
    wait_text(driver,'.import-card:last-child','Ready to import')
    def inherited(_):
        with app.app_context():
            row=MusicImportItem.query.filter_by(original_filename='song-3.mp3').one()
            return bool(row.choices.get('artist_id'))
    WebDriverWait(driver,10).until(inherited)
    click(driver,'#media-upload-form [type=submit]');wait_text(driver,'#import-message','Import started');work(app)
    wait_text(driver,'.import-card:last-child','Imported')
    with app.app_context():
        songs=Track.query.filter(Track.title.in_(['Song 1','Song 2','Song 3'])).all()
        assert len(songs)==3 and len({s.album_id for s in songs})==1
        assert all(s.artist=='Amber State' for s in songs)


def test_bulk_reset_undo_keyboard_and_large_album(booth):
    app,driver,base,tmp_path=booth
    import uuid
    from app.models import MusicImportSession, Station, AdminUser
    from app.services.music_catalog import artist_for
    with app.app_context():
        station=Station.query.filter_by(slug='test-station').one()
        artist=artist_for(station.id,'Amber State')
        session=MusicImportSession(station_id=station.id,admin_user_id=AdminUser.query.first().id)
        db.session.add(session);db.session.flush()
        for index in range(105):
            db.session.add(MusicImportItem(id=str(uuid.uuid4()),session_id=session.id,original_filename=f'{index+1:03}.mp3',relative_path='',size_bytes=100,checksum=str(index).zfill(64),status='ready',detected={'artist':'File artist','album':'Large album','track_number':index+1,'title':f'Track {index+1}'},choices={'artist_id':artist.id}))
        db.session.commit()
    open_import(driver,base)
    assert len(driver.find_elements(By.CSS_SELECTOR,'.import-card'))==105
    assert driver.find_element(By.CSS_SELECTOR,'#media-upload-form [type=submit]').text=='Import 105 ready songs'
    click(driver,'.import-group-head button')
    field=driver.find_element(By.CSS_SELECTOR,'#batch-catalog input[aria-label=Artist]');field.click()
    # The first keyboard option restores file metadata, rather than leaving the old ID.
    from selenium.webdriver.common.keys import Keys
    field.send_keys(Keys.ARROW_DOWN);driver.switch_to.active_element.send_keys(Keys.ENTER)
    click(driver,'#apply-batch');wait_text(driver,'#batch-status','Updated 105 songs')
    with app.app_context():assert all('artist_id' not in row.choices for row in MusicImportItem.query.all())
    click(driver,'#undo-batch');wait_text(driver,'#import-message','Shared changes undone')
    with app.app_context():assert all(row.choices.get('artist_id') for row in MusicImportItem.query.all())
    click(driver,'#close-batch')
    driver.set_window_size(430,932)
    driver.execute_script('document.querySelector(".import-group-head").scrollIntoView({block:"start"})')
    assert driver.execute_script('return document.documentElement.scrollWidth <= innerWidth')
    assert driver.execute_script('const r=document.querySelector(".import-action-bar").getBoundingClientRect();return r.top>=0 && r.bottom<=innerHeight')
    driver.save_screenshot('/tmp/freo-import-album-mobile.png')


def test_single_tagged_song_then_add_another_after_import(booth):
    app,driver,base,tmp_path=booth;open_import(driver,base)
    add_audio(driver,tmp_path,1);work(app,True);wait_text(driver,'.import-card','Ready to import')
    click(driver,'#media-upload-form [type=submit]');wait_text(driver,'#import-message','Import started');work(app)
    wait_text(driver,'.import-card','Imported')
    field=driver.find_element(By.CSS_SELECTOR,'.import-card input[aria-label=Artist]')
    WebDriverWait(driver,8).until(lambda _:field.get_attribute('value')=='File artist')
    choose(driver,'.import-card','Artist','Amber State',True)
    def saved(_):
        with app.app_context():return Track.query.filter_by(title='Song 1',artist='Amber State').count()==1
    WebDriverWait(driver,8).until(saved)
    add_audio(driver,tmp_path,2);work(app,True);wait_text(driver,'.import-card:last-child','Ready to import')
    assert driver.find_element(By.CSS_SELECTOR,'.import-card:last-child .import-row-editor').is_displayed()
    choose(driver,'.import-card:last-child','Artist','Amber State')
    click(driver,'#media-upload-form [type=submit]');wait_text(driver,'#import-message','Import started');work(app)
    wait_text(driver,'.import-card:last-child','Imported')
    with app.app_context():assert Track.query.filter_by(artist='Amber State').count()==2


def test_interrupted_first_upload_restores_file_reselection(booth):
    app,driver,base,tmp_path=booth;open_import(driver,base)
    import json,uuid
    from app.models import MusicImportSession
    with app.app_context():identifier=MusicImportSession.query.one().id
    key='/admin/api/stations/test-station/imports/'+identifier
    record={'id':str(uuid.uuid4()),'name':'interrupted.mp3','size':100,'path':'','choices':{}}
    driver.execute_script('localStorage.setItem(arguments[0],arguments[1])',key,json.dumps([record]))
    driver.refresh();wait_text(driver,'.import-card','Reselect this file')
    driver.execute_script("""const dt=new DataTransfer();dt.items.add(new File([new Uint8Array(100)],'interrupted.mp3'));
      const input=document.getElementById('media-file');input.files=dt.files;input.dispatchEvent(new Event('change',{bubbles:true}));""")
    wait_text(driver,'.import-card','Uploaded')
    assert len(driver.find_elements(By.CSS_SELECTOR,'.import-card'))==1
    with app.app_context():assert MusicImportItem.query.one().id==record['id']


def test_upload_errors_keep_file_for_retry(booth, monkeypatch):
    app,driver,base,tmp_path=booth;open_import(driver,base)
    from werkzeug.wrappers import Response
    from app.services.admin_media import staged_path
    original=app.wsgi_app
    failures=[
        (Response('<html><h1>Too large</h1></html>',status=413,mimetype='text/html'),'server upload limit'),
        (Response('<html>Bad gateway</html>',status=502,mimetype='text/html'),'HTTP 502'),
        (Response('<html>Gateway timeout</html>',status=504,mimetype='text/html'),'HTTP 504'),
        (Response(status=302,headers={'Location':'/admin/login'}),'session expired'),
        (Response('<html>Forbidden</html>',status=403,mimetype='text/html'),'permission to upload'),
        (Response('<html>Unexpected success page</html>',mimetype='text/html'),'HTTP 200'),
        (Response('<html>Malformed JSON</html>',mimetype='application/json'),'invalid response'),
        (Response('null',mimetype='application/json'),'invalid upload response'),
        (Response('{"message":"Upload staging is unavailable"}',status=409,mimetype='application/json'),'Upload staging is unavailable'),
    ]
    pending=list(failures)
    def intercept(environ,start_response):
        if environ['REQUEST_METHOD']=='POST' and environ['PATH_INFO'].endswith('/files') and pending:
            # Consume the request just as a real proxy would, then return its error.
            environ['wsgi.input'].read(int(environ.get('CONTENT_LENGTH','0')))
            return pending.pop(0)[0](environ,start_response)
        return original(environ,start_response)
    monkeypatch.setattr(app,'wsgi_app',intercept)
    driver.execute_script("""const dt=new DataTransfer();dt.items.add(new File([new Uint8Array(100)],'retry.mp3'));
      const input=document.getElementById('media-file');input.files=dt.files;input.dispatchEvent(new Event('change',{bubbles:true}));""")
    for _,message in failures:
        wait_text(driver,'.import-row-status',message)
        assert len(driver.find_elements(By.CSS_SELECTOR,'.import-card'))==1
        with app.app_context():assert MusicImportItem.query.count()==0
        retry=next(button for button in driver.find_elements(By.CSS_SELECTOR,'.import-card > button') if button.text=='Retry')
        driver.execute_script('arguments[0].click()',retry)
    wait_text(driver,'.import-row-status','Uploaded')
    with app.app_context():
        item=MusicImportItem.query.one()
        assert item.original_filename=='retry.mp3'
        assert staged_path(item.id).read_bytes()==bytes(100)


def test_delayed_poll_cannot_undo_edits_or_restore_previous_workspace(booth):
    app,driver,base,tmp_path=booth;open_import(driver,base)
    add_audio(driver,tmp_path);work(app,True);wait_text(driver,'.import-card','Ready to import')
    from app.models import MusicImportSession
    with app.app_context():identifier=MusicImportSession.query.one().id
    driver.execute_script("""const original=window.fetch;window.holdImportPoll=true;
      window.fetch=async (url,options={})=>{const response=await original(url,options);
        if(String(url).endsWith(arguments[0])&&(!options.method||options.method==='GET')&&window.holdImportPoll){
          window.holdImportPoll=false;window.importPollWaiting=true;
          await new Promise(resolve=>{window.releaseImportPoll=resolve;});
        }return response;};""",identifier)
    WebDriverWait(driver,8).until(lambda d:d.execute_script('return window.importPollWaiting'))
    choose(driver,'.import-card','Artist','First change',True);wait_saved(app,artist='First change')
    driver.execute_script('window.releaseImportPoll()')
    choose(driver,'.import-card','Artist','Second change',True);wait_saved(app,artist='Second change')
    driver.execute_script('window.importPollWaiting=false;window.holdImportPoll=true;')
    WebDriverWait(driver,8).until(lambda d:d.execute_script('return window.importPollWaiting'))
    click(driver,'#new-import')
    WebDriverWait(driver,8).until(lambda d:not d.find_elements(By.CSS_SELECTOR,'.import-card')
        and d.find_element(By.ID,'import-sessions').get_attribute('value') != identifier)
    new_session=driver.find_element(By.ID,'import-sessions').get_attribute('value')
    driver.execute_script('window.releaseImportPoll()')
    # Let the old response and the next normal polling interval both complete.
    driver.execute_async_script('setTimeout(arguments[0],3000)')
    assert not driver.find_elements(By.CSS_SELECTOR,'.import-card')
    assert driver.find_element(By.ID,'import-sessions').get_attribute('value') == new_session
    assert 'has-files' not in driver.find_element(By.ID,'media-upload-form').get_attribute('class').split()
