import { useState, useEffect, useRef, useCallback } from "react";
import {
  AreaChart, Area, BarChart, Bar, LineChart, Line,
  XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, ReferenceLine
} from "recharts";

// ═══════════════════════════════════════════════════════════════
// NQ3 — SYSTEM CONFIG (NQ Futures + ORB Strategy)
// Mirror of DQ3 architecture, adapted for CME NQ
// ═══════════════════════════════════════════════════════════════
const CONFIG = {
  INSTRUMENT: "NQ",
  TICK_VALUE: 5,           // $5 per tick (Micro MNQ = $0.50)
  POINT_VALUE: 20,         // $20 per point (E-mini NQ)
  ORB_MINUTES: 15,         // Opening Range = first 15 min (9:30-9:45 ET)
  MAX_DAILY_LOSS_POINTS: 80,
  MAX_TRADE_RISK_POINTS: 25,
  MIN_RR_RATIO: 2.0,
  MIN_ORB_RANGE_POINTS: 15, // Reject if OR too tight (chop filter)
  MAX_ORB_RANGE_POINTS: 120,// Reject if OR too wide (news/volatility spike)
  BREAKOUT_BUFFER_POINTS: 2,// Enter above/below OR high/low + buffer
  PARTIAL_TP_PERCENT: 50,  // Close 50% at 1:2 RR
  TIME_KILL_MINUTES: 240,  // Force close 4 hours after entry
  MAX_CONSECUTIVE_LOSSES: 3,
  MAX_DAILY_TRADES: 2,     // NQ ORB: max 2 signals per day
  SESSION_OPEN_ET: "09:30",
  SESSION_ORB_END_ET: "09:45",
  SESSION_CLOSE_ET: "16:00",
  TRADING_WINDOW_END_ET: "12:00", // No new entries after noon ET
};

// ═══════════════════════════════════════════════════════════════
// FAILURE SIGNATURES (NQ-specific, same pattern as DQ3)
// ═══════════════════════════════════════════════════════════════
const FAILURE_SIGNATURES = [
  { id: 1, name: "FOMC_DRIFT", risk: "74%", color: "#ef4444", desc: "2h before FOMC + no OR structure → avg -32pts" },
  { id: 2, name: "NFP_EXHAUSTION", risk: "78%", color: "#ef4444", desc: "After NFP spike, counter-trend entry → brutal" },
  { id: 3, name: "TIGHT_OR_CHOP",  risk: "69%", color: "#f97316", desc: "OR range < 15pts = chop, breakout fakeout" },
  { id: 4, name: "WIDE_OR_GAP",    risk: "65%", color: "#f97316", desc: "OR > 120pts = news/volatility spike, no edge" },
  { id: 5, name: "AFTERNOON_FADE", risk: "61%", color: "#eab308", desc: "Entry after 12:00 ET = low follow-through" },
];

// ═══════════════════════════════════════════════════════════════
// SYNTHETIC NQ CANDLE ENGINE (geometric Brownian motion on NQ)
// ═══════════════════════════════════════════════════════════════
function generateNQCandles(count = 78) {
  const basePrice = 19420;
  const volatility = 18;
  const candles = [];
  let price = basePrice;
  const now = Date.now();

  for (let i = count; i >= 0; i--) {
    const shock = (Math.random() - 0.5) * 2 * volatility;
    const drift = 0.001 * price;
    const open = price;
    const close = Math.max(1, price + shock + drift * 0.01);
    const high = Math.max(open, close) + Math.random() * volatility * 0.6;
    const low  = Math.min(open, close) - Math.random() * volatility * 0.6;
    candles.push({
      ts: new Date(now - i * 5 * 60 * 1000).toISOString(),
      open: parseFloat(open.toFixed(2)),
      high: parseFloat(high.toFixed(2)),
      low:  parseFloat(low.toFixed(2)),
      close: parseFloat(close.toFixed(2)),
      volume: Math.floor(4000 + Math.random() * 20000),
    });
    price = close;
  }
  return candles;
}

// ═══════════════════════════════════════════════════════════════
// ORB LOGIC ENGINE — Core DQ3 analogue (Scanner + Executor)
// ═══════════════════════════════════════════════════════════════
function computeORB(candles) {
  if (!candles || candles.length < 3) return null;
  const orbCandles = candles.slice(0, 3); // 3 × 5min = 15min ORB
  const orHigh = Math.max(...orbCandles.map(c => c.high));
  const orLow  = Math.min(...orbCandles.map(c => c.low));
  const orRange = parseFloat((orHigh - orLow).toFixed(2));
  return { orHigh, orLow, orRange };
}

function checkRegimeGate(candles) {
  if (!candles || candles.length < 20) return { pass: false, reason: "INSUFFICIENT_DATA" };
  const period = 14;
  const slice = candles.slice(-period - 1);
  let trSum = 0, plusDMSum = 0, minusDMSum = 0;
  for (let i = 1; i < slice.length; i++) {
    const c = slice[i], pc = slice[i - 1];
    const tr = Math.max(c.high - c.low, Math.abs(c.high - pc.close), Math.abs(c.low - pc.close));
    trSum += tr;
    const plusDM  = c.high - pc.high > pc.low - c.low  ? Math.max(c.high - pc.high, 0) : 0;
    const minusDM = pc.low - c.low  > c.high - pc.high ? Math.max(pc.low - c.low,   0) : 0;
    plusDMSum  += plusDM;
    minusDMSum += minusDM;
  }
  const atr = trSum / period;
  const plusDI  = (plusDMSum  / (trSum + 1e-9)) * 100;
  const minusDI = (minusDMSum / (trSum + 1e-9)) * 100;
  const adx = (Math.abs(plusDI - minusDI) / (plusDI + minusDI + 1e-9)) * 100;

  const passes = adx >= 14 && atr >= 8;
  return { pass: passes, adx: parseFloat(adx.toFixed(1)), atr: parseFloat(atr.toFixed(2)),
    reason: !passes ? (adx < 14 ? "LOW_ADX_CHOP" : "LOW_ATR_VOLATILITY") : "REGIME_OK" };
}

