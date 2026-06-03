"""
Shadow AI Trading System - Core Libraries
Production-hardened trading logic with regime filtering and risk management
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum


class MarketRegime(Enum):
    TRENDING_BULL = "trending_bull"
    TRENDING_BEAR = "trending_bear"
    RANGING = "ranging"
    CHOPPY = "choppy"


@dataclass
class RegimeMetrics:
    adx: float
    atr: float
    atr_percentile: float
    regime: MarketRegime
    is_tradeable: bool
    reason: str


class RegimeFilter:
    """
    PATCH 1: Regime Hard-Gate
    Blocks trades in low-volatility, ranging markets where SMC fails
    
    OPTIMIZED: ADX threshold lowered from 20.0 to 14.0 to increase trade frequency
    """
    
    def __init__(self, adx_threshold: float = 14.0, atr_percentile_threshold: float = 30.0):
        self.adx_threshold = adx_threshold
        self.atr_percentile_threshold = atr_percentile_threshold
    
    def calculate_adx(self, high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
        """Calculate ADX (Average Directional Index)"""
        plus_dm = high.diff()
        minus_dm = -low.diff()
        
        plus_dm[plus_dm < 0] = 0
        minus_dm[minus_dm < 0] = 0
        
        tr1 = high - low
        tr2 = abs(high - close.shift())
        tr3 = abs(low - close.shift())
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        
        plus_di = 100 * (plus_dm.ewm(span=period).mean() / tr.ewm(span=period).mean())
        minus_di = 100 * (minus_dm.ewm(span=period).mean() / tr.ewm(span=period).mean())
        
        dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
        adx = dx.ewm(span=period).mean()
        
        return adx
    
    def calculate_atr(self, high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
        """Calculate ATR (Average True Range)"""
        tr1 = high - low
        tr2 = abs(high - close.shift())
        tr3 = abs(low - close.shift())
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.ewm(span=period).mean()
        return atr
    
    def calculate_atr_percentile(self, atr: pd.Series, lookback: int = 100) -> pd.Series:
        """Calculate ATR percentile relative to recent history"""
        return atr.rolling(lookback).apply(lambda x: (x.iloc[-1] - x.min()) / (x.max() - x.min()) * 100 if x.max() != x.min() else 50)
    
    def assess_regime(self, df: pd.DataFrame) -> RegimeMetrics:
        """
        Assess current market regime using ADX and ATR
        Returns tradeable=False if market is choppy/ranging
        """
        high = df['high']
        low = df['low']
        close = df['close']
        
        adx = self.calculate_adx(high, low, close)
        atr = self.calculate_atr(high, low, close)
        atr_percentile = self.calculate_atr_percentile(atr)
        
        current_adx = adx.iloc[-1] if len(adx) > 0 else 0
        current_atr = atr.iloc[-1] if len(atr) > 0 else 0
        current_atr_pct = atr_percentile.iloc[-1] if len(atr_percentile) > 0 else 50
        
        # Handle NaN values
        if np.isnan(current_adx):
            current_adx = 0
        if np.isnan(current_atr):
            current_atr = 0
        if np.isnan(current_atr_pct):
            current_atr_pct = 50
        
        # Determine regime
        if current_adx < self.adx_threshold:
            regime = MarketRegime.CHOPPY
            is_tradeable = False
            reason = f"ADX ({current_adx:.2f}) below threshold ({self.adx_threshold}) - Choppy market"
        elif current_atr_pct < self.atr_percentile_threshold:
            regime = MarketRegime.RANGING
            is_tradeable = False
            reason = f"ATR percentile ({current_atr_pct:.2f}%) below threshold ({self.atr_percentile_threshold}%) - Low volatility"
        elif current_adx > 25 and current_adx > 40:
            regime = MarketRegime.TRENDING_BULL if close.iloc[-1] > close.iloc[-5] else MarketRegime.TRENDING_BEAR
            is_tradeable = True
            reason = f"Strong trend detected (ADX: {current_adx:.2f})"
        else:
            regime = MarketRegime.TRENDING_BULL if close.iloc[-1] > close.iloc[-5] else MarketRegime.TRENDING_BEAR
            is_tradeable = True
            reason = f"Tradeable regime (ADX: {current_adx:.2f}, ATR%: {current_atr_pct:.2f})"
        
        return RegimeMetrics(
            adx=current_adx,
            atr=current_atr,
            atr_percentile=current_atr_pct,
            regime=regime,
            is_tradeable=is_tradeable,
            reason=reason
        )
    
    def is_tradeable(self, df: pd.DataFrame) -> Tuple[bool, str]:
        """Quick check if market conditions allow trading"""
        metrics = self.assess_regime(df)
        return metrics.is_tradeable, metrics.reason


@dataclass
class TradeSignal:
    asset: str
    direction: str  # 'BUY' or 'SELL'
    entry: float
    stop_loss: float
    take_profit: float
    confidence: float
    rr_ratio: float
    regime_ok: bool
    structure_valid: bool
    timestamp: str
    reasoning: str


class RiskManager:
    """
    PATCH 2 & 4: Asymmetric Exits and Prop Firm Kill-Switches
    Manages position sizing, breakeven logic, and circuit breakers
    
    CRITICAL UPDATE: Daily drawdown halt (0.60%) calculated using real-time
    floating equity (balance + unrealized PnL), not just closed balance.
    """
    
    def __init__(self, 
                 account_balance: float = 100000,
                 max_risk_per_trade: float = 0.003,  # 0.3%
                 daily_loss_limit: float = 0.006,    # 0.60% FLOATING EQUITY HALT
                 consecutive_loss_limit: int = 3,
                 weekly_loss_limit: float = 0.08):   # 8%
        
        self.account_balance = account_balance
        self.max_risk_per_trade = max_risk_per_trade
        self.daily_loss_limit = daily_loss_limit  # 0.60% hard stop
        self.consecutive_loss_limit = consecutive_loss_limit
        self.weekly_loss_limit = weekly_loss_limit
        
        # State tracking
        self.daily_pnl = 0.0
        self.weekly_pnl = 0.0
        self.consecutive_losses = 0
        self.total_trades_today = 0
        self.daily_start_balance = account_balance  # Track starting balance for DD calc
        self.unrealized_pnl = 0.0  # Floating PnL from open positions
    
    def reset_daily(self):
        """Reset daily counters (call at start of each trading day)"""
        self.daily_pnl = 0.0
        self.consecutive_losses = 0
        self.total_trades_today = 0
        self.daily_start_balance = self.account_balance + self.unrealized_pnl
        self.unrealized_pnl = 0.0
    
    def update_floating_equity(self, unrealized_pnl: float):
        """Update unrealized PnL from open positions for floating equity calc"""
        self.unrealized_pnl = unrealized_pnl
    
    def get_floating_equity(self) -> float:
        """Returns current floating equity (balance + unrealized PnL)"""
        return self.daily_start_balance + self.daily_pnl + self.unrealized_pnl
    
    def reset_weekly(self):
        """Reset weekly counters (call at start of each week)"""
        self.weekly_pnl = 0.0
    
    def record_trade_result(self, pnl: float, is_winner: bool):
        """Record trade result for kill-switch tracking"""
        self.daily_pnl += pnl
        self.weekly_pnl += pnl
        self.total_trades_today += 1
        
        if is_winner:
            self.consecutive_losses = 0
        else:
            self.consecutive_losses += 1
    
    def check_kill_switches(self) -> Tuple[bool, str]:
        """
        PATCH 4: Prop Firm Kill-Switches
        CRITICAL: Uses floating equity (balance + unrealized PnL) for daily DD calc
        
        Returns (can_trade, reason)
        """
        # Calculate floating equity drawdown
        current_floating_equity = self.get_floating_equity()
        floating_dd_amount = self.daily_start_balance - current_floating_equity
        floating_dd_pct = floating_dd_amount / self.daily_start_balance if self.daily_start_balance > 0 else 0
        
        weekly_loss_pct = self.weekly_pnl / self.account_balance
        
        # 0.60% FLOATING EQUITY HALT - Immediate trigger
        if floating_dd_pct >= self.daily_loss_limit:
            return False, f"CRITICAL: Floating equity DD {floating_dd_pct:.2%} >= {self.daily_loss_limit:.2%} limit - E-STOP TRIGGERED"
        
        if weekly_loss_pct <= -self.weekly_loss_limit:
            return False, f"Weekly loss limit reached: {weekly_loss_pct:.2%}"
        
        if self.consecutive_losses >= self.consecutive_loss_limit:
            return False, f"Consecutive loss limit reached: {self.consecutive_losses}"
        
        return True, f"All kill-switches clear (Floating DD: {floating_dd_pct:.2%}, Daily Start: ${self.daily_start_balance:.2f})"
    
    def calculate_position_size(self, entry: float, stop_loss: float, asset: str = "EURUSD") -> float:
        """
        Calculate position size based on risk parameters
        Returns lot size
        """
        risk_amount = self.account_balance * self.max_risk_per_trade
        pip_value = self._get_pip_value(asset)
        
        if asset in ["XAUUSD", "GOLD"]:
            # Gold: $0.01 per 0.01 lot per point
            stop_distance = abs(entry - stop_loss)
            lot_size = risk_amount / (stop_distance * 100)  # $100 per lot per point
        else:
            # Forex: ~$10 per pip per standard lot
            stop_distance_pips = abs(entry - stop_loss) * 10000
            lot_size = risk_amount / (stop_distance_pips * 10)
        
        # Round to 2 decimal places for micro lots
        return round(max(0.01, lot_size), 2)
    
    def _get_pip_value(self, asset: str) -> float:
        """Get approximate pip value per standard lot"""
        if asset in ["EURUSD", "GBPUSD", "AUDUSD"]:
            return 10.0
        elif asset in ["USDJPY"]:
            return 7.0
        elif asset in ["XAUUSD", "GOLD"]:
            return 100.0
        else:
            return 10.0
    
    def get_breakeven_alert(self, entry: float, sl: float, tp: float, current_price: float, direction: str) -> Optional[str]:
        """
        PATCH 2: Breakeven Shield with spread buffer
        Alerts when to move SL to breakeven + buffer
        """
        spread_buffer = 0.00015  # 1.5 pips
        
        if direction == "BUY":
            breakeven_price = entry + spread_buffer
            if current_price >= tp:
                return None  # Already hit TP
            elif current_price >= breakeven_price:
                return f"⚠️ MOVE SL TO BREAKEVEN NOW (Entry: {entry:.5f}, Current: {current_price:.5f}, Buffer included)"
        else:  # SELL
            breakeven_price = entry - spread_buffer
            if current_price <= tp:
                return None
            elif current_price <= breakeven_price:
                return f"⚠️ MOVE SL TO BREAKEVEN NOW (Entry: {entry:.5f}, Current: {current_price:.5f}, Buffer included)"
        
        return None
    
    def get_partial_profit_alert(self, entry: float, sl: float, tp: float, current_price: float, direction: str, rr_target: float = 2.0) -> Optional[str]:
        """
        PATCH 2: Partial Profit Lock at 1:2 RR
        """
        risk = abs(entry - sl)
        target_profit = risk * rr_target
        
        if direction == "BUY":
            profit = current_price - entry
            tp_level = entry + target_profit
        else:
            profit = entry - current_price
            tp_level = entry - target_profit
        
        if profit >= target_profit * 0.95:  # Alert at 95% of target to account for slippage
            return f"🔒 CLOSE 50% POSITION. TRAIL REMAINING. (Target: {tp_level:.5f}, Current: {current_price:.5f})"
        
        return None
    
    def get_time_decay_alert(self, entry_time: str, current_time: str, max_hours: int = 18) -> Optional[str]:
        """
        PATCH 2: Time-Decay Kill Switch
        Close trade if no progress after 18 hours
        """
        from datetime import datetime
        
        try:
            entry_dt = datetime.fromisoformat(entry_time.replace('Z', '+00:00'))
            current_dt = datetime.fromisoformat(current_time.replace('Z', '+00:00'))
            hours_elapsed = (current_dt - entry_dt).total_seconds() / 3600
            
            if hours_elapsed >= max_hours:
                return f"⏰ TIME DECAY: CLOSE TRADE AT MARKET (Elapsed: {hours_elapsed:.1f}h, Max: {max_hours}h)"
        except:
            pass
        
        return None


# Few-Shot Autopsy Injection - Compressed Failure Signatures
FEW_SHOT_FAILURE_SIGNATURES = """
CRITICAL FAILURE PATTERNS - NEVER ENTER IF THESE CONDITIONS EXIST:

