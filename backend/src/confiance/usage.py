"""Token/cost ledger. Every model call in the system (internal agents and tested engines) lands here."""

from sqlalchemy import func, select

from .config import PRICING
from .context import current_ids
from .db import session_scope
from .models import UsageRecord


def cost_usd(model: str, inp: int, out: int, cache_read: int = 0, cache_write: int = 0) -> float:
    pin, pout = PRICING.get(model, (0.0, 0.0))
    return (inp * pin + out * pout + cache_read * pin * 0.1 + cache_write * pin * 1.25) / 1_000_000


def record(component: str, provider: str, model: str, inp: int = 0, out: int = 0,
           cache_read: int = 0, cache_write: int = 0) -> None:
    project_id, run_id = current_ids()
    with session_scope() as s:
        s.add(UsageRecord(project_id=project_id, run_id=run_id, component=component, provider=provider,
                          model=model, input_tokens=inp, output_tokens=out, cache_read_tokens=cache_read,
                          cache_write_tokens=cache_write,
                          cost_usd=cost_usd(model, inp, out, cache_read, cache_write)))


def summary(project_id: int | None = None, run_id: int | None = None) -> list[dict]:
    with session_scope() as s:
        q = select(UsageRecord.component, UsageRecord.provider, UsageRecord.model,
                   func.count(), func.sum(UsageRecord.input_tokens), func.sum(UsageRecord.output_tokens),
                   func.sum(UsageRecord.cache_read_tokens), func.sum(UsageRecord.cost_usd)
                   ).group_by(UsageRecord.component, UsageRecord.provider, UsageRecord.model)
        if project_id is not None:
            q = q.where(UsageRecord.project_id == project_id)
        if run_id is not None:
            q = q.where(UsageRecord.run_id == run_id)
        return [dict(component=c, provider=p, model=m, calls=n, input_tokens=i or 0, output_tokens=o or 0,
                     cache_read_tokens=cr or 0, cost_usd=round(cost or 0, 4))
                for c, p, m, n, i, o, cr, cost in s.execute(q)]
