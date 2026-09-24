from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from app.models import Station, LiveControlCommand
from tests.test_live_browser import booth, app_fixture
import copy
import time
import pytest
from app.extensions import db


def test_live_mic_board_preserves_feed_and_shares_carts(booth):
    app, driver, base, tmp_path = booth
    driver.find_element(By.ID, 'mic-tab').click()
    WebDriverWait(driver, 5).until(lambda d: d.find_element(By.ID,'mic-heading').is_displayed())
    assert driver.find_element(By.CSS_SELECTOR,'.cart-console').is_displayed()
    assert driver.find_element(By.CSS_SELECTOR,'.station-id-console').is_displayed()
    assert not driver.find_element(By.CSS_SELECTOR,'.deck-workspace').is_displayed()
    assert not driver.find_element(By.ID,'mic-go').is_enabled()
    with app.app_context():
        assert Station.query.filter_by(slug='test-station').one().automation.operator_mode == 'DJ_BOOTH'
        assert LiveControlCommand.query.count() == 0
    # Polling the engine must not replace the selected board.
    driver.execute_script("document.getElementById('mic-gain').value=6; document.getElementById('mic-gain').dispatchEvent(new Event('input'))")
    assert driver.find_element(By.ID,'mic-gain-value').text == '+6 dB'
    driver.set_window_size(390,844)
    assert driver.execute_script('return document.documentElement.scrollWidth<=innerWidth')
    driver.save_screenshot('/tmp/freo-live-mic-mobile.png')
    driver.set_window_size(1600,1200)
    driver.save_screenshot('/tmp/freo-live-mic-desktop.png')
    driver.find_element(By.CSS_SELECTOR,'button[data-mode=DJ_BOOTH]').click()
    WebDriverWait(driver,5).until(lambda d:not d.find_element(By.ID,'mic-heading').is_displayed())


def test_denied_microphone_permission_never_enables_go_live(booth, monkeypatch):
    app, driver, base, tmp_path = booth
    monkeypatch.setattr('app.services.live_mic.enabled', lambda: True)
    monkeypatch.setattr('app.routes.live_mic.gateway', lambda *args, **kwargs: {'phase':'OFF AIR'})
    driver.refresh()
    driver.find_element(By.ID,'mic-tab').click()
    driver.execute_script("navigator.mediaDevices.getUserMedia=async()=>{throw new DOMException('Microphone permission denied','NotAllowedError');}")
    driver.find_element(By.ID,'mic-connect').click()
    WebDriverWait(driver,5).until(lambda d:'permission denied' in d.find_element(By.ID,'mic-message').text)
    assert not driver.find_element(By.ID,'mic-go').is_enabled()
    assert driver.find_element(By.ID,'mic-connect').is_enabled()
    with app.app_context():
        assert Station.query.filter_by(slug='test-station').one().automation.operator_mode == 'DJ_BOOTH'
        assert LiveControlCommand.query.count() == 0


