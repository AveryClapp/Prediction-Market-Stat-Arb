# Prediction Market Arbitrage Detection System - Design Document

**Date:** 2026-01-25
**Status:** Approved
**Platform Coverage:** Kalshi, Polymarket (binary markets only)

## Overview

A system that polls Kalshi and Polymarket APIs every 60 seconds to detect risk-free arbitrage opportunities across matched events, accounting for all platform fees and transaction costs. Alerts are sent via Discord webhook with capital-tier color coding, and all opportunities are logged to SQLite for historical analysis.

## Design Principles

- **Correctness over speed**: Conservative matching (90%+ confidence) prevents false positives
- **Sequential processing**: Simple, predictable workflow for debugging
- **Full historical data**: Keep all opportunities for backtesting and analysis
- **Modular design**: Easy to add new platforms (PredictIt, etc.) later

## High-Level Architecture

### 1. Data Collection Layer

**Sequential polling cycle (60 seconds)**:
1. Poll Kalshi API for active binary markets
2. Poll Polymarket API for active binary markets
3. Wait until 60s elapsed since cycle start
4. Repeat

**Client implementation**:
- `KalshiClient` and `PolymarketClient` classes inherit from abstract `BaseClient`
- Each client handles authentication, rate limiting, and error recovery
- Exponential backoff on failures: 1s → 2s → 4s → 8s (max 60s)
- After 3 consecutive failures: send Discord alert but continue retrying
- Track last successful poll timestamp for health monitoring

**Error handling**:
- Transient errors: retry with backoff, log to DB and terminal
- Persistent failures: alert via Discord, keep polling
- Critical errors (DB write failures): alert and exit gracefully

### 2. Event Matching Engine

**Two-phase hybrid matching**:

**Phase 1 - Fast keyword filter**:
- Extract key entities: people names, team names, event types, dates
- Extract outcome types: win/lose, yes/no, victory/defeat
- Normalize: lowercase, remove punctuation, expand abbreviations ("DJT" → "Donald Trump")
- Discard pairs with <50% keyword overlap

**Phase 2 - Semantic similarity**:
- Use sentence transformer model (`all-MiniLM-L6-v2`, ~80MB download)
- Compute cosine similarity between normalized market descriptions
- Match if similarity ≥0.90 (configurable in config.yaml)
- Cache embeddings per market description to avoid recomputation

**Match confidence**: Only 90%+ similarity matches are processed (conservative approach)

**Scalability**: Keyword phase filters 80-90% of non-matches before expensive semantic computation

### 3. Arbitrage Calculator

**Fee calculation** (all values configurable in config.yaml):

**Kalshi fees**:
- Maker fee: 0% (current as of Jan 2026)
- Taker fee: 3%
- Withdrawal cost: $0

**Polymarket fees**:
- Trading fee: 0%
- Polygon gas fee: ~$0.50 average
- USDC bridge cost: ~$1.00

**Calculation logic**:
- For each matched pair, calculate net profit % for both directions:
  - Direction A: Buy on Kalshi, sell on Polymarket
  - Direction B: Sell on Kalshi, buy on Polymarket
- Return the more profitable direction
- Flag as opportunity if net profit ≥ 3% (configurable threshold)
- Calculate required capital for the trade

**Output**: `{net_profit_pct, required_capital, fees_breakdown, is_profitable, direction}`

### 4. Alerting System

**Tiered alerts** (single Discord webhook):

| Tier | Capital Range | Embed Color | Icon |
|------|---------------|-------------|------|
| Small | $0 - $5,000 | Green | 🟢 |
| Medium | $5,001 - $20,000 | Yellow | 🟡 |
| Large | $20,001+ | Red | 🔴 |

**Discord embed format**:
```
🟢 Small Opportunity Detected
Event: Trump wins 2024 election
Kalshi: 48% ($0.48) → Polymarket: 55% ($0.55)
Net Profit: 4.2% | Required Capital: $2,500

[View on Kalshi] [View on Polymarket]
```

**Terminal output**: All opportunities displayed in rich table regardless of tier

### 5. Storage

**SQLite schema** (`data/arbitrage.db`):

```sql
CREATE TABLE arbitrage_opportunities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME NOT NULL,
    kalshi_market_id TEXT NOT NULL,
    polymarket_market_id TEXT NOT NULL,
    event_description TEXT NOT NULL,
    kalshi_price REAL NOT NULL,
    polymarket_price REAL NOT NULL,
    kalshi_probability REAL NOT NULL,
    polymarket_probability REAL NOT NULL,
    net_profit_pct REAL NOT NULL,
    required_capital REAL NOT NULL,
    capital_tier INTEGER NOT NULL,
    kalshi_url TEXT NOT NULL,
    polymarket_url TEXT NOT NULL
);

CREATE INDEX idx_timestamp ON arbitrage_opportunities(timestamp);
CREATE INDEX idx_profit ON arbitrage_opportunities(net_profit_pct);
```

**Retention policy**: Keep all records forever (no automatic cleanup)

**Estimated growth**: ~100MB per year

### 6. Terminal UI

**Layout** (using `rich` library):

