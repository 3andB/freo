"""Rendered layout and management workflows on desktop and mobile."""
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from app.extensions import db
from app.models import Campaign
from tests.test_live_browser import booth, app_fixture
from tests.test_platform_polish_browser import seed_ads


def test_manager_surfaces_and_zero_space(booth):
    app,driver,base,tmp=booth
    seed_ads(app)
    driver.get(base+'/admin/stations/test-station/advertising')
    assert driver.find_element(By.CSS_SELECTOR,'h1').text=='Advertising'
    driver.find_element(By.LINK_TEXT,'Edit').click()
    WebDriverWait(driver,15).until(lambda d:not d.execute_script("return document.documentElement.classList.contains('is-navigating')") and d.find_elements(By.NAME,'name'))
    name=driver.find_element(By.NAME,'name');name.clear();name.send_keys('Local Sponsor')
    driver.find_element(By.CSS_SELECTOR,'.ad-editor-actions button').click()
    WebDriverWait(driver,15).until(lambda d:d.find_elements(By.CSS_SELECTOR,'.ad-campaign'))
    assert 'Local Sponsor' in driver.find_element(By.CSS_SELECTOR,'.ad-campaign').text
    driver.save_screenshot('/tmp/freo-advertising-manager-desktop.png')
    for width in (1440,390):
        driver.set_window_size(width,1000)
        driver.get(base+'/admin/stations/test-station/advertising')
        assert driver.execute_script('return document.documentElement.scrollWidth<=innerWidth')
        driver.save_screenshot('/tmp/freo-advertising-manager-'+str(width)+'.png')
        driver.get(base+'/player/test-station')
        WebDriverWait(driver,8).until(lambda d:d.find_element(By.CSS_SELECTOR,'.phase9-ad').is_displayed())
        assert driver.execute_script("return [...document.querySelectorAll('.phase9-ad[hidden]')].every(e=>e.getBoundingClientRect().height===0)")
        assert driver.execute_script('return document.documentElement.scrollWidth<=innerWidth')
        driver.find_element(By.ID,'visualizer-open').click()
        WebDriverWait(driver,8).until(lambda d:d.find_element(By.CSS_SELECTOR,'#visualizer-dialog .phase9-ad').is_displayed())
        assert driver.find_element(By.ID,'player-visual').is_displayed()
        driver.find_element(By.ID,'visualizer-close').click()
        driver.get(base+'/')
        WebDriverWait(driver,8).until(lambda d:d.find_element(By.CSS_SELECTOR,'.phase9-ad').is_displayed())
    driver.get(base+'/player/test-station')
    WebDriverWait(driver,8).until(lambda d:d.find_element(By.CSS_SELECTOR,'.phase9-ad').is_displayed())
    with app.app_context():
        c=Campaign.query.one();c.advertising=dict(c.advertising,active=False);db.session.commit()
    # Returning to a long-lived player triggers eligibility revalidation.
    driver.execute_script("document.dispatchEvent(new Event('visibilitychange'))")
    WebDriverWait(driver,8).until(lambda d:d.execute_script("return [...document.querySelectorAll('.phase9-ad')].every(e=>e.getBoundingClientRect().height===0)"))
    assert driver.find_element(By.ID,'play-button').is_displayed()
