import pytest

from confiance import config, db


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("CONFIANCE_DATABASE_URL", f"sqlite:///{tmp_path}/t.db")
    monkeypatch.setenv("CONFIANCE_BLOB_DIR", str(tmp_path / "blobs"))
    monkeypatch.setenv("CONFIANCE_ALLOW_OFFLINE", "true")
    monkeypatch.setenv("CONFIANCE_USE_LLM_JUDGE", "false")
    monkeypatch.setenv("CONFIANCE_ENABLE_SCHEDULER", "false")
    monkeypatch.setenv("CONFIANCE_SECRETS_FILE", str(tmp_path / "secrets.json"))
    for k in ("CONFIANCE_LLM_BASE_URL", "CONFIANCE_LLM_MODEL", "CONFIANCE_LLM_API_KEY", "CONFIANCE_SEARCH_PROVIDER",
              "CONFIANCE_TAVILY_API_KEY", "CONFIANCE_SEARXNG_URL"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("CONFIANCE_SAMPLES_PER_QUESTION", "2")
    config.get_settings.cache_clear()
    db.reset_engine()
    db.init_db()
    yield
    db.reset_engine()
    config.get_settings.cache_clear()
