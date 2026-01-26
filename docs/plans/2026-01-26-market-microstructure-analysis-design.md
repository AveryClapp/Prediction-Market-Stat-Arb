# Market Microstructure Analysis System Design

**Date:** 2026-01-26
**Purpose:** Build data collection and analysis infrastructure for prediction market microstructure blog post

## Overview

Enhance the existing arbitrage detection system to collect comprehensive market microstructure data over 1-2 weeks, then analyze efficiency, liquidity, and opportunity patterns. Output: publication-ready blog post with original research and visualizations.

## Goals

1. **Data Collection**: Capture market state at multiple granularities without overwhelming database
2. **Robustness**: Run unattended for 1-2 weeks with automatic crash recovery
3. **Analysis**: Generate insights on market efficiency, price discovery, and arbitrage characteristics
4. **Blog Post**: Automated report generation with embedded visualizations

## Architecture

### Two-Tier Data Collection Strategy

**Tier 1: Aggregated Stats (Every Cycle)**
- One row per 60-second polling cycle
- High-level metrics: market counts, match counts, correlation, activity
- Enables time-series analysis with minimal storage

**Tier 2: Detailed Records (Selective)**
- Full details for interesting opportunities only
- Criteria: profitable, near-miss, high similarity, inverse arbitrage
- Deduplication prevents redundant records

### Components

```
┌─────────────────────────────────────────────────────────────┐
│                     supervisor.py                            │
│  ┌───────────────────────────────────────────────────────┐  │
│  │                  ArbitrageMonitor                       │  │
│  │  ┌─────────────┐    ┌──────────────────┐             │  │
│  │  │   Polling   │───▶│AnalyticsCollector│───▶Database │  │
│  │  │    Cycle    │    └──────────────────┘             │  │
│  │  └─────────────┘                                      │  │
│  └───────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
                    ┌──────────────────┐
                    │  Analysis Tools  │
                    │  - Analyzer      │
                    │  - Visualizer    │
                    │  - Blog Gen      │
                    └──────────────────┘
```

## Database Schema

### New Table: `market_snapshots`

Captures aggregate market state per polling cycle.

```sql
CREATE TABLE market_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME NOT NULL,
    cycle_duration_ms INTEGER NOT NULL,

    -- Market counts
    kalshi_markets_count INTEGER NOT NULL,
    predictit_markets_count INTEGER NOT NULL,

    -- Matching results
    total_matches INTEGER NOT NULL,
    profitable_matches INTEGER NOT NULL,
    near_miss_matches INTEGER NOT NULL,
    inverse_opportunities INTEGER NOT NULL,

    -- Statistical measures
    avg_price_correlation REAL,
    avg_similarity_score REAL,
    median_spread REAL,

    -- Platform health
    kalshi_api_healthy BOOLEAN NOT NULL,
    predictit_api_healthy BOOLEAN NOT NULL
);

CREATE INDEX idx_snapshot_timestamp ON market_snapshots(timestamp);
```

**Storage**: ~1,440 rows/day (one per minute) = ~20-30K rows for 2 weeks

### New Table: `detailed_matches`

Stores full details for interesting opportunities.

```sql
CREATE TABLE detailed_matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME NOT NULL,

    -- Market identifiers
    kalshi_market_id TEXT NOT NULL,
    predictit_market_id TEXT NOT NULL,
    event_description TEXT NOT NULL,

    -- Prices and spreads
    kalshi_price REAL NOT NULL,
    predictit_price REAL NOT NULL,
    gross_spread REAL NOT NULL,
    net_profit_pct REAL NOT NULL,

    -- Matching quality
    similarity_score REAL NOT NULL,
    match_quality TEXT NOT NULL, -- 'high', 'medium', 'low'

    -- Opportunity characteristics
    required_capital REAL NOT NULL,
    kalshi_fees REAL NOT NULL,
    predictit_fees REAL NOT NULL,
    total_fees REAL NOT NULL,

    -- Classification
    is_profitable BOOLEAN NOT NULL,
    is_near_miss BOOLEAN NOT NULL,
    is_inverse BOOLEAN NOT NULL,
    direction TEXT NOT NULL,

    -- URLs for reference
    kalshi_url TEXT NOT NULL,
    predictit_url TEXT NOT NULL,

    -- Deduplication tracking
    pair_hash TEXT NOT NULL
);

CREATE INDEX idx_detailed_timestamp ON detailed_matches(timestamp);
CREATE INDEX idx_detailed_profitable ON detailed_matches(is_profitable);
CREATE INDEX idx_detailed_pair_hash ON detailed_matches(pair_hash, timestamp);
```

