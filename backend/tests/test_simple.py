from fastapi.testclient import TestClient

from confiance import kb, secrets_store


def client():
    from confiance.api.app import app
    return TestClient(app)


def test_discover_uses_sitemap_then_links(monkeypatch):
    pages = {
        "https://shop.test/sitemap.xml": "<urlset><url><loc>https://shop.test/about</loc></url><url><loc>https://shop.test/logo.png</loc></url></urlset>",
        "https://shop.test/": '<a href="/contact">c</a><a href="https://other.com/x">x</a><a href="/about#team">a</a>',
    }
    monkeypatch.setattr(kb.store, "fetch_html", lambda u: pages[u] if u in pages else (_ for _ in ()).throw(RuntimeError("404")))
    found = kb.discover("shop.test")
    assert found[0] == "https://shop.test/" and "https://shop.test/about" in found and "https://shop.test/contact" in found
    assert not any("logo.png" in u or "other.com" in u for u in found)
    assert len(found) == len(set(found))


def test_config_saved_secrets_never_returned(tmp_path):
    with client() as c:
        assert c.get("/api/setup/status").json() == {"llm": False, "search": True}  # free search needs no setup
        r = c.put("/api/setup/config", json={"llm_base_url": "http://localhost:11434/v1", "llm_model": "llama3", "llm_api_key": "sk-secret-123"})
        assert r.json()["has_llm_key"] is True and r.json()["local"] is True and "sk-secret" not in r.text
        assert "sk-secret" not in c.get("/api/setup/config").text
        assert c.get("/api/setup/status").json()["llm"] is True
        assert (tmp_path / "secrets.json").stat().st_mode & 0o077 == 0  # owner-only file
        c.put("/api/setup/config", json={"llm_api_key": ""})
        assert c.get("/api/setup/config").json()["has_llm_key"] is False
        assert c.put("/api/setup/config", json={"search_provider": "nope"}).status_code == 400
        c.put("/api/setup/config", json={"search_provider": "tavily"})
        assert c.get("/api/setup/status").json()["search"] is False  # tavily needs its key
        c.put("/api/setup/config", json={"search_api_key": "tvly-x"})
        assert c.get("/api/setup/status").json()["search"] is True


def test_find_models_and_friendly_errors(monkeypatch):
    monkeypatch.setattr(secrets_store, "list_models", lambda u, k: (["llama3", "qwen"], None))
    with client() as c:
        assert c.post("/api/setup/models", json={"base_url": "http://localhost:11434/v1"}).json()["models"] == ["llama3", "qwen"]
    msg = secrets_store._friendly(Exception("Connection error."), "http://localhost:11434/v1")
    assert "Ollama" in msg
    assert "key was not accepted" in secrets_store._friendly(Exception("Error code: 401 - invalid api key"), "https://x/v1")


def test_friendly_setup_flow():
    with client() as c:
        assert c.post("/api/simple/projects", json={"business_name": "Acme", "website": "nodots"}).status_code == 400
        pid = c.post("/api/simple/projects", json={"business_name": "Acme", "website": "https://www.Acme.com/about"}).json()["id"]
        p = c.get(f"/api/projects/{pid}").json()
        assert p["domain"] == "acme.com"
        assert c.put(f"/api/projects/{pid}/simple-brief", json={"questions": ["  "]}).status_code == 400
        c.put(f"/api/projects/{pid}/simple-brief", json={
            "questions": ["who fixes pipes", "best plumber near me"], "competitors": ["https://www.rival.com/x"],
            "never_change": ["Visit fee: $89"], "never_say": ["cheapest"], "editable_pages": []})
        b = c.get(f"/api/projects/{pid}/simple-brief").json()
        assert b["questions"] == ["who fixes pipes", "best plumber near me"] and b["competitors"] == ["rival.com"]
        assert b["never_change"] == ["Visit fee: $89"]
        assert c.patch(f"/api/projects/{pid}", json={"ai_assistants": []}).status_code == 400
        assert c.post(f"/api/projects/{pid}/prepare").status_code == 409  # no AI model connected yet
