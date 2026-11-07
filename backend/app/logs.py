"""Terminal logging: request timings, import progress, and database calls that are slow.
Set LMS_LOG_SQL=1 to log every database call."""
import logging
import os
import time

from sqlalchemy import event

log = logging.getLogger("lms")
SLOW_SECONDS = 0.5


def setup(engine) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    trace = os.getenv("LMS_LOG_SQL") == "1"

    @event.listens_for(engine, "before_cursor_execute")
    def before(conn, cursor, statement, params, context, executemany):
        conn.info["lms_t0"] = time.perf_counter()
        if trace:
            log.info("db start  %s", " ".join(statement.split())[:100])

    @event.listens_for(engine, "after_cursor_execute")
    def after(conn, cursor, statement, params, context, executemany):
        dt = time.perf_counter() - conn.info.pop("lms_t0", time.perf_counter())
        if trace or dt >= SLOW_SECONDS:
            log.info("db %6.2fs %s", dt, " ".join(statement.split())[:100])
