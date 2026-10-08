"""External Chrome acceptance against the real installed customer application."""
import json,os,subprocess,sys,tempfile,time,shutil
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
E=Path(os.environ.get('FREO_ACCEPTANCE_EVIDENCE','/root/freo-upgrade-tests'));E.mkdir(exist_ok=True);base='http://209.38.64.12';phase=sys.argv[1]
profile=tempfile.mkdtemp(prefix='freo-native-browser-')
options=Options();options.binary_location='/snap/chromium/current/usr/lib/chromium-browser/chrome'
for flag in ['--headless=new','--no-sandbox','--disable-dev-shm-usage','--window-size=1440,1100','--host-resolver-rules=MAP 209.38.64.12 127.0.0.1','--disable-background-networking',f'--user-data-dir={profile}']:options.add_argument(flag)
driver=webdriver.Chrome(service=Service('/snap/chromium/current/usr/lib/chromium-browser/chromedriver'),options=options)
wait=WebDriverWait(driver,30);jobs=WebDriverWait(driver,180)
report={'phase':phase,'status':'running','checks':[]}
def passed(name):
 report['checks'].append(name);(E/f'native-browser-{phase}.json').write_text(json.dumps(report,indent=2)+'\n');print(name,flush=True)
def ready():wait.until(lambda d:not d.execute_script('return document.documentElement.classList.contains("is-navigating")'))
def click(selector):
 element=driver.find_element(By.CSS_SELECTOR,selector);driver.execute_script('arguments[0].scrollIntoView({block:"center"})',element);element.click()
def text(selector,value,deadline=wait):deadline.until(lambda d:value in d.find_element(By.CSS_SELECTOR,selector).text)
def login(password):
 driver.get(base+'/admin/login');driver.find_element(By.NAME,'email').send_keys('admin');driver.find_element(By.NAME,'password').send_keys(password);click('.login-card button[type=submit]')
