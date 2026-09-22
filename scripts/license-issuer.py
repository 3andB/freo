#!/usr/bin/env python3
"""3andB operator tool; private keys and issued licenses stay outside the repo."""
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import uuid
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.software_license import signing_bytes
from freo_ops.__main__ import passphrase

parser = argparse.ArgumentParser()
commands = parser.add_subparsers(dest='action', required=True)
generate = commands.add_parser('generate-key')
generate.add_argument('--public-key', required=True)
issue = commands.add_parser('issue')
issue.add_argument('--owner', required=True)
issue.add_argument('--paid', action='store_true', required=True, help='Confirm that the Stripe invoice was paid')
issue.add_argument('--output', required=True)
for command in (generate, issue):
    command.add_argument('--private-key', required=True)
    command.add_argument('--passphrase-file', required=True)
args = parser.parse_args()
os.umask(0o077)
secret = passphrase(args.passphrase_file)
if not secret:
    parser.error('Private key passphrase must not be empty')
private_path = Path(args.private_key).resolve()
repo = Path(__file__).resolve().parents[1]
if private_path.is_relative_to(repo):
    parser.error('Keep the private issuer key outside the source tree')
if args.action == 'generate-key':
    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes_raw()
    key_id = hashlib.sha256(public).hexdigest()[:16]
    if private_path.exists() or Path(args.public_key).exists():
        parser.error('Key output already exists')
    with private_path.open('xb') as stream:
        stream.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                      serialization.BestAvailableEncryption(secret)))
    with Path(args.public_key).open('x') as stream:
        json.dump({key_id: base64.b64encode(public).decode()}, stream, indent=2)
        stream.write('\n')
    print('Created encrypted issuer key and public verification key:', key_id)
else:
    output = Path(args.output).resolve()
    if output.is_relative_to(repo) or not 1 <= len(args.owner.strip()) <= 254:
        parser.error('Use an external output path and a nonempty purchaser name of at most 254 characters')
    if private_path.stat().st_mode & 0o077:
        parser.error('Issuer private key must have mode 0600 or stricter')
    key = serialization.load_pem_private_key(private_path.read_bytes(), password=secret)
    if not isinstance(key, Ed25519PrivateKey):
        parser.error('An Ed25519 issuer key is required')
    public = key.public_key().public_bytes_raw()
    payload = dict(license_id=str(uuid.uuid4()), owner=args.owner.strip(), issued_at=datetime.now(timezone.utc).isoformat(),
        product='Freo', edition='unlimited', updates='all-future', installations='all-owned', expires=None)
    document = dict(payload=payload, key_id=hashlib.sha256(public).hexdigest()[:16],
                    signature=base64.b64encode(key.sign(signing_bytes(payload))).decode())
    with output.open('x') as stream:
        json.dump(document, stream, indent=2); stream.write('\n')
    print('Issued license:', payload['license_id'])
