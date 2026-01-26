# Event Filtering Guide

## Overview

The system now supports **powerful event filtering** to focus on exactly the types of markets you care about. Instead of monitoring all 42+ event matches, you can narrow down to specific topics like Senate races, presidential markets, sports, crypto, etc.

---

## Quick Start

Edit `config.yaml` and add:

```yaml
filters:
  enabled: true
  mode: "include"
  keywords: ["senate"]
```

Now the system will **only monitor Senate races**!

---

## How It Works

### Two Modes

**1. INCLUDE Mode (Whitelist)**
- Only show matches that contain your keywords
- Use this when you want to focus on specific topics

**2. EXCLUDE Mode (Blacklist)**
- Show all matches EXCEPT those containing your keywords
- Use this to filter out topics you don't care about

### Keyword Matching

- **Case-insensitive**: "Senate" matches "senate", "SENATE", "SeNaTe"
- **Partial matches**: "trump" matches "Trump", "Donald Trump", "Trump's"
- **Searches both platforms**: Checks both Kalshi and PredictIt descriptions
- **OR logic**: If any keyword matches, the event passes the filter

---

## Examples

### Example 1: Senate Races Only

```yaml
filters:
  enabled: true
  mode: "include"
  keywords: ["senate", "senator"]
```

**Result:** Only matches with "senate" or "senator" in the description

**Expected matches:** ~15-20 (from 42 total)
- "GA Senate - Democrats vs Republicans"
- "NH Senate election"
- "Senator Warren re-election"
- etc.

---

### Example 2: Presidential Markets Only

```yaml
filters:
  enabled: true
  mode: "include"
  keywords: ["president", "presidential", "presidency", "potus"]
```

**Result:** Only presidential-related markets

**Expected matches:** ~5-10
- "2028 Presidential election"
- "Presidential pardon"
- "President approval rating"
- etc.

---

### Example 3: All Politics

```yaml
filters:
  enabled: true
  mode: "include"
  keywords:
    - "senate"
    - "house"
    - "congress"
    - "president"
    - "governor"
    - "election"
    - "republican"
    - "democrat"
```

**Result:** Any political market

**Expected matches:** ~30-35 (most of the 42)

---

### Example 4: Trump-Related Only

```yaml
filters:
  enabled: true
  mode: "include"
  keywords: ["trump", "donald trump"]
```

**Result:** Only Trump-related markets

**Expected matches:** ~10-15
- "Trump pardon for X"
- "Trump approval rating"
- "Will Trump do X?"
- etc.

---

### Example 5: Everything EXCEPT Trump

```yaml
filters:
  enabled: true
  mode: "exclude"
  keywords: ["trump"]
```

**Result:** All markets that DON'T mention Trump

**Expected matches:** ~27-32 (42 minus Trump markets)

---

### Example 6: Multiple Specific Topics

```yaml
filters:
  enabled: true
  mode: "include"
  keywords:
    - "senate"
    - "nba"
    - "bitcoin"
    - "oscar"
```

**Result:** Senate races OR NBA OR Bitcoin OR Oscar-related markets

**Expected matches:** Varies based on what's available

---

## Preset Filters

The system includes predefined filter sets for common use cases:

### Politics Presets

**Senate Only:**
```yaml
keywords: ["senate", "senator"]
```

**Presidential Only:**
```yaml
keywords: ["president", "presidential", "presidency", "potus"]
```

**All Politics:**
```yaml
keywords:
  - "senate"
  - "house"
  - "congress"
  - "president"
  - "presidential"
  - "governor"
  - "election"
  - "republican"
  - "democrat"
  - "party"
```

---

### Sports Presets

**NFL Only:**
```yaml
keywords: ["nfl", "football", "super bowl", "chiefs", "patriots", "cowboys"]
```

**NBA Only:**
```yaml
keywords: ["nba", "basketball", "lakers", "celtics", "warriors", "championship"]
```

---

### Crypto Preset

```yaml
keywords: ["bitcoin", "btc", "ethereum", "eth", "crypto", "cryptocurrency"]
```

---

### Entertainment Preset

```yaml
keywords: ["movie", "actor", "actress", "film", "oscar", "emmy", "release"]
```

---

## Advanced Usage

### Combining Include and Exclude

**Scenario:** You want Senate races but NOT Trump-related Senate races

**Solution:** Run two passes (would need code modification) OR use specific keywords:

```yaml
filters:
  enabled: true
  mode: "include"
  keywords:
    - "senate georgia"
    - "senate new hampshire"
    - "senate florida"
    # etc. (be specific about which states)
```

---

### Dynamic Filtering

You can change filters **without restarting the system**:

