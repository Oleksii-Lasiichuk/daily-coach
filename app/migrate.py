"""Apply migrations/*.sql in order, once each, recorded in schema_migrations.

Uses the direct (non-pooler) Neon host, as Neon recommends for schema changes.
Run: `uv run python -m app.migrate`
"""

from pathlib import Path

import psycopg

from app.config import get_settings

MIGRATIONS = Path(__file__).resolve().parent.parent / "migrations"


def direct_url() -> str:
    s = get_settings()
    return s.database_url_unpooled or s.database_url.replace("-pooler.", ".", 1)


def migrate() -> list[str]:
    applied_now = []
    with psycopg.connect(direct_url()) as conn:
        conn.execute("""create table if not exists schema_migrations (
            version text primary key, applied_at timestamptz not null default now())""")
        done = {r[0] for r in conn.execute("select version from schema_migrations")}
        for path in sorted(MIGRATIONS.glob("*.sql")):
            if path.name in done:
                continue
            with conn.transaction():
                conn.execute(path.read_text())
                conn.execute("insert into schema_migrations (version) values (%s)", (path.name,))
            applied_now.append(path.name)
    return applied_now


if __name__ == "__main__":
    applied = migrate()
    print("applied:", ", ".join(applied) if applied else "nothing (up to date)")
