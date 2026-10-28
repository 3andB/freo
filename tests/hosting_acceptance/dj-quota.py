import json,time,os,sys,socket,secrets,traceback,hashlib,subprocess
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
assert socket.gethostname()=='Freo-v1-Test-1'
os.environ['FREO_ENV_FILE']='/etc/freo/freo.env';os.chdir('/opt/freo/current');sys.path.insert(0,'/opt/freo/current')
from app import create_app,models as m
E=Path('/root/freo-upgrade-tests')/sys.argv[1];E.mkdir(exist_ok=True);base='http://209.38.64.12';slug='acceptance';admin=json.loads(Path('/root/freo-phase-b/admin-credentials.json').read_text());app=create_app();results=[]
options=Options();options.binary_location='/snap/chromium/current/usr/lib/chromium-browser/chrome'
for x in ['--headless=new','--no-sandbox','--disable-dev-shm-usage','--window-size=1440,1100','--host-resolver-rules=MAP 209.38.64.12 127.0.0.1']:options.add_argument(x)
d=webdriver.Chrome(service=Service('/snap/chromium/current/usr/lib/chromium-browser/chromedriver'),options=options);wait=WebDriverWait(d,60)
def click(css):
 e=d.find_element(By.CSS_SELECTOR,css);d.execute_script('arguments[0].scrollIntoView({block:"center"})',e);e.click()
def login(c):
 d.get(base+'/admin/login');d.find_element(By.NAME,'email').send_keys(c['email']);d.find_element(By.NAME,'password').send_keys(c['password']);click('.login-card button[type=submit]');wait.until(lambda _: '/admin/login' not in d.current_url)
def note(test,**data):
 results.append(dict(test=test,**data));(E/'staging-dj-results.json').write_text(json.dumps(results,indent=2));print(test,flush=True)
def recording():
 with app.app_context():
  s=m.Station.query.filter_by(slug=slug).one();r=m.ShowRecording.query.join(m.LiveSession).filter(m.ShowRecording.station_id==s.id).order_by(m.LiveSession.created_at.desc()).first()
  return dict(id=r.id,status=r.status,size=r.file_size_bytes,duration=r.duration_ms,key=r.storage_key,error=r.error,show_ended=r.session.active_station_id is None) if r else None
try:
 login(admin)
 credsfile=E/'dj-credentials.json'
 if not credsfile.exists():
  dj=dict(email='soak-dj-20261008@example.test',password=secrets.token_urlsafe(24))
  d.get(base+'/admin/djs');form=d.find_element(By.CSS_SELECTOR,'.ops-create form')
  for name,value in dict(username='Soak DJ 20261008',**dj).items():form.find_element(By.NAME,name).send_keys(value)
  form.find_element(By.CSS_SELECTOR,'input[name=station_id][value="1"]').click();form.find_element(By.CSS_SELECTOR,'button').click()
  wait.until(lambda _: 'Soak DJ 20261008' in d.find_element(By.TAG_NAME,'body').text)
  credsfile.write_text(json.dumps(dj));credsfile.chmod(0o600);note('Created scoped DJ through browser')
 else:dj=json.loads(credsfile.read_text())
 click('form[action$="/logout"] button');wait.until(lambda _: d.current_url.rstrip('/')==base);note('Administrator logout')
 login(dj);note('DJ login')
 if d.find_elements(By.CSS_SELECTOR,'#license-agreement[open]'):
  click('#license-accept-form input[name=agree]');click('#license-accept-form button[type=submit]')
  wait.until(lambda _:not d.find_element(By.ID,'license-agreement').is_displayed())
 for path,expected in [(f'/admin/stations/{slug}/live',200),('/admin/stations/upgrade-two/live',403),('/admin/stations/upgrade-two/recordings',403),('/admin/djs',403),('/admin/api-credentials',403),(f'/admin/stations/{slug}/media/upload',403)]:
  status=d.execute_async_script('const done=arguments[arguments.length-1];fetch(arguments[0]).then(r=>done(r.status));',path)
  assert status==expected,(path,status);note('DJ route authority',path=path,status=status)
 hashes={}
 for turn in range(2):
  d.get(base+f'/admin/stations/{slug}/live');wait.until(lambda _:d.find_element(By.ID,'record-show').is_enabled())
  if not d.find_element(By.ID,'record-show').is_selected():click('#record-show')
  click('.mode-button[data-mode="DJ_BOOTH"]');wait.until(lambda _:d.find_element(By.ID,'dj-booth').get_attribute('data-mode')=='DJ_BOOTH')
  click('.cue-picker-button[data-target="A"]');d.find_element(By.ID,'song-picker-search').send_keys('Acceptance tone 1')
  wait.until(lambda _:'Acceptance tone 1' in d.find_element(By.ID,'song-picker-results').text);click('#song-picker-results button')
  wait.until(lambda _:d.find_element(By.ID,'deck-a-state').text=='READY');click('[data-deck="A"][data-operation="PLAY"]')
  wait.until(lambda _:recording() and recording()['status']=='recording')
  if turn == 0:
   from freo_ops.hosting_storage import usage
   quota_fixture=Path('/srv/freo-upgrade-media/hosting-dj-quota-fixture.bin')
   with quota_fixture.open('xb') as output:output.truncate(usage()['limit_bytes']-usage()['used_bytes']-150000)
   quota_fixture.chmod(0o644)
   wait.until(lambda _:recording()['status'] in ('partial','failed'))
   r=recording();assert r['status']=='partial' and 'storage' in r['error'],r
   import urllib.request
   with urllib.request.urlopen('http://127.0.0.1:8001/acceptance',timeout=5) as audio:assert audio.read(8192)
   quota_fixture.unlink();note('Quota stopped actual Liquidsoap recording while DJ broadcast continued',**r)
  else:time.sleep(3.2)
  click('#end-show');wait.until(lambda _:recording()['status'] in ['complete','failed','partial'] and recording()['show_ended'])
  r=recording();assert r['status']==('partial' if turn==0 else 'complete') and r['size']>1000 and r['duration']>2000,r
  path=Path('/srv/freo-upgrade-media')/slug/'recordings'/r['key']
  subprocess.run(['ffmpeg','-v','error','-i',str(path),'-f','null','-'],check=True,timeout=10)
  hashes[str(path)]=hashlib.sha256(path.read_bytes()).hexdigest();note('Consecutive short recording decoded',turn=turn,**r)
 for path,digest in hashes.items():assert hashlib.sha256(Path(path).read_bytes()).hexdigest()==digest
 d.get(base+f'/admin/stations/{slug}/recordings');audio=d.find_element(By.TAG_NAME,'audio');
 from selenium.webdriver.common.action_chains import ActionChains
 d.execute_script('arguments[0].scrollIntoView({block:"center"})',audio)
 ActionChains(d).move_to_element_with_offset(audio,-audio.size['width']/2+20,0).click().perform()
 wait.until(lambda _:d.execute_script('return arguments[0].currentTime',audio)>.5);note('Recorded show actually plays in browser')
 d.set_window_size(390,844);assert d.execute_script('return document.documentElement.scrollWidth<=innerWidth+1');d.save_screenshot(str(E/'recordings-mobile.png'))
 click('form[action$="/logout"] button');wait.until(lambda _: d.current_url.rstrip('/')==base);note('DJ logout')
except Exception:
 (E/'staging-dj-error.txt').write_text(traceback.format_exc());d.save_screenshot(str(E/'staging-dj-error.png'));raise
finally:
 Path('/srv/freo-upgrade-media/hosting-dj-quota-fixture.bin').unlink(missing_ok=True)
 d.quit()
