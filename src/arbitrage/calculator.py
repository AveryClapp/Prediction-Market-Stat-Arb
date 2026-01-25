"""Arbitrage calculation with fee accounting."""

from dataclasses import dataclass
from typing import Optional

from ..config import Config


@dataclass
class ArbitrageOpportunity:
    """Arbitrage opportunity details."""

    direction: str  # "buy_kalshi_sell_poly" or "buy_poly_sell_kalshi"
    net_profit_pct: float  # Net profit percentage after all fees
    gross_profit_pct: float  # Profit before fees
    required_capital: float  # Total capital needed
    kalshi_price: float
    polymarket_price: float
    kalshi_fees: float  # Total Kalshi fees in USD
    polymarket_fees: float  # Total Polymarket fees in USD
    total_fees: float  # All fees combined
    is_profitable: bool  # True if net profit > 0


def calculate_fees(
    position_size: float,
    kalshi_price: float,
    polymarket_price: float,
    config: Config,
    direction: str,
) -> tuple[float, float]:
    """
    Calculate fees for a given arbitrage trade.

    Args:
        position_size: Size of position in contracts/dollars
        kalshi_price: Kalshi market price (0-1)
        polymarket_price: Polymarket market price (0-1)
        config: Configuration with fee structures
        direction: Trade direction

    Returns:
        Tuple of (kalshi_fees, polymarket_fees)
    """
    kalshi_fees = 0.0
    polymarket_fees = 0.0

    if direction == "buy_kalshi_sell_poly":
        # Buy on Kalshi (taker), sell on Polymarket
        kalshi_cost = position_size * kalshi_price
        kalshi_fees = (
            kalshi_cost * config.fees.kalshi.taker_fee_pct / 100
            + config.fees.kalshi.withdrawal_cost_usd
        )

        polymarket_revenue = position_size * polymarket_price
        polymarket_fees = (
            polymarket_revenue * config.fees.polymarket.trading_fee_pct / 100
            + config.fees.polymarket.gas_fee_usd
            + config.fees.polymarket.usdc_bridge_cost_usd
        )

    else:  # buy_poly_sell_kalshi
        # Buy on Polymarket, sell on Kalshi (taker)
        polymarket_cost = position_size * polymarket_price
        polymarket_fees = (
            polymarket_cost * config.fees.polymarket.trading_fee_pct / 100
            + config.fees.polymarket.gas_fee_usd
            + config.fees.polymarket.usdc_bridge_cost_usd
        )

        kalshi_revenue = position_size * kalshi_price
        kalshi_fees = (
            kalshi_revenue * config.fees.kalshi.taker_fee_pct / 100
            + config.fees.kalshi.withdrawal_cost_usd
        )

    return kalshi_fees, polymarket_fees


def calculate_arbitrage(
    kalshi_price: float, polymarket_price: float, config: Config
) -> Optional[ArbitrageOpportunity]:
    """
    Calculate arbitrage opportunity between two markets.

    Evaluates both directions and returns the more profitable one.

    Args:
        kalshi_price: Kalshi YES price (0-1)
        polymarket_price: Polymarket YES price (0-1)
        config: Configuration with fee structures and thresholds

    Returns:
        ArbitrageOpportunity or None if no profitable arbitrage exists
    """
    # Validate prices
    if not (0.01 <= kalshi_price <= 0.99) or not (0.01 <= polymarket_price <= 0.99):
        return None

    # For standardized calculation, use $1000 position size
    position_size = 1000.0

    # Direction 1: Buy on Kalshi, Sell on Polymarket
    # Only profitable if Kalshi price < Polymarket price
    direction1_opportunity = None
    if kalshi_price < polymarket_price:
        # Cost: buy on Kalshi
        cost1 = position_size * kalshi_price

        # Revenue: sell on Polymarket
        revenue1 = position_size * polymarket_price

        # Calculate fees
        kalshi_fees1, poly_fees1 = calculate_fees(
            position_size, kalshi_price, polymarket_price, config, "buy_kalshi_sell_poly"
        )

        # Net profit
        gross_profit1 = revenue1 - cost1
        net_profit1 = gross_profit1 - kalshi_fees1 - poly_fees1

        # Calculate percentages based on capital required
        capital1 = cost1 + kalshi_fees1 + poly_fees1  # Total capital needed upfront
        gross_profit_pct1 = (gross_profit1 / capital1) * 100
        net_profit_pct1 = (net_profit1 / capital1) * 100

        direction1_opportunity = ArbitrageOpportunity(
            direction="buy_kalshi_sell_poly",
            net_profit_pct=net_profit_pct1,
            gross_profit_pct=gross_profit_pct1,
            required_capital=capital1,
            kalshi_price=kalshi_price,
            polymarket_price=polymarket_price,
            kalshi_fees=kalshi_fees1,
            polymarket_fees=poly_fees1,
            total_fees=kalshi_fees1 + poly_fees1,
            is_profitable=net_profit_pct1 >= config.thresholds.min_profit_pct,
        )

    # Direction 2: Buy on Polymarket, Sell on Kalshi
    # Only profitable if Polymarket price < Kalshi price
    direction2_opportunity = None
    if polymarket_price < kalshi_price:
        # Cost: buy on Polymarket
        cost2 = position_size * polymarket_price

        # Revenue: sell on Kalshi
        revenue2 = position_size * kalshi_price

        # Calculate fees
        kalshi_fees2, poly_fees2 = calculate_fees(
            position_size, kalshi_price, polymarket_price, config, "buy_poly_sell_kalshi"
        )

        # Net profit
        gross_profit2 = revenue2 - cost2
        net_profit2 = gross_profit2 - kalshi_fees2 - poly_fees2

        # Calculate percentages
        capital2 = cost2 + kalshi_fees2 + poly_fees2
        gross_profit_pct2 = (gross_profit2 / capital2) * 100
        net_profit_pct2 = (net_profit2 / capital2) * 100

        direction2_opportunity = ArbitrageOpportunity(
            direction="buy_poly_sell_kalshi",
            net_profit_pct=net_profit_pct2,
            gross_profit_pct=gross_profit_pct2,
            required_capital=capital2,
            kalshi_price=kalshi_price,
            polymarket_price=polymarket_price,
            kalshi_fees=kalshi_fees2,
            polymarket_fees=poly_fees2,
            total_fees=kalshi_fees2 + poly_fees2,
            is_profitable=net_profit_pct2 >= config.thresholds.min_profit_pct,
        )

    # Return the more profitable direction, or None if neither is profitable
    opportunities = [
        opp
        for opp in [direction1_opportunity, direction2_opportunity]
        if opp and opp.is_profitable
    ]

    if not opportunities:
        return None

    # Return the opportunity with highest net profit %
    return max(opportunities, key=lambda x: x.net_profit_pct)
