# Shadow Portfolio Hub - Serverless Deployment Blueprint

## Executive Summary

This document provides a complete guide to deploying the **Shadow Portfolio Hub** as a **100% Serverless Signal Generation Engine** on Vercel. The system has been architecturally pivoted from a hybrid VPS/MT5 automated system to a human-in-the-loop model.

**Key Changes:**
- ✅ **Eliminated:** Windows VPS, MQL5 scripts, Python daemons, automated order execution
- ✅ **Implemented:** Serverless signal generation with manual Telegram-to-MT5 execution (60-second window)
- ✅ **Risk Model:** Method A - Fixed Initial Balance (0.30% risk of user-defined static balance in Supabase)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        VERCEL SERVERLESS                         │
│  ┌──────────────────────┐    ┌──────────────────────────────┐  │
│  │   Signal Router      │    │   Telegram Webhook Handler   │  │
│  │   (Cron Triggered)   │    │   (Command Processing)       │  │
│  │                      │    │                              │  │
│  │  1. Fetch OHLCV      │    │  /setbalance [value]         │  │
│  │  2. Kronos Gate      │    │  /status                     │  │
│  │  3. Qwen SMC Audit   │    │  /estop                      │  │
│  │  4. Calculate Lots   │    │  /pause [module]             │  │
│  │  5. Send Alert       │    │  /resume [module]            │  │
│  └──────────┬───────────┘    └──────────────┬───────────────┘  │
│             │                               │                  │
│             └───────────────┬───────────────┘                  │
│                             ▼                                  │
│                    ┌─────────────────┐                         │
│                    │   Supabase DB   │                         │
│                    │   (PostgreSQL)  │                         │
│                    └─────────────────┘                         │
└─────────────────────────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                         TELEGRAM                                 │
│  Signal Alerts → User copies to MT5 mobile app → Manual execute │
└─────────────────────────────────────────────────────────────────┘
```

---

## Phase 1: Prerequisites

### 1.1 Required Accounts

| Service | Purpose | Link |
|---------|---------|------|
| **Vercel** | Serverless hosting | https://vercel.com |
| **Supabase** | PostgreSQL database | https://supabase.com |
| **Telegram** | Bot for alerts & commands | https://telegram.org |
| **Alibaba DashScope** | Qwen LLM API | https://dashscope.aliyun.com |
| **TwelveData** (optional) | Market data feed | https://twelvedata.com |

### 1.2 Environment Variables

Create a `.env` file locally (never commit to Git):

```bash
# Supabase Configuration
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key

# Telegram Bot Configuration
TELEGRAM_BOT_TOKEN=bot_token_from_botfather
TELEGRAM_CHAT_ID=your_telegram_user_id

# Qwen/DashScope Configuration
QWEN_API_KEY=your-dashscope-api-key
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN_MODEL=qwen-plus

# Optional: Market Data (if not using simulated data)
TWELVEDATA_API_KEY=your-twelvedata-key
```

---

## Phase 2: Database Setup

### 2.1 Create Supabase Project

1. Go to https://supabase.com and create a new project
2. Wait for database initialization (~2 minutes)
3. Navigate to **Settings → API** and copy:
   - `Project URL` → `SUPABASE_URL`
   - `service_role secret` → `SUPABASE_SERVICE_ROLE_KEY`

### 2.2 Run Schema Migration

1. Navigate to **SQL Editor** in Supabase dashboard
2. Copy contents of `/workspace/supabase_schema.sql`
3. Paste and run the entire script
4. Verify tables created:
   - `system_state`
   - `audit_logs`
   - `trade_executions`
   - `performance_metrics`
   - `module_pause_states`
   - `system_logs`

### 2.3 Verify Default State

Run this query to confirm default balance is set:

```sql
SELECT * FROM system_state WHERE id = 1;
```

Expected output: `target_initial_balance = 5000.00`

---

## Phase 3: Vercel Deployment

### 3.1 Install Vercel CLI (Optional but Recommended)

```bash
npm install -g vercel
```

### 3.2 Deploy via Git (Recommended)

1. **Push code to GitHub:**
   ```bash
   git add .
   git commit -m "Serverless refactor - Human-in-the-loop architecture"
   git push origin main
   ```

2. **Connect to Vercel:**
   - Go to https://vercel.com/new
   - Import your GitHub repository
   - Configure project settings:
     - **Framework Preset:** Other
     - **Root Directory:** `./`
     - **Python Version:** 3.11

3. **Add Environment Variables:**
   In Vercel dashboard → Settings → Environment Variables, add all variables from Section 1.2

4. **Deploy:**
   Click "Deploy" - Vercel will build and deploy automatically

### 3.3 Deploy via CLI (Alternative)

```bash
cd /workspace
vercel login
vercel --prod
```

---

## Phase 4: Telegram Bot Configuration

### 4.1 Create Telegram Bot

1. Open Telegram and search for `@BotFather`
2. Send `/newbot` command
3. Follow prompts to name your bot
4. Save the bot token (e.g., `123456789:ABCdefGHIjklMNOpqrsTUVwxyz`)

### 4.2 Get Your Chat ID

1. Search for `@userinfobot` on Telegram
2. Start a chat and send any message
3. It will reply with your User ID (e.g., `123456789`)
4. This is your `TELEGRAM_CHAT_ID`

### 4.3 Register Webhook

After deployment, register the webhook:

```bash
curl -X POST "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/setWebhook?url=https://<YOUR_VERCEL_URL>/api/telegram"
```

Verify webhook is set:

```bash
curl "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getWebhookInfo"
```

---

## Phase 5: Cron Job Verification

Vercel cron jobs are configured in `vercel.json`:

| Schedule | Timeframe | Endpoint |
|----------|-----------|----------|
| `*/5 * * * *` | 5-minute | `/api/signal_router?timeframe=5m` |
| `*/15 * * * *` | 15-minute | `/api/signal_router?timeframe=15m` |
| `0 * * * *` | Hourly | `/api/signal_router?timeframe=1h` |

**Note:** Cron jobs only run on **Hobby plan or higher**. Free tier does not support cron.

To verify cron is working:
1. Go to Vercel Dashboard → Your Project → Cron
2. Check last execution timestamps
3. Review logs in **Functions** tab

---

## Phase 6: Testing & Validation

### 6.1 Test Telegram Commands

Send these commands to your bot:

```
/status
```

Expected response:
```
📊 SYSTEM STATUS

