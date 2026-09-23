"""Audit shared controls and headers across the actual authenticated screens."""
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from app.models import Track
from tests.test_live_browser import booth, open_import
from tests.test_web import app as app_fixture


def test_forms_and_headers_across_pages(booth):
    app, driver, base, tmp_path = booth
    with app.app_context():
        track = Track.query.first().uuid
    paths = ['/admin', '/admin/stations', '/admin/audit'] + [
        '/admin/stations/test-station/' + section for section in (
            'settings', 'player-settings', 'listener-feedback', 'media', 'media/upload',
            'media/' + track, 'categories', 'categories/power', 'rotations', 'rotations/main',
            'clocks', 'clocks/music', 'schedule', 'tags',
            'playlists', 'sound-room', 'imaging', 'imaging/upload', 'calendar',
            'events', 'events/create', 'blocks', 'traffic', 'live')]
    import json
    issues = []
    for path in paths:
        if path.endswith('/media/upload'): open_import(driver, base)
        else: driver.get(base + path)
        WebDriverWait(driver, 10).until(lambda d:d.find_elements(By.CSS_SELECTOR, '.admin-topbar'))
        for theme in ('day', 'night'):
            driver.find_element(By.CSS_SELECTOR, f'[data-appearance={theme}]').click()
            driver.save_screenshot(str(tmp_path / (path.replace('/', '_') + '-' + theme + '.png')))
        for width in (390, 820, 1024, 1440):
            driver.set_window_size(width, 1100)
            problems = driver.execute_script('''
                const problems=[];
                if(document.documentElement.scrollWidth>innerWidth) problems.push('page overflow');
                const header=document.querySelector('.admin-topbar');
                const groups=[...header.children].filter(el=>el.getBoundingClientRect().width);
                for(let i=0;i<groups.length;i++)for(let j=i+1;j<groups.length;j++) {
                    const a=groups[i].getBoundingClientRect(),b=groups[j].getBoundingClientRect();
                    if(Math.min(a.right,b.right)-Math.max(a.left,b.left)>1 && Math.min(a.bottom,b.bottom)-Math.max(a.top,b.top)>1) problems.push('header overlap');
                }
                for(const input of document.querySelectorAll('form input:not([type=hidden],[type=checkbox],[type=radio],[type=range],[type=color]),form select,form textarea')) {
                    if(!input.checkVisibility({checkOpacity:true})) continue;
                    const r=input.getBoundingClientRect();
                    if(r.height<43)problems.push('small control '+input.name);
                    if(r.width<60 && input.type!=='number')problems.push('narrow control '+input.name);
                }
                return [...new Set(problems)];
            ''')
            issues.extend((path, width, problem) for problem in problems)
        driver.save_screenshot(str(tmp_path / (path.replace('/', '_') + '-final.png')))
        (tmp_path / 'layout-issues.json').write_text(json.dumps(issues, indent=2))
        print('Audited ' + path, flush=True)
    assert not issues, issues


def test_station_form_keyboard_validation_and_dialog(booth):
    app, driver, base, tmp_path = booth
    driver.get(base + '/admin/stations')
    form = driver.find_element(By.CSS_SELECTOR, '.station-create form')
    field = form.find_element(By.NAME, 'name')
    field.send_keys('Coastal radio')
    driver.find_element(By.CSS_SELECTOR, '[data-appearance=night]').click()
    assert field.get_attribute('value') == 'Coastal radio'
    assert form.find_element(By.NAME, 'slug').get_attribute('aria-describedby') == 'station-id-help'
    # Native validity remains available to the workspace submission handler.
    assert driver.execute_script('return arguments[0].checkValidity()', form) is False
    driver.get(base + '/admin/stations/test-station/calendar')
    driver.find_element(By.XPATH, "//nav[@id='source-tabs']/button[text()='Songs']").click()
    WebDriverWait(driver, 10).until(lambda d:d.find_elements(By.CSS_SELECTOR, '.source-actions button'))
    driver.find_element(By.CSS_SELECTOR, '.source-actions button').click()
    dialog = driver.find_element(By.ID, 'section-inspector')
    assert dialog.is_displayed()
    for width in (390, 820, 1440):
        driver.set_window_size(width, 1100)
        assert driver.execute_script('return arguments[0].scrollWidth <= arguments[0].clientWidth', dialog)
        assert driver.execute_script('return document.documentElement.scrollWidth <= innerWidth')
