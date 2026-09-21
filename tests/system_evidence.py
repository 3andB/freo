"""Opt-in pytest plugin: preserve each failure before fixtures are torn down."""
from pathlib import Path
import json
import pytest


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    # JUnit is written at session end. Preserve completed cases even if a host
    # or command session interrupts a many-hour run before that report exists.
    xml = item.config.getoption('xmlpath', default=None)
    if xml and (report.when == 'call' or report.failed or report.skipped):
        try:
            with (Path(xml).parent/'case-results.jsonl').open('a') as output:
                output.write(json.dumps(dict(node=report.nodeid, phase=report.when,
                    outcome=report.outcome, seconds=report.duration))+'\n')
        except OSError as error:
            item.warn(pytest.PytestWarning(f'Unable to record test progress: {error}'))
    if not report.failed:
        return
    booth = item.funcargs.get('booth')
    stack = item.funcargs.get('system_stack')
    directory = (booth[3] if booth else stack.evidence if stack else item.funcargs.get('tmp_path'))
    if directory is None:
        return
    directory = Path(directory)
    try:
        (directory/'failure.txt').write_text(report.longreprtext)
        if booth and report.when == 'call':
            driver = booth[1]
            driver.save_screenshot(str(directory/'failure.png'))
            (directory/'failure.html').write_text(driver.page_source)
            (directory/'failure-console.json').write_text(json.dumps(driver.get_log('browser'), indent=2))
    except Exception as error:
        # Evidence collection must not replace the original test failure.
        item.warn(pytest.PytestWarning(f'Unable to capture all failure evidence: {error}'))
