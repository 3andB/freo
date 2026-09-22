"""Browser workflows use isolated storage and an isolated station database."""
import os
import shutil
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

import pytest
from werkzeug.serving import make_server
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.common.exceptions import StaleElementReferenceException
from selenium.webdriver.support.ui import WebDriverWait
from app.extensions import db
from app.models import AutomationState, SelectionDecision, Station, Track, LiveQueueSnapshot, LiveControlCommand, MediaIngestJob, MusicImportItem
from tests.test_web import app as app_fixture


@pytest.fixture
def booth(app_fixture, monkeypatch, tmp_path):
    app=app_fixture
    monkeypatch.setenv('FREO_MEDIA_ROOT',str(tmp_path/'media'))
    originals=tmp_path/'media'/'test-station'/'originals';originals.mkdir(parents=True)
    import subprocess
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','sine=frequency=440:duration=4','-y',str(originals/('a'*32+'.mp3'))],check=True)
    uploads=tmp_path/'uploads';uploads.mkdir();app.config['FREO_UPLOAD_ROOT']=str(uploads)
    with app.app_context():
        station=Station.query.filter_by(slug='test-station').first()
        station.automation.operator_mode='DJ_BOOTH';station.automation.hold=True
        Track.query.first().storage_key='a'*32+'.mp3'
        current=SelectionDecision.query.filter_by(status='started').first()
        db.session.add(LiveQueueSnapshot(station_id=station.id,current_decision_id=current.id,queued_decision_ids=[],unknown_count=0,observed_at=datetime.now(timezone.utc),mixer=dict(mode='DJ_BOOTH',a_id=current.id,b_id=None,cart_id=None,a_playing=True,b_playing=False,a_elapsed=2,b_elapsed=0,crossfader=0)))
        db.session.commit()
    # An actual playable stream for persistent-monitor navigation tests.
    import io, wave
    from flask import Response
    audio_bytes=io.BytesIO()
    with wave.open(audio_bytes,'wb') as wav:
        import math, struct
        samples=b''.join(struct.pack('<h',int(4000*math.sin(2*math.pi*440*n/8000))) for n in range(8000))
        wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(8000);wav.writeframes(samples*120)
    app.add_url_rule('/stream/test-station','test_monitor_stream',lambda:Response(audio_bytes.getvalue(),mimetype='audio/wav'))
    # This fixture supplies stable engine observations; audio is tested separately.
    from flask import request
    @app.before_request
    def fixture_observer_heartbeat():
        if request.path.endswith('/live-status'):
            LiveQueueSnapshot.query.update({'observed_at':datetime.now(timezone.utc)})
            db.session.commit()
    server=make_server('127.0.0.1',0,app,threaded=True)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    profile=tempfile.mkdtemp(prefix='freo-browser-',dir='/tmp')
    options=Options();options.binary_location=os.environ.get('FREO_TEST_CHROME','/usr/bin/chromium-browser')
    for arg in ['--headless=new','--no-sandbox','--disable-dev-shm-usage','--window-size=1600,1200',f'--user-data-dir={profile}']:options.add_argument(arg)
    driver=webdriver.Chrome(service=Service(os.environ.get('FREO_TEST_CHROMEDRIVER','/usr/bin/chromedriver')),options=options)
    try:
        base=f'http://127.0.0.1:{server.server_port}'
        driver.get(base+'/admin/login')
        driver.find_element(By.NAME,'email').send_keys('admin@example.test')
        driver.find_element(By.NAME,'password').send_keys('test-password-long-enough')
        driver.find_element(By.CSS_SELECTOR,'.login-card button[type=submit]').click()
        WebDriverWait(driver,10).until(lambda d:d.current_url==base+'/admin' and d.find_elements(By.CSS_SELECTOR,'.admin-sidebar'))
        WebDriverWait(driver,10).until(lambda d:d.find_element(By.ID,'license-agreement').is_displayed())
        driver.find_element(By.CSS_SELECTOR,'#license-accept-form input[name=agree]').click()
        driver.find_element(By.CSS_SELECTOR,'#license-accept-form button[type=submit]').click()
        WebDriverWait(driver,10).until(lambda d:not d.find_element(By.ID,'license-agreement').is_displayed())
        driver.get(base+'/admin/stations/test-station/live')
        yield app,driver,base,tmp_path
    except Exception:
        driver.save_screenshot("/tmp/freo-browser-failure.png")
        raise
    finally:
        driver.quit();server.shutdown();thread.join(timeout=3);shutil.rmtree(profile,ignore_errors=True)


