"""Shared run budgets and bounded admission for non-cancellable synchronous LLM calls."""

from __future__ import annotations

import concurrent.futures as futures
import threading
from collections.abc import Callable

from reasoning_kernel.schemas.limits import RunLimits


class RunBoundExceeded(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class RunBudget:
    def __init__(self, limits: RunLimits) -> None:
        self.limits = limits
        self._counts: dict[str, int] = {}

    def consume(self, name: str, amount: int = 1) -> None:
        limit: int | None = getattr(self.limits, name)
        total = self._counts.get(name, 0) + amount
        if limit is not None and total > limit:
            raise RunBoundExceeded(f"run budget exceeds {name} {limit}")
        self._counts[name] = total


class ReasonerExecutor:
    """No queue: timed-out calls keep a slot until the underlying call actually returns.

    Threads cannot be killed; SDK timeouts and host process shutdown remain necessary.
    """

    def __init__(self, max_workers: int = 8) -> None:
        if max_workers < 1:
            raise ValueError("max_workers must be positive")
        self._slots = threading.BoundedSemaphore(max_workers)
        self._pool = futures.ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="rk-llm"
        )

    def call[T](self, thunk: Callable[[], T], timeout: float | None) -> T:
        if not self._slots.acquire(blocking=False):
            raise RunBoundExceeded("reasoner executor capacity exhausted")
        try:
            future = self._pool.submit(thunk)
        except RuntimeError:
            self._slots.release()
            raise RunBoundExceeded("reasoner executor closed") from None
        future.add_done_callback(lambda _: self._slots.release())
        try:
            return future.result(timeout=timeout)
        except futures.TimeoutError:
            raise RunBoundExceeded(f"reasoner call exceeded {timeout}s") from None

    def close(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)


DEFAULT_EXECUTOR = ReasonerExecutor()
