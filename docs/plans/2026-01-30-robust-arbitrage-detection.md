# Robust Arbitrage Detection System - Design Document

**Date**: 2026-01-30
**Status**: Approved
**Philosophy**: Precision over recall - trustworthy alerts only

## Problem Statement

Current system produces false positives (e.g., "121% profit" on Trump/Greenland markets) due to:
1. Low similarity threshold (80%) catching vaguely related events
2. Broken inverse arbitrage detection (prices 0.17 + 0.07 ≠ 1.0 but still triggered)
3. Limited market coverage (PredictIt only, which is politics-heavy)
4. Weak validation allowing questionable matches through

**Goal**: Build a precision-focused system that only alerts on highly confident arbitrage opportunities.

## Core Design Principles

1. **Precision over recall** - Better to miss opportunities than alert on false positives
2. **Conservative profit calculations** - Always assume worst-case fees and slippage
3. **Strict validation** - Multiple validation layers before any alert
4. **Multi-platform support** - Kalshi vs Polymarket (primary) + PredictIt (optional)
5. **Narrow and robust** - If it must be narrow to be reliable, make it narrow

## Architecture Changes

### 1. Matching Engine Overhaul

**Current issues**:
- 80% similarity threshold too low
- Inverse detection broken (allows any price sum < 1.15)
- Date filtering has bugs
- Action verb detection doesn't catch semantic differences

**New matching pipeline**:

```
Phase 1: Keyword Filter (unchanged)
  - 20% keyword overlap required
  - Fast filtering to reduce semantic matching load

Phase 2: Strict Semantic Matching
  Layer 1: High Similarity
    - Require 95%+ similarity (up from 80%)
    - Use sentence transformers (all-MiniLM-L6-v2)

  Layer 2: Date Alignment
    - Markets must expire within 7 days (down from 14)
    - Reject if dates extractable but mismatched
    - Extract from API, market ID, or description

  Layer 3: Price Sanity Checks
    - Both prices must be 0.05-0.95 (reject edge cases)
    - Minimum spread of 5% (below this, fees eat profit)

  Layer 4: Inverse Detection (if applicable)
    - Only triggered if attempting inverse arbitrage
    - See separate section for strict requirements
```

**Quality grading**:
- **A-Grade** (95-100% similarity, same dates, clear profit): Auto-alert
- **B-Grade** (90-95% similarity, close dates, marginal profit): Alert with warning
- **C-Grade** (85-90% similarity, any issues): Log only, no alert
- **D-Grade** (<85% similarity): Reject completely

### 2. Strict Inverse Arbitrage Detection

**Current bug**: Code allows prices summing to <1.15 to pass as inverse arbitrage, catching completely different questions.

**New requirements** (ALL must be true):

```python
1. Price Sum Validation
   - Must be 0.95 ≤ (price1 + price2) ≤ 1.05
   - Tighter bounds prevent false matches

2. High Semantic Similarity
   - Require 95%+ similarity (same as regular matching)
   - Markets must be about the same event

3. Explicit Pattern Match (at least one required)
   - Opposite parties: "democrat" vs "republican"
   - Explicit markers: " - yes" vs " - no"
   - Clear opposites: "over X" vs "under X"
   - Win/lose pairs with same subject

4. No Conflicting Subjects
   - Both must be about the same base event
   - Different actions (buy vs visit) = reject
```

**Example PASS**:
```
Market 1: "Will Democrats win Senate majority?" (price: 0.52)
Market 2: "Will Republicans win Senate majority?" (price: 0.48)
✓ Prices sum to 1.00
✓ Explicit party opposition
✓ 98% similarity
✓ Same event (Senate majority)
```

**Example REJECT** (current false positive):
```
Market 1: "Will Trump buy Greenland?" (price: 0.17)
Market 2: "Will the US purchase Greenland in 2026?" (price: 0.07)
✗ Prices sum to 0.24 (not even close to 1.0)
✗ These are the SAME question, not opposites
✗ Only 80% similarity (below 95% threshold)
```

### 3. Multi-Platform Integration

**Current state**: Polymarket client exists but is unused. Code references "polymarket" in variable names but actually uses PredictIt data.

**New platform strategy**:

```
Supported platforms:
  1. Kalshi (primary)
     - Most liquid
     - Low fees (0% maker, 3% taker)
     - Good API

  2. Polymarket (secondary)
     - Diverse markets (crypto, sports, politics, entertainment)
     - Low fees (~$1.50 total for gas + bridge)
     - Large volume

  3. PredictIt (tertiary, optional)
     - Politics only
     - High fees (10% on profits + 5% withdrawal = 15% total)
     - Small market caps ($850 limit)
     - Enable via config flag
```

