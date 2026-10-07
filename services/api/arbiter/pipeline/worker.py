"""Worker process: `python -m arbiter.pipeline.worker`.

Claims one work item at a time and runs its handler in its own transaction. A failure
rolls the step back completely (state + any enqueued follow-ups), then the item is
retried with backoff; when attempts run out the job is marked failed with the reason.
Housekeeping (expired holds, disputes, quotes, payouts sending) runs every minute.
"""

from __future__ import annotations

import logging
import os
import signal
import socket
import time
import traceback
from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from arbiter import db
from arbiter.pipeline import orchestrator
from arbiter.pipeline.queue import claim, complete, fail

log = logging.getLogger("arbiter.worker")


def _webhook(session: Session, payload: dict[str, Any]) -> None:
    from arbiter import webhooks

    webhooks.deliver(session, payload["delivery_id"])


def _handler(kind: str) -> Callable[[Session, dict[str, Any]], None] | None:
    if kind in orchestrator.HANDLERS:
        fn = orchestrator.HANDLERS[kind]
        return lambda s, p: fn(s, p["job_id"])
    if kind == "webhook.deliver":
        return _webhook
    return None


def run_one(factory: sessionmaker[Session], worker_id: str) -> bool:
    """Process one item. Returns False when the queue had nothing ready."""
    with factory() as s:
        item = claim(s, worker_id)
        if item is None:
            s.rollback()
            return False
        item_id, kind, payload = item.id, item.kind, dict(item.payload)
        s.commit()  # lease is visible to other workers

    handler = _handler(kind)
    error: str | None = None
    with factory() as s:
        try:
            if handler is None:
                raise RuntimeError(f"no handler for {kind}")
            handler(s, payload)
            s.flush()
            from arbiter.models import WorkItem

            it = s.get(WorkItem, item_id)
            assert it is not None
            complete(it)
            s.commit()
        except Exception as e:  # the step failed: nothing it did is kept
            s.rollback()
            error = f"{type(e).__name__}: {e}\n{traceback.format_exc(limit=5)}"
            log.warning("work item %s (%s) failed: %s", item_id, kind, e)

    if error is not None:
        with factory() as s:
            from arbiter.models import WorkItem

            it = s.get(WorkItem, item_id)
            assert it is not None
            dead = fail(it, error)
            if dead and kind.startswith("job.") and "job_id" in payload:
                orchestrator.fail_job(s, payload["job_id"], error.splitlines()[0])
            s.commit()
    return True


def housekeeping(factory: sessionmaker[Session]) -> None:
    from arbiter.billing import quotes
    from arbiter.community import disputes, queue

    with factory() as s:
        queue.expire_holds(s)
        disputes.expire(s)
        quotes.expire_quotes(s)
        s.commit()


def run_until_idle(factory: sessionmaker[Session] | None = None, *, max_items: int = 10_000) -> int:
    """Drain the queue synchronously (tests, CLI demo). Only items already due are run."""
    factory = factory or db.session_factory()
    n = 0
    while n < max_items and run_one(factory, "inline"):
        n += 1
    return n


def main() -> None:
    logging.basicConfig(level=os.environ.get("ARBITER_LOG_LEVEL", "INFO"))
    worker_id = f"{socket.gethostname()}:{os.getpid()}"
    factory = db.session_factory()
    stop = False

    def _stop(*_: Any) -> None:
        nonlocal stop
        stop = True

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    last_hk = 0.0
    log.info("worker %s started", worker_id)
    while not stop:
        if time.monotonic() - last_hk > 60:
            try:
                housekeeping(factory)
            except Exception:
                log.exception("housekeeping failed")
            last_hk = time.monotonic()
        if not run_one(factory, worker_id):
            time.sleep(1.0)
    log.info("worker %s stopped", worker_id)


if __name__ == "__main__":
    main()
