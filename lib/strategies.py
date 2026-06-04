"""
Shadow AI Trading System - Isolated Strategy Modules
=====================================================

Object-Oriented modular architecture with strict isolation between strategies.
Each strategy is an independent silo with its own:
- Entry/exit logic
- Indicator calculations
- Risk parameters
- State tracking

NO cross-contamination allowed between strategies.
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime, time
from enum import Enum
from abc import ABC, abstractmethod


class StrategySignal:
    """Unified signal structure for all strategies"""
    
    def __init__(self,
                 strategy_id: str,
                 direction: Optional[str],  # 'BUY', 'SELL', or None
                 entry: Optional[float],
                 stop_loss: Optional[float],
                 take_profit: Optional[float],
                 lots: float = 0.0,
                 confidence: float = 0.0,
                 rr_ratio: float = 0.0,
                 timestamp: Optional[datetime] = None,
                 reasoning: str = "",
                 grade_score: Optional[int] = None):
        
        self.strategy_id = strategy_id
        self.direction = direction
        self.entry = entry
        self.stop_loss = stop_loss
        self.take_profit = take_profit
        self.lots = lots
        self.confidence = confidence
        self.rr_ratio = rr_ratio
        self.timestamp = timestamp or datetime.utcnow()
        self.reasoning = reasoning
        self.grade_score = grade_score
    
    def is_valid(self) -> bool:
        """Check if signal is tradeable"""
        return (
            self.direction in ['BUY', 'SELL'] and
            self.entry is not None and
            self.stop_loss is not None and
            self.take_profit is not None and
            self.confidence >= 50 and
            self.rr_ratio >= 1.5
        )
    
    def to_dict(self) -> Dict:
        return {
            'strategy_id': self.strategy_id,
            'direction': self.direction,
            'entry': self.entry,
            'stop_loss': self.stop_loss,
            'take_profit': self.take_profit,
            'lots': self.lots,
            'confidence': self.confidence,
            'rr_ratio': self.rr_ratio,
            'timestamp': self.timestamp.isoformat(),
            'reasoning': self.reasoning,
            'grade_score': self.grade_score
        }


class BaseStrategy(ABC):
    """Abstract base class for all strategies"""
    
    def __init__(self, strategy_id: str, risk_per_trade: float = 0.003):
        self.strategy_id = strategy_id
        self.risk_per_trade = risk_per_trade
        self.trades_today = 0
        self.last_trade_date = None
        self.enabled = True
    
    @abstractmethod
    def on_tick(self, df: pd.DataFrame, current_price: float) -> Optional[StrategySignal]:
        """Main strategy logic - must be implemented by subclass"""
        pass
    
    def reset_daily(self):
        """Reset daily counters"""
        today = datetime.utcnow().date()
        if self.last_trade_date != today:
            self.trades_today = 0
            self.last_trade_date = today
    
    def can_trade(self) -> Tuple[bool, str]:
        """Check if strategy can trade (daily cap enforcement)"""
        self.reset_daily()
        
        if not self.enabled:
            return False, f"Strategy {self.strategy_id} disabled"
        
        if self.trades_today >= 2:
            return False, f"Daily trade cap reached (2/2)"
        
        return True, "OK"
    
    def increment_trade_count(self):
        """Increment daily trade counter"""
        self.trades_today += 1


# ============================================================================
# STRATEGY 1: NQ ORB (Nasdaq-100 Opening Range Breakout)
# ============================================================================

class StrategyNQORB(BaseStrategy):
    """
    NQ_ORBV2 Logic Ported to Python
    
    Rules from MQL5:
    - 15-minute Opening Range Breakout (ORB)
    - Session: NY Standard Time (9:30 AM open)
    - Risk: 0.5% per trade
    - Entry: Limit orders at ORB high/low retest with 1.5-point buffer
    - Exit: TP1 at 1:1 RR (50% close → SL to BE), TP2 at 1:2.2 RR
    - Filters: VWAP alignment, EMA20/50 trend, RVOL ≥ 1.4×, pre-market range ≤ 40 pts
    """
    
    def __init__(self, risk_per_trade: float = 0.005):
        super().__init__('NQ_ORB', risk_per_trade)
        
        # Strategy-specific parameters
        self.orb_minutes = 15
        self.entry_buffer_points = 1.5
        self.min_rvol = 1.4
        self.max_premarket_range = 40.0
        self.ema_fast = 20
        self.ema_slow = 50
        
        # State
        self.orb_high = None
        self.orb_low = None
        self.orb_calculated = False
        self.session_open_time = None
    
    def _calculate_ema(self, series: pd.Series, period: int) -> pd.Series:
        """Calculate EMA"""
        return series.ewm(span=period, adjust=False).mean()
    
    def _calculate_vwap(self, df: pd.DataFrame) -> pd.Series:
        """Calculate VWAP"""
        typical_price = (df['high'] + df['low'] + df['close']) / 3
        volume = df.get('volume', pd.Series([1] * len(df)))
        vwap = (typical_price * volume).cumsum() / volume.cumsum()
        return vwap
    
    def _is_ny_session(self, dt: datetime) -> bool:
        """Check if within NY trading session (9:30 AM - 4:00 PM ET)"""
        # Simplified - would use proper timezone conversion in production
        hour_utc = dt.hour
        return 14 <= hour_utc <= 20  # Approximate NY session in UTC
    
    def _check_premarket_range(self, df: pd.DataFrame) -> Tuple[bool, float]:
        """Check if pre-market range is within limits (≤ 40 points)"""
        if len(df) < 20:
            return False, 0.0
        
        # Get pre-market candles (before 9:30 AM)
        premarket = df.iloc[-20:-5]  # Approximation
        range_pts = premarket['high'].max() - premarket['low'].max()
        
        return range_pts <= self.max_premarket_range, range_pts
    
    def on_tick(self, df: pd.DataFrame, current_price: float) -> Optional[StrategySignal]:
        """
        NQ ORB Strategy Logic
        
        Entry Conditions:
        1. ORB calculated (first 15 min of NY session)
        2. Price breaks above/below ORB with buffer
        3. VWAP alignment (long: price > VWAP, short: price < VWAP)
        4. EMA20 > EMA50 for longs, EMA20 < EMA50 for shorts
        5. RVOL ≥ 1.4
        6. Pre-market range ≤ 40 points
        """
        if not self.can_trade()[0]:
            return None
        
        if len(df) < 50:
            return None
        
        # Check session
        current_time = datetime.utcnow()
        if not self._is_ny_session(current_time):
            return None
        
        # Calculate indicators
        ema20 = self._calculate_ema(df['close'], self.ema_fast)
        ema50 = self._calculate_ema(df['close'], self.ema_slow)
        vwap = self._calculate_vwap(df)
        
        current_ema20 = ema20.iloc[-1]
        current_ema50 = ema50.iloc[-1]
        current_vwap = vwap.iloc[-1]
        
        # Calculate ORB (high/low of first 15 minutes)
        if not self.orb_calculated:
            # Find session open (simplified)
            session_start_idx = max(0, len(df) - 10)  # Approximation
            orb_candles = df.iloc[session_start_idx:min(session_start_idx + 4, len(df))]
            
            self.orb_high = orb_candles['high'].max()
            self.orb_low = orb_candles['low'].min()
            self.orb_calculated = True
        
        if self.orb_high is None or self.orb_low is None:
            return None
        
        # Check pre-market range filter
        premaket_ok, premaket_range = self._check_premarket_range(df)
        if not premaket_ok:
            return None
        
        # Calculate RVOL (simplified - would use volume profile in production)
        avg_volume = df['volume'].rolling(20).mean().iloc[-1]
        current_volume = df['volume'].iloc[-1]
        rvol = current_volume / avg_volume if avg_volume > 0 else 0
        
        if rvol < self.min_rvol:
            return None
        
        # LONG Setup
        long_signal = None
        if (current_price > self.orb_high + self.entry_buffer_points and
            current_price > current_vwap and
            current_ema20 > current_ema50):
            
            risk = current_price - self.orb_low
            reward = risk * 2.2
            tp = current_price + reward
            sl = self.orb_low
            
            rr = reward / risk if risk > 0 else 0
            
            long_signal = StrategySignal(
                strategy_id=self.strategy_id,
                direction='BUY',
                entry=current_price,
                stop_loss=sl,
                take_profit=tp,
                confidence=75,
                rr_ratio=rr,
                reasoning=f"NQ ORB Long | Break above {self.orb_high:.1f} + buffer | VWAP: {current_vwap:.1f} | EMA20>50 | RVOL: {rvol:.2f}"
            )
        
        # SHORT Setup
        short_signal = None
        if (current_price < self.orb_low - self.entry_buffer_points and
            current_price < current_vwap and
            current_ema20 < current_ema50):
            
            risk = self.orb_high - current_price
            reward = risk * 2.2
            tp = current_price - reward
            sl = self.orb_high
            
            rr = reward / risk if risk > 0 else 0
            
            short_signal = StrategySignal(
                strategy_id=self.strategy_id,
                direction='SELL',
                entry=current_price,
                stop_loss=sl,
                take_profit=tp,
                confidence=75,
                rr_ratio=rr,
                reasoning=f"NQ ORB Short | Break below {self.orb_low:.1f} - buffer | VWAP: {current_vwap:.1f} | EMA20<50 | RVOL: {rvol:.2f}"
            )
        
        # Return highest confidence signal
        if long_signal and short_signal:
            # Shouldn't happen, but prioritize long if both trigger
            return long_signal
        
        return long_signal or short_signal


# ============================================================================
# STRATEGY 2: GOLD PULLBACK (XAUUSD EMA + Supply/Demand)
# ============================================================================

class StrategyGoldPullback(BaseStrategy):
    """
    XAUUSD_EMA_SD_V3_Final Logic Ported to Python
    
    Rules from MQL5:
    - H1 timeframe
    - Trend filter: EMA50/200
    - Entry: Pullback to EMA50 + Supply/Demand zone confirmation
    - Zone detection: Impulse body ≥ 500 points + ATR × 1.5
    - Risk: 0.30% locked
    - SL: Zone width (200 pts) + spread buffer
    - TP: 1:2 RR
    """
    
    def __init__(self, risk_per_trade: float = 0.003):
        super().__init__('GOLD_PULLBACK', risk_per_trade)
        
        # Strategy-specific parameters
        self.ema_period_fast = 50
        self.ema_period_slow = 200
        self.min_impulse_points = 500  # Gold points ($0.01 = 1 point)
        self.atr_multiplier = 1.5
        self.zone_width_default = 200  # Points
        self.spread_buffer_multiplier = 2.0
    
    def _calculate_ema(self, series: pd.Series, period: int) -> pd.Series:
        """Calculate EMA"""
        return series.ewm(span=period, adjust=False).mean()
    
    def _calculate_atr(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        """Calculate ATR"""
        high = df['high']
        low = df['low']
        close = df['close']
        
        tr1 = high - low
        tr2 = abs(high - close.shift())
        tr3 = abs(low - close.shift())
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        
        return tr.ewm(span=period, adjust=False).mean()
    
    def _detect_supply_demand_zones(self, df: pd.DataFrame, atr: pd.Series) -> List[Dict]:
        """
        Detect Supply/Demand zones based on impulse moves
        
        Criteria:
        - Impulse body ≥ 500 points
        - AND > ATR × 1.5
        - Pre-impulse opposite-color bar
        """
        zones = []
        
        if len(df) < 10:
            return zones
        
        current_atr = atr.iloc[-1]
        atr_threshold = current_atr * self.atr_multiplier
        
        for i in range(len(df) - 5, len(df)):
            candle = df.iloc[i]
            prev_candle = df.iloc[i - 1] if i > 0 else candle
            
            body = abs(candle.close - candle.open)
            body_points = body * 100  # Convert to points
            
            # Check impulse criteria
            if body_points >= self.min_impulse_points and body > atr_threshold:
                # Determine zone type
                is_bullish = candle.close > candle.open
                
                # Check pre-impulse bar (opposite color)
                if i > 0:
                    prev_is_bullish = prev_candle.close > prev_candle.open
                    
                    if is_bullish and not prev_is_bullish:
                        # Demand zone (bullish impulse after bearish bar)
                        zone = {
                            'type': 'DEMAND',
                            'top': candle.open,
                            'bottom': candle.low,
                            'strength': body_points,
                            'index': i
                        }
                        zones.append(zone)
                    
                    elif not is_bullish and prev_is_bullish:
                        # Supply zone (bearish impulse after bullish bar)
                        zone = {
                            'type': 'SUPPLY',
                            'top': candle.high,
                            'bottom': candle.close,
                            'strength': body_points,
                            'index': i
                        }
                        zones.append(zones)
        
        return zones[-5:]  # Return last 5 zones
    
    def on_tick(self, df: pd.DataFrame, current_price: float) -> Optional[StrategySignal]:
        """
        Gold Pullback Strategy Logic
        
        Entry Conditions (LONG):
        1. Price > EMA200 (uptrend)
        2. Bullish bar touching/near EMA50
        3. Valid demand zone present
        4. SL: Zone low - spread buffer
        5. TP: 1:2 RR
        
        Entry Conditions (SHORT):
        1. Price < EMA200 (downtrend)
        2. Bearish bar touching/near EMA50
        3. Valid supply zone present
        4. SL: Zone high + spread buffer
        5. TP: 1:2 RR
        """
        if not self.can_trade()[0]:
            return None
        
        if len(df) < 200:
            return None
        
        # Calculate indicators
        ema50 = self._calculate_ema(df['close'], self.ema_period_fast)
        ema200 = self._calculate_ema(df['close'], self.ema_period_slow)
        atr = self._calculate_atr(df)
        
        current_ema50 = ema50.iloc[-1]
        current_ema200 = ema200.iloc[-1]
        current_atr = atr.iloc[-1]
        
        # Detect S/D zones
        zones = self._detect_supply_demand_zones(df, atr)
        
        # Current candle
        curr_candle = df.iloc[-1]
        is_bullish = curr_candle.close > curr_candle.open
        
        # LONG Setup
        long_signal = None
        if (current_price > current_ema200 and
            is_bullish and
            abs(current_price - current_ema50) < current_atr * 0.5):  # Near EMA50
            
            # Check for demand zone
            demand_zone = next((z for z in zones if z['type'] == 'DEMAND'), None)
            
            if demand_zone:
                sl = demand_zone['bottom'] - (current_atr * self.spread_buffer_multiplier * 0.01)
                risk = current_price - sl
                reward = risk * 2.0
                tp = current_price + reward
                
                rr = reward / risk if risk > 0 else 0
                
                long_signal = StrategySignal(
                    strategy_id=self.strategy_id,
                    direction='BUY',
                    entry=current_price,
                    stop_loss=sl,
                    take_profit=tp,
                    confidence=70,
                    rr_ratio=rr,
                    reasoning=f"Gold Pullback Long | EMA50 test | Demand zone @ {demand_zone['bottom']:.2f} | ATR: {current_atr:.2f}"
                )
        
        # SHORT Setup
        short_signal = None
        if (current_price < current_ema200 and
            not is_bullish and
            abs(current_price - current_ema50) < current_atr * 0.5):
            
            # Check for supply zone
            supply_zone = next((z for z in zones if z['type'] == 'SUPPLY'), None)
            
            if supply_zone:
                sl = supply_zone['top'] + (current_atr * self.spread_buffer_multiplier * 0.01)
                risk = sl - current_price
                reward = risk * 2.0
                tp = current_price - reward
                
                rr = reward / risk if risk > 0 else 0
                
                short_signal = StrategySignal(
                    strategy_id=self.strategy_id,
                    direction='SELL',
                    entry=current_price,
                    stop_loss=sl,
                    take_profit=tp,
                    confidence=70,
                    rr_ratio=rr,
                    reasoning=f"Gold Pullback Short | EMA50 test | Supply zone @ {supply_zone['top']:.2f} | ATR: {current_atr:.2f}"
                )
        
        return long_signal or short_signal


# ============================================================================
# STRATEGY 3: GRADING BOT (7-Factor Quantitative Grading System)
# ============================================================================

class StrategyGradingBot(BaseStrategy):
    """
    BuySell_Bot_V2_Final Logic Ported to Python
    
    Rules from MQL5:
    - SMA cross + RSI momentum with 7-factor grading system
    - Min grade: 55/100 to trade
    - 7 Factors:
      1. RSI Momentum (0-20 pts)
      2. SMA Proximity (0-20 pts)
      3. ATR Environment (0-15 pts)
      4. Bar Body Quality (0-15 pts)
      5. Volume Confirmation (0-10 pts)
      6. Trend Alignment (0-10 pts)
      7. Session Quality (0-10 pts)
    - SL: ATR(14) × 1.5 + spread buffer
    - TP: Configurable RR (default 1:2)
    """
    
    def __init__(self, risk_per_trade: float = 0.003, min_grade: int = 55):
        super().__init__('GRADING_BOT', risk_per_trade)
        
        # Strategy-specific parameters
        self.sma_period = 20
        self.rsi_period = 14
        self.atr_period = 14
        self.min_grade = min_grade
        self.volume_baseline = 1000
        self.rr_target = 2.0
    
    def _calculate_sma(self, series: pd.Series, period: int) -> pd.Series:
        """Calculate SMA"""
        return series.rolling(window=period).mean()
    
    def _calculate_rsi(self, series: pd.Series, period: int = 14) -> pd.Series:
        """Calculate RSI"""
        delta = series.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        
        rs = gain / loss
        return 100 - (100 / (1 + rs))
    
    def _calculate_atr(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        """Calculate ATR"""
        high = df['high']
        low = df['low']
        close = df['close']
        
        tr1 = high - low
        tr2 = abs(high - close.shift())
        tr3 = abs(low - close.shift())
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        
        return tr.rolling(window=period).mean()
    
    def _calculate_grade(self, df: pd.DataFrame, direction: str) -> Tuple[int, Dict]:
        """
        Calculate 7-factor grade (0-100)
        
        Returns:
            Tuple[int, Dict]: (total_grade, factor_breakdown)
        """
        factors = {}
        
        # Factor 1: RSI Momentum (0-20 pts)
        rsi = self._calculate_rsi(df['close'], self.rsi_period).iloc[-1]
        if np.isnan(rsi):
            rsi = 50
        
        if direction == 'BUY':
            if rsi > 60:
                factors['rsi'] = 20
            elif rsi > 50:
                factors['rsi'] = 15
            elif rsi > 40:
                factors['rsi'] = 8
            else:
                factors['rsi'] = 0
        else:  # SELL
            if rsi < 40:
                factors['rsi'] = 20
            elif rsi < 50:
                factors['rsi'] = 15
            elif rsi < 60:
                factors['rsi'] = 8
            else:
                factors['rsi'] = 0
        
        # Factor 2: SMA Proximity (0-20 pts)
        sma = self._calculate_sma(df['close'], self.sma_period).iloc[-1]
        current_price = df['close'].iloc[-1]
        distance_pct = abs(current_price - sma) / sma * 100
        
        if distance_pct < 0.1:
            factors['sma_proximity'] = 20  # Tight breakout
        elif distance_pct < 0.3:
            factors['sma_proximity'] = 15
        elif distance_pct < 0.5:
            factors['sma_proximity'] = 10
        else:
            factors['sma_proximity'] = 5
        
        # Factor 3: ATR Environment (0-15 pts)
        atr = self._calculate_atr(df, self.atr_period).iloc[-1]
        avg_atr = self._calculate_atr(df, self.atr_period).rolling(50).mean().iloc[-1]
        
        if np.isnan(atr) or np.isnan(avg_atr) or avg_atr == 0:
            factors['atr_env'] = 10
        else:
            atr_ratio = atr / avg_atr
            if 1.0 <= atr_ratio <= 2.0:
                factors['atr_env'] = 15  # Optimal volatility
            elif 0.7 <= atr_ratio < 1.0 or 2.0 < atr_ratio <= 3.0:
                factors['atr_env'] = 10
            else:
                factors['atr_env'] = 5
        
        # Factor 4: Bar Body Quality (0-15 pts)
        curr_candle = df.iloc[-1]
        body = abs(curr_candle.close - curr_candle.open)
        total_range = curr_candle.high - curr_candle.low
        
        if total_range == 0:
            factors['bar_body'] = 0
        else:
            body_ratio = body / total_range
            if body_ratio > 0.7:
                factors['bar_body'] = 15  # Strong directional bar
            elif body_ratio > 0.5:
                factors['bar_body'] = 10
            elif body_ratio > 0.3:
                factors['bar_body'] = 5
            else:
                factors['bar_body'] = 0
        
        # Factor 5: Volume Confirmation (0-10 pts)
        volume = df['volume'].iloc[-1]
        if volume > self.volume_baseline * 1.5:
            factors['volume'] = 10
        elif volume > self.volume_baseline:
            factors['volume'] = 7
        elif volume > self.volume_baseline * 0.8:
            factors['volume'] = 5
        else:
            factors['volume'] = 2
        
        # Factor 6: Trend Alignment (0-10 pts)
        sma200 = self._calculate_sma(df['close'], 200).iloc[-1]
        
        if direction == 'BUY' and current_price > sma200:
            factors['trend'] = 10
        elif direction == 'SELL' and current_price < sma200:
            factors['trend'] = 10
        elif direction == 'BUY' and current_price > sma:
            factors['trend'] = 5
        elif direction == 'SELL' and current_price < sma:
            factors['trend'] = 5
        else:
            factors['trend'] = 0
        
        # Factor 7: Session Quality (0-10 pts)
        current_hour = datetime.utcnow().hour
        # London/NY overlap (13:00-16:00 UTC) = best
        if 13 <= current_hour <= 16:
            factors['session'] = 10
        # London session (7:00-16:00 UTC) or NY session (13:00-20:00 UTC)
        elif (7 <= current_hour <= 16) or (13 <= current_hour <= 20):
            factors['session'] = 7
        else:
            factors['session'] = 3
        
        # Total grade
        total = sum(factors.values())
        
        return total, factors
    
    def on_tick(self, df: pd.DataFrame, current_price: float) -> Optional[StrategySignal]:
        """
        Grading Bot Strategy Logic
        
        Entry Conditions:
        1. SMA cross detected (price crosses above/below SMA20)
        2. RSI confirms (RSI > 50 for buys, < 50 for sells)
        3. Grade score ≥ 55
        """
        if not self.can_trade()[0]:
            return None
        
        if len(df) < 200:
            return None
        
        # Calculate indicators
        sma = self._calculate_sma(df['close'], self.sma_period).iloc[-1]
        sma_prev = self._calculate_sma(df['close'], self.sma_period).iloc[-2]
        rsi = self._calculate_rsi(df['close'], self.rsi_period).iloc[-1]
        atr = self._calculate_atr(df, self.atr_period).iloc[-1]
        
        prev_price = df['close'].iloc[-2]
        
        # Detect SMA cross
        cross_above = prev_price <= sma_prev and current_price > sma
        cross_below = prev_price >= sma_prev and current_price < sma
        
        signal = None
        
        # BUY Setup
        if cross_above and rsi > 50:
            grade, factors = self._calculate_grade(df, 'BUY')
            
            if grade >= self.min_grade:
                sl = current_price - (atr * 1.5)
                risk = current_price - sl
                reward = risk * self.rr_target
                tp = current_price + reward
                
                rr = reward / risk if risk > 0 else 0
                
                signal = StrategySignal(
                    strategy_id=self.strategy_id,
                    direction='BUY',
                    entry=current_price,
                    stop_loss=sl,
                    take_profit=tp,
                    confidence=min(100, grade),
                    rr_ratio=rr,
                    grade_score=grade,
                    reasoning=f"Grading Bot Long | Grade: {grade}/100 | SMA cross + RSI {rsi:.1f} | Factors: {factors}"
                )
        
        # SELL Setup
        elif cross_below and rsi < 50:
            grade, factors = self._calculate_grade(df, 'SELL')
            
            if grade >= self.min_grade:
                sl = current_price + (atr * 1.5)
                risk = sl - current_price
                reward = risk * self.rr_target
                tp = current_price - reward
                
                rr = reward / risk if risk > 0 else 0
                
                signal = StrategySignal(
                    strategy_id=self.strategy_id,
                    direction='SELL',
                    entry=current_price,
                    stop_loss=sl,
                    take_profit=tp,
                    confidence=min(100, grade),
                    rr_ratio=rr,
                    grade_score=grade,
                    reasoning=f"Grading Bot Short | Grade: {grade}/100 | SMA cross + RSI {rsi:.1f} | Factors: {factors}"
                )
        
        return signal
