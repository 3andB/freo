"""Acceptance-only SIGKILL after real migrations, before release activation."""
import os,sys,signal,subprocess
assert subprocess.check_output(['hostname'],text=True).strip()=='Freo-v1-Test-1'
os.chdir('/root/freo-v1-source');sys.path.insert(0,os.getcwd())
from freo_ops import recovery
from freo_ops.__main__ import main
original=recovery.run
def interrupted(args,**kwargs):
 result=original(args,**kwargs)
 if args[-2:]==['db','upgrade']:
  os.kill(os.getpid(),signal.SIGKILL)
 return result
recovery.run=interrupted
main(['upgrade','/root/freo-v1-candidate-6.tar.gz','--signature','/root/freo-v1-candidate-6.tar.gz.sig',
 '--keyring','/root/freo-upgrade-signing/test.gpg','--allow-candidate','--env-file','/opt/freo/.env',
 '--backup','/root/freo-upgrade-tests/pre-interruption.gpg','--verification-env-file','/root/freo-upgrade-preservation/verification.env',
 '--verification-directory','/root/freo-upgrade-tests/restore-interruption','--passphrase-file','/root/freo-upgrade-preservation/passphrase'])