```
┌─────────────────────────────────────────────────────────────────┐
│ Prediction Market Arbitrage Monitor                             │
│ Kalshi: ✓ (2s ago) | Polymarket: ✓ (3s ago) | Cycle: 12/60s    │
└─────────────────────────────────────────────────────────────────┘

Active Opportunities (2)
┌──────┬────────────────────┬────────┬────────┬───────┬──────────┐
│ Tier │ Event              │ Profit │ Capital│ Kalshi│ Poly     │
├──────┼────────────────────┼────────┼────────┼───────┼──────────┤
│ 🟢 S │ Trump wins 2024... │  4.2%  │ $2,500 │ 0.48  │ 0.55     │
│ 🟡 M │ Lakers win NBA...  │  3.8%  │ $8,900 │ 0.62  │ 0.68     │
└──────┴────────────────────┴────────┴────────┴───────┴──────────┘

Historical Stats
Total opportunities detected: 47
Total potential profit: $12,450 (across all opportunities)
Average profit per opportunity: 3.9%

Logs (last 5)
[12:34:56] Polled Kalshi: 145 active markets
[12:34:58] Polled Polymarket: 203 active markets
[12:35:02] Matched 12 event pairs
[12:35:03] Found 2 arbitrage opportunities
[12:35:03] Sent Discord alert for 2 opportunities
```

**Keyboard shortcuts**:
- `q`: Quit gracefully
- `r`: Force immediate refresh (skip 60s wait)
- `h`: Show help overlay

**Auto-refresh**: UI updates every polling cycle automatically

## Configuration

**config.yaml structure**:

```yaml
api_keys:
  kalshi_api_key: ""
  kalshi_api_secret: ""
  polymarket_api_key: ""  # If needed

fees:
  kalshi:
    maker_fee_pct: 0.0
    taker_fee_pct: 3.0
    withdrawal_cost_usd: 0.0
  polymarket:
    gas_fee_usd: 0.50
    usdc_bridge_cost_usd: 1.00
    trading_fee_pct: 0.0

thresholds:
  min_profit_pct: 3.0
  match_similarity: 0.90

capital_tiers:
  - max: 5000
    name: "Small"
    color: "green"
  - max: 20000
    name: "Medium"
    color: "yellow"
  - max: 999999999
    name: "Large"
    color: "red"

discord:
  webhook_url: ""
  enabled: true

polling:
  interval_seconds: 60
  max_retries: 3
  backoff_base: 2
```

**Validation on startup**:
- All fee percentages: 0-10%
- All fixed costs: $0-$100
- Capital tiers: ordered correctly
- Discord webhook URL: valid format (if enabled)
- Fail fast with clear error messages

## Project Structure

```
prediction-market-arb/
├── config.yaml
├── config.example.yaml
├── requirements.txt
├── README.md
├── .env.example
├── data/
│   └── arbitrage.db           # gitignored
├── src/
│   ├── __init__.py
│   ├── main.py                # Entry point, orchestrates polling loop
│   ├── config.py              # Config loading and validation
│   ├── clients/
│   │   ├── __init__.py
│   │   ├── base.py            # Abstract base client with retry logic
│   │   ├── kalshi.py          # KalshiClient
│   │   └── polymarket.py      # PolymarketClient
│   ├── matching/
│   │   ├── __init__.py
│   │   ├── matcher.py         # EventMatcher with hybrid algorithm
│   │   └── normalizer.py      # Text normalization utilities
│   ├── arbitrage/
│   │   ├── __init__.py
│   │   └── calculator.py      # Fee calculation and profit logic
│   ├── alerting/
│   │   ├── __init__.py
│   │   └── discord.py         # Discord webhook formatting
│   ├── storage/
│   │   ├── __init__.py
│   │   └── database.py        # SQLite operations
│   └── ui/
│       ├── __init__.py
│       └── terminal.py        # Rich TUI implementation
└── tests/
    ├── __init__.py
    ├── test_matching.py
    ├── test_calculator.py
    └── fixtures/              # Sample API responses
```

## Key Dependencies

- `httpx` - Async HTTP client for API calls
- `rich` - Terminal UI
- `pydantic` - Config validation
- `pyyaml` - Config file parsing
- `sentence-transformers` - Semantic matching
- `rapidfuzz` - Fuzzy string matching
- `aiosqlite` - Async SQLite

## Module Responsibilities

| Module | Responsibility |
|--------|----------------|
| `main.py` | Async event loop, 60s cycle orchestration, graceful shutdown |
| `clients/base.py` | Shared retry logic, rate limiting, error handling |
| `clients/kalshi.py` | Kalshi-specific API calls, authentication |
| `clients/polymarket.py` | Polymarket-specific API calls |
| `matching/matcher.py` | Two-phase matching, caching embeddings |
| `matching/normalizer.py` | Text preprocessing, entity extraction |
| `arbitrage/calculator.py` | Pure functions for profit calculations (no I/O) |
| `alerting/discord.py` | Discord embed formatting, webhook sending |
| `storage/database.py` | All SQL queries, schema creation, indexes |
| `ui/terminal.py` | Rich TUI rendering, keyboard input handling |

## Future Extensibility

**Adding new platforms**:
1. Create new client in `src/clients/new_platform.py` inheriting from `BaseClient`
2. Implement `get_active_markets()` method returning standardized format
3. Add platform to sequential polling in `main.py`
4. Add fee structure to `config.yaml`
5. Update calculator to handle new fee types

**Standardized market format** (internal representation):
```python
{
    "platform": "kalshi",
    "market_id": "abc123",
    "description": "Will Trump win 2024 election?",
    "price": 0.48,
    "url": "https://kalshi.com/...",
    "close_time": "2024-11-05T23:59:59Z"
}
```

## Success Metrics

- **Accuracy**: <1% false positive match rate
- **Latency**: Complete 60s cycle even with 300+ markets per platform
- **Reliability**: 99%+ uptime (handle transient API failures gracefully)
- **Coverage**: Detect 95%+ of true arbitrage opportunities ≥3% profit

## Open Questions

None - design is approved and ready for implementation.