def connected_mic(booth, monkeypatch, *, go=True):
    app, driver, base, tmp_path = booth
    state={'phase':'OFF AIR'}
    calls=[]
    def gateway(slug, action, **data):
        calls.append(action)
        if action=='config':return {'iceServers':[]}
        if action=='offer':
            state.update(phase='READY', desired='READY', ready=True, healthy=True, owner=1)
            return {'token':'a'*32,'sdp':'fixture','type':'answer'}
        if action=='go':state.update(phase='LIVE', desired='LIVE')
        if action=='disconnect':
            state.update(phase='RETURNING', desired='END', leaving=True, until=time.monotonic()+.5)
        if action in ('status','heartbeat') and state.get('until',float('inf'))<time.monotonic():
            state.clear();state.update(phase='OFF AIR')
        return copy.deepcopy(state)
    monkeypatch.setattr('app.services.live_mic.enabled', lambda: True)
    monkeypatch.setattr('app.services.live_mic.gateway', gateway)
    monkeypatch.setattr('app.routes.live_mic.gateway', gateway)
    driver.refresh()
    # Real browser AudioContext/MediaStream tracks, with isolated signaling.
    # Real WebRTC and rendered audio have independent engine tests.
    driver.execute_script("""
      window.micFixtureContext=new AudioContext();
      const osc=micFixtureContext.createOscillator(), output=micFixtureContext.createMediaStreamDestination();
      osc.connect(output);osc.start();window.micFixtureTrack=output.stream.getAudioTracks()[0];
      navigator.mediaDevices.getUserMedia=async()=>output.stream;
      window.RTCPeerConnection=class {
        constructor(){this.iceGatheringState='complete';}
        addTrack(){} async createOffer(){return {type:'offer',sdp:'fixture'};}
        async setLocalDescription(value){this.localDescription=value;}
        async setRemoteDescription(){} close(){}
      };
    """)
    driver.find_element(By.ID,'mic-tab').click()
    driver.find_element(By.ID,'mic-connect').click()
    wait=WebDriverWait(driver,10)
    wait.until(lambda d:d.find_element(By.ID,'mic-go').is_enabled())
    if go:
        driver.find_element(By.ID,'mic-go').click()
        wait.until(lambda d:d.find_element(By.ID,'mic-state').text=='ON AIR')
    return state,calls


@pytest.mark.parametrize('mode',['AUTO','DJ_BOOTH'])
def test_mode_switch_stops_capture_and_waits_for_return(booth, monkeypatch, mode):
    app,driver,_,_=booth
    state,calls=connected_mic(booth,monkeypatch)
    driver.find_element(By.CSS_SELECTOR,f'button[data-mode="{mode}"]').click()
    assert driver.find_element(By.ID,'dj-booth').get_attribute('data-board')=='LIVE_MIC'
    WebDriverWait(driver,10).until(lambda d:d.find_element(By.ID,'dj-booth').get_attribute('data-board')==mode)
    assert driver.execute_script('return micFixtureTrack.readyState')=='ended'
    assert state['phase']=='OFF AIR'
    assert calls.count('disconnect')==1
    with app.app_context():
        assert Station.query.filter_by(slug='test-station').one().automation.operator_mode==mode


def test_leave_warning_cancel_then_resume_previous_feed(booth, monkeypatch):
    app,driver,base,_=booth
    _,calls=connected_mic(booth,monkeypatch)
    driver.execute_script('FreoWorkspace.navigate(arguments[0])',base+'/admin/stations/test-station/media')
    wait=WebDriverWait(driver,10)
    wait.until(lambda d:d.find_elements(By.CSS_SELECTOR,'.freo-dialog[open]'))
    assert 'resume the previous program' in driver.find_element(By.CSS_SELECTOR,'.freo-dialog').text
    driver.find_element(By.CSS_SELECTOR,'.freo-dialog button:not(.admin-primary)').click()
    assert driver.current_url.endswith('/live')
    assert 'disconnect' not in calls
    assert driver.execute_script('return micFixtureTrack.readyState')=='live'
    driver.execute_script('FreoWorkspace.navigate(arguments[0],{submitted:true})',base+'/admin/stations/test-station/media')
    wait.until(lambda d:d.find_elements(By.CSS_SELECTOR,'.freo-dialog[open]'))
    driver.find_element(By.CSS_SELECTOR,'.freo-dialog .admin-primary').click()
    wait.until(lambda d:d.current_url.endswith('/media'))
    assert driver.execute_script('return micFixtureTrack.readyState')=='ended'
    assert calls.count('disconnect')==1
    with app.app_context():
        assert Station.query.filter_by(slug='test-station').one().automation.operator_mode=='DJ_BOOTH'