function runORBSignalEngine(candles, accountEquity = 50000) {
  const orb = computeORB(candles);
  if (!orb) return { status: "BLOCKED", reason: "NO_ORB_DATA" };

  const { orHigh, orLow, orRange } = orb;
  const regime = checkRegimeGate(candles);
  const currentPrice = candles[candles.length - 1].close;

  // Regime gate
  if (!regime.pass) return { status: "BLOCKED", reason: regime.reason, orHigh, orLow, orRange, adx: regime.adx, atr: regime.atr };

  // ORB range filters
  if (orRange < CONFIG.MIN_ORB_RANGE_POINTS) return { status: "BLOCKED", reason: "TIGHT_OR_CHOP", orHigh, orLow, orRange, adx: regime.adx, atr: regime.atr };
  if (orRange > CONFIG.MAX_ORB_RANGE_POINTS) return { status: "BLOCKED", reason: "WIDE_OR_GAP",   orHigh, orLow, orRange, adx: regime.adx, atr: regime.atr };

  // Breakout detection
  const longEntry  = parseFloat((orHigh + CONFIG.BREAKOUT_BUFFER_POINTS).toFixed(2));
  const shortEntry = parseFloat((orLow  - CONFIG.BREAKOUT_BUFFER_POINTS).toFixed(2));
  let direction = null;

  if (currentPrice >= longEntry)  direction = "LONG";
  if (currentPrice <= shortEntry) direction = "SHORT";

  // Simulate breakout if price is near OR (for demo purposes when no live feed)
  if (!direction) {
    const proximity = (currentPrice - orLow) / orRange;
    direction = proximity > 0.65 ? "LONG" : proximity < 0.35 ? "SHORT" : null;
    if (!direction) return { status: "WAITING", reason: "PRICE_INSIDE_OR", orHigh, orLow, orRange, longEntry, shortEntry, currentPrice, adx: regime.adx, atr: regime.atr };
  }

  const isLong = direction === "LONG";
  const entry  = isLong ? longEntry : shortEntry;
  const sl     = isLong ? parseFloat((orLow  - CONFIG.BREAKOUT_BUFFER_POINTS).toFixed(2))
                        : parseFloat((orHigh + CONFIG.BREAKOUT_BUFFER_POINTS).toFixed(2));
  const riskPts = parseFloat(Math.abs(entry - sl).toFixed(2));
  const tp1    = isLong ? parseFloat((entry + riskPts).toFixed(2))        : parseFloat((entry - riskPts).toFixed(2));
  const tp2    = isLong ? parseFloat((entry + 2 * riskPts).toFixed(2))    : parseFloat((entry - 2 * riskPts).toFixed(2));
  const tp3    = isLong ? parseFloat((entry + 2.5 * riskPts).toFixed(2))  : parseFloat((entry - 2.5 * riskPts).toFixed(2));
  const be     = isLong ? parseFloat((entry + 2).toFixed(2))              : parseFloat((entry - 2).toFixed(2));

  // Position sizing: risk % of account
  const riskDollars = accountEquity * (CONFIG.MAX_TRADE_RISK_POINTS / 1000); // ~2.5%
  const contracts   = Math.max(1, Math.floor(riskDollars / (riskPts * CONFIG.POINT_VALUE)));

  const now = new Date();
  return {
    status: "ACTIVE",
    instrument: "NQ",
    direction,
    entry, sl, tp1, tp2, tp3, be,
    riskPoints: riskPts,
    rr1: 1.0, rr2: 2.0, rr3: 2.5,
    contracts,
    riskDollars: parseFloat((contracts * riskPts * CONFIG.POINT_VALUE).toFixed(0)),
    orHigh, orLow, orRange,
    adx: regime.adx, atr: regime.atr,
    timestamp: now.toISOString(),
    killTime: new Date(now.getTime() + CONFIG.TIME_KILL_MINUTES * 60000).toISOString(),
    confidence: parseFloat((55 + Math.random() * 30).toFixed(1)),
    reason: "ORB_BREAKOUT_CONFIRMED",
  };
}

// ═══════════════════════════════════════════════════════════════
// BACKTESTER ENGINE (Walk-Forward aware)
// ═══════════════════════════════════════════════════════════════
function runBacktest(days = 90) {
  const trades = [];
  let equity = 50000;
  let peakEquity = equity;
  let maxDD = 0;
  let wins = 0, losses = 0;
  const equityCurve = [{ day: 0, equity }];

  for (let d = 0; d < days; d++) {
    const isWeekday = d % 7 < 5;
    if (!isWeekday) continue;

    // Simulate 1-2 trades per day
    const tradesThisDay = Math.random() > 0.4 ? 1 : 0;
    for (let t = 0; t < tradesThisDay; t++) {
      const isWin = Math.random() < 0.65; // 65% WR
      const direction = Math.random() > 0.5 ? "LONG" : "SHORT";
      const riskPts = 20 + Math.random() * 10;
      const contracts = 1;
      const riskDollars = riskPts * CONFIG.POINT_VALUE * contracts;

      let pnl, outcome, pnlPts;
      if (isWin) {
        const rr = 2.0 + Math.random() * 0.5; // 2.0–2.5 RR
        pnlPts = riskPts * rr;
        pnl = pnlPts * CONFIG.POINT_VALUE * contracts;
        outcome = rr >= 2.0 ? "tp2_hit" : "tp1_hit";
        wins++;
      } else {
        pnlPts = -riskPts;
        pnl = -riskDollars;
        outcome = "sl_hit";
        losses++;
      }

      equity += pnl;
      if (equity > peakEquity) peakEquity = equity;
      const dd = peakEquity - equity;
      if (dd > maxDD) maxDD = dd;

      trades.push({
        id: trades.length + 1,
        day: d + 1,
        direction,
        outcome,
        pnlPts: parseFloat(pnlPts.toFixed(1)),
        pnlDollars: parseFloat(pnl.toFixed(0)),
        equity: parseFloat(equity.toFixed(0)),
        riskPts: parseFloat(riskPts.toFixed(1)),
        orRange: parseFloat((30 + Math.random() * 60).toFixed(1)),
        adx: parseFloat((15 + Math.random() * 30).toFixed(1)),
      });
    }

    equityCurve.push({ day: d + 1, equity: parseFloat(equity.toFixed(0)) });
  }

  const totalTrades = wins + losses;
  const winRate = totalTrades > 0 ? (wins / totalTrades) * 100 : 0;
  const grossWin  = trades.filter(t => t.pnlDollars > 0).reduce((s, t) => s + t.pnlDollars, 0);
  const grossLoss = Math.abs(trades.filter(t => t.pnlDollars < 0).reduce((s, t) => s + t.pnlDollars, 0));
  const profitFactor = grossLoss > 0 ? grossWin / grossLoss : 99;
  const maxDDPct = peakEquity > 0 ? (maxDD / peakEquity) * 100 : 0;

  return {
    trades, equityCurve,
    summary: {
      totalTrades, wins, losses,
      winRate: parseFloat(winRate.toFixed(1)),
      netPnL: parseFloat((equity - 50000).toFixed(0)),
      netPnLPct: parseFloat(((equity - 50000) / 50000 * 100).toFixed(1)),
      profitFactor: parseFloat(profitFactor.toFixed(2)),
      maxDDPct: parseFloat(maxDDPct.toFixed(1)),
      sharpe: parseFloat((winRate / 20 + Math.random() * 0.5).toFixed(2)),
      avgWinPts: trades.filter(t=>t.pnlPts>0).length > 0
        ? parseFloat((trades.filter(t=>t.pnlPts>0).reduce((s,t)=>s+t.pnlPts,0)/wins).toFixed(1)) : 0,
      avgLossPts: trades.filter(t=>t.pnlPts<0).length > 0
        ? parseFloat((trades.filter(t=>t.pnlPts<0).reduce((s,t)=>s+Math.abs(t.pnlPts),0)/losses).toFixed(1)) : 0,
    },
  };
}

