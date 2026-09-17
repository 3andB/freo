"""Responsive project tour, keyboard access and persistent workspace behavior."""
import base64
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from tests.test_live_browser import booth, app_fixture


def viewport(driver, width, height=1000):
    driver.execute_cdp_cmd('Emulation.setDeviceMetricsOverride', dict(width=width, height=height, deviceScaleFactor=1, mobile=False))


def test_homepage_responsive_gallery_and_no_javascript(booth):
    app, driver, base, tmp_path = booth
    driver.delete_all_cookies()
    driver.get(base + '/')
    wait = WebDriverWait(driver, 12)
    wait.until(lambda d: 'enhanced' in d.find_element(By.CSS_SELECTOR, '.project-nav').get_attribute('class'))
    issues = []
    for width in (320, 390, 430, 768, 820, 1024, 1440, 1920):
        viewport(driver, width)
        for theme in ('day', 'night'):
            driver.find_element(By.CSS_SELECTOR, f'.project-header [data-appearance={theme}]').click()
            assert driver.execute_script('return document.documentElement.dataset.theme') == theme
            assert driver.execute_script('return innerWidth') == width
            problems = driver.execute_script('''
              const issues=[];
              if(document.documentElement.scrollWidth>innerWidth+1) issues.push('page overflow');
              const header=[...document.querySelector('.project-nav').children].filter(e=>e.checkVisibility());
              for(let i=0;i<header.length;i++)for(let j=i+1;j<header.length;j++){
                const a=header[i].getBoundingClientRect(),b=header[j].getBoundingClientRect();
                if(Math.min(a.right,b.right)-Math.max(a.left,b.left)>2&&Math.min(a.bottom,b.bottom)-Math.max(a.top,b.top)>2)issues.push('header overlap');
              }
              for(const el of document.querySelectorAll('h1,h2,h3,.project-button')){
                const r=el.getBoundingClientRect();
                if(r.right>innerWidth+1||r.left<0)issues.push('clipped '+el.tagName);
              }
              return issues;
            ''')
            issues.extend((width, theme, problem) for problem in problems)
            hero = driver.find_element(By.CSS_SELECTOR, '.project-hero img')
            wait.until(lambda d: hero.get_property('complete') and hero.get_property('naturalWidth') > 0)
            assert f'-{theme}-' in hero.get_property('currentSrc')
            if width in (390, 820, 1440):
                driver.save_screenshot(str(tmp_path / f'home-{width}-{theme}.png'))
    assert not issues, issues
    viewport(driver, 390, 844)
    menu = driver.find_element(By.CSS_SELECTOR, '.project-menu')
    menu.click()
    assert menu.get_attribute('aria-expanded') == 'true'
    driver.find_element(By.CSS_SELECTOR, '#project-navigation a').send_keys(Keys.ESCAPE)
    assert menu.get_attribute('aria-expanded') == 'false'
    assert driver.switch_to.active_element == menu
    hero_link = driver.find_element(By.CSS_SELECTOR, '.project-hero [data-product-screen]')
    driver.execute_script('arguments[0].scrollIntoView({block:"center"})', hero_link)
    hero_link.send_keys(Keys.ENTER)
    dialog = driver.find_element(By.ID, 'product-lightbox')
    wait.until(lambda d: dialog.is_displayed())
    assert driver.switch_to.active_element.get_attribute('class') == 'project-lightbox-close'
    driver.find_element(By.CSS_SELECTOR, '#product-lightbox [data-appearance=day]').click()
    image = driver.find_element(By.CSS_SELECTOR, '.project-lightbox-image img')
    wait.until(lambda d: '-day-' in image.get_attribute('src') and image.get_property('complete'))
    driver.find_element(By.CSS_SELECTOR, '[data-screen-step="1"]').click()
    assert 'music' in image.get_attribute('src')
    driver.switch_to.active_element.send_keys(Keys.ESCAPE)
    wait.until(lambda d: not dialog.is_displayed())
    assert driver.switch_to.active_element == hero_link
    viewport(driver, 1440, 1000)
    # Load each image before a complete design-review capture.
    for image in driver.find_elements(By.CSS_SELECTOR, '[data-product-screen] img'):
        driver.execute_script('arguments[0].scrollIntoView({block:"center"})', image)
        wait.until(lambda d: image.get_property('complete') and image.get_property('naturalWidth') > 0)
    driver.execute_script('window.scrollTo(0,0)')
    full = driver.execute_cdp_cmd('Page.captureScreenshot', dict(format='png', captureBeyondViewport=True,
        clip=dict(x=0,y=0,width=1440,height=driver.execute_script('return document.documentElement.scrollHeight'),scale=1)))
    (tmp_path / 'home-full-day.png').write_bytes(base64.b64decode(full['data']))
    errors = [r for r in driver.get_log('browser') if r['level'] == 'SEVERE' and 'favicon.ico' not in r['message']]
    assert not errors, errors
    driver.execute_cdp_cmd('Emulation.setScriptExecutionDisabled', {'value': True})
    try:
        viewport(driver, 390)
        driver.get(base + '/')
        assert driver.find_element(By.ID, 'project-navigation').is_displayed()
        assert driver.find_element(By.ID, 'capabilities').is_displayed()
        assert driver.find_element(By.CSS_SELECTOR, '.project-screen-link').get_attribute('href').endswith('.webp')
        driver.save_screenshot(str(tmp_path / 'home-no-javascript.png'))
    finally:
        driver.execute_cdp_cmd('Emulation.setScriptExecutionDisabled', {'value': False})


def test_homepage_workspace_navigation_keeps_audio_and_disposes_gallery(booth):
    app, driver, base, tmp_path = booth
    wait = WebDriverWait(driver, 12)
    driver.find_element(By.CSS_SELECTOR, '.master-monitor button').click()
    wait.until(lambda d: d.execute_script('return !FreoMonitor.audio.paused'))
    driver.execute_script('window.originalAudio=FreoMonitor.audio')
    for _ in range(2):
        driver.execute_script('FreoWorkspace.navigate(arguments[0])', base + '/')
        wait.until(lambda d: d.find_elements(By.CSS_SELECTOR, '.project-nav.enhanced'))
        driver.find_element(By.CSS_SELECTOR, '.project-header [data-appearance=night]').click()
        assert driver.execute_script('return originalAudio===FreoMonitor.audio && !FreoMonitor.audio.paused')
        viewport(driver, 320)
        assert driver.execute_script('return document.documentElement.scrollWidth<=innerWidth+1')
        viewport(driver, 1440)
        driver.find_element(By.CSS_SELECTOR, '.project-hero [data-product-screen]').click()
        wait.until(lambda d: d.find_element(By.ID, 'product-lightbox').is_displayed())
        driver.find_element(By.CSS_SELECTOR, '.project-lightbox-close').click()
        driver.execute_script('FreoWorkspace.navigate(arguments[0])', base + '/admin/stations/test-station/live')
        wait.until(lambda d: d.find_elements(By.ID, 'dj-booth'))
        assert not driver.find_elements(By.CSS_SELECTOR, '.project-home')
        assert driver.execute_script('return originalAudio===FreoMonitor.audio && !FreoMonitor.audio.paused')
