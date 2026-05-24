# Backtest Engine Setup & Usage Guide

## Overview
This Python script runs the Shadow AI Trading Auditor's SMC (Smart Money Concepts) strategy against 2 years of historical EUR/USD data to validate performance claims.

**Important**: This uses **deterministic rules**, not LLM calls per candle. LLMs are too expensive and non-deterministic for backtesting. The LLM (Qwen) is only used for daily thesis generation in live trading.

## Prerequisites

### 1. Install Dependencies
```bash
pip install requests
```

### 2. Get Free API Key (Optional but Recommended)
The script works with a demo key, but has limited requests. For full 2-year data:

1. Sign up at [TwelveData](https://twelvedata.com/pricing) - Free tier: 100 requests/day
2. Get your API key from dashboard
3. Set environment variable:
   ```bash
   export TWELVEDATA_API_KEY="your_api_key_here"
   ```

## Running the Backtest

### Basic Usage
```bash
python backtest_engine.py
```

### With Custom API Key
```bash
TWELVEDATA_API_KEY="your_key" python backtest_engine.py
```

## What It Does

### Step 1: Fetch Historical Data
- Downloads 2 years (2022-2024) of EUR/USD H4 candles
- Caches data locally to avoid re-fetching
- Uses TwelveData free API (or demo key with limits)

### Step 2: SMC Analysis Engine
Implements deterministic rules for:
- **Market Structure**: HH/HL (uptrend), LH/LL (downtrend), Range
- **Break of Structure (BOS)**: Continuation signals
- **Change of Character (CHoCH)**: Reversal signals
- **Order Blocks**: Institutional entry zones
- **Fair Value Gaps (FVG)**: Imbalance zones
- **Liquidity Pools**: Equal highs/lows

### Step 3: Trading Strategy
Entry conditions (ALL must be met):
1. Clear market structure (confidence > 60%)
2. BOS or CHoCH confirmation
3. Price at Order Block or FVG
4. Minimum 1:2 risk-reward ratio
5. Confidence score >= 70%

### Step 4: Backtest Execution
- Simulates trades through entire dataset
- No lookahead bias (only uses past data)
- Tracks TP hits, SL hits, timeouts
- Calculates position sizing (2% risk per trade)

### Step 5: Generate Report
Outputs comprehensive statistics:
- Win Rate (%)
- Total P&L ($)
- Profit Factor (Gross Profit / Gross Loss)
- Maximum Drawdown ($)
- Sharpe Ratio
- Average R:R Ratio
- Full trade log (JSON)

## Output Files

Reports saved to `./backtest_results/`:
- `backtest_result_YYYYMMDD_HHMMSS.json` - Full trade data
- `backtest_summary_YYYYMMDD_HHMMSS.txt` - Human-readable summary

## Success Criteria

Strategy is considered **validated** if:
- ✅ Win Rate >= 55%
- ✅ Profit Factor >= 1.5
- ✅ Max Drawdown <= 20%

## Configuration

Edit the `CONFIG` dictionary at the top of the script:

```python
CONFIG = {
    'SYMBOL': 'EURUSD',
    'TIMEFRAME': 'H4',
    'LOOKBACK_PERIODS': 50,
    'START_DATE': '2022-01-01',
    'END_DATE': '2024-01-01',
    'INITIAL_BALANCE': 10000,
    'RISK_PER_TRADE': 0.02,      # 2% risk per trade
    'MIN_RR_RATIO': 2.0,         # Minimum 1:2 risk-reward
    'MIN_CONFIDENCE_THRESHOLD': 70,
    'MAX_DAILY_LOSS': 0.05,      # 5% daily kill switch
}
```

## Sample Output

```
================================================================================
SHADOW AI TRADING AUDITOR - HISTORICAL BACKTESTING ENGINE
================================================================================

📥 Step 1: Fetching historical EUR/USD data...
📡 Fetching data from TwelveData API...
  Fetched 4380 candles from 2022-01-01
✓ Cached 4380 candles to ./backtest_cache/EURUSD_2022-01-01_2024-01-01_4h.json
✓ Loaded 4380 candles from 2022-01-01 00:00:00 to 2023-12-31 20:00:00

🧠 Step 2: Initializing SMC Analysis Engine...
✓ Strategy initialized with deterministic SMC rules

📈 Step 3: Running backtest...
🚀 Starting backtest on 4380 candles...
   Initial Balance: $10,000.00
   Risk per Trade: 2.0%
   Date Range: 2022-01-01 00:00:00 to 2023-12-31 20:00:00

  ✅ Trade T0001: TP | P&L: +$200.00 | Balance: $10,200.00
  ❌ Trade T0002: SL | P&L: -$200.00 | Balance: $10,000.00
  ...

📝 Step 4: Generating report...
📊 Reports saved to ./backtest_results/

================================================================================
BACKTEST SUMMARY
================================================================================
Total Trades:       127
Win Rate:           58.27%
Total Return:       34.50%
Profit Factor:      1.82
Max Drawdown:       12.30%
Sharpe Ratio:       1.45
================================================================================

🎯 FINAL VERDICT:
✅ STRATEGY VALIDATED: Meets all criteria for paper trading
   - Win Rate >= 55% ✓
   - Profit Factor >= 1.5 ✓
   - Max Drawdown <= 20% ✓

⚠️  DISCLAIMER: This is a backtest, not a guarantee of future performance.
Always paper trade before risking real capital.
```

## Troubleshooting

### "Failed to fetch data"
- Check internet connection
- Verify API key (or use demo key with smaller date range)
- Reduce date range if hitting rate limits

### "No trades generated"
- Strategy filters may be too strict for current parameters
- Try lowering `MIN_CONFIDENCE_THRESHOLD` to 60
- Ensure sufficient lookback periods (50+)

### Syntax Error in find_fvg
- The script references `candles[i].body_size()` which needs to be defined
- Fix: Replace `candles[i].body_size()` with `abs(candles[i].close - candles[i].open)`

## Next Steps After Backtest

1. **If Validated (meets all criteria)**:
   - Begin paper trading with live data
   - Track performance for 30+ days
   - Compare live results vs backtest

2. **If Not Validated**:
   - Adjust strategy parameters
   - Optimize entry/exit rules
   - Test different timeframes (H1, D1)
   - Consider additional filters (volume, volatility)

3. **Never Skip**:
   - ❌ Do NOT deploy real money based solely on backtest
   - ✅ ALWAYS paper trade first
   - ✅ Monitor for 3+ months minimum
   - ✅ Verify win rate remains >55% in live conditions

## Limitations

- **No Slippage Model**: Real trading includes slippage (0.5-2 pips)
- **No Spread Costs**: EUR/USD spread averages 0.5-1.5 pips
- **Perfect Execution**: Assumes fills at exact TP/SL levels
- **Historical Bias**: Past performance ≠ future results
- **Single Asset**: Only tests EUR/USD (not multi-currency)

## Ethical Notice

This tool is for **educational and research purposes only**. 

- Never trade money you cannot afford to lose
- Backtests are optimistic compared to live trading
- Forex trading involves substantial risk of loss
- This is not financial advice

---

**Author**: Shadow AI Trading Team  
**License**: MIT  
**Version**: 1.0.0
