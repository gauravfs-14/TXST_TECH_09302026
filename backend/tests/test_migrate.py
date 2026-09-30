"""An older database must survive an upgrade with its data intact."""
import sqlite3

from confiance import config, db


def test_old_database_gains_new_columns_and_keeps_its_rows(tmp_path, monkeypatch):
    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE projects (id INTEGER PRIMARY KEY, name VARCHAR(200) NOT NULL, domain VARCHAR(255) NOT NULL,
            site_url VARCHAR(500), brand_aliases JSON, engines JSON, deploy_config JSON,
            current_brief_version INTEGER, kb_version INTEGER, created_at DATETIME);
        INSERT INTO projects VALUES (1, 'Old Co', 'old.test', 'https://old.test', '[]', '[]', '{}', 2, 1, '2026-01-01');
        CREATE TABLE pages (id INTEGER PRIMARY KEY, project_id INTEGER, url VARCHAR(1000), source_path VARCHAR(1000), live_version_id INTEGER);
        INSERT INTO pages VALUES (1, 1, 'https://old.test/', NULL, 5);
    """)
    con.commit(); con.close()
    monkeypatch.setenv("CONFIANCE_DATABASE_URL", f"sqlite:///{path}")
    config.get_settings.cache_clear()
    db.reset_engine()
    db.init_db()
    from sqlalchemy import text
    with db.session_scope() as s:
        row = s.execute(text("select name, current_brief_version, settings from projects where id=1")).one()
        assert row[0] == "Old Co" and row[1] == 2 and row[2] == "{}"  # data kept, JSON default filled in
        pg = s.execute(text("select live_version_id, kind, page_type, is_new, origin from pages where id=1")).one()
        assert tuple(pg) == (5, "page", "other", 0, "crawl")
        assert s.execute(text("select count(*) from products")).scalar() == 0  # new tables exist
    assert db.migrate() == []  # running it again changes nothing
    from confiance.models import Page, Project
    with db.session_scope() as s:  # and the ORM can read the upgraded rows
        assert s.get(Page, 1).page_type == "other" and s.get(Project, 1).settings == {}