def wait_text(driver, selector, text):
    WebDriverWait(driver,8,ignored_exceptions=(StaleElementReferenceException,)).until(lambda d:text in d.find_element(By.CSS_SELECTOR,selector).text)


def apply_browser_command(app, operation, deck):
    """Provide a worker observation after verifying the browser's durable intent.

    Real engine behavior is covered by the independent Liquidsoap audio proof.
    """
    import time
    for _ in range(50):
        with app.app_context():
            if LiveControlCommand.query.filter_by(status='pending').first():break
        time.sleep(.1)
    with app.app_context():
        command=LiveControlCommand.query.filter_by(status='pending').one()
        assert command.action=='DECK_'+operation and command.deck==deck
        snapshot=LiveQueueSnapshot.query.first();mixer=dict(snapshot.mixer);key=deck.lower()
        if operation=='LOAD':
            target=command.target_decision;target.status='queued';target.socket_identity='test';target.liquidsoap_request_id=target.id
            mixer[key+'_id']=target.id;mixer[key+'_playing']=command.play_on_load
            if command.play_on_load:
                target.status='started';target.started_at=datetime.now(timezone.utc);snapshot.current_decision_id=target.id
        elif operation=='PLAY':
            mixer[key+'_playing']=True;mixer[('b' if key=='a' else 'a')+'_playing']=False
            row=db.session.get(SelectionDecision,mixer[key+'_id']);row.status='started';row.started_at=datetime.now(timezone.utc)
            snapshot.current_decision_id=row.id
        elif operation=='PAUSE':mixer[key+'_playing']=False;snapshot.current_decision_id=None
        elif operation in ('CLEAR','FADE'):
            row=db.session.get(SelectionDecision,mixer[key+'_id'])
            if row.status=='queued':row.status='failed'
            # The engine clears future requests too; mirror the worker's
            # reconciliation so a queued repeat cannot appear as a ready deck.
            SelectionDecision.query.filter_by(station_id=command.station_id,
                playback_bus=deck,status='queued').update({'status':'failed','reason':'request_not_started'})
            mixer[key+'_id']=None;mixer[key+'_playing']=False;snapshot.current_decision_id=None
        elif operation=='REPEAT':command.target_decision.status='queued'
        command.status='sent';snapshot.mixer=mixer;snapshot.observed_at=datetime.now(timezone.utc);db.session.commit()


def test_picker_load_clear_and_artwork_drag(booth):
    app,driver,base,tmp_path=booth
    assert not driver.find_elements(By.ID,'broadcast-fader')
    assert not driver.find_element(By.CSS_SELECTOR,'.up-next').is_displayed()
    assert not any(button.is_displayed() for button in driver.find_elements(By.CSS_SELECTOR,'[data-queue-track]'))
    assert driver.find_element(By.ID,'booth-cue-list').is_displayed()
    driver.find_elements(By.CSS_SELECTOR,'.cue-picker-button')[1].click()
    driver.find_element(By.ID,'song-picker-search').send_keys('Verified Test')
    wait_text(driver,'#song-picker-results','Verified Test Track')
    driver.find_element(By.CSS_SELECTOR,'#song-picker-results button').click()
    wait_text(driver,'#booth-notice','Deck command requested')
    apply_browser_command(app,'LOAD','B')
    wait_text(driver,'#cue-title','Verified Test Track');wait_text(driver,'#deck-b-state','READY')
    for preview in ('A','B'):
        driver.find_element(By.CSS_SELECTOR,'[data-monitor-station="test-station"] button').click()
        WebDriverWait(driver,8).until(lambda d:d.execute_script('return !FreoMonitor.audio.paused'))
        button=driver.find_element(By.CSS_SELECTOR,f'[data-preview-deck="{preview}"]');button.click()
        WebDriverWait(driver,8).until(lambda d:d.execute_script('return !document.getElementById("cue-monitor").paused && FreoMonitor.audio.paused'))
        WebDriverWait(driver,8).until(lambda d:button.text=='STOP PREVIEW')
        button.click()
        assert driver.execute_script('return document.getElementById("cue-monitor").paused')
    driver.find_element(By.CSS_SELECTOR,'[data-deck="B"][data-operation="CLEAR"]').click()
    wait_text(driver,'#booth-notice','Deck command requested');apply_browser_command(app,'CLEAR','B')
    wait_text(driver,'#cue-title','NOTHING LOADED')
    artwork=driver.find_element(By.CSS_SELECTOR,'.song-art');deck=driver.find_element(By.ID,'cue-drop')
    ActionChains(driver).move_to_element(artwork).click_and_hold().move_to_element(deck).pause(.2).release().perform()
    wait_text(driver,'#booth-notice','Deck command requested');apply_browser_command(app,'LOAD','B')
    wait_text(driver,'#cue-title','Verified Test Track')
    for width in (430,820,1440):
        driver.set_window_size(width,1000)
        assert driver.execute_script('return document.documentElement.scrollWidth<=document.documentElement.clientWidth')