try:
 if phase=='fresh':
  login('IAmOnTheAir');wait.until(lambda d:d.current_url==base+'/admin/setup')
  driver.get(base+'/admin/software');assert driver.current_url==base+'/admin/setup';passed('mandatory first-time setup enforced')
  driver.find_element(By.NAME,'email').send_keys('acceptance@example.test')
  for name in ('password','confirmation'):driver.find_element(By.NAME,name).send_keys('private native acceptance passphrase')
  click('.login-card button[type=submit]');wait.until(lambda d:d.current_url==base+'/admin')
  wait.until(lambda d:d.find_element(By.ID,'license-agreement').is_displayed())
  click('#license-accept-form input[name=agree]');click('#license-accept-form button[type=submit]')
  wait.until(lambda d:not d.find_element(By.ID,'license-agreement').is_displayed());passed('password replacement and supported license acceptance')
  form=driver.find_element(By.CSS_SELECTOR,'form[action="/admin/stations/create"]')
  form.find_element(By.NAME,'name').send_keys('Upgrade Acceptance');form.find_element(By.NAME,'slug').send_keys('acceptance');form.find_element(By.CSS_SELECTOR,'button').click()
  jobs.until(lambda d:d.find_elements(By.CSS_SELECTOR,'[data-monitor-station="acceptance"]'));ready()
  driver.get(base+'/admin/stations/acceptance/schedule-studio/control');jobs.until(lambda d:d.find_element(By.ID,'master-broadcast-toggle').is_enabled());passed('station created and provisioned by real services')

 else:
  login('private native acceptance passphrase');wait.until(lambda d:d.current_url==base+'/admin');passed('existing administrator login retained')
  assert not driver.find_element(By.ID,'license-agreement').is_displayed();passed('license acceptance retained')
 if phase in ('fresh','upload'):
  driver.get(base+'/admin/stations/acceptance/media/upload')
  wait.until(lambda d:d.find_elements(By.ID,'choose-files'))
  wait.until(lambda d:d.find_elements(By.CSS_SELECTOR,'.freo-dialog[open]') or d.execute_script('return !!document.getElementById("choose-files").onclick'))
  dialogs=driver.find_elements(By.CSS_SELECTOR,'.freo-dialog[open] .admin-primary')
  if dialogs:dialogs[0].click()
  wait.until(lambda d:d.execute_script('return !!document.getElementById("choose-files").onclick'))
  audio=[]
  for index,freq in [(1,440),(2,660)]:
   file=E/f'native-tone-{index}.mp3' if index==1 else E/f'native-tone-{index}.m4a'
   subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i',f'sine=frequency={freq}:duration=22','-metadata',f'title=Acceptance tone {index}','-metadata','artist=Acceptance fixture','-y',str(file)],check=True)
   audio.append(str(file))
  driver.find_element(By.ID,'media-file').send_keys('\n'.join(audio))
  text('#media-upload-form [type=submit]','Import 2 ready songs',jobs);click('#media-upload-form [type=submit]')
  text('#import-message','Import started');text('#import-success','imported successfully',jobs);passed('music upload and background ingest through customer UI')
 driver.get(base+'/admin/stations/acceptance/schedule-studio/control')
 jobs.until(lambda d:d.find_element(By.ID,'master-broadcast-toggle').is_enabled())
 if driver.find_element(By.ID,'master-broadcast-toggle').text.strip()=='OFF':click('#master-broadcast-toggle')
 jobs.until(lambda d:'STATION LIVE' in d.find_element(By.CSS_SELECTOR,'[data-monitor-station="acceptance"]').text)
 passed('broadcast started through actual systemd and Icecast')
 if phase in ('fresh','configure'):
  driver.get(base+'/admin/stations/acceptance/schedule-studio/simple')
  wait.until(lambda d:d.find_elements(By.CSS_SELECTOR,'#source-tabs button'))
  next(t for t in driver.find_elements(By.CSS_SELECTOR,'#source-tabs button') if t.text=='Artists').click()
  text('#source-results','Acceptance fixture');click('#source-results [aria-label="Add Acceptance fixture"]')
  text('#simple-selection','Acceptance fixture');click('#save-schedule');text('#save-state','Saved')
  click('#activate-mode');wait.until(lambda d:d.find_element(By.ID,'mode-confirm').is_displayed() and d.find_element(By.ID,'confirm-mode').is_enabled());click('#confirm-mode')
  text('#mode-detail','Following your saved programming',jobs)
  passed('Simple programming selected, saved, and activated through UI')
 driver.get(base+'/admin/stations/acceptance/live')
 jobs.until(lambda d:'Acceptance tone' in d.find_element(By.ID,'auto-song').text)
 first=driver.find_element(By.ID,'auto-song').text
 jobs.until(lambda d:'Acceptance tone' in d.find_element(By.ID,'auto-song').text and d.find_element(By.ID,'auto-song').text!=first)
 passed('automatic playback and track handoff observed')
 ready();click('[data-monitor-station="acceptance"] button')
 wait.until(lambda d:d.execute_script('return !FreoMonitor.audio.paused'))
 driver.execute_script('window.acceptanceMonitor=FreoMonitor.audio')
 click('.admin-nav a[href$="/categories"]');wait.until(lambda d:d.execute_script('return document.querySelector("h1")?.textContent === "Categories"'));ready()
 driver.back();wait.until(lambda d:d.find_elements(By.ID,'dj-booth'))
 assert driver.execute_script('return acceptanceMonitor===FreoMonitor.audio && !FreoMonitor.audio.paused');passed('Back navigation and persistent monitor')
 if 'restart' in phase:
  wait.until(lambda d:len(d.find_elements(By.CSS_SELECTOR,'#booth-cue-list [data-cue-entry]'))==2)
  passed('server-owned Cue entries persisted across the full environment restart')
 if phase not in ('fresh','cue'):
  ready();click('.mode-button[data-mode="DJ_BOOTH"]')
  wait.until(lambda d:d.find_element(By.ID,'dj-booth').get_attribute('data-mode')=='DJ_BOOTH')
  click('.cue-picker-button[data-target="A"]')
  driver.find_element(By.ID,'song-picker-search').send_keys('Acceptance tone 1')
  text('#song-picker-results','Acceptance tone 1');click('#song-picker-results button')
  text('#deck-a-state','READY');click('[data-deck="A"][data-operation="PLAY"]')
  text('#deck-a-state','LIVE');passed('booth deck load and PLAY confirmed by worker status')
  click('[data-deck="A"][data-operation="PAUSE"]')
  wait.until(lambda d:d.find_element(By.ID,'dj-booth').get_attribute('data-mode')=='AUTO')
  passed('booth PAUSE and supported return to automatic playback')
 if phase == 'cue':
  from selenium.webdriver.common.keys import Keys
  ready();click('.mode-button[data-mode="DJ_BOOTH"]')
  wait.until(lambda d:d.find_element(By.ID,'dj-booth').get_attribute('data-mode')=='DJ_BOOTH')
  identifiers=driver.execute_script('return [...document.querySelectorAll(".song-card[data-id]")].map(x=>x.dataset.id)')
  assert len(identifiers)==2
  def cue_ids():return driver.execute_script('return [...document.querySelectorAll("#booth-cue-list [data-cue-entry]")].map(x=>x.dataset.cueEntry)')
  assert cue_ids()==[]
  for count,identifier in enumerate(identifiers,1):
   selector=f'.song-card[data-id="{identifier}"] [data-add-cue]'
   wait.until(lambda d:d.find_element(By.CSS_SELECTOR,selector).is_enabled());click(selector)
   wait.until(lambda d:len(cue_ids())==count)
  first=cue_ids()[0]
  driver.find_elements(By.CSS_SELECTOR,'#booth-cue-list [data-cue-entry]')[1].find_element(By.CSS_SELECTOR,'.cue-handle').send_keys(Keys.ALT,Keys.ARROW_UP,Keys.NULL)
  wait.until(lambda d:cue_ids()[0]!=first)
  def live_status():
   result=driver.execute_async_script("const done=arguments[0];fetch('/admin/api/stations/acceptance/live-status').then(r=>{if(!r.ok)throw Error(r.status);return r.json()}).then(done).catch(e=>done({error:String(e)}))")
   assert 'error' not in result,result
   return result
  expected=[entry['uuid'] for entry in live_status()['cue_list']['entries']]
  click('#cue-auto');seen=[]
  def cycled(_):
   current=live_status().get('current')
   if current and current.get('source')=='CUE' and (not seen or seen[-1]['decision_id']!=current['decision_id']):
    seen.append({k:current[k] for k in ('decision_id','uuid','title')})
   return len(seen)>=3
  jobs.until(cycled)
  assert [row['uuid'] for row in seen[:3]]==[expected[0],expected[1],expected[0]],seen
  report['cue_starts']=seen
  click('#cue-auto');wait.until(lambda d:d.find_element(By.ID,'cue-auto').get_attribute('aria-pressed')=='false')
  click('.mode-button[data-mode="AUTO"]');wait.until(lambda d:d.find_element(By.ID,'dj-booth').get_attribute('data-mode')=='AUTO')
  passed('reordered AUTO_CUE completed three real PostgreSQL-backed starts in exact cyclic order')
 driver.save_screenshot(str(E/f'native-{phase}.png'))
 report['status']='passed'
except Exception as error:
 report['status']='failed';report['error']=type(error).__name__+': '+str(error)[:1200]
 driver.save_screenshot(str(E/f'native-{phase}-failure.png'))
 (E/f'native-{phase}-failure.html').write_text(driver.page_source)
 raise
finally:
 (E/f'native-browser-{phase}.json').write_text(json.dumps(report,indent=2)+'\n')
 driver.quit();shutil.rmtree(profile,ignore_errors=True)
