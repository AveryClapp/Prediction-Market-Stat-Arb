"""Main orchestration loop for arbitrage detection system."""

import asyncio
import logging
import signal
import sys
from pathlib import Path
from time import time

from .alerting.discord import DiscordAlerter
from .arbitrage.calculator import calculate_arbitrage, calculate_inverse_arbitrage
from .clients.kalshi import KalshiClient
from .clients.predictit import PredictItClient
from .config import load_config
from .matching.matcher import EventMatcher
from .matching.filter import apply_filters, get_filter_summary
from .storage.database import Database
from .ui.terminal import TerminalUI

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("arbitrage.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


class ArbitrageMonitor:
    """Main arbitrage detection and monitoring system."""

    def __init__(self, config_path: Path = Path("config.yaml")):
        """
        Initialize arbitrage monitor.

        Args:
            config_path: Path to configuration file
        """
        # Load configuration
        self.config = load_config(config_path)

        # Initialize components
        self.kalshi_client = KalshiClient(
            api_key=self.config.api_keys.kalshi_api_key,
            api_secret=self.config.api_keys.kalshi_api_secret,
            max_retries=self.config.polling.max_retries,
            backoff_base=self.config.polling.backoff_base,
        )

        self.predictit_client = PredictItClient(
            max_retries=self.config.polling.max_retries,
            backoff_base=self.config.polling.backoff_base,
        )

        self.matcher = EventMatcher(
            keyword_threshold=0.2,  # 20% keyword overlap required
            semantic_threshold=self.config.thresholds.match_similarity,  # 75% semantic similarity
        )

        self.database = Database()

        self.discord = DiscordAlerter(self.config)

        self.ui = TerminalUI(self.config)

        # State
        self.running = False
        self.cycle_count = 0

    async def initialize(self):
        """Initialize all components."""
        logger.info("Initializing arbitrage monitor...")

        # Connect to database
        await self.database.connect()

        # Load historical stats
        stats = await self.database.get_historical_stats()
        self.ui.set_historical_stats(stats)

        # Log filter configuration
        filter_summary = get_filter_summary(self.config.filters)
        logger.info(f"Event filters: {filter_summary}")

        logger.info("Initialization complete")

    async def cleanup(self):
        """Cleanup resources."""
        logger.info("Cleaning up...")

        # Close clients
        await self.kalshi_client.close()
        await self.predictit_client.close()
        await self.discord.close()

        # Close database
        await self.database.close()

        # Stop UI
        self.ui.stop()

        logger.info("Cleanup complete")

    async def _polling_cycle(self):
        """Execute one polling cycle."""
        cycle_start = time()
        self.cycle_count += 1

        logger.info(f"=== Polling Cycle {self.cycle_count} ===")
        self.ui.add_log(f"Starting cycle {self.cycle_count}")

        # Update cycle progress
        self.ui.set_cycle_progress(0)
        self.ui.update()

        try:
            # Step 1: Poll Kalshi
            logger.info("Polling Kalshi...")
            self.ui.add_log("Polling Kalshi...")
            kalshi_markets = await self.kalshi_client.get_active_markets()
            kalshi_status = self.kalshi_client.get_status()
            self.ui.set_platform_status(kalshi_status, None)
            self.ui.add_log(f"Kalshi: {len(kalshi_markets)} markets")
            self.ui.update()

            # Check for platform down
            if kalshi_status.consecutive_failures >= self.config.polling.max_retries:
                await self.discord.send_platform_down_alert(
                    "Kalshi", kalshi_status.consecutive_failures
                )

            # Step 2: Poll PredictIt
            logger.info("Polling PredictIt...")
            self.ui.add_log("Polling PredictIt...")
            predictit_markets = await self.predictit_client.get_active_markets()
            predictit_status = self.predictit_client.get_status()
            self.ui.set_platform_status(kalshi_status, predictit_status)
            self.ui.add_log(f"PredictIt: {len(predictit_markets)} markets")
            self.ui.update()

            # Check for platform down
            if (
                predictit_status.consecutive_failures
                >= self.config.polling.max_retries
            ):
                await self.discord.send_platform_down_alert(
                    "PredictIt", predictit_status.consecutive_failures
                )

            # Skip matching if either platform failed
            if not kalshi_markets or not predictit_markets:
                logger.warning("Skipping cycle due to empty market data")
                self.ui.add_log("Skipping cycle - no market data")
                self.ui.update()
                return

            # Step 3: Match events
            logger.info("Matching events...")
            self.ui.add_log("Matching events...")
            self.ui.update()
            matches = self.matcher.match_events(kalshi_markets, predictit_markets)
            self.ui.add_log(f"Found {len(matches)} event matches")

            # Step 3.5: Apply user filters
            if self.config.filters.enabled:
                matches_before = len(matches)
                matches = apply_filters(matches, self.config.filters)
                self.ui.add_log(f"Filtered: {matches_before} → {len(matches)} matches")

            self.ui.update()

            # Step 4: Calculate arbitrage and find opportunities
            logger.info("Calculating arbitrage...")
            self.ui.add_log("Calculating arbitrage...")
            self.ui.update()

            opportunities = []
            monitor_opportunities = []

            for match in matches:
                # Try inverse arbitrage first (betting opposite outcomes)
                # Note: polymarket_market field now contains PredictIt markets
                opportunity = calculate_inverse_arbitrage(
                    kalshi_price=match.kalshi_market.price,
                    polymarket_price=match.polymarket_market.price,
                    kalshi_desc=match.kalshi_market.description,
                    polymarket_desc=match.polymarket_market.description,
                    config=self.config,
                    platform2_name="PredictIt",
                )

                # If not inverse, try regular arbitrage
                if opportunity is None:
                    opportunity = calculate_arbitrage(
                        kalshi_price=match.kalshi_market.price,
                        polymarket_price=match.polymarket_market.price,
                        config=self.config,
                    )

                if opportunity and opportunity.is_profitable:
                    # Get tier for this opportunity
                    tier = self.config.get_tier_for_capital(opportunity.required_capital)

                    opportunities.append(
                        (match.kalshi_market, match.polymarket_market, opportunity, tier)
                    )

                    # Store in database
                    await self.database.insert_opportunity(
                        kalshi_market_id=match.kalshi_market.market_id,
                        polymarket_market_id=match.polymarket_market.market_id,
                        event_description=match.kalshi_market.description,
                        kalshi_price=opportunity.kalshi_price,
                        polymarket_price=opportunity.polymarket_price,
                        net_profit_pct=opportunity.net_profit_pct,
                        required_capital=opportunity.required_capital,
                        capital_tier=self.config.capital_tiers.index(tier),
                        kalshi_url=match.kalshi_market.url,
                        polymarket_url=match.polymarket_market.url,
                        direction=opportunity.direction,
                        similarity_score=match.similarity_score,
                    )

                    # Send Discord alert
                    await self.discord.send_alert(
                        kalshi_market=match.kalshi_market,
                        polymarket_market=match.polymarket_market,
                        opportunity=opportunity,
                        tier=tier,
                    )

                elif opportunity and opportunity.monitor_opportunity:
                    # Track near-profitable opportunities for monitoring
                    tier = self.config.get_tier_for_capital(opportunity.required_capital)

                    monitor_opportunities.append(
                        (match.kalshi_market, match.polymarket_market, opportunity, tier)
                    )

            # Update UI with opportunities
            self.ui.set_opportunities(opportunities)
            self.ui.add_log(f"Found {len(opportunities)} arbitrage opportunities")

            if monitor_opportunities:
                self.ui.add_log(f"Monitoring {len(monitor_opportunities)} near-profitable opportunities")

            # Update historical stats
            stats = await self.database.get_historical_stats()
            self.ui.set_historical_stats(stats)

            if opportunities:
                logger.info(f"Found {len(opportunities)} profitable arbitrage opportunities!")
            else:
                logger.info("No profitable arbitrage opportunities found")

            if monitor_opportunities:
                logger.info(f"Monitoring {len(monitor_opportunities)} near-profitable opportunities")
                for i, (k_market, p_market, opp, tier) in enumerate(monitor_opportunities[:5]):
                    logger.info(
                        f"  Monitor #{i+1}: {opp.net_profit_pct:.2f}% profit "
                        f"({opp.net_profit_pct - self.config.thresholds.min_profit_pct:.2f}% below threshold)"
                    )
                    if opp.is_inverse:
                        logger.info(f"    INVERSE: Combined cost ${opp.combined_cost:.2f}")
                    logger.info(f"    {k_market.description[:60]}...")
                    logger.info(f"    {p_market.description[:60]}...")

        except Exception as e:
            logger.error(f"Error during polling cycle: {e}", exc_info=True)
            self.ui.add_log(f"Error: {str(e)[:50]}")

        finally:
            # Calculate time to wait before next cycle
            cycle_duration = time() - cycle_start
            wait_time = max(0, self.config.polling.interval_seconds - cycle_duration)

            logger.info(
                f"Cycle {self.cycle_count} complete in {cycle_duration:.1f}s. "
                f"Waiting {wait_time:.1f}s until next cycle."
            )

            # Update UI during wait
            self.ui.update()

            # Wait with progress updates
            for i in range(int(wait_time)):
                await asyncio.sleep(1)
                self.ui.set_cycle_progress(int(cycle_duration) + i)
                self.ui.update()

    async def run(self):
        """Run the main monitoring loop."""
        self.running = True

        # Start UI
        self.ui.start()

        try:
            # Initialize
            await self.initialize()

            # Main loop
            while self.running:
                await self._polling_cycle()

        except asyncio.CancelledError:
            logger.info("Monitor cancelled")
        except KeyboardInterrupt:
            logger.info("Keyboard interrupt received")
        finally:
            await self.cleanup()

    def stop(self):
        """Stop the monitor."""
        logger.info("Stopping monitor...")
        self.running = False


async def main():
    """Main entry point."""
    monitor = ArbitrageMonitor()

    # Setup signal handlers for graceful shutdown
    loop = asyncio.get_event_loop()

    def signal_handler():
        logger.info("Shutdown signal received")
        monitor.stop()

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, signal_handler)

    # Run monitor
    await monitor.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutdown complete")
        sys.exit(0)