def test_button_actions_are_scoped_and_dj_queue_is_absent(booth):
    app,driver,base,tmp_path=booth
    for operation in ('PAUSE','PLAY','REPEAT','FADE'):
        selector=f'[data-deck="A"][data-operation="{operation}"]'
        WebDriverWait(driver,8).until(lambda d:d.find_element(By.CSS_SELECTOR,selector).is_enabled())
        driver.find_element(By.CSS_SELECTOR,selector).click()
        WebDriverWait(driver,8).until(lambda d:d.find_element(By.ID,'booth-notice').text.startswith('Deck command requested'))
        apply_browser_command(app,operation,'A')
        if operation in ('PAUSE','PLAY'):wait_text(driver,'#deck-a-state','PAUSED' if operation=='PAUSE' else 'LIVE')
    # Wait for the browser to observe the completed fade. Until its next
    # status poll, Load remains disabled while the command is pending.
    wait_text(driver,'#deck-a-state','EMPTY')
    (tmp_path/'media'/'test-station'/'originals'/('a'*32+'.mp3')).unlink()
    load_b = WebDriverWait(driver,8).until(lambda d: (button := d.find_element(By.CSS_SELECTOR,'[data-load-deck="B"]')).is_enabled() and button)
    load_b.click()
    wait_text(driver,'#booth-notice','The song audio is unavailable')
    with app.app_context():
        assert not LiveControlCommand.query.filter_by(deck='B').count()
    driver.find_element(By.CSS_SELECTOR,'.mode-button[data-mode="AUTO"]').click()
    WebDriverWait(driver,8).until(lambda d:d.find_element(By.CSS_SELECTOR,'.auto-status').is_displayed())
    assert not driver.find_element(By.CSS_SELECTOR,'.lower-stage').is_displayed()


def open_import(driver, base):
    driver.get(base+'/admin/stations/test-station/media/upload')
    WebDriverWait(driver, 8).until(lambda d:d.find_elements(By.CSS_SELECTOR, 'dialog.freo-dialog[open]') or d.execute_script("return !!document.querySelector('.drop-zone').ondrop"))
    dialogs = driver.find_elements(By.CSS_SELECTOR, 'dialog.freo-dialog[open]')
    if dialogs:
        dialogs[0].find_element(By.CSS_SELECTOR, '.admin-primary').click()
    WebDriverWait(driver, 8).until(lambda d:d.execute_script("return !!document.querySelector('.drop-zone').ondrop"))


def test_file_picker_and_drop_import_results(booth):
    app,driver,base,tmp_path=booth
    open_import(driver, base)
    # Snap Chromium has a private /tmp namespace.
    browser_tmp=Path('/tmp/snap-private-tmp/snap.chromium/tmp')
    upload_dir=Path(tempfile.mkdtemp(prefix='freo-upload-',dir=browser_tmp if browser_tmp.exists() else tmp_path))
    audio=upload_dir/'picked.mp3';audio.write_bytes(b'fixture upload')
    browser_audio=Path('/tmp')/upload_dir.name/audio.name if browser_tmp.exists() else audio
    driver.find_element(By.ID,'media-file').send_keys(str(browser_audio))
    wait_text(driver,'#selected-files','picked.mp3')
    wait_text(driver,'.import-card:last-child','Uploaded')
    shutil.rmtree(upload_dir)
    with app.app_context():assert MusicImportItem.query.count()==1 and MediaIngestJob.query.count()==0
    driver.execute_script("const data=new DataTransfer();data.items.add(new File(['drop audio'],'dropped.mp3',{type:'audio/mpeg'}));document.querySelector('.drop-zone').dispatchEvent(new DragEvent('drop',{dataTransfer:data,bubbles:true,cancelable:true}));")
    wait_text(driver,'.import-card:last-child','Uploaded')
    with app.app_context():assert MusicImportItem.query.count()==2
    driver.refresh()
    WebDriverWait(driver,8).until(lambda d:len(d.find_elements(By.CSS_SELECTOR,'.import-card'))==2)
    wait_text(driver,'#selected-files','dropped.mp3')


