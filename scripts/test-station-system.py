#!/usr/bin/env python3
"""Run repeatable station tests against a frozen copy of the edited source."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import os
import tempfile
import signal


QUICK = [
    'test_station_control', 'test_playout_simulation', 'test_visual_schedule',
    'test_simple_blocks', 'test_block_scheduling', 'test_schedule_booth_integration',
    'test_deck_controls', 'test_dj_return', 'test_booth_state', 'test_booth_cue', 'test_live_assist',
    'test_event_completion', 'test_programming_refresh', 'test_schedule_regressions',
    'test_statistics', 'test_live_stress_runner',
]
INTEGRATION = [
    'test_system_playout', 'test_dj_return_audio', 'test_station_control_browser', 'test_schedule_studio_browser',
    'test_master_broadcast_browser', 'test_live_browser', 'test_cue_browser',
    'test_booth_state_browser', 'test_station_features_browser', 'test_workspace_browser',
    'test_block_scheduler_browser', 'test_simple_blocks_browser',
    'test_schedule_engine', 'test_schedule_booth_engine', 'test_cue_engine',
    'test_booth_engine', 'test_deck_engine', 'test_master_broadcast_engine',
    'test_live_mic', 'test_live_mic_browser', 'test_loudness_playout',
    'test_schedule_autosave_browser', 'test_schedule_soak', 'test_workspace_lifecycle_browser',
]


def write_status(path, result):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(result, indent=2))
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['quick', 'integration', 'soak', 'programme'])
    parser.add_argument('--seconds', type=int, default=172800, help='Soak duration; default 48 hours')
    parser.add_argument('--output', type=Path, help='New evidence directory (must not exist)')
    parser.add_argument('--media-dir', type=Path, help='Private programme media bundle with manifest.json')
    parser.add_argument('--programme-smoke', action='store_true', help='Rehearse programme with shortened copies and section intervals')
    parser.add_argument('--test', action='append', dest='selected_tests',
                        help='Run only this tests/ path or pytest node; repeat for focused reruns')
    args = parser.parse_args()
    if args.selected_tests and any(not node.startswith('tests/') or '..' in Path(node.split('::')[0]).parts
                                   for node in args.selected_tests):
        parser.error('--test must identify a test within tests/')
    if args.mode == 'soak' and args.seconds < 120:
        parser.error('Soak duration must be at least 120 seconds')
    if args.mode == 'programme':
        if not args.media_dir or not (args.media_dir/'manifest.json').is_file():
            parser.error('Programme requires --media-dir with a private manifest.json')
        if args.seconds < (300 if args.programme_smoke else 10800):
            parser.error('Programme requires three hours, or at least 300 seconds with --programme-smoke')
    root = Path(__file__).resolve().parents[1]
    evidence = (args.output or Path('/tmp') / ('freo-station-'+args.mode+'-'+
        datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S'))).resolve()
    evidence.mkdir(parents=True, exist_ok=False)
    source = evidence/'source'
    source.mkdir()
    # Existing engine fixtures append long test names and control.sock. Keep
    # their actual path below AF_UNIX's 108-byte limit, even with a long output.
    runtime = Path(tempfile.mkdtemp(prefix='fr-', dir='/tmp'))
    (evidence/'runtime').symlink_to(runtime, target_is_directory=True)
    # Include the working tree's edits and new tests, but no installation secrets,
    # live media, runtime files, or Git internals. Each run retains its exact source.
    names = subprocess.check_output(['git', 'ls-files', '-c', '-o', '--exclude-standard', '-z'], cwd=root).decode().split('\0')
    manifest = {}
    for name in sorted(set(names)):
        if not name or not (name.startswith(('app/', 'tests/', 'migrations/', 'deploy/liquidsoap/', 'scripts/'))
                            or name in ('pytest.ini', 'requirements.txt', 'requirements-dev.txt', 'wsgi.py')):
            continue
        original = root/name
        if not original.is_file() or original.is_symlink():
            continue
        target = source/name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(original, target)
        manifest[name] = hashlib.sha256(target.read_bytes()).hexdigest()
    (evidence/'source-manifest.json').write_text(json.dumps(manifest, indent=2))
    (source/'venv').symlink_to(root/'venv', target_is_directory=True)
    environment = dict(os.environ, FREO_ENV_FILE='/dev/null', FREO_LIVE_MIC='0',
                       PYTHONUNBUFFERED='1', FREO_SYSTEM_TEST='0', FREO_ENGINE_TEST='0',
                       FREO_SYSTEM_SOAK_SECONDS='0', FREO_SCHEDULE_SOAK_SECONDS='0', FREO_PROGRAMME_SECONDS='0')
    if args.mode != 'quick':
        environment.update(FREO_SYSTEM_TEST='1', FREO_ENGINE_TEST='1')
        for binary in ('liquidsoap', 'icecast2', 'ffmpeg', 'chromedriver'):
            if shutil.which(binary) is None:
                parser.error(f'Required local executable missing: {binary}')
    if args.mode == 'integration':
        environment.update(FREO_SYSTEM_SOAK_SECONDS='120', FREO_SCHEDULE_SOAK_SECONDS='65')
    if args.mode == 'soak':
        environment['FREO_SYSTEM_SOAK_SECONDS'] = str(args.seconds)
        tests = ['tests/test_system_playout.py::test_system_endurance']
    elif args.mode == 'programme':
        environment.update(FREO_PROGRAMME_SECONDS=str(args.seconds),
            FREO_PROGRAMME_MEDIA_DIR=str(args.media_dir.resolve()),
            FREO_PROGRAMME_SMOKE='1' if args.programme_smoke else '0')
        shutil.copyfile(args.media_dir/'manifest.json', evidence/'media-manifest.json')
        tests = ['tests/test_programme_shift.py::test_three_hour_programme']
    else:
        tests = ['tests/'+name+'.py' for name in (QUICK if args.mode == 'quick' else INTEGRATION)]
    if args.selected_tests:
        tests = args.selected_tests
    # The navigation diagnostic intentionally exceeds four minutes. Do not dump
    # all live Flask thread stacks mid-run merely because its work is lengthy.
    diagnostic_timeout = (args.seconds+240 if args.mode in ('soak', 'programme') else
        max(240, int(environment.get('FREO_NAVIGATION_ROUNDS', '0'))*10+120))
    command = [str(root/'venv/bin/python'), '-m', 'pytest', '-p', 'tests.system_evidence', '-q', '--tb=short',
        '-o', 'faulthandler_timeout='+str(diagnostic_timeout), '--basetemp='+str(runtime),
        '--junitxml='+str(evidence/'results.xml')]
    if args.mode in ('soak', 'programme'):
        # Avoid keeping days of successful HTTP request logs in pytest's capture.
        command += ['-s', '-o', 'log_level=WARNING']
    command += tests
    result = dict(mode=args.mode, started_at=datetime.now(timezone.utc).isoformat(),
                  command=command, source=str(source), runtime=str(runtime), runner_pid=os.getpid(),
                  selection='focused' if args.selected_tests else 'profile', status='running')
    status_path = evidence/'run.json'
    write_status(status_path, result)
    print(f'Evidence: {evidence}', flush=True)
    with (evidence/'pytest.log').open('w') as log:
        process = subprocess.Popen(command, cwd=source, env=environment, stdout=log,
            stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True)
        result['test_pid'] = process.pid
        write_status(status_path, result)
        def interrupt(signum, frame):
            raise KeyboardInterrupt
        signal.signal(signal.SIGTERM, interrupt)
        try:
            code = process.wait()
        except KeyboardInterrupt:
            process.send_signal(signal.SIGINT)
            code = process.wait()
    (evidence/'runtime').unlink()
    shutil.move(str(runtime), str(evidence/'runtime'))
    result.update(status='passed' if code == 0 else 'failed', exit_code=code,
                  runtime=str(evidence/'runtime'),
                  finished_at=datetime.now(timezone.utc).isoformat())
    write_status(status_path, result)
    print(f'{result["status"]}: {evidence / "results.xml"}', flush=True)
    return code


if __name__ == '__main__':
    sys.exit(main())
