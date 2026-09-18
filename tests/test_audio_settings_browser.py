from datetime import datetime, timedelta, timezone
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from app.extensions import db
from app.models import AdminUser, MediaIngestJob, Station, MusicImportItem
from tests.test_live_browser import booth, wait_text, open_import
from tests.test_web import app as app_fixture


def test_daily_notice_cancel_and_all_file_extensions(booth):
    app, driver, base, tmp_path = booth
    driver.get(base + '/admin/stations/test-station/media/upload')
    dialog = WebDriverWait(driver, 8).until(lambda d:d.find_element(By.CSS_SELECTOR, 'dialog.freo-dialog[open]'))
    assert 'legally authorized' in dialog.text
    driver.save_screenshot('/tmp/freo-import-notice.png')
    dialog.find_element(By.XPATH, ".//button[text()='Cancel']").click()
    WebDriverWait(driver, 8).until(lambda d:d.current_url.endswith('/media'))
    with app.app_context(): assert MediaIngestJob.query.count() == 0
    open_import(driver, base)
    assert not driver.find_elements(By.CSS_SELECTOR, 'dialog[open]')
    driver.execute_script("""
      const data=new DataTransfer();
      for(const name of ['song.WAV','song.M4A','song.MP3','song.FLAC','bad.txt'])data.items.add(new File(['fixture'],name));
      document.getElementById('media-file').files=data.files;
      document.getElementById('media-file').dispatchEvent(new Event('change',{bubbles:true}));
    """)
    wait_text(driver, '#selection-summary', '4 selected')
    cards = driver.find_elements(By.CSS_SELECTOR, '.import-card')
    assert len(cards) == 4
    assert 'non-audio' in driver.find_element(By.ID,'import-message').text
    WebDriverWait(driver, 10).until(lambda d:sum('Uploaded' in card.text for card in d.find_elements(By.CSS_SELECTOR, '.import-card')) == 4)
    with app.app_context():
        assert MusicImportItem.query.count() == 4 and MediaIngestJob.query.count() == 0
        AdminUser.query.first().import_notice_date = datetime.now(timezone.utc).date() - timedelta(days=1)
        db.session.commit()
    driver.get(base + '/admin/stations/second-station/media/upload')
    WebDriverWait(driver, 8).until(lambda d:d.find_element(By.CSS_SELECTOR, 'dialog.freo-dialog[open]'))
    # Navigating away disposes the modal without a second redirect from Cancel.
    driver.execute_script("FreoWorkspace.navigate('/admin/stations/second-station/media')")
    WebDriverWait(driver, 8).until(lambda d:d.current_url.endswith('/second-station/media') and not d.find_elements(By.CSS_SELECTOR, 'dialog[open]'))


def test_audio_settings_queue_and_status_in_browser(booth):
    app, driver, base, tmp_path = booth
    driver.get(base + '/admin/stations/test-station/settings')
    from selenium.webdriver.support.ui import Select
    Select(driver.find_element(By.CSS_SELECTOR, '#audio-settings [name=bitrate]')).select_by_value('128')
    for name in ('agc','multiband','eq'):
        element=driver.find_element(By.CSS_SELECTOR, f'#audio-settings [name={name}]')
        driver.execute_script('arguments[0].scrollIntoView({block:"center"})', element);element.click()
    field=driver.find_element(By.CSS_SELECTOR, '#audio-settings [name=bass]');field.clear();field.send_keys('2')
    button=driver.find_element(By.CSS_SELECTOR, '#audio-settings button[type=submit]')
    driver.execute_script('arguments[0].scrollIntoView({block:"center"})', button);button.click()
    wait_text(driver, '#audio-settings-status', 'pending')
    with app.app_context():
        stream=Station.query.filter_by(slug='test-station').one().stream
        assert stream.bitrate == 64 and stream.pending_audio['bitrate'] == 128 and stream.pending_audio['bass'] == 2
        assert stream.pending_audio['agc'] and stream.pending_audio['eq'] and stream.pending_audio['multiband']
        stream.audio_status='failed';stream.audio_error='Previous settings retained.';db.session.commit()
    wait_text(driver, '#audio-settings-status', 'Previous settings retained.')
    assert driver.find_element(By.CSS_SELECTOR, '#audio-settings button[type=submit]').is_enabled()
    for width in (390, 820, 1440):
        driver.set_window_size(width, 1100)
        assert driver.execute_script('return document.documentElement.scrollWidth <= innerWidth')
    driver.execute_script("document.getElementById('audio-settings').scrollIntoView({block:'start'})")
    driver.save_screenshot('/tmp/freo-audio-settings.png')
