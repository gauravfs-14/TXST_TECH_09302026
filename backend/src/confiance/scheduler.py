"""Background jobs: periodic drift checks, and waking runs whose post-deploy measurement is due."""

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import select

from . import audit
from .config import get_settings
from .db import session_scope, utcnow
from .drift import monitor
from .models import Project, Run
from .pipeline import orchestrator


def drift_job() -> None:
    with session_scope() as s:
        engines = [e for p in s.scalars(select(Project)) for e in p.engines]
    engines = [e for e in engines if e["name"] != "offline"]
    if engines:
        monitor.check_all(engines)


def wake_job() -> None:
    with session_scope() as s:
        due = [r.id for r in s.scalars(select(Run).where(Run.stage == "awaiting_measure", Run.status == "waiting"))
               if r.measure_after and r.measure_after <= utcnow()]
        live = [r.id for r in s.scalars(select(Run).where(Run.stage == "awaiting_live", Run.status == "waiting"))]
    for rid in [*due, *live]:
        try:
            orchestrator.advance(rid)
        except Exception as e:  # already alerted by the orchestrator
            audit.record("scheduler.wake_failed", "scheduler", {"run_id": rid, "error": str(e)})


def build() -> BackgroundScheduler:
    cfg = get_settings()
    sched = BackgroundScheduler(daemon=True)
    sched.add_job(drift_job, "interval", minutes=cfg.drift_interval_minutes, id="drift", max_instances=1,
                  coalesce=True)
    sched.add_job(wake_job, "interval", minutes=15, id="wake", max_instances=1, coalesce=True)
    return sched
