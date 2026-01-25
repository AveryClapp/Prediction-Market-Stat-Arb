"""Polymarket API client implementation."""

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
                # Skip non-binary markets (markets with more than 2 outcomes)
                if not isinstance(m.get("tokens"), list) or len(m["tokens"]) != 2:
                    continue

                # Polymarket binary markets have two tokens (YES and NO)
                # We want the price of the YES outcome
                tokens = m["tokens"]

                # Find the YES token (outcome token)
                # Typically token 0 is YES and token 1 is NO, but check
                yes_token = None
                for token in tokens:
                    if token.get("outcome", "").lower() in ["yes", "1", "true"]:
                        yes_token = token
                        break

                # If we couldn't find explicit YES token, use first token
                if yes_token is None:
                    yes_token = tokens[0]

                # Get the last price or mid price
                price = yes_token.get("price", 0.5)

                # Price should already be in 0-1 range, but ensure it
                price = max(0.01, min(0.99, float(price)))

                # Get market description
                description = m.get("question", "")
                if not description:
                    description = m.get("title", "")

                # Get market ID (condition_id or token_id)
                market_id = m.get("condition_id", yes_token.get("token_id", ""))

                # Build market URL
                slug = m.get("slug", market_id)
                market_url = f"https://polymarket.com/event/{slug}"

                # Get close time
                close_time = m.get("end_date_iso", "")

                market = Market(
                    platform="Polymarket",
                    market_id=str(market_id),
                    description=description,
                    price=price,
                    url=market_url,
                    close_time=close_time,
                )
                markets.append(market)

            logger.info(f"Polymarket: Fetched {len(markets)} binary markets")
            return markets

        except Exception as e:
            logger.error(f"Polymarket: Failed to parse markets response: {e}")
            logger.exception(e)  # Log full traceback for debugging
            return []
