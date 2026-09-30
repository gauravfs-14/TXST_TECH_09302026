"""Ambient project/run ids so audit and cost records are attributed without threading ids everywhere."""

import contextvars
from collections.abc import Callable, Iterator
from concurrent.futures import Executor, Future
from contextlib import contextmanager

_project: contextvars.ContextVar[int | None] = contextvars.ContextVar("project_id", default=None)
_run: contextvars.ContextVar[int | None] = contextvars.ContextVar("run_id", default=None)


_task: contextvars.ContextVar[int | None] = contextvars.ContextVar("task_id", default=None)


def current_task() -> int | None:
    return _task.get()


@contextmanager
def task_scope(task_id: int) -> Iterator[None]:
    """Attribute live-activity events to a one-off task (a scan, a question suggestion) that is not a round.
    Kept apart from run ids so audit and cost records are never pointed at something that isn't a run."""
    tok = _task.set(task_id)
    try:
        yield
    finally:
        _task.reset(tok)


def current_ids() -> tuple[int | None, int | None]:
    return _project.get(), _run.get()


@contextmanager
def scope(project_id: int | None = None, run_id: int | None = None) -> Iterator[None]:
    t1 = _project.set(project_id)
    t2 = _run.set(run_id)
    try:
        yield
    finally:
        _run.reset(t2)
        _project.reset(t1)


def submit(pool: Executor, fn: Callable, *args, **kwargs) -> Future:
    """Submit to a thread pool while carrying the current context vars across."""
    ctx = contextvars.copy_context()
    return pool.submit(ctx.run, fn, *args, **kwargs)
