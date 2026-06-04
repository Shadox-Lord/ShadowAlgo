# Shadow Portfolio Hub - End-to-End Deployment Blueprint

## Executive Summary

This document provides a chronological, step-by-step guide to deploying the **Shadow Portfolio Hub** unified trading ecosystem to a 24/5 cloud environment. The system merges four distinct strategies (NQ ORB, Gold Pullback, Grading Bot) into a single Master EA with centralized risk management.

---

## Phase 1: Infrastructure Staging

### 1.1 Cloud Provider Selection

**Recommended:** GCP Windows Server or AWS EC2 Windows
- **Instance Type:** Minimum 2 vCPU, 4GB RAM
- **OS:** Windows Server 2019/2022
- **Location:** Choose region closest to broker's server (typically London NY4 for forex, Chicago for futures)
- **Uptime SLA:** 99.9% minimum

### 1.2 Network Configuration

```
┌─────────────────────────────────────────────────────────────┐
│                    INTERNET                                  │
│         ┌──────────────────────────────────────┐            │
│         │  Cloud VPS (GCP/AWS Windows Server)  │            │
│         │  ┌────────────────────────────────┐  │            │
│         │  │      MetaTrader 5 Terminal     │  │            │
│         │  │  ┌──────────────────────────┐  │  │            │
│         │  │  │  Shadow_Portfolio_Hub    │  │  │            │
│         │  │  │     (Master EA)          │  │  │            │
│         │  │  └──────────────────────────┘  │  │            │
│         │  └────────────────────────────────┘  │            │
│         └──────────────────────────────────────┘            │
│                          │                                   │
│         ┌────────────────┼────────────────┐                 │
│         ▼                ▼                ▼                 │
│    ┌─────────┐    ┌─────────┐    ┌─────────┐               │
│    │ Broker  │    │ Twelve  │    │ Alibaba │               │
│    │  MT5    │    │  Data   │    │ DashScope│              │
│    │ Server  │    │  API    │    │  (Qwen) │               │
│    └─────────┘    └─────────┘    └─────────┘               │
└─────────────────────────────────────────────────────────────┘
```

### 1.3 Security Hardening

1. **Windows Firewall Rules:**
   - Allow outbound: TCP 443 (HTTPS), TCP 80 (HTTP)
   - Block all inbound except RDP (change default port from 3389)

2. **User Account Setup:**
   - Create dedicated user `MT5Trader` (non-administrator)
   - Enable automatic login for this account
   - Set strong password policy

