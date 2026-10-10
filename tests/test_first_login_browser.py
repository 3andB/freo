"""Real Chrome + production config on non-localhost names: HTTP and TLS setup."""
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import shutil
import pytest
from werkzeug.serving import make_server
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from app import create_app
from app.extensions import db
from app.services.admin_setup import bootstrap
from app.services.installation_settings import import_environment


@pytest.mark.parametrize('scheme',['http','https'])
def test_fresh_production_first_login_logout_and_restart(tmp_path,monkeypatch,scheme):
    monkeypatch.setenv('FREO_ENV_FILE','/dev/null')
    monkeypatch.setenv('DATABASE_URL','sqlite:///'+str(tmp_path/'browser.sqlite'))
    monkeypatch.setenv('SECRET_KEY','isolated-browser-test-only')
    monkeypatch.setenv('FREO_MEDIA_ROOT',str(tmp_path/'media'))
    app=create_app('production')
    (tmp_path/'uploads').mkdir()
    app.config['FREO_UPLOAD_ROOT']=str(tmp_path/'uploads')
    tls=None
    if scheme == 'https':
        cert,key=tmp_path/'cert.pem',tmp_path/'key.pem'
        subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-keyout',str(key),'-out',str(cert),'-days','1','-subj','/CN=freo-test.invalid','-addext','subjectAltName=DNS:freo-test.invalid'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        tls=(str(cert),str(key))
    server=make_server('127.0.0.1',0,app,threaded=True,ssl_context=tls)
    base=f'{scheme}://freo-test.invalid:{server.server_port}'
    app.config['PUBLIC_BASE_URL']=base
    with app.app_context():
        db.create_all(); import_environment(); assert bootstrap()
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    profile=tempfile.mkdtemp(prefix='freo-first-login-',dir='/tmp')
    options=Options()
    options.binary_location=os.environ.get('FREO_TEST_CHROME','/usr/bin/chromium-browser')
    for arg in ['--headless=new','--no-sandbox','--disable-dev-shm-usage','--window-size=1440,1000','--no-proxy-server','--ignore-certificate-errors','--host-resolver-rules=MAP freo-test.invalid 127.0.0.1',f'--user-data-dir={profile}']: options.add_argument(arg)
    driver=None
    try:
        driver=webdriver.Chrome(service=Service(os.environ.get('FREO_TEST_CHROMEDRIVER','/usr/bin/chromedriver')),options=options)
        def sign_in(password):
            driver.get(base+'/admin/login')
            driver.find_element(By.NAME,'email').send_keys('admin')
            driver.find_element(By.NAME,'password').send_keys(password)
            # A second tab and signed-out admin polling must not invalidate
            # the form already filled in the first tab.
            login_tab = driver.current_window_handle
            driver.switch_to.new_window('tab')
            driver.get(base+'/admin/login')
            statuses = driver.execute_async_script("""
                const done = arguments[0];
                Promise.all(['/admin/api/broadcast-status',
                    '/admin/api/stations/1/live-status'].map(path =>
                    fetch(path).then(response => response.status)))
                    .then(done).catch(() => done([]));
            """)
            assert statuses == [200, 200]
            driver.close()
            driver.switch_to.window(login_tab)
            driver.find_element(By.CSS_SELECTOR,'.login-card button[type=submit]').click()
        sign_in('IAmOnTheAir')
        WebDriverWait(driver,15).until(lambda d:d.current_url==base+'/admin/setup')
        cookie=driver.get_cookie('session')
        assert cookie['secure'] is (scheme=='https')
        driver.get(base+'/admin/software')
        assert driver.current_url==base+'/admin/setup'
        driver.find_element(By.NAME,'email').send_keys('owner@example.test')
        for name in ('password','confirmation'):
            driver.find_element(By.NAME,name).send_keys('private browser fixture passphrase')
        driver.find_element(By.CSS_SELECTOR,'.login-card button[type=submit]').click()
        WebDriverWait(driver,15).until(lambda d:d.current_url==base+'/admin')
        assert driver.find_elements(By.CSS_SELECTOR,'.admin-sidebar')
        driver.find_element(By.CSS_SELECTOR,'#license-accept-form input[name=agree]').click()
        driver.find_element(By.CSS_SELECTOR,'#license-accept-form button[type=submit]').click()
        WebDriverWait(driver,10).until(lambda d:not d.find_element(By.ID,'license-agreement').is_displayed())
        from tests.rc5_browser_workflow import first_station_workflow
        first_station_workflow(app, driver, base, tmp_path)
        driver.find_element(By.CSS_SELECTOR,'form[action="/admin/logout"] button').click()
        WebDriverWait(driver,10).until(lambda d:d.current_url==base+'/')
        sign_in('IAmOnTheAir')
        WebDriverWait(driver,15).until(lambda d:'was not accepted' in d.page_source)
        # Recreate the application/server against the same DB to simulate process restart.
        server.shutdown();server.server_close();thread.join(timeout=5)
        replacement=create_app('production')
        replacement.config['FREO_UPLOAD_ROOT']=str(tmp_path/'uploads')
        with replacement.app_context():
            assert not bootstrap()
            from app.models import Station, Track
            assert Station.query.filter_by(slug='1').count() == 1
            assert Track.query.count() == 2
        server=make_server('127.0.0.1',int(base.rsplit(':',1)[1]),replacement,threaded=True,ssl_context=tls)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        sign_in('private browser fixture passphrase')
        WebDriverWait(driver,15).until(lambda d:d.current_url==base+'/admin')
        driver.get(base+'/')
        assert driver.get_cookie('session')['secure'] is (scheme=='https')
        driver.get(base+'/admin/software')
        WebDriverWait(driver,15).until(lambda d:'Software and license' in d.find_element(By.TAG_NAME,'body').text)
    finally:
        if driver: driver.quit()
        server.shutdown();server.server_close();thread.join(timeout=5)
        shutil.rmtree(profile,ignore_errors=True)