**Storage**: ~50-200 rows/day = ~1K-3K rows for 2 weeks

### Existing Table: `arbitrage_opportunities`

Keep existing table unchanged for backward compatibility. New tables augment, don't replace.

## Data Collection Implementation

### AnalyticsCollector Class

New class in `src/analytics/collector.py`:

```python
class AnalyticsCollector:
    """Collects market microstructure data for analysis."""

    def __init__(self, database: Database, config: Config):
        self.database = database
        self.config = config
        self._seen_pairs = {}  # Deduplication cache

    async def record_cycle(
        self,
        kalshi_markets: list[Market],
        predictit_markets: list[Market],
        matches: list[EventMatch],
        opportunities: list[ArbitrageOpportunity],
        cycle_duration_ms: int
    ):
        """Record aggregated stats for this polling cycle."""
        # Compute aggregate metrics
        # Insert into market_snapshots

    async def record_match(
        self,
        match: EventMatch,
        opportunity: Optional[ArbitrageOpportunity]
    ):
        """Selectively record interesting matches."""
        # Check if interesting
        # Check deduplication
        # Insert into detailed_matches if novel

    def _is_interesting(self, opportunity) -> bool:
        """Determine if match warrants detailed storage."""
        # Profitable OR near-miss OR high-similarity OR inverse

    def _compute_pair_hash(self, kalshi_id, predictit_id) -> str:
        """Generate hash for deduplication."""
        # Hash(kalshi_id + predictit_id)
```

### Integration into Main Loop

Minimal changes to `src/main.py`:

```python
class ArbitrageMonitor:
    def __init__(self, config_path=Path("config.yaml")):
        # ... existing code ...
        self.analytics = AnalyticsCollector(self.database, self.config)

    async def _polling_cycle(self):
        cycle_start = time()

        # ... existing polling and matching code ...

        # NEW: Record analytics
        await self.analytics.record_cycle(
            kalshi_markets=kalshi_markets,
            predictit_markets=predictit_markets,
            matches=matches,
            opportunities=opportunities,
            cycle_duration_ms=int((time() - cycle_start) * 1000)
        )

        # Record individual interesting matches
        for match in matches:
            opportunity = calculate_arbitrage(...)
            await self.analytics.record_match(match, opportunity)
```

### Deduplication Logic

Track recent observations to prevent redundant storage:

```python
def _should_record(self, pair_hash: str, current_price_spread: float) -> bool:
    """Check if we should record this observation."""

    if pair_hash not in self._seen_pairs:
        # First time seeing this pair
        self._seen_pairs[pair_hash] = {
            'last_seen': datetime.now(),
            'last_spread': current_price_spread
        }
        return True

    last_obs = self._seen_pairs[pair_hash]
    time_delta = (datetime.now() - last_obs['last_seen']).total_seconds()
    spread_delta = abs(current_price_spread - last_obs['last_spread'])

    # Record if: >1 hour elapsed OR spread changed >2%
    if time_delta > 3600 or spread_delta > 0.02:
        self._seen_pairs[pair_hash] = {
            'last_seen': datetime.now(),
            'last_spread': current_price_spread
        }
        return True

    return False
```

## Supervisor Script

Simple process monitor in `supervisor.py`:

### Responsibilities

1. **Start Process**: Launch main arbitrage monitor
2. **Health Monitoring**: Check process status every 30 seconds
3. **Auto-Restart**: Restart on crash with exponential backoff
4. **Logging**: Track supervisor activity and child process output
5. **Graceful Shutdown**: Handle Ctrl+C, cleanup child process

### Implementation

