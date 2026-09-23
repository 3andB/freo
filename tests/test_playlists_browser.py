"""Owner workflow through Music, the playlist editor, and the calendar."""
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.common.exceptions import StaleElementReferenceException
from app.extensions import db
from app.models import Station, Playlist, ChannelSchedule
from app.services.playlists import seed_playlists
from tests.test_live_browser import booth, wait_text
from tests.test_web import app as app_fixture


def test_playlist_music_bubbles_editor_undo_and_schedule(booth):
    app,driver,base,tmp_path=booth
    with app.app_context():
        station=Station.query.filter_by(slug='test-station').one();seed_playlists(station.id);db.session.commit()
    driver.get(base+'/admin/stations/test-station/media')
    wait_text(driver,'#room-playlists','Playlist 1')
    bubble='.room-song .music-toggle[data-kind=playlist]'
    driver.find_element(By.CSS_SELECTOR,bubble).click()
    WebDriverWait(driver,8).until(lambda d:not d.execute_script('return FreoMusicToggles.pending'))
    assert driver.find_element(By.CSS_SELECTOR,bubble).get_attribute('aria-pressed')=='true'
    driver.find_element(By.CSS_SELECTOR,'#room-playlists .destination-name').click()
    wait_text(driver,'#playlist-songs','Verified Test Track')
    name=driver.find_element(By.CSS_SELECTOR,'#playlist-form [name=name]');name.clear();name.send_keys('Friday Drive')
    Select(driver.find_element(By.CSS_SELECTOR,'#playlist-form [name=mode]')).select_by_value('RANDOM')
    driver.find_element(By.CSS_SELECTOR,'#playlist-form button[type=submit]').click()
    wait_text(driver,'#playlist-list','Friday Drive')
    driver.find_element(By.CSS_SELECTOR,'.playlist-song .preview-button').click()
    WebDriverWait(driver,8).until(lambda d:d.execute_script('return !document.getElementById("music-audio").paused'))
    driver.find_element(By.CSS_SELECTOR,'.playlist-song button[aria-label^="Remove"]').click()
    wait_text(driver,'#playlist-count','0 songs')
    driver.find_element(By.ID,'playlist-undo').click()
    wait_text(driver,'#playlist-count','1 songs')
    driver.find_element(By.ID,'playlist-add').click()
    wait_text(driver,'#playlist-results','Verified Test Track')
    assert driver.find_element(By.CSS_SELECTOR,'#playlist-results button[aria-label^="Add"]').get_attribute('disabled')
    driver.find_element(By.CSS_SELECTOR,'#playlist-source-form button').click()
    wait_text(driver,'#playlist-add-status','0 song(s)')
    driver.find_element(By.CSS_SELECTOR,'#playlist-add-dialog .dialog-close').click()
    driver.set_window_size(430,932)
    assert driver.execute_script('return document.documentElement.scrollWidth <= innerWidth')
    driver.save_screenshot('/tmp/freo-playlists-mobile.png')
    driver.set_window_size(1600,1200)
    driver.save_screenshot('/tmp/freo-playlists.png')
    driver.get(base+'/admin/stations/test-station/calendar')
    driver.find_element(By.XPATH,"//nav[@id='source-tabs']/button[text()='Playlists']").click()
    wait_text(driver,'#source-results','Friday Drive')
    driver.find_element(By.CSS_SELECTOR,'button[aria-label="Add Friday Drive"]').click()
    driver.find_element(By.CSS_SELECTOR,'#section-form button[type=submit]').click()
    WebDriverWait(driver,8).until(lambda d:not d.find_element(By.ID,'section-inspector').is_displayed())
    wait_text(driver,'#save-state','Saved')
    with app.app_context():
        row=Playlist.query.filter_by(name='Friday Drive').one();assert row.mode=='RANDOM' and len(row.items)==1
        assert any(item['source']['kind']=='playlist' and item['source']['id']==row.id for item in ChannelSchedule.query.one().calendar)


def test_playlist_reorder_and_music_drag(booth):
    from selenium.webdriver.common.action_chains import ActionChains
    from tests.test_playlists import setup_playlist
    app,driver,base,tmp_path=booth
    with app.app_context():
        station,row,songs=setup_playlist();identifier=row.id;ids=[song.uuid for song in songs]
    driver.get(base+f'/admin/stations/test-station/playlists?playlist={identifier}')
    wait_text(driver,'#playlist-count','4 songs')
    driver.find_element(By.CSS_SELECTOR,'.playlist-song button[aria-label$="down"]').click()
    WebDriverWait(driver,8,ignored_exceptions=(StaleElementReferenceException,)).until(lambda d:d.find_element(By.CSS_SELECTOR,'.playlist-song').get_attribute('data-song')==ids[1])
    rows=driver.find_elements(By.CSS_SELECTOR,'.playlist-song')
    ActionChains(driver).drag_and_drop(rows[0].find_element(By.CSS_SELECTOR,'.playlist-grip'),rows[2]).perform()
    WebDriverWait(driver,8,ignored_exceptions=(StaleElementReferenceException,)).until(lambda d:d.find_elements(By.CSS_SELECTOR,'.playlist-song')[2].get_attribute('data-song')==ids[1])
    driver.get(base+'/admin/stations/test-station/media')
    wait_text(driver,'#room-songs','Verified Test Track')
    source=driver.find_element(By.CSS_SELECTOR,'.song-row-copy b')
    target=driver.find_elements(By.CSS_SELECTOR,'[data-drop-kind=playlist]')[1]
    ActionChains(driver).move_to_element(source).click_and_hold().move_to_element(target).pause(.2).release().perform()
    wait_text(driver,'#room-message-text','1 song(s) updated · Playlist 2')
    with app.app_context():
        assert [item.track.uuid for item in db.session.get(Playlist,identifier).items]==[ids[0],ids[2],ids[1],ids[3]]
        assert len(Playlist.query.filter_by(name='Playlist 2').one().items)==1
