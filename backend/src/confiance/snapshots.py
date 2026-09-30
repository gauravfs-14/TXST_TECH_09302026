"""Content-addressed page snapshots. Blobs are immutable; versions form a parent chain per page."""

import hashlib
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import get_settings
from .models import Page, PageVersion


def _blob_path(h: str) -> Path:
    return Path(get_settings().blob_dir) / h[:2] / h


def put_blob(content: str) -> str:
    data = content.encode()
    h = hashlib.sha256(data).hexdigest()
    p = _blob_path(h)
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_bytes(data)
        tmp.replace(p)
    return h


def get_blob(h: str) -> str:
    return _blob_path(h).read_bytes().decode()


def new_version(s: Session, page: Page, content: str, source: str, *, parent_id: int | None = None,
                run_id: int | None = None, note: str = "") -> PageVersion:
    h = put_blob(content)
    n = s.scalar(select(func.max(PageVersion.version_no)).where(PageVersion.page_id == page.id)) or 0
    v = PageVersion(page_id=page.id, version_no=n + 1, blob_hash=h, source=source,
                    parent_id=parent_id, run_id=run_id, note=note)
    s.add(v)
    s.flush()
    return v


def version_content(s: Session, version_id: int) -> str:
    v = s.get(PageVersion, version_id)
    if v is None:
        raise KeyError(version_id)
    return get_blob(v.blob_hash)


def live_content(s: Session, page: Page) -> str | None:
    return version_content(s, page.live_version_id) if page.live_version_id else None
