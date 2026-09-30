"""Append-only, hash-chained audit trail.

Every event stores the hash of the previous event, so any edit or deletion of a
past row breaks the chain and is detected by `verify_chain`.
"""

import hashlib
import json
import threading
from typing import Any

from sqlalchemy import select

from .context import current_ids
from .db import session_scope, utcnow
from .models import AuditEvent

GENESIS = "0" * 64
_lock = threading.Lock()


def _digest(prev_hash: str, ts: str, actor: str, action: str, project_id, run_id, payload: dict) -> str:
    body = json.dumps(
        {"prev": prev_hash, "ts": ts, "actor": actor, "action": action,
         "project_id": project_id, "run_id": run_id, "payload": payload},
        sort_keys=True, default=str,
    )
    return hashlib.sha256(body.encode()).hexdigest()


def record(action: str, actor: str = "system", payload: dict[str, Any] | None = None,
           project_id: int | None = None, run_id: int | None = None) -> int:
    ctx_project, ctx_run = current_ids()
    project_id = project_id if project_id is not None else ctx_project
    run_id = run_id if run_id is not None else ctx_run
    # Round-trip through JSON so what we hash is exactly what we store.
    payload = json.loads(json.dumps(payload or {}, default=str))
    with _lock, session_scope() as s:
        last = s.scalars(select(AuditEvent).order_by(AuditEvent.id.desc()).limit(1)).first()
        prev = last.hash if last else GENESIS
        ts = utcnow()
        h = _digest(prev, ts.isoformat(), actor, action, project_id, run_id, payload)
        ev = AuditEvent(ts=ts, project_id=project_id, run_id=run_id, actor=actor,
                        action=action, payload=payload, prev_hash=prev, hash=h)
        s.add(ev)
        s.flush()
        return ev.id


def verify_chain() -> dict:
    with session_scope() as s:
        prev = GENESIS
        count = 0
        for ev in s.scalars(select(AuditEvent).order_by(AuditEvent.id)):
            expected = _digest(prev, ev.ts.isoformat(), ev.actor, ev.action, ev.project_id, ev.run_id, ev.payload)
            if ev.prev_hash != prev or ev.hash != expected:
                return {"ok": False, "broken_at": ev.id, "checked": count}
            prev = ev.hash
            count += 1
        return {"ok": True, "checked": count}