def test_recursive_folder_drop_and_cancelled_song_drag(booth):
    app,driver,base,tmp_path=booth
    card=driver.find_element(By.CSS_SELECTOR,'.song-card b')
    ActionChains(driver).move_to_element(card).click_and_hold().move_by_offset(20,0).perform()
    driver.execute_script("document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}))")
    ActionChains(driver).release().perform()
    assert not driver.find_elements(By.CSS_SELECTOR,'.pointer-drag-ghost,.drop-active')
    with app.app_context():assert not Station.query.filter_by(slug='test-station').first().automation.cued_track
    open_import(driver, base)
    WebDriverWait(driver, 8).until(lambda d:d.execute_script("return !!document.querySelector('.drop-zone').ondrop"))
    driver.execute_script("""
      const file={isFile:true,file:resolve=>resolve(new File(['folder song'],'nested.mp3',{type:'audio/mpeg'}))};
      const directory={isDirectory:true,createReader:()=>{let read=false;return {readEntries:resolve=>{resolve(read?[]:[file]);read=true;}}}};
      const event=new Event('drop',{bubbles:true,cancelable:true});
      Object.defineProperty(event,'dataTransfer',{value:{items:[{kind:'file',webkitGetAsEntry:()=>directory}],files:[],types:['Files']}});
      document.querySelector('.drop-zone').dispatchEvent(event);
    """)
    wait_text(driver,'#selected-files','nested.mp3')
    wait_text(driver,'.import-card:last-child','Uploaded')
    with app.app_context():assert MusicImportItem.query.one().original_filename=='nested.mp3'




def test_drop_replaces_ready_deck_and_confirms_live_replacement(booth):
    app,driver,base,tmp_path=booth
    wait_text(driver,'#deck-a-state','LIVE')
    def drop(deck):
        ActionChains(driver).move_to_element(driver.find_element(By.CSS_SELECTOR,'.song-art')).click_and_hold().move_to_element(driver.find_element(By.ID,deck)).pause(.2).release().perform()
    drop('cue-drop');wait_text(driver,'#booth-notice','Deck command requested')
    apply_browser_command(app,'LOAD','B');wait_text(driver,'#deck-b-state','READY')
    with app.app_context():first=LiveControlCommand.query.order_by(LiveControlCommand.id.desc()).first().target_decision_id
    drop('cue-drop');wait_text(driver,'#booth-notice','Deck command requested')
    assert not driver.find_elements(By.CSS_SELECTOR,'.freo-dialog[open]')
    apply_browser_command(app,'LOAD','B')
    with app.app_context():
        command=LiveControlCommand.query.order_by(LiveControlCommand.id.desc()).first()
        assert command.target_decision_id!=first and not command.play_on_load
    # Wait for the newly prepared request to be observed before the next drop.
    WebDriverWait(driver,8).until(lambda d:d.find_element(By.CSS_SELECTOR,'[data-deck="B"][data-operation="PLAY"]').is_enabled())
    drop('now-drop')
    wait_text(driver,'.freo-dialog h2','Replace and go live')
    driver.find_element(By.CSS_SELECTOR,'.freo-dialog .dialog-actions button').click()
    with app.app_context():assert not LiveControlCommand.query.filter_by(status='pending').count()
    driver.execute_script("const input=document.getElementById('deck-fade-seconds');input.value='5.5';input.dispatchEvent(new Event('input',{bubbles:true}))")
    drop('now-drop');wait_text(driver,'.freo-dialog h2','Replace and go live')
    driver.find_element(By.CSS_SELECTOR,'.freo-dialog .admin-primary').click()
    wait_text(driver,'#booth-notice','Deck command requested')
    with app.app_context():
        command=LiveControlCommand.query.filter_by(status='pending').one()
        assert command.play_on_load and command.fade_seconds==5.5
    apply_browser_command(app,'LOAD','A');wait_text(driver,'#deck-a-state','LIVE')
    for width in (1600,820,390):
        driver.set_window_size(width,1000)
        for deck in ('A','B'):
            button=driver.find_element(By.CSS_SELECTOR,f'[data-deck="{deck}"][data-operation="PLAY"]')
            row=driver.find_element(By.CSS_SELECTOR,f'.transport-row[data-deck="{deck}"]')
            assert abs(button.rect['width']-row.rect['width'])<2
        assert driver.execute_script('return document.documentElement.scrollWidth<=document.documentElement.clientWidth')
    driver.save_screenshot('/tmp/freo-deck-controls.png')


