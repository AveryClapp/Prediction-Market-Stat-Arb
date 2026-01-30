"""Test suite for robust arbitrage detection fixes."""

import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent / 'src'))

from src.arbitrage.calculator import is_inverse_market, calculate_quality_grade


def test_inverse_detection_strict_validation():
    """Test that inverse detection rejects false positives."""

    print("Testing inverse arbitrage detection...")

    # TEST 1: Should REJECT - Same question, not inverse (Trump/Greenland false positive)
    result = is_inverse_market(
        desc1="Will Trump buy Greenland?",
        desc2="Will the US purchase Greenland in 2026?",
        price1=0.17,
        price2=0.07,
        similarity_score=0.80
    )
    assert result == False, "FAILED: Should reject same question as inverse (prices don't sum to 1.0)"
    print("✓ Test 1 PASS: Rejects Trump/Greenland false positive")

    # TEST 2: Should REJECT - Prices sum to 1.0 but low similarity
    result = is_inverse_market(
        desc1="Will Democrats win?",
        desc2="Will Republicans win?",
        price1=0.52,
        price2=0.48,
        similarity_score=0.85  # Below 95% threshold
    )
    assert result == False, "FAILED: Should reject low similarity even if prices sum to 1.0"
    print("✓ Test 2 PASS: Rejects low similarity inverse")

    # TEST 3: Should PASS - Valid inverse with all requirements met
    result = is_inverse_market(
        desc1="Will Democrats win Senate?",
        desc2="Will Republicans win Senate?",
        price1=0.52,
        price2=0.48,
        similarity_score=0.96
    )
    assert result == True, "FAILED: Should accept valid inverse arbitrage"
    print("✓ Test 3 PASS: Accepts valid dem/rep inverse")

    # TEST 4: Should REJECT - Prices don't sum to 1.0
    result = is_inverse_market(
        desc1="Will Democrats win Senate?",
        desc2="Will Republicans win Senate?",
        price1=0.30,
        price2=0.40,  # Sum = 0.70, not 1.0
        similarity_score=0.96
    )
    assert result == False, "FAILED: Should reject when prices don't sum to ~1.0"
    print("✓ Test 4 PASS: Rejects prices that don't sum to 1.0")

    # TEST 5: Should PASS - Yes/No explicit markers
    result = is_inverse_market(
        desc1="Will Bitcoin hit $100k? - Yes",
        desc2="Will Bitcoin hit $100k? - No",
        price1=0.51,
        price2=0.49,
        similarity_score=0.98
    )
    assert result == True, "FAILED: Should accept yes/no markers"
    print("✓ Test 5 PASS: Accepts yes/no markers")

    # TEST 6: Should REJECT - Pattern match but prices sum to 0.20
    result = is_inverse_market(
        desc1="Will Democrats win primary? - Yes",
        desc2="Will Democrats win primary? - No",
        price1=0.10,
        price2=0.10,  # Sum = 0.20, way off
        similarity_score=0.98
    )
    assert result == False, "FAILED: Should reject pattern match if prices don't sum correctly"
    print("✓ Test 6 PASS: Rejects pattern match with bad price sum")

    print("\n✅ All inverse detection tests passed!")


def test_quality_grading():
    """Test quality grade calculation."""

    print("\nTesting quality grading...")

    assert calculate_quality_grade(0.98) == "A", "FAILED: 98% should be A-grade"
    print("✓ 98% similarity → A-grade")

    assert calculate_quality_grade(0.95) == "A", "FAILED: 95% should be A-grade"
    print("✓ 95% similarity → A-grade")

    assert calculate_quality_grade(0.93) == "B", "FAILED: 93% should be B-grade"
    print("✓ 93% similarity → B-grade")

    assert calculate_quality_grade(0.90) == "B", "FAILED: 90% should be B-grade"
    print("✓ 90% similarity → B-grade")

    assert calculate_quality_grade(0.87) == "C", "FAILED: 87% should be C-grade"
    print("✓ 87% similarity → C-grade")

    assert calculate_quality_grade(0.80) == "D", "FAILED: 80% should be D-grade"
    print("✓ 80% similarity → D-grade")

    print("\n✅ All quality grading tests passed!")


if __name__ == "__main__":
    try:
        test_inverse_detection_strict_validation()
        test_quality_grading()
        print("\n" + "="*60)
        print("🎉 ALL TESTS PASSED - Robust fixes validated!")
        print("="*60)
    except AssertionError as e:
        print(f"\n❌ TEST FAILURE: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ UNEXPECTED ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
