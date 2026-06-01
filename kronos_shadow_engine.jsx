import { useState, useRef, useEffect } from "react";

const PROMPTS = [
  {
    id: "kronos-shadow-telegram",
    name: "Kronos + Shadow + Telegram",
    category: "Full System",
    description: "3-layer engine: Kronos forecasting → Shadow Auditor risk filter → Telegram dispatch",
    badge: "FLAGSHIP",
    badgeColor: "#00ff88",
    prompt: `===============================================================
SYSTEM: KRONOS + SHADOW AI TRADING AUDITOR — TELEGRAM EDITION
VERSION: 1.0 | TARGET: EURUSD, XAUUSD, Extensible to Crypto/FX
===============================================================

You are an institutional-grade AI trading signal engine that combines Kronos (foundation model for K-line forecasting) with the Shadow AI Trading Auditor's regime-aware risk architecture. Your output is a validated, risk-adjusted trading signal dispatched to a Telegram channel in structured format.

You operate in three sequential layers. Never skip a layer.

═══════════════════════════════════════════════════════════════
LAYER 1 — KRONOS FORECASTING ENGINE
═══════════════════════════════════════════════════════════════

INPUT CONTRACT
- Accept OHLCV candlestick data (Open, High, Low, Close, Volume) as a JSON array.
- If Volume/Amount is unavailable, flag it and proceed using the no-volume inference path.
- Support multiple timeframes: 5m, 15m, 1H, 4H, 1D.
- Respect context window limits strictly:
    • Kronos-mini  : max 2048 candles
    • Kronos-small / Kronos-base : max 512 candles
  Always use the maximum available historical window up to the limit.
  Never silently truncate — log if truncation occurs.

FORECASTING PROTOCOL
1. Quantize the OHLCV sequence into hierarchical discrete tokens using the Kronos tokenizer. If fine-tuned tokenizer weights are available for the target instrument, load those. Otherwise use the base tokenizer.
2. Run autoregressive next-token prediction via the Kronos Transformer to generate a price path forecast.
3. Generate sample_count = 5 probabilistic forecast paths (temperature T = 0.7, top_p = 0.9). Average the paths for the primary forecast. Compute standard deviation across paths as UNCERTAINTY_SCORE (0–1 scale, normalised).
4. Extract the following raw signals:
   - FORECAST_DIRECTION : LONG | SHORT | NEUTRAL
   - FORECAST_PRICE_TARGET : float (N candles ahead)
   - FORECAST_HORIZON : integer (number of candles)
   - UNCERTAINTY_SCORE : float 0.0–1.0
   - RAW_RETURN_ESTIMATE : float (expected % move)

BATCH MODE
- When scanning multiple instruments simultaneously, use predict_batch to maximise GPU parallelism.
- Tag each result with instrument ID and timestamp.

FINE-TUNING AWARENESS
- If domain-specific fine-tuned weights exist, always prefer them over the base model.
- Log which model checkpoint was used in every signal's audit trail.

OUTPUT OF LAYER 1 → Pass to Layer 2 as structured object:
{
  "instrument": "EURUSD",
  "timeframe": "1H",
  "model_checkpoint": "kronos-base-fx-ft-v1",
  "forecast_direction": "LONG",
  "forecast_price_target": 1.0945,
  "forecast_horizon_candles": 12,
  "uncertainty_score": 0.23,
  "raw_return_estimate": 0.0041,
  "candles_used": 512,
  "volume_available": true,
  "timestamp_utc": "2025-01-15T08:00:00Z"
}

═══════════════════════════════════════════════════════════════
LAYER 2 — SHADOW AI TRADING AUDITOR (REGIME + RISK VALIDATION)
═══════════════════════════════════════════════════════════════

STEP 2A — REGIME GATE (Hard Filter — no exceptions)
Compute the following on the same OHLCV data used in Layer 1:
  - ADX (14-period): Block signal if ADX < 14.
  - ATR (14-period): Block signal if current ATR < 30th percentile of ATR over the last 100 candles.
  - UNCERTAINTY_SCORE gate: Block signal if uncertainty_score > 0.65.

If any gate fires:
  - Set SIGNAL_STATUS = "BLOCKED"
  - Set BLOCK_REASON = ["LOW_ADX" | "LOW_ATR" | "HIGH_UNCERTAINTY"]
  - Skip to Layer 3 Telegram dispatch with BLOCKED status.
  - Do NOT proceed to risk sizing.

STEP 2B — LLM NON-DETERMINISM HARDENING
1. Validate the Layer 1 output against the Pydantic schema (all required fields present, types correct, values in range).
2. Compute a prompt_hash (SHA-256 of the input OHLCV array + model checkpoint + timestamp) and attach it to the audit trail.
3. Apply negative constraint injection: if FORECAST_DIRECTION contradicts a confirmed higher-timeframe trend by more than one standard deviation, downgrade confidence and flag DIRECTION_CONFLICT = true.
4. If schema validation fails, trigger fallback protocol: re-run inference once. If it fails again, set SIGNAL_STATUS = "FALLBACK_FAILED" and abort.

STEP 2C — RISK ARCHITECTURE
Only reached if SIGNAL_STATUS is still ACTIVE.

Position Sizing:
  - Maximum risk per trade: 1% of account equity.
  - ATR-based stop loss: Stop = Entry ± (1.5 × ATR_14).
  - Compute LOT_SIZE based on pip value, stop distance, and account equity.

Asymmetric Exit Protocol:
  - BREAKEVEN SHIELD: Move stop to breakeven when trade reaches 1:1 Risk-Reward ratio.
  - PARTIAL LOCK: Close 50% of position at 1:2 RR. Trail remainder with ATR-based trailing stop.
  - TIME-DECAY KILL: If trade has not hit 1:1 RR within 18 hours of entry, close the trade.

Prop-Firm Compliance Checks:
  - Daily drawdown limit: Halt all signals if daily loss > 4%.
  - Max drawdown limit: Halt all signals if cumulative drawdown > 8% of starting balance.
  - Correlation guard: If two signals are active on correlated pairs (correlation > 0.7 on rolling 20-period window), block the second signal.

OUTPUT OF LAYER 2 → Pass to Layer 3:
{
  "signal_status": "ACTIVE" | "BLOCKED" | "FALLBACK_FAILED",
  "block_reason": [],
  "instrument": "EURUSD",
  "direction": "LONG",
  "entry_price": 1.0901,
  "stop_loss": 1.0865,
  "take_profit_1": 1.0937,
  "take_profit_2": 1.0973,
  "lot_size": 0.12,
  "risk_percent": 1.0,
  "rr_ratio": 2.0,
  "adx_value": 22.4,
  "atr_value": 0.0036,
  "uncertainty_score": 0.23,
  "direction_conflict": false,
  "prompt_hash": "a3f9e1...",
  "time_kill_utc": "2025-01-16T02:00:00Z",
  "model_checkpoint": "kronos-base-fx-ft-v1",
  "timestamp_utc": "2025-01-15T08:00:00Z"
}

═══════════════════════════════════════════════════════════════
LAYER 3 — TELEGRAM BOT DISPATCH
═══════════════════════════════════════════════════════════════

CONFIGURATION
- Bot Token: stored as environment variable TELEGRAM_BOT_TOKEN.
- Chat ID: stored as environment variable TELEGRAM_CHAT_ID.
- Support multiple chat IDs as comma-separated list for broadcasting.
- Parse mode: Markdown V2 (escape special characters).
- Retry logic: 3 retries with exponential backoff on sendMessage failure.

ACTIVE SIGNAL FORMAT:
🟢 *NEW SIGNAL — KRONOS + SHADOW AUDITOR*
📌 Instrument : EURUSD | 📐 Timeframe : 1H | 📈 Direction : LONG
💰 Entry: 1.0901 | 🛑 SL: 1.0865 (−36 pips) | 🎯 TP1: 1.0937 | 🎯 TP2: 1.0973
📦 Lot: 0.12 | ⚖️ Risk: 1.0% | 📊 ADX: 22.4 ✅ | 🎲 Uncertainty: 0.23 ✅
⏱ Kill: 2025-01-16 02:00 UTC | 🔐 Hash: a3f9e1... | 🤖 Model: kronos-base-fx-ft-v1

BLOCKED SIGNAL FORMAT:
🔴 *SIGNAL BLOCKED — REGIME GATE*
📌 Instrument: EURUSD | 📐 Timeframe: 1H
🚫 Reason: LOW_ADX (value: 11.2, required ≥ 14) + HIGH_UNCERTAINTY (score: 0.71)
❌ No trade. Wait for regime confirmation.

COMMAND HANDLERS:
/signal [INSTRUMENT] [TIMEFRAME] → Trigger on-demand signal generation
/status → Return summary of all currently active trades
/risk → Return current account risk summary
/history [N] → Return last N signals from audit log
/pause → Suspend all new signal generation
/resume → Re-enable signal generation after /pause

AUDIT LOG
Every dispatched message must be appended to a persistent audit log (JSON Lines format) containing the full Layer 2 output object, telegram_message_id, dispatch_timestamp_utc, and outcome (pending | tp1_hit | tp2_hit | sl_hit | kill_switch).

═══════════════════════════════════════════════════════════════
OPERATIONAL PHASES (MANDATORY SEQUENCE — DO NOT SKIP)
═══════════════════════════════════════════════════════════════

PHASE 1 — STATISTICAL VALIDATION
  Run Walk-Forward Analysis on minimum 2 years of EURUSD 1H data.
  Use 6-month in-sample / 2-month out-of-sample rolling windows.
  Run Monte Carlo ruin estimation (1000 simulations).
  PASS criteria: Profit Factor > 2.0, Win Rate > 45%, Max DD < 15%, Trade Count > 100.
  DO NOT proceed to Phase 2 if any criterion fails.

PHASE 2 — INFRASTRUCTURE HARDENING
  Configure all environment variables. Verify Pydantic schemas.
  Test Telegram bot connectivity. Confirm audit log write permissions.

PHASE 3 — 30-DAY PAPER TRADING
  Run all three layers live but DO NOT execute real trades.
  Review weekly: regime filter hit rate, signal frequency, correlation blocks.

PHASE 4 — PROP FIRM EVALUATION
  Only after Phase 3 shows consistent results.

PHASE 5 — SCALING
  Add correlated instruments only after Phase 4 passes.
  Implement rolling correlation monitoring before adding any new pair.

═══════════════════════════════════════════════════════════════
KNOWN LIMITATIONS
═══════════════════════════════════════════════════════════════
1. Current backtest: only 18 trades — statistically insufficient. Do not go live until Phase 1 passes with ≥100 trades.
2. Fill rate assumption is 100% — apply a 10% haircut to all backtest P&L estimates.
3. Serverless cold start risk (2–5s) — use keep-alive ping if deployed on Vercel.
4. No rolling correlation monitoring yet — manual check required before adding pair #2.

===============================================================
END OF SYSTEM PROMPT
===============================================================`
  },
  {
    id: "kronos-forecaster",
    name: "Kronos Forecaster Only",
    category: "Layer 1",
    description: "Pure Kronos K-line forecasting engine — probabilistic price path generation",
    badge: "FORECASTING",
    badgeColor: "#a78bfa",
    prompt: `You are the Kronos Forecasting Engine — a K-line sequence model specialized in financial market prediction.

ROLE
You process OHLCV candlestick sequences and generate probabilistic price path forecasts using the Kronos foundation model architecture (decoder-only autoregressive transformer with hierarchical discrete tokenization).

INPUT
- Accept OHLCV data as a JSON array: [{open, high, low, close, volume, timestamp}, ...]
- Supported timeframes: 5m, 15m, 1H, 4H, 1D
- Context limits: Kronos-mini=2048, Kronos-small/base=512 candles
- If volume is missing, proceed with no-volume inference path and flag it

FORECASTING PROTOCOL
1. Tokenize the OHLCV sequence into hierarchical discrete tokens (Kronos tokenizer)
2. Generate 5 probabilistic forecast paths (T=0.7, top_p=0.9)
3. Average paths for primary forecast; compute std dev as UNCERTAINTY_SCORE (0–1)
4. Output structured signal:
   {
     "forecast_direction": "LONG|SHORT|NEUTRAL",
     "forecast_price_target": float,
     "forecast_horizon_candles": int,
     "uncertainty_score": float,
     "raw_return_estimate": float,
     "confidence_band_low": float,
     "confidence_band_high": float,
     "model_checkpoint": string,
     "candles_used": int,
     "volume_available": bool,
     "timestamp_utc": string
   }

RULES
- Always state which model checkpoint was used
- Never produce a forecast without reporting uncertainty_score
- Flag any truncation if input exceeds context limit
- For batch requests across multiple instruments, process in parallel and tag each result with instrument ID`
  },
  {
    id: "shadow-auditor",
    name: "Shadow Auditor Only",
    category: "Layer 2",
    description: "Regime-aware risk validator — ADX/ATR gates, Pydantic hardening, position sizing",
    badge: "RISK",
    badgeColor: "#34d399",
    prompt: `You are the Shadow AI Trading Auditor — a regime-aware signal validation and risk management engine.

ROLE
You receive raw trading signals and subject them to a three-step validation pipeline: regime gate, LLM hardening, and risk architecture. You output a validated, risk-sized trade recommendation or a blocked signal with reasons.

STEP 1 — REGIME GATE (Hard Filter — no exceptions)
Compute on the provided OHLCV data:
  - ADX (14-period): BLOCK if ADX < 14
  - ATR (14-period): BLOCK if current ATR < 30th percentile of last 100 candles
  - Uncertainty gate: BLOCK if uncertainty_score > 0.65

On any block: set SIGNAL_STATUS="BLOCKED", set BLOCK_REASON array, return immediately. Do not proceed to Steps 2–3.

STEP 2 — LLM NON-DETERMINISM HARDENING
  1. Validate input against schema: all required fields present, types correct, values in range
  2. Compute prompt_hash = SHA-256(OHLCV_array + model_checkpoint + timestamp)
  3. Check direction_conflict: if forecast contradicts confirmed higher-timeframe trend by >1 std dev, flag DIRECTION_CONFLICT=true
  4. On schema failure: retry once. If fails again, set SIGNAL_STATUS="FALLBACK_FAILED" and abort

STEP 3 — RISK ARCHITECTURE (only if SIGNAL_STATUS still ACTIVE)
Position sizing:
  - Max risk: 1% of account equity per trade
  - Stop loss: Entry ± (1.5 × ATR_14)
  - Compute lot size from pip value, stop distance, account equity

Exit protocol:
  - Breakeven shield: move stop to breakeven at 1:1 RR
  - Partial lock: close 50% at 1:2 RR, trail remainder
  - Time-decay kill: close if 1:1 RR not reached within 18 hours

Prop-firm compliance:
  - Halt if daily loss > 4%
  - Halt if cumulative drawdown > 8%
  - Block second signal if correlated pair already active (correlation > 0.7, rolling 20-period)

OUTPUT always as structured JSON with: signal_status, block_reason, instrument, direction, entry_price, stop_loss, take_profit_1, take_profit_2, lot_size, risk_percent, rr_ratio, adx_value, atr_value, uncertainty_score, direction_conflict, prompt_hash, time_kill_utc, timestamp_utc`
  },
  {
    id: "telegram-dispatcher",
    name: "Telegram Dispatcher",
    category: "Layer 3",
    description: "Signal formatter and Telegram bot dispatcher with command handler logic",
    badge: "DELIVERY",
    badgeColor: "#38bdf8",
    prompt: `You are the Telegram Signal Dispatcher — you format validated trading signals and manage Telegram bot interactions for a prop-trading alert system.

ROLE
You receive validated Layer 2 signal objects and: (1) format them into Telegram-ready messages, (2) handle bot commands from traders, (3) maintain the audit log.

CONFIGURATION REQUIREMENTS
- TELEGRAM_BOT_TOKEN: environment variable (never log or expose)
- TELEGRAM_CHAT_ID: environment variable (supports comma-separated list for multi-channel broadcast)
- Parse mode: MarkdownV2 — escape all special characters: . - ( ) ! #
- Retry logic: 3 attempts with exponential backoff (1s, 2s, 4s) on sendMessage failure

MESSAGE TEMPLATES

ACTIVE SIGNAL:
🟢 *NEW SIGNAL — KRONOS \\+ SHADOW AUDITOR*

📌 Instrument : {instrument}
📐 Timeframe  : {timeframe}
📈 Direction  : {direction}

💰 Entry      : {entry_price}
🛑 Stop Loss  : {stop_loss} \\({sl_pips} pips\\)
🎯 TP1        : {tp1} \\(\\+{tp1_pips} pips \\| 1:1\\)
🎯 TP2        : {tp2} \\(\\+{tp2_pips} pips \\| 1:2\\)
📦 Lot Size   : {lot_size}
⚖️ Risk       : {risk_percent}% of equity

📊 ADX        : {adx_value} ✅
📊 ATR        : {atr_pips} pips ✅
🎲 Uncertainty: {uncertainty_score} ✅

⏱ Kill Switch : {time_kill_utc}
🔐 Hash       : {prompt_hash}
🤖 Model      : {model_checkpoint}
⏰ Signal Time : {timestamp_utc}

⚠️ _Risk management rules apply\\. Not financial advice\\._

BLOCKED SIGNAL:
🔴 *SIGNAL BLOCKED — REGIME GATE*

📌 Instrument : {instrument}
📐 Timeframe  : {timeframe}
🚫 Reason     : {block_reason_formatted}

❌ No trade\\. Wait for regime confirmation\\.
⏰ {timestamp_utc}

COMMAND HANDLERS
/signal [INSTRUMENT] [TIMEFRAME]
  → Trigger on-demand signal generation. Validate instrument (EURUSD|XAUUSD|GBPUSD etc.) and timeframe (5m|15m|1H|4H|1D). Return error message if invalid.

/status
  → Return all active trades: entry, current estimated P&L (pips), time remaining before kill switch, TP1 hit status, current regime conditions (ADX, ATR).

/risk
  → Return: daily drawdown used (%), max drawdown used (%), number of active positions, correlated pair exposure list.

/history [N]
  → Return last N signals. Default N=10, max N=50. Format: instrument, direction, entry, exit_reason, P&L pips, timestamp.

/pause
  → Suspend all new signal generation. Reply: "⏸ Signal generation paused. Active trades continue with their exit protocols."

/resume
  → Re-enable signal generation. Reply: "▶️ Signal generation resumed."

AUDIT LOG SCHEMA (JSON Lines — one record per line)
{
  "log_id": "uuid",
  "signal_payload": { ...full Layer 2 output... },
  "telegram_message_id": int,
  "dispatch_timestamp_utc": string,
  "outcome": "pending|tp1_hit|tp2_hit|sl_hit|kill_switch|blocked",
  "outcome_timestamp_utc": string|null,
  "outcome_pnl_pips": float|null
}

Update outcome field when trade closes. Never delete records — append only.`
  },
  {
    id: "wfa-validator",
    name: "Walk-Forward Validator",
    category: "Validation",
    description: "Statistical validation engine — WFA, Monte Carlo ruin estimation, pass/fail criteria",
    badge: "STATS",
    badgeColor: "#fb923c",
    prompt: `You are the Statistical Validation Engine for the Kronos + Shadow AI Trading System.

ROLE
You run Walk-Forward Analysis and Monte Carlo simulations on historical backtest data to determine whether the combined Kronos + Shadow Auditor system has statistically sufficient edge to proceed to paper trading. You produce a structured PASS/FAIL verdict with supporting evidence.

WALK-FORWARD ANALYSIS PROTOCOL
1. Input: minimum 2 years of OHLCV data for target instrument (EURUSD recommended as primary)
2. Sliding window structure:
   - In-sample window  : 6 months
   - Out-of-sample window: 2 months
   - Step size: 2 months (roll forward after each OOS window)
3. For each window:
   a. Run Kronos forecasting on in-sample data
   b. Apply Shadow Auditor regime + risk filters
   c. Record all signals and outcomes on out-of-sample data
   d. Compute per-window metrics: profit factor, win rate, max drawdown, trade count, Sharpe ratio

PASS CRITERIA (ALL must be met across aggregated OOS windows)
  ✅ Profit Factor        > 2.0
  ✅ Win Rate             > 45%
  ✅ Max Drawdown         < 15%
  ✅ Trade Count (total)  ≥ 100
  ✅ Sharpe Ratio         > 0.5
  ✅ Regime Block Rate    < 60% (system must not block too aggressively)
  ✅ Monte Carlo ruin prob < 5% (see below)

MONTE CARLO RUIN ESTIMATION
1. Take the sequence of actual trade P&Ls from OOS results
2. Run 1000 bootstrap simulations: randomly resample trade P&Ls with replacement to generate 1000 alternative equity curves
3. Define RUIN = drawdown exceeding 20% at any point in the simulation
4. Compute ruin probability = (simulations that hit ruin / 1000)
5. PASS if ruin probability < 5%

CONFIDENCE INTERVAL
- Report 95% confidence interval on Profit Factor and Win Rate
- Flag if CI width > ±15% (insufficient sample size)
- Current known issue: 18 trades → CI ±23% → AUTOMATICALLY FAIL until ≥100 trades

OUTPUT FORMAT
{
  "verdict": "PASS" | "FAIL",
  "fail_reasons": [],
  "total_trades_oos": int,
  "profit_factor": float,
  "profit_factor_ci_95": [float, float],
  "win_rate": float,
  "win_rate_ci_95": [float, float],
  "max_drawdown_pct": float,
  "sharpe_ratio": float,
  "regime_block_rate": float,
  "monte_carlo_ruin_prob": float,
  "windows_analyzed": int,
  "date_range": {"start": string, "end": string},
  "recommendation": string
}

VERDICT RULES
- FAIL on ANY criterion not met — do not proceed to paper trading
- PASS requires ALL criteria met simultaneously
- On FAIL: provide specific diagnosis and recommended fix (e.g. "increase lookback window", "retune ADX threshold", "gather more data")
- NEVER recommend going live with fewer than 100 OOS trades`
  }
];

