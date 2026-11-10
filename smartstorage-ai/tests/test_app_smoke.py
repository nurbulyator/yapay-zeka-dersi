"""UI smoke test: importing app.py must not scan, write or start anything."""
import importlib
import sys
import tomllib
from unittest import mock

from conftest import ROOT


def test_import_app_has_no_side_effects():
    sys.path.insert(0, str(ROOT))
    with mock.patch("smartstorage.scanner.scan", side_effect=AssertionError("scan on import")), \
         mock.patch("os.remove", side_effect=AssertionError("remove")), \
         mock.patch("shutil.move", side_effect=AssertionError("move")):
        mod = importlib.import_module("app")
    assert callable(mod.main)


def test_streamlit_bound_to_localhost_without_telemetry():
    cfg = tomllib.loads((ROOT / ".streamlit" / "config.toml").read_text(encoding="utf-8"))
    assert cfg["server"]["address"] == "localhost"
    assert cfg["browser"]["gatherUsageStats"] is False


def test_no_destructive_calls_in_package():
    bad = ("os.remove(", "os.unlink(", "shutil.rmtree(", "shutil.move(", "os.rename(",
           ".unlink(", "os.replace(", "send2trash")
    for path in (ROOT / "smartstorage").glob("*.py"):
        text = path.read_text(encoding="utf-8")
        for b in bad:
            assert b not in text, f"{b} in {path.name}"
        assert "open(" not in text or '"rb"' in text or path.name not in ("scanner.py",)
