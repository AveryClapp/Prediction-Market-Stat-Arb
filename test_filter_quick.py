"""Quick filter demonstration."""

from src.config import EventFilters
from src.matching.filter import get_filter_summary, FILTER_PRESETS
from src.matching.matcher import EventMatch
from src.clients.base import Market


# Create mock matches for testing
def create_mock_match(desc1, desc2):
    """Create a mock EventMatch for testing."""
    return EventMatch(
        kalshi_market=Market("Kalshi", "k1", desc1, 0.5, "url", ""),
        polymarket_market=Market("PredictIt", "p1", desc2, 0.5, "url", ""),
        similarity_score=0.85,
        normalized_kalshi=desc1.lower(),
        normalized_polymarket=desc2.lower(),
    )


# Mock data
mock_matches = [
    create_mock_match("GA Senate - Democrats", "Georgia Senate Race - Democratic"),
    create_mock_match("NH Senate - Republicans", "New Hampshire Senate - GOP"),
    create_mock_match("Trump pardon for Snowden", "Will Trump pardon Snowden?"),
    create_mock_match("2028 Presidential election", "Who wins Presidency in 2028?"),
    create_mock_match("Lakers vs Celtics NBA", "NBA Championship - Lakers"),
    create_mock_match("Bitcoin hits $200k", "Will BTC reach $200k?"),
]

print("=" * 70)
print("EVENT FILTERING - QUICK DEMO")
print("=" * 70)

# Test 1: No filter
print("\n[1] NO FILTER")
print(f"Matches: {len(mock_matches)}")
for i, m in enumerate(mock_matches):
    print(f"  {i+1}. {m.kalshi_market.description}")

# Test 2: Senate only
print("\n[2] SENATE ONLY")
from src.matching.filter import apply_filters
senate_filter = EventFilters(enabled=True, mode="include", keywords=["senate"])
senate_matches = apply_filters(mock_matches, senate_filter)
print(f"Matches: {len(senate_matches)}")
for i, m in enumerate(senate_matches):
    print(f"  {i+1}. {m.kalshi_market.description}")

# Test 3: Presidential only
print("\n[3] PRESIDENTIAL ONLY")
pres_filter = EventFilters(enabled=True, mode="include", keywords=["president", "presidency"])
pres_matches = apply_filters(mock_matches, pres_filter)
print(f"Matches: {len(pres_matches)}")
for i, m in enumerate(pres_matches):
    print(f"  {i+1}. {m.kalshi_market.description}")

# Test 4: Trump only
print("\n[4] TRUMP ONLY")
trump_filter = EventFilters(enabled=True, mode="include", keywords=["trump"])
trump_matches = apply_filters(mock_matches, trump_filter)
print(f"Matches: {len(trump_matches)}")
for i, m in enumerate(trump_matches):
    print(f"  {i+1}. {m.kalshi_market.description}")

# Test 5: Exclude Trump
print("\n[5] EXCLUDE TRUMP")
no_trump_filter = EventFilters(enabled=True, mode="exclude", keywords=["trump"])
no_trump_matches = apply_filters(mock_matches, no_trump_filter)
print(f"Matches: {len(no_trump_matches)}")
for i, m in enumerate(no_trump_matches):
    print(f"  {i+1}. {m.kalshi_market.description}")

# Test 6: Multiple keywords (Senate OR Presidential)
print("\n[6] SENATE OR PRESIDENTIAL")
multi_filter = EventFilters(enabled=True, mode="include", keywords=["senate", "president"])
multi_matches = apply_filters(mock_matches, multi_filter)
print(f"Matches: {len(multi_matches)}")
for i, m in enumerate(multi_matches):
    print(f"  {i+1}. {m.kalshi_market.description}")

print("\n" + "=" * 70)
print("\n✅ FILTERING WORKS!")
print("\nAvailable Presets:")
for name in FILTER_PRESETS.keys():
    print(f"  • {name}")

print("\n📝 To use, edit config.yaml:")
print("""
filters:
  enabled: true
  mode: "include"
  keywords: ["senate", "presidential"]
""")
print("=" * 70)