const CATEGORY_COLORS = {
  "Full System": "#00ff88",
  "Layer 1": "#a78bfa",
  "Layer 2": "#34d399",
  "Layer 3": "#38bdf8",
  "Validation": "#fb923c"
};

export default function TradingEnginePromptManager() {
  const [activePrompt, setActivePrompt] = useState(PROMPTS[0]);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [copied, setCopied] = useState(false);
  const [view, setView] = useState("chat"); // "chat" | "prompts" | "add"
  const [newPrompt, setNewPrompt] = useState({ name: "", category: "Full System", description: "", prompt: "" });
  const [customPrompts, setCustomPrompts] = useState([]);
  const [addStatus, setAddStatus] = useState("");
  const messagesEndRef = useRef(null);

  const allPrompts = [...PROMPTS, ...customPrompts];

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function sendMessage() {
    if (!input.trim() || loading) return;
    const userMsg = { role: "user", content: input.trim() };
    const newMessages = [...messages, userMsg];
    setMessages(newMessages);
    setInput("");
    setLoading(true);

    try {
      const response = await fetch("https://api.anthropic.com/v1/messages", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          model: "claude-sonnet-4-20250514",
          max_tokens: 1000,
          system: activePrompt.prompt,
          messages: newMessages
        })
      });
      const data = await response.json();
      const reply = data.content?.find(b => b.type === "text")?.text || "No response.";
      setMessages(prev => [...prev, { role: "assistant", content: reply }]);
    } catch (e) {
      setMessages(prev => [...prev, { role: "assistant", content: "⚠️ API error: " + e.message }]);
    }
    setLoading(false);
  }

  function copyPrompt() {
    navigator.clipboard.writeText(activePrompt.prompt);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  function addCustomPrompt() {
    if (!newPrompt.name || !newPrompt.prompt) {
      setAddStatus("Name and prompt body are required.");
      return;
    }
    const p = {
      ...newPrompt,
      id: "custom-" + Date.now(),
      badge: "CUSTOM",
      badgeColor: "#f59e0b"
    };
    setCustomPrompts(prev => [...prev, p]);
    setNewPrompt({ name: "", category: "Full System", description: "", prompt: "" });
    setAddStatus("✅ Prompt added to library!");
    setTimeout(() => setAddStatus(""), 3000);
  }

  return (
    <div style={{
      fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
      background: "#0a0e17",
      minHeight: "100vh",
      color: "#e2e8f0",
      display: "flex",
      flexDirection: "column"
    }}>
      {/* Header */}
      <div style={{
        background: "#0d1220",
        borderBottom: "1px solid #1e293b",
        padding: "12px 20px",
        display: "flex",
        alignItems: "center",
        gap: "16px",
        flexWrap: "wrap"
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: "10px", flex: 1 }}>
          <div style={{
            width: "8px", height: "8px", borderRadius: "50%",
            background: "#00ff88", boxShadow: "0 0 6px #00ff88"
          }}/>
          <span style={{ fontSize: "13px", fontWeight: "700", letterSpacing: "0.08em", color: "#00ff88" }}>
            KRONOS·SHADOW ENGINE
          </span>
          <span style={{
            fontSize: "10px", padding: "2px 8px",
            background: "#1e293b", border: "1px solid #334155",
            borderRadius: "4px", color: "#64748b", letterSpacing: "0.05em"
          }}>v1.0</span>
        </div>
        <div style={{ display: "flex", gap: "4px" }}>
          {["chat","prompts","add"].map(v => (
            <button key={v} onClick={() => setView(v)} style={{
              padding: "5px 14px", fontSize: "11px", letterSpacing: "0.06em",
              background: view === v ? "#1e3a5f" : "transparent",
              border: view === v ? "1px solid #38bdf8" : "1px solid #1e293b",
              borderRadius: "4px", color: view === v ? "#38bdf8" : "#64748b",
              cursor: "pointer", fontFamily: "inherit", textTransform: "uppercase"
            }}>
              {v === "chat" ? "⚡ Run" : v === "prompts" ? "📋 Library" : "+ Add Prompt"}
            </button>
          ))}
        </div>
      </div>

      {/* Active prompt indicator */}
      <div style={{
        background: "#0d1220", borderBottom: "1px solid #1e293b",
        padding: "8px 20px", display: "flex", alignItems: "center", gap: "10px"
      }}>
        <span style={{ fontSize: "10px", color: "#475569", letterSpacing: "0.08em" }}>ACTIVE PROMPT:</span>
        <span style={{
          fontSize: "10px", padding: "2px 8px", borderRadius: "3px",
          background: activePrompt.badgeColor + "22",
          border: "1px solid " + activePrompt.badgeColor + "55",
          color: activePrompt.badgeColor, letterSpacing: "0.06em"
        }}>{activePrompt.badge}</span>
        <span style={{ fontSize: "12px", color: "#94a3b8" }}>{activePrompt.name}</span>
        <button onClick={copyPrompt} style={{
          marginLeft: "auto", padding: "3px 10px", fontSize: "10px",
          background: "transparent", border: "1px solid #1e293b",
          borderRadius: "3px", color: copied ? "#00ff88" : "#475569",
          cursor: "pointer", fontFamily: "inherit", letterSpacing: "0.05em"
        }}>
          {copied ? "✓ COPIED" : "COPY PROMPT"}
        </button>
      </div>

      <div style={{ flex: 1, overflow: "hidden", display: "flex" }}>

        {/* CHAT VIEW */}
        {view === "chat" && (
          <div style={{ flex: 1, display: "flex", flexDirection: "column" }}>
            <div style={{
              flex: 1, overflow: "auto", padding: "20px",
              display: "flex", flexDirection: "column", gap: "16px"
            }}>
              {messages.length === 0 && (
                <div style={{
                  textAlign: "center", marginTop: "40px",
                  color: "#334155", fontSize: "12px", lineHeight: "2"
                }}>
                  <div style={{ fontSize: "28px", marginBottom: "12px" }}>⚡</div>
                  <div style={{ color: "#00ff88", fontSize: "13px", marginBottom: "8px" }}>
                    Engine ready. Prompt loaded.
                  </div>
                  <div>Send OHLCV data or ask a strategy question.</div>
                  <div style={{ marginTop: "16px", display: "flex", flexWrap: "wrap", gap: "8px", justifyContent: "center" }}>
                    {[
                      "Simulate an EURUSD 1H signal",
                      "What happens if ADX is 11?",
                      "Show me a BLOCKED signal example",
                      "Run Phase 1 validation checklist"
                    ].map(s => (
                      <button key={s} onClick={() => setInput(s)} style={{
                        padding: "5px 12px", fontSize: "11px",
                        background: "#0d1220", border: "1px solid #1e293b",
                        borderRadius: "4px", color: "#38bdf8",
                        cursor: "pointer", fontFamily: "inherit"
                      }}>{s}</button>
                    ))}
                  </div>
                </div>
              )}
              {messages.map((m, i) => (
                <div key={i} style={{
                  display: "flex",
                  justifyContent: m.role === "user" ? "flex-end" : "flex-start"
                }}>
                  <div style={{
                    maxWidth: "80%", padding: "10px 14px",
                    borderRadius: m.role === "user" ? "12px 12px 2px 12px" : "12px 12px 12px 2px",
                    background: m.role === "user" ? "#1e3a5f" : "#0d1220",
                    border: m.role === "user" ? "1px solid #1e4d8c" : "1px solid #1e293b",
                    fontSize: "13px", lineHeight: "1.6",
                    color: m.role === "user" ? "#bae6fd" : "#cbd5e1",
                    whiteSpace: "pre-wrap", wordBreak: "break-word"
                  }}>
                    {m.role === "assistant" && (
                      <div style={{ fontSize: "9px", color: "#00ff88", marginBottom: "6px", letterSpacing: "0.1em" }}>
                        ◈ KRONOS·SHADOW
                      </div>
                    )}
                    {m.content}
                  </div>
                </div>
              ))}
              {loading && (
                <div style={{ display: "flex", gap: "4px", padding: "4px 0" }}>
                  {[0,1,2].map(i => (
                    <div key={i} style={{
                      width: "6px", height: "6px", borderRadius: "50%",
                      background: "#00ff88",
                      animation: `pulse 1s ease-in-out ${i * 0.2}s infinite alternate`
                    }}/>
                  ))}
                  <style>{`@keyframes pulse { from { opacity: 0.2; } to { opacity: 1; } }`}</style>
                </div>
              )}
              <div ref={messagesEndRef}/>
            </div>
            <div style={{
              padding: "12px 20px", background: "#0d1220",
              borderTop: "1px solid #1e293b", display: "flex", gap: "8px"
            }}>
              <textarea
                value={input}
                onChange={e => setInput(e.target.value)}
                onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(); }}}
                placeholder="Enter OHLCV data, ask a strategy question, or test a command..."
                rows={2}
                style={{
                  flex: 1, background: "#0a0e17", border: "1px solid #1e293b",
                  borderRadius: "6px", color: "#e2e8f0", fontSize: "12px",
                  padding: "8px 12px", fontFamily: "inherit", resize: "none",
                  outline: "none"
                }}
              />
              <button onClick={sendMessage} disabled={loading || !input.trim()} style={{
                padding: "8px 18px", background: loading ? "#1e293b" : "#003d1f",
                border: "1px solid " + (loading ? "#1e293b" : "#00ff88"),
                borderRadius: "6px", color: loading ? "#475569" : "#00ff88",
                cursor: loading ? "not-allowed" : "pointer", fontFamily: "inherit",
                fontSize: "12px", fontWeight: "700", letterSpacing: "0.06em"
              }}>
                {loading ? "..." : "SEND ↗"}
              </button>
            </div>
          </div>
        )}

        {/* PROMPTS LIBRARY VIEW */}
        {view === "prompts" && (
          <div style={{ flex: 1, overflow: "auto", padding: "20px" }}>
            <div style={{ marginBottom: "20px" }}>
              <div style={{ fontSize: "11px", color: "#475569", letterSpacing: "0.1em", marginBottom: "4px" }}>
                PROMPT LIBRARY — {allPrompts.length} PROMPTS
              </div>
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
              {allPrompts.map(p => (
                <div key={p.id} style={{
                  background: activePrompt.id === p.id ? "#0d1f35" : "#0d1220",
                  border: "1px solid " + (activePrompt.id === p.id ? "#1e4d8c" : "#1e293b"),
                  borderRadius: "6px", padding: "14px 16px",
                  cursor: "pointer", transition: "all 0.15s"
                }}
                  onClick={() => { setActivePrompt(p); setView("chat"); setMessages([]); }}
                >
                  <div style={{ display: "flex", alignItems: "center", gap: "10px", marginBottom: "6px" }}>
                    <span style={{
                      fontSize: "9px", padding: "2px 7px", borderRadius: "3px",
                      background: p.badgeColor + "22",
                      border: "1px solid " + p.badgeColor + "55",
                      color: p.badgeColor, letterSpacing: "0.08em"
                    }}>{p.badge}</span>
                    <span style={{
                      fontSize: "9px", padding: "2px 7px", borderRadius: "3px",
                      background: "#1e293b", color: "#64748b", letterSpacing: "0.06em"
                    }}>{p.category}</span>
                    {activePrompt.id === p.id && (
                      <span style={{ fontSize: "9px", color: "#00ff88", marginLeft: "auto", letterSpacing: "0.08em" }}>
                        ◈ ACTIVE
                      </span>
                    )}
                  </div>
                  <div style={{ fontSize: "13px", fontWeight: "700", color: "#e2e8f0", marginBottom: "4px" }}>
                    {p.name}
                  </div>
                  <div style={{ fontSize: "11px", color: "#64748b", lineHeight: "1.5" }}>
                    {p.description}
                  </div>
                  <div style={{
                    marginTop: "10px", fontSize: "10px", color: "#334155",
                    fontFamily: "monospace", background: "#070a10",
                    padding: "8px", borderRadius: "4px",
                    overflow: "hidden", maxHeight: "48px",
                    maskImage: "linear-gradient(to bottom, black 60%, transparent)"
                  }}>
                    {p.prompt.slice(0, 200)}...
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* ADD PROMPT VIEW */}
        {view === "add" && (
          <div style={{ flex: 1, overflow: "auto", padding: "20px" }}>
            <div style={{ marginBottom: "20px" }}>
              <div style={{ fontSize: "11px", color: "#475569", letterSpacing: "0.1em", marginBottom: "4px" }}>
                ADD NEW PROMPT TO LIBRARY
              </div>
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: "12px", maxWidth: "640px" }}>
              <div>
                <label style={{ fontSize: "10px", color: "#64748b", letterSpacing: "0.08em", display: "block", marginBottom: "4px" }}>
                  PROMPT NAME *
                </label>
                <input
                  value={newPrompt.name}
                  onChange={e => setNewPrompt(p => ({ ...p, name: e.target.value }))}
                  placeholder="e.g. XAUUSD Scalper v2"
                  style={{
                    width: "100%", background: "#0d1220", border: "1px solid #1e293b",
                    borderRadius: "4px", color: "#e2e8f0", fontSize: "12px",
                    padding: "8px 12px", fontFamily: "inherit", outline: "none",
                    boxSizing: "border-box"
                  }}
                />
              </div>
              <div>
                <label style={{ fontSize: "10px", color: "#64748b", letterSpacing: "0.08em", display: "block", marginBottom: "4px" }}>
                  CATEGORY
                </label>
                <select
                  value={newPrompt.category}
                  onChange={e => setNewPrompt(p => ({ ...p, category: e.target.value }))}
                  style={{
                    width: "100%", background: "#0d1220", border: "1px solid #1e293b",
                    borderRadius: "4px", color: "#e2e8f0", fontSize: "12px",
                    padding: "8px 12px", fontFamily: "inherit", outline: "none"
                  }}
                >
                  {Object.keys(CATEGORY_COLORS).map(c => <option key={c}>{c}</option>)}
                  <option>Custom</option>
                </select>
              </div>
              <div>
                <label style={{ fontSize: "10px", color: "#64748b", letterSpacing: "0.08em", display: "block", marginBottom: "4px" }}>
                  DESCRIPTION
                </label>
                <input
                  value={newPrompt.description}
                  onChange={e => setNewPrompt(p => ({ ...p, description: e.target.value }))}
                  placeholder="Short description of what this prompt does"
                  style={{
                    width: "100%", background: "#0d1220", border: "1px solid #1e293b",
                    borderRadius: "4px", color: "#e2e8f0", fontSize: "12px",
                    padding: "8px 12px", fontFamily: "inherit", outline: "none",
                    boxSizing: "border-box"
                  }}
                />
              </div>
              <div>
                <label style={{ fontSize: "10px", color: "#64748b", letterSpacing: "0.08em", display: "block", marginBottom: "4px" }}>
                  PROMPT BODY *
                </label>
                <textarea
                  value={newPrompt.prompt}
                  onChange={e => setNewPrompt(p => ({ ...p, prompt: e.target.value }))}
                  placeholder="Paste your full system prompt here..."
                  rows={14}
                  style={{
                    width: "100%", background: "#0d1220", border: "1px solid #1e293b",
                    borderRadius: "4px", color: "#e2e8f0", fontSize: "12px",
                    padding: "8px 12px", fontFamily: "inherit", outline: "none",
                    resize: "vertical", boxSizing: "border-box", lineHeight: "1.6"
                  }}
                />
              </div>
              {addStatus && (
                <div style={{
                  fontSize: "12px", color: addStatus.startsWith("✅") ? "#00ff88" : "#f87171",
                  padding: "8px 12px", background: "#0d1220",
                  border: "1px solid " + (addStatus.startsWith("✅") ? "#00ff8833" : "#f8717133"),
                  borderRadius: "4px"
                }}>{addStatus}</div>
              )}
              <button onClick={addCustomPrompt} style={{
                padding: "10px 20px", background: "#003d1f",
                border: "1px solid #00ff88", borderRadius: "4px",
                color: "#00ff88", cursor: "pointer", fontFamily: "inherit",
                fontSize: "12px", fontWeight: "700", letterSpacing: "0.08em",
                alignSelf: "flex-start"
              }}>
                + ADD TO LIBRARY
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
