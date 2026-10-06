import json
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from tests.test_live_browser import booth
from tests.test_web import app as app_fixture


def test_broadcast_pages_and_pwa_offline_on_mobile_and_desktop(booth):
    app,driver,base,tmp_path=booth
    for width in (1440,390):
        driver.set_window_size(width,1000)
        for path,label in [('broadcast-reports','Broadcast Reports'),('external-bulletins','External Bulletin'),('settings','Freo Broadcast Processor')]:
            driver.get(base+'/admin/stations/test-station/'+path)
            WebDriverWait(driver,10).until(lambda d:label in d.find_element(By.TAG_NAME,'body').text)
            assert driver.execute_script('return document.documentElement.scrollWidth<=innerWidth+1')
    driver.get(base+'/admin/stations/test-station/broadcast-reports')
    driver.set_script_timeout(15)
    assert driver.execute_async_script('const done=arguments[0];navigator.serviceWorker.ready.then(r=>done(r.scope));').endswith('/admin/')
    driver.refresh()
    WebDriverWait(driver,10).until(lambda d:d.execute_script('return !!navigator.serviceWorker.controller'))
    driver.execute_cdp_cmd('Network.enable',{})
    driver.execute_cdp_cmd('Network.setCacheDisabled',{'cacheDisabled':True})
    target=next(t for t in driver.execute_cdp_cmd('Target.getTargets',{})['targetInfos'] if t['type']=='service_worker')
    session=driver.execute_cdp_cmd('Target.attachToTarget',{'targetId':target['targetId'],'flatten':False})['sessionId']
    def worker_network(identifier, offline):
        driver.execute_cdp_cmd('Target.sendMessageToTarget',{'sessionId':session,'message':json.dumps(dict(id=identifier,method='Network.emulateNetworkConditions',params=dict(offline=offline,latency=0,downloadThroughput=0 if offline else -1,uploadThroughput=0 if offline else -1)))})
    driver.execute_cdp_cmd('Target.sendMessageToTarget',{'sessionId':session,'message':json.dumps(dict(id=1,method='Network.enable',params={}))})
    worker_network(2,True)
    driver.execute_cdp_cmd('Network.emulateNetworkConditions',dict(offline=True,latency=0,downloadThroughput=0,uploadThroughput=0))
    try:
        driver.get(base+'/admin/stations/test-station/settings')
        assert 'You’re offline' in driver.find_element(By.TAG_NAME,'body').text
        assert not driver.find_elements(By.CSS_SELECTOR,'form')
    finally:
        worker_network(3,False)
        driver.execute_cdp_cmd('Network.emulateNetworkConditions',dict(offline=False,latency=0,downloadThroughput=-1,uploadThroughput=-1))
    driver.get(base+'/admin/stations/test-station/settings')
    assert driver.find_element(By.NAME,'preset').is_displayed()
