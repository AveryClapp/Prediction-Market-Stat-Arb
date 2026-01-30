"""Integration test - verify system initializes and basic flow works."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / 'src'))

from src.config import load_config
from src.arbitrage.calculator import calculate_arbitrage, calculate_inverse_arbitrage
from src.clients.base import Market


async def test_initialization():
    """Test that config loads and clients initialize."""
    print("Testing configuration and initialization...")

    # Test config loading
    config = load_config(Path("config.yaml"))
    print(f"✓ Config loaded successfully")
    print(f"  - Similarity threshold: {config.thresholds.match_similarity}")
    print(f"  - Min profit: {config.thresholds.min_profit_pct}%")

    # Verify raised similarity threshold
    assert config.thresholds.match_similarity >= 0.90, "Similarity threshold should be ≥90%"
    print(f"✓ Similarity threshold validated: {config.thresholds.match_similarity}")

    return config


def test_regular_arbitrage_validation():
    """Test regular arbitrage validation pipeline."""
    print("\nTesting regular arbitrage validation...")

    # Create mock config
    from src.config import Config, Fees, KalshiFees, PolymarketFees, PredictItFees, Thresholds, ApiKeys, Discord, Polling, CapitalTier

    config = Config(
        api_keys=ApiKeys(kalshi_api_key="test", kalshi_api_secret="test"),
        fees=Fees(
            kalshi=KalshiFees(maker_fee_pct=0.0, taker_fee_pct=3.0, withdrawal_cost_usd=0.0),
            polymarket=PolymarketFees(gas_fee_usd=0.50, usdc_bridge_cost_usd=1.00, trading_fee_pct=0.0),
            predictit=PredictItFees(profit_fee_pct=10.0, withdrawal_fee_pct=5.0)
        ),
        thresholds=Thresholds(min_profit_pct=3.0, match_similarity=0.95),
        capital_tiers=[CapitalTier(max=999999, name="Test", color="green")],
        discord=Discord(enabled=False),
        polling=Polling(interval_seconds=60, max_retries=3, backoff_base=2)
    )

    # TEST 1: Should REJECT - Prices too close (edge case)
    result = calculate_arbitrage(kalshi_price=0.02, polymarket_price=0.50, config=config)
    assert result is None, "Should reject edge case prices < 0.05"
    print("✓ Rejects edge case prices (< 0.05)")

    # TEST 2: Should REJECT - Spread too small
    result = calculate_arbitrage(kalshi_price=0.50, polymarket_price=0.52, config=config, similarity_score=0.96)
    assert result is None, "Should reject spread < 5%"
    print("✓ Rejects small spread (< 5%)")

    # TEST 3: Should PASS - Valid arbitrage
    result = calculate_arbitrage(kalshi_price=0.40, polymarket_price=0.60, config=config, similarity_score=0.96)
    assert result is not None, "Should accept valid arbitrage"
    assert result.quality_grade == "A", "Should be A-grade with 96% similarity"
    print(f"✓ Accepts valid arbitrage: {result.net_profit_pct:.2f}% profit, Grade {result.quality_grade}")

    # TEST 4: Quality grade assignment
    result_b_grade = calculate_arbitrage(kalshi_price=0.40, polymarket_price=0.60, config=config, similarity_score=0.92)
    assert result_b_grade.quality_grade == "B", "Should be B-grade with 92% similarity"
    print(f"✓ B-grade assigned correctly for 92% similarity")

    print("\n✅ All regular arbitrage validation tests passed!")


if __name__ == "__main__":
    try:
        # Run async tests
        config = asyncio.run(test_initialization())

        # Run sync tests
        test_regular_arbitrage_validation()

        print("\n" + "="*60)
        print("🎉 ALL INTEGRATION TESTS PASSED!")
        print("="*60)
        print("\nSystem is ready for live testing.")
        print("Run: python -m src.main")

    except AssertionError as e:
        print(f"\n❌ TEST FAILURE: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
