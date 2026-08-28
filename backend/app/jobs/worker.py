"""
Background worker.

    python -m app.jobs.worker

Runs the same codebase as the API, in a separate process. Polls the queue,
claims one job at a time, dispatches it, and reports progress back to the row
so the admin UI can show a real stage name.

Deliberately single-job-at-a-time: the workload is a few dozen jobs a week,
and serial execution makes both the logs and the budget trivial to reason
about. `claim_job` uses SKIP LOCKED, so running a second worker is safe if
that ever changes.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import socket
import uuid

from app.config import get_settings
from app.jobs import queue
from app.jobs.handlers import extract_file, generate_lesson, index_lesson
from app.logging import configure_logging, get_logger

log = get_logger("worker")

# type -> coroutine(job) -> result dict
HANDLERS = {
    queue.JobType.EXTRACT_FILE: extract_file.run,
    queue.JobType.GENERATE_LESSON: generate_lesson.run,
    queue.JobType.INDEX_LESSON: index_lesson.run,
    queue.JobType.UNINDEX_LESSON: index_lesson.run_unindex,
}

# How long a running job may go without finishing before it is presumed dead.
STALE_AFTER_SECONDS = 900
REAP_EVERY_SECONDS = 120


class Worker:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.name = f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:6]}"
        self._stopping = asyncio.Event()

    def request_stop(self) -> None:
        log.info("worker_stopping", worker=self.name)
        self._stopping.set()

    async def run(self) -> None:
        log.info(
            "worker_started",
            worker=self.name,
            handlers=sorted(HANDLERS),
            llm_mode=self.settings.llm_mode,
        )

        reaper = asyncio.create_task(self._reap_loop())
        try:
            while not self._stopping.is_set():
                worked = await self._tick()
                if not worked:
                    # Nothing queued — wait, but wake immediately on shutdown.
                    with contextlib.suppress(asyncio.TimeoutError):
                        await asyncio.wait_for(
                            self._stopping.wait(),
                            timeout=self.settings.worker_poll_interval_seconds,
                        )
        finally:
            reaper.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await reaper
            log.info("worker_stopped", worker=self.name)

    async def _tick(self) -> bool:
        """Claim and run one job. Returns True if there was work."""
        try:
            job = await queue.claim(self.name, list(HANDLERS))
        except Exception:
            log.exception("claim_failed")
            await asyncio.sleep(5)
            return False

        if job is None:
            return False

        handler = HANDLERS.get(job.type)
        if handler is None:
            await queue.fail(job.id, f"No handler for job type {job.type!r}", retry=False)
            return True

        log.info("job_started", job_id=job.id, type=job.type, attempt=job.attempts)

        try:
            result = await handler(job)
            await queue.complete(job.id, result or {})

        except (
            extract_file.Terminal,
            generate_lesson.Terminal,
            index_lesson.Terminal,
        ) as exc:
            # Deterministic failure — retrying would fail identically.
            await queue.fail(job.id, str(exc), retry=False)

        except Exception as exc:
            outcome = await queue.fail(job.id, f"{type(exc).__name__}: {exc}")
            log.exception(
                "job_error", job_id=job.id, type=job.type, outcome=outcome
            )

        return True

    async def _reap_loop(self) -> None:
        """Periodically requeue jobs abandoned by a dead worker."""
        while not self._stopping.is_set():
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(
                    self._stopping.wait(), timeout=REAP_EVERY_SECONDS
                )
                return
            try:
                await queue.reap_stale(STALE_AFTER_SECONDS)
            except Exception:
                log.exception("reap_failed")


async def main() -> None:
    configure_logging()
    worker = Worker()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError, AttributeError):
            # Windows has no add_signal_handler; KeyboardInterrupt covers it.
            loop.add_signal_handler(sig, worker.request_stop)

    try:
        await worker.run()
    except KeyboardInterrupt:
        worker.request_stop()


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main())
