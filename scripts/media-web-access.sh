#!/usr/bin/env bash
# Grant web read access to media only. The playout control group stays private.
set -euo pipefail
media_root=${1:-/var/lib/freo/media}
[[ $(id -u) == 0 ]] || { echo 'Run as root.' >&2; exit 1; }
[[ -d $media_root && ! -L $media_root ]] || exit 1
command -v setfacl >/dev/null
# Defaults propagate to new station directories and new media files. Private
# staging directories retain mode 2700, so staged files cannot be read by web.
setfacl -m d:u:freo:r-x "$media_root"
for station in "$media_root"/*; do
  [[ -d $station && ! -L $station ]] || continue
  setfacl -m u:freo:r-x,d:u:freo:r-x "$station"
  for kind in originals imaging artwork; do
    dir="$station/$kind"
    [[ -d $dir && ! -L $dir ]] || continue
    setfacl -m u:freo:r-x,d:u:freo:r-x "$dir"
    find "$dir" -maxdepth 1 -type f -exec setfacl -m u:freo:r--,g::r-- {} +
  done
  if [[ -d $station/staging && ! -L $station/staging ]]; then
    setfacl -m d:u:freo:r-- "$station/staging"
  fi
done
