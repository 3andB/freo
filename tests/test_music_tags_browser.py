"""Exercise optimistic saves, rollback, management, and shared row controls."""
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from app.extensions import db
from app.models import Track, MusicTag
from app.services.music_tags import seed_starter_tags
from app.services.music_catalog import organize_song
from tests.test_live_browser import booth, wait_text
from tests.test_web import app as app_fixture


def test_quick_toggles_management_and_album(booth):
    app, driver, base, tmp_path = booth
    import subprocess
    audio = tmp_path / "media" / "test-station" / "originals" / ("a" * 32 + ".mp3")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=30", str(audio)], check=True)
    with app.app_context():
        song = Track.query.first()
        seed_starter_tags(song.station_id)
        organize_song(song)
        db.session.commit()
        album_id = song.album_id
    driver.get(base + '/admin/stations/test-station/media')
    wait_text(driver, '#room-songs', 'HIT')
    driver.find_element(By.CSS_SELECTOR, '.room-song .preview-button').click()
    WebDriverWait(driver, 8).until(lambda d: d.execute_script('return !document.getElementById("music-audio").paused'))
    driver.find_element(By.CSS_SELECTOR, '.room-song input').click()
    driver.execute_script('''
      window.pageMarker = 123;
      const original = FreoPage.fetch.bind(FreoPage);
      FreoPage.fetch = async (...args) => {await new Promise(r => setTimeout(r, 100));return original(...args);};
      const buttons = [...document.querySelectorAll('.room-song [data-kind=tag]')];
      const hit = buttons.find(b => b.textContent.includes('HIT'));
      const chill = buttons.find(b => b.textContent.includes('CHILL'));
      hit.click();hit.click();hit.click();chill.click();
      window.optimistic = hit.getAttribute('aria-pressed') === 'true' && chill.getAttribute('aria-pressed') === 'true';
    ''')
    assert driver.execute_script('return window.optimistic')
    WebDriverWait(driver, 10).until(lambda d: not d.execute_script('return FreoMusicToggles.pending'))
    with app.app_context():
        assert {tag.name for tag in Track.query.first().tags} == {'HIT', 'CHILL'}
    assert driver.execute_script('return !document.getElementById("music-audio").paused')
    assert driver.execute_script('return window.pageMarker === 123 && document.querySelector(".room-song input").checked')
    driver.execute_script('''
      const original = FreoPage.fetch.bind(FreoPage);
      FreoPage.fetch = async (...args) => {FreoPage.fetch = original;throw Error('Connection lost. Try again.');};
      [...document.querySelectorAll('.room-song [data-kind=tag]')].find(b => b.textContent.includes('HIT')).click();
    ''')
    wait_text(driver, '.toggle-status', 'Connection lost')
    assert driver.execute_script('return [...document.querySelectorAll(".room-song [data-kind=tag]")].find(b => b.textContent.includes("HIT")).getAttribute("aria-pressed")') == 'true'
    driver.find_element(By.CSS_SELECTOR, '.room-song [data-kind=category]').click()
    WebDriverWait(driver, 10).until(lambda d: not d.execute_script('return FreoMusicToggles.pending'))
    with app.app_context():assert not Track.query.first().categories
    driver.set_window_size(430, 932)
    assert driver.execute_script('return document.documentElement.scrollWidth <= innerWidth')
    driver.execute_script('document.querySelector(".music-toggles").scrollIntoView({block: "center"})')
    driver.save_screenshot('/tmp/freo-tags-mobile.png')
    driver.set_window_size(1600, 1200)
    driver.find_element(By.LINK_TEXT, 'Tags').click()
    wait_text(driver, '#tag-manager', 'Create tag')
    form = driver.find_element(By.ID, 'tag-create')
    form.find_element(By.NAME, 'name').send_keys('ROAD TRIP')
    form.find_element(By.NAME, 'description').send_keys('Open road songs')
    form.find_element(By.CSS_SELECTOR, 'button').click()
    wait_text(driver, '#tag-status', 'Tag saved')
    with app.app_context():
        tag = MusicTag.query.filter_by(name='ROAD TRIP').one();tag_id = tag.id
        assert tag.description == 'Open road songs'
    card = driver.find_element(By.CSS_SELECTOR, f'[data-tag-id="{tag_id}"]')
    name = card.find_element(By.NAME, 'name');name.clear();name.send_keys('TRAVEL')
    card.find_element(By.CSS_SELECTOR, 'button[type=submit]').click()
    WebDriverWait(driver, 8).until(lambda d: not d.find_element(By.CSS_SELECTOR, f'[data-tag-id="{tag_id}"] button').get_attribute('disabled'))
    with app.app_context():assert db.session.get(MusicTag, tag_id).name == 'TRAVEL'
    card.find_element(By.CSS_SELECTOR, '[data-delete-tag]').click()
    driver.find_element(By.CSS_SELECTOR, '.freo-dialog .admin-primary').click()
    wait_text(driver, '#tag-status', 'deleted')
    with app.app_context():assert db.session.get(MusicTag, tag_id) is None
    driver.get(base + f'/admin/stations/test-station/media/albums/{album_id}')
    driver.find_element(By.CSS_SELECTOR, '.music-toggles [data-kind=category]').click()
    wait_text(driver, '.toggle-status', 'Saved')
    with app.app_context():assert len(Track.query.first().categories) == 1
    driver.save_screenshot('/tmp/freo-tags-album.png')
