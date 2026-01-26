"""SQLite database operations for arbitrage opportunities."""

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import aiosqlite

logger = logging.getLogger(__name__)


@dataclass
class HistoricalStats:
    """Historical arbitrage statistics."""

    total_opportunities: int
    total_potential_profit: float
    average_profit_pct: float


class Database:
    """Async SQLite database for arbitrage opportunities."""

    def __init__(self, db_path: Path = Path("data/arbitrage.db")):
        """
        Initialize database.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path
        self.db: Optional[aiosqlite.Connection] = None

        # Ensure data directory exists
        db_path.parent.mkdir(parents=True, exist_ok=True)

    async def connect(self):
        """Connect to database and initialize schema."""
        self.db = await aiosqlite.connect(self.db_path)
        await self._init_schema()
        logger.info(f"Connected to database: {self.db_path}")

    async def close(self):
        """Close database connection."""
        if self.db:
            await self.db.close()
            logger.info("Database connection closed")

    async def _init_schema(self):
        """Initialize database schema if it doesn't exist."""
        if not self.db:
            raise RuntimeError("Database not connected")

        # Existing arbitrage_opportunities table
        await self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS arbitrage_opportunities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME NOT NULL,
                kalshi_market_id TEXT NOT NULL,
                polymarket_market_id TEXT NOT NULL,
                event_description TEXT NOT NULL,
                kalshi_price REAL NOT NULL,
                polymarket_price REAL NOT NULL,
                kalshi_probability REAL NOT NULL,
                polymarket_probability REAL NOT NULL,
                net_profit_pct REAL NOT NULL,
                required_capital REAL NOT NULL,
                capital_tier INTEGER NOT NULL,
                kalshi_url TEXT NOT NULL,
                polymarket_url TEXT NOT NULL,
                direction TEXT NOT NULL,
                similarity_score REAL NOT NULL
            )
            """
        )

        # New: Aggregated market snapshots per cycle
        await self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS market_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME NOT NULL,
                cycle_duration_ms INTEGER NOT NULL,
                kalshi_markets_count INTEGER NOT NULL,
                predictit_markets_count INTEGER NOT NULL,
                total_matches INTEGER NOT NULL,
                profitable_matches INTEGER NOT NULL,
                near_miss_matches INTEGER NOT NULL,
                inverse_opportunities INTEGER NOT NULL,
                avg_price_correlation REAL,
                avg_similarity_score REAL,
                median_spread REAL,
                kalshi_api_healthy BOOLEAN NOT NULL,
                predictit_api_healthy BOOLEAN NOT NULL
            )
            """
        )

        # New: Detailed records for interesting matches
        await self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS detailed_matches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME NOT NULL,
                kalshi_market_id TEXT NOT NULL,
                predictit_market_id TEXT NOT NULL,
                event_description TEXT NOT NULL,
                kalshi_price REAL NOT NULL,
                predictit_price REAL NOT NULL,
                gross_spread REAL NOT NULL,
                net_profit_pct REAL NOT NULL,
                similarity_score REAL NOT NULL,
                match_quality TEXT NOT NULL,
                required_capital REAL NOT NULL,
                kalshi_fees REAL NOT NULL,
                predictit_fees REAL NOT NULL,
                total_fees REAL NOT NULL,
                is_profitable BOOLEAN NOT NULL,
                is_near_miss BOOLEAN NOT NULL,
                is_inverse BOOLEAN NOT NULL,
                direction TEXT NOT NULL,
                kalshi_url TEXT NOT NULL,
                predictit_url TEXT NOT NULL,
                pair_hash TEXT NOT NULL
            )
            """
        )

        # New: Price history for tracking spread evolution over time
        await self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS price_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME NOT NULL,
                pair_hash TEXT NOT NULL,
                kalshi_market_id TEXT NOT NULL,
                predictit_market_id TEXT NOT NULL,
                event_description TEXT NOT NULL,
                kalshi_price REAL NOT NULL,
                predictit_price REAL NOT NULL,
                spread REAL NOT NULL,
                similarity_score REAL NOT NULL
            )
            """
        )

        # Create indexes for fast queries
        await self.db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_timestamp
            ON arbitrage_opportunities(timestamp)
            """
        )

        await self.db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_profit
            ON arbitrage_opportunities(net_profit_pct)
            """
        )

        await self.db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_snapshot_timestamp
            ON market_snapshots(timestamp)
            """
        )

        await self.db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_detailed_timestamp
            ON detailed_matches(timestamp)
            """
        )

        await self.db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_detailed_profitable
            ON detailed_matches(is_profitable)
            """
        )

        await self.db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_detailed_pair_hash
            ON detailed_matches(pair_hash, timestamp)
            """
        )

        await self.db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_price_history_pair
            ON price_history(pair_hash, timestamp)
            """
        )

        await self.db.commit()
        logger.debug("Database schema initialized")

    async def insert_opportunity(
        self,
        kalshi_market_id: str,
        polymarket_market_id: str,
        event_description: str,
        kalshi_price: float,
        polymarket_price: float,
        net_profit_pct: float,
        required_capital: float,
        capital_tier: int,
        kalshi_url: str,
        polymarket_url: str,
        direction: str,
        similarity_score: float,
    ) -> int:
        """
        Insert arbitrage opportunity into database.

        Args:
            kalshi_market_id: Kalshi market ID
            polymarket_market_id: Polymarket market ID
            event_description: Human-readable event description
            kalshi_price: Kalshi YES price
            polymarket_price: Polymarket YES price
            net_profit_pct: Net profit percentage after fees
            required_capital: Required capital for trade
            capital_tier: Tier index (0, 1, 2, etc.)
            kalshi_url: URL to Kalshi market
            polymarket_url: URL to Polymarket market
            direction: Trade direction
            similarity_score: Event match similarity score

        Returns:
            Row ID of inserted record
        """
        if not self.db:
            raise RuntimeError("Database not connected")

        cursor = await self.db.execute(
            """
            INSERT INTO arbitrage_opportunities (
                timestamp, kalshi_market_id, polymarket_market_id,
                event_description, kalshi_price, polymarket_price,
                kalshi_probability, polymarket_probability,
                net_profit_pct, required_capital, capital_tier,
                kalshi_url, polymarket_url, direction, similarity_score
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now().isoformat(),
                kalshi_market_id,
                polymarket_market_id,
                event_description,
                kalshi_price,
                polymarket_price,
                kalshi_price,  # Probability same as price for binary markets
                polymarket_price,
                net_profit_pct,
                required_capital,
                capital_tier,
                kalshi_url,
                polymarket_url,
                direction,
                similarity_score,
            ),
        )

        await self.db.commit()
        return cursor.lastrowid

    async def get_historical_stats(self) -> HistoricalStats:
        """
        Get historical statistics about arbitrage opportunities.

        Returns:
            HistoricalStats object
        """
        if not self.db:
            raise RuntimeError("Database not connected")

        cursor = await self.db.execute(
            """
            SELECT
                COUNT(*) as total_opportunities,
                SUM(required_capital * net_profit_pct / 100) as total_potential_profit,
                AVG(net_profit_pct) as average_profit_pct
            FROM arbitrage_opportunities
            """
        )

        row = await cursor.fetchone()

        if not row or row[0] == 0:
            return HistoricalStats(
                total_opportunities=0,
                total_potential_profit=0.0,
                average_profit_pct=0.0,
            )

        return HistoricalStats(
            total_opportunities=row[0],
            total_potential_profit=row[1] or 0.0,
            average_profit_pct=row[2] or 0.0,
        )

    async def get_recent_opportunities(self, limit: int = 10) -> list[dict]:
        """
        Get most recent arbitrage opportunities.

        Args:
            limit: Maximum number of opportunities to return

        Returns:
            List of opportunity dicts
        """
        if not self.db:
            raise RuntimeError("Database not connected")

        cursor = await self.db.execute(
            """
            SELECT
                timestamp, event_description, net_profit_pct,
                required_capital, kalshi_url, polymarket_url
            FROM arbitrage_opportunities
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (limit,),
        )

        rows = await cursor.fetchall()

        opportunities = []
        for row in rows:
            opportunities.append(
                {
                    "timestamp": row[0],
                    "event_description": row[1],
                    "net_profit_pct": row[2],
                    "required_capital": row[3],
                    "kalshi_url": row[4],
                    "polymarket_url": row[5],
                }
            )

        return opportunities

    async def insert_market_snapshot(
        self,
        cycle_duration_ms,
        kalshi_markets_count,
        predictit_markets_count,
        total_matches,
        profitable_matches,
        near_miss_matches,
        inverse_opportunities,
        avg_price_correlation,
        avg_similarity_score,
        median_spread,
        kalshi_api_healthy,
        predictit_api_healthy,
    ):
        """Insert aggregated market snapshot for current cycle."""
        if not self.db:
            raise RuntimeError("Database not connected")

        cursor = await self.db.execute(
            """
            INSERT INTO market_snapshots (
                timestamp, cycle_duration_ms,
                kalshi_markets_count, predictit_markets_count,
                total_matches, profitable_matches, near_miss_matches,
                inverse_opportunities, avg_price_correlation,
                avg_similarity_score, median_spread,
                kalshi_api_healthy, predictit_api_healthy
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now().isoformat(),
                cycle_duration_ms,
                kalshi_markets_count,
                predictit_markets_count,
                total_matches,
                profitable_matches,
                near_miss_matches,
                inverse_opportunities,
                avg_price_correlation,
                avg_similarity_score,
                median_spread,
                kalshi_api_healthy,
                predictit_api_healthy,
            ),
        )

        await self.db.commit()
        return cursor.lastrowid

    async def insert_detailed_match(
        self,
        kalshi_market_id,
        predictit_market_id,
        event_description,
        kalshi_price,
        predictit_price,
        gross_spread,
        net_profit_pct,
        similarity_score,
        match_quality,
        required_capital,
        kalshi_fees,
        predictit_fees,
        total_fees,
        is_profitable,
        is_near_miss,
        is_inverse,
        direction,
        kalshi_url,
        predictit_url,
        pair_hash,
    ):
        """Insert detailed match record for interesting opportunity."""
        if not self.db:
            raise RuntimeError("Database not connected")

        cursor = await self.db.execute(
            """
            INSERT INTO detailed_matches (
                timestamp, kalshi_market_id, predictit_market_id,
                event_description, kalshi_price, predictit_price,
                gross_spread, net_profit_pct, similarity_score,
                match_quality, required_capital, kalshi_fees,
                predictit_fees, total_fees, is_profitable,
                is_near_miss, is_inverse, direction,
                kalshi_url, predictit_url, pair_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now().isoformat(),
                kalshi_market_id,
                predictit_market_id,
                event_description,
                kalshi_price,
                predictit_price,
                gross_spread,
                net_profit_pct,
                similarity_score,
                match_quality,
                required_capital,
                kalshi_fees,
                predictit_fees,
                total_fees,
                is_profitable,
                is_near_miss,
                is_inverse,
                direction,
                kalshi_url,
                predictit_url,
                pair_hash,
            ),
        )

        await self.db.commit()
        return cursor.lastrowid

    async def insert_price_history(
        self,
        pair_hash,
        kalshi_market_id,
        predictit_market_id,
        event_description,
        kalshi_price,
        predictit_price,
        similarity_score,
    ):
        """Insert price history record for tracking spread evolution."""
        if not self.db:
            raise RuntimeError("Database not connected")

        spread = abs(kalshi_price - predictit_price)

        cursor = await self.db.execute(
            """
            INSERT INTO price_history (
                timestamp, pair_hash, kalshi_market_id, predictit_market_id,
                event_description, kalshi_price, predictit_price,
                spread, similarity_score
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now().isoformat(),
                pair_hash,
                kalshi_market_id,
                predictit_market_id,
                event_description,
                kalshi_price,
                predictit_price,
                spread,
                similarity_score,
            ),
        )

        await self.db.commit()
        return cursor.lastrowid