FAILURE #1 (2023-06-15 EURUSD): Entered on "bullish order block" during summer chop. 
ADDITIONAL CONTEXT: ADX was 12 (extremely low), no liquidity sweep occurred, price was consolidating in 20-pip range.
LESSON: NO trade if ADX < 20 OR no confirmed sweep+BOS.

FAILURE #2 (2023-09-20 EURUSD): Held losing short through FOMC. 
ADDITIONAL CONTEXT: High-impact news event occurred 2 hours after entry, ignored macro calendar.
LESSON: NO new entries within 4 hours of high-impact news (CPI, NFP, FOMC, Rate Decision).

FAILURE #3 (2024-01-10 XAUUSD): Chased breakout without retest. 
ADDITIONAL CONTEXT: Price broke structure but did not return to fill FVG or test order block before entry.
LESSON: MUST wait for mitigation (FVG fill or OB test) after BOS. No chasing.

FAILURE #4 (2023-11-03 EURUSD): Counter-trend fade in strong trend. 
ADDITIONAL CONTEXT: ADX was 45 (strong trend), tried to pick top without reversal confirmation.
LESSON: NO counter-trend trades if ADX > 30. Wait for clear reversal structure (sweep+BOS+mitigation).

FAILURE #5 (2024-02-28 XAUUSD): Entry too far from structural level. 
ADDITIONAL CONTEXT: Entered 15 pips away from identified order block, stopped out by wick before move.
LESSON: Entry must be WITHIN 5 pips of identified structural level (OB/FVG edge). Precision required.

MANDATORY VALIDATION CHECKLIST (ALL MUST BE TRUE):
✓ ADX >= 20 AND ATR percentile >= 30
✓ Confirmed liquidity sweep (stop hunt) in opposite direction
✓ Market structure shift (BOS) after sweep
✓ Mitigation present (FVG fill or OB test)
✓ No high-impact news within 4 hours
✓ Entry within 5 pips of structural level
✓ Minimum 1:2.0 RR available to next structural level
"""
