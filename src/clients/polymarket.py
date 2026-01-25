"""Polymarket API client implementation."""

import json
import logging
from typing import Optional

from .base import BaseClient, Market

logger = logging.getLogger(__name__)


class PolymarketClient(BaseClient):
    """Client for Polymarket prediction market API."""

    # Polymarket CLOB API endpoint
    BASE_URL = "https://clob.polymarket.com"
    GAMMA_API = "https://gamma-api.polymarket.com"

    def __init__(self, api_key: Optional[str] = None, **kwargs):
        """
        Initialize Polymarket client.

        Args:
            api_key: Optional API key (not required for read-only operations)
            **kwargs: Additional arguments for BaseClient
        """
        super().__init__(platform_name="Polymarket", **kwargs)
        self.api_key = api_key

    def _get_headers(self) -> dict[str, str]:
        """
        Get headers for API requests.

        Returns:
            Headers dict
        """
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def get_active_markets(self) -> list[Market]:
        """
        Fetch active binary markets from Polymarket.

        Returns:
            List of Market objects
        """
        # Use Gamma API to get active markets
        url = f"{self.GAMMA_API}/markets"
        params = {
            "closed": "false",  # Only active markets
            "limit": 1000,
        }

        response = await self.fetch_with_retry(
            "GET", url, headers=self._get_headers(), params=params
        )

        if response is None:
            logger.error("Polymarket: Failed to fetch markets")
            return []

        try:
            markets_data = response.json()

            # Filter for binary markets and convert to standard format
            markets = []
            for m in markets_data:
                try:
                    # Parse outcomes field (it's a JSON string)
                    outcomes_raw = m.get("outcomes", "[]")
                    if isinstance(outcomes_raw, str):
                        outcomes = json.loads(outcomes_raw)
                    else:
                        outcomes = outcomes_raw

                    # Skip non-binary markets (markets with more than 2 outcomes)
                    if not isinstance(outcomes, list) or len(outcomes) != 2:
                        continue

                    # Skip inactive or closed markets
                    if not m.get("active", False) or m.get("closed", False):
                        continue

                    # Parse outcome prices (also a JSON string)
                    prices_raw = m.get("outcomePrices", "[]")
                    if isinstance(prices_raw, str):
                        outcome_prices = json.loads(prices_raw)
                    else:
                        outcome_prices = prices_raw

                    if not outcome_prices or len(outcome_prices) != 2:
                        continue

                    # The first outcome is typically "Yes", get its price
                    price = float(outcome_prices[0])

                    # Ensure price is in valid range (0.01 to 0.99)
                    price = max(0.01, min(0.99, price))

                    # Get market description
                    description = m.get("question", "")
                    if not description:
                        description = m.get("title", "")

                    # Get market ID (conditionId is the primary identifier)
                    market_id = m.get("conditionId", "")
                    if not market_id:
                        market_id = m.get("id", "")

                    # Build market URL
                    slug = m.get("slug", market_id)
                    market_url = f"https://polymarket.com/event/{slug}"

                    # Get close time (ISO format)
                    close_time = m.get("endDateIso", "")

                    market = Market(
                        platform="Polymarket",
                        market_id=str(market_id),
                        description=description,
                        price=price,
                        url=market_url,
                        close_time=close_time,
                    )
                    markets.append(market)
                except (ValueError, TypeError, json.JSONDecodeError):
                    # Skip if parsing fails
                    continue

            logger.info(f"Polymarket: Fetched {len(markets)} binary markets")
            return markets

        except Exception as e:
            logger.error(f"Polymarket: Failed to parse markets response: {e}")
            logger.exception(e)  # Log full traceback for debugging
            return []
