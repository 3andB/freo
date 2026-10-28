# Disposable-host upgrade acceptance

These scripts record the 8 October 2026 test on `Freo-v1-Test-1`
(`209.38.64.12`). They are test fixtures, not customer management tools.
Destructive attachment helpers assert that hostname and retain every previous
host tree/database. Synthetic passwords in fixtures are disposable test data.
Never copy actual credentials, signing keys or raw private journals into Git.

Use the exact official 0.3.2 kit and final candidate identified in
`docs/v1-upgrade-test-report-2026-10-08.md`. Install the kit normally, complete
setup/uploads with `browser.py fresh`, populate with `seed.py`, and create the
verified custom-storage baseline with `baseline.py` and `snapshot.py`.
`baseline.py` requires protected passphrase/verification files already created
and new backup/restore destinations. Evidence lives in `/root/freo-upgrade-tests`.

The persistent tools environment used after the reboot test is
`/root/freo-upgrade-tool-venv`, with the candidate's locked application wheels,
pytest 8.3.5, Selenium 4.35.0 and requests 2.32.5. Chromium/ChromeDriver are
`/snap/chromium/current/usr/lib/chromium-browser/{chrome,chromedriver}`.
The browser resolves the public test IP to loopback; HTTP requests use the
configured Host. Keep recovery tooling outside `/tmp`: reboot cleanup removed
the original temporary test virtualenv.

Run the documented `freo_ops upgrade` command first. Then run these copied
scripts using the persistent tools Python, with a new evidence name:

```bash
python preservation-check.py final1
python imaging-check.py final1
python features.py final1
python dj.py final1
python mic.py final1
```

Order matters: imaging verifies the original music count before production
creates another song. It then fires converted legacy imaging through a real
cart and adds its converted group to the existing second-station clock, waiting
for a confirmed real-engine start. Features checks both old accounts, all
station/library/schedule/history/analytics pages, artwork responses, scoped API
access/revocation, listener-request submission, and real production/ingest.
DJ checks scoped authority, two recorded deck shows, decoded recordings and
Chromium playback. Mic sends a generated tone through actual WebRTC signaling,
Icecast and Liquidsoap, decodes the program audio and verifies return to AUTO.
It allows Icecast's initial buffered audio to drain before measuring the tone.
This does not certify physical microphone hardware, remote NAT/TURN or TLS.

`restore-baseline.py NAME [BACKUP]` verifies and attaches a matched backup while
retaining the displaced state. Use a unique alphanumeric NAME. By default it
uses the pristine `baseline.gpg`; pass the updater's actual pre-upgrade bundle
to demonstrate self-contained recovery. `recovery-check.py NAME` verifies old
version/schema, files, stations, settings, both original logins and decoded
streams; `browser.py recoveryNAME` observes original login, automated handoff
and browser monitor playback. The original official 0.3.2 fixture has saved mic
enablement but no gateway unit; its mic-leave hook blocks the extra DJ mode UI
check. Recovery deliberately tests its working AUTO path and records that
legacy limitation. Installed V1 DJ and microphone checks are separate.

`interrupt-upgrade.py` kills the actual updater after real `flask db upgrade`
returns. Update its explicit candidate/backup paths before repeating, use a new
backup/restore destination, verify phase `migration` and the maintenance marker,
verify a new upgrade refuses, reboot the disposable host, and assert no Freo
service/timer became active. Restore that operation's backup and rerun both
recovery checks. Do not run this injection on a customer installation.
