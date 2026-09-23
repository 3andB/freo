#!/usr/bin/env python3
"""Expose fixture failures in CI annotations and its human-readable job summary."""
import argparse
import os
from pathlib import Path
import xml.etree.ElementTree as ET

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('xml', type=Path)
parser.add_argument('--setup-log', type=Path)
args = parser.parse_args()
def escaped(value):
    return value.replace('%', '%25').replace('\r', '%0D').replace('\n', '%0A')
if args.xml.exists():
    cases = ET.parse(args.xml).findall('.//testcase')
    failures = [(c, c.find('failure') if c.find('failure') is not None else c.find('error')) for c in cases]
    failures = [(c, f) for c, f in failures if f is not None]
    skipped = sum(c.find('skipped') is not None for c in cases)
    summary = f'{len(cases)-len(failures)-skipped} passed; {len(failures)} failed; {skipped} skipped.\n'
    for case, failure in failures:
        name = case.get('classname', '') + '::' + case.get('name', '')
        detail = (failure.text or failure.get('message', ''))[-5500:]
        print('::error::' + escaped(name + '\n' + detail))
        summary += '\n- `' + name.replace('`', '') + '`\n'
    print(summary)
elif args.setup_log and args.setup_log.exists():
    summary = 'Tests did not run. Runner setup failed; see the setup log artifact.\n'
    print('::error::' + escaped(summary + args.setup_log.read_text(errors='replace')[-5500:]))
else:
    summary = 'No completed test report is available.\n'
if os.environ.get('GITHUB_STEP_SUMMARY'):
    with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as output:
        output.write(summary)
