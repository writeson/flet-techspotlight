"""Asyncio service that maintains the shared ``hotspot-data`` SQLite database.

The database file lives at ``<repo-root>/data/hotspot-data.db``. This tool
writes to it and the Flet app in ``ui/src`` reads from it (see
``ui/src/database.py`` for the app-side access). The connection enables WAL
journaling and a busy timeout so both processes can use the file concurrently.

Usage (from the repo root, so the root uv environment provides ``aiosqlite``):

    uv run python backend/tools/main.py --once   # seed + a single pass, then exit
    uv run python backend/tools/main.py          # run the poll loop until Ctrl-C
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite

logger = logging.getLogger("hotspot-tools")

REPO_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = Path(os.environ.get("HOTSPOT_DATA_DB", str(REPO_ROOT / "data" / "hotspot-data.db")))

POLL_SECONDS = 5.0
SEED_HOTSPOTS = ("alpha", "bravo", "charlie")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS hotspots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'offline',
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    message TEXT NOT NULL
);
"""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@asynccontextmanager
async def open_db(path: Path = DB_PATH) -> AsyncIterator[aiosqlite.Connection]:
    """Open the shared database with concurrency-friendly pragmas.

    :param path: Path of the SQLite file to open. Defaults to the shared
        ``data/hotspot-data.db`` under the repository root.
    :returns: An async context manager yielding an open ``aiosqlite``
        connection in WAL mode; the connection is closed on exit.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    db = await aiosqlite.connect(path)
    try:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA busy_timeout=5000")
        await db.execute("PRAGMA synchronous=NORMAL")
        yield db
    finally:
        await db.close()


async def ensure_schema(db: aiosqlite.Connection) -> None:
    """Create the tables if they do not exist yet.

    :param db: Open database connection.
    """
    await db.executescript(_SCHEMA)
    await db.commit()


async def seed(db: aiosqlite.Connection) -> int:
    """Insert the demo hotspot rows, keeping existing ones untouched.

    :param db: Open database connection.
    :returns: Number of rows actually inserted.
    """
    now = _utc_now()
    inserted = 0
    for name in SEED_HOTSPOTS:
        cursor = await db.execute(
            "INSERT OR IGNORE INTO hotspots (name, status, updated_at) VALUES (?, 'offline', ?)",
            (name, now),
        )
        inserted += cursor.rowcount
    await db.commit()
    return inserted


async def tick(db: aiosqlite.Connection) -> str:
    """Run one work pass: toggle the least-recently-updated hotspot.

    :param db: Open database connection.
    :returns: A human-readable description of what changed.
    """
    now = _utc_now()
    async with db.execute(
        "SELECT id, name, status FROM hotspots ORDER BY updated_at, id LIMIT 1"
    ) as cursor:
        row = await cursor.fetchone()
    if row is None:
        return "no hotspots to update"
    hotspot_id, name, status = row
    new_status = "offline" if status == "online" else "online"
    await db.execute(
        "UPDATE hotspots SET status = ?, updated_at = ? WHERE id = ?",
        (new_status, now, hotspot_id),
    )
    message = f"{name} -> {new_status}"
    await db.execute("INSERT INTO events (ts, message) VALUES (?, ?)", (now, message))
    await db.commit()
    return message


async def run(*, once: bool = False) -> None:
    """Open the database and drive the poll loop.

    :param once: Run a single pass and return instead of polling forever.
    """
    async with open_db() as db:
        await ensure_schema(db)
        seeded = await seed(db)
        if seeded:
            logger.info("seeded %d hotspot(s)", seeded)
        while True:
            logger.info("tick: %s", await tick(db))
            if once:
                return
            await asyncio.sleep(POLL_SECONDS)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--once", action="store_true", help="seed and run a single pass, then exit"
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        asyncio.run(run(once=args.once))
    except KeyboardInterrupt:
        logger.info("stopped")


if __name__ == "__main__":
    main()