3. **Antivirus Exclusions:**
   - Add exclusions for: `C:\Program Files\MetaTrader 5\`
   - Exclude `.mq5`, `.ex5`, `.dll` files from real-time scanning

---

## Phase 2: Environment Setup

### 2.1 MetaTrader 5 Installation

1. Download MT5 installer from your broker
2. Install to default location: `C:\Program Files\MetaTrader 5\`
3. Login with demo/paper trading account first
4. Verify connectivity and data feed

### 2.2 Directory Structure

Create the following structure in MT5 data folder:

```
C:\Users\[Username]\AppData\Roaming\MetaQuotes\Terminal\[InstanceID]\
├── MQL5\
│   ├── Experts\
│   │   └── Shadow_Portfolio_Hub.mq5    ← Main EA file
│   ├── Include\
│   │   └── (Standard MQL5 libraries auto-installed)
│   ├── Presets\
│   │   └── Shadow_Hub_Default.set      ← Settings preset
│   ├── Logs\
│   │   └── (Auto-generated)
│   └── Files\
│       └── Shadow_Hub_Performance_*.csv ← Trade exports
```

### 2.3 File Deployment Steps

1. **Copy EA File:**
   ```
   Source: /workspace/Shadow_Portfolio_Hub.mq5
   Destination: C:\Program Files\MetaTrader 5\MQL5\Experts\
   ```

2. **Compile in MetaEditor:**
   - Open MetaEditor (F4 from MT5 terminal)
   - Navigate to `Experts/Shadow_Portfolio_Hub.mq5`
   - Press F7 to compile
   - Verify "0 errors, 0 warnings" in compilation log

3. **Verify Compilation Output:**
   - Check that `Shadow_Portfolio_Hub.ex5` is created in same directory
   - File size should be ~50-100KB

### 2.4 Environment Variables (Optional)

For Python-based components (backtesting, WFA):

```powershell
# Set in Windows System Properties → Environment Variables
QWEN_API_KEY=sk-your-dashscope-api-key
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN_MODEL=qwen-plus
TWELVEDATA_API_KEY=your-twelvedata-key
```

---

## Phase 3: Configuration & Initialization

### 3.1 Attach EA to Chart

1. Open MT5 terminal
2. Open chart for primary symbol (e.g., EURUSD H1)
3. Drag `Shadow_Portfolio_Hub` from Navigator → Expert Advisors onto chart
4. Enable "Allow Algo Trading" (top toolbar button)
5. Enable "Auto Trading" in EA properties

### 3.2 Input Parameter Configuration

Configure the following inputs in EA Properties → Inputs tab:

#### Global Risk Settings
| Parameter | Recommended Value | Notes |
|-----------|------------------|-------|
| Inp_GlobalRiskPct | 0.30 | 0.30% risk per trade |
| Inp_EnableNewsFilter | true | Enable NFP/CPI/FOMC blackout |
| Inp_EnableFridayClose | true | Close positions Friday 20:00 UTC |

#### Strategy-Specific Settings
| Strategy | Enable? | Symbols | Notes |
|----------|---------|---------|-------|
| NQ ORB | false (unless US100 chart) | US100, NQ | For Nasdaq only |
| Shadow | true | EURUSD, GBPUSD | London Killzone |
| Gold Pullback | true | XAUUSD, GOLD | H1 timeframe |
| Grading Bot | true | Any | Multi-asset |

### 3.3 Magic Number Verification

Ensure no other EAs use these magic numbers:
- 550000 (NQ ORB)
- 660000 (Shadow - now archived/decommissioned)
- 770000 (Gold Pullback)
- 880000 (Grading Bot)

Check existing positions:
```mql5
// Run this in a new EA temporarily to verify
void OnStart() {
   for(int i=0; i<PositionsTotal(); i++) {
      Print("Position ", i, " Magic: ", PositionGetInteger(POSITION_MAGIC));
   }
}
```

---

## Phase 4: System Verification

### 4.1 Pre-Launch Checklist

Before enabling live autonomous trading:

- [ ] **Compilation:** Zero errors/warnings in MetaEditor
- [ ] **Journal Log:** No initialization errors in MT5 Journal tab
- [ ] **Indicator Handles:** All indicators load successfully (check Experts log)
- [ ] **Broker Filling Mode:** Auto-detected correctly (FOK/IOC/RETURN)
- [ ] **Magic Numbers:** No conflicts with existing EAs
- [ ] **Network Connectivity:** Ping broker server < 50ms
- [ ] **Account Type:** Verified as Hedging or Netting (EA supports both)
- [ ] **Minimum Balance:** At least $1,000 for proper lot sizing

### 4.2 Diagnostic Test Sequence

Run this sequence to verify all systems:

1. **Test 1: Daily Reset Trigger**
   - Wait for midnight server time or manually trigger
   - Verify journal shows: `[RISK] New Day Reset. Balance: $XXXX`

2. **Test 2: News Blackout Detection**
   - Check journal during NFP/CPI/FOMC events
   - Verify: `[BLACKOUT] NFP` or similar message appears

3. **Test 3: Friday Close Protection**
   - On Friday 20:00 UTC, verify all positions close automatically
   - Journal should show: `[RISK] Friday Close Protection`

4. **Test 4: Module Trade Cap**
   - Manually place 2 trades for a strategy
   - Attempt 3rd trade - should be blocked
   - Journal: `[RISK] Module X trade count: 2`

5. **Test 5: Emergency Stop (E-Stop)**
   - Simulate by setting `Inp_GlobalRiskPct` extremely high temporarily
   - Or wait for natural drawdown
   - Verify all positions close and trading halts

### 4.3 CSV Export Verification

After any trade activity:
1. Navigate to `MQL5/Files/` folder
2. Locate `Shadow_Hub_Performance_YYYY-MM-DD.csv`
3. Verify columns: Timestamp, StrategyID, MagicNumber, Type, Lots, Price, SL, TP, Result
4. Cross-reference with MT5 History tab

---

## Phase 5: Live Autonomous Trading

### 5.1 Paper Trading Phase (MANDATORY - 30 Days Minimum)

**DO NOT SKIP THIS PHASE**

1. Run on demo account for 30 consecutive days
2. Log every trade in external spreadsheet:
   - Date/Time
   - Strategy ID
   - Direction
   - Entry/Exit
   - P&L
   - Reason for entry (from journal)
3. Calculate metrics weekly:
   - Win Rate
   - Profit Factor
   - Max Drawdown
   - Average RR

**Pass Criteria for Live Deployment:**
- Win Rate ≥ 40%
- Profit Factor ≥ 1.3
- Max Drawdown ≤ 10%
- Minimum 20 trades executed

### 5.2 Graduated Capital Deployment

Once paper trading passes:

| Week | Capital | Risk % | Max Daily Loss |
|------|---------|--------|----------------|
| 1-2 | $500 | 0.15% | $3/day |
| 3-4 | $1,000 | 0.20% | $6/day |
| 5-8 | $2,500 | 0.25% | $15/day |
| 9+ | $5,000+ | 0.30% | $30/day |

**NEVER increase capital until previous tier shows profitability for 2+ weeks.**

### 5.3 Monitoring Schedule

| Frequency | Task |
|-----------|------|
| Every 4 hours | Check MT5 connection status |
| Daily (08:00 UTC) | Review journal logs, verify daily reset |
| Weekly (Sunday) | Export CSV, calculate weekly metrics |
| Monthly | Full performance review, adjust parameters if needed |

### 5.4 Emergency Procedures

**If E-Stop triggers:**
1. Do NOT restart EA immediately
2. Review journal logs to identify cause
3. Calculate total drawdown
4. If drawdown > 10%, halt trading for 48 hours
5. Analyze losing trades for pattern recognition
6. Only restart after root cause identified

**If broker disconnects:**
1. EA will continue managing open positions (SL/TP still active)
2. No new entries will be made
3. Reconnect ASAP and check journal for missed events

---

## Appendix A: Troubleshooting Guide

### Common Issues & Solutions

| Issue | Symptom | Solution |
|-------|---------|----------|
| Compilation Error | "undeclared identifier" | Ensure all `#include` statements present |
| Indicator Failure | "handle INVALID" in log | Check symbol/timeframe compatibility |
| Order Rejection | "Trade not allowed" | Enable Auto Trading in MT5 toolbar |
| Magic Conflict | Duplicate magic errors | Change base magic numbers in constants |
| News Filter False Positive | Trading blocked incorrectly | Verify hardcoded news dates are accurate |
| Lot Size Zero | "lots <= 0" error | Increase account balance or reduce risk % |

