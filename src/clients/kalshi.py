"""Kalshi API client implementation."""

import logging
from datetime import datetime

from .base import BaseClient, Market

logger = logging.getLogger(__name__)


class KalshiClient(BaseClient):
    """Client for Kalshi prediction market API."""

    BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"

    def __init__(self, api_key: str, api_secret: str, **kwargs):
        """
        Initialize Kalshi client.

        Args:
            api_key: Kalshi API key
            api_secret: Kalshi API secret
            **kwargs: Additional arguments for BaseClient
        """
        super().__init__(platform_name="Kalshi", **kwargs)
        self.api_key = api_key
        self.api_secret = api_secret
        self._auth_token: str | None = None

    async def _authenticate(self) -> bool:
        """
        Authenticate with Kalshi API.

        Returns:
            True if authentication successful, False otherwise
        """
        url = f"{self.BASE_URL}/login"
        payload = {"email": self.api_key, "password": self.api_secret}

        response = await self.fetch_with_retry("POST", url, json=payload)

        if response is None:
            logger.error("Kalshi: Authentication failed")
            return False

        try:
            data = response.json()
            self._auth_token = data.get("token")
            if not self._auth_token:
                logger.error("Kalshi: No token in authentication response")
                return False

            logger.info("Kalshi: Authentication successful")
            return True

        except Exception as e:
            logger.error(f"Kalshi: Failed to parse auth response: {e}")
            return False

    async def _get_headers(self) -> dict[str, str]:
        """
        Get authentication headers for API requests.

        Returns:
            Headers dict with authorization token
        """
        if not self._auth_token:
            await self._authenticate()

        return {"Authorization": f"Bearer {self._auth_token}"}

    async def get_active_markets(self) -> list[Market]:
        """
        Fetch active binary markets from Kalshi.

        Returns:
            List of Market objects
        """
        # Ensure we're authenticated
        if not self._auth_token:
            authenticated = await self._authenticate()
            if not authenticated:
                logger.error("Kalshi: Cannot fetch markets - authentication failed")
                return []

        # Fetch all active markets
        url = f"{self.BASE_URL}/markets"
        params = {
            "status": "open",
            "limit": 1000,  # Fetch up to 1000 markets
        }

        response = await self.fetch_with_retry(
            "GET", url, headers=await self._get_headers(), params=params
        )

        if response is None:
            logger.error("Kalshi: Failed to fetch markets")
            return []

        try:
            data = response.json()
            markets_data = data.get("markets", [])

            # Filter for binary (yes/no) markets and convert to standard format
            markets = []
            for m in markets_data:
                # Kalshi uses "yes_sub_title" and "no_sub_title" for binary markets
                # Skip non-binary markets
                if not m.get("yes_sub_title") or not m.get("no_sub_title"):
                    continue

                # Get the "yes" price (last traded price or mid price)
                yes_price = m.get("yes_bid", 0.5)  # Default to 0.5 if no price
                if "last_price" in m:
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
                markets.append(market)

            logger.info(f"Kalshi: Fetched {len(markets)} binary markets")
            return markets

        except Exception as e:
            logger.error(f"Kalshi: Failed to parse markets response: {e}")
            return []
