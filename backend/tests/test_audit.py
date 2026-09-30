from sqlalchemy import update

from confiance import audit
from confiance.db import session_scope
from confiance.models import AuditEvent


def test_chain_verifies_and_detects_tampering():
    for i in range(5):
        audit.record("x", "t", {"i": i})
    assert audit.verify_chain() == {"ok": True, "checked": 5}
    with session_scope() as s:
        s.execute(update(AuditEvent).where(AuditEvent.id == 3).values(payload={"i": 99}))
    res = audit.verify_chain()
    assert not res["ok"] and res["broken_at"] == 3
