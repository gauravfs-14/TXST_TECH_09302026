import io
import zipfile

from fastapi.testclient import TestClient

from confiance.api.app import app
from confiance.db import session_scope
from confiance.models import Deployment, Project


def test_download_includes_files_in_subfolders(tmp_path):
    pkg = tmp_path / "pkg"
    (pkg / "pages").mkdir(parents=True)
    (pkg / "site-files").mkdir()
    (pkg / "manifest.json").write_text("{}")
    (pkg / "pages" / "home.new.html").write_text("<html></html>")
    (pkg / "site-files" / "llms.txt").write_text("# Acme")
    with session_scope() as s:
        p = Project(name="Acme", domain="acme.test")
        s.add(p)
        s.flush()
        d = Deployment(project_id=p.id, kind="deploy", deployer="export", status="draft_open", external_ref=str(pkg))
        s.add(d)
        s.flush()
        did = d.id
    r = TestClient(app).get(f"/api/deployments/{did}/download")
    assert r.status_code == 200
    names = set(zipfile.ZipFile(io.BytesIO(r.content)).namelist())
    assert {"manifest.json", "pages/home.new.html", "site-files/llms.txt"} <= names
