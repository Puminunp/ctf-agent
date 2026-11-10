"""Import shim so tests can use scripts/check_results.py."""
import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "check_results", Path(__file__).resolve().parent.parent / "scripts" / "check_results.py")
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
check = _mod.check
