import os,sys,subprocess,json
from pathlib import Path
os.environ['FREO_ENV_FILE']='/opt/freo/.env';sys.path.insert(0,'/opt/freo')
assert subprocess.check_output(['hostname'],text=True).strip()=='Freo-v1-Test-1'
from app import create_app
from app.extensions import db
from app.models import Station,Track,Playlist,AdminUser,MediaCategory,Rotation,Clock,ImagingGroup
from app.services import automation as auto,clocks,playlists,imaging
from app.services.media import ingest
from werkzeug.security import generate_password_hash
E=Path('/root/freo-upgrade-tests')
def run(*args):subprocess.run(args,check=True,stdout=subprocess.DEVNULL)
for slug in ('upgrade-two','upgrade-stopped'):
 run('/opt/freo/venv/bin/flask','--app','wsgi:app','station','create',slug,'--name',slug,'--timezone','Europe/London','--if-not-exists')
run('ffmpeg','-v','error','-f','lavfi','-i','color=c=blue:s=120x120','-frames:v','1','-threads','1','-y',str(E/'cover.jpg'))
run('ffmpeg','-v','error','-f','lavfi','-i','sine=frequency=880:duration=18','-i',str(E/'cover.jpg'),'-map','0:a','-map','1:v','-c:a','libmp3lame','-c:v','copy','-id3v2_version','3','-metadata','title=Artwork song','-metadata','artist=Upgrade Artist','-metadata','album=Upgrade Album','-metadata:s:v','title=Album cover','-metadata:s:v','comment=Cover (front)','-y',str(E/'artwork.mp3'))
app=create_app()
with app.app_context():
 for slug in ('acceptance','upgrade-two','upgrade-stopped'):
  station=Station.query.filter_by(slug=slug).one()
  for filename in ('artwork.mp3','native-tone-1.mp3','native-tone-2.m4a'):
   if slug=='acceptance' and filename!='artwork.mp3':continue
   ingest(slug,E/filename)
  tracks=Track.query.filter_by(station_id=station.id).all()
  category=MediaCategory.query.filter_by(station_id=station.id,slug='upgrade-music').first() or auto.category_create(slug,'Upgrade music','upgrade-music')
  for track in tracks:auto.assign_track(slug,track.uuid,category.slug)
  rotation=Rotation.query.filter_by(station_id=station.id,slug='upgrade-rotation').first() or auto.rotation_create(slug,'Upgrade rotation','upgrade-rotation')
  if not rotation.slots:auto.add_slot(slug,rotation.slug,category.slug)
  playlist=Playlist.query.filter_by(station_id=station.id,system_key='PLAYLIST_1').one()
  playlists.membership(playlist,tracks,'add',AdminUser.query.filter_by(installation_admin=True).one().id);db.session.commit()
  clock=Clock.query.filter_by(station_id=station.id,slug='upgrade-clock').first()
  if clock is None:
   clock=clocks.create_clock(slug,'Upgrade clock','upgrade-clock');clocks.add_clock_slot(slug,clock.slug,'ROTATION',rotation.slug)
   for day in range(7):clocks.assign(slug,day,'00:00',clock.slug)
  auto.activate(slug,rotation.slug);auto.set_automation(slug,True,0,0)
  asset,_=imaging.ingest_imaging(slug,E/'native-tone-1.mp3','JINGLE',name='Upgrade station ID',cart_code='UPGRADE',enabled=True)
  group=ImagingGroup.query.filter_by(station_id=station.id,slug='upgrade-ids').first() or imaging.create_group(slug,'Upgrade IDs','upgrade-ids');imaging.set_group_membership(slug,group.slug,asset.uuid,True)
 user=AdminUser(email='upgrade-dj@example.test',username='upgrade-dj',password_hash=generate_password_hash('disposable upgrade DJ password'),active=True)
 db.session.add(user);db.session.commit()
 print(json.dumps({'stations':Station.query.count(),'tracks':Track.query.count(),'playlists':Playlist.query.count(),'users':AdminUser.query.count()}))
run('/opt/freo/venv/bin/flask','--app','wsgi:app','station','start','upgrade-two')
