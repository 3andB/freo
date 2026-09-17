"""Responsive station homepage and owner publishing in a real browser."""
import base64
from pathlib import Path
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait, Select
from tests.test_live_browser import booth, app_fixture


def viewport(driver,width,height=1000):
    driver.execute_cdp_cmd('Emulation.setDeviceMetricsOverride',dict(width=width,height=height,deviceScaleFactor=1,mobile=False))


def test_station_homepage_responsive_and_without_javascript(booth):
    app,driver,base,tmp_path=booth
    driver.get('about:blank');driver.delete_all_cookies();driver.get(base+'/')
    wait=WebDriverWait(driver,12)
    wait.until(lambda d:d.find_elements(By.CSS_SELECTOR,'.station-header.enhanced'))
    for width in (360,390,768,1024,1440):
        viewport(driver,width)
        for theme in ('day','night'):
            if driver.execute_script('return document.body.dataset.siteTheme')!=theme:
                driver.find_element(By.CSS_SELECTOR,'.site-theme-toggle').click()
            assert driver.execute_script('return document.documentElement.scrollWidth<=innerWidth+1'),(width,theme)
            assert len(driver.find_elements(By.CSS_SELECTOR,'.channel-card'))==2
            hero=driver.find_element(By.CSS_SELECTOR,'.hero-photo')
            wait.until(lambda d:hero.get_property('complete') and hero.get_property('naturalWidth')>0)
            if width in (390,1440):
                driver.execute_script('scrollTo(0,0)')
                full=driver.execute_cdp_cmd('Page.captureScreenshot',dict(format='png',captureBeyondViewport=True,
                    clip=dict(x=0,y=0,width=width,height=driver.execute_script('return document.documentElement.scrollHeight'),scale=1)))
                Path(f'/tmp/station-homepage-{width}-{theme}.png').write_bytes(base64.b64decode(full['data']))
    viewport(driver,390)
    menu=driver.find_element(By.CSS_SELECTOR,'.station-menu');menu.click()
    assert menu.get_attribute('aria-expanded')=='true'
    driver.find_element(By.CSS_SELECTOR,'#station-navigation a').send_keys(Keys.ESCAPE)
    assert menu.get_attribute('aria-expanded')=='false'
    assert driver.switch_to.active_element==menu
    errors=[row for row in driver.get_log('browser') if row['level']=='SEVERE' and 'favicon.ico' not in row['message']]
    assert not errors,errors
    driver.execute_cdp_cmd('Emulation.setScriptExecutionDisabled',{'value':True})
    try:
        driver.get(base+'/')
        assert driver.find_element(By.ID,'station-navigation').is_displayed()
        assert len(driver.find_elements(By.CSS_SELECTOR,'.channel-link'))==2
        assert driver.find_element(By.CSS_SELECTOR,'.hero-listen').get_attribute('href').endswith('/player/test-station')
    finally:driver.execute_cdp_cmd('Emulation.setScriptExecutionDisabled',{'value':False})


