import asyncio
import logging
import signal
import sys
from pathlib import Path
from time import time

from .alerting.discord import DiscordAlerter
from .analytics.collector import AnalyticsCollector
from .arbitrage.calculator import calculate_arbitrage, calculate_inverse_arbitrage
from .clients.kalshi import KalshiClient
from .clients.polymarket import PolymarketClient
from .clients.predictit import PredictItClient
from .config import load_config
from .matching.matcher import EventMatcher
from .matching.filter import apply_filters, get_filter_summary
from .storage.database import Database
from .ui.terminal import TerminalUI

# Configure logging (file only, not stdout to keep TUI clean)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("arbitrage.log"),
    ],
)
logger = logging.getLogger(__name__)


class ArbitrageMonitor:
    """Monitors prediction markets and detects arbitrage opportunities."""

    def __init__(self, config_path=Path("config.yaml")):
        self.config = load_config(config_path)

        # Initialize components
        self.kalshi_client = KalshiClient(
            api_key=self.config.api_keys.kalshi_api_key,
            api_secret=self.config.api_keys.kalshi_api_secret,
            max_retries=self.config.polling.max_retries,
            backoff_base=self.config.polling.backoff_base,
        )

        self.polymarket_client = PolymarketClient(
            api_key=self.config.api_keys.polymarket_api_key,
            max_retries=self.config.polling.max_retries,
            backoff_base=self.config.polling.backoff_base,
        )

        self.predictit_client = PredictItClient(
            max_retries=self.config.polling.max_retries,
            backoff_base=self.config.polling.backoff_base,
        )

        self.matcher = EventMatcher(
            keyword_threshold=0.2,  # 20% keyword overlap required
            semantic_threshold=self.config.thresholds.match_similarity,  # From config (default: 95%)
        )

        self.database = Database()

        self.discord = DiscordAlerter(self.config)

        self.ui = TerminalUI(self.config)

        self.analytics = AnalyticsCollector(self.database, self.config)

        # State
        self.running = False
        self.cycle_count = 0
        self.cycle_start_time = None  # Track cycle start for real-time progress

    async def initialize(self):
        logger.info("Initializing arbitrage monitor...")

        await self.database.connect()
        stats = await self.database.get_historical_stats()
        self.ui.set_historical_stats(stats)

        filter_summary = get_filter_summary(self.config.filters)
        logger.info(f"Event filters: {filter_summary}")

        logger.info("Initialization complete")

    async def cleanup(self):
        logger.info("Cleaning up...")

        # Fast cleanup with timeouts
        async def safe_close(coro, name):
            try:
                await asyncio.wait_for(coro, timeout=0.5)
            except asyncio.TimeoutError:
                logger.warning(f"{name} cleanup timed out")
            except Exception as e:
                logger.warning(f"{name} cleanup error: {e}")

        await safe_close(self.kalshi_client.close(), "Kalshi")
        await safe_close(self.polymarket_client.close(), "Polymarket")
        await safe_close(self.predictit_client.close(), "PredictIt")
        await safe_close(self.discord.close(), "Discord")
        await safe_close(self.database.close(), "Database")
        self.ui.stop()

        logger.info("Cleanup complete")

    async def _polling_cycle(self):
        cycle_start = time()
        self.cycle_count += 1

        logger.info(f"=== Polling Cycle {self.cycle_count} ===")
        self.ui.add_log(f"Starting cycle {self.cycle_count}")
        self.ui.set_cycle_start_time(cycle_start)  # Set for real-time progress
        self.ui.update()

        try:
            # Poll Kalshi first
            logger.info("Polling Kalshi...")
            self.ui.add_log("Polling Kalshi (this may take 1-2 min)...")
            self.ui.update()
            kalshi_markets = await self.kalshi_client.get_active_markets()
            kalshi_status = self.kalshi_client.get_status()
            self.ui.set_platform_status(kalshi_status, None)
            self.ui.add_log(f"Kalshi: {len(kalshi_markets)} markets fetched")
            self.ui.update()

            if kalshi_status.consecutive_failures >= self.config.polling.max_retries:
                await self.discord.send_platform_down_alert(
                    "Kalshi", kalshi_status.consecutive_failures
                )

            # Then poll Polymarket
            logger.info("Polling Polymarket...")
            self.ui.add_log("Polling Polymarket...")
            self.ui.update()
            polymarket_markets = await self.polymarket_client.get_active_markets()
            polymarket_status = self.polymarket_client.get_status()
            self.ui.set_platform_status(kalshi_status, polymarket_status)
            self.ui.add_log(f"Polymarket: {len(polymarket_markets)} markets fetched")
            self.ui.update()

            if polymarket_status.consecutive_failures >= self.config.polling.max_retries:
                await self.discord.send_platform_down_alert(
                    "Polymarket", polymarket_status.consecutive_failures
                )

            # Then poll PredictIt
            logger.info("Polling PredictIt...")
            self.ui.add_log("Polling PredictIt...")
            predictit_markets = await self.predictit_client.get_active_markets()
            predictit_status = self.predictit_client.get_status()
            self.ui.add_log(f"PredictIt: {len(predictit_markets)} markets")
            self.ui.update()

            if predictit_status.consecutive_failures >= self.config.polling.max_retries:
                await self.discord.send_platform_down_alert(
                    "PredictIt", predictit_status.consecutive_failures
                )

            # Can't match if we don't have Kalshi data (primary platform)
            if not kalshi_markets:
                logger.warning("Skipping cycle - no Kalshi market data")
                self.ui.add_log("Skipping cycle - no Kalshi data")
                self.ui.update()
                return

            # Find matching events across platforms
            # Match Kalshi vs Polymarket (primary pair - better fees)
            all_matches = []

            if polymarket_markets:
                logger.info("Matching Kalshi vs Polymarket...")
                self.ui.add_log("Matching Kalshi vs Polymarket...")
                self.ui.update()
                polymarket_matches = self.matcher.match_events(kalshi_markets, polymarket_markets, "Polymarket")
                all_matches.extend(polymarket_matches)
                self.ui.add_log(f"Found {len(polymarket_matches)} Kalshi-Polymarket matches")

            # Match Kalshi vs PredictIt (secondary pair - high fees, politics only)
            if predictit_markets:
                logger.info("Matching Kalshi vs PredictIt...")
                self.ui.add_log("Matching Kalshi vs PredictIt...")
                self.ui.update()
                predictit_matches = self.matcher.match_events(kalshi_markets, predictit_markets, "PredictIt")
                all_matches.extend(predictit_matches)
                self.ui.add_log(f"Found {len(predictit_matches)} Kalshi-PredictIt matches")

            matches = all_matches
            self.ui.add_log(f"Total: {len(matches)} event matches across all platforms")

            # Apply keyword filters if enabled
            if self.config.filters.enabled:
                matches_before = len(matches)
                matches = apply_filters(matches, self.config.filters)
                self.ui.add_log(f"Filtered: {matches_before} → {len(matches)} matches")

            # Log if no matches found (for diagnostics)
            if len(matches) == 0:
                self.ui.add_log("No valid matches (all rejected by date filter)")
                logger.info("No matches after date filtering - check logs for rejected examples")

            self.ui.update()

            # Check each match for arbitrage opportunities
            logger.info("Calculating arbitrage...")
            self.ui.add_log("Calculating arbitrage...")
            self.ui.update()

            opportunities = []
            monitor_opportunities = []
            all_opportunities_for_analytics = []

            for match in matches:
                # Try inverse arb first (betting opposite outcomes on each platform)
                opportunity = calculate_inverse_arbitrage(
                    kalshi_price=match.kalshi_market.price,
                    polymarket_price=match.platform2_market.price,
                    kalshi_desc=match.kalshi_market.description,
                    polymarket_desc=match.platform2_market.description,
                    config=self.config,
                    platform2_name=match.platform2_name,
                    similarity_score=match.similarity_score,
                )

                # Fall back to regular arbitrage if inverse doesn't work
                if opportunity is None:
                    opportunity = calculate_arbitrage(
                        kalshi_price=match.kalshi_market.price,
                        polymarket_price=match.platform2_market.price,
                        config=self.config,
                        similarity_score=match.similarity_score,
                    )

                # Record match for analytics (selective storage)
                await self.analytics.record_match(match, opportunity)

                if opportunity and opportunity.is_profitable:
                    tier = self.config.get_tier_for_capital(opportunity.required_capital)

                    # Only alert on A-grade opportunities (95%+ similarity)
                    # Lower grades are logged but not alerted
                    if opportunity.quality_grade == "A":
                        opportunities.append(
                            (match.kalshi_market, match.platform2_market, opportunity, tier, match.similarity_score, match.platform2_name)
                        )

                        await self.database.insert_opportunity(
                            kalshi_market_id=match.kalshi_market.market_id,
                            polymarket_market_id=match.platform2_market.market_id,
                            event_description=match.kalshi_market.description,
                            kalshi_price=opportunity.kalshi_price,
                            polymarket_price=opportunity.polymarket_price,
                            net_profit_pct=opportunity.net_profit_pct,
                            required_capital=opportunity.required_capital,
                            capital_tier=self.config.capital_tiers.index(tier),
                            kalshi_url=match.kalshi_market.url,
                            polymarket_url=match.platform2_market.url,
                            direction=opportunity.direction,
                            similarity_score=match.similarity_score,
                        )

                        await self.discord.send_alert(
                            kalshi_market=match.kalshi_market,
                            platform2_market=match.platform2_market,
                            platform2_name=match.platform2_name,
                            opportunity=opportunity,
                            tier=tier,
                            similarity_score=match.similarity_score,
                        )
                    else:
                        # Log lower-grade profitable opportunities for analysis
                        logger.info(
                            f"Grade-{opportunity.quality_grade} opportunity (not alerting): "
                            f"{match.kalshi_market.description[:50]}... "
                            f"({opportunity.net_profit_pct:.2f}% profit, {match.similarity_score:.2f} similarity)"
                        )

                elif opportunity and opportunity.monitor_opportunity:
                    # Not profitable yet, but close - worth keeping an eye on
                    tier = self.config.get_tier_for_capital(opportunity.required_capital)
                    monitor_opportunities.append(
                        (match.kalshi_market, match.platform2_market, opportunity, tier, match.similarity_score, match.platform2_name)
                    )

            # Record cycle-level analytics
            cycle_duration_ms = int((time() - cycle_start) * 1000)
            await self.analytics.record_cycle(
                kalshi_markets=kalshi_markets,
                polymarket_markets=polymarket_markets,
                predictit_markets=predictit_markets,
                matches=matches,
                opportunities=opportunities,
                cycle_duration_ms=cycle_duration_ms,
                kalshi_api_healthy=kalshi_status.is_healthy,
                polymarket_api_healthy=polymarket_status.is_healthy,
                predictit_api_healthy=predictit_status.is_healthy,
            )

            self.ui.set_opportunities(opportunities)
            self.ui.add_log(f"Found {len(opportunities)} arbitrage opportunities")

            if monitor_opportunities:
                self.ui.add_log(f"Monitoring {len(monitor_opportunities)} near-profitable opportunities")

            stats = await self.database.get_historical_stats()
            self.ui.set_historical_stats(stats)

            if opportunities:
                logger.info(f"Found {len(opportunities)} profitable arbitrage opportunities!")
            else:
                logger.info("No profitable arbitrage opportunities found")

            if monitor_opportunities:
                logger.info(f"Monitoring {len(monitor_opportunities)} near-profitable opportunities")
                for i, (k_market, p2_market, opp, tier, sim_score, p2_name) in enumerate(monitor_opportunities[:5]):
                    logger.info(
                        f"  Monitor #{i+1}: {opp.net_profit_pct:.2f}% profit "
                        f"({opp.net_profit_pct - self.config.thresholds.min_profit_pct:.2f}% below threshold)"
                    )
                    if opp.is_inverse:
                        logger.info(f"    INVERSE: Combined cost ${opp.combined_cost:.2f}")
                    logger.info(f"    Kalshi: {k_market.description[:60]}...")
                    logger.info(f"    {p2_name}: {p2_market.description[:60]}...")

        except Exception as e:
            logger.error(f"Error during polling cycle: {e}", exc_info=True)
            self.ui.add_log(f"Error: {str(e)[:50]}")

        finally:
            cycle_duration = time() - cycle_start
            wait_time = max(0, self.config.polling.interval_seconds - cycle_duration)

            logger.info(
                f"Cycle {self.cycle_count} complete in {cycle_duration:.1f}s. "
                f"Waiting {wait_time:.1f}s until next cycle."
            )

            self.ui.update()

            # Wait until next cycle (progress updates automatically via TUI refresh)
            for i in range(int(wait_time)):
                if not self.running:
                    break
                await asyncio.sleep(1)

    async def run(self):
        self.running = True
        self.ui.start()

        try:
            await self.initialize()

            while self.running:
                await self._polling_cycle()

        except asyncio.CancelledError:
            logger.info("Monitor cancelled")
        except KeyboardInterrupt:
            logger.info("Keyboard interrupt received")
        finally:
            await self.cleanup()

    def stop(self):
        logger.info("Stopping monitor...")
        self.running = False


async def main():
    monitor = ArbitrageMonitor()
    monitor_task = None

    # Handle graceful shutdown
    loop = asyncio.get_event_loop()

    def signal_handler():
        logger.info("Shutdown signal received")
        monitor.stop()
        if monitor_task:
            monitor_task.cancel()

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, signal_handler)

    monitor_task = asyncio.create_task(monitor.run())
    try:
        await monitor_task
    except asyncio.CancelledError:
        logger.info("Monitor task cancelled")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutdown complete")
        sys.exit(0)
