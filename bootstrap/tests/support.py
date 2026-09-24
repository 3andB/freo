"""Load the embedded helper without entering its root/installation lifecycle."""
from pathlib import Path
import types

SCRIPT = Path(__file__).resolve().parents[1] / "install.sh"


def load():
    source = SCRIPT.read_text().split("<<'FREO_BOOTSTRAP_PY'\n", 1)[1].split("\nFREO_BOOTSTRAP_PY\n", 1)[0]
    module = types.ModuleType("freo_bootstrap_test_subject")
    exec(compile(source, str(SCRIPT) + ":embedded", "exec"), module.__dict__)
    return module
