import logging
from dataclasses import dataclass
from typing import Optional

from ..config import Config

logger = logging.getLogger(__name__)


def calculate_quality_grade(similarity_score: float) -> str:
    """
    Calculate quality grade based on similarity score.

    Quality grades:
    - A: 95-100% similarity (very high confidence, auto-alert)
    - B: 90-95% similarity (high confidence, alert with warning)
    - C: 85-90% similarity (medium confidence, log only)
    - D: <85% similarity (low confidence, reject)

    Args:
        similarity_score: Semantic similarity score (0-1)

    Returns:
        Quality grade (A, B, C, or D)
    """
    if similarity_score >= 0.95:
        return "A"
    elif similarity_score >= 0.90:
        return "B"
    elif similarity_score >= 0.85:
        return "C"
    else:
        return "D"


@dataclass
class ArbitrageOpportunity:
    direction: str
    net_profit_pct: float
    gross_profit_pct: float
    required_capital: float
    kalshi_price: float
    polymarket_price: float
    kalshi_fees: float
    polymarket_fees: float
    total_fees: float
    is_profitable: bool
    quality_grade: str = "C"  # A, B, C, or D based on similarity and validation
    is_inverse: bool = False  # betting opposite outcomes
    combined_cost: Optional[float] = None  # for inverse arb
    monitor_opportunity: bool = False  # close to profitable


def is_inverse_market(desc1, desc2, price1, price2, similarity_score=None):
    """
    Check if two markets are opposites (e.g. "Dems win" vs "Reps win").

    STRICT REQUIREMENTS (ALL must be true):
    1. Prices sum to 0.95-1.05 (tighter bounds to prevent false positives)
    2. Explicit pattern match (dem/rep, yes/no, over/under)
    3. High similarity score if provided (95%+)

    Args:
        desc1: First market description
        desc2: Second market description
        price1: First market price (0-1)
        price2: Second market price (0-1)
        similarity_score: Optional semantic similarity (0-1)

    Returns:
        True if markets are confirmed inverses, False otherwise
    """
    desc1_lower = desc1.lower()
    desc2_lower = desc2.lower()

    # REQUIREMENT 1: Strict price sum validation
    # Prices MUST sum to ~1.0 (within tight bounds)
    price_sum = price1 + price2
    if not (0.95 <= price_sum <= 1.05):
        return False  # Not inverse if prices don't sum to 1.0

    # REQUIREMENT 2: Explicit pattern match required
    pattern_suggests_inverse = False

    # Political parties
    has_dem_1 = any(word in desc1_lower for word in ["democrat", "democratic", "democrats"])
    has_rep_1 = any(word in desc1_lower for word in ["republican", "republicans"])
    has_dem_2 = any(word in desc2_lower for word in ["democrat", "democratic", "democrats"])
    has_rep_2 = any(word in desc2_lower for word in ["republican", "republicans"])

    if (has_dem_1 and not has_rep_1 and has_rep_2 and not has_dem_2):
        pattern_suggests_inverse = True
    elif (has_rep_1 and not has_dem_1 and has_dem_2 and not has_rep_2):
        pattern_suggests_inverse = True

    # Yes/No markers
    if (" - yes" in desc1_lower and " - no" in desc2_lower):
        pattern_suggests_inverse = True
    elif (" - no" in desc1_lower and " - yes" in desc2_lower):
        pattern_suggests_inverse = True

    # Over/Under
    has_over_1 = "over" in desc1_lower
    has_under_1 = "under" in desc1_lower
    has_over_2 = "over" in desc2_lower
    has_under_2 = "under" in desc2_lower

    if (has_over_1 and not has_under_1 and has_under_2 and not has_over_2):
        pattern_suggests_inverse = True
    elif (has_under_1 and not has_over_1 and has_over_2 and not has_under_2):
        pattern_suggests_inverse = True

    # Win/Lose pairs
    has_win_1 = " win" in desc1_lower or " wins" in desc1_lower
    has_lose_1 = " lose" in desc1_lower or " loses" in desc1_lower
    has_win_2 = " win" in desc2_lower or " wins" in desc2_lower
    has_lose_2 = " lose" in desc2_lower or " loses" in desc2_lower

    if (has_win_1 and not has_lose_1 and has_lose_2 and not has_win_2):
        pattern_suggests_inverse = True
    elif (has_lose_1 and not has_win_1 and has_win_2 and not has_lose_2):
        pattern_suggests_inverse = True

    # Must have explicit pattern match
    if not pattern_suggests_inverse:
        return False

    # REQUIREMENT 3: High similarity if provided
    if similarity_score is not None and similarity_score < 0.95:
        return False  # Markets must be highly similar (about same event)

    # All requirements met
    return True


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
    similarity_score: Optional[float] = None,
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
        similarity_score: Semantic similarity between markets (0-1), required to be ≥0.95

    Returns:
        ArbitrageOpportunity or None if not inverse or not profitable
    """
    # Check if markets are inverses (strict validation)
    if not is_inverse_market(kalshi_desc, polymarket_desc, kalshi_price, polymarket_price, similarity_score):
        logger.debug(
            f"REJECT_INVERSE: Not inverse markets "
            f"(sum={kalshi_price + polymarket_price:.2f}, sim={similarity_score:.2f if similarity_score else 'N/A'})"
        )
        return None

    # VALIDATION: Strict price sanity checks (same as regular arbitrage)
    if not (0.05 <= kalshi_price <= 0.95) or not (0.05 <= polymarket_price <= 0.95):
        logger.debug(f"REJECT_PRICE_SANITY (inverse): Prices outside 0.05-0.95 range")
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

    # Calculate quality grade from similarity score
    quality_grade = calculate_quality_grade(similarity_score) if similarity_score is not None else "C"

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
        quality_grade=quality_grade,
        is_inverse=True,
        combined_cost=combined_cost,
        monitor_opportunity=monitor_opportunity,
    )


def calculate_arbitrage(
    kalshi_price: float, polymarket_price: float, config: Config, similarity_score: Optional[float] = None
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
    # VALIDATION 1: Strict price sanity checks
    # Reject edge cases (too close to 0 or 1)
    if not (0.05 <= kalshi_price <= 0.95) or not (0.05 <= polymarket_price <= 0.95):
        logger.debug(f"REJECT_PRICE_SANITY: Prices outside 0.05-0.95 range (K:{kalshi_price:.2f}, P:{polymarket_price:.2f})")
        return None

    # VALIDATION 2: Minimum spread requirement
    # Below 5% spread, fees consume all profit
    price_spread = abs(kalshi_price - polymarket_price)
    if price_spread < 0.05:
        logger.debug(f"REJECT_SPREAD: Price spread {price_spread:.2%} below 5% minimum")
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

        quality_grade1 = calculate_quality_grade(similarity_score) if similarity_score is not None else "C"

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
            quality_grade=quality_grade1,
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

        quality_grade2 = calculate_quality_grade(similarity_score) if similarity_score is not None else "C"

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
            quality_grade=quality_grade2,
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
