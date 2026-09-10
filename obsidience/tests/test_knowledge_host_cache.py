"""Exercise entrypoint revalidation through the installed WebKit URIRequest API."""

from pathlib import Path
import subprocess

import pytest


HOST = Path(__file__).resolve().parents[1] / "shell/surfaces/knowledge/host.py"


def test_knowledge_entrypoint_uses_real_webkit_revalidation_request() -> None:
    # The desktop's distro Python owns GI; the harness venv does not. No WebView,
    # display connection, request dispatch, or presenter process is created here.
    result = subprocess.run(
        [
            "/usr/bin/python3",
            "-c",
            """
import importlib.util
import sys

try:
    import gi
    for name, version in [('Gtk', '3.0'), ('Gdk', '3.0'),
                          ('GtkLayerShell', '0.1'), ('WebKit2', '4.1')]:
        gi.require_version(name, version)
except (ImportError, ValueError):
    sys.exit(77)

spec = importlib.util.spec_from_file_location('knowledge_host', sys.argv[1])
host = importlib.util.module_from_spec(spec)
spec.loader.exec_module(host)
for surface_id in host.SURFACE_SIZES:
    request = host.KnowledgeDesktop._knowledge_request(surface_id)
    assert request.get_uri() == host.KnowledgeDesktop._knowledge_url(surface_id)
    assert request.get_http_headers().get_one('Cache-Control') == 'no-cache'
""",
            str(HOST),
        ],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if result.returncode == 77:
        pytest.skip("native WebKit desktop dependencies are not installed")
    assert result.returncode == 0, result.stdout + result.stderr