def test_program_and_persistent_monitor_meters(booth):
    app,driver,base,tmp_path=booth
    with app.app_context():
        LiveQueueSnapshot.query.first().program_rms=.1;db.session.commit()
    WebDriverWait(driver,8).until(lambda d:d.execute_script("return document.getElementById('program-left').value>.5"))
    driver.find_element(By.CSS_SELECTOR,'[data-monitor-station="test-station"] button').click()
    WebDriverWait(driver,10).until(lambda d:d.execute_script("return document.getElementById('monitor-left').value>.3 && document.getElementById('monitor-right').value>.3"))
    driver.find_element(By.CSS_SELECTOR,'[data-monitor-station="test-station"] button').click()
    WebDriverWait(driver,8).until(lambda d:d.execute_script("return document.getElementById('monitor-left').value===0 && document.getElementById('monitor-right').value===0"))


def test_decks_stay_symmetric_and_show_live_and_transition_edges(booth):
    app,driver,base,tmp_path=booth
    wait_text(driver,'[data-deck="A"][data-operation="PLAY"]','LIVE')
    live=driver.find_element(By.CSS_SELECTOR,'[data-deck="A"][data-operation="PLAY"]')
    assert live.value_of_css_property('opacity')=='1'
    assert driver.find_element(By.ID,'cue-artist').text==''
    assert driver.find_element(By.ID,'cue-album').text==''
    assert driver.find_element(By.ID,'deck-b-message').text==''
    with app.app_context():
        track=Track.query.first();track.title='An exceptionally long title that wraps onto multiple lines and still keeps both decks aligned'
        cue=SelectionDecision(station_id=track.station_id,track=track,playback_bus='B',status='queued',selection_method='manual_track')
        db.session.add(cue);db.session.flush()
        snapshot=LiveQueueSnapshot.query.first();snapshot.mixer=dict(snapshot.mixer,b_id=cue.id,b_playing=False,b_elapsed=11)
        db.session.commit();cue_id=cue.id
    wait_text(driver,'#deck-b-state','READY');wait_text(driver,'#b-elapsed','0:0:00')
    for width in (1600,1100,820,390):
        driver.set_window_size(width,1200)
        a=driver.find_element(By.ID,'now-drop').rect;b=driver.find_element(By.ID,'cue-drop').rect
        header=driver.find_element(By.CSS_SELECTOR,'.booth-header').rect
        assert abs(header['y']-driver.find_element(By.ID,'dj-booth').rect['y'])<1
        assert a['y']>=header['y']+header['height']
        bar=driver.find_element(By.ID,'booth-notice').rect
        assert bar['y']>=header['y']+header['height']
        assert 0<=a['y']-bar['y']-bar['height']<25
        assert abs(a['height']-b['height'])<1 and abs(a['width']-b['width'])<1
        buttons=[driver.find_element(By.CSS_SELECTOR,f'[data-deck="{deck}"][data-operation="PLAY"]').rect for deck in ('A','B')]
        assert abs((buttons[0]['y']-a['y'])-(buttons[1]['y']-b['y']))<1
        if width>650:assert abs(buttons[0]['y']-buttons[1]['y'])<1
        fade=driver.find_element(By.CSS_SELECTOR,'.deck-transition').rect
        assert fade['y']>=max(a['y']+a['height'],b['y']+b['height'])
        meters=driver.find_element(By.CSS_SELECTOR,'.meter-rack').rect
        assert meters['y']>=fade['y']+fade['height']
        driver.execute_script("const n=document.getElementById('booth-notice');n.hidden=false;n.textContent='Deck command requested'")
        assert driver.find_element(By.ID,'now-drop').rect['y']==a['y']
        assert driver.find_element(By.CSS_SELECTOR,'.meter-rack').rect['y']==meters['y']
        driver.execute_script("document.getElementById('booth-notice').textContent='Broadcast online'")
        assert driver.execute_script('return document.documentElement.scrollWidth<=document.documentElement.clientWidth')
    driver.set_window_size(1600,1200)
    driver.save_screenshot('/tmp/freo-booth-heading-decks-first.png')
    driver.find_element(By.CSS_SELECTOR,'.deck-workspace').screenshot('/tmp/freo-decks-ready.png')
    with app.app_context():
        cue=db.session.get(SelectionDecision,cue_id);cue.status='started';cue.started_at=datetime.now(timezone.utc)
        snapshot=LiveQueueSnapshot.query.first();snapshot.mixer=dict(snapshot.mixer,b_playing=True,transition=dict(incoming='B',progress=.4,a_gain=.6,b_gain=.4));db.session.commit()
    wait_text(driver,'[data-deck="B"][data-operation="PLAY"]','GOING LIVE')
    assert driver.execute_script("return getComputedStyle(document.getElementById('cue-drop'),'::before').animationName==='deck-fade-ice'")
    assert 'is-incoming' in driver.find_element(By.ID,'cue-drop').get_attribute('class')
    assert 'is-incoming' not in driver.find_element(By.ID,'now-drop').get_attribute('class')
    driver.find_element(By.CSS_SELECTOR,'.deck-workspace').screenshot('/tmp/freo-decks-fading.png')
    with app.app_context():
        snapshot=LiveQueueSnapshot.query.first();snapshot.mixer=dict(snapshot.mixer,a_playing=False,transition=dict(incoming=None,progress=1,a_gain=0,b_gain=1));db.session.commit()
    WebDriverWait(driver,8).until(lambda d:d.find_element(By.CSS_SELECTOR,'[data-deck="B"][data-operation="PLAY"]').text=='LIVE')
    assert driver.execute_script("return getComputedStyle(document.getElementById('cue-drop'),'::before').animationName==='deck-live-fire'")
    driver.find_element(By.CSS_SELECTOR,'.deck-workspace').screenshot('/tmp/freo-decks-live.png')
    driver.execute_cdp_cmd('Emulation.setEmulatedMedia',{'features':[{'name':'prefers-reduced-motion','value':'reduce'}]})
    assert driver.execute_script("return getComputedStyle(document.getElementById('cue-drop'),'::before').animationName==='none'")


