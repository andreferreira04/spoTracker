"""Shared test setup.

Runs before any app module is imported: the data folder points at a temporary
directory (never your real Documents/SpoTracker) and dialogs print instead of blocking.
"""
import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_session_dir = tempfile.mkdtemp(prefix="spotracker-tests-")
os.environ["SPOTRACKER_DATA_DIR"] = _session_dir
os.environ["SPOTRACKER_HEADLESS"] = "1"


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    """A fresh data folder for tests that start the app as a subprocess."""
    monkeypatch.setenv("SPOTRACKER_DATA_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture
def as_platform(monkeypatch):
    """as_platform("windows") makes platform_utils behave as if it ran on that OS (for OS-independent logic)."""
    import platform_utils as pu

    def switch(name):
        monkeypatch.setattr(pu, "IS_WINDOWS", name == "windows")
    return switch


SAMPLE_CSV = (
    "Artist A;Song 1;200;01-09-2026;10:00:00\n"
    "Artist A;Song 2;180;01-09-2026;10:04:00\n"
    "Artist B;Song 3;15;02-09-2026;11:00:00\n"
    "Artist B;Song 3;240;15-09-2026;12:00:00\n"
    "Árvore;Canção;120;20-09-2026;09:30:00\n"
)
