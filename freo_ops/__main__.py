"""Run with the release's Python: python -m freo_ops --help."""
import argparse
import ast
import getpass
import json
import os
from pathlib import Path
import stat
import sys

from dotenv import dotenv_values
import psycopg2

from . import recovery


def configuration(path):
    path = Path(path).absolute()
    if not path.is_file() or path.is_symlink():
        raise recovery.RecoveryError('An explicit, existing configuration file is required')
    # No interpolation or ambient process environment overrides recovery targets.
    values = dotenv_values(path, interpolate=False)
    if not values.get('DATABASE_URL'):
        raise recovery.RecoveryError('Configuration lacks DATABASE_URL; refusing to create or guess a database')
    return values


def inventory(env_file, values):
    roots = [Path(env_file).absolute(), Path('/var/lib/freo'), Path('/etc/freo'),
             Path(values.get('FREO_MEDIA_ROOT') or '/var/lib/freo/media'),
             Path(values.get('FREO_UPLOAD_ROOT') or '/var/lib/freo/uploads')]
    for key in ('FREO_API_STATE_DIR', 'FREO_STATS_STATE_DIR', 'FREO_GEOIP_DATABASE'):
        if values.get(key):
            roots.append(Path(values[key]))
    for path in ('/etc/nginx', '/etc/letsencrypt', '/etc/postgresql'):
        if Path(path).exists():
            roots.append(Path(path))
    for pattern in ('freo*', 'icecast2.service', 'icecast2.service.d'):
        roots.extend(p for p in Path('/etc/systemd/system').glob(pattern) if not p.is_symlink())
    return recovery.normalize_roots(roots)


def active_units():
    raw = recovery.run(['systemctl', 'list-units', '--all', '--no-pager', '--output=json',
                        '--type=service', '--type=timer', 'freo*'])
    return [row['unit'] for row in json.loads(raw)
            if row['active'] not in ('inactive', 'failed')]


def installed_version():
    tree = ast.parse((Path(__file__).resolve().parents[1] / 'app/version.py').read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'VERSION' for t in node.targets):
            return ast.literal_eval(node.value)
    raise recovery.RecoveryError('Release version is missing')


def passphrase(path, confirm=False):
    if path:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
                raise recovery.RecoveryError('Passphrase file must be a private regular file (0600 or stricter)')
            secret = stream.read(4097).rstrip(b'\n')
        if len(secret) > 4096:
            raise recovery.RecoveryError('Passphrase is too long')
        return secret
    secret = getpass.getpass('Backup passphrase: ')
    if confirm and secret != getpass.getpass('Repeat backup passphrase: '):
        raise recovery.RecoveryError('Backup passphrases do not match')
    return secret.encode('utf-8')


def main(argv=None):
    parser = argparse.ArgumentParser(description='Freo offline recovery: encrypted backups and isolated restores')
    commands = parser.add_subparsers(dest='command', required=True)
    inv = commands.add_parser('inventory', help='Show configured durable roots and active Freo units')
    inv.add_argument('--env-file', required=True)
    create = commands.add_parser('backup', help='Create an encrypted backup after all Freo units/writers are stopped')
    create.add_argument('--env-file', required=True)
    create.add_argument('--output', required=True)
    create.add_argument('--include', action='append', default=[], help='Additional permanent path; repeat as needed')
    create.add_argument('--passphrase-file')
    verify = commands.add_parser('verify', help='Verify encrypted bundle integrity; this is not a restore test')
    verify.add_argument('bundle')
    verify.add_argument('--passphrase-file')
    restore = commands.add_parser('restore', help='Restore/verify a new database and a new isolated directory')
    restore.add_argument('bundle')
    restore.add_argument('--target-env-file', required=True, help='Explicit PostgreSQL maintenance connection with CREATEDB')
    restore.add_argument('--directory', required=True, help='A new path; existing paths are always refused')
    restore.add_argument('--passphrase-file')
    restore.add_argument('--preserve-ownership', action='store_true', help='Use only where saved numeric user/group IDs are valid')
    upgrade = commands.add_parser('upgrade', help='Verified, explicit maintenance-window upgrade; never resets a database')
    upgrade.add_argument('artifact')
    upgrade.add_argument('--signature', required=True)
    upgrade.add_argument('--keyring', required=True, help='Trusted publisher keyring obtained independently')
    upgrade.add_argument('--env-file', required=True)
    upgrade.add_argument('--backup', required=True)
    upgrade.add_argument('--verification-env-file', required=True)
    upgrade.add_argument('--verification-directory', required=True)
    upgrade.add_argument('--passphrase-file')
    upgrade.add_argument('--check', action='store_true')
    commands.add_parser('upgrade-status', help='Read the private upgrade journal without starting the application')
    args = parser.parse_args(argv)
    os.umask(0o077)
    try:
        if args.command == 'upgrade-status':
            path = Path('/var/lib/freo-updates/journal.json')
            result = json.loads(path.read_text()) if path.exists() else {'status': 'no_recorded_upgrade'}
            result.pop('previous_units', None)
        elif args.command == 'upgrade':
            from .upgrade import upgrade as apply_upgrade
            result = apply_upgrade(args.artifact, args.signature, args.keyring, args.env_file,
                                   args.backup, b'' if args.check else passphrase(args.passphrase_file, confirm=True),
                                   args.verification_env_file, args.verification_directory, check=args.check)
        elif args.command in ('inventory', 'backup'):
            values = configuration(args.env_file)
            roots = inventory(args.env_file, values)
            units = active_units()
            if args.command == 'inventory':
                result = dict(roots=[str(p) for p in roots], active_units=units,
                              services_stopped=not units)
            else:
                if units:
                    raise recovery.RecoveryError('Stop all Freo services/timers before backup: ' + ', '.join(units))
                result = recovery.create(values['DATABASE_URL'], roots + list(map(Path, args.include)),
                                         args.output, passphrase(args.passphrase_file, confirm=True),
                                         version=installed_version(),
                                         media_root=values.get('FREO_MEDIA_ROOT') or '/var/lib/freo/media',
                                         upload_root=values.get('FREO_UPLOAD_ROOT') or '/var/lib/freo/uploads')
                result['status'] = 'integrity_verified_restore_not_tested'
        elif args.command == 'verify':
            with recovery.unpack(args.bundle, passphrase(args.passphrase_file)) as (_, manifest):
                result = dict(backup_id=manifest['backup_id'], version=manifest['version'],
                              schema_revision=manifest['schema_revision'],
                              status='integrity_verified_restore_not_tested')
        else:
            values = configuration(args.target_env_file)
            result = recovery.restore(args.bundle, passphrase(args.passphrase_file), values['DATABASE_URL'],
                                      args.directory, preserve_ownership=args.preserve_ownership)
        print(json.dumps(result, indent=2))
        return 0
    except (recovery.RecoveryError, OSError, ValueError, KeyError, TypeError, psycopg2.Error) as error:
        # PostgreSQL and filesystem exceptions can contain private values/paths.
        message = str(error) if isinstance(error, recovery.RecoveryError) else 'Operation failed; no success recorded. Inspect the private recovery directory if present.'
        print(message, file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
