#!/usr/bin/env bash
# Shared by fresh installation, release validation and staged upgrades.
set -euo pipefail
source_dir=${1:?source directory required}
venv_dir=${2:?virtual environment directory required}
mode=${3:-auto}
if [[ $mode != auto && $mode != --offline ]]; then
  echo 'Expected auto or --offline dependency installation mode.' >&2
  exit 1
fi
bundled=0
# A damaged release must never silently resolve new packages from the internet.
if [[ $mode == --offline || -e "$source_dir/release.json" || -e "$source_dir/requirements.lock" || -d "$source_dir/wheels" ]]; then
  if [[ ! -s "$source_dir/requirements.lock" || ! -d "$source_dir/wheels" ]] || ! compgen -G "$source_dir/wheels/*.whl" >/dev/null; then
    echo 'Incomplete release: requirements.lock and bundled wheels are required. Obtain a complete verified kit.' >&2
    exit 1
  fi
  bundled=1
fi
if [[ ! -x "$venv_dir/bin/python" ]]; then
  python3 -m venv "$venv_dir"
fi
checks=()
if (( bundled )); then
  "$venv_dir/bin/python" -m pip install --no-index --require-hashes --find-links "$source_dir/wheels" -r "$source_dir/requirements.lock"
  # Reject stale supplied wheelhouses that do not satisfy the source requirements,
  # including extras (the generated lock lists wheel names without extras).
  "$venv_dir/bin/python" -m pip install --no-index --find-links "$source_dir/wheels" --dry-run -r "$source_dir/requirements-live-mic.txt"
  checks=(--live-mic)
else
  if [[ ${FREO_LIVE_MIC:-0} == 1 ]]; then
    "$venv_dir/bin/python" -m pip install -r "$source_dir/requirements-live-mic.txt"
    checks=(--live-mic)
  else
    "$venv_dir/bin/python" -m pip install -r "$source_dir/requirements.txt"
  fi
fi
"$venv_dir/bin/python" -m pip check
(cd "$source_dir" && "$venv_dir/bin/python" -B -m freo_ops.dependencies "${checks[@]}")