def test_website_editor_publish_preview_and_workspace_monitor(booth):
    app,driver,base,tmp_path=booth
    wait=WebDriverWait(driver,15)
    driver.find_element(By.CSS_SELECTOR,'.master-monitor button').click()
    wait.until(lambda d:d.execute_script('return !FreoMonitor.audio.paused'))
    driver.execute_script('window.originalAudio=FreoMonitor.audio;FreoWorkspace.navigate(arguments[0])',base+'/')
    wait.until(lambda d:d.find_elements(By.CSS_SELECTOR,'.station-header.enhanced'))
    assert driver.execute_script('return originalAudio===FreoMonitor.audio && !FreoMonitor.audio.paused')
    driver.execute_script('FreoWorkspace.navigate(arguments[0])',base+'/admin/website')
    wait.until(lambda d:d.find_elements(By.CSS_SELECTOR,'[data-website-editor]'))
    assert driver.execute_script('return originalAudio===FreoMonitor.audio && !FreoMonitor.audio.paused')
    name=driver.find_element(By.NAME,'name');name.clear();name.send_keys('Sunroom Radio')
    tagline=driver.find_element(By.NAME,'tagline');tagline.clear();tagline.send_keys('For the love of listening.')
    Select(driver.find_element(By.CSS_SELECTOR,'[data-website-palette]')).select_by_value('ocean')
    driver.find_element(By.CSS_SELECTOR,'button[value=save]').click()
    wait.until(lambda d:d.find_elements(By.CSS_SELECTOR,'.admin-notice.success'))
    driver.get(base+'/')
    assert 'Sunroom Radio' not in driver.find_element(By.TAG_NAME,'body').text
    driver.get(base+'/admin/website/preview-frame')
    driver.find_element(By.CSS_SELECTOR,'button[data-size=mobile]').click()
    iframe=driver.find_element(By.TAG_NAME,'iframe')
    assert round(iframe.rect['width'])==390
    driver.switch_to.frame(iframe)
    wait.until(lambda d:'Sunroom Radio' in d.find_element(By.TAG_NAME,'body').text)
    assert driver.execute_script('return document.documentElement.scrollWidth<=innerWidth+1')
    driver.switch_to.default_content()
    driver.get(base+'/admin/website')
    viewport(driver,390)
    driver.save_screenshot('/tmp/website-editor-mobile.png')
    assert driver.execute_script('return document.documentElement.scrollWidth<=innerWidth+1'), driver.execute_script('return [...document.querySelectorAll("body *")].filter(el=>el.getBoundingClientRect().right>innerWidth+1).map(el=>[el.tagName,el.className,el.getBoundingClientRect().width]).slice(-30)')
    viewport(driver,1440)
    driver.find_element(By.CSS_SELECTOR,'button[value=publish]').click()
    wait.until(lambda d:d.find_elements(By.CSS_SELECTOR,'.admin-notice.success'))
    driver.get(base+'/')
    assert 'Sunroom Radio' in driver.find_element(By.TAG_NAME,'body').text
    assert driver.execute_script('return getComputedStyle(document.body).getPropertyValue("--site-accent").trim()')=='#285977'


def test_homepage_section_links_preserve_content_and_history(booth):
    app, driver, base, tmp_path = booth
    wait = WebDriverWait(driver, 12)
    driver.get(base + '/')
    wait.until(lambda d: d.find_elements(By.CSS_SELECTOR, '.station-header.enhanced'))
    driver.execute_script('''
        window.originalMain = document.getElementById('main');
        window.documentFetches = [];
        const originalFetch = window.fetch;
        window.fetch = (...args) => {
            const url = new URL(args[0], location.href);
            if (url.pathname === '/') documentFetches.push(url.href);
            return originalFetch(...args);
        };
    ''')
    for fragment in ('channels', 'about', 'contact'):
        driver.find_element(By.CSS_SELECTOR, f'#station-navigation a[href="#{fragment}"]').click()
        wait.until(lambda d: d.execute_script('return location.hash === arguments[0] && scrollY > 100', '#'+fragment))
        assert driver.execute_script('return originalMain === document.getElementById("main") && documentFetches.length === 0')
    driver.back()
    wait.until(lambda d: d.execute_script('return location.hash === "#about"'))
    driver.forward()
    wait.until(lambda d: d.execute_script('return location.hash === "#contact"'))
    assert driver.execute_script('return originalMain === document.getElementById("main") && documentFetches.length === 0')
    viewport(driver, 390)
    driver.execute_script('scrollTo(0,0)')
    driver.find_element(By.CSS_SELECTOR, '.station-menu').click()
    driver.find_element(By.CSS_SELECTOR, '#station-navigation a[href="#channels"]').click()
    wait.until(lambda d: d.execute_script('return location.hash === "#channels" && scrollY > 100'))
    assert driver.find_element(By.CSS_SELECTOR, '.station-menu').get_attribute('aria-expanded') == 'false'
    assert driver.execute_script('return originalMain === document.getElementById("main") && documentFetches.length === 0')
    # Cross-page navigation must still load a page and retain its target section.
    driver.execute_script('FreoWorkspace.navigate(arguments[0])', base + '/player/test-station')
    wait.until(lambda d: d.find_elements(By.CSS_SELECTOR, '.radio-experience'))
    driver.execute_script('FreoWorkspace.navigate(arguments[0])', base + '/#channels')
    wait.until(lambda d: d.find_elements(By.CSS_SELECTOR, '.station-header.enhanced') and d.execute_script('return location.hash === "#channels" && scrollY > 100'))
    assert driver.execute_script('return Math.abs(document.getElementById("channels").getBoundingClientRect().top) < 2')
    driver.back()
    wait.until(lambda d: d.find_elements(By.CSS_SELECTOR, '.radio-experience'))
