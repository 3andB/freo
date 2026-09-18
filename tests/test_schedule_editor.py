"""Pure browser editing operations, including deterministic randomized intervals."""
import shutil
import subprocess
from pathlib import Path
import pytest


def test_schedule_editor_operations():
    if not shutil.which('node'):
        pytest.skip('Node.js is required for the pure editor regression suite')
    result=subprocess.run(['node','--test',str(Path(__file__).with_name('schedule_editor.test.cjs'))],capture_output=True,text=True)
    assert result.returncode==0,result.stdout+result.stderr
