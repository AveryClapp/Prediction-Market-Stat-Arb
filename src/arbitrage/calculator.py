"""Arbitrage calculation with fee accounting."""

from dataclasses import dataclass
from typing import Optional

from ..config import Config


@dataclass
class ArbitrageOpportunity:
    """Arbitrage opportunity details."""

    direction: str  # "buy_kalshi_sell_poly", "buy_poly_sell_kalshi", or "inverse_arbitrage"
    net_profit_pct: float  # Net profit percentage after all fees
    gross_profit_pct: float  # Profit before fees
    required_capital: float  # Total capital needed
    kalshi_price: float
    polymarket_price: float
    kalshi_fees: float  # Total Kalshi fees in USD
    polymarket_fees: float  # Total Polymarket fees in USD
    total_fees: float  # All fees combined
    is_profitable: bool  # True if net profit > 0
    is_inverse: bool = False  # True if this is inverse arbitrage (opposite outcomes)
    combined_cost: Optional[float] = None  # For inverse: combined cost of both positions
    monitor_opportunity: bool = False  # True if close to profitable (within monitor threshold)


def is_inverse_market(desc1: str, desc2: str, price1: float, price2: float) -> bool:
    """
    Detect if two market descriptions represent inverse/opposite outcomes.

    Uses two strategies:
    1. Price-based: If prices sum to ~1.0, likely inverse (one must win)
    2. Pattern-based: Detects specific inverse patterns (political, yes/no, team sports, etc.)

    Examples of inverse markets:
    - Politics: "Democrats win" vs "Republicans win"
    - Sports: "Team A wins" vs "Team B wins"
    - Binary: "Yes" vs "No", "Over X" vs "Under X"
    - General: Any two outcomes where prices sum to ~1.0

    Args:
        desc1: First market description
        desc2: Second market description
        price1: First market price (0-1)
        price2: Second market price (0-1)

    Returns:
        True if markets appear to be inverses (opposite outcomes of same event)
    """
    desc1_lower = desc1.lower()
    desc2_lower = desc2.lower()

    # Strategy 1: PRICE-BASED DETECTION (Universal)
    # If two markets are truly inverse (one must win), their prices should sum to ~1.0
    # Allow some slippage for market inefficiency (0.85-1.15)
    price_sum = price1 + price2
    prices_suggest_inverse = 0.85 <= price_sum <= 1.15

    # Strategy 2: PATTERN-BASED DETECTION (Specific patterns)
    pattern_suggests_inverse = False

    # Pattern 1: Political parties (Democrat vs Republican)
    has_dem_1 = any(word in desc1_lower for word in ["democrat", "democratic", "democrats"])
    has_rep_1 = any(word in desc1_lower for word in ["republican", "republicans"])
    has_dem_2 = any(word in desc2_lower for word in ["democrat", "democratic", "democrats"])
    has_rep_2 = any(word in desc2_lower for word in ["republican", "republicans"])

    if (has_dem_1 and not has_rep_1 and has_rep_2 and not has_dem_2):
        pattern_suggests_inverse = True
    elif (has_rep_1 and not has_dem_1 and has_dem_2 and not has_rep_2):
        pattern_suggests_inverse = True

    # Pattern 2: Yes/No explicit markers
    if (" - yes" in desc1_lower and " - no" in desc2_lower):
        pattern_suggests_inverse = True
    elif (" - no" in desc1_lower and " - yes" in desc2_lower):
        pattern_suggests_inverse = True

    # Pattern 3: Over/Under
    has_over_1 = "over" in desc1_lower
    has_under_1 = "under" in desc1_lower
    has_over_2 = "over" in desc2_lower
    has_under_2 = "under" in desc2_lower

    if (has_over_1 and not has_under_1 and has_under_2 and not has_over_2):
        pattern_suggests_inverse = True
    elif (has_under_1 and not has_over_1 and has_over_2 and not has_under_2):
        pattern_suggests_inverse = True

    # Pattern 4: Different specific outcomes in same question
    # Look for markers like "- Option A" vs "- Option B"
    # This catches categorical markets with explicit outcome labels

    # DECISION LOGIC:
    # If prices strongly suggest inverse (sum ~1.0), that's sufficient evidence
    # OR if we detect a clear pattern, trust it
    # Best: Both agree!

    if prices_suggest_inverse and pattern_suggests_inverse:
        return True  # Strong confidence - both signals agree

    if prices_suggest_inverse:
        # Prices sum to ~1.0, which is strong evidence even without pattern match
        # This catches all types of binary markets (sports, entertainment, etc.)
        # Only exception: if prices are both very high (0.9 + 0.9 = 1.8) or both very low
        if price_sum < 1.15:  # Tighter bound for price-only detection
            return True

    if pattern_suggests_inverse:
        # Clear pattern detected, even if prices don't perfectly sum to 1.0
        # (market inefficiency is real)
        return True

    return False


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