💰 Target Balance: $5,000.00
⚠️ Risk Per Trade: $15.00 (0.30%)
🛑 Trading Halted: NO

MODULES:
- NQ: ✅ ACTIVE
- XAUUSD: ✅ ACTIVE
...
```

```
/setbalance 10000
```

Expected response:
```
✅ BALANCE UPDATED

New Target Balance: $10,000.00
Risk Per Trade (0.30%): $30.00
```

```
/pause NQ
```

Expected response:
```
⏸️ Module NQ has been paused.
```

### 6.2 Manual Signal Execution Flow

1. **Signal Alert Received** (Telegram):
   ```
   🟢 NQ 15M LONG
   
   📊 ENTRY: 17850.5
   🛑 SL: 17840.0
   ✅ TP: 17870.0
   
   📐 Lot Size: 0.14
   💰 Risk: $15.00 (0.30%)
   📈 RR: 1:1.95
   
   ⏰ Time: 14:35 UTC
   ⚠️ Manual Execute: Copy to MT5 within 60 seconds!
   ```

2. **User Action** (within 60 seconds):
   - Open MT5 mobile app
   - Select NQ (US100) instrument
   - Set lot size: 0.14
   - Set entry: 17850.5 (or current market price)
   - Set SL: 17840.0
   - Set TP: 17870.0
   - Execute trade

3. **Post-Trade Update** (optional):
   Use Supabase dashboard or future command to log fill results

---

## Phase 7: The 1.5-Week Paper Trading Crucible

### 7.1 Mandatory Validation Period

**DO NOT skip this phase.** All users must complete a **10-day paper trading crucible** before live deployment.

### 7.2 Daily Checklist

| Day | Task | Pass Criteria |
|-----|------|---------------|
| 1-3 | Execute ALL signals on demo account | 100% execution rate |
| 4-6 | Track win rate & drawdown | Win rate ≥ 40%, DD ≤ 5% |
| 7-10 | Refine execution speed | Average execution < 60 seconds |

### 7.3 Metrics to Track

Create a spreadsheet with these columns:

| Date | Asset | Direction | Entry | SL | TP | Lot | Result | PnL | Notes |
|------|-------|-----------|-------|----|----|-----|--------|-----|-------|

### 7.4 Pass Criteria for Live Trading

- ✅ Minimum 20 trades executed
- ✅ Win rate ≥ 40%
- ✅ Profit factor ≥ 1.2
- ✅ Maximum drawdown ≤ 8%
- ✅ No single-day loss > 3%
- ✅ Average execution time < 60 seconds

---

## Appendix A: Troubleshooting

### Common Issues

| Issue | Symptom | Solution |
|-------|---------|----------|
| Webhook not firing | No alerts received | Re-run `setWebhook` curl command |
| Unauthorized errors | Commands rejected | Verify `TELEGRAM_CHAT_ID` matches your user ID |
| Cron not running | No signals generated | Upgrade Vercel plan (cron requires paid tier) |
| Supabase connection failed | 500 errors | Check `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` |
| Zero lot sizes | Signals show 0.01 lots | Increase balance via `/setbalance` |

### Log Locations

- **Vercel Functions:** Dashboard → Functions → Select function → Logs
- **Supabase Logs:** Dashboard → Database → Query Editor → Run diagnostic queries
- **Telegram Errors:** Check bot chat for error messages

---

## Appendix B: Security Best Practices

1. **Never share your `TELEGRAM_BOT_TOKEN` or `SUPABASE_SERVICE_ROLE_KEY`**
2. **Enable 2FA on all accounts** (Vercel, Supabase, Telegram)
3. **Rotate API keys quarterly**
4. **Use environment variables exclusively** - never hardcode secrets
5. **Monitor unauthorized access attempts** in Vercel logs

---

## Appendix C: Cost Breakdown

| Service | Tier | Monthly Cost |
|---------|------|--------------|
| Vercel | Pro (required for cron) | $20/month |
| Supabase | Free tier | $0/month |
| Telegram | Free | $0/month |
| DashScope (Qwen) | Pay-as-you-go | ~$5-15/month |
| TwelveData (optional) | Starter | $0-34/month |

**Total Estimated Monthly Cost:** $25-70/month

---

*Document Version: 2.0 (Serverless Refactor)*  
*Last Updated: $(date +%Y-%m-%d)*  
*System Version: Shadow Portfolio Hub v2.0 - Human-in-the-Loop*
