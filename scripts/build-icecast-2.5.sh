#!/usr/bin/env bash
# Build only; does not replace packages, deploy, or restart services.
# Required development packages: libigloo-dev libxml2-dev libxslt1-dev
# libvorbis-dev libogg-dev libcurl4-openssl-dev librhash-dev libssl-dev
# libtheora-dev libspeex-dev, plus build-essential/pkg-config/patch.
# libigloo-dev must match the runtime and provide igloo >= 0.9.4.
set -euo pipefail
if [[ $# != 2 ]]; then
  echo 'Usage: build-icecast-2.5.sh SOURCE_TARBALL NEW_BUILD_DIRECTORY' >&2
  exit 2
fi
archive=$(realpath "$1")
build=$(realpath -m "$2")
repo=$(cd "$(dirname "$0")/.." && pwd)
expected=d9aa07c7429aec19d950ff6fd425c371f77158cd34ff220fc191b2c186c67c7a
actual=$(sha256sum "$archive" | cut -d ' ' -f 1)
[[ "$actual" == "$expected" ]] || { echo 'Unexpected Icecast 2.5.0 source archive' >&2; exit 1; }
[[ ! -e "$build" ]] || { echo 'Build directory must not already exist' >&2; exit 1; }
pkg-config --atleast-version=0.9.4 igloo || { echo 'libigloo development headers >= 0.9.4 are required' >&2; exit 1; }
mkdir -p "$build"
tar -xzf "$archive" --strip-components=1 -C "$build"
cd "$build"
patch --batch --fuzz=0 -p1 < "$repo/deploy/icecast/patches/2.5.0-listener-locks.patch"
patch --batch --fuzz=0 -p1 < "$repo/deploy/icecast/patches/2.5.0-hosting-listeners.patch"
./configure --prefix=/usr --sysconfdir=/etc --localstatedir=/var CFLAGS='-O2 -g'
make -j1
./src/icecast -V
sha256sum ./src/icecast
