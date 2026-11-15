"""Postgres (Neon) connection pool.

min_size=0 and a short max_idle let idle connections close, so the Neon compute can scale to
zero between uses (the free plan has a monthly compute-hours limit).
Run `uv run python -m app.db` to check the connection.
"""

from contextlib import contextmanager

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.config import get_settings

_pool: ConnectionPool | None = None


def open_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            get_settings().database_url,
            min_size=0,
            max_size=5,
            max_idle=60,
            kwargs={"row_factory": dict_row},
            check=ConnectionPool.check_connection,  # Neon may drop idle connections
            open=True,
        )
    return _pool


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


@contextmanager
def connection() -> Connection:
    with open_pool().connection() as conn:
        yield conn


if __name__ == "__main__":
    with connection() as conn:
        row = conn.execute("select current_database() as db, version() as version").fetchone()
        print(row["db"], "|", row["version"].split(",")[0])
    close_pool()
