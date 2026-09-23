#!/usr/bin/env python3
"""Full candidate checks on disposable runners; never point these at production."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('suite', choices=['backend', 'browser-primary', 'browser-programming', 'audio'])
parser.add_argument('evidence', type=Path)
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
os.chdir(root)
if os.environ.get('FREO_ENV_FILE') != '/dev/null' or os.environ.get('DATABASE_URL') != 'sqlite://':
    parser.error('Use FREO_ENV_FILE=/dev/null and DATABASE_URL=sqlite:// for isolated fixtures')
evidence = args.evidence.resolve()
evidence.mkdir(parents=True, exist_ok=True)
primary = ['first_login', 'rc4', 'rc5', 'rc6', 'statistics', 'import_flow', 'import_review',
           'import_sessions', 'catalog_editor', 'sound_room', 'music_tags', 'playlists',
           'homepage', 'player_experience', 'forms', 'appearance', 'audio_settings',
           'operations', 'station_features', 'station_domains', 'central_api', 'copyright',
           'license_agreement']
primary = [f'tests/test_{name}_browser.py' for name in primary]
if args.suite == 'backend':
    excluded = ('browser', '_engine', '_audio', '_postgres', 'system_playout',
                'programme_shift', 'schedule_soak', 'schedule_scale', 'loudness_playout')
    files = [str(p) for p in sorted(Path('tests').glob('test_*.py'))
             if not any(word in p.name for word in excluded)]
    # Opt-in engine tests belong to the audio job, even when embedded in a unit module.
    os.environ.pop('FREO_SYSTEM_TEST', None)
    os.environ.pop('FREO_ENGINE_TEST', None)
elif args.suite == 'browser-primary':
    files = primary
elif args.suite == 'browser-programming':
    files = [str(p) for p in sorted(Path('tests').glob('test_*browser.py')) if str(p) not in primary]
else:
    files = ['tests/test_dj_return_audio.py', 'tests/test_booth_engine.py',
             'tests/test_live_mic.py::test_real_microphone_fade_return_and_disconnect']
    os.environ.update(FREO_SYSTEM_TEST='1', FREO_ENGINE_TEST='1')
(evidence/'files.json').write_text(json.dumps(files, indent=2) + '\n')
command = [sys.executable, '-m', 'pytest', '-q', '--tb=short', '--show-capture=no',
           '--basetemp=' + str(evidence/'fixtures'), '--junitxml=' + str(evidence/'results.xml'), *files]
with (evidence/'pytest.log').open('w') as log:
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    for line in process.stdout:
        log.write(line)
        log.flush()
        print(line, end='', flush=True)
    code = process.wait()
(evidence/'exit.txt').write_text(str(code) + '\n')
subprocess.run([sys.executable, 'scripts/summarize-tests.py', str(evidence/'results.xml')], check=False)
raise SystemExit(code)
