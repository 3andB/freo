"""Real browser recording, upload, AI production and responsive UI in /tmp."""
import os
from cryptography.fernet import Fernet
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select, WebDriverWait
from app import models as m
from app.extensions import db
from app.services import production_providers as provider, production_worker as worker
from tests.test_live_browser import booth, app_fixture
from tests.test_production import fixture_audio

BASE='/admin/stations/test-station/production'


def test_record_in_browser_preview_and_save_to_station(booth,monkeypatch):
    app,driver,base,folder=booth
    root=folder/'production';root.mkdir();app.config['FREO_PRODUCTION_ROOT']=str(root)
    monkeypatch.setattr('app.services.media.require_ingest_identity',lambda:None)
    monkeypatch.setattr(os,'chown',lambda *args:None)
    monkeypatch.setattr('grp.getgrnam',lambda _:type('Group',(),{'gr_gid':os.getgid()})())
    monkeypatch.setattr('pwd.getpwnam',lambda _:type('User',(),{'pw_uid':os.getuid()})())
    with app.app_context():m.Track.query.update({'analysis_status':'complete'});db.session.commit()
    driver.get(base+BASE)
    driver.find_element(By.CSS_SELECTOR,'#production-create [name=title]').send_keys('Morning link')
    driver.find_element(By.CSS_SELECTOR,'#production-create button').click()
    WebDriverWait(driver,10).until(lambda d:d.find_element(By.ID,'production-title').text=='Morning link')
    # Exercise actual MediaRecorder output using a deterministic microphone source.
    driver.execute_script("""window.testAudio=new AudioContext();const osc=testAudio.createOscillator();
      const dest=testAudio.createMediaStreamDestination();osc.connect(dest);osc.start();
      navigator.mediaDevices.getUserMedia=async()=>dest.stream;""")
    driver.find_element(By.ID,'record-start').click()
    WebDriverWait(driver,5).until(lambda d:d.find_element(By.ID,'record-stop').is_enabled())
    driver.execute_async_script('setTimeout(arguments[0],1200)')
    driver.find_element(By.ID,'record-stop').click()
    WebDriverWait(driver,5).until(lambda d:d.find_element(By.ID,'record-upload').is_enabled())
    driver.find_element(By.ID,'record-upload').click()
    def pending():
        with app.app_context():return m.ProductionAttempt.query.filter_by(status='pending').count()>0
    WebDriverWait(driver,10).until(lambda d:pending())
    with app.app_context():assert worker.process_one()
    WebDriverWait(driver,10).until(lambda d:len(d.find_elements(By.CSS_SELECTOR,'#component-previews audio'))==2)
    driver.find_element(By.CSS_SELECTOR,'[data-action=save] button').click()
    WebDriverWait(driver,10).until(lambda d:pending())
    with app.app_context():
        assert worker.process_one()
        from app.ingest_worker import process_one
        assert process_one()
        from app.services.analysis_queue import process_analysis
        assert process_analysis()
        worker.reconcile()
        record=m.ProductionDraft.query.one()
        assert record.state=='saved',record.error
        assert record.track.audio_kind=='STATION'
    WebDriverWait(driver,10).until(lambda d:'saved' in d.find_element(By.ID,'production-state').text)
    driver.set_window_size(390,844)
    assert driver.execute_script('return document.documentElement.scrollWidth <= innerWidth')
    driver.execute_script("document.getElementById('production-editor').scrollIntoView()")
    driver.save_screenshot(str(folder/'voice-track-mobile.png'))
    driver.execute_script('testAudio.close()')


def test_script_generation_voice_music_effects_and_save(booth,monkeypatch):
    app,driver,base,folder=booth
    root=folder/'production';root.mkdir();app.config.update(FREO_PRODUCTION_ROOT=str(root),FREO_PROVIDER_ENCRYPTION_KEY=Fernet.generate_key().decode())
    raw=fixture_audio(folder)
    monkeypatch.setattr(provider,'models',lambda:[dict(id='test-model',name='Test voice model',style=True,similarity=True)])
    monkeypatch.setattr(provider,'voices',lambda *a:dict(voices=[dict(id='voice',name='Radio voice',preview=True)],cursor=None))
    monkeypatch.setattr(provider,'write_script',lambda *a:('You are listening to KXYZ.',{'input_tokens':12}))
    monkeypatch.setattr(provider,'call',lambda *a,**kw:(raw,{'character-cost':'10'}))
    with app.app_context():
        station=m.Station.query.first();db.session.add(m.StationProduction(station_id=station.id,enabled=True,script_provider='openai',model_id='test-model'))
        for name in ('openai','elevenlabs'):provider.save_credential(name,'test-secret-key','model',0)
        db.session.commit()
    driver.get(base+BASE)
    driver.find_element(By.CSS_SELECTOR,'#production-create [name=title]').send_keys('KXYZ <station ID>')
    Select(driver.find_element(By.CSS_SELECTOR,'#production-create [name=mode]')).select_by_value('ai')
    driver.find_element(By.CSS_SELECTOR,'#production-create button').click()
    WebDriverWait(driver,10).until(lambda d:d.find_element(By.ID,'production-title').text=='KXYZ <station ID>')
    def finish(action):
        def pending():
            with app.app_context():return m.ProductionAttempt.query.filter_by(action=action,status='pending').count()>0
        WebDriverWait(driver,10).until(lambda d:pending())
        with app.app_context():assert worker.process_one()
        WebDriverWait(driver,10).until(lambda d:action+' · complete' in d.find_element(By.ID,'production-history').text)
    driver.find_element(By.CSS_SELECTOR,'[data-action=script] [name=prompt]').send_keys('Rock station ID for KXYZ')
    driver.find_element(By.CSS_SELECTOR,'[data-action=script] button').click();finish('script')
    assert driver.find_element(By.CSS_SELECTOR,'[data-action=voice] [name=script]').get_attribute('value')=='You are listening to KXYZ.'
    driver.find_element(By.ID,'voice-find').click()
    WebDriverWait(driver,10).until(lambda d:d.find_elements(By.CSS_SELECTOR,'#voice-select option[value=voice]'))
    driver.find_element(By.CSS_SELECTOR,'[data-action=voice] button').click();finish('voice')
    for action,prompt in [('bed','Rock instrumental'),('fx','Whoosh')]:
        driver.find_element(By.CSS_SELECTOR,f'[data-action={action}] [name=prompt]').send_keys(prompt)
        driver.find_element(By.CSS_SELECTOR,f'[data-action={action}] button').click();finish(action)
    driver.find_element(By.CSS_SELECTOR,'[data-action=render] button').click();finish('render')
    assert len(driver.find_elements(By.CSS_SELECTOR,'#component-previews audio'))==4
    driver.find_element(By.CSS_SELECTOR,'[data-action=save] button').click();finish('save')
    with app.app_context():
        assert m.ProductionDraft.query.one().state=='ingesting'
        assert m.MediaIngestJob.query.one().import_metadata['audio_kind']=='STATION'
    driver.set_window_size(390,844)
    assert driver.execute_script('return document.documentElement.scrollWidth <= innerWidth')
    driver.execute_script("document.getElementById('production-editor').scrollIntoView()")
    driver.save_screenshot(str(folder/'station-imaging-mobile.png'))
