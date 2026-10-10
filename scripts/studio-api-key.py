#!/usr/bin/env python3
"""Manage the root-owned Freo Studio release API credential."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from freo_ops import studio_access


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('create', help='Create the first key; print its secret once')
    commands.add_parser('rotate', help='Create a second key; revoke the old key after Studio switches')
    revoke = commands.add_parser('revoke', help='Revoke a key immediately')
    revoke.add_argument('key_id')
    commands.add_parser('list', help='List key IDs and status, never token values')
    args = parser.parse_args()
    try:
        if args.command in ('create', 'rotate'):
            identifier, token = studio_access.create_key(rotate=args.command == 'rotate')
            print(json.dumps({'name': studio_access.NAME, 'key_id': identifier, 'api_key': token}))
        elif args.command == 'revoke':
            studio_access.revoke_key(args.key_id)
            print(json.dumps({'key_id': args.key_id, 'revoked': True}))
        else:
            value = studio_access.keys()
            print(json.dumps({'keys': [{key: row[key] for key in ('id', 'name', 'created_at', 'revoked_at')}
                                       for row in value['keys']]}))
    except studio_access.AccessError as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
