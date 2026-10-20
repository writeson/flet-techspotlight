"""Asyncio service that populates the shared payments heatmap database.

Implements the backend half of ``docs/database-design.md``: every
``POLL_SECONDS`` seconds it inserts a batch of rows into the ``payments``
table of ``data/heatmap_data.db`` (SQLite in WAL mode), which the Flet app
in ``ui/src`` reads for its US payment heatmap.

Each batch follows the design's pattern:

- ``created_at`` is a Unix epoch timestamp spread randomly across the
  just-elapsed 5-second window,
- ``amount_cents`` is drawn randomly from 100 to 10000,
- the (state, zip) location is weighted by state population and zip rank,
  then shaped by a Gaussian ("bell curve") over the 9-5 business-hours
  window in the state's time zone -- so the wave of activity follows the
  clock time across the United States.

The 9-5 bell curve modulates *how many* records each time zone contributes
(peaking where local time is mid-window) because the spec pins every
``created_at`` to the current 5-second window. Time zones are dominant-zone
approximations (some states span two zones) with DST handled by ``zoneinfo``.

Usage (from the repo root, so the root uv environment provides the deps):

    uv run python backend/tools/main.py --once   # single batch, then exit
    uv run python backend/tools/main.py          # run until Ctrl-C
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import math
import os
import random
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import Field, SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

logger = logging.getLogger("heatmap-tools")

REPO_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = Path(
    os.environ.get("HEATMAP_DATA_DB", str(REPO_ROOT / "data" / "heatmap_data.db"))
)

POLL_SECONDS = 5.0
WINDOW_SECONDS = 5.0  # created_at values spread across this window
BATCH_SIZE = 25
AMOUNT_MIN_CENTS = 100
AMOUNT_MAX_CENTS = 10000

# Bell curve over the 9-5 business-hours window (peak at 1pm local).
BUSINESS_HOURS_CENTER = 13.0
BUSINESS_HOURS_SIGMA = 2.5
# Baseline keeps a trickle of records flowing outside business hours.
BASE_ACTIVITY = 0.05

_ZONES = {
    "ET": ZoneInfo("America/New_York"),
    "CT": ZoneInfo("America/Chicago"),
    "MT": ZoneInfo("America/Denver"),
    "PT": ZoneInfo("America/Los_Angeles"),
    "AT": ZoneInfo("America/Anchorage"),
    "HT": ZoneInfo("Pacific/Honolulu"),
}


@dataclass(frozen=True)
class StateInfo:
    """Static per-state data used to weight payment locations.

    ``zone`` is the dominant IANA time zone and ``population`` is in
    millions. ``zips`` lists representative metro zip codes, most populous
    first.
    """

    name: str
    zone: str
    population: float
    zips: tuple[str, ...]


STATES: dict[str, StateInfo] = {
    "AK": StateInfo("Alaska", "AT", 0.7, ("99501", "99801")),
    "AL": StateInfo("Alabama", "CT", 5.0, ("35203", "36602")),
    "AR": StateInfo("Arkansas", "CT", 3.0, ("72201", "72203")),
    "AZ": StateInfo("Arizona", "MT", 7.2, ("85001", "85281")),
    "CA": StateInfo("California", "PT", 39.0, ("90001", "94105", "92101")),
    "CO": StateInfo("Colorado", "MT", 5.8, ("80202", "80903")),
    "CT": StateInfo("Connecticut", "ET", 3.6, ("06103", "06901")),
    "DC": StateInfo("District of Columbia", "ET", 0.7, ("20001", "20009")),
    "DE": StateInfo("Delaware", "ET", 1.0, ("19801", "19901")),
    "FL": StateInfo("Florida", "ET", 21.5, ("33101", "32801", "33602")),
    "GA": StateInfo("Georgia", "ET", 10.7, ("30303", "31401")),
    "HI": StateInfo("Hawaii", "HT", 1.5, ("96813", "96720")),
    "IA": StateInfo("Iowa", "CT", 3.2, ("50309", "52240")),
    "ID": StateInfo("Idaho", "MT", 1.8, ("83702", "83440")),
    "IL": StateInfo("Illinois", "CT", 12.8, ("60601", "62704")),
    "IN": StateInfo("Indiana", "ET", 6.8, ("46204", "47701")),
    "KS": StateInfo("Kansas", "CT", 2.9, ("67202", "66603")),
    "KY": StateInfo("Kentucky", "ET", 4.5, ("40202", "40507")),
    "LA": StateInfo("Louisiana", "CT", 4.7, ("70112", "70802")),
    "MA": StateInfo("Massachusetts", "ET", 7.0, ("02108", "02116", "01103")),
    "MD": StateInfo("Maryland", "ET", 6.2, ("21201", "20814")),
    "ME": StateInfo("Maine", "ET", 1.4, ("04101", "04330")),
    "MI": StateInfo("Michigan", "ET", 10.1, ("48226", "48901")),
    "MN": StateInfo("Minnesota", "CT", 5.7, ("55401", "55102")),
    "MO": StateInfo("Missouri", "CT", 6.2, ("63101", "64106")),
    "MS": StateInfo("Mississippi", "CT", 2.9, ("39201", "39530")),
    "MT": StateInfo("Montana", "MT", 1.1, ("59101", "59601")),
    "NC": StateInfo("North Carolina", "ET", 10.6, ("28202", "27601")),
    "ND": StateInfo("North Dakota", "CT", 0.8, ("58102", "58501")),
    "NE": StateInfo("Nebraska", "CT", 2.0, ("68102", "68501")),
    "NH": StateInfo("New Hampshire", "ET", 1.4, ("03101", "03301")),
    "NJ": StateInfo("New Jersey", "ET", 9.3, ("07102", "08608")),
    "NM": StateInfo("New Mexico", "MT", 2.1, ("87102", "87501")),
    "NV": StateInfo("Nevada", "PT", 3.1, ("89101", "89501")),
    "NY": StateInfo("New York", "ET", 20.2, ("10001", "14604", "13202")),
    "OH": StateInfo("Ohio", "ET", 11.8, ("43215", "44114", "45202")),
    "OK": StateInfo("Oklahoma", "CT", 4.0, ("73102", "74103")),
    "OR": StateInfo("Oregon", "PT", 4.2, ("97205", "97401")),
    "PA": StateInfo("Pennsylvania", "ET", 13.0, ("19102", "15222")),
    "RI": StateInfo("Rhode Island", "ET", 1.1, ("02903", "02906")),
    "SC": StateInfo("South Carolina", "ET", 5.1, ("29401", "29201")),
    "SD": StateInfo("South Dakota", "CT", 0.9, ("57104", "57501")),
    "TN": StateInfo("Tennessee", "CT", 6.9, ("37203", "38103")),
    "TX": StateInfo("Texas", "CT", 29.1, ("77002", "75201", "78205")),
    "UT": StateInfo("Utah", "MT", 3.3, ("84101", "84401")),
    "VA": StateInfo("Virginia", "ET", 8.6, ("23219", "22201")),
    "VT": StateInfo("Vermont", "ET", 0.6, ("05401", "05601")),
    "WA": StateInfo("Washington", "PT", 7.7, ("98101", "98402")),
    "WI": StateInfo("Wisconsin", "CT", 5.9, ("53202", "53703")),
    "WV": StateInfo("West Virginia", "ET", 1.8, ("25301", "26003")),
    "WY": StateInfo("Wyoming", "MT", 0.6, ("82001", "83001")),
}


class Payment(SQLModel, table=True):
    """A single payment event feeding the heatmap."""

    __tablename__ = "payments"

    id: int | None = Field(default=None, primary_key=True)
    created_at: int  # Unix epoch seconds
    amount_cents: int  # payments are stored as integer cents
    zipcode: str
    state: str  # two-character abbreviation
    state_name: str  # full state name


@dataclass(frozen=True)
class Location:
    """A weighted (state, zip) sampling candidate."""

    state: str
    zipcode: str


def _zone_activity(zone: str, now: datetime) -> float:
    """Return the 9-5 bell-curve multiplier for a time zone right now.

    :param zone: Key into ``_ZONES``.
    :param now: The current UTC moment.
    :returns: Multiplier in ``(BASE_ACTIVITY, BASE_ACTIVITY + 1]`` -- it
        peaks where local time is mid-window (1pm) and decays toward the
        9-5 edges.
    """
    local = now.astimezone(_ZONES[zone])
    hour = local.hour + local.minute / 60
    bell = math.exp(-0.5 * ((hour - BUSINESS_HOURS_CENTER) / BUSINESS_HOURS_SIGMA) ** 2)
    return BASE_ACTIVITY + bell


def _build_location_weights(now: datetime) -> tuple[list[Location], list[float]]:
    """Build the weighted (state, zip) sampling pool for one batch.

    :param now: The current UTC moment (fixes the bell-curve phase).
    :returns: Parallel lists of candidate locations and their weights.
    """
    locations: list[Location] = []
    weights: list[float] = []
    for abbreviation, info in STATES.items():
        zone_factor = _zone_activity(info.zone, now)
        for rank, zipcode in enumerate(info.zips, start=1):
            locations.append(Location(abbreviation, zipcode))
            weights.append(info.population * zone_factor / rank)
    return locations, weights


def build_batch(*, size: int = BATCH_SIZE, now: datetime | None = None) -> list[Payment]:
    """Generate one batch of payment records per the design's pattern.

    :param size: Number of records to generate.
    :param now: Base moment for the 5-second window; defaults to now.
    :returns: The generated (unsaved) ``Payment`` rows.
    """
    now = now or datetime.now(timezone.utc)
    end = int(now.timestamp())
    start = end - int(WINDOW_SECONDS)
    locations, weights = _build_location_weights(now)
    chosen = random.choices(locations, weights=weights, k=size)
    return [
        Payment(
            created_at=random.randint(start, end),
            amount_cents=random.randint(AMOUNT_MIN_CENTS, AMOUNT_MAX_CENTS),
            zipcode=location.zipcode,
            state=location.state,
            state_name=STATES[location.state].name,
        )
        for location in chosen
    ]


def _ensure_wal() -> None:
    """Create the database file if needed and switch it to WAL mode.

    WAL is a persistent database-level setting, so setting it once at
    startup is enough; the SQLAlchemy connections then inherit it.
    """
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    try:
        connection.execute("PRAGMA journal_mode=WAL")
    finally:
        connection.close()


_engine = create_async_engine(f"sqlite+aiosqlite:///{DB_PATH}", connect_args={"timeout": 30})
_session_factory = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)


async def create_tables() -> None:
    """Create the ``payments`` table if it does not exist yet."""
    async with _engine.begin() as connection:
        await connection.run_sync(SQLModel.metadata.create_all)


async def insert_payments(payments: list[Payment]) -> None:
    """Persist one batch of payments.

    :param payments: The rows to insert; committed in a single transaction.
    """
    async with _session_factory() as session:
        session.add_all(payments)
        await session.commit()


async def run(*, once: bool = False) -> None:
    """Drive the poll loop that populates the payments table.

    :param once: Insert a single batch and return instead of polling.
    """
    _ensure_wal()
    await create_tables()
    while True:
        batch = build_batch()
        await insert_payments(batch)
        total_cents = sum(payment.amount_cents for payment in batch)
        logger.info("inserted %d payments ($%.2f)", len(batch), total_cents / 100)
        if once:
            return
        await asyncio.sleep(POLL_SECONDS)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--once", action="store_true", help="insert a single batch, then exit"
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        asyncio.run(run(once=args.once))
    except KeyboardInterrupt:
        logger.info("stopped")


if __name__ == "__main__":
    main()