def test_signout_waits_for_mic_return(booth, monkeypatch):
    _,driver,base,_=booth
    state,calls=connected_mic(booth,monkeypatch)
    driver.find_element(By.CSS_SELECTOR,'form[action="/admin/logout"] button').click()
    wait=WebDriverWait(driver,10)
    wait.until(lambda d:d.find_elements(By.CSS_SELECTOR,'.freo-dialog[open]'))
    driver.find_element(By.CSS_SELECTOR,'.freo-dialog .admin-primary').click()
    wait.until(lambda d:d.current_url==base+'/')
    assert calls.count('disconnect')==1 and state['phase']=='OFF AIR'
    driver.get(base+'/admin/software')
    wait.until(lambda d:d.current_url.endswith('/admin/login') and d.find_elements(By.CSS_SELECTOR,'.login-card'))
    assert driver.current_url.endswith('/admin/login')


def test_back_cancel_restores_url_and_keeps_microphone_live(booth, monkeypatch):
    _,driver,base,_=booth
    _,calls=connected_mic(booth,monkeypatch)
    driver.execute_script("""
      const live=location.href;
      history.replaceState({freo:true},'',arguments[0]);
      history.pushState({freo:true},'',live);
      history.back();
    """,base+'/admin/stations/test-station/media')
    wait=WebDriverWait(driver,10)
    wait.until(lambda d:d.find_elements(By.CSS_SELECTOR,'.freo-dialog[open]'))
    driver.find_element(By.CSS_SELECTOR,'.freo-dialog button:not(.admin-primary)').click()
    wait.until(lambda d:d.current_url.endswith('/live'))
    assert 'disconnect' not in calls
    assert driver.execute_script('return micFixtureTrack.readyState')=='live'


@pytest.fixture
def native_prompts():
    """Ask the shared browser fixture to leave native beforeunload prompts open."""
    return True


def test_refresh_warning_and_pagehide_release(booth, monkeypatch, native_prompts):
    _,driver,_,_=booth
    _,calls=connected_mic(booth,monkeypatch)
    assert driver.execute_script("return !dispatchEvent(new Event('beforeunload',{cancelable:true}))")
    assert driver.execute_script('return navigator.userActivation.hasBeenActive')
    driver.execute_script('setTimeout(()=>location.reload(),100)')
    alert=WebDriverWait(driver,5).until(EC.alert_is_present())
    alert.dismiss()
    assert 'disconnect' not in calls
    assert driver.execute_script('return micFixtureTrack.readyState')=='live'
    driver.execute_script('setTimeout(()=>location.reload(),100)')
    WebDriverWait(driver,5).until(EC.alert_is_present()).accept()
    WebDriverWait(driver,10).until(lambda d:'disconnect' in calls and d.execute_script('return typeof micFixtureTrack')=='undefined')
    assert not driver.find_element(By.ID,'mic-go').is_enabled()


def test_failed_return_keeps_mic_view_and_blocks_mode_change(booth, monkeypatch):
    app,driver,_,_=booth
    _,calls=connected_mic(booth,monkeypatch)
    def unavailable(*args, **kwargs):raise ValueError('Fixture return unavailable')
    monkeypatch.setattr('app.routes.live_mic.gateway',unavailable)
    driver.find_element(By.CSS_SELECTOR,'button[data-mode="AUTO"]').click()
    WebDriverWait(driver,10).until(lambda d:'unavailable' in d.find_element(By.ID,'mic-message').text)
    assert driver.find_element(By.ID,'dj-booth').get_attribute('data-board')=='LIVE_MIC'
    assert driver.execute_script('return micFixtureTrack.readyState')=='ended'
    assert not driver.find_element(By.ID,'mic-connect').is_enabled()
    assert driver.find_element(By.ID,'mic-disconnect').is_enabled()
    with app.app_context():
        assert Station.query.filter_by(slug='test-station').one().automation.operator_mode=='DJ_BOOTH'
    # If the acknowledgement was lost, a later observed OFF AIR permits retry.
    monkeypatch.setattr('app.routes.live_mic.gateway',lambda *a,**k:{'phase':'OFF AIR'})
    monkeypatch.setattr('app.services.live_mic.gateway',lambda *a,**k:{'phase':'OFF AIR'})
    driver.find_element(By.CSS_SELECTOR,'button[data-mode="AUTO"]').click()
    WebDriverWait(driver,10).until(lambda d:d.find_element(By.ID,'dj-booth').get_attribute('data-board')=='AUTO')


