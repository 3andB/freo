#!/usr/bin/env python3
"""Generate the website/API release index from the exact downloadable artifact."""
import argparse
import hashlib
import json
from pathlib import Path
import tarfile
from urllib.parse import urlsplit

parser = argparse.ArgumentParser()
parser.add_argument('artifact')
parser.add_argument('--download-url', required=True)
parser.add_argument('--output', required=True)
args = parser.parse_args()
url = urlsplit(args.download_url)
if url.scheme != 'https' or not url.hostname or url.username or url.password or url.query or url.fragment:
    parser.error('Download URL must be an HTTPS URL without credentials, query or fragment')
with tarfile.open(args.artifact) as archive:
    manifest = json.load(archive.extractfile('release.json'))
if manifest['development']:
    parser.error('Development review artifacts cannot enter the public release index')
with open(args.artifact, 'rb') as stream:
    digest = hashlib.file_digest(stream, 'sha256').hexdigest()
value = dict(latest_version=manifest['version'], schema_head=manifest['schema_head'],
             platform=manifest['platform'], download_url=args.download_url,
             signature_url=args.download_url + '.asc', sha256=digest,
             supported_source_revisions=manifest['supported_source_revisions'])
with Path(args.output).open('x') as stream:
    json.dump(value, stream, indent=2)
    stream.write('\n')
