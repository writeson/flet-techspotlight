"""Shared access to the ``hotspot-data`` SQLite database for the Flet app.

Single source of the database location on the app side: the file lives at
``<repo-root>/data/hotspot-data.db`` — the same file written by the asyncio
service in ``backend/tools/main.py``. WAL journaling (enabled on both sides)
keeps concurrent read/write access from the two processes safe.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite

REPO_ROOT = Path(__file__).resolve().parents[2]


def _db_path() -> Path:
    """Resolve the database location, honouring ``HOTSPOT_DATA_DB``."""
    env = os.environ.get("HOTSPOT_DATA_DB")
    return Path(env) if env else REPO_ROOT / "data" / "hotspot-data.db"


DB_PATH = _db_path()


@asynccontextmanager
async def open_db() -> AsyncIterator[aiosqlite.Connection]:
    """Open the shared database with concurrency-friendly pragmas.

    :returns: An async context manager yielding an open ``aiosqlite``
        connection in WAL mode; the connection is closed on exit.
    """
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = await aiosqlite.connect(DB_PATH)
    try:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA busy_timeout=5000")
        yield db
    finally:
        await db.close()


async def load_hotspots_text() -> str:
    """Summarise the hotspot rows for display, tolerating a missing DB.

    :returns: A one-line ``name (status), ...`` summary, or a hint to run
        the backend tool when the database does not exist yet.
    """
    if not DB_PATH.exists():
        return "no hotspot data yet — run backend/tools/main.py"
    try:
        async with open_db() as db:
            async with db.execute(
                "SELECT name, status FROM hotspots ORDER BY name"
            ) as cursor:
                rows = await cursor.fetchall()
    except aiosqlite.Error:
        return "hotspot data unavailable"
    if not rows:
        return "no hotspots yet — run backend/tools/main.py"
    return ", ".join(f"{name} ({status})" for name, status in rows)
