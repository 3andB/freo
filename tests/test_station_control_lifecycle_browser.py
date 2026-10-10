"""A retired Control page must discard both late bodies and late errors."""
import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from tests.test_live_browser import booth, app_fixture
from tests.test_workspace_lifecycle_browser import navigate

@pytest.mark.parametrize('result',['success','error'])
@pytest.mark.parametrize('return_first',[False,True])
def test_control_body_completion_after_navigation_is_discarded(booth,result,return_first):
    _,driver,base,_=booth
    wait=WebDriverWait(driver,20)
    control=base+'/admin/stations/test-station/schedule-studio/control'
    live=base+'/admin/stations/test-station/live'
    navigate(driver,control)
    wait.until(lambda d:d.find_elements(By.ID,'station-control'))
    driver.execute_script('''
      window.pageErrors=[];
      window.addEventListener('unhandledrejection',e=>pageErrors.push(String(e.reason)));
      window.addEventListener('error',e=>pageErrors.push(e.message));
      const scope=FreoPage,original=scope.fetch.bind(scope);
      scope.fetch=async(url,options)=>{
        const response=await original(url,options);
        if(!String(url).endsWith('/api/state'))return response;
        const payload=await response.json();payload.mode='BLOCKS';
        return {ok:true,json:()=>new Promise((resolve,reject)=>{
          window.releaseOldControlBody=()=>arguments[0]==='error'
            ?reject(new Error('Delayed old Control error')):resolve(payload);
        })};
      };
    ''',result)
    wait.until(lambda d:d.execute_script('return !!window.releaseOldControlBody'))
    navigate(driver,live)
    if return_first:
        navigate(driver,control)
        wait.until(lambda d:d.find_elements(By.ID,'station-control'))
        before=driver.find_element(By.ID,'control-status-heading').text
    driver.execute_async_script('releaseOldControlBody();setTimeout(arguments[0],150)')
    assert driver.execute_script('return pageErrors')==[]
    if return_first:
        assert driver.find_element(By.ID,'control-status-heading').text==before
    else:
        assert driver.find_elements(By.ID,'dj-booth')