def test_mode_switch_cancels_pending_permission_without_late_capture(booth, monkeypatch):
    _,driver,_,_=booth
    monkeypatch.setattr('app.services.live_mic.enabled',lambda:True)
    monkeypatch.setattr('app.services.live_mic.gateway',lambda *a,**k:{'phase':'OFF AIR'})
    monkeypatch.setattr('app.routes.live_mic.gateway',lambda *a,**k:{'phase':'OFF AIR'})
    driver.refresh()
    driver.execute_script("navigator.mediaDevices.getUserMedia=()=>new Promise(resolve=>window.allowMic=resolve)")
    driver.find_element(By.ID,'mic-tab').click()
    driver.find_element(By.ID,'mic-connect').click()
    wait=WebDriverWait(driver,10)
    wait.until(lambda d:d.execute_script('return !!window.allowMic'))
    driver.find_element(By.CSS_SELECTOR,'button[data-mode="AUTO"]').click()
    wait.until(lambda d:d.find_element(By.ID,'dj-booth').get_attribute('data-board')=='AUTO')
    driver.execute_script("""
      const context=new AudioContext(),output=context.createMediaStreamDestination();
      window.lateTrack=output.stream.getAudioTracks()[0];allowMic(output.stream);
    """)
    wait.until(lambda d:d.execute_script('return lateTrack.readyState')=='ended')
    assert not driver.find_element(By.ID,'mic-go').is_enabled()


def test_live_mic_logout_with_delayed_response_in_another_tab(booth, monkeypatch):
    """Another tab survives booth disposal and must not restore its login."""
    from threading import Event
    from flask import request as flask_request
    app,driver,base,_=booth
    state,calls=connected_mic(booth,monkeypatch)
    entered,release=Event(),Event()
    def hold_response(response):
        if flask_request.args.get('logout_race')=='held':
            entered.set()
            if not release.wait(30):
                raise RuntimeError('Test did not release its delayed response')
        return response
    app.after_request_funcs.setdefault(None,[]).append(hold_response)
    booth_tab=driver.current_window_handle
    wait=WebDriverWait(driver,10)
    try:
        driver.switch_to.new_window('tab')
        second_tab=driver.current_window_handle
        driver.get(base+'/')
        driver.execute_script("window.heldResponseDone=false;fetch('/admin/api/broadcast-status?logout_race=held').then(r=>r.text()).then(()=>window.heldResponseDone=true)")
        assert entered.wait(10)
        driver.switch_to.window(booth_tab)
        driver.find_element(By.CSS_SELECTOR,'form[action="/admin/logout"] button').click()
        wait.until(lambda d:d.find_elements(By.CSS_SELECTOR,'.freo-dialog[open]'))
        # Cancellation must keep both authentication and microphone ownership.
        driver.find_element(By.CSS_SELECTOR,'.freo-dialog button:not(.admin-primary)').click()
        assert driver.execute_script('return micFixtureTrack.readyState')=='live'
        assert 'disconnect' not in calls
        driver.find_element(By.CSS_SELECTOR,'form[action="/admin/logout"] button').click()
        wait.until(lambda d:d.find_elements(By.CSS_SELECTOR,'.freo-dialog[open]'))
        driver.find_element(By.CSS_SELECTOR,'.freo-dialog .admin-primary').click()
        wait.until(lambda d:d.current_url==base+'/')
        assert calls.count('disconnect')==1 and state['phase']=='OFF AIR'
        release.set()
        driver.switch_to.window(second_tab)
        wait.until(lambda d:d.execute_script('return window.heldResponseDone===true'))
        for tab in (second_tab,booth_tab):
            driver.switch_to.window(tab)
            driver.get(base+'/admin/software')
            wait.until(lambda d:d.current_url.endswith('/admin/login') and d.find_elements(By.CSS_SELECTOR,'.login-card'))
            assert not driver.find_elements(By.CSS_SELECTOR,'.admin-sidebar')
    finally:
        release.set()
        app.after_request_funcs[None].remove(hold_response)
