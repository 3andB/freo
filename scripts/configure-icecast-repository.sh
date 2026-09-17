#!/usr/bin/env bash
# Xiph's official Ubuntu packages, scoped to the Icecast 2.5 series.
set -euo pipefail
[[ $EUID == 0 ]] || { echo 'Run as root.' >&2; exit 1; }
. /etc/os-release
[[ ${ID:-} == ubuntu && ${VERSION_ID:-} == 24.04 ]] || {
  echo 'This repository configuration supports Ubuntu 24.04 only.' >&2; exit 1;
}
architecture=$(dpkg --print-architecture)
[[ $architecture == amd64 || $architecture == arm64 ]] || {
  echo 'Xiph publishes these packages for amd64 and arm64 only.' >&2; exit 1;
}
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
install -d -m 0700 "$work/gnupg"
python3 - "$work/Release.key" <<'PY'
from pathlib import Path
import sys
from urllib.request import urlopen
url = 'https://download.opensuse.org/repositories/multimedia:/xiph/xUbuntu_24.04/Release.key'
with urlopen(url, timeout=30) as response:
    key = response.read(65537)
if len(key) > 65536:
    raise SystemExit('Unexpected repository key size')
Path(sys.argv[1]).write_bytes(key)
PY
fingerprint=$(gpg --homedir "$work/gnupg" --batch --show-keys --with-colons "$work/Release.key" |
  awk -F: '$1 == "fpr" { print $10; exit }')
[[ $fingerprint == 0E313DB7936B4E76E720065B77EC2301F23C6AA3 ]] || {
  echo 'Unexpected Xiph repository signing key; review upstream key rotation.' >&2; exit 1;
}
gpg --homedir "$work/gnupg" --batch --dearmor --output "$work/xiph.gpg" "$work/Release.key"
install -d -m 0755 /etc/apt/keyrings
install -m 0644 "$work/xiph.gpg" /etc/apt/keyrings/freo-xiph.gpg
cat > /etc/apt/sources.list.d/freo-xiph.sources <<EOF
Types: deb
URIs: https://download.opensuse.org/repositories/multimedia:/xiph/xUbuntu_24.04/
Suites: /
Architectures: $architecture
Signed-By: /etc/apt/keyrings/freo-xiph.gpg
EOF
cat > /etc/apt/preferences.d/freo-icecast <<'EOF'
Package: icecast2
Pin: version 2.5.*
Pin-Priority: 700

Package: libigloo0
Pin: origin download.opensuse.org
Pin-Priority: 700

Package: *
Pin: origin download.opensuse.org
Pin-Priority: -1
EOF
chmod 0644 /etc/apt/sources.list.d/freo-xiph.sources /etc/apt/preferences.d/freo-icecast
echo 'Configured signed Xiph repository for Icecast 2.5; run apt-get update before installing.'
