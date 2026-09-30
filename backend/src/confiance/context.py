"""Ambient project/run ids so audit and cost records are attributed without threading ids everywhere."""

import contextvars
from collections.abc import Callable, Iterator
from concurrent.futures import Executor, Future
from contextlib import contextmanager

_project: contextvars.ContextVar[int | None] = contextvars.ContextVar("project_id", default=None)
_run: contextvars.ContextVar[int | None] = contextvars.ContextVar("run_id", default=None)


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
