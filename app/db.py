"""Postgres (Neon) connection pool.

min_size=0 and a short max_idle let idle connections close, so the Neon compute can scale to
zero between uses (the free plan has a monthly compute-hours limit).
Run `uv run python -m app.db` to check the connection.
"""

import contextvars
import time
from contextlib import contextmanager

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.config import get_settings

_pool: ConnectionPool | None = None
# Per request: [connection checkouts, seconds inside them] for the Server-Timing header.
timing: contextvars.ContextVar[list | None] = contextvars.ContextVar("db_timing", default=None)


IDLE_CHECK_S = 20  # a connection used this recently is alive; skip the extra round trip


def _mark_used(conn: Connection) -> None:
    conn.info_used_at = time.monotonic()  # called when a connection goes back to the pool


def _check_if_idle(conn: Connection) -> None:
    if time.monotonic() - getattr(conn, "info_used_at", 0) > IDLE_CHECK_S:
        ConnectionPool.check_connection(conn)


def open_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            get_settings().database_url,
            min_size=0,
            max_size=5,
            max_idle=60,
            # autocommit: one round trip per query (no BEGIN/COMMIT); blocks that must be
            # all-or-nothing use connection(atomic=True).
            kwargs={"row_factory": dict_row, "autocommit": True},
            check=_check_if_idle,  # Neon may drop idle connections
            reset=_mark_used,
            open=True,
        )
    return _pool


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


@contextmanager
def connection(atomic: bool = False) -> Connection:
    t0, acc = time.perf_counter(), timing.get()
    try:
        with open_pool().connection() as conn:
            if atomic:
                with conn.transaction():
                    yield conn
            else:
                yield conn
    finally:
        if acc is not None:
            acc[0] += 1
            acc[1] += time.perf_counter() - t0


if __name__ == "__main__":
    with connection() as conn:
        row = conn.execute("select current_database() as db, version() as version").fetchone()
        print(row["db"], "|", row["version"].split(",")[0])
    close_pool()
