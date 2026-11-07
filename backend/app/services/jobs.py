"""Imports run as background jobs, so the page can show progress while they work."""
import threading
import time
import traceback
import uuid

from ..db import SessionLocal
from ..logs import log as lms_log

_JOBS: dict[str, dict] = {}
_lock = threading.Lock()
KEEP_SECONDS = 3600


def _prune() -> None:
    cutoff = time.time() - KEEP_SECONDS
    for jid in [j for j, job in _JOBS.items() if job["finished"] and job["finished"] < cutoff]:
        del _JOBS[jid]


class JobBusy(Exception):
    """An import of this type is already running."""


def start(kind: str, fn, *args, **kwargs) -> str:
    with _lock:
        if any(j["kind"] == kind and j["status"] == "running" for j in _JOBS.values()):
            raise JobBusy(kind)
    jid = uuid.uuid4().hex
    job = {"id": jid, "kind": kind, "status": "running", "done": 0, "total": 0, "step": "starting",
           "result": None, "error": None, "finished": None}
    with _lock:
        _prune()
        _JOBS[jid] = job

    def progress(done: int, total: int | None = None, step: str | None = None) -> None:
        job["done"] = done
        if total is not None:
            job["total"] = total
        if step is not None:
            job["step"] = step
            lms_log.info("%s: %s (%d of %s)", kind, step, done, job["total"])

    def run() -> None:
        db = SessionLocal()
        try:
            job["result"] = fn(db, *args, progress=progress, **kwargs)
            job["status"] = "done"
        except Exception as e:  # reported to the page, and to the terminal
            lms_log.error("%s job failed:\n%s", kind, traceback.format_exc())
            job["error"] = f"{e.__class__.__name__}: {str(e)[:300]}"
            job["status"] = "failed"
        finally:
            job["finished"] = time.time()
            db.close()

    threading.Thread(target=run, daemon=True).start()
    return jid


def get(jid: str) -> dict | None:
    job = _JOBS.get(jid)
    if job is None:
        return None
    total = job["total"] or 0
    pct = 100 if job["status"] == "done" else (min(99, int(100 * job["done"] / total)) if total else 0)
    return {"id": jid, "kind": job["kind"], "status": job["status"], "done": job["done"], "total": total,
            "percent": pct, "step": job["step"], "result": job["result"], "error": job["error"]}
