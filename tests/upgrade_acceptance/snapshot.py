import os,sys,json,hashlib,subprocess
from pathlib import Path
root=Path('/opt/freo/current') if Path('/opt/freo/current').exists() else Path('/opt/freo')
sys.path.insert(0,str(root));os.environ['FREO_ENV_FILE']='/etc/freo/freo.env' if root.name=='current' else '/opt/freo/.env'
from freo_ops.__main__ import configuration
from freo_ops import recovery
values=configuration(os.environ['FREO_ENV_FILE']);conn=recovery.connect(values['DATABASE_URL'])
result={'version':None,'counts':recovery.database_inventory(conn),'files':{}}
with conn.cursor() as c:
 c.execute('SELECT id,slug,name,timezone,desired_state FROM stations ORDER BY id');result['stations']=c.fetchall()
 c.execute("SELECT count(*) FROM selection_decisions WHERE status='started'");result['confirmed_history']=c.fetchone()[0]
 c.execute('SELECT id,email,active,installation_admin FROM admin_users ORDER BY id');result['users']=c.fetchall()
 c.execute('SELECT values FROM installation_settings');result['settings']=c.fetchone()[0]
conn.close()
for path in Path(values.get('FREO_MEDIA_ROOT') or '/var/lib/freo/media').rglob('*'):
 if path.is_file():result['files'][str(path)]=hashlib.sha256(path.read_bytes()).hexdigest()
from freo_ops.releases import version_at
result['version']=version_at(root)
Path(sys.argv[1]).write_text(json.dumps(result,indent=2))
print(json.dumps({k:result[k] for k in ['version','stations','confirmed_history']}))
