"""A changed development entry page must replace previously cached HTML."""
import ast
from pathlib import Path

from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.staticfiles import StaticFiles
from starlette.testclient import TestClient


def test_entry_revalidates_including_304_without_disabling_asset_cache(tmp_path):
    path = Path(__file__).parents[1] / "harness/interfaces/api/app.py"
    tree = ast.parse(path.read_text())
    node = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "ShellKnowledgeFiles")
    namespace = {"StaticFiles": StaticFiles}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"), namespace)
    (tmp_path / "index.html").write_text('<script src="/assets/current-hash.js"></script>')
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets/current-hash.js").write_text("currentBuild()")
    app = Starlette(routes=[Mount("/shell/knowledge", namespace["ShellKnowledgeFiles"](directory=tmp_path, html=True))])
    with TestClient(app) as client:
        for entry in ("/shell/knowledge/", "/shell/knowledge/index.html"):
            current = client.get(entry)
            assert current.status_code == 200
            assert current.headers["cache-control"] == "no-cache"
            assert "current-hash.js" in current.text
            retained = client.get(entry, headers={"If-None-Match": current.headers["etag"]})
            assert retained.status_code == 304
            assert retained.headers["cache-control"] == "no-cache"
        asset = client.get("/shell/knowledge/assets/current-hash.js")
        assert asset.status_code == 200
        assert "cache-control" not in asset.headers
        assert client.get("/shell/knowledge/assets/current-hash.js", headers={"If-None-Match": asset.headers["etag"]}).status_code == 304
