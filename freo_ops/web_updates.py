"""Root prepares immutable plans; an installation admin may queue their IDs."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import shutil
import uuid
from . import recovery
from .__main__ import configuration, passphrase
from .upgrade import upgrade, atomic_json, require_root_directory

STATE = Path('/var/lib/freo-updates')


def plan_path(identifier):
    if str(uuid.UUID(identifier)) != identifier:
        raise ValueError('Invalid plan identifier')
    return STATE / 'plans' / identifier / 'plan.json'


def prepare(args):
    STATE.mkdir(mode=0o700, exist_ok=True)
    require_root_directory(STATE, private=True)
    plans = STATE / 'plans'
    plans.mkdir(mode=0o700, exist_ok=True)
    require_root_directory(plans, private=True)
    identifier = str(uuid.uuid4())
    directory = plans / identifier
    directory.mkdir(mode=0o700)
    for source, name in ((args.artifact, 'release.tar.gz'), (args.signature, 'release.tar.gz.asc'), (args.keyring, 'publisher.gpg')):
        shutil.copyfile(source, directory / name)
        (directory / name).chmod(0o600)
    passphrase(args.passphrase_file)  # Permission/readability check; secret is never put in the plan.
    plan = dict(artifact=str(directory / 'release.tar.gz'), signature=str(directory / 'release.tar.gz.asc'),
        keyring=str(directory / 'publisher.gpg'), env_file=str(Path(args.env_file).absolute()),
        backup=str(Path(args.backup).absolute()), passphrase_file=str(Path(args.passphrase_file).absolute()),
        verification_env_file=str(Path(args.verification_env_file).absolute()),
        verification_directory=str(Path(args.verification_directory).absolute()))
    result = upgrade(plan['artifact'], plan['signature'], plan['keyring'], plan['env_file'], plan['backup'], b'',
                     plan['verification_env_file'], plan['verification_directory'], check=True)
    if result['status'] != 'preflight_passed':
        raise recovery.RecoveryError('Release is already installed; no web plan prepared')
    atomic_json(plan_path(identifier), plan)
    con = recovery.connect(configuration(args.env_file)['DATABASE_URL'])
    try:
        with con:
            with con.cursor() as cur:
                cur.execute("INSERT INTO system_upgrades (id,version,state,message) VALUES (%s,%s,'prepared',%s)",
                    (identifier, result['version'], 'Signature and compatibility checked. Backup/restore verification will run before migration.'))
    finally:
        con.close()
    print(json.dumps({'plan_id': identifier, 'version': result['version'], 'status': 'prepared'}))


def finish(url, identifier, state, message):
    con = recovery.connect(url)
    try:
        with con:
            with con.cursor() as cur:
                cur.execute('UPDATE system_upgrades SET state=%s, message=%s WHERE id=%s', (state, message, identifier))
    finally:
        con.close()


def run_once(env_file):
    if not STATE.exists():
        return
    require_root_directory(STATE, private=True)
    with (STATE / 'web-runner.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        url = configuration(env_file)['DATABASE_URL']
        con = recovery.connect(url)
        try:
            with con:
                with con.cursor() as cur:
                    # An interrupted request is never automatically replayed.
                    cur.execute("SELECT id FROM system_upgrades WHERE state='running' LIMIT 1")
                    if cur.fetchone():
                        return
                    cur.execute("SELECT id FROM system_upgrades WHERE state='queued' ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED")
                    row = cur.fetchone()
                    if row is None:
                        return
                    identifier = row[0]
                    cur.execute("UPDATE system_upgrades SET state='running', message='Maintenance in progress; check again after services return.' WHERE id=%s", (identifier,))
        finally:
            con.close()  # Critical: no worker DB client may remain during backup.
        try:
            path = plan_path(identifier)
            require_root_directory(path.parent, private=True)
            info = path.lstat()
            if path.is_symlink() or info.st_uid != 0 or info.st_mode & 0o077:
                raise recovery.RecoveryError('Upgrade plan permissions are invalid')
            plan = json.loads(path.read_text())
            if configuration(plan['env_file'])['DATABASE_URL'] != url:
                raise recovery.RecoveryError('Plan belongs to another installation')
            result = upgrade(plan['artifact'], plan['signature'], plan['keyring'], plan['env_file'], plan['backup'],
                passphrase(plan['passphrase_file']), plan['verification_env_file'], plan['verification_directory'])
            finish(url, identifier, 'complete', 'Upgrade and recovery verification completed: ' + result['version'])
        except Exception:
            finish(url, identifier, 'failed', 'Operator recovery review required. Check the private upgrade journal; do not retry automatically.')
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', required=True)
    commands = parser.add_subparsers(dest='action', required=True)
    commands.add_parser('run')
    stage = commands.add_parser('prepare')
    stage.add_argument('artifact')
    for name in ('signature', 'keyring', 'backup', 'passphrase-file', 'verification-env-file', 'verification-directory'):
        stage.add_argument('--' + name, required=True)
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error('The trusted server operator must run this command as root')
    os.umask(0o077)
    try:
        if args.action == 'prepare':
            prepare(args)
        else:
            run_once(args.env_file)
    except Exception:
        parser.exit(1, 'Upgrade runner failed; inspect private recovery state. No automatic retry.\n')


if __name__ == '__main__':
    main()