```python
class ProcessSupervisor:
    def __init__(self, command: list[str], max_restarts_per_hour: int = 3):
        self.command = command
        self.max_restarts = max_restarts_per_hour
        self.restart_history = []
        self.process = None

    def start(self):
        """Start supervised process."""
        while True:
            if self._too_many_restarts():
                logger.error("Too many restarts, exiting")
                break

            self.process = subprocess.Popen(
                self.command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )

            logger.info(f"Started process PID {self.process.pid}")
            self._write_pid_file()

            # Wait for process to exit
            exit_code = self.process.wait()

            if exit_code != 0:
                logger.warning(f"Process crashed with code {exit_code}")
                self.restart_history.append(datetime.now())
                time.sleep(60)  # Backoff before restart
            else:
                logger.info("Process exited cleanly")
                break

    def _too_many_restarts(self) -> bool:
        """Check if restart rate exceeds threshold."""
        one_hour_ago = datetime.now() - timedelta(hours=1)
        recent = [t for t in self.restart_history if t > one_hour_ago]
        return len(recent) >= self.max_restarts
```

### Usage

```bash
# Start supervised data collection
python supervisor.py

# Run in tmux for long-term collection
tmux new -s arbitrage
python supervisor.py

# Or background with nohup
nohup python supervisor.py > supervisor.log 2>&1 &
```

## Analysis Tools

### Module: `analysis/analyzer.py`

Core analytics class with SQL queries and calculations.

```python
class MarketMicrostructureAnalyzer:
    """Analyzes prediction market microstructure data."""

    def __init__(self, db_path: Path):
        self.db_path = db_path

    # Market Efficiency Metrics
    def get_opportunity_frequency(self) -> pd.DataFrame:
        """Opportunities per day over time."""

    def get_profit_distribution(self) -> pd.Series:
        """Distribution of profit margins."""

    def estimate_opportunity_lifespan(self) -> dict:
        """How long do arbitrage opportunities persist?"""

    # Liquidity & Price Discovery
    def get_price_correlation(self) -> float:
        """Correlation between Kalshi and PredictIt prices."""

    def analyze_spread_by_category(self) -> pd.DataFrame:
        """Price spreads by event type."""

    def get_platform_lead_lag(self) -> dict:
        """Which platform leads price discovery?"""

    # Opportunity Characteristics
    def get_capital_distribution(self) -> pd.Series:
        """Distribution of required capital."""

    def analyze_fee_impact(self) -> dict:
        """Gross vs net profit analysis."""

    def get_inverse_frequency(self) -> dict:
        """Inverse vs regular arbitrage frequency."""

    # Temporal Patterns
    def get_hourly_heatmap(self) -> pd.DataFrame:
        """Opportunities by day-of-week and hour."""

    def get_market_activity_cycles(self) -> pd.DataFrame:
        """Market activity over time."""
```

### Module: `analysis/visualizations.py`

Chart generation using matplotlib/seaborn.

```python
class MarketVisualizer:
    """Generates visualizations for market microstructure analysis."""

    def plot_opportunity_frequency(self, data: pd.DataFrame) -> Figure:
        """Time series: opportunities per day."""

    def plot_profit_distribution(self, data: pd.Series) -> Figure:
        """Histogram + box plot of profit margins."""

    def plot_price_correlation(self, data: pd.DataFrame) -> Figure:
        """Scatter plot: Kalshi vs PredictIt prices."""

    def plot_temporal_heatmap(self, data: pd.DataFrame) -> Figure:
        """Heatmap: opportunities by day/hour."""

    def plot_spread_by_category(self, data: pd.DataFrame) -> Figure:
        """Bar chart: spreads across event types."""

    def plot_fee_impact(self, gross: pd.Series, net: pd.Series) -> Figure:
        """Side-by-side comparison of gross vs net."""
```

### Module: `analysis/blog_report.py`

Automated markdown blog post generation.

```python
class BlogPostGenerator:
    """Generates market microstructure blog post."""

    def __init__(self, analyzer: MarketMicrostructureAnalyzer):
        self.analyzer = analyzer
        self.visualizer = MarketVisualizer()

    def generate(self, output_path: Path):
        """Generate complete blog post with embedded charts."""

        sections = [
            self._intro_section(),
            self._efficiency_section(),
            self._liquidity_section(),
            self._opportunities_section(),
            self._temporal_section(),
            self._conclusion_section()
        ]

        # Write markdown with embedded PNGs
        with open(output_path, 'w') as f:
            f.write('\n\n'.join(sections))

    def _efficiency_section(self) -> str:
        """Generate market efficiency analysis section."""
        # Run analytics
        freq_data = self.analyzer.get_opportunity_frequency()
        profit_data = self.analyzer.get_profit_distribution()

        # Generate charts
        freq_fig = self.visualizer.plot_opportunity_frequency(freq_data)
        profit_fig = self.visualizer.plot_profit_distribution(profit_data)

        # Save charts
        freq_fig.savefig('output/opportunity_frequency.png')
        profit_fig.savefig('output/profit_distribution.png')

        # Generate markdown
        return f"""
## Market Efficiency

Our analysis of {len(freq_data)} days reveals...

![Opportunity Frequency](output/opportunity_frequency.png)

Key findings:
- Average {freq_data['count'].mean():.1f} opportunities per day
- Median profit margin: {profit_data.median():.2f}%
- ...
"""
```

