"""Deterministic browser audio-clock edge cases, alongside real Chromium tests."""
from pathlib import Path
import subprocess


def test_preview_audio_clock_regressions():
    result = subprocess.run(['node', '--test', str(Path(__file__).with_name('phase2_preview.test.cjs'))],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout+result.stderr
