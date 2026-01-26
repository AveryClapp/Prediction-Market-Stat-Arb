"""PredictIt API client implementation."""

import logging
from datetime import datetime

from .base import BaseClient, Market

logger = logging.getLogger(__name__)


class PredictItClient(BaseClient):
    """Client for PredictIt prediction market API."""

    BASE_URL = "https://www.predictit.org/api/marketdata"

    def __init__(self, **kwargs):
        """
        Initialize PredictIt client.

        Note: PredictIt's public API does not require authentication.

        Args:
            **kwargs: Additional arguments for BaseClient
        """
        super().__init__(platform_name="PredictIt", **kwargs)

    async def get_active_markets(self) -> list[Market]:
        """
        Fetch active binary markets from PredictIt.

        PredictIt markets can have multiple contracts (e.g., ranges). For arbitrage
        matching, we only want simple binary yes/no markets (2 contracts: Yes/No).

        Returns:
            List of Market objects (binary markets only)
        """
        # Fetch all active markets (public endpoint, no auth required)
        url = f"{self.BASE_URL}/all/"

        response = await self.fetch_with_retry("GET", url)

        if response is None:
            logger.error("PredictIt: Failed to fetch markets")
            return []

        try:
            data = response.json()
            markets_data = data.get("markets", [])

            logger.info(f"PredictIt: Fetched {len(markets_data)} total markets")

            # Filter for binary (yes/no) markets and convert to standard format
            markets = []
            for m in markets_data:
                contracts = m.get("contracts", [])

                # Skip markets that are not binary (we want exactly 2 contracts: Yes/No)
                # Binary markets typically have names like "Yes" and "No", or are the only contract
                if len(contracts) == 0:
                    continue

                # For markets with exactly 1 contract, that's a binary yes/no
                # For markets with 2 contracts, check if they're Yes/No pairs
                # Skip markets with >2 contracts (those are ranges/multiple outcomes)

                is_binary = False
                contract_to_use = None

                if len(contracts) == 1:
                    # Single contract market = binary yes/no
                    is_binary = True
                    contract_to_use = contracts[0]
                elif len(contracts) == 2:
                    # Check if it's a Yes/No pair (contract names are typically inverse)
                    # For now, we'll use the first contract as the "Yes" side
                    # and verify the prices roughly sum to 1.0
                    contract1 = contracts[0]
                    contract2 = contracts[1]

                    price1 = contract1.get("lastTradePrice", 0.5)
                    price2 = contract2.get("lastTradePrice", 0.5)

                    # If prices roughly sum to ~1.0 (+/- 0.2), it's likely a binary market
                    if 0.8 <= (price1 + price2) <= 1.2:
                        is_binary = True
                        contract_to_use = contract1

                if not is_binary or contract_to_use is None:
                    continue

                # Extract contract data
                contract_id = contract_to_use.get("id")
                contract_name = contract_to_use.get("name", "")
                contract_status = contract_to_use.get("status", "")

                # Skip closed contracts
                if contract_status != "Open":
                    continue

                # Get the "yes" price (last trade price or best buy price)
                yes_price = contract_to_use.get("lastTradePrice", 0.5)
                if yes_price is None or yes_price == 0:
                    # Use best buy price if no last trade
                    yes_price = contract_to_use.get("bestBuyYesCost", 0.5)

                # Ensure price is in valid range
                yes_price = max(0.01, min(0.99, float(yes_price)))

                # Create market description by combining market name and contract name
                market_name = m.get("name", "")
                if len(contracts) == 1:
                    # For single-contract markets, the market name is the full question
                    description = market_name
                else:
                    # For multi-contract binary markets, include the contract name
                    description = f"{market_name} - {contract_name}"

                market = Market(
                    platform="PredictIt",
                    market_id=f"{m['id']}_{contract_id}",
                    description=description,
                    price=yes_price,
                    url=m.get("url", f"https://www.predictit.org/markets/detail/{m['id']}"),
                    close_time="",  # PredictIt doesn't provide close times in this endpoint
                )
                markets.append(market)

            logger.info(f"PredictIt: Fetched {len(markets)} binary markets (filtered from {len(markets_data)} total)")
            return markets

        except Exception as e:
            logger.error(f"PredictIt: Failed to parse markets response: {e}")
            return []
