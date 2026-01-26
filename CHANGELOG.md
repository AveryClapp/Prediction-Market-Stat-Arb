# Changelog

All notable changes to this project will be documented in this file.

## [1.0.0] - 2026-01-25

### Added
- Real-time arbitrage detection across Kalshi and PredictIt prediction markets
- Hybrid two-phase event matching (keyword filtering + semantic similarity)
- Inverse arbitrage detection (betting opposite outcomes across platforms)
- Comprehensive fee calculation including maker/taker fees, gas fees, and bridge costs
- Tiered Discord webhook alerts based on capital requirements
- Live terminal UI with real-time opportunity display
- SQLite database for historical tracking and analysis
- Configurable event filtering (whitelist/blacklist by keywords)
- Near-arbitrage monitoring (tracks opportunities close to profitable)
- Automatic retry logic with exponential backoff for API failures
- Platform health monitoring and downtime alerts

### Features
- Sequential polling architecture (Kalshi → PredictIt → Match → Calculate)
- 90%+ confidence matching using sentence transformer embeddings
- Support for small ($0-5k), medium ($5k-20k), and large ($20k+) capital tiers
- Configurable profit thresholds and matching sensitivity
- Graceful shutdown handling
- Comprehensive logging system

### Technical
- Async/await architecture for efficient I/O
- Type hints with Pydantic for configuration validation
- Modular client design supporting easy platform additions
- Rich terminal UI with live updates
- Sentence transformers for semantic matching
- RapidFuzz for keyword similarity