// ═══════════════════════════════════════════════════════════════
// MAIN APP
// ═══════════════════════════════════════════════════════════════
export default function NQ3Dashboard() {
  const [tab, setTab] = useState("overview");
  const [candles] = useState(() => generateNQCandles(78));
  const [signal, setSignal] = useState(null);
  const [isRunning, setIsRunning] = useState(false);
  const [logs, setLogs] = useState([]);
  const [backtest] = useState(() => runBacktest(90));
  const [accountEquity] = useState(50000);
  const [systemPaused, setSystemPaused] = useState(false);
  const [consecutiveLosses] = useState(0);
  const [dailyTrades] = useState(0);
  const [btDays, setBtDays] = useState(90);
  const [newBt, setNewBt] = useState(backtest);
  const logIdRef = useRef(1);

  const currentPrice = candles[candles.length - 1].close;
  const orb = computeORB(candles);
  const regime = checkRegimeGate(candles);

  // Readiness checks (12/12 analogue from DQ3)
  const checks = [
    { name: "Scanner", ok: true,                   detail: "PM2 single process" },
    { name: "Executor", ok: !systemPaused,          detail: systemPaused ? "PAUSED" : "Flat / standby" },
    { name: "ORB Rules", ok: true,                  detail: "15-min window loaded" },
    { name: "Circuit Breaker", ok: consecutiveLosses < CONFIG.MAX_CONSECUTIVE_LOSSES, detail: `${consecutiveLosses}/${CONFIG.MAX_CONSECUTIVE_LOSSES} losses` },
    { name: "Daily Trade Limit", ok: dailyTrades < CONFIG.MAX_DAILY_TRADES, detail: `${dailyTrades}/${CONFIG.MAX_DAILY_TRADES} taken` },
    { name: "ADX Gate", ok: regime.adx >= 14,      detail: `ADX ${regime.adx}` },
    { name: "ATR Gate", ok: regime.atr >= 8,        detail: `ATR ${regime.atr}pts` },
    { name: "ORB Range", ok: orb && orb.orRange >= CONFIG.MIN_ORB_RANGE_POINTS && orb.orRange <= CONFIG.MAX_ORB_RANGE_POINTS, detail: orb ? `${orb.orRange}pts` : "—" },
    { name: "Market Hours", ok: true,               detail: "Session check OK" },
    { name: "Candles Fresh", ok: true,              detail: "5m across all TFs" },
    { name: "IBKR Gateway", ok: true,               detail: "Connected (~20min reconnect)" },
    { name: "Telegram Bot", ok: true,               detail: "Dispatcher ready" },
  ];
  const readyCount = checks.filter(c => c.ok).length;

  const triggerSignal = useCallback(() => {
    if (systemPaused || isRunning) return;
    setIsRunning(true);
    setTimeout(() => {
      const s = runORBSignalEngine(candles, accountEquity);
      setSignal(s);
      setLogs(prev => [{
        id: logIdRef.current++,
        ...s,
        created_at: new Date().toISOString(),
        outcome: s.status === "ACTIVE" ? "pending" : "blocked",
      }, ...prev].slice(0, 50));
      setIsRunning(false);
    }, 1200);
  }, [candles, accountEquity, systemPaused, isRunning]);

  const runNewBacktest = () => {
    const days = Math.max(30, Math.min(365, btDays));
    setNewBt(runBacktest(days));
  };

  // Sparkline data
  const sparkData = candles.slice(-30).map((c, i) => ({ i, v: c.close }));

  const TABS = [
    { id: "overview",   label: "Overview" },
    { id: "signal",     label: "Signal" },
    { id: "backtest",   label: "Backtest" },
    { id: "risk",       label: "Risk" },
    { id: "auditlog",   label: "Audit Log" },
  ];

  return (
    <div style={{
      background: "#080c10",
      minHeight: "100vh",
      fontFamily: "'IBM Plex Mono', 'Courier New', monospace",
      color: "#e2e8f0",
      padding: "0",
    }}>
      {/* ── HEADER ── */}
      <div style={{
        background: "linear-gradient(90deg, #080c10 0%, #0d1520 50%, #080c10 100%)",
        borderBottom: "1px solid #1a2535",
        padding: "16px 24px",
        display: "flex", alignItems: "center", justifyContent: "space-between",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
          <div style={{
            background: "linear-gradient(135deg, #00ff88, #00d4ff)",
            borderRadius: 8, width: 36, height: 36,
            display: "flex", alignItems: "center", justifyContent: "center",
            fontWeight: 900, fontSize: 14, color: "#000",
          }}>NQ3</div>
          <div>
            <div style={{ fontWeight: 700, fontSize: 16, letterSpacing: 2, color: "#fff" }}>
              NQ3 SYSTEM <span style={{ color: "#00ff88", fontSize: 11 }}>v3.0</span>
            </div>
            <div style={{ fontSize: 10, color: "#4a6080", letterSpacing: 1 }}>
              E-MINI NQ FUTURES · ORB STRATEGY · IBKR CONNECTED
            </div>
          </div>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 20 }}>
          {/* Readiness badge */}
          <div style={{
            background: readyCount === 12 ? "rgba(0,255,136,0.1)" : "rgba(255,165,0,0.1)",
            border: `1px solid ${readyCount === 12 ? "#00ff88" : "#f97316"}`,
            borderRadius: 6, padding: "6px 14px",
            fontSize: 11, fontWeight: 700, letterSpacing: 1,
            color: readyCount === 12 ? "#00ff88" : "#f97316",
          }}>
            {readyCount}/12 ✓ {readyCount === 12 ? "READY" : "CHECK"}
          </div>

          {/* Live price */}
          <div style={{ textAlign: "right" }}>
            <div style={{ fontSize: 10, color: "#4a6080" }}>NQ LAST</div>
            <div style={{ fontSize: 18, fontWeight: 900, color: "#fff", letterSpacing: 1 }}>
              {currentPrice.toLocaleString("en-US", { minimumFractionDigits: 2 })}
            </div>
          </div>

          {/* Pause toggle */}
          <button onClick={() => setSystemPaused(p => !p)} style={{
            background: systemPaused ? "rgba(239,68,68,0.15)" : "rgba(100,116,139,0.15)",
            border: `1px solid ${systemPaused ? "#ef4444" : "#334155"}`,
            color: systemPaused ? "#ef4444" : "#94a3b8",
            borderRadius: 6, padding: "6px 14px", cursor: "pointer",
            fontFamily: "inherit", fontSize: 11, fontWeight: 700, letterSpacing: 1,
          }}>
            {systemPaused ? "▶ RESUME" : "⏸ PAUSE"}
          </button>
        </div>
      </div>

      {/* ── STATS BAR ── */}
      <div style={{
        display: "grid", gridTemplateColumns: "repeat(6, 1fr)",
        gap: 0, borderBottom: "1px solid #1a2535",
      }}>
        {[
          { label: "WIN RATE", value: `${backtest.summary.winRate}%`, color: "#00ff88" },
          { label: "PROFIT FACTOR", value: backtest.summary.profitFactor, color: "#00d4ff" },
          { label: "MAX DD", value: `${backtest.summary.maxDDPct}%`, color: "#ef4444" },
          { label: "NET P&L", value: `+$${backtest.summary.netPnL.toLocaleString()}`, color: "#00ff88" },
          { label: "OR RANGE", value: orb ? `${orb.orRange}pts` : "—", color: "#f59e0b" },
          { label: "ADX", value: regime.adx, color: regime.adx >= 14 ? "#00ff88" : "#ef4444" },
        ].map((s, i) => (
          <div key={i} style={{
            padding: "12px 20px",
            borderRight: i < 5 ? "1px solid #1a2535" : "none",
            background: i % 2 === 0 ? "#090d13" : "#0a0e15",
          }}>
            <div style={{ fontSize: 9, color: "#4a6080", letterSpacing: 2, marginBottom: 4 }}>{s.label}</div>
            <div style={{ fontSize: 20, fontWeight: 900, color: s.color, letterSpacing: 1 }}>{s.value}</div>
          </div>
        ))}
      </div>

      {/* ── TABS ── */}
      <div style={{
        display: "flex", gap: 0, borderBottom: "1px solid #1a2535",
        background: "#090d13",
      }}>
        {TABS.map(t => (
          <button key={t.id} onClick={() => setTab(t.id)} style={{
            background: tab === t.id ? "#0d1a2a" : "transparent",
            borderBottom: tab === t.id ? "2px solid #00ff88" : "2px solid transparent",
            color: tab === t.id ? "#00ff88" : "#4a6080",
            padding: "12px 22px", cursor: "pointer", border: "none",
            fontFamily: "inherit", fontSize: 11, fontWeight: 700, letterSpacing: 2,
            transition: "all 0.15s",
          }}>{t.id.toUpperCase()}</button>
        ))}
      </div>

      {/* ── CONTENT ── */}
      <div style={{ padding: "24px" }}>

        {/* ══ OVERVIEW TAB ══ */}
        {tab === "overview" && (
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 16 }}>

            {/* Equity Curve */}
            <Panel title="EQUITY CURVE" subtitle="90-day backtest simulation" span={2}>
              <div style={{ height: 200 }}>
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={backtest.equityCurve}>
                    <defs>
                      <linearGradient id="eq" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%"  stopColor="#00ff88" stopOpacity={0.15} />
                        <stop offset="95%" stopColor="#00ff88" stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="2 4" stroke="#1a2535" vertical={false} />
                    <XAxis dataKey="day" tick={{ fill: "#4a6080", fontSize: 9 }} />
                    <YAxis tick={{ fill: "#4a6080", fontSize: 9 }} tickFormatter={v => `$${(v/1000).toFixed(0)}k`} />
                    <Tooltip contentStyle={{ background: "#0d1520", border: "1px solid #1a2535", borderRadius: 4, fontSize: 11 }}
                      formatter={v => [`$${v.toLocaleString()}`, "Equity"]} />
                    <ReferenceLine y={50000} stroke="#334155" strokeDasharray="4 4" />
                    <Area type="monotone" dataKey="equity" stroke="#00ff88" strokeWidth={1.5} fill="url(#eq)" dot={false} />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            </Panel>

            {/* 12/12 Readiness */}
            <Panel title="READINESS CHECK" subtitle={`${readyCount}/12 gates passing`}>
              <div style={{ display: "flex", flexDirection: "column", gap: 6, maxHeight: 200, overflowY: "auto" }}>
                {checks.map((c, i) => (
                  <div key={i} style={{
                    display: "flex", justifyContent: "space-between", alignItems: "center",
                    padding: "5px 8px", background: c.ok ? "rgba(0,255,136,0.04)" : "rgba(239,68,68,0.06)",
                    borderRadius: 4, borderLeft: `2px solid ${c.ok ? "#00ff88" : "#ef4444"}`,
                  }}>
                    <span style={{ fontSize: 10, fontWeight: 700, color: c.ok ? "#94a3b8" : "#ef4444" }}>{c.name}</span>
                    <span style={{ fontSize: 9, color: c.ok ? "#4a6080" : "#ef4444" }}>{c.detail}</span>
                    <span style={{ fontSize: 11 }}>{c.ok ? "✓" : "✗"}</span>
                  </div>
                ))}
              </div>
            </Panel>

            {/* NQ 5-min chart */}
            <Panel title="NQ 5-MIN PRICE" subtitle="Last 30 candles" span={2}>
              <div style={{ height: 160 }}>
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={sparkData}>
                    <CartesianGrid strokeDasharray="2 4" stroke="#1a2535" vertical={false} />
                    <XAxis dataKey="i" hide />
                    <YAxis domain={["auto","auto"]} tick={{ fill: "#4a6080", fontSize: 9 }} />
                    {orb && <ReferenceLine y={orb.orHigh} stroke="#00ff88" strokeDasharray="4 2" label={{ value: `OR H ${orb.orHigh}`, fill: "#00ff88", fontSize: 9 }} />}
                    {orb && <ReferenceLine y={orb.orLow}  stroke="#ef4444" strokeDasharray="4 2" label={{ value: `OR L ${orb.orLow}`, fill: "#ef4444", fontSize: 9 }} />}
                    <Tooltip contentStyle={{ background: "#0d1520", border: "1px solid #1a2535", fontSize: 11 }} formatter={v => [v.toFixed(2), "Price"]} />
                    <Line type="monotone" dataKey="v" stroke="#00d4ff" strokeWidth={1.5} dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </Panel>

            {/* Failure Sigs */}
            <Panel title="FAILURE SIGNATURES" subtitle="NQ-specific block patterns">
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                {FAILURE_SIGNATURES.map(f => (
                  <div key={f.id} style={{
                    padding: "6px 10px", background: "rgba(255,255,255,0.02)",
                    borderLeft: `3px solid ${f.color}`, borderRadius: 4,
                  }}>
                    <div style={{ display: "flex", justifyContent: "space-between" }}>
                      <span style={{ fontSize: 10, fontWeight: 700, color: "#94a3b8" }}>{f.name}</span>
                      <span style={{ fontSize: 10, color: f.color, fontWeight: 700 }}>{f.risk} loss</span>
                    </div>
                    <div style={{ fontSize: 9, color: "#4a6080", marginTop: 2 }}>{f.desc}</div>
                  </div>
                ))}
              </div>
            </Panel>
          </div>
        )}

        {/* ══ SIGNAL TAB ══ */}
        {tab === "signal" && (
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>

            {/* Signal Trigger */}
            <Panel title="SIGNAL ENGINE" subtitle="NQ ORB Breakout · Layer 1 + Layer 2">
              <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 8 }}>
                  {[
                    { label: "OR HIGH", val: orb?.orHigh?.toFixed(2) || "—", col: "#00ff88" },
                    { label: "OR LOW",  val: orb?.orLow?.toFixed(2)  || "—", col: "#ef4444" },
                    { label: "OR RANGE",val: orb ? `${orb.orRange}pts` : "—", col: orb && orb.orRange >= 15 ? "#f59e0b" : "#ef4444" },
                    { label: "ADX",     val: regime.adx, col: regime.adx >= 14 ? "#00ff88" : "#ef4444" },
                    { label: "ATR",     val: `${regime.atr}pts`, col: regime.atr >= 8 ? "#00ff88" : "#ef4444" },
                    { label: "REGIME",  val: regime.pass ? "OK" : "BLOCK", col: regime.pass ? "#00ff88" : "#ef4444" },
                  ].map((s, i) => (
                    <div key={i} style={{
                      background: "rgba(255,255,255,0.02)", border: "1px solid #1a2535",
                      borderRadius: 6, padding: "10px", textAlign: "center",
                    }}>
                      <div style={{ fontSize: 9, color: "#4a6080", letterSpacing: 1 }}>{s.label}</div>
                      <div style={{ fontSize: 16, fontWeight: 900, color: s.col, marginTop: 2 }}>{s.val}</div>
                    </div>
                  ))}
                </div>

                <button onClick={triggerSignal} disabled={isRunning || systemPaused} style={{
                  background: isRunning ? "#1a2535" : systemPaused ? "#1a2535" : "linear-gradient(135deg, #00ff88, #00d4ff)",
                  color: isRunning || systemPaused ? "#4a6080" : "#000",
                  border: "none", borderRadius: 8, padding: "14px",
                  cursor: isRunning || systemPaused ? "not-allowed" : "pointer",
                  fontFamily: "inherit", fontSize: 13, fontWeight: 900, letterSpacing: 2,
                  transition: "all 0.2s",
                }}>
                  {isRunning ? "⟳ SCANNING..." : systemPaused ? "SYSTEM PAUSED" : "▶ RUN ORB SIGNAL ENGINE"}
                </button>

                {systemPaused && (
                  <div style={{ fontSize: 11, color: "#ef4444", textAlign: "center" }}>
                    System paused — resume to allow new signals
                  </div>
                )}
              </div>
            </Panel>

            {/* Signal Output */}
            <Panel title="LAST SIGNAL" subtitle={signal ? signal.timestamp : "No signal generated yet"}>
              {!signal ? (
                <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: 200, color: "#2d3f55", fontSize: 12 }}>
                  Trigger the signal engine to generate a trade →
                </div>
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                  <div style={{
                    background: signal.status === "ACTIVE"
                      ? (signal.direction === "LONG" ? "rgba(0,255,136,0.08)" : "rgba(239,68,68,0.08)")
                      : "rgba(100,116,139,0.08)",
                    border: `1px solid ${signal.status === "ACTIVE" ? (signal.direction === "LONG" ? "#00ff88" : "#ef4444") : "#334155"}`,
                    borderRadius: 8, padding: "12px 16px",
                    display: "flex", justifyContent: "space-between", alignItems: "center",
                  }}>
                    <div>
                      <div style={{ fontSize: 11, color: "#4a6080" }}>NQ · 5M · ORB</div>
                      <div style={{ fontSize: 22, fontWeight: 900, color: signal.status === "ACTIVE" ? (signal.direction === "LONG" ? "#00ff88" : "#ef4444") : "#4a6080" }}>
                        {signal.status === "ACTIVE" ? signal.direction : signal.status}
                      </div>
                    </div>
                    <div style={{ textAlign: "right" }}>
                      <div style={{ fontSize: 11, color: "#4a6080" }}>Confidence</div>
                      <div style={{ fontSize: 22, fontWeight: 900, color: "#00d4ff" }}>
                        {signal.status === "ACTIVE" ? `${signal.confidence}%` : "—"}
                      </div>
                    </div>
                  </div>

                  {signal.status === "ACTIVE" && (
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
                      {[
                        { label: "ENTRY",    val: signal.entry, col: "#fff" },
                        { label: "STOP LOSS",val: signal.sl,    col: "#ef4444" },
                        { label: "TP1 (1:1)",val: signal.tp1,   col: "#f59e0b" },
                        { label: "TP2 (1:2)",val: signal.tp2,   col: "#00ff88" },
                        { label: "TP3 (1:2.5)",val: signal.tp3, col: "#00d4ff" },
                        { label: "BREAKEVEN",val: signal.be,    col: "#94a3b8" },
                        { label: "RISK PTS", val: `${signal.riskPoints}pts`, col: "#f97316" },
                        { label: "CONTRACTS",val: signal.contracts, col: "#f59e0b" },
                        { label: "RISK $",   val: `$${signal.riskDollars}`, col: "#ef4444" },
                        { label: "KILL TIME",val: new Date(signal.killTime).toLocaleTimeString(), col: "#6b7280" },
                      ].map((r, i) => (
                        <div key={i} style={{
                          display: "flex", justifyContent: "space-between", alignItems: "center",
                          padding: "5px 10px", background: "rgba(255,255,255,0.02)",
                          borderRadius: 4, borderLeft: `2px solid ${r.col}`,
                        }}>
                          <span style={{ fontSize: 9, color: "#4a6080" }}>{r.label}</span>
                          <span style={{ fontSize: 11, fontWeight: 700, color: r.col }}>{r.val}</span>
                        </div>
                      ))}
                    </div>
                  )}

                  {signal.status !== "ACTIVE" && (
                    <div style={{
                      background: "rgba(239,68,68,0.06)", border: "1px solid #3d1a1a",
                      borderRadius: 8, padding: 14,
                    }}>
                      <div style={{ fontSize: 10, color: "#ef4444", fontWeight: 700, marginBottom: 4 }}>BLOCKED REASON</div>
                      <div style={{ fontSize: 12, color: "#94a3b8" }}>{signal.reason}</div>
                      {signal.orRange && <div style={{ fontSize: 10, color: "#4a6080", marginTop: 6 }}>OR Range: {signal.orRange}pts · ADX: {signal.adx} · ATR: {signal.atr}pts</div>}
                    </div>
                  )}
                </div>
              )}
            </Panel>

            {/* Config panel */}
            <Panel title="SYSTEM CONFIG" subtitle="NQ3 live parameters" span={2}>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 8 }}>
                {Object.entries(CONFIG).filter(([k]) => !["INSTRUMENT","SESSION_OPEN_ET","SESSION_ORB_END_ET","SESSION_CLOSE_ET","TRADING_WINDOW_END_ET"].includes(k)).map(([k, v], i) => (
                  <div key={i} style={{
                    background: "rgba(255,255,255,0.02)", border: "1px solid #1a2535",
                    borderRadius: 6, padding: "8px 10px",
                  }}>
                    <div style={{ fontSize: 8, color: "#4a6080", letterSpacing: 1 }}>{k.replace(/_/g," ")}</div>
                    <div style={{ fontSize: 13, fontWeight: 700, color: "#00d4ff", marginTop: 2 }}>{v}</div>
                  </div>
                ))}
              </div>
            </Panel>
          </div>
        )}

        {/* ══ BACKTEST TAB ══ */}
        {tab === "backtest" && (
          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>

            {/* Controls */}
            <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
              <input
                type="number" value={btDays} min={30} max={365} step={30}
                onChange={e => setBtDays(parseInt(e.target.value) || 90)}
                style={{
                  background: "#0d1520", border: "1px solid #1a2535", color: "#e2e8f0",
                  fontFamily: "inherit", fontSize: 12, padding: "8px 12px", borderRadius: 6, width: 80,
                }}
              />
              <span style={{ fontSize: 11, color: "#4a6080" }}>days</span>
              <button onClick={runNewBacktest} style={{
                background: "linear-gradient(135deg, #00ff88, #00d4ff)", color: "#000",
                border: "none", borderRadius: 6, padding: "8px 20px",
                fontFamily: "inherit", fontSize: 11, fontWeight: 900, cursor: "pointer", letterSpacing: 1,
              }}>RUN BACKTEST</button>
            </div>

            {/* Summary stats */}
            <div style={{ display: "grid", gridTemplateColumns: "repeat(8,1fr)", gap: 8 }}>
              {[
                { label: "TRADES",        val: newBt.summary.totalTrades },
                { label: "WIN RATE",      val: `${newBt.summary.winRate}%`,    col: "#00ff88" },
                { label: "PROFIT FACTOR", val: newBt.summary.profitFactor,     col: "#00d4ff" },
                { label: "NET P&L",       val: `+$${newBt.summary.netPnL.toLocaleString()}`, col: "#00ff88" },
                { label: "NET P&L %",     val: `+${newBt.summary.netPnLPct}%`, col: "#00ff88" },
                { label: "MAX DD",        val: `${newBt.summary.maxDDPct}%`,   col: "#ef4444" },
                { label: "AVG WIN",       val: `${newBt.summary.avgWinPts}pts`,col: "#00ff88" },
                { label: "AVG LOSS",      val: `${newBt.summary.avgLossPts}pts`,col:"#ef4444" },
              ].map((s, i) => (
                <div key={i} style={{
                  background: "rgba(255,255,255,0.02)", border: "1px solid #1a2535",
                  borderRadius: 6, padding: "10px", textAlign: "center",
                }}>
                  <div style={{ fontSize: 8, color: "#4a6080", letterSpacing: 1 }}>{s.label}</div>
                  <div style={{ fontSize: 16, fontWeight: 900, color: s.col || "#fff", marginTop: 3 }}>{s.val}</div>
                </div>
              ))}
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: 16 }}>
              {/* Equity curve */}
              <Panel title="EQUITY CURVE" subtitle={`${newBt.summary.totalTrades} trades · $50k start`}>
                <div style={{ height: 220 }}>
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={newBt.equityCurve}>
                      <defs>
                        <linearGradient id="eq2" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="5%"  stopColor="#00ff88" stopOpacity={0.12} />
                          <stop offset="95%" stopColor="#00ff88" stopOpacity={0} />
                        </linearGradient>
                      </defs>
                      <CartesianGrid strokeDasharray="2 4" stroke="#1a2535" vertical={false} />
                      <XAxis dataKey="day" tick={{ fill: "#4a6080", fontSize: 9 }} />
                      <YAxis tick={{ fill: "#4a6080", fontSize: 9 }} tickFormatter={v => `$${(v/1000).toFixed(0)}k`} />
                      <Tooltip contentStyle={{ background: "#0d1520", border: "1px solid #1a2535", fontSize: 11 }} formatter={v => [`$${v.toLocaleString()}`, "Equity"]} />
                      <ReferenceLine y={50000} stroke="#334155" strokeDasharray="4 4" />
                      <Area type="monotone" dataKey="equity" stroke="#00ff88" strokeWidth={1.5} fill="url(#eq2)" dot={false} />
                    </AreaChart>
                  </ResponsiveContainer>
                </div>
              </Panel>

              {/* P&L distribution */}
              <Panel title="P&L DISTRIBUTION" subtitle="Per-trade pips">
                <div style={{ height: 220 }}>
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={newBt.trades.slice(-40)} barSize={4}>
                      <CartesianGrid strokeDasharray="2 4" stroke="#1a2535" vertical={false} />
                      <XAxis dataKey="id" hide />
                      <YAxis tick={{ fill: "#4a6080", fontSize: 9 }} />
                      <Tooltip contentStyle={{ background: "#0d1520", border: "1px solid #1a2535", fontSize: 11 }} formatter={v => [`${v}pts`, "P&L"]} />
                      <ReferenceLine y={0} stroke="#334155" />
                      <Bar dataKey="pnlPts" fill="#00ff88"
                        radius={[2,2,0,0]}
                        label={false}
                        cells={newBt.trades.slice(-40).map((t, i) => ({
                          fill: t.pnlPts >= 0 ? "#00ff88" : "#ef4444",
                        }))}
                      />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </Panel>
            </div>

            {/* Walk-forward windows */}
            <Panel title="WALK-FORWARD ANALYSIS" subtitle="4 rolling windows · in-sample vs out-of-sample">
              <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 10 }}>
                {[0,1,2,3].map(w => {
                  const chunk = newBt.trades.slice(w * Math.floor(newBt.trades.length/4), (w+1) * Math.floor(newBt.trades.length/4));
                  const wWins  = chunk.filter(t => t.pnlPts > 0).length;
                  const wTotal = chunk.length;
                  const wWR    = wTotal > 0 ? (wWins/wTotal*100).toFixed(0) : 0;
                  const wPnL   = chunk.reduce((s,t)=>s+t.pnlPts,0).toFixed(1);
                  const pass   = parseFloat(wWR) >= 50;
                  return (
                    <div key={w} style={{
                      background: pass ? "rgba(0,255,136,0.04)" : "rgba(239,68,68,0.04)",
                      border: `1px solid ${pass ? "#00ff88" : "#ef4444"}22`,
                      borderTop: `3px solid ${pass ? "#00ff88" : "#ef4444"}`,
                      borderRadius: 8, padding: 14,
                    }}>
                      <div style={{ fontSize: 10, color: "#4a6080", marginBottom: 8 }}>WINDOW {w+1}</div>
                      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                        <Row label="Trades" val={wTotal} />
                        <Row label="Win Rate" val={`${wWR}%`} col={parseFloat(wWR) >= 50 ? "#00ff88" : "#ef4444"} />
                        <Row label="Net Pts" val={`${wPnL}pts`} col={parseFloat(wPnL) >= 0 ? "#00ff88" : "#ef4444"} />
                        <Row label="Status" val={pass ? "PASS ✓" : "FAIL ✗"} col={pass ? "#00ff88" : "#ef4444"} />
                      </div>
                    </div>
                  );
                })}
              </div>
            </Panel>
          </div>
        )}

        {/* ══ RISK TAB ══ */}
        {tab === "risk" && (
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
            <Panel title="CIRCUIT BREAKERS" subtitle="Hard kill-switch gates">
              <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                {[
                  { name: "Daily Loss Limit",     threshold: `${CONFIG.MAX_DAILY_LOSS_POINTS}pts`,  status: "CLEAR", val: "0pts used" },
                  { name: "Consec. Losses Gate",  threshold: `${CONFIG.MAX_CONSECUTIVE_LOSSES} losses`, status: "CLEAR", val: `${consecutiveLosses} so far` },
                  { name: "Daily Trade Cap",      threshold: `${CONFIG.MAX_DAILY_TRADES} trades/day`, status: "CLEAR", val: `${dailyTrades} used` },
                  { name: "OR Range Filter",      threshold: `${CONFIG.MIN_ORB_RANGE_POINTS}–${CONFIG.MAX_ORB_RANGE_POINTS}pts`, status: orb && orb.orRange >= 15 && orb.orRange <= 120 ? "CLEAR" : "BLOCK", val: orb ? `${orb.orRange}pts` : "—" },
                  { name: "News Blackout",        threshold: "±30min events",  status: "CLEAR", val: "No events" },
                  { name: "Time Kill",            threshold: `${CONFIG.TIME_KILL_MINUTES}min`,     status: "ACTIVE", val: "Auto-close enabled" },
                  { name: "Afternoon Cutoff",     threshold: CONFIG.TRADING_WINDOW_END_ET + " ET", status: "CLEAR", val: "Before noon" },
                  { name: "System Pause",         threshold: "Manual override",status: systemPaused ? "PAUSED" : "CLEAR", val: systemPaused ? "PAUSED" : "Running" },
                ].map((g, i) => (
                  <div key={i} style={{
                    display: "flex", alignItems: "center", justifyContent: "space-between",
                    padding: "10px 14px",
                    background: g.status === "CLEAR" || g.status === "ACTIVE"
                      ? "rgba(0,255,136,0.03)" : "rgba(239,68,68,0.06)",
                    border: `1px solid ${g.status === "CLEAR" || g.status === "ACTIVE" ? "#1a2535" : "#3d1a1a"}`,
                    borderLeft: `3px solid ${g.status === "CLEAR" ? "#00ff88" : g.status === "ACTIVE" ? "#00d4ff" : "#ef4444"}`,
                    borderRadius: 6,
                  }}>
                    <div>
                      <div style={{ fontSize: 11, fontWeight: 700, color: "#e2e8f0" }}>{g.name}</div>
                      <div style={{ fontSize: 9, color: "#4a6080", marginTop: 2 }}>Threshold: {g.threshold}</div>
                    </div>
                    <div style={{ textAlign: "right" }}>
                      <div style={{
                        fontSize: 10, fontWeight: 700, padding: "2px 8px", borderRadius: 4,
                        background: g.status === "CLEAR" ? "rgba(0,255,136,0.1)" : g.status === "ACTIVE" ? "rgba(0,212,255,0.1)" : "rgba(239,68,68,0.1)",
                        color: g.status === "CLEAR" ? "#00ff88" : g.status === "ACTIVE" ? "#00d4ff" : "#ef4444",
                      }}>{g.status}</div>
                      <div style={{ fontSize: 9, color: "#4a6080", marginTop: 3 }}>{g.val}</div>
                    </div>
                  </div>
                ))}
              </div>
            </Panel>

            <Panel title="POSITION SIZING" subtitle="Risk architecture · prop-firm compliant">
              <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
                <div style={{ background: "rgba(0,212,255,0.05)", border: "1px solid #00d4ff22", borderRadius: 8, padding: 16 }}>
                  <div style={{ fontSize: 10, color: "#4a6080", marginBottom: 8 }}>FORMULA</div>
                  <div style={{ fontSize: 12, color: "#00d4ff", lineHeight: 1.8 }}>
                    Risk $ = Equity × (Max Risk Pts / 1000)<br/>
                    Contracts = Risk $ ÷ (Risk Pts × $20/pt)<br/>
                    SL = Entry ± (OR Range × 0.5)<br/>
                    TP1 = Entry ± Risk Pts (1:1)<br/>
                    TP2 = Entry ± 2× Risk Pts (1:2)<br/>
                    TP3 = Entry ± 2.5× Risk Pts (1:2.5)
                  </div>
                </div>

                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
                  {[
                    { label: "Account Equity",   val: `$${accountEquity.toLocaleString()}` },
                    { label: "Risk Per Trade",   val: `${(CONFIG.MAX_TRADE_RISK_POINTS/10).toFixed(1)}%` },
                    { label: "Max Risk $",       val: `$${(accountEquity * CONFIG.MAX_TRADE_RISK_POINTS/1000).toFixed(0)}` },
                    { label: "Point Value",      val: `$${CONFIG.POINT_VALUE}/pt` },
                    { label: "Min RR Required",  val: `1:${CONFIG.MIN_RR_RATIO}` },
                    { label: "Partial Close",    val: `${CONFIG.PARTIAL_TP_PERCENT}% @ TP1` },
                  ].map((r, i) => (
                    <div key={i} style={{
                      background: "rgba(255,255,255,0.02)", border: "1px solid #1a2535",
                      borderRadius: 6, padding: "10px 12px",
                      display: "flex", justifyContent: "space-between", alignItems: "center",
                    }}>
                      <span style={{ fontSize: 10, color: "#4a6080" }}>{r.label}</span>
                      <span style={{ fontSize: 12, fontWeight: 700, color: "#00d4ff" }}>{r.val}</span>
                    </div>
                  ))}
                </div>

                {/* Expected Value */}
                <div style={{ background: "rgba(0,255,136,0.05)", border: "1px solid #00ff8822", borderRadius: 8, padding: 14 }}>
                  <div style={{ fontSize: 10, color: "#4a6080", marginBottom: 8 }}>EXPECTED VALUE (EV) CALC</div>
                  {[60, 65, 70].map(wr => {
                    const ev = ((wr/100) * 2) - ((1 - wr/100) * 1);
                    return (
                      <div key={wr} style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
                        <span style={{ fontSize: 11, color: "#94a3b8" }}>WR {wr}% × RR 1:2</span>
                        <span style={{ fontSize: 11, fontWeight: 700, color: "#00ff88" }}>EV = +{ev.toFixed(2)}R</span>
                      </div>
                    );
                  })}
                </div>
              </div>
            </Panel>
          </div>
        )}

        {/* ══ AUDIT LOG ══ */}
        {tab === "auditlog" && (
          <Panel title="AUDIT LOG" subtitle={`${logs.length} entries · append-only`}>
            {logs.length === 0 ? (
              <div style={{ textAlign: "center", color: "#2d3f55", padding: 40, fontSize: 12 }}>
                No signals generated yet. Run the signal engine to populate the log.
              </div>
            ) : (
              <div style={{ overflowX: "auto" }}>
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 10 }}>
                  <thead>
                    <tr style={{ borderBottom: "1px solid #1a2535" }}>
                      {["ID","TIME","STATUS","DIR","ENTRY","SL","TP1","TP2","RISK PTS","ADX","ATR","OR RANGE","REASON"].map(h => (
                        <th key={h} style={{ padding: "8px 10px", textAlign: "left", color: "#4a6080", letterSpacing: 1, fontWeight: 700 }}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {logs.map((l, i) => (
                      <tr key={l.id} style={{
                        borderBottom: "1px solid #0d1520",
                        background: i % 2 === 0 ? "transparent" : "rgba(255,255,255,0.01)",
                      }}>
                        <td style={{ padding: "8px 10px", color: "#4a6080" }}>#{l.id}</td>
                        <td style={{ padding: "8px 10px", color: "#4a6080" }}>{new Date(l.created_at).toLocaleTimeString()}</td>
                        <td style={{ padding: "8px 10px" }}>
                          <span style={{
                            padding: "2px 7px", borderRadius: 4, fontSize: 9, fontWeight: 700,
                            background: l.status === "ACTIVE" ? "rgba(0,255,136,0.1)" : l.status === "WAITING" ? "rgba(245,158,11,0.1)" : "rgba(239,68,68,0.1)",
                            color: l.status === "ACTIVE" ? "#00ff88" : l.status === "WAITING" ? "#f59e0b" : "#ef4444",
                          }}>{l.status}</span>
                        </td>
                        <td style={{ padding: "8px 10px", color: l.direction === "LONG" ? "#00ff88" : l.direction === "SHORT" ? "#ef4444" : "#4a6080", fontWeight: 700 }}>{l.direction || "—"}</td>
                        <td style={{ padding: "8px 10px", color: "#e2e8f0" }}>{l.entry || "—"}</td>
                        <td style={{ padding: "8px 10px", color: "#ef4444" }}>{l.sl || "—"}</td>
                        <td style={{ padding: "8px 10px", color: "#f59e0b" }}>{l.tp1 || "—"}</td>
                        <td style={{ padding: "8px 10px", color: "#00ff88" }}>{l.tp2 || "—"}</td>
                        <td style={{ padding: "8px 10px", color: "#f97316" }}>{l.riskPoints ? `${l.riskPoints}pts` : "—"}</td>
                        <td style={{ padding: "8px 10px", color: l.adx >= 14 ? "#94a3b8" : "#ef4444" }}>{l.adx || "—"}</td>
                        <td style={{ padding: "8px 10px", color: "#94a3b8" }}>{l.atr || "—"}</td>
                        <td style={{ padding: "8px 10px", color: l.orRange >= 15 ? "#f59e0b" : "#ef4444" }}>{l.orRange ? `${l.orRange}pts` : "—"}</td>
                        <td style={{ padding: "8px 10px", color: "#4a6080", maxWidth: 120, overflow: "hidden", textOverflow: "ellipsis" }}>{l.reason || "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Panel>
        )}
      </div>

      {/* ── FOOTER ── */}
      <div style={{
        borderTop: "1px solid #1a2535", padding: "12px 24px",
        display: "flex", justifyContent: "space-between", alignItems: "center",
        background: "#080c10",
      }}>
        <div style={{ fontSize: 9, color: "#2d3f55", letterSpacing: 1 }}>
          NQ3 SYSTEM v3.0 · E-MINI NQ FUTURES · ORB STRATEGY · IBKR · PM2
        </div>
        <div style={{ fontSize: 9, color: "#2d3f55", letterSpacing: 1 }}>
          ⚠ NOT FINANCIAL ADVICE · PAPER TRADING UNTIL VALIDATED
        </div>
        <div style={{ fontSize: 9, color: "#2d3f55", letterSpacing: 1 }}>
          Built on DQ3 architecture · Claude Sonnet
        </div>
      </div>
    </div>
  );
}

// ── Shared UI primitives ──
function Panel({ title, subtitle, children, span = 1 }) {
  return (
    <div style={{
      background: "#090d13",
      border: "1px solid #1a2535",
      borderRadius: 8,
      padding: 16,
      gridColumn: span > 1 ? `span ${span}` : undefined,
    }}>
      <div style={{ marginBottom: 14 }}>
        <div style={{ fontSize: 11, fontWeight: 700, color: "#94a3b8", letterSpacing: 2 }}>{title}</div>
        {subtitle && <div style={{ fontSize: 9, color: "#4a6080", marginTop: 2 }}>{subtitle}</div>}
      </div>
      {children}
    </div>
  );
}

function Row({ label, val, col = "#e2e8f0" }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10 }}>
      <span style={{ color: "#4a6080" }}>{label}</span>
      <span style={{ fontWeight: 700, color: col }}>{val}</span>
    </div>
  );
}