def calculate_inverse_arbitrage(
    kalshi_price: float,
    polymarket_price: float,
    kalshi_desc: str,
    polymarket_desc: str,
    config: Config,
    platform2_name: str = "Polymarket",
) -> Optional[ArbitrageOpportunity]:
    """
    Calculate inverse arbitrage opportunity (betting opposite outcomes).

    For inverse arbitrage, we buy BOTH outcomes on different platforms:
    - If combined cost < 1.0, we have guaranteed profit
    - We pay for both positions upfront but are guaranteed one will win

    Args:
        kalshi_price: Kalshi market price (0-1)
        polymarket_price: Second platform market price (0-1)
        kalshi_desc: Kalshi market description (to detect inverse)
        polymarket_desc: Second platform description
        config: Configuration with fee structures and thresholds
        platform2_name: Name of second platform ("Polymarket" or "PredictIt")

    Returns:
        ArbitrageOpportunity or None if not inverse or not profitable
    """
    # Check if markets are inverses
    if not is_inverse_market(kalshi_desc, polymarket_desc, kalshi_price, polymarket_price):
        return None

    # Validate prices
    if not (0.01 <= kalshi_price <= 0.99) or not (0.01 <= polymarket_price <= 0.99):
        return None

    # For inverse arbitrage, we buy BOTH positions
    position_size = 1000.0

    # Cost to buy both positions
    kalshi_cost = position_size * kalshi_price
    polymarket_cost = position_size * polymarket_price

    # Calculate fees for buying on both platforms
    # For Kalshi: buying (taker fee)
    kalshi_fees = (
        kalshi_cost * config.fees.kalshi.taker_fee_pct / 100
        + config.fees.kalshi.withdrawal_cost_usd
    )

    # For second platform: detect which platform and use appropriate fees
    if platform2_name == "PredictIt":
        # PredictIt fees: 10% on profits, 5% withdrawal
        # For inverse arbitrage, we're buying, so estimate profit first
        # Simplified: apply fees to the cost side
        estimated_profit = max(0, position_size - polymarket_cost)
        polymarket_fees = (
            estimated_profit * config.fees.predictit.profit_fee_pct / 100
            + polymarket_cost * config.fees.predictit.withdrawal_fee_pct / 100
        )
    else:
        # Polymarket fees
        polymarket_fees = (
            polymarket_cost * config.fees.polymarket.trading_fee_pct / 100
            + config.fees.polymarket.gas_fee_usd
            + config.fees.polymarket.usdc_bridge_cost_usd
        )

    # Total capital required
    total_cost = kalshi_cost + polymarket_cost + kalshi_fees + polymarket_fees

    # Guaranteed payout (one side will win)
    payout = position_size * 1.0

    # Calculate profit
    gross_profit = payout - (kalshi_cost + polymarket_cost)
    net_profit = payout - total_cost

    # Calculate percentages
    gross_profit_pct = (gross_profit / total_cost) * 100 if total_cost > 0 else 0
    net_profit_pct = (net_profit / total_cost) * 100 if total_cost > 0 else 0

    # Combined cost of positions (useful for display)
    combined_cost = kalshi_price + polymarket_price

    # Determine if profitable or monitor opportunity
    is_profitable = net_profit_pct >= config.thresholds.min_profit_pct
    monitor_opportunity = (
        not is_profitable
        and net_profit_pct >= (config.thresholds.min_profit_pct - config.thresholds.monitor_threshold_pct)
    )

    return ArbitrageOpportunity(
        direction="inverse_arbitrage",
        net_profit_pct=net_profit_pct,
        gross_profit_pct=gross_profit_pct,
        required_capital=total_cost,
        kalshi_price=kalshi_price,
        polymarket_price=polymarket_price,
        kalshi_fees=kalshi_fees,
        polymarket_fees=polymarket_fees,
        total_fees=kalshi_fees + polymarket_fees,
        is_profitable=is_profitable,
        is_inverse=True,
        combined_cost=combined_cost,
        monitor_opportunity=monitor_opportunity,
    )


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

        is_profitable1 = net_profit_pct1 >= config.thresholds.min_profit_pct
        monitor_opportunity1 = (
            not is_profitable1
            and net_profit_pct1 >= (config.thresholds.min_profit_pct - config.thresholds.monitor_threshold_pct)
        )

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
            is_profitable=is_profitable1,
            monitor_opportunity=monitor_opportunity1,
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

        is_profitable2 = net_profit_pct2 >= config.thresholds.min_profit_pct
        monitor_opportunity2 = (
            not is_profitable2
            and net_profit_pct2 >= (config.thresholds.min_profit_pct - config.thresholds.monitor_threshold_pct)
        )

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
            is_profitable=is_profitable2,
            monitor_opportunity=monitor_opportunity2,
        )

    # Return the more profitable direction
    # Include both profitable and monitor opportunities
    opportunities = [
        opp
        for opp in [direction1_opportunity, direction2_opportunity]
        if opp and (opp.is_profitable or opp.monitor_opportunity)
    ]

    if not opportunities:
        return None

    # Return the opportunity with highest net profit %
    return max(opportunities, key=lambda x: x.net_profit_pct)
