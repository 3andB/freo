#!/usr/bin/env bash
# Isolated database, browser and short audio fixtures; no broadcast output.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
export FREO_LIVE_MIC=0 FREO_ENGINE_TEST=1
venv/bin/pytest -q \
  tests/test_booth_cue.py tests/test_cue_migration.py \
  tests/test_deck_controls.py tests/test_live_assist.py tests/test_booth_state.py \
  tests/test_cue_browser.py tests/test_cue_engine.py \
  tests/test_deck_engine.py::test_actual_worker_load_play_pause_repeat_clear_and_mode
