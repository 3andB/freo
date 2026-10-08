"""Select public test-fixture results; never copy environments/private journals."""
import json
from pathlib import Path
E=Path('/root/freo-upgrade-tests')
def read(name):return json.loads((E/name).read_text())
b=read('healthy-baseline.json')
r=dict(source_commit='83200e6508654bea13f404e9d5699a8ad3eae19d',target_commit='e6b8b47af908ecf7ad0a72f56a86a471274cbbad')
r['artifact_sha256']='4ba428aae8c1161a762375b4818baad7b5166ea65db68d7cecbc25a3c5b08149'
r['baseline']={'version':b['version'],'stations':b['stations'],'table_counts':{k:v['rows'] for k,v in b['counts'].items()},'media_sha256':b['files'],'confirmed_history':b['confirmed_history'],'original_accounts':len(b['users'])}
r['runs']={}
for name in ('final1','final2'):
 j=read(name+'-journal.json');s=read(name+'-snapshot.json')
 r['runs'][name]={'upgrade':{k:j.get(k) for k in ('operation','phase','source_revision','target_revision','version','backup','verification_database')},'preservation':read(name+'-preservation.json'),'counts_before_feature_tests':{k:v['rows'] for k,v in s['counts'].items()},'imaging':read(name+'/imaging.json'),'features':read(name+'/features.json'),'dj':read(name+'/staging-dj-results.json'),'microphone':read(name+'/microphone.json')}
r['recovery']={k:read(v) for k,v in {'interruption':'interruption-before-reboot.json','reboot':'interruption-after-reboot.json','restored_interrupted':'interrupted-recovery-check.json','browser_after_interruption':'native-browser-recoveryinterrupted.json','restored_final1':'final1-recovery-check.json'}.items()}
r['same_artifact_noop']=read('final1-noop.log')
r['checks']={'focused_upgrade_release_imaging':60,'real_postgresql':29,'installer':6,'deployed_icecast_isolated_reload_and_codecs':2,'strengthened_imaging_relationship_case':1}
r['off_server_pre_final1_backup_sha256']='5cb60355f68de52c4b05211fee84c53ef22ef1f1972ef12e8f73e171b69fe428'
(E/'public-acceptance.json').write_text(json.dumps(r,indent=2)+'\n')
print('Sanitized final acceptance evidence written')