def test_drop_resets_position_before_worker_observation(booth):
    app,driver,base,tmp_path=booth
    with app.app_context():
        snapshot=LiveQueueSnapshot.query.first();snapshot.mixer=dict(snapshot.mixer,a_playing=False,a_elapsed=5);db.session.commit()
    wait_text(driver,'#deck-a-state','PAUSED');wait_text(driver,'#elapsed','0:0:05')
    artwork=driver.find_element(By.CSS_SELECTOR,'.song-art');deck=driver.find_element(By.ID,'now-drop')
    ActionChains(driver).move_to_element(artwork).click_and_hold().move_to_element(deck).pause(.2).release().perform()
    wait_text(driver,'#deck-a-state','LOADING');wait_text(driver,'#elapsed','0:0:00')
    assert not driver.find_elements(By.CSS_SELECTOR,'.freo-dialog[open]')
    apply_browser_command(app,'LOAD','A')
    # The fixture deliberately retains the previous engine elapsed value.
    wait_text(driver,'#deck-a-state','READY');wait_text(driver,'#elapsed','0:0:00')
    assert driver.find_element(By.ID,'time-progress').value_of_css_property('width')=='0px'


@pytest.mark.parametrize('deck', ['A', 'B'])
def test_paused_load_completes_before_engine_reports_current_id(booth, deck):
    app,driver,base,tmp_path=booth
    key=deck.lower()
    with app.app_context():
        snapshot=LiveQueueSnapshot.query.first()
        snapshot.mixer=dict(snapshot.mixer, **{key+'_playing':False})
        db.session.commit()
    wait_text(driver,f'#deck-{key}-state','PAUSED' if deck=='A' else 'EMPTY')
    driver.find_element(By.CSS_SELECTOR,f'[data-load-deck="{deck}"]').click()
    wait_text(driver,f'#deck-{key}-state','LOADING')
    # LOADING is optimistic; wait for the request to reach the server.
    def command_received(_):
        with app.app_context():
            return LiveControlCommand.query.filter_by(status='pending').count() == 1
    WebDriverWait(driver, 8).until(command_received)
    with app.app_context():
        command=LiveControlCommand.query.filter_by(status='pending').one()
        assert command.deck==deck and not command.play_on_load
        target=command.target_decision;target.status='queued'
        target.socket_identity='test';target.liquidsoap_request_id=target.id
        command.status='sent';command.processed_at=datetime.now(timezone.utc)
        snapshot=LiveQueueSnapshot.query.first()
        snapshot.mixer=dict(snapshot.mixer, **{key+'_id':None,key+'_elapsed':147.24,key+'_playing':False})
        db.session.commit()
    wait_text(driver,f'#deck-{key}-state','READY')
    wait_text(driver,'#elapsed' if deck=='A' else '#b-elapsed','0:0:00')
    play=driver.find_element(By.CSS_SELECTOR,f'[data-deck="{deck}"][data-operation="PLAY"]')
    assert play.is_enabled() and play.text=='PLAY / TAKE AIR'
    play.click()
    wait_text(driver,'#booth-notice','Deck command requested')
    with app.app_context():
        command=LiveControlCommand.query.filter_by(status='pending').one()
        assert command.deck==deck and command.action=='DECK_PLAY'


