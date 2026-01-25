"""Discord webhook alerting with tier-based embeds."""

import logging
from datetime import datetime

import httpx

from ..arbitrage.calculator import ArbitrageOpportunity
from ..clients.base import Market
from ..config import CapitalTier, Config

logger = logging.getLogger(__name__)


# Emoji icons for tiers
TIER_ICONS = {
    "green": "🟢",
    "yellow": "🟡",
    "red": "🔴",
}

# Discord embed colors (decimal format)
EMBED_COLORS = {
    "green": 0x00FF00,  # Green
    "yellow": 0xFFFF00,  # Yellow
    "red": 0xFF0000,  # Red
}


class DiscordAlerter:
    """Discord webhook alerting with tier-based formatting."""

    def __init__(self, config: Config):
        """
        Initialize Discord alerter.

        Args:
            config: Configuration with Discord webhook and tiers
        """
        self.config = config
        self.webhook_url = config.discord.webhook_url
        self.enabled = config.discord.enabled
        self.client = httpx.AsyncClient(timeout=10.0)

    async def close(self):
        """Close HTTP client."""
        await self.client.aclose()

    def _create_embed(
        self,
        kalshi_market: Market,
        polymarket_market: Market,
        opportunity: ArbitrageOpportunity,
        tier: CapitalTier,
    ) -> dict:
        """
        Create Discord embed for arbitrage opportunity.

        Args:
            kalshi_market: Kalshi market
            polymarket_market: Polymarket market
            opportunity: Arbitrage opportunity details
            tier: Capital tier

        Returns:
            Discord embed dict
        """
        # Get tier icon and color
        icon = TIER_ICONS.get(tier.color, "⚪")
        color = EMBED_COLORS.get(tier.color, 0x808080)

        # Format prices as percentages
        kalshi_pct = int(opportunity.kalshi_price * 100)
        poly_pct = int(opportunity.polymarket_price * 100)

        # Determine direction text
        if opportunity.direction == "buy_kalshi_sell_poly":
            direction_text = f"Buy Kalshi ({kalshi_pct}%) → Sell Polymarket ({poly_pct}%)"
        else:
            direction_text = f"Buy Polymarket ({poly_pct}%) → Sell Kalshi ({kalshi_pct}%)"

        # Format capital with commas
        capital_str = f"${opportunity.required_capital:,.2f}"
        profit_str = f"{opportunity.net_profit_pct:.2f}%"

        # Build embed
        embed = {
            "title": f"{icon} {tier.name} Opportunity Detected",
            "description": (
                f"**Event:** {kalshi_market.description[:200]}\n\n"
                f"**Direction:** {direction_text}\n"
                f"**Net Profit:** {profit_str}\n"
                f"**Required Capital:** {capital_str}\n"
            ),
            "color": color,
            "fields": [
                {
                    "name": "Kalshi",
                    "value": f"[View Market]({kalshi_market.url})",
                    "inline": True,
                },
                {
                    "name": "Polymarket",
                    "value": f"[View Market]({polymarket_market.url})",
                    "inline": True,
                },
                {
                    "name": "Fees Breakdown",
                    "value": (
                        f"Kalshi: ${opportunity.kalshi_fees:.2f}\n"
                        f"Polymarket: ${opportunity.polymarket_fees:.2f}\n"
                        f"Total: ${opportunity.total_fees:.2f}"
                    ),
                    "inline": False,
                },
            ],
            "timestamp": datetime.now().isoformat(),
            "footer": {"text": "Prediction Market Arbitrage Monitor"},
        }

        return embed

    async def send_alert(
        self,
        kalshi_market: Market,
        polymarket_market: Market,
        opportunity: ArbitrageOpportunity,
        tier: CapitalTier,
    ) -> bool:
        """
        Send Discord alert for arbitrage opportunity.

        Args:
            kalshi_market: Kalshi market
            polymarket_market: Polymarket market
            opportunity: Arbitrage opportunity details
            tier: Capital tier

        Returns:
            True if alert sent successfully, False otherwise
        """
        if not self.enabled:
            logger.debug("Discord alerts disabled")
            return False

        if not self.webhook_url:
            logger.warning("Discord webhook URL not configured")
            return False

        # Create embed
        embed = self._create_embed(kalshi_market, polymarket_market, opportunity, tier)

        # Send to Discord
        payload = {"embeds": [embed]}

        try:
            response = await self.client.post(self.webhook_url, json=payload)
            response.raise_for_status()
            logger.info(f"Discord alert sent for {tier.name} opportunity")
            return True

        except httpx.HTTPStatusError as e:
            logger.error(f"Discord webhook HTTP error: {e.response.status_code}")
            return False

        except Exception as e:
            logger.error(f"Failed to send Discord alert: {e}")
            return False

    async def send_platform_down_alert(self, platform: str, failures: int) -> bool:
        """
        Send alert when platform is down.

        Args:
            platform: Platform name (Kalshi or Polymarket)
            failures: Number of consecutive failures

        Returns:
            True if alert sent successfully
        """
        if not self.enabled or not self.webhook_url:
            return False

        embed = {
            "title": f"⚠️ {platform} Platform Issue",
            "description": (
                f"{platform} has failed {failures} consecutive polling attempts.\n"
                f"Monitor will continue retrying."
            ),
            "color": 0xFFA500,  # Orange
            "timestamp": datetime.now().isoformat(),
        }

        payload = {"embeds": [embed]}

        try:
            response = await self.client.post(self.webhook_url, json=payload)
            response.raise_for_status()
            logger.info(f"Platform down alert sent for {platform}")
            return True

        except Exception as e:
            logger.error(f"Failed to send platform down alert: {e}")
            return False
