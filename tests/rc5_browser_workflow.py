"""First-station acceptance shared by the real HTTP and HTTPS setup tests."""
import base64
import subprocess

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

from app.extensions import db
from app.models import MusicImportItem, Station, Track


def first_station_workflow(app, driver, base, tmp_path):
    wait = WebDriverWait(driver, 15)
    # localhost is treated as secure by Chrome; this must use the mapped hostname.
    assert driver.execute_script('return isSecureContext') is base.startswith('https:')
    if base.startswith('http:'):
        assert driver.execute_script('return typeof crypto.randomUUID') == 'undefined'
    values = driver.execute_script('return Array.from({length:100},()=>FreoUUID())')
    from uuid import UUID
    assert len(set(values)) == 100 and all(UUID(value).version == 4 for value in values)

    assert not driver.find_elements(By.CSS_SELECTOR, '[data-monitor-station]')
    form = driver.find_element(By.CSS_SELECTOR, 'form[action="/admin/stations/create"]')
    form.find_element(By.NAME, 'name').send_keys('First radio')
    form.find_element(By.NAME, 'slug').send_keys('1')
    form.find_element(By.CSS_SELECTOR, 'button').click()
    wait.until(lambda d: d.find_elements(By.CSS_SELECTOR, '[data-monitor-station="1"]'))
    monitor = '[data-monitor-station="1"]'
    assert driver.find_element(By.CSS_SELECTOR, monitor + ' button').is_displayed()
    assert not driver.find_element(By.CSS_SELECTOR, monitor + ' button').is_enabled()
    assert 'Preparing' in driver.find_element(By.CSS_SELECTOR, monitor).text
    wait.until(lambda d: not d.execute_script('return document.documentElement.classList.contains("is-navigating")'))
    driver.find_element(By.CSS_SELECTOR, 'a[href$="/1/schedule-studio/control"]').click()
    wait.until(lambda d: d.find_elements(By.ID, 'master-broadcast-toggle'))
    assert not driver.find_element(By.ID, 'master-broadcast-toggle').is_enabled()
    # UI observation only. Real rendering and audio are tested as the service user
    # by the separate isolated engine acceptance test.
    with app.app_context():
        station = Station.query.filter_by(slug='1').one()
        station.lifecycle_state = 'ready'
        db.session.commit()
    wait.until(lambda d: d.find_element(By.ID, 'master-broadcast-toggle').is_enabled())
    wait.until(lambda d: d.find_element(By.CSS_SELECTOR, monitor + ' button').is_enabled())
    assert 'Ready when you are' in driver.find_element(By.ID, 'broadcast-hint').text
    assert driver.find_element(By.ID, 'master-broadcast-toggle').text == 'OFF'
    wait.until(lambda d: not d.execute_script('return document.documentElement.classList.contains("is-navigating")'))

    # Navigate within the workspace, not just driver.get() for every page.
    driver.find_element(By.CSS_SELECTOR, '.admin-nav a[href*="section/media"], .admin-nav a[href*="/admin/media"], .admin-nav a[href*="/admin/section/media"]').click()
    wait.until(lambda d: d.find_elements(By.CSS_SELECTOR, 'a[href$="/media/upload"]'))
    wait.until(lambda d: not d.execute_script('return document.documentElement.classList.contains("is-navigating")'))
    driver.find_element(By.CSS_SELECTOR, 'a[href$="/media/upload"]').click()
    wait.until(lambda d: d.find_elements(By.CSS_SELECTOR, '.freo-dialog[open]'))
    driver.find_element(By.CSS_SELECTOR, '.freo-dialog .admin-primary').click()
    wait.until(lambda d: d.find_elements(By.ID, 'choose-files') and d.execute_script('return !!document.getElementById("choose-files").onclick'))
    assert not driver.execute_script('return document.getElementById("media-upload-form").inert')
    driver.execute_cdp_cmd('Page.setInterceptFileChooserDialog', {'enabled': True})
    driver.execute_script('window.pickerClicks=0;document.getElementById("media-file").addEventListener("click",()=>pickerClicks++)')
    driver.find_element(By.ID, 'choose-files').click()
    wait.until(lambda d: d.execute_script('return pickerClicks') == 1)
    label = driver.find_element(By.CSS_SELECTOR, '.drop-zone b')
    driver.execute_script('arguments[0].scrollIntoView({block:"center"})', label)
    label.click()
    wait.until(lambda d: d.execute_script('return pickerClicks') == 2)

    for index in (1, 2):
        audio = tmp_path / f'first-song-{index}.mp3'
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                        f'sine=frequency={400+index}:duration=2', '-metadata',
                        f'title=First song {index}', '-metadata', 'artist=Test artist', '-y', str(audio)], check=True)
        if index == 1:
            driver.find_element(By.ID, 'media-file').send_keys(str(audio))
        else:
            driver.execute_script('''const bytes=Uint8Array.from(atob(arguments[0]),c=>c.charCodeAt(0));
              const data=new DataTransfer();data.items.add(new File([bytes],arguments[1],{type:'audio/mpeg'}));
              document.querySelector('.drop-zone').dispatchEvent(new DragEvent('drop',{bubbles:true,dataTransfer:data}));''',
                                  base64.b64encode(audio.read_bytes()).decode(), audio.name)
        def uploaded(_):
            with app.app_context():
                return MusicImportItem.query.count() == index
        wait.until(uploaded)
    with app.app_context():
        from app.services.import_sessions import prepare_one
        while prepare_one():
            pass
    wait.until(lambda d: 'Import 2 ready songs' in d.find_element(By.CSS_SELECTOR, '#media-upload-form [type=submit]').text)
    submit = driver.find_element(By.CSS_SELECTOR, '#media-upload-form [type=submit]')
    driver.execute_script('arguments[0].scrollIntoView({block:"center"})', submit)
    submit.click()
    wait.until(lambda d: 'Import started' in d.find_element(By.ID, 'import-message').text)
    with app.app_context():
        from app.ingest_worker import process_one
        while process_one():
            pass
        songs = Track.query.order_by(Track.id).all()
        assert len(songs) == 2 and all(song.ingest_status == 'accepted' for song in songs)
    wait.until(lambda d: 'Imported' in d.find_element(By.CSS_SELECTOR, '.import-card:last-child').text)
    # A completed import is available from the workspace selector; the default
    # importer URL intentionally opens a new workspace after completion.
    workspace = driver.find_element(By.ID, 'import-sessions').get_attribute('value')
    driver.get(base+'/admin/stations/1/media/upload?import_session='+workspace)
    wait.until(lambda d: len(d.find_elements(By.CSS_SELECTOR, '.import-card')) == 2)
    driver.refresh()
    wait.until(lambda d: len(d.find_elements(By.CSS_SELECTOR, '.import-card')) == 2)
    assert driver.find_element(By.CSS_SELECTOR, monitor + ' button').is_displayed()
    for width in (390, 820, 1440):
        driver.set_window_size(width, 1100)
        assert driver.find_element(By.CSS_SELECTOR, monitor + ' button').is_displayed()
        assert driver.execute_script('return document.documentElement.scrollWidth <= innerWidth+1')
    driver.get(base + '/admin')
