import logging
from datetime import datetime

from .base import BaseClient, Market

logger = logging.getLogger(__name__)


class PredictItClient(BaseClient):
    BASE_URL = "https://www.predictit.org/api/marketdata"

    def __init__(self, **kwargs):
        super().__init__(platform_name="PredictIt", **kwargs)

    async def get_active_markets(self):
        """Get active binary markets only - filters out range/multi-outcome markets."""
        url = f"{self.BASE_URL}/all/"

        response = await self.fetch_with_retry("GET", url)

        if response is None:
            logger.error("PredictIt: Failed to fetch markets")
            return []

        try:
            data = response.json()
            markets_data = data.get("markets", [])

            logger.info(f"PredictIt: Fetched {len(markets_data)} total markets")

            # Only keep binary markets
            markets = []
            for m in markets_data:
                contracts = m.get("contracts", [])

                if len(contracts) == 0:
                    continue

                is_binary = False
                contract_to_use = None

                if len(contracts) == 1:
                    # Single contract = binary yes/no
                    is_binary = True
                    contract_to_use = contracts[0]
                elif len(contracts) == 2:
                    # Two contracts - check if prices sum to ~1.0 (likely yes/no pair)
                    contract1 = contracts[0]
                    contract2 = contracts[1]

                    price1 = contract1.get("lastTradePrice", 0.5)
                    price2 = contract2.get("lastTradePrice", 0.5)

                    if 0.8 <= (price1 + price2) <= 1.2:
                        is_binary = True
                        contract_to_use = contract1

                if not is_binary or contract_to_use is None:
                    continue

                contract_id = contract_to_use.get("id")
                contract_name = contract_to_use.get("name", "")
                contract_status = contract_to_use.get("status", "")

                if contract_status != "Open":
                    continue

                # Get yes price
                yes_price = contract_to_use.get("lastTradePrice", 0.5)
                if yes_price is None or yes_price == 0:
                    yes_price = contract_to_use.get("bestBuyYesCost", 0.5)

                yes_price = max(0.01, min(0.99, float(yes_price)))

                # Build description
                market_name = m.get("name", "")
                if len(contracts) == 1:
                    description = market_name
                else:
                    description = f"{market_name} - {contract_name}"

                market = Market(
                    platform="PredictIt",
                    market_id=f"{m['id']}_{contract_id}",
                    description=description,
                    price=yes_price,
                    url=m.get("url", f"https://www.predictit.org/markets/detail/{m['id']}"),
                    close_time="",
                )
                markets.append(market)

            logger.info(f"PredictIt: Fetched {len(markets)} binary markets (filtered from {len(markets_data)} total)")
            return markets

        except Exception as e:
            logger.error(f"PredictIt: Failed to parse markets response: {e}")
            return []