## Analysis Metrics

### Market Efficiency

**Arbitrage Frequency**
- Opportunities per day (time series)
- Distribution across event types
- Weekday vs weekend patterns

**Profit Margins**
- Distribution (histogram)
- Median, mean, percentiles
- Gross vs net (fee impact)

**Opportunity Lifespan**
- Estimate from repeat observations
- Time-to-convergence for near-misses
- Price adjustment speed

### Liquidity & Price Discovery

**Price Correlation**
- Scatter plot: Kalshi vs PredictIt
- Pearson correlation coefficient
- Deviation analysis

**Spread Analysis**
- By event category (politics, sports, etc.)
- By time of day
- By market maturity (time to close)

**Platform Leadership**
- Lagged correlation analysis
- Which platform prices move first?
- Cross-platform arbitrage direction bias

### Opportunity Characteristics

**Capital Requirements**
- Distribution of required capital
- Relationship to profit margin
- Tier analysis (small/medium/large)

**Fee Impact**
- Gross profit vs net profit
- Fee breakdown (trading, gas, bridge)
- Platform fee comparison

**Arbitrage Types**
- Regular vs inverse frequency
- Success rates by type
- Difficulty/complexity analysis

### Temporal Patterns

**Day/Hour Heatmap**
- Opportunities by day-of-week and hour
- Trading hours vs off-hours
- Major event impact (elections, etc.)

**Market Activity Cycles**
- Polling cycle stats over time
- Platform health correlation
- API performance patterns

## Implementation Timeline

### Phase 1: Data Collection (Days 1-3)

**Day 1:**
- Create new database tables
- Implement `AnalyticsCollector` class
- Integration into main loop
- Testing with mock data

**Day 2:**
- Implement supervisor script
- Test crash recovery
- Logging setup
- Deployment preparation

**Day 3:**
- Start supervised data collection
- Monitor first 24 hours
- Fix any issues
- Let it run

### Phase 2: Data Collection Period (Days 4-17)

- Monitor periodically (daily check-in)
- Ensure supervisor is working
- Verify data quality
- ~2 weeks of unattended operation

### Phase 3: Analysis & Blog (Days 18-21)

**Day 18:**
- Implement `MarketMicrostructureAnalyzer`
- Test queries on collected data
- Validate metrics

**Day 19:**
- Implement `MarketVisualizer`
- Generate all charts
- Review visualizations

**Day 20:**
- Implement `BlogPostGenerator`
- Generate draft blog post
- Review and refine

**Day 21:**
- Polish blog post
- Add commentary and insights
- Finalize for publication

## Deliverables

1. **Enhanced Arbitrage Monitor**
   - Two-tier data collection
   - Minimal performance impact
   - Rich microstructure data

2. **Supervisor Script**
   - Auto-restart on crashes
   - Health monitoring
   - Robust for 1-2 weeks unattended

3. **Analysis Tools**
   - `analyzer.py` - SQL-based analytics
   - `visualizations.py` - Chart generation
   - `blog_report.py` - Automated report

4. **Blog Post**
   - Market microstructure analysis
   - Original research and insights
   - Publication-ready with visualizations

5. **Reusable Infrastructure**
   - Tools for future data collection
   - Analysis framework for other studies
   - Portfolio-ready demonstration

## Success Criteria

- [ ] Collect 1-2 weeks of continuous data
- [ ] <5% downtime (supervisor handles crashes)
- [ ] Database size <100MB
- [ ] Generate 10+ meaningful visualizations
- [ ] Blog post 2,000-3,000 words
- [ ] Demonstrate 3+ novel insights about market microstructure
