"""Import shim so the scripts/ directory can be imported as a package."""

import importlib.util
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent.parent / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def _load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(name, module)
    spec.loader.exec_module(module)
    return module


readme_table = _load("readme_table")
recheck_listed = _load("recheck_listed")
verify_repo = _load("verify_repo")
prune_unchanged_reports = _load("prune_unchanged_reports")
