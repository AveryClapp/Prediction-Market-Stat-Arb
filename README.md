# Prediction Market Arbitrage Detection System

A real-time arbitrage detection system that identifies risk-free profit opportunities across Kalshi and Polymarket prediction markets.

## Features

- **Automated Polling**: Fetches active binary markets from Kalshi and Polymarket every 60 seconds
- **Intelligent Matching**: Hybrid two-phase event matching using keyword filtering + semantic similarity (90%+ confidence)
- **Accurate Profit Calculation**: Accounts for all fees including Kalshi maker/taker fees, Polymarket gas fees, and USDC bridge costs
- **Tiered Alerting**: Discord webhook alerts with color-coded capital tiers (small/medium/large opportunities)
- **Historical Tracking**: SQLite database stores all opportunities for analysis
- **Live Terminal UI**: Real-time dashboard showing active opportunities, platform status, and historical stats

## Requirements

- Python 3.10+
- Kalshi account with API credentials
- (Optional) Discord webhook for alerts

## Installation

### 1. Clone and Install Dependencies

```bash
git clone <repository-url>
cd Prediction-Market-Stat-Arb
pip install -r requirements.txt
```

### 2. Configure API Credentials

Copy the example configuration and add your credentials:

```bash
cp config.example.yaml config.yaml
```

Edit `config.yaml` and fill in:
- **Kalshi API credentials**: Your Kalshi email and password (get from https://kalshi.com/account/api-keys)
- **Discord webhook URL** (optional): Create one in Discord: Server Settings → Integrations → Webhooks

### 3. Adjust Fee Structures (Optional)

The default config includes current fee structures as of January 2026:
- Kalshi: 0% maker fee, 3% taker fee, $0 withdrawal
- Polymarket: $0.50 gas fee, $1.00 bridge cost, 0% trading fee

Update these in `config.yaml` if platforms change their fees.

### 4. Configure Alert Thresholds (Optional)

Default settings:
- **Minimum profit**: 3% after all fees
- **Match similarity**: 0.90 (90% confidence)
- **Capital tiers**: Small ($0-$5k), Medium ($5k-$20k), Large ($20k+)

Adjust in `config.yaml` to match your risk tolerance and capital availability.

## Usage

### Run the Monitor

```bash
python -m src.main
```

The terminal UI will display:
- **Header**: Platform connection status and polling cycle progress
- **Active Opportunities**: Real-time table of profitable arbitrage opportunities
- **Historical Stats**: Total opportunities detected, potential profit, average profit %
- **Activity Logs**: Recent system events

### Keyboard Shortcuts

- `q` - Quit the monitor
- `Ctrl+C` - Graceful shutdown

### Understanding the Output

**Opportunity Table Columns**:
- **Tier**: Capital tier (🟢 Small, 🟡 Medium, 🔴 Large)
- **Event**: Market description
- **Profit**: Net profit % after all fees
- **Capital**: Total capital required for the trade
- **Kalshi**: Kalshi market price (0-1)
- **Poly**: Polymarket price (0-1)

**Discord Alerts**:
Each opportunity triggers a color-coded Discord embed with:
- Event description
- Trade direction (buy platform A, sell platform B)
- Net profit % and required capital
- Direct links to both markets
- Fee breakdown

## How It Works

### 1. Sequential Polling
Every 60 seconds, the system:
1. Polls Kalshi API for active binary markets
2. Polls Polymarket API for active binary markets

### 2. Event Matching (Hybrid Two-Phase)

**Phase 1 - Keyword Filtering**:
- Normalizes market descriptions (lowercase, remove punctuation, expand abbreviations)
- Extracts keywords and calculates overlap ratio
- Filters out pairs with <50% keyword overlap

**Phase 2 - Semantic Similarity**:
- Uses sentence transformer model (`all-MiniLM-L6-v2`) to compute embeddings
- Calculates cosine similarity between market descriptions
- Matches only if similarity ≥0.90 (configurable)

### 3. Arbitrage Calculation

For each matched pair:
- Evaluates both directions (buy Kalshi/sell Poly AND buy Poly/sell Kalshi)
- Calculates gross profit (price difference)
- Subtracts all fees (platform fees, gas, bridge costs)
- Returns net profit % and required capital
- Flags as opportunity if net profit ≥ minimum threshold

### 4. Alerting & Storage

- Stores all opportunities in SQLite database (`data/arbitrage.db`)
- Sends tiered Discord alerts based on required capital
- Updates live terminal UI

## Project Structure

```
prediction-market-arb/
├── config.yaml              # Your configuration (gitignored)
├── config.example.yaml      # Template configuration
├── requirements.txt         # Python dependencies
├── data/
│   └── arbitrage.db        # SQLite database (auto-created)
├── src/
│   ├── main.py             # Entry point and orchestration
│   ├── config.py           # Configuration loading/validation
│   ├── clients/
│   │   ├── base.py         # Base client with retry logic
│   │   ├── kalshi.py       # Kalshi API client
│   │   └── polymarket.py   # Polymarket API client
│   ├── matching/
│   │   ├── matcher.py      # Event matching engine
│   │   └── normalizer.py   # Text normalization
│   ├── arbitrage/
│   │   └── calculator.py   # Fee calculation and profit logic
│   ├── alerting/
│   │   └── discord.py      # Discord webhook alerts
│   ├── storage/
│   │   └── database.py     # SQLite operations
│   └── ui/
│       └── terminal.py     # Rich TUI
└── tests/
    └── fixtures/           # Test data
```

## Extending to New Platforms

To add a new platform (e.g., PredictIt):

1. Create `src/clients/predictit.py` inheriting from `BaseClient`
2. Implement `get_active_markets()` returning standardized `Market` objects
3. Add fee structure to `config.yaml`
4. Update `src/main.py` to poll the new platform in sequence
5. Update `calculate_arbitrage()` if the platform has unique fee structures

## Troubleshooting

### "Config file not found"
Run `cp config.example.yaml config.yaml` and fill in your credentials.

### "Kalshi authentication failed"
Verify your email and password in `config.yaml` are correct. Note: Kalshi uses your account email/password, not separate API keys.

### "No opportunities found"
This is normal! True arbitrage is rare. The system is working correctly if you see:
- Platform status shows green checkmarks
- Markets are being polled successfully
- Event matches are being found (check logs)

Arbitrage opportunities are fleeting and may only appear a few times per day.

### Discord alerts not working
1. Verify `discord.enabled: true` in config.yaml
2. Check webhook URL is correct format: `https://discord.com/api/webhooks/...`
3. Test webhook manually using curl

## Security Notes

- `config.yaml` contains API credentials and is automatically gitignored
- Never commit your `config.yaml` to version control
- Store API credentials securely
- The system only requires read-only API access (no trading execution)

## Performance

- **Polling interval**: 60 seconds (configurable)
- **Market capacity**: Handles 500+ markets per platform
- **Matching speed**: Phase 1 filters 80-90% of pairs in <1s, Phase 2 semantic matching on remaining candidates
- **Model download**: First run downloads sentence transformer model (~80MB)

## License

MIT

## Disclaimer

This tool is for educational and research purposes. Arbitrage opportunities identified by this system:
- May disappear before you can execute trades
- Require manual verification before execution
- Do not account for slippage, liquidity constraints, or execution delays
- Are not investment advice

Always verify calculations and market conditions before executing any trades.
