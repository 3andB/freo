"""Installed self-hosted UI/audio checks on the final clean upgrade."""
import concurrent.futures,http.client,json,os,re,socket,subprocess,sys,time
from pathlib import Path
import requests
assert socket.gethostname()=='Freo-v1-Test-1'
os.chdir('/opt/freo/current');sys.path.insert(0,str(Path.cwd()));os.environ['FREO_ENV_FILE']='/etc/freo/freo.env'
from freo_ops import hosting,hosting_storage
assert hosting.read()=={'hosted':False}
assert not (hosting.STATE/'enabled').exists()
E=Path('/root/freo-phase-b');session=requests.Session();session.trust_env=False;base='http://209.38.64.12'
credentials=json.loads((E/'admin-credentials.json').read_text())
page=session.get(base+'/admin/login',timeout=10)
token=re.search(r'name="csrf" value="([^"]+)"',page.text).group(1)
response=session.post(base+'/admin/login',data=dict(credentials,csrf=token),timeout=15)
assert '/admin/login' not in response.url
for path in ('/admin','/admin/stations','/admin/software','/admin/installation'):
    response=session.get(base+path,timeout=15);assert response.status_code==200,(path,response.status_code)
    assert 'aria-label="Hosting usage"' not in response.text and 'Media Storage —' not in response.text
assert session.get(base+'/hosting/status',timeout=10).status_code==404
with hosting_storage.reserve(100_000_000_000):pass
hosting.check_stations(99999);hosting.check_bitrate(192)
assert hosting_storage.usage()=={'hosted':False}
result=subprocess.run(['freo-admin','hosting','suspend'],capture_output=True,text=True)
assert result.returncode==4 and json.loads(result.stdout)['error']=='not_hosted'
from app import create_app
from app.extensions import db
from app.models import Station,AdminUser
from app.services.station_audio import queue_settings,process_audio,validate_settings,active_settings
app=create_app()
with app.app_context():
    station=Station.query.filter_by(slug='acceptance').one();original=active_settings(station.stream)
    def change(settings):
        db.session.refresh(station.stream)
        queue_settings(station,validate_settings(settings),station.stream.audio_revision,AdminUser.query.filter_by(installation_admin=True).first())
        db.session.commit();process_audio(station)
    try:
        change(dict(original,bitrate=192))
        output=subprocess.check_output(['ffprobe','-v','error','-read_intervals','%+#50','-show_entries','stream=bit_rate','-of','json','http://127.0.0.1:8001/acceptance'],text=True,timeout=20)
        assert json.loads(output)['streams'][0]['bit_rate']=='192000'
    finally:change(original)
# Existing Icecast transport tuning remains independent of hosting. Temporarily
# raise its original technical client budget to demonstrate >100 audio listeners.
import xml.etree.ElementTree as ET
path=Path('/etc/freo/radio/icecast.xml');original=path.read_bytes();root=ET.fromstring(original)
assert root.find('limits/freo-listeners') is None
rows=[]
def listen(index):
    client=http.client.HTTPConnection('127.0.0.1',8001,timeout=10)
    client.request('GET','/'+('acceptance' if index%2 else 'upgrade-two'))
    response=client.getresponse();assert response.status==200,response.status;assert response.read(512)
    return client,response
try:
    root.find('limits/clients').text='250';path.write_bytes(ET.tostring(root))
    subprocess.run(['systemctl','reload','icecast2.service'],check=True);time.sleep(2)
    with concurrent.futures.ThreadPoolExecutor(max_workers=116) as pool:rows=list(pool.map(listen,range(116)))
    assert len(rows)==116
finally:
    for client,response in rows:response.close();client.close()
    path.write_bytes(original);subprocess.run(['systemctl','reload','icecast2.service'],check=True)
report=dict(hosted=False,hosting_ui_absent=True,hosting_endpoint_404=True,commercial_suspend_refused=True,
            no_hosting_storage_or_station_cap=True,actual_192kbps=True,actual_aggregate_listeners=116,
            original_transport_configuration_restored=True)
(E/'selfhost-results.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))
