"""Actual HTTP upload reservations and PostgreSQL artwork accounting."""
import http.client, json, os, re, socket, subprocess, sys, time, uuid
from pathlib import Path
import requests
assert socket.gethostname() == 'Freo-v1-Test-1'
os.chdir('/opt/freo/current');sys.path.insert(0,str(Path.cwd()))
os.environ['FREO_ENV_FILE']='/etc/freo/freo.env'
from freo_ops import hosting_storage as storage, hosting
from app import create_app
from app.extensions import db
from app.models import WebsiteAsset
E=Path('/root/freo-phase-b');base='http://127.0.0.1'
session=requests.Session();session.trust_env=False;session.headers['Host']='209.38.64.12'
credentials=json.loads((E/'admin-credentials.json').read_text())
page=session.get(base+'/admin/login',timeout=10)
token=re.search(r'name="csrf" value="([^"]+)"',page.text).group(1)
response=session.post(base+'/admin/login',data=dict(credentials,csrf=token),timeout=15)
assert '/admin/login' not in response.url
page=session.get(base+'/admin/stations/acceptance/media/upload',timeout=10)
assert page.status_code==200 and '/media/upload' in page.url
token=re.search(r'data-csrf="([^"]+)"',page.text).group(1)
audio=Path('/root/freo-upgrade-tests/native-tone-1.mp3').read_bytes()
path='/admin/stations/acceptance/media/upload'
def request():
    return session.prepare_request(requests.Request('POST',base+path,data={'csrf':token},
        files={'file':('hosting-upload.mp3',audio,'audio/mpeg')},headers={'Accept':'application/json'}))
prepared=request();size=len(prepared.body)
fixture=Path('/srv/freo-upgrade-media/hosting-http-quota-fixture.bin')
assert not fixture.exists()
connection=None
try:
    used=storage.usage()['used_bytes']
    with fixture.open('xb') as stream:stream.truncate(storage.usage()['limit_bytes']-used-size-size//2)
    fixture.chmod(0o644)
    connection=http.client.HTTPConnection('127.0.0.1',80,timeout=10)
    connection.putrequest('POST',path,skip_host=True)
    for key,value in prepared.headers.items():connection.putheader(key,value)
    connection.endheaders();connection.send(prepared.body[:1024])
    deadline=time.monotonic()+10
    while storage.usage()['reserved_bytes']<size and time.monotonic()<deadline:time.sleep(.1)
    assert storage.usage()['reserved_bytes']>=size,'Request body was buffered before reservation'
    response=session.send(request(),timeout=10)
    assert response.status_code==409 and response.json()['error']=='storage_limit_exceeded',response.text
    connection.close();connection=None
    deadline=time.monotonic()+15
    while storage.usage()['reserved_bytes'] and time.monotonic()<deadline:time.sleep(.1)
    assert storage.usage()['reserved_bytes']==0
finally:
    if connection:connection.close()
    fixture.unlink(missing_ok=True)
# The same actual MP3 is accepted when quota space is available.
response=session.send(request(),timeout=15)
assert response.status_code==202,response.text
job=response.json()['jobs'][0]['id']
from app.models import MediaIngestJob
app=create_app()
deadline=time.monotonic()+90
while True:
    with app.app_context():
        row=db.session.get(MediaIngestJob,job)
        status=row.status;error=row.error_code
    if status not in ('pending','processing'):break
    assert time.monotonic()<deadline,(status,error)
    time.sleep(.5)
assert status=='accepted',(status,error)
# Persisted database image bytes count exactly; an over-quota blob is rejected.
with app.app_context():
    before=storage.usage()['database_media_bytes']
    key='hosting-test-'+uuid.uuid4().hex
    row=WebsiteAsset(id=key,image=b'i'*12000,small=b's'*3000)
    db.session.add(row);db.session.commit()
    assert storage.usage()['database_media_bytes']==before+15000
    try:
        with fixture.open('xb') as stream:stream.truncate(storage.usage()['limit_bytes'])
        fixture.chmod(0o644)
        row.image=b'x'*12001
        try:db.session.commit()
        except hosting.HostingError as error:
            assert error.code=='storage_limit_exceeded';db.session.rollback()
        else:raise AssertionError('Over-quota database image was accepted')
        db.session.delete(db.session.get(WebsiteAsset,key));db.session.commit()
        assert storage.usage()['database_media_bytes']==before
    finally:fixture.unlink(missing_ok=True)
report=dict(concurrent_http_reservation=True,second_upload_rejected=True,aborted_upload_released=True,
            actual_mp3_ingested=True,database_artwork_bytes=15000,over_quota_blob_rejected=True,deletion_allowed=True)
(E/'upload-results.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))