**Matching strategy**:
```
1. Poll all enabled platforms
2. Match Kalshi vs Polymarket first (better fees, more markets)
3. Match Kalshi vs PredictIt if enabled (high fees, politics only)
4. Deduplicate opportunities across platform pairs
5. Rank by net profit after fees
```

**Fee structures**:
```yaml
kalshi:
  maker_fee_pct: 0.0
  taker_fee_pct: 3.0
  withdrawal_cost_usd: 0.0

polymarket:
  trading_fee_pct: 0.0
  gas_fee_usd: 0.50
  usdc_bridge_cost_usd: 1.00

predictit:
  profit_fee_pct: 10.0      # 10% on profits
  withdrawal_fee_pct: 5.0   # 5% on withdrawals
```

**Code cleanup**:
- Rename all `polymarket_*` variables to `platform2_*` or dynamic names
- Update database schema to use generic platform names
- Fix variable naming confusion throughout codebase

### 4. Validation Pipeline

**Every match passes through strict validation**:

```
Validation Pipeline:
├─ 1. Similarity Check
│   └─ Must be ≥ 95% (or 90% for B-grade with warning)
│
├─ 2. Date Alignment
│   ├─ Markets expire within 7 days of each other
│   ├─ Extract from API, market ID patterns, or description
│   └─ Reject if extractable but mismatched
│
├─ 3. Price Sanity
│   ├─ Both prices between 0.05 and 0.95
│   ├─ No extreme edge cases (0.01 or 0.99)
│   └─ Reject obvious data errors
│
├─ 4. Spread Minimum
│   ├─ Price difference ≥ 5% (for regular arbitrage)
│   ├─ Below this, fees consume all profit
│   └─ Exception: inverse arbitrage uses different logic
│
├─ 5. Net Profit After Fees
│   ├─ Must be ≥ min_profit_pct (default 3%)
│   ├─ Calculate ALL fees: trading, gas, withdrawal, bridge
│   ├─ Assume worst case (taker fees everywhere)
│   └─ Add 10% buffer for slippage on Polymarket gas
│
├─ 6. Inverse Detection
│   └─ If inverse, apply strict validation (see section 2)
│
└─ 7. Manual Review Flag
    └─ Any warnings → flag for manual review
```

**Conservative profit calculation**:
```python
# Always assume worst case
fees = max(maker_fee, taker_fee)  # Use taker
gas_estimate = base_gas * 1.10    # 10% buffer for spikes
total_fees = trading + gas + withdrawal + bridge

# Net profit must exceed threshold
net_profit_pct = (gross_profit - total_fees) / required_capital * 100
if net_profit_pct < min_profit_pct:
    reject()
```

### 5. Monitoring, Alerting & Error Handling

**Alerting strategy**:

```
Alert only on A-Grade opportunities:
  ✓ 95%+ similarity
  ✓ Dates aligned
  ✓ Net profit ≥ threshold
  ✓ All validations pass

Alert channels:
  1. Discord webhook
     - Quality grade (A/B/C)
     - Similarity score
     - Full fee breakdown
     - Direct market links
     - Warning flags (if any)
     - "DO NOT TRADE" disclaimer

  2. Terminal UI
     - Color-coded by grade (green=A, yellow=B, gray=rejected)
     - Live opportunity table
     - Rejection statistics

  3. Database
     - Log everything (opportunities + rejections)
     - Track rejection reasons
     - Enable analysis and calibration
```

**Alert content format**:
```
🟢 A-GRADE ARBITRAGE OPPORTUNITY

Event: Will Democrats win Senate majority?
Similarity: 98.5% | Quality: A

Kalshi:  Buy YES at $0.48 → Sell for $1.00 if wins
Polymarket: Sell YES at $0.52 → Pay $0.52 if wins

Net Profit: 4.2% after all fees
Required Capital: $1,003.50

Fee Breakdown:
  Kalshi taker fee: $14.40 (3% of $480)
  Polymarket gas: $0.50
  USDC bridge: $1.00
  Total fees: $15.90

Links:
  Kalshi: https://kalshi.com/markets/...
  Polymarket: https://polymarket.com/event/...

⚠️ EDUCATIONAL ONLY - NOT TRADING ADVICE
```

**Error handling**:

