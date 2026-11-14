from __future__ import annotations

import os

import pytest

from terminal_linux.state import SessionState


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Every test gets its own data directory; none touches real sessions."""
    home = tmp_path / "tl-home"
    monkeypatch.setenv("TERMINAL_LINUX_HOME", str(home))
    return home


@pytest.fixture
def fake_state() -> SessionState:
    """A session record that looks alive only where a test patches it to."""
    return SessionState(
        name="t",
        display=97,
        width=1280,
        height=800,
        xvfb_pid=os.getpid(),
        wm_pid=os.getpid(),
        created_at=0.0,
        apps=[],
    )
