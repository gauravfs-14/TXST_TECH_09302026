"""Live activity for running jobs: progress counters and a feed of what is happening right now.

Kept in memory (one process) with a bounded buffer per run. It is a *view*, not a record: the durable record is
the hash-chained audit log. If the server restarts, live details for a running job are simply unavailable and the
job can be resumed from its last finished stage.

Events are emitted from anywhere (including worker threads) and attributed to the current run through the
context variables in `context.py`.
"""

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime

from .context import current_ids

# Rough share of a whole round each stage represents, so one bar can cover everything.
STAGE_WEIGHTS = [("created", 0), ("kb", 5), ("prompts", 5), ("baseline", 35), ("optimize", 20), ("candidate", 30), ("evaluate", 5)]
FINISHED_STAGES = {"awaiting_approval", "deploy", "awaiting_live", "awaiting_measure", "measure", "done"}
MAX_EVENTS = 500


@dataclass
class _Live:
    events: deque = field(default_factory=lambda: deque(maxlen=MAX_EVENTS))
    seq: int = 0
    stage: str = "created"
    stage_done: int = 0
    stage_total: int = 0
    started: float = field(default_factory=time.monotonic)
    stage_started: float = field(default_factory=time.monotonic)
    last_event: float = field(default_factory=time.monotonic)
    llm_calls: int = 0
    in_flight: int = 0
    waiting_until: float = 0.0
    waiting_reason: str = ""


_runs: dict[int, _Live] = {}
_lock = threading.Lock()
_cancelled: set[int] = set()


class RunCancelled(Exception):
    """Raised inside a running job when the person pressed Stop."""


def request_cancel(run_id: int) -> None:
    with _lock:
        _cancelled.add(run_id)


def clear_cancel(run_id: int) -> None:
    with _lock:
        _cancelled.discard(run_id)


def is_cancelled(run_id: int | None = None) -> bool:
    rid = _rid(run_id)
    return rid is not None and rid in _cancelled


def check_cancelled() -> None:
    if is_cancelled():
        raise RunCancelled()


def _get(run_id: int) -> _Live:
    return _runs.setdefault(run_id, _Live())


def _rid(run_id: int | None) -> int | None:
    return run_id if run_id is not None else current_ids()[1]


def reset(run_id: int) -> None:
    with _lock:
        _runs.pop(run_id, None)
        _cancelled.discard(run_id)


def emit(text: str, kind: str = "info", detail: dict | None = None, run_id: int | None = None) -> None:
    """kind: info | step | ask | tool | wait | warn | done | llm (llm is technical detail only)."""
    rid = _rid(run_id)
    if rid is None:
        return
    with _lock:
        live = _get(rid)
        live.seq += 1
        live.events.append({"seq": live.seq, "ts": datetime.now(UTC).replace(tzinfo=None).isoformat(), "kind": kind,
                            "text": text, "detail": detail or {}})
        live.last_event = time.monotonic()


def set_stage(run_id: int, stage: str, total: int = 0) -> None:
    with _lock:
        live = _get(run_id)
        live.stage, live.stage_done, live.stage_total = stage, 0, total
        live.stage_started = live.last_event = time.monotonic()


def set_total(total: int, run_id: int | None = None) -> None:
    rid = _rid(run_id)
    if rid is None:
        return
    with _lock:
        live = _get(rid)
        live.stage_total, live.stage_done = total, 0
        live.stage_started = time.monotonic()


def tick(n: int = 1, run_id: int | None = None) -> None:
    rid = _rid(run_id)
    if rid is None:
        return
    with _lock:
        live = _get(rid)
        live.stage_done += n
        live.last_event = time.monotonic()


def llm_started() -> int | None:
    rid = _rid(None)
    if rid is not None:
        with _lock:
            _get(rid).in_flight += 1
    return rid


def llm_finished(rid: int | None) -> None:
    if rid is not None:
        with _lock:
            live = _get(rid)
            live.in_flight = max(0, live.in_flight - 1)
            live.llm_calls += 1
            live.last_event = time.monotonic()


def waiting(seconds: float, reason: str) -> None:
    rid = _rid(None)
    if rid is None:
        return
    with _lock:
        live = _get(rid)
        live.waiting_until = max(live.waiting_until, time.monotonic() + seconds)
        live.waiting_reason = reason
    emit(f"{reason} Waiting {int(round(seconds))} seconds…", "wait", {"seconds": round(seconds, 1)})


def _percent(stage: str, frac: float) -> float:
    if stage in FINISHED_STAGES:
        return 100.0
    cum = 0.0
    for name, w in STAGE_WEIGHTS:
        if name == stage:
            return min(99.0, cum + w * max(0.0, min(1.0, frac)))
        cum += w
    return 0.0


def snapshot(run_id: int, after: int = 0) -> dict:
    with _lock:
        live = _runs.get(run_id)
        if live is None:
            return {"known": False, "events": [], "last_seq": after}
        now = time.monotonic()
        frac = (live.stage_done / live.stage_total) if live.stage_total else 0.0
        if live.stage == "optimize" and not live.stage_total:
            frac = min(0.95, live.stage_done / 12)
        pct = _percent(live.stage, frac)
        elapsed = now - live.started
        eta = None
        if 8 <= pct < 100 and elapsed > 20:
            eta = elapsed * (100 - pct) / pct
        return {
            "known": True, "stage": live.stage, "stage_done": live.stage_done, "stage_total": live.stage_total,
            "pct": round(pct, 1), "elapsed_s": int(elapsed), "eta_s": int(eta) if eta is not None else None,
            "idle_s": int(now - live.last_event), "llm_calls": live.llm_calls, "in_flight": live.in_flight,
            "waiting": {"seconds_left": int(live.waiting_until - now), "reason": live.waiting_reason} if live.waiting_until > now else None,
            "events": [e for e in live.events if e["seq"] > after], "last_seq": live.seq,
        }
