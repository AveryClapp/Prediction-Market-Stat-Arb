import asyncio
import logging
from datetime import datetime

from .base import BaseClient, Market

logger = logging.getLogger(__name__)


class KalshiClient(BaseClient):
    BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"

    def __init__(self, api_key=None, api_secret=None, **kwargs):
        super().__init__(platform_name="Kalshi", **kwargs)
        # Kalshi made their market data public in 2026, no auth needed anymore

    async def get_active_markets(self):
        """Get active markets from Kalshi. Filters out MVE/parlay markets."""
        # Fetch events first
        events_url = f"{self.BASE_URL}/events"
        events_params = {
            "status": "open",
            "limit": 200,
        }

        events_response = await self.fetch_with_retry("GET", events_url, params=events_params)

        if events_response is None:
            logger.error("Kalshi: Failed to fetch events")
            return []

        try:
            events_data = events_response.json()
            events = events_data.get("events", [])

            logger.info(f"Kalshi: Fetched {len(events)} events")

            # Now fetch markets for each event
            all_markets = []
            total_events = len(events)

            for i, event in enumerate(events):
                event_ticker = event.get("event_ticker")
                if not event_ticker:
                    continue

                # Log progress every 20 events
                if i > 0 and i % 20 == 0:
                    logger.info(f"Kalshi: Processing event {i}/{total_events}...")

                # Rate limiting (reduced to speed up polling)
                if i > 0:
                    await asyncio.sleep(0.1)

                markets_url = f"{self.BASE_URL}/markets"
                markets_params = {
                    "status": "open",
                    "event_ticker": event_ticker,
                    "limit": 100,
                }

                markets_response = await self.fetch_with_retry("GET", markets_url, params=markets_params)

                if markets_response is None:
                    continue

                markets_data = markets_response.json()
                event_markets = markets_data.get("markets", [])

                for m in event_markets:
                    # Skip MVE (multivariate/parlay) markets
                    if m.get("mve_collection_ticker"):
                        continue

                    if m.get("market_type") != "binary":
                        continue

                    # Get yes price - prefer last price, fall back to mid
                    yes_price = m.get("yes_bid", 0.5)
                    if "last_price" in m and m["last_price"] is not None:
                        yes_price = m["last_price"]
                    elif "yes_ask" in m and "yes_bid" in m:
                        yes_price = (m["yes_ask"] + m["yes_bid"]) / 2

                    # Kalshi uses cents, convert to 0-1
                    yes_price = yes_price / 100 if yes_price > 1 else yes_price
                    yes_price = max(0.01, min(0.99, yes_price))

                    market = Market(
                        platform="Kalshi",
                        market_id=m["ticker"],
                        description=m.get("title", ""),
                        price=yes_price,
                        url=f"https://kalshi.com/markets/{m['ticker']}",
                        close_time=m.get("close_time", ""),
                    )
                    all_markets.append(market)

            logger.info(f"Kalshi: Fetched {len(all_markets)} simple binary markets (filtered out MVE/parlays)")
            return all_markets

        except Exception as e:
            logger.error(f"Kalshi: Failed to parse events/markets response: {e}")
            return []