```
API Failures:
  - Retry with exponential backoff (already implemented)
  - Continue on partial failure (one platform down → log, don't crash)
  - Alert if platform down for 3+ consecutive cycles
  - Track API health in database

Data Quality:
  - Reject any market with missing/invalid price
  - Log markets with unparseable dates (for debugging)
  - Validate price ranges (0.01-0.99)
  - Track malformed data from each platform

Database Issues:
  - Fix "readonly database" error (permissions issue)
  - Graceful degradation (if DB fails, still show in terminal)
  - Auto-retry DB operations with timeout
  - Log but don't crash on DB errors

Rate Limiting:
  - Respect platform rate limits
  - Exponential backoff on 429 responses
  - Queue requests if needed
```

**Logging & debugging**:

```
Log ALL rejected matches with reason codes:
  - REJECT_SIMILARITY: Below 95% threshold
  - REJECT_DATE: Markets expire >7 days apart
  - REJECT_PRICE: Prices outside 0.05-0.95 range
  - REJECT_SPREAD: Price difference too small
  - REJECT_FEES: Net profit below threshold
  - REJECT_INVERSE: Failed inverse validation
  - REJECT_SANITY: Failed basic sanity checks

Track rejection statistics:
  - Count by rejection reason
  - Average similarity of rejected matches
  - Most common rejection patterns
  - Platform-specific rejection rates

Weekly summary report:
  - Total opportunities found
  - Opportunities by grade (A/B/C)
  - Rejections by reason
  - Platform health statistics
  - False positive rate (if user feedback available)
```

## Implementation Plan

### Phase 1: Fix Critical Bugs
1. Fix inverse arbitrage detection (tighten price sum bounds)
2. Raise similarity threshold to 95%
3. Fix database permissions issue
4. Add strict validation pipeline

### Phase 2: Platform Integration
1. Integrate Polymarket client into main.py
2. Update fee calculations for Polymarket
3. Rename polymarket_* variables to platform2_*
4. Add config flag for PredictIt (optional)

### Phase 3: Quality & Monitoring
1. Implement quality grading (A/B/C/D)
2. Add detailed rejection logging
3. Improve alert formatting with fee breakdown
4. Add weekly summary statistics

### Phase 4: Testing & Calibration
1. Test on historical data
2. Validate no false positives
3. Calibrate thresholds if needed
4. Document edge cases

## Success Metrics

**Primary**: Zero false positives (no "121% profit" nonsense)
**Secondary**: Find 1-5 real opportunities per week (if they exist)
**Tertiary**: All alerts are A-grade or B-grade with warnings

**Not a success metric**: Number of opportunities (quality > quantity)

## Configuration Changes

```yaml
thresholds:
  min_profit_pct: 3.0           # Minimum net profit to alert
  match_similarity: 0.95         # Raised from 0.80
  inverse_price_sum_min: 0.95    # New: strict inverse bounds
  inverse_price_sum_max: 1.05    # New: strict inverse bounds
  min_price_spread_pct: 5.0      # New: minimum spread for regular arb
  date_alignment_days: 7         # Tightened from 14

platforms:
  kalshi:
    enabled: true
  polymarket:
    enabled: true              # New: enable Polymarket
  predictit:
    enabled: false             # New: make PredictIt optional

quality_grading:
  a_grade_min_similarity: 0.95
  b_grade_min_similarity: 0.90
  c_grade_min_similarity: 0.85
  auto_alert_grades: ["A"]     # Only auto-alert on A-grade
```

## Risk Mitigation

**Risk**: Too strict thresholds = no opportunities found
**Mitigation**: Log all rejections with reasons; calibrate thresholds based on real data

**Risk**: Polymarket integration breaks existing PredictIt functionality
**Mitigation**: Test both platforms independently; use feature flags

**Risk**: Still finding false positives despite strict validation
**Mitigation**: Manual review of first 100 alerts; iterate on validation logic

**Risk**: Fees make everything unprofitable
**Mitigation**: Focus on high-volume markets; consider this a research tool, not trading system

## Future Enhancements (Out of Scope)

- Automated trading execution
- Real-time WebSocket feeds (vs 60s polling)
- Machine learning for match quality prediction
- Multi-leg arbitrage (3+ platforms)
- Options/derivative arbitrage

## Conclusion

This design prioritizes reliability over coverage. By raising similarity thresholds, tightening inverse detection, adding strict validation, and integrating Polymarket, we create a system that:

1. **Produces trustworthy alerts** - Every alert should be worth investigating
2. **Handles multiple platforms** - More market diversity = more opportunities
3. **Degrades gracefully** - API failures don't crash the system
4. **Provides transparency** - Clear fee breakdowns and quality scores

The system may find fewer opportunities, but every one will be real.
