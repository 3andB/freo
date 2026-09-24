#!/usr/bin/env python3
"""Read-only public network integration: download/verify, NEVER install Freo.

The known 0.3.0 identity is acceptance evidence here, not bootstrap runtime policy.
Run with an unused --output directory. No Flask/application imports.
"""
import argparse
import datetime
import json
from pathlib import Path
from unittest.mock import patch

from support import load, SCRIPT

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
args.output.mkdir(mode=0o700, parents=False, exist_ok=False)
b = load()
with patch.object(b, "install", side_effect=AssertionError("Integration MUST NOT execute an installer")) as installer:
    latest = b.discover(args.output)
    release = b.discover(args.output, "0.3.0")
    version, package = b.download_assets(release, args.output)
    source, manifest = b.verify(args.output, package, version)
    expected = "f171ebac1492b6a952787f15515884f3356576bce884640357f83f3bfc292584"
    if b.sha256(args.output / package) != expected:
        raise SystemExit("STOP: 0.3.0 does not match its approved acceptance hash")
    if manifest["commit"] != "4ff69067e3a3f1b4a488b7ea8f8598ac25a27bda":
        raise SystemExit("STOP: 0.3.0 source identity mismatch")
    installer.assert_not_called()
    receipt = dict(checked_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                   bootstrap_version=b.BOOTSTRAP_VERSION, bootstrap_sha256=b.sha256(SCRIPT),
                   latest_stable=b.release_version(latest), tested_version=version,
                   source_commit=manifest["commit"], publisher_fingerprint=b.FINGERPRINT,
                   package_sha256=b.sha256(args.output / package), signature="PASS",
                   signed_manifest_files=len(manifest["files"]), safe_extraction="PASS",
                   installer_executed=False, acceptance_hash_match=True,
                   downloaded_assets={name: b.sha256(args.output / name) for name in b.assets(release)[2]})
    (args.output / "public-verification.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt, indent=2))
