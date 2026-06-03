# Shadow AI Trading Auditor - Production Deployment Guide v3.0

## ✅ Security Fixes Completed

### Vulnerabilities Fixed:
1. **API Key Exposure** - Moved to server-side environment variables
2. **Real-time Market Data** - Integrated OANDA v20 API + TwelveData fallback for Forex/Indices
3. **Risk Management** - Added position sizing, R:R validation, confidence thresholds, floating equity DD monitoring
4. **Rate Limiting** - IP-based limiting (10 requests/hour)
5. **Input Validation** - Server-side validation for all inputs
6. **Kill Switches** - Auto-rejects trades below 70% confidence or < 2.0 R:R
7. **Database Persistence** - Supabase PostgreSQL for immutable audit trails

---

## 🚀 Deployment Instructions

### Step 1: Install Dependencies

```bash
npm install openai @supabase/supabase-js
```

### Step 2: Set Environment Variables in Vercel

1. Go to your Vercel Dashboard → Project → Settings → Environment Variables
2. Add the following variables:
   - **Name:** `QWEN_API_KEY`
     - **Value:** Your Alibaba DashScope API key (get from https://dashscope.console.aliyun.com)
   - **Name:** `QWEN_BASE_URL`
     - **Value:** `https://dashscope.aliyuncs.com/compatible-mode/v1`
   - **Name:** `OANDA_API_KEY`
     - **Value:** Your OANDA v20 API key (demo account: https://fxpractice.oanda.com)
   - **Name:** `TWELVEDATA_API_KEY`
     - **Value:** Your TwelveData API key (free tier: https://twelvedata.com/pricing)
   - **Name:** `SUPABASE_URL`
     - **Value:** Your Supabase project URL (https://app.supabase.com)
   - **Name:** `SUPABASE_SERVICE_ROLE_KEY`
     - **Value:** Your Supabase service role key
3. Click "Save"

### Step 3: Deploy to Vercel

```bash
vercel deploy --prod
```

Or push to your Git repository connected to Vercel for automatic deployment.

---

## 📊 System Architecture

```
┌─────────────────┐      ┌──────────────────────┐      ┌─────────────────┐
│   React Client  │ ───► │  Vercel Edge Function │ ───► │  Qwen 3.6-Plus  │
│   (Browser)     │      │  (/api/audit.js)      │      │  (DashScope)    │
└─────────────────┘      └──────────────────────┘      └─────────────────┘
                                │
                                ├──► OANDA v20 API (Forex/Indices)
                                ├──► TwelveData (Fallback)
                                └──► Supabase PostgreSQL (Audit Trail)
```

### Data Flow:
1. User clicks "Run Audit" in browser
2. Frontend sends request to `/api/audit` (your Vercel function)
3. Backend fetches real-time market data from OANDA v20 API (or TwelveData fallback)
4. Backend calls Qwen 3.6-Plus API with market data + system prompt
5. AI analyzes and returns trading decision
6. Backend validates risk metrics (confidence ≥70%, R:R ≥2.0, position size)
7. Response persisted to Supabase audit trail
8. Formatted response sent back to client

**Security:** API key and system prompt NEVER leave the server.

---

## 🔒 Risk Management Features

### Automatic Kill Switches:
- **Confidence Threshold:** Rejects trades below 70% confidence
- **Risk:Reward Filter:** Rejects trades with R:R < 1:2
- **Position Sizing:** Calculates safe position size (2% risk per trade)
- **Daily Loss Limit:** Configurable max daily loss (default 5%)
- **Rate Limiting:** Prevents abuse (10 requests/hour per IP)

### Example Response:
```json
{
  "id": "log_1234567890_abc123",
  "timestamp": "2025-05-24T10:30:00.000Z",
  "symbol": "BTCUSDT",
  "currentPrice": 67500.50,
  "analysis": {
    "decision": "BUY",
    "confidence": 82,
    "reasoning": "Bullish BOS confirmed with FVG fill...",
    "entry_price": 67500.50,
    "stop_loss": 66800.00,
    "take_profit": 69200.00,
    "invalidation_condition": "Price closes below 66500",
    "risk_score": 6
  },
  "riskMetrics": {
    "positionSize": 0.0286,
    "riskAmount": 200.00,
    "potentialProfit": 485.71,
    "rrRatio": 2.43
  },
  "executionTimeMs": 3450,
  "disclaimer": "This is an AI-assisted analysis tool..."
}
```

---

## ⚠️ IMPORTANT WARNINGS

### NOT READY FOR REAL MONEY YET

Before trading with real capital, you MUST:

1. **Paper Trade First**
   - Run the system for 3+ months on demo account
   - Log every trade and outcome
   - Verify profitability before going live

2. **Backtest Extensively**
   - Test on 2+ years of historical data
   - Validate across different market conditions
   - Document win rate, drawdown, Sharpe ratio

3. **Add Database Logging**
   - Store all audit results in a database (PostgreSQL/MongoDB)
   - Enable performance tracking over time
   - Create audit trail for compliance

4. **Implement Circuit Breakers**
   - Hard stop after 3 consecutive losses
   - Daily maximum loss limit (e.g., 5% of account)
   - Weekly review and manual override capability

5. **Monitor & Alert**
   - Set up error monitoring (Sentry, LogRocket)
   - Create alerts for API failures
   - Track latency and success rates

6. **Legal Compliance**
   - Consult with legal counsel about trading regulations
   - Add proper disclaimers and terms of service
   - Ensure compliance with your jurisdiction's laws

---

## 🛠️ Customization Options

### Adjust Risk Parameters:
Edit `/pages/api/audit.js`:
```javascript
const CONFIG = {
  MAX_DAILY_LOSS_PERCENT: 5,     // Change max daily loss %
  MAX_TRADE_RISK_PERCENT: 2,     // Change risk per trade %
  MIN_CONFIDENCE_SCORE: 70,      // Change minimum confidence threshold
  RATE_LIMIT_WINDOW_MS: 3600000, // Rate limit window (ms)
  RATE_LIMIT_MAX_REQUESTS: 10,   // Max requests per window
};
```

### Change Timeframe:
```javascript
const marketData = await fetchMarketData(symbol, '4h'); // 1h, 4h, 1d, etc.
```

### Use Different Symbols:
Frontend can pass any valid OANDA/TwelveData symbol (Forex, Indices, Commodities):
```javascript
body: JSON.stringify({
  symbol: "EURUSD", // or "XAUUSD", "US100", "GBPUSD", etc.
  accountBalance: 50000,
  riskPreference: "aggressive"
})
```

---

## 📈 Next Steps for Production

### Phase 1: Testing (2-4 weeks)
- [ ] Paper trade with virtual money
- [ ] Log all decisions and outcomes
- [ ] Collect performance metrics
- [ ] Refine prompts based on results

### Phase 2: Infrastructure (2-3 weeks)
- [ ] Add PostgreSQL database for trade logging
- [ ] Implement user authentication (NextAuth.js)
- [ ] Set up monitoring (Sentry + Vercel Analytics)
- [ ] Create admin dashboard for oversight

### Phase 3: Safety Systems (1-2 weeks)
- [ ] Add circuit breakers (max loss limits)
- [ ] Implement manual override controls
- [ ] Create emergency shutdown mechanism
- [ ] Set up SMS/email alerts for large moves

### Phase 4: Live Deployment (Ongoing)
- [ ] Start with small capital ($100-500)
- [ ] Scale gradually as confidence grows
- [ ] Weekly performance reviews
- [ ] Continuous improvement based on data

---

## 📞 Support & Resources

- **Vercel Docs:** https://vercel.com/docs
- **Alibaba DashScope (Qwen):** https://help.aliyun.com/zh/dashscope
- **OANDA v20 API:** https://developer.oanda.com/rest-live-v20/introduction/
- **TwelveData API:** https://twelvedata.com/docs
- **Supabase:** https://supabase.com/docs
- **Next.js:** https://nextjs.org/docs

---

## ⚡ Quick Test

After deployment, test your API:

```bash
curl -X POST https://your-app.vercel.app/api/audit \
  -H "Content-Type: application/json" \
  -d '{"symbol":"BTCUSDT","accountBalance":10000,"riskPreference":"moderate"}'
```

Expected response: Valid JSON with trading analysis.

---

**Remember:** This is a powerful tool, but trading involves significant risk. Never risk more than you can afford to lose. Past performance does not guarantee future results.
