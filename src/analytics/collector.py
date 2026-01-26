import hashlib
import logging
from datetime import datetime, timedelta
from typing import Optional

import numpy as np

from ..clients.base import Market
from ..config import Config
from ..matching.matcher import EventMatch
from ..storage.database import Database

logger = logging.getLogger(__name__)


class AnalyticsCollector:
    """Collects market microstructure data for analysis."""

    def __init__(self, database: Database, config: Config):
        self.database = database
        self.config = config
        self._seen_pairs = {}  # Deduplication cache: pair_hash -> {last_seen, last_spread}

    async def record_cycle(
        self,
        kalshi_markets,
        predictit_markets,
        matches,
        opportunities,
        cycle_duration_ms,
        kalshi_api_healthy,
        predictit_api_healthy,
    ):
        """Record aggregated stats for this polling cycle."""

        # Count different opportunity types
        profitable_count = sum(1 for opp in opportunities if opp[2].is_profitable)
        inverse_count = sum(1 for opp in opportunities if opp[2].is_inverse)

        # Calculate near-misses (within 5% of threshold)
        threshold = self.config.thresholds.min_profit_pct
        near_miss_count = 0

        # Compute price correlation if we have matches
        avg_correlation = None
        avg_similarity = None
        median_spread = None

        if matches:
            # Average similarity score
            similarities = [m.similarity_score for m in matches]
            avg_similarity = np.mean(similarities)

            # Price correlation
            kalshi_prices = [m.kalshi_market.price for m in matches]
            predictit_prices = [m.polymarket_market.price for m in matches]

            if len(kalshi_prices) > 1:
                avg_correlation = np.corrcoef(kalshi_prices, predictit_prices)[0, 1]

            # Median spread
            spreads = [abs(m.kalshi_market.price - m.polymarket_market.price) for m in matches]
            median_spread = np.median(spreads)

        # Insert snapshot
        await self.database.insert_market_snapshot(
            cycle_duration_ms=cycle_duration_ms,
            kalshi_markets_count=len(kalshi_markets),
            predictit_markets_count=len(predictit_markets),
            total_matches=len(matches),
            profitable_matches=profitable_count,
            near_miss_matches=near_miss_count,
            inverse_opportunities=inverse_count,
            avg_price_correlation=avg_correlation,
            avg_similarity_score=avg_similarity,
            median_spread=median_spread,
            kalshi_api_healthy=kalshi_api_healthy,
            predictit_api_healthy=predictit_api_healthy,
        )

        logger.debug(
            f"Recorded cycle snapshot: {len(matches)} matches, "
            f"{profitable_count} profitable, {near_miss_count} near-miss"
        )

    async def record_match(self, match: EventMatch, opportunity):
        """Selectively record interesting matches."""

        if not self._is_interesting(opportunity):
            return

        pair_hash = self._compute_pair_hash(
            match.kalshi_market.market_id,
            match.polymarket_market.market_id
        )

        # Check deduplication
        gross_spread = abs(match.kalshi_market.price - match.polymarket_market.price)

        if not self._should_record(pair_hash, gross_spread):
            return

        # Determine match quality based on similarity
        if match.similarity_score >= 0.95:
            match_quality = "high"
        elif match.similarity_score >= 0.85:
            match_quality = "medium"
        else:
            match_quality = "low"

        # Extract opportunity details
        if opportunity:
            net_profit_pct = opportunity.net_profit_pct
            required_capital = opportunity.required_capital
            kalshi_fees = opportunity.kalshi_fees
            predictit_fees = opportunity.polymarket_fees
            total_fees = opportunity.total_fees
            is_profitable = opportunity.is_profitable
            is_inverse = opportunity.is_inverse
            direction = opportunity.direction

            # Check if near-miss
            threshold = self.config.thresholds.min_profit_pct
            is_near_miss = (threshold - 5.0) <= net_profit_pct < threshold
        else:
            # Non-profitable match with high similarity
            net_profit_pct = 0.0
            required_capital = 1000.0  # Default
            kalshi_fees = 0.0
            predictit_fees = 0.0
            total_fees = 0.0
            is_profitable = False
            is_inverse = False
            is_near_miss = False
            direction = "none"

        # Insert detailed match
        await self.database.insert_detailed_match(
            kalshi_market_id=match.kalshi_market.market_id,
            predictit_market_id=match.polymarket_market.market_id,
            event_description=match.kalshi_market.description,
            kalshi_price=match.kalshi_market.price,
            predictit_price=match.polymarket_market.price,
            gross_spread=gross_spread,
            net_profit_pct=net_profit_pct,
            similarity_score=match.similarity_score,
            match_quality=match_quality,
            required_capital=required_capital,
            kalshi_fees=kalshi_fees,
            predictit_fees=predictit_fees,
            total_fees=total_fees,
            is_profitable=is_profitable,
            is_near_miss=is_near_miss,
            is_inverse=is_inverse,
            direction=direction,
            kalshi_url=match.kalshi_market.url,
            predictit_url=match.polymarket_market.url,
            pair_hash=pair_hash,
        )

        logger.debug(f"Recorded detailed match: {match.kalshi_market.description[:50]}...")

    def _is_interesting(self, opportunity) -> bool:
        """Determine if match warrants detailed storage."""

        if not opportunity:
            # Could be high similarity match - check if we want to store these
            # For now, skip non-profitable matches unless we add a similarity check
            return False

        # Profitable opportunities
        if opportunity.is_profitable:
            return True

        # Near-miss opportunities (within 5% of threshold)
        threshold = self.config.thresholds.min_profit_pct
        if (threshold - 5.0) <= opportunity.net_profit_pct < threshold:
            return True

        # Inverse arbitrage (always interesting)
        if opportunity.is_inverse:
            return True

        return False

    def _should_record(self, pair_hash, current_spread) -> bool:
        """Check if we should record this observation (deduplication)."""

        if pair_hash not in self._seen_pairs:
            # First time seeing this pair
            self._seen_pairs[pair_hash] = {
                'last_seen': datetime.now(),
                'last_spread': current_spread
            }
            return True

        last_obs = self._seen_pairs[pair_hash]
        time_delta = (datetime.now() - last_obs['last_seen']).total_seconds()
        spread_delta = abs(current_spread - last_obs['last_spread'])

        # Record if: >1 hour elapsed OR spread changed >2%
        if time_delta > 3600 or spread_delta > 0.02:
            self._seen_pairs[pair_hash] = {
                'last_seen': datetime.now(),
                'last_spread': current_spread
            }
            return True

        return False

    def _compute_pair_hash(self, kalshi_id, predictit_id) -> str:
        """Generate hash for deduplication."""
        pair_str = f"{kalshi_id}:{predictit_id}"
        return hashlib.md5(pair_str.encode()).hexdigest()