### Log File Locations

| Log Type | Location |
|----------|----------|
| MT5 Terminal Log | `C:\Users\[User]\AppData\Roaming\MetaQuotes\Terminal\[ID]\Logs\` |
| EA Journal | MT5 Terminal → Toolbox → Journal tab |
| Experts Log | MT5 Terminal → Toolbox → Experts tab |
| CSV Exports | `MQL5\Files\Shadow_Hub_Performance_*.csv` |

---

## Appendix B: Performance Benchmarks

### Expected Metrics (Based on Backtested Data)

| Metric | Target | Acceptable Range |
|--------|--------|------------------|
| Win Rate | 45-55% | 38-60% |
| Profit Factor | 1.5+ | 1.2-2.0 |
| Max Drawdown | < 8% | < 12% |
| Avg RR | 1:2.0 | 1:1.5 to 1:2.5 |
| Trades/Month | 15-25 | 10-40 |
| Sharpe Ratio | 1.5+ | 1.0-2.5 |

### Red Flags (Investigate Immediately)

- Win Rate < 35% over 50+ trades
- Profit Factor < 1.0 over 30+ trades
- Max Drawdown > 15%
- Three consecutive losing days
- Any single day loss > 3%

---

## Appendix C: Update Procedure

To deploy updates to `Shadow_Portfolio_Hub.mq5`:

1. **Backup Current Version:**
   ```
   Copy Shadow_Portfolio_Hub.ex5 to Shadow_Portfolio_Hub.ex5.backup
   ```

2. **Stop EA:**
   - Remove EA from chart or disable Auto Trading

3. **Deploy New Version:**
   - Replace `.mq5` source file
   - Recompile in MetaEditor (F7)

4. **Verify:**
   - Check compilation output
   - Confirm version number updated in Experts log

5. **Restart:**
   - Reattach EA to chart
   - Monitor first 10 ticks for errors

---

*Document Version: 1.0*
*Last Updated: June 2026*
*System Version: Shadow Portfolio Hub v1.00*
