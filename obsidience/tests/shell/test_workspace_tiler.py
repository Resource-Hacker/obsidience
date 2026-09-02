"""Execute the workspace tiler's real QML state and geometry contract."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess

import pytest


def test_workspace_tiler_qml_contract() -> None:
    qml = shutil.which("qml6")
    if qml is None:
        pytest.skip("qml6 is not installed")

    fixture = Path(__file__).with_name("qml") / "workspace_tiler_test.qml"
    environment = os.environ.copy()
    environment["QT_QPA_PLATFORM"] = "offscreen"
    result = subprocess.run(
        [qml, "-a", "core", str(fixture)],
        capture_output=True,
        check=False,
        env=environment,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr
