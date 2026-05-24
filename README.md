# Shadow AI Trading Auditor

Professional-grade AI-powered trading analysis system built with Next.js, Vercel Edge Functions, and Anthropic's Claude.

## 🎯 Current Rating: 8.5/10

**Status:** Ready for paper trading and research. NOT ready for real money without extensive backtesting.

---

## ✨ Features

- 🔒 **Enterprise Security** - API keys server-side only, zero client exposure
- 📊 **Real-Time Data** - Live market data from Binance (not mocked)
- 🛡️ **Risk Management** - Multiple kill switches, position sizing, R:R validation
- 🤖 **AI Analysis** - Smart Money Concepts analysis powered by Claude 3.5
- ⚡ **Edge Computing** - Deployed on Vercel Edge Functions for low latency
- 📈 **Position Calculator** - Automatic position sizing based on risk %

---

## 🚀 Quick Start

### 1. Install Dependencies
```bash
npm install @anthropic-ai/sdk
```

### 2. Set Environment Variables
In Vercel Dashboard → Settings → Environment Variables:
```
ANTHROPIC_API_KEY=your_anthropic_api_key_here
```

### 3. Deploy
```bash
vercel deploy --prod
```

---

## 📁 Project Structure

```
/workspace
├── pages/
│   └── api/
│       └── audit.js          # Secure backend API (288 lines)
├── shadow_ai_trading_auditor.jsx  # React frontend (323 lines)
├── DEPLOYMENT_GUIDE.md       # Full deployment instructions
├── PRODUCTION_READINESS.md   # Detailed readiness assessment
└── SECURITY_FIXES.md         # Security documentation
```

---

## 🔒 Security Features

✅ API keys stored in environment variables (never in code)  
✅ System prompt hidden server-side (no IP leakage)  
✅ Rate limiting (10 requests/hour per IP)  
✅ Input validation on all endpoints  
✅ CORS protection  
✅ No hardcoded secrets  

---

## 🛡️ Risk Management

| Feature | Setting | Purpose |
|---------|---------|---------|
| Confidence Threshold | 70% min | Filters low-quality setups |
| Risk:Reward Ratio | 1:2 min | Ensures favorable trades |
| Position Sizing | 2% risk | Prevents overexposure |
| Daily Loss Limit | 5% max | Circuit breaker |
| Rate Limiting | 10/hr | Prevents abuse |

---

## 📊 How It Works

1. User triggers audit in React UI
2. Frontend calls `/api/audit` endpoint
3. Backend fetches live data from Binance
4. AI analyzes market structure (SMC framework)
5. Risk checks validate the setup
6. Position size calculated automatically
7. Response returned with entry/SL/TP levels

**Total execution time:** ~3-5 seconds

---

## ⚠️ Important Warnings

### NOT READY FOR REAL MONEY YET

Before trading with real capital:

1. **Paper trade for 3+ months** - Prove the edge works
2. **Backtest extensively** - Test on 2+ years of data
3. **Add database logging** - Track all outcomes
4. **Set up monitoring** - Error tracking & alerts
5. **Consult legal counsel** - Ensure compliance

**This tool is for educational and research purposes only.** Trading involves significant risk of loss.

---

## 📈 Performance Tracking

Create a simple spreadsheet to log:
- Date/Time of each audit
- Symbol analyzed
- AI decision (BUY/SELL/NO_TRADE)
- Suggested entry/SL/TP
- Actual outcome if traded
- Win/Loss result

Track these metrics:
- Win rate (%)
- Average R:R achieved
- Maximum drawdown
- Profit factor

---

## 🛠️ Customization

### Change Risk Parameters
Edit `pages/api/audit.js`:
```javascript
const CONFIG = {
  MAX_TRADE_RISK_PERCENT: 2,    // Change risk per trade
  MIN_CONFIDENCE_SCORE: 70,     // Change confidence threshold
  RATE_LIMIT_MAX_REQUESTS: 10,  // Change rate limit
};
```

### Change Timeframe
```javascript
const marketData = await fetchMarketData(symbol, '4h'); // 1h, 4h, 1d
```

### Add More Symbols
Frontend can use any valid Binance symbol:
```javascript
{ symbol: "ETHUSDT", accountBalance: 10000 }
```

---

## 📚 Documentation

- **[DEPLOYMENT_GUIDE.md](./DEPLOYMENT_GUIDE.md)** - Complete deployment instructions
- **[PRODUCTION_READINESS.md](./PRODUCTION_READINESS.md)** - Detailed readiness report
- **[SECURITY_FIXES.md](./SECURITY_FIXES.md)** - Security architecture details

---

## 🔗 Resources

- [Vercel Documentation](https://vercel.com/docs)
- [Anthropic API Docs](https://docs.anthropic.com)
- [Binance API Docs](https://binance-docs.github.io/apidocs/)
- [Next.js Documentation](https://nextjs.org/docs)

---

## 📝 License

MIT License - For educational purposes only. Not financial advice.

---

## ⚡ Quick Test

After deployment:
```bash
curl -X POST https://your-app.vercel.app/api/audit \
  -H "Content-Type: application/json" \
  -d '{"symbol":"BTCUSDT","accountBalance":10000}'
```

---

**Built with ❤️ for traders who value risk management**

*Remember: Past performance does not guarantee future results. Never risk more than you can afford to lose.*
