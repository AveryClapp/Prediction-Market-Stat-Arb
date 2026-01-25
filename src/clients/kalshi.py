"""Kalshi API client implementation."""

import asyncio
import logging
from datetime import datetime

from .base import BaseClient, Market

logger = logging.getLogger(__name__)


class KalshiClient(BaseClient):
    """Client for Kalshi prediction market API."""

    BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"

    def __init__(self, api_key: str = None, api_secret: str = None, **kwargs):
        """
        Initialize Kalshi client.

        Note: As of 2026, Kalshi's market data endpoints are public and do not
        require authentication. The api_key and api_secret parameters are kept
        for backwards compatibility but are no longer used.

        Args:
            api_key: (Deprecated) Kalshi API key - no longer required
            api_secret: (Deprecated) Kalshi API secret - no longer required
            **kwargs: Additional arguments for BaseClient
        """
        super().__init__(platform_name="Kalshi", **kwargs)
        # Note: Authentication is no longer required for public market data
        # Kalshi has deprecated email/password login and made market data public

    async def get_active_markets(self) -> list[Market]:
        """
        Fetch active binary markets from Kalshi.

        Note: As of 2026, this endpoint is public and does not require authentication.

        Strategy: Fetch events first, then get simple markets for each event.
        This avoids MVE (multivariate/parlay) markets which cannot be matched
        against simple binary markets from other platforms.

        Returns:
            List of Market objects
        """
        # Step 1: Fetch active events
        events_url = f"{self.BASE_URL}/events"
        events_params = {
            "status": "open",
            "limit": 200,  # Fetch up to 200 events
        }

        events_response = await self.fetch_with_retry("GET", events_url, params=events_params)

        if events_response is None:
            logger.error("Kalshi: Failed to fetch events")
            return []

        try:
            events_data = events_response.json()
            events = events_data.get("events", [])

            logger.info(f"Kalshi: Fetched {len(events)} events")

            # Step 2: Fetch markets for each event
            all_markets = []

            for i, event in enumerate(events):
                event_ticker = event.get("event_ticker")
                if not event_ticker:
                    continue

                # Add delay to avoid rate limiting
                if i > 0:
                    await asyncio.sleep(0.5)  # 500ms between requests

                # Fetch markets for this specific event
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

                # Process markets for this event
                for m in event_markets:
                    # Skip MVE (multivariate event / parlay) markets
                    if m.get("mve_collection_ticker"):
                        continue

                    # Skip non-binary markets
                    if m.get("market_type") != "binary":
                        continue

                    # Get the "yes" price (last traded price or mid price)
                    yes_price = m.get("yes_bid", 0.5)  # Default to 0.5 if no price
                    if "last_price" in m and m["last_price"] is not None:
                        yes_price = m["last_price"]
                    elif "yes_ask" in m and "yes_bid" in m:
                        # Use mid price if we have bid and ask
                        yes_price = (m["yes_ask"] + m["yes_bid"]) / 2

                    # Kalshi prices are in cents (0-100), convert to 0-1 range
                    yes_price = yes_price / 100 if yes_price > 1 else yes_price

                    # Ensure price is in valid range
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