def test_auto_return_popup_for_manual_switch_and_stopped_music(booth):
    from app.services.live_assist import return_to_schedule
    app,driver,base,tmp_path=booth
    with app.app_context():
        snapshot=LiveQueueSnapshot.query.first()
        snapshot.mixer=dict(snapshot.mixer,transition=dict(incoming=None,progress=1,a_gain=1,b_gain=0))
        db.session.commit()
    wait_text(driver,'#deck-a-state','LIVE')
    driver.find_element(By.CSS_SELECTOR,'[data-mode="AUTO"]').click()
    wait_text(driver,'.freo-dialog h2','Returning to Auto')
    wait_text(driver,'.freo-dialog p','3-second crossfade')
    assert [b.text for b in driver.find_elements(By.CSS_SELECTOR,'.freo-dialog button')]==['OK']
    driver.find_element(By.CSS_SELECTOR,'.freo-dialog button').click()
    driver.find_element(By.CSS_SELECTOR,'[data-mode="DJ_BOOTH"]').click()
    WebDriverWait(driver,8).until(lambda d:d.find_element(By.ID,'dj-booth').get_attribute('data-mode')=='DJ_BOOTH')
    with app.app_context():
        return_to_schedule(Station.query.filter_by(slug='test-station').one(),reason='DJ music stopped. Returning to the schedule in Auto mode.')
    wait_text(driver,'.freo-dialog p','DJ music stopped')
    driver.find_element(By.CSS_SELECTOR,'.freo-dialog button').click()
    driver.refresh()
    WebDriverWait(driver,8).until(lambda d:d.find_element(By.ID,'dj-booth').get_attribute('data-mode')=='AUTO')
    assert not driver.find_elements(By.CSS_SELECTOR,'.freo-dialog[open]')


def test_dj_standby_shows_empty_decks_and_auto_on_air(booth):
    app,driver,base,tmp_path=booth
    with app.app_context():
        snapshot=LiveQueueSnapshot.query.first()
        snapshot.mixer=dict(snapshot.mixer,auto_standby=True,auto_id=snapshot.current_decision_id,auto_gain=1,a_id=None,a_playing=False)
        db.session.commit()
    wait_text(driver,'#deck-a-state','EMPTY');wait_text(driver,'#deck-b-state','EMPTY')
    wait_text(driver,'#led-detail','AUTO ON AIR · DJ READY')
    wait_text(driver,'#morph-text','Verified Test Track')
    driver.find_element(By.CSS_SELECTOR,'[data-load-deck="A"]').click()
    wait_text(driver,'#deck-a-state','LOADING')
    apply_browser_command(app,'LOAD','A')
    wait_text(driver,'#deck-a-state','READY')
    wait_text(driver,'#deck-b-state','EMPTY')
    wait_text(driver,'#led-detail','AUTO ON AIR · DJ READY')
    wait_text(driver,'#elapsed','0:0:00')
