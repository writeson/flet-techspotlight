"""Shared access to the payments heatmap SQLite database for the Flet app.

Single source of the database location on the app side: the file lives at
``<repo-root>/data/heatmap_data.db`` — the same file written by the asyncio
service in ``backend/tools/main.py`` (see ``docs/database-design.md``). WAL
journaling (persistent, enabled by the writer) plus a busy timeout keeps
concurrent read/write access from the two processes safe.
"""

from __future__ import annotations

import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite

REPO_ROOT = Path(__file__).resolve().parents[2]


def _db_path() -> Path:
    """Resolve the database location, honouring ``HEATMAP_DATA_DB``."""
    env = os.environ.get("HEATMAP_DATA_DB")
    return Path(env) if env else REPO_ROOT / "data" / "heatmap_data.db"


DB_PATH = _db_path()


@asynccontextmanager
async def open_db() -> AsyncIterator[aiosqlite.Connection]:
    """Open the shared database with concurrency-friendly pragmas.

    :returns: An async context manager yielding an open ``aiosqlite``
        connection; the connection is closed on exit.
    """
    db = await aiosqlite.connect(DB_PATH)
    try:
        await db.execute("PRAGMA busy_timeout=5000")
        yield db
    finally:
        await db.close()


async def load_payments_summary() -> str:
    """Summarise recent payments for display, tolerating a missing DB.

    :returns: A one-line summary of the last hour of payments, or a hint
        to run the backend tool when the database does not exist yet.
    """
    if not DB_PATH.exists():
        return "no heatmap data yet — run backend/tools/main.py"
    try:
        async with open_db() as db:
            async with db.execute(
                "SELECT COUNT(*), COALESCE(SUM(amount_cents), 0) "
                "FROM payments WHERE created_at >= ?",
                (int(time.time()) - 3600,),
            ) as cursor:
                count, total_cents = await cursor.fetchone()
    except aiosqlite.Error:
        return "heatmap data unavailable"
    if not count:
        return "payments table is empty — run backend/tools/main.py"
    return f"{count:,} payments in the last hour · ${total_cents / 100:,.2f}"