1. Edit `config.yaml` while the system is running
2. The config is reloaded each cycle
3. New filters apply on the next polling cycle (60 seconds)

**Note:** This may vary based on implementation - safer to restart for now.

---

## Filter Performance

### Without Filters
- Monitors: 42 matches
- Processing time: Fast (all events)

### With Filters
- Monitors: 5-30 matches (depending on keywords)
- Processing time: Slightly faster (fewer events to process)
- Bandwidth: Same (still fetches all markets)

**Filters don't save bandwidth** - they just narrow what you see and calculate arbitrage for.

---

## Complete Configuration Example

```yaml
# config.yaml - Complete example

api_keys:
  kalshi_api_key: "your-email@example.com"
  kalshi_api_secret: "your-password"
  polymarket_api_key: null

fees:
  kalshi:
    maker_fee_pct: 0.0
    taker_fee_pct: 3.0
    withdrawal_cost_usd: 0.0
  polymarket:
    gas_fee_usd: 0.50
    usdc_bridge_cost_usd: 1.00
    trading_fee_pct: 0.0
  predictit:
    profit_fee_pct: 10.0
    withdrawal_fee_pct: 5.0

thresholds:
  min_profit_pct: 3.0
  match_similarity: 0.80
  monitor_threshold_pct: 2.0

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
  webhook_url: "https://discord.com/api/webhooks/YOUR_WEBHOOK"
  enabled: false

polling:
  interval_seconds: 60
  max_retries: 3
  backoff_base: 2

# EVENT FILTERING - Customize what you want to monitor
filters:
  enabled: true
  mode: "include"
  keywords:
    - "senate"
    - "presidential"
```

---

## Real-World Scenarios

### Scenario 1: Day Trader - Fast-Moving Markets

**Goal:** Only monitor markets that change frequently

```yaml
filters:
  enabled: true
  mode: "include"
  keywords: ["2026", "pardon", "cabinet"]  # Near-term events
```

---

### Scenario 2: Long-Term Investor

**Goal:** Only monitor elections (high-value, long-term)

```yaml
filters:
  enabled: true
  mode: "include"
  keywords: ["election", "2026", "2028"]
```

---

### Scenario 3: Specialist - Senate Races Only

**Goal:** Become expert in one market type

```yaml
filters:
  enabled: true
  mode: "include"
  keywords: ["senate"]
```

**Benefit:**
- Monitor 15-20 Senate races instead of 42 total events
- Become expert at Senate race pricing
- Spot mispricing faster

---

### Scenario 4: Avoid Controversial Topics

**Goal:** Don't want Trump-related markets

```yaml
filters:
  enabled: true
  mode: "exclude"
  keywords: ["trump"]
```

---

## Troubleshooting

### No Matches After Enabling Filters

**Problem:** Filters too restrictive

**Solution:**
1. Check spelling of keywords
2. Try broader keywords (e.g., "senate" instead of "senate race")
3. Add more keywords (OR logic means more = more matches)
4. Temporarily disable to see what you're missing:
   ```yaml
   filters:
     enabled: false
   ```

---

### Still Seeing Unwanted Events

**Problem:** Keyword not matching

**Solution:**
1. Check exact description wording in logs
2. Add variations:
   ```yaml
   keywords: ["trump", "donald trump", "djt", "potus trump"]
   ```

---

### Filter Not Taking Effect

**Problem:** Config not reloaded

**Solution:** Restart the system:
```bash
# Stop current run (Ctrl+C)
python -m src.main
```

---

## Logging and Debugging

When filters are enabled, you'll see:

```
2026-01-25 18:00:00 - __main__ - INFO - Event filters: Including only: 'senate', 'presidential'
2026-01-25 18:00:05 - src.matching.filter - INFO - Filtering: 42 → 18 matches (include mode, 2 keywords)
```

This tells you:
- Filter mode (include/exclude)
- Keywords being used
- How many matches before/after filtering

---

## Best Practices

1. **Start Broad:** Begin with 1-2 keywords, add more if needed
2. **Use Include Mode:** Easier to think "what I want" vs "what I don't want"
3. **Test First:** Run without filters to see what's available, then filter
4. **Monitor Logs:** Check filtering output to ensure it's working as expected
5. **Iterate:** Adjust keywords based on what you see

---

## Summary

✅ **Powerful filtering** - Focus on exactly what you want
✅ **Two modes** - Include (whitelist) or Exclude (blacklist)
✅ **Flexible keywords** - Case-insensitive, partial matching
✅ **Easy to use** - Just edit config.yaml
✅ **Predefined presets** - Common use cases included

**The system is now fully customizable to your specific interests!**
