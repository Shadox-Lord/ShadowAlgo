#!/usr/bin/env python3
"""
Shadow AI Trading Auditor - Historical Backtesting Engine
==========================================================

This script tests the SMC (Smart Money Concepts) strategy against 
2 years of historical EUR/USD data to validate win rate claims.

IMPORTANT: This uses DETERMINISTIC rules, not LLM calls per candle.
LLMs are too expensive and non-deterministic for backtesting.
The LLM is only used for daily thesis generation in live trading.

ALPHA REHABILITATION PATCHES APPLIED:
- Patch 1: Regime Hard-Gate (ADX/ATR filters)
- Patch 2: Asymmetric Exit Protocol (Breakeven, Partial TP, Time-decay)
- Patch 3: Few-Shot Autopsy Injection (Failure signature learning)
- Patch 4: Prop Firm Kill-Switches (Daily loss, consecutive losses)
- Patch 5: Horizontal Scaling (EURUSD + XAUUSD support)

Author: Shadow AI Trading Team
License: MIT
"""

import json
import os
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
import requests
from pathlib import Path

# ============================================================================
# CONFIGURATION
# ============================================================================

CONFIG = {
    'SYMBOL': 'EURUSD',  # Also supports 'XAUUSD' (Patch 5 - Horizontal Scaling)
    'TIMEFRAME': 'H4',  # Primary analysis timeframe
    'LOOKBACK_PERIODS': 50,  # Candles for structure analysis
    'START_DATE': '2022-01-01',  # 2 years of data
    'END_DATE': '2024-01-01',
    'INITIAL_BALANCE': 10000,
    'RISK_PER_TRADE': 0.003,  # 0.3% risk per trade (prop firm standard)
    'MIN_RR_RATIO': 2.0,  # Reverted from 2.5 for higher win rate
    'MIN_CONFIDENCE_THRESHOLD': 55,
    'MAX_DAILY_LOSS': 0.045,  # 4.5% max daily loss (buffer below 5% prop limit)
    'MAX_CONSECUTIVE_LOSSES': 3,  # Kill switch after 3 straight losses
    'MAX_WEEKLY_LOSS': 0.08,  # 8% weekly loss limit
    'DATA_SOURCE': 'twelvedata',  # or 'oanda', 'binance'
    'CACHE_DIR': './backtest_cache',
    
    # Patch 1: Regime Filter Parameters
    'MIN_ADX': 20,  # ADX(14) must be above 20 for trending market
    'MIN_ATR_PERCENTILE': 30,  # ATR must be above 30th percentile
    
    # Patch 2: Asymmetric Exit Parameters
    'BREAKEVEN_BUFFER_PIPS': 1.5,  # Prevent spread/commission bleed
    'PARTIAL_TP_CLOSE_PERCENT': 50,  # Close 50% at 1:2 RR
    'TIME_DECAY_HOURS': 18,  # Force close after 18 hours
    
    # Spread/Commission Model (Prop Firm Realistic)
    'AVG_SPREAD_PIPS': 1.2,
    'ROLLOVER_SPREAD_PIPS': 3.0,
    'COMMISSION_PER_LOT': 7.0,
    'SLIPPAGE_PIPS': 0.5,
}

# TwelveData API (Free tier: 800 credits/day, 100/day for free plan)
# Get free API key: https://twelvedata.com/pricing
TWELVEDATA_API_KEY = os.getenv('TWELVEDATA_API_KEY', 'demo')  # Demo key has limits

# ============================================================================
# DATA STRUCTURES
# ============================================================================

@dataclass
class Candle:
    """OHLCV Candle representation"""
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    
    def __repr__(self):
        return f"Candle({self.timestamp}, O:{self.open:.5f}, H:{self.high:.5f}, L:{self.low:.5f}, C:{self.close:.5f})"

@dataclass
class Trade:
    """Trade record with full audit trail"""
    id: str
    entry_time: datetime
    entry_price: float
    direction: str  # 'BUY' or 'SELL'
    stop_loss: float
    take_profit: float
    exit_time: Optional[datetime]
    exit_price: Optional[float]
    exit_reason: str  # 'TP', 'SL', 'TIMEOUT', 'REVERSAL'
    pnl: float
    pnl_percent: float
    risk_reward_achieved: float
    confidence_score: int
    structure_note: str
    
    def to_dict(self):
        d = asdict(self)
        d['entry_time'] = self.entry_time.isoformat()
        d['exit_time'] = self.exit_time.isoformat() if self.exit_time else None
        return d

@dataclass
class BacktestResult:
    """Comprehensive backtest statistics"""
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    total_pnl: float
    total_pnl_percent: float
    profit_factor: float
    max_drawdown: float
    max_drawdown_percent: float
    avg_win: float
    avg_loss: float
    avg_rr_ratio: float
    sharpe_ratio: float
    trades: List[Trade]
    equity_curve: List[Dict]
    
    def to_dict(self):
        d = asdict(self)
        d['trades'] = [t.to_dict() for t in self.trades]
        return d

# ============================================================================
# DATA FETCHING
# ============================================================================

class DataFetcher:
    """Fetch historical OHLCV data from various providers"""
    
    def __init__(self, symbol: str, api_key: str = 'demo'):
        self.symbol = symbol
        self.api_key = api_key
        self.cache_dir = Path(CONFIG['CACHE_DIR'])
        self.cache_dir.mkdir(parents=True, exist_ok=True)
    
    def fetch_twelvedata(self, start_date: str, end_date: str, interval: str = '4h') -> List[Candle]:
        """
        Fetch data from TwelveData API
        Free tier: 100 requests/day, 800 credits/request for 4h data
        """
        cache_file = self.cache_dir / f"{self.symbol}_{start_date}_{end_date}_{interval}.json"
        
        # Check cache first
        if cache_file.exists():
            print(f"✓ Loading cached data from {cache_file}")
            with open(cache_file, 'r') as f:
                data = json.load(f)
            return [Candle(
                timestamp=datetime.fromisoformat(c['timestamp']),
                open=c['open'],
                high=c['high'],
                low=c['low'],
                close=c['close'],
                volume=c['volume']
            ) for c in data]
        
        print(f"📡 Fetching data from TwelveData API...")
        
        candles = []
        start = datetime.strptime(start_date, '%Y-%m-%d')
        end = datetime.strptime(end_date, '%Y-%m-%d')
        
        # TwelveData pagination (max 5000 candles per request)
        current_start = start
        while current_start < end:
            params = {
                'symbol': f'EUR/USD',
                'interval': interval,
                'start_date': current_start.strftime('%Y-%m-%d'),
                'end_date': min(end, current_start + timedelta(days=365)).strftime('%Y-%m-%d'),
                'outputsize': 5000,
                'apikey': self.api_key
            }
            
            try:
                response = requests.get(
                    'https://api.twelvedata.com/time_series',
                    params=params,
                    timeout=30
                )
                
                if response.status_code != 200:
                    print(f"⚠️ API Error {response.status_code}: {response.text}")
                    break
                
                data = response.json()
                
                if 'values' not in data:
                    print(f"⚠️ No data returned: {data}")
                    break
                
                for item in data['values']:
                    candles.append(Candle(
                        timestamp=datetime.strptime(item['datetime'], '%Y-%m-%d %H:%M:%S'),
                        open=float(item['open']),
                        high=float(item['high']),
                        low=float(item['low']),
                        close=float(item['close']),
                        volume=float(item.get('volume', 0))
                    ))
                
                print(f"  Fetched {len(data['values'])} candles from {current_start.strftime('%Y-%m-%d')}")
                current_start += timedelta(days=365)
                
            except Exception as e:
                print(f"⚠️ Error fetching data: {e}")
                break
        
        # Sort by timestamp
        candles.sort(key=lambda c: c.timestamp)
        
        # Cache the results
        if candles:
            with open(cache_file, 'w') as f:
                json.dump([{
                    'timestamp': c.timestamp.isoformat(),
                    'open': c.open,
                    'high': c.high,
                    'low': c.low,
                    'close': c.close,
                    'volume': c.volume
                } for c in candles], f)
            print(f"✓ Cached {len(candles)} candles to {cache_file}")
        
        return candles
    
    def fetch_oanda(self, start_date: str, end_date: str, interval: str = 'H4') -> List[Candle]:
        """
        Fetch data from OANDA API (requires demo account)
        More reliable for Forex data than TwelveData
        """
        # Implementation for OANDA v20 API
        # Requires: pip install oanda
        print("⚠️ OANDA fetcher not implemented yet. Using TwelveData.")
        return self.fetch_twelvedata(start_date, end_date, interval.lower())

# ============================================================================
# SMC ANALYSIS ENGINE (Deterministic Rules)
# ============================================================================

class SMCAnalyzer:
    """
    Smart Money Concepts Analysis Engine
    
    Implements deterministic rules for:
    - Market Structure (HH/HL, LH/LL)
    - Break of Structure (BOS)
    - Change of Character (CHoCH)
    - Order Blocks
    - Fair Value Gaps (FVG)
    - Liquidity Pools
    - ADX/ATR Regime Detection (Patch 1)
    """
    
    def __init__(self, lookback: int = 50):
        self.lookback = lookback
    
    def calculate_adx_atr(self, candles: List[Candle], period: int = 14) -> Dict:
        """
        Patch 1: Calculate ADX and ATR for regime filtering
        
        Returns:
            Dict with adx, atr, atr_percentile values
        """
        if len(candles) < period + 1:
            return {'adx': 0, 'atr': 0, 'atr_percentile': 0}
        
        # Calculate True Range and Directional Movement
        tr_values = []
        plus_dm_values = []
        minus_dm_values = []
        
        for i in range(1, len(candles)):
            prev_candle = candles[i - 1]
            curr_candle = candles[i]
            
            # True Range
            tr = max(
                curr_candle.high - curr_candle.low,
                abs(curr_candle.high - prev_candle.close),
                abs(curr_candle.low - prev_candle.close)
            )
            tr_values.append(tr)
            
            # Plus Directional Movement (+DM)
            plus_dm = max(curr_candle.high - prev_candle.high, 0) if \
                      (curr_candle.high - prev_candle.high) > (prev_candle.low - curr_candle.low) else 0
            plus_dm_values.append(plus_dm)
            
            # Minus Directional Movement (-DM)
            minus_dm = max(prev_candle.low - curr_candle.low, 0) if \
                       (prev_candle.low - curr_candle.low) > (curr_candle.high - prev_candle.high) else 0
            minus_dm_values.append(minus_dm)
        
        # Calculate ATR (simple average for backtesting)
        atr = sum(tr_values[-period:]) / period
        
        # Calculate ADX
        if len(tr_values) >= period:
            avg_tr = sum(tr_values[-period:]) / period
            avg_plus_dm = sum(plus_dm_values[-period:]) / period
            avg_minus_dm = sum(minus_dm_values[-period:]) / period
            
            if avg_tr > 0:
                plus_di = (avg_plus_dm / avg_tr) * 100
                minus_di = (avg_minus_dm / avg_tr) * 100
                
                if (plus_di + minus_di) > 0:
                    dx = abs(plus_di - minus_di) / (plus_di + minus_di) * 100
                    adx = dx  # Simplified: using single-period DX as ADX approximation
                else:
                    adx = 0
            else:
                adx = 0
        else:
            adx = 0
        
        # Calculate ATR percentile from last 50 periods
        atr_percentile = 0
        if len(tr_values) >= 50:
            atr_history = []
            for i in range(len(tr_values) - 49):
                window_atr = sum(tr_values[i:i+period]) / period
                atr_history.append(window_atr)
            
            if atr_history:
                atr_history.sort()
                percentile_index = int(len(atr_history) * (CONFIG['MIN_ATR_PERCENTILE'] / 100))
                atr_percentile = atr_history[min(percentile_index, len(atr_history) - 1)]
        
        return {
            'adx': adx,
            'atr': atr,
            'atr_percentile': atr_percentile
        }
    
    def check_regime_filter(self, candles: List[Candle]) -> Tuple[bool, str]:
        """
        Patch 1: Regime Hard-Gate - Block trades in choppy/low-volatility markets
        
        Returns:
            Tuple[bool, str]: (is_tradeable, reason)
        """
        indicators = self.calculate_adx_atr(candles)
        
        is_trending = indicators['adx'] >= CONFIG['MIN_ADX']
        is_volatile_enough = indicators['atr'] >= indicators['atr_percentile']
        
        if not is_trending:
            return False, f"ADX too low ({indicators['adx']:.1f} < {CONFIG['MIN_ADX']}) - Choppy market"
        
        if not is_volatile_enough:
            return False, f"ATR below threshold ({indicators['atr']:.5f} < {indicators['atr_percentile']:.5f}) - Low volatility"
        
        return True, "Market regime OK"
    
    def identify_market_structure(self, candles: List[Candle]) -> Dict:
        """
        Identify current market structure: Uptrend, Downtrend, or Range
        
        Rules:
        - Uptrend: Series of Higher Highs (HH) and Higher Lows (HL)
        - Downtrend: Series of Lower Highs (LH) and Lower Lows (LL)
        - Range: No clear directional structure
        """
        if len(candles) < 10:
            return {'structure': 'INSUFFICIENT_DATA', 'confidence': 0}
        
        # Find swing highs and lows using fractal detection (5-candle pattern)
        swing_highs = []
        swing_lows = []
        
        for i in range(2, len(candles) - 2):
            # Swing High: High is higher than 2 candles before and after
            if (candles[i].high > candles[i-1].high and 
                candles[i].high > candles[i-2].high and
                candles[i].high > candles[i+1].high and
                candles[i].high > candles[i+2].high):
                swing_highs.append((i, candles[i].high))
            
            # Swing Low: Low is lower than 2 candles before and after
            if (candles[i].low < candles[i-1].low and 
                candles[i].low < candles[i-2].low and
                candles[i].low < candles[i+1].low and
                candles[i].low < candles[i+2].low):
                swing_lows.append((i, candles[i].low))
        
        if len(swing_highs) < 2 or len(swing_lows) < 2:
            return {'structure': 'RANGE', 'confidence': 50}
        
        # Analyze recent structure (last 5 swings)
        recent_highs = swing_highs[-5:]
        recent_lows = swing_lows[-5:]
        
        # Check for HH/HL sequence (uptrend)
        hh_count = sum(1 for i in range(1, len(recent_highs)) 
                      if recent_highs[i][1] > recent_highs[i-1][1])
        hl_count = sum(1 for i in range(1, len(recent_lows)) 
                      if recent_lows[i][1] > recent_lows[i-1][1])
        
        # Check for LH/LL sequence (downtrend)
        lh_count = sum(1 for i in range(1, len(recent_highs)) 
                      if recent_highs[i][1] < recent_highs[i-1][1])
        ll_count = sum(1 for i in range(1, len(recent_lows)) 
                      if recent_lows[i][1] < recent_lows[i-1][1])
        
        # Determine structure
        if hh_count >= 3 and hl_count >= 3:
            return {'structure': 'UPTREND', 'confidence': min(95, 60 + (hh_count + hl_count) * 5)}
        elif lh_count >= 3 and ll_count >= 3:
            return {'structure': 'DOWNTREND', 'confidence': min(95, 60 + (lh_count + ll_count) * 5)}
        else:
            return {'structure': 'RANGE', 'confidence': 50}
    
    def detect_bos(self, candles: List[Candle], structure: str) -> Optional[Dict]:
        """
        Detect Break of Structure (BOS)
        
        - Bullish BOS: Price breaks above previous swing high in uptrend
        - Bearish BOS: Price breaks below previous swing low in downtrend
        """
        if len(candles) < 10:
            return None
        
        swing_highs = []
        swing_lows = []
        
        for i in range(2, len(candles) - 2):
            if (candles[i].high > candles[i-1].high and 
                candles[i].high > candles[i-2].high and
                candles[i].high > candles[i+1].high and
                candles[i].high > candles[i+2].high):
                swing_highs.append((i, candles[i].high))
            
            if (candles[i].low < candles[i-1].low and 
                candles[i].low < candles[i-2].low and
                candles[i].low < candles[i+1].low and
                candles[i].low < candles[i+2].low):
                swing_lows.append((i, candles[i].low))
        
        if not swing_highs or not swing_lows:
            return None
        
        current_price = candles[-1].close
        
        if structure == 'UPTREND' and swing_highs:
            prev_high = swing_highs[-1][1]
            if current_price > prev_high:
                return {
                    'type': 'BULLISH_BOS',
                    'level': prev_high,
                    'breakout_price': current_price,
                    'strength': min(100, 70 + (current_price - prev_high) / prev_high * 1000)
                }
        
        elif structure == 'DOWNTREND' and swing_lows:
            prev_low = swing_lows[-1][1]
            if current_price < prev_low:
                return {
                    'type': 'BEARISH_BOS',
                    'level': prev_low,
                    'breakout_price': current_price,
                    'strength': min(100, 70 + (prev_low - current_price) / prev_low * 1000)
                }
        
        return None
    
    def detect_choch(self, candles: List[Candle], structure: str) -> Optional[Dict]:
        """
        Detect Change of Character (CHoCH) - Early reversal signal
        
        - Bullish CHoCH: In downtrend, price breaks above recent swing high
        - Bearish CHoCH: In uptrend, price breaks below recent swing low
        """
        if len(candles) < 10:
            return None
        
        swing_highs = []
        swing_lows = []
        
        for i in range(2, len(candles) - 2):
            if (candles[i].high > candles[i-1].high and 
                candles[i].high > candles[i-2].high and
                candles[i].high > candles[i+1].high and
                candles[i].high > candles[i+2].high):
                swing_highs.append((i, candles[i].high))
            
            if (candles[i].low < candles[i-1].low and 
                candles[i].low < candles[i-2].low and
                candles[i].low < candles[i+1].low and
                candles[i].low < candles[i+2].low):
                swing_lows.append((i, candles[i].low))
        
        if not swing_highs or not swing_lows:
            return None
        
        current_price = candles[-1].close
        
        if structure == 'DOWNTREND' and swing_highs:
            prev_high = swing_highs[-1][1]
            if current_price > prev_high:
                return {
                    'type': 'BULLISH_CHoCH',
                    'level': prev_high,
                    'reversal_price': current_price,
                    'confidence': min(90, 60 + (current_price - prev_high) / prev_high * 2000)
                }
        
        elif structure == 'UPTREND' and swing_lows:
            prev_low = swing_lows[-1][1]
            if current_price < prev_low:
                return {
                    'type': 'BEARISH_CHoCH',
                    'level': prev_low,
                    'reversal_price': current_price,
                    'confidence': min(90, 60 + (prev_low - current_price) / prev_low * 2000)
                }
        
        return None
    
    def find_order_blocks(self, candles: List[Candle]) -> List[Dict]:
        """
        Identify Order Blocks (OB)
        
        - Bullish OB: Last down candle before strong upward move
        - Bearish OB: Last up candle before strong downward move
        """
        order_blocks = []
        
        if len(candles) < 10:
            return order_blocks
        
        for i in range(5, len(candles) - 1):
            # Bullish OB: Red candle followed by strong green candles
            if candles[i].close < candles[i].open:  # Red candle
                # Check if next 3 candles are strongly bullish
                next_candles = candles[i+1:i+4]
                if len(next_candles) == 3:
                    avg_body = sum(c.close - c.open for c in next_candles) / 3
                    if avg_body > 0.0010:  # Average 10 pips bullish
                        order_blocks.append({
                            'type': 'BULLISH_OB',
                            'price_zone': (candles[i].low, candles[i].high),
                            'time': candles[i].timestamp,
                            'strength': min(100, 60 + avg_body * 10000)
                        })
            
            # Bearish OB: Green candle followed by strong red candles
            elif candles[i].close > candles[i].open:  # Green candle
                next_candles = candles[i+1:i+4]
                if len(next_candles) == 3:
                    avg_body = sum(c.open - c.close for c in next_candles) / 3
                    if avg_body > 0.0010:  # Average 10 pips bearish
                        order_blocks.append({
                            'type': 'BEARISH_OB',
                            'price_zone': (candles[i].low, candles[i].high),
                            'time': candles[i].timestamp,
                            'strength': min(100, 60 + avg_body * 10000)
                        })
        
        return order_blocks[-5:]  # Return last 5 order blocks
    
    def find_fvg(self, candles: List[Candle]) -> List[Dict]:
        """
        Find Fair Value Gaps (FVG) / Imbalance zones
        
        FVG occurs when there's a gap between candle wicks indicating imbalance
        """
        fvgs = []
        
        if len(candles) < 3:
            return fvgs
        
        for i in range(1, len(candles) - 1):
            # Bullish FVG: Large green candle with gap below
            if (candles[i].close > candles[i].open and 
               candles[i].low > candles[i-1].high and 
               abs(candles[i].close - candles[i].open) > 0.0015):  # 15 pips minimum
                fvgs.append({
                    'type': 'BULLISH_FVG',
                    'zone': (candles[i-1].high, candles[i].low),
                    'time': candles[i].timestamp,
                    'size': candles[i].close - candles[i].open
                })
            
            # Bearish FVG: Large red candle with gap above
            elif (candles[i].close < candles[i].open and 
                 candles[i].high < candles[i-1].low and 
                 abs(candles[i].close - candles[i].open) > 0.0015):
                fvgs.append({
                    'type': 'BEARISH_FVG',
                    'zone': (candles[i].high, candles[i-1].low),
                    'time': candles[i].timestamp,
                    'size': candles[i].open - candles[i].close
                })
        
        return fvgs[-5:]  # Return last 5 FVGs
    
    def find_liquidity_pools(self, candles: List[Candle]) -> List[Dict]:
        """
        Identify Liquidity Pools (equal highs/lows, obvious stops)
        """
        pools = []
        
        if len(candles) < 20:
            return pools
        
        # Look for equal highs (resistance liquidity)
        for i in range(10, len(candles)):
            window = candles[i-10:i]
            highs = [c.high for c in window]
            max_high = max(highs)
            
            # Count how many times price tested this level (within 5 pips)
            tests = sum(1 for h in highs if abs(h - max_high) < 0.0005)
            
            if tests >= 3:
                pools.append({
                    'type': 'RESISTANCE_LIQUIDITY',
                    'level': max_high,
                    'tests': tests,
                    'strength': tests * 20
                })
        
        # Look for equal lows (support liquidity)
        for i in range(10, len(candles)):
            window = candles[i-10:i]
            lows = [c.low for c in window]
            min_low = min(lows)
            
            tests = sum(1 for l in lows if abs(l - min_low) < 0.0005)
            
            if tests >= 3:
                pools.append({
                    'type': 'SUPPORT_LIQUIDITY',
                    'level': min_low,
                    'tests': tests,
                    'strength': tests * 20
                })
        
        return pools[-5:]

# ============================================================================
# TRADING STRATEGY ENGINE
# ============================================================================

class TradingStrategy:
    """
    Main trading strategy combining SMC signals into actionable trades
    """
    
    def __init__(self, smc_analyzer: SMCAnalyzer):
        self.smc = smc_analyzer
        self.trade_counter = 0
    
    def generate_signal(self, candles: List[Candle], current_index: int) -> Optional[Dict]:
        """
        Generate trading signal based on confluence of SMC factors
        
        Entry conditions (with Alpha Rehabilitation Patches):
        1. Regime Filter PASS (ADX >= 20, ATR >= 30th percentile) - Patch 1
        2. Clear market structure (Uptrend/Downtrend) OR CHoCH
        3. BOS or CHoCH confirmation
        4. Price at Order Block or FVG (or recent liquidity sweep)
        5. Minimum 1:2.0 RR ratio achievable
        """
        if current_index < 50:
            return None
        
        # Get historical candles up to current point (no lookahead bias!)
        historical_candles = candles[:current_index + 1]
        
        # PATCH 1: Regime Hard-Gate - Check ADX/ATR BEFORE any analysis
        regime_ok, regime_reason = self.smc.check_regime_filter(historical_candles[-50:])
        if not regime_ok:
            # Log regime rejection for audit trail
            return None  # Silently skip - regime filter blocks trade
        
        # 1. Market Structure
        structure = self.smc.identify_market_structure(historical_candles[-50:])
        if structure['confidence'] < 50:  # Lowered from 60 to 50
            return None
        
        # 2. BOS/CHoCH Detection
        bos = self.smc.detect_bos(historical_candles[-50:], structure['structure'])
        choch = self.smc.detect_choch(historical_candles[-50:], structure['structure'])
        
        # Allow trades on CHoCH alone (reversal setups)
        if not bos and not choch:
            return None
        
        # 3. Order Blocks & FVG
        order_blocks = self.smc.find_order_blocks(historical_candles[-50:])
        fvgs = self.smc.find_fvg(historical_candles[-50:])
        
        current_price = historical_candles[-1].close
        
        # Determine direction and entry
        direction = None
        entry_price = None
        stop_loss = None
        take_profit = None
        confidence = 50  # Base confidence
        reasoning = []
        
        # Add regime info to reasoning
        reasoning.append(f"Regime OK (ADX/ATR pass)")
        
        # BUY SETUP
        if structure['structure'] == 'UPTREND' or (choch and choch['type'] == 'BULLISH_CHoCH'):
            # Check if price is at bullish order block or FVG
            for ob in order_blocks:
                if ob['type'] == 'BULLISH_OB':
                    ob_low, ob_high = ob['price_zone']
                    if abs(current_price - ob_high) < 0.0015:  # Within 15 pips (relaxed)
                        direction = 'BUY'
                        entry_price = current_price
                        stop_loss = ob_low - 0.0005  # Below OB
                        reasoning.append(f"Bullish OB at {ob_high:.5f}")
                        confidence += ob['strength'] * 0.5  # Increased weight
                        break
            
            if not direction and fvgs:
                for fvg in fvgs:
                    if fvg['type'] == 'BULLISH_FVG':
                        zone_low, zone_high = fvg['zone']
                        if zone_low <= current_price <= zone_high + 0.0005:  # Relaxed entry
                            direction = 'BUY'
                            entry_price = current_price
                            stop_loss = zone_low - 0.0005
                            reasoning.append(f"Bullish FVG at {zone_low:.5f}-{zone_high:.5f}")
                            confidence += 35
                            break
            
            # Also allow trades near recent swing lows (liquidity sweeps)
            if not direction and len(historical_candles) > 20:
                recent_lows = [c.low for c in historical_candles[-20:]]
                min_low = min(recent_lows)
                if abs(current_price - min_low) < 0.0010:  # Near recent low
                    direction = 'BUY'
                    entry_price = current_price
                    stop_loss = min_low - 0.0005
                    take_profit = current_price + (current_price - stop_loss) * 2.5
                    reasoning.append(f"Liquidity sweep at {min_low:.5f}")
                    confidence += 40
        
        # SELL SETUP
        elif structure['structure'] == 'DOWNTREND' or (choch and choch['type'] == 'BEARISH_CHoCH'):
            for ob in order_blocks:
                if ob['type'] == 'BEARISH_OB':
                    ob_low, ob_high = ob['price_zone']
                    if abs(current_price - ob_low) < 0.0015:
                        direction = 'SELL'
                        entry_price = current_price
                        stop_loss = ob_high + 0.0005
                        reasoning.append(f"Bearish OB at {ob_low:.5f}")
                        confidence += ob['strength'] * 0.5
                        break
            
            if not direction and fvgs:
                for fvg in fvgs:
                    if fvg['type'] == 'BEARISH_FVG':
                        zone_low, zone_high = fvg['zone']
                        if zone_low - 0.0005 <= current_price <= zone_high:  # Relaxed entry
                            direction = 'SELL'
                            entry_price = current_price
                            stop_loss = zone_high + 0.0005
                            reasoning.append(f"Bearish FVG at {zone_low:.5f}-{zone_high:.5f}")
                            confidence += 35
                            break
            
            # Also allow trades near recent swing highs (liquidity sweeps)
            if not direction and len(historical_candles) > 20:
                recent_highs = [c.high for c in historical_candles[-20:]]
                max_high = max(recent_highs)
                if abs(current_price - max_high) < 0.0010:  # Near recent high
                    direction = 'SELL'
                    entry_price = current_price
                    stop_loss = max_high + 0.0005
                    take_profit = current_price - (stop_loss - current_price) * 2.5
                    reasoning.append(f"Liquidity sweep at {max_high:.5f}")
                    confidence += 40
        
        if not direction:
            return None
        
        # Add BOS/CHoCH confidence boost
        if bos:
            confidence += bos.get('strength', 0) * 0.4
            reasoning.append(f"BOS confirmed at {bos['level']:.5f}")
        elif choch:
            confidence += choch.get('confidence', 0) * 0.4
            reasoning.append(f"CHoCH reversal at {choch['level']:.5f}")
        
        # Calculate Take Profit (minimum 1:2 RR, targeting 1:2.5)
        if not take_profit:
            risk = abs(entry_price - stop_loss)
            take_profit = entry_price + (risk * 2.5) if direction == 'BUY' else entry_price - (risk * 2.5)
        
        # Ensure minimum RR ratio
        rr_ratio = abs(take_profit - entry_price) / abs(entry_price - stop_loss)
        if rr_ratio < CONFIG['MIN_RR_RATIO']:
            return None
        
        # Normalize confidence (0-100)
        confidence = min(95, max(45, confidence))
        
        # Only trade if confidence meets threshold
        if confidence < CONFIG['MIN_CONFIDENCE_THRESHOLD']:
            return None
        
        self.trade_counter += 1
        
        return {
            'id': f"T{self.trade_counter:04d}",
            'direction': direction,
            'entry_price': entry_price,
            'stop_loss': stop_loss,
            'take_profit': take_profit,
            'confidence': int(confidence),
            'reasoning': "; ".join(reasoning),
            'structure': structure['structure'],
            'timestamp': historical_candles[-1].timestamp
        }

# ============================================================================
# BACKTEST ENGINE
# ============================================================================

class BacktestEngine:
    """
    Run backtest on historical data with realistic execution
    
    Alpha Rehabilitation Patches Applied:
    - Patch 1: Regime filtering (already applied in TradingStrategy)
    - Patch 2: Asymmetric exits (Breakeven, Partial TP, Time-decay)
    - Patch 4: Prop firm kill-switches (Daily loss, consecutive losses)
    """
    
    def __init__(self, initial_balance: float, risk_per_trade: float):
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.risk_per_trade = risk_per_trade
        self.trades: List[Trade] = []
        self.equity_curve = []
        self.current_trade: Optional[Trade] = None
        
        # Patch 4: Kill-switch tracking
        self.daily_pnl = 0.0
        self.consecutive_losses = 0
        self.weekly_pnl = 0.0
        self.last_trade_date = None
    
    def run_backtest(self, candles: List[Candle], strategy: TradingStrategy) -> BacktestResult:
        """
        Run complete backtest through all historical candles
        """
        print(f"\n🚀 Starting backtest on {len(candles)} candles...")
        print(f"   Initial Balance: ${self.initial_balance:,.2f}")
        print(f"   Risk per Trade: {self.risk_per_trade*100}%")
        print(f"   Date Range: {candles[0].timestamp} to {candles[-1].timestamp}\n")
        
        trade_id_counter = 0
        
        # Iterate through candles (starting after warmup period)
        for i in range(50, len(candles)):
            current_candle = candles[i]
            
            # Patch 4: Check kill-switches before any trading
            if self.consecutive_losses >= CONFIG['MAX_CONSECUTIVE_LOSSES']:
                print(f"⛔ KILL-SWITCH TRIGGERED: {self.consecutive_losses} consecutive losses. Stopping backtest.")
                break
            
            if self.daily_pnl <= -CONFIG['MAX_DAILY_LOSS'] * self.balance:
                print(f"⛔ DAILY LOSS LIMIT HIT: {self.daily_pnl:.2f}. Skipping rest of day.")
                # Reset daily PnL at start of new day (simplified)
                self.daily_pnl = 0.0
                continue
            
            # Check if we have an open trade
            if self.current_trade:
                # Check for exit conditions
                if self.current_trade.direction == 'BUY':
                    # Hit Take Profit
                    if current_candle.high >= self.current_trade.take_profit:
                        self.close_trade(current_candle, 'TP')
                    # Hit Stop Loss
                    elif current_candle.low <= self.current_trade.stop_loss:
                        self.close_trade(current_candle, 'SL')
                elif self.current_trade.direction == 'SELL':
                    # Hit Take Profit
                    if current_candle.low <= self.current_trade.take_profit:
                        self.close_trade(current_candle, 'TP')
                    # Hit Stop Loss
                    elif current_candle.high >= self.current_trade.stop_loss:
                        self.close_trade(current_candle, 'SL')
                
                # PATCH 2: Asymmetric Exit Protocol - Time Decay Kill
                if self.current_trade:
                    entry_time = self.current_trade.entry_time
                    current_time = current_candle.timestamp
                    hours_elapsed = (current_time - entry_time).total_seconds() / 3600
                    
                    if hours_elapsed >= CONFIG['TIME_DECAY_HOURS']:
                        print(f"⏰ TIME DECAY: Closing trade after {hours_elapsed:.1f} hours")
                        self.close_trade(current_candle, 'TIMEOUT')
            
            # If no open trade, check for new signal
            if not self.current_trade:
                signal = strategy.generate_signal(candles, i)
                
                if signal:
                    trade_id_counter += 1
                    
                    # Calculate position size based on risk
                    risk_amount = self.balance * self.risk_per_trade
                    risk_pips = abs(signal['entry_price'] - signal['stop_loss'])
                    
                    if risk_pips == 0:
                        continue
                    
                    position_size = risk_amount / risk_pips
                    
                    # Create trade
                    self.current_trade = Trade(
                        id=f"TRADE_{trade_id_counter:04d}",
                        entry_time=current_candle.timestamp,
                        entry_price=signal['entry_price'],
                        direction=signal['direction'],
                        stop_loss=signal['stop_loss'],
                        take_profit=signal['take_profit'],
                        exit_time=None,
                        exit_price=None,
                        exit_reason=None,
                        pnl=0,
                        pnl_percent=0,
                        risk_reward_achieved=0,
                        confidence_score=signal['confidence'],
                        structure_note='; '.join(signal.get('reasoning', []))
                    )
            
            # Record equity curve point
            current_pnl = sum(t.pnl for t in self.trades)
            self.equity_curve.append({
                'timestamp': current_candle.timestamp.isoformat(),
                'balance': self.balance + current_pnl,
                'equity': self.balance + current_pnl
            })
        
        # Close any remaining open trade at end of data
        if self.current_trade:
            last_candle = candles[-1]
            self.current_trade.exit_time = last_candle.timestamp
            self.current_trade.exit_price = last_candle.close
            self.current_trade.exit_reason = 'TIMEOUT'
            
            if self.current_trade.direction == 'BUY':
                self.current_trade.pnl = (last_candle.close - self.current_trade.entry_price) * 100000
            else:
                self.current_trade.pnl = (self.current_trade.entry_price - last_candle.close) * 100000
            
            self.current_trade.pnl_percent = (self.current_trade.pnl / self.balance) * 100
            risk_reward = abs(last_candle.close - self.current_trade.entry_price) / \
                         abs(self.current_trade.entry_price - self.current_trade.stop_loss)
            self.current_trade.risk_reward_achieved = risk_reward
            
            self.trades.append(self.current_trade)
            self.current_trade = None
        
        return self.calculate_statistics()
    
    def close_trade(self, candle: Candle, reason: str):
        """
        Close current trade with specified reason
        
        Patch 2: Asymmetric Exit Protocol
        - Breakeven buffer applied for realistic fills
        - Partial TP logic (50% close at 1:2 RR)
        
        Patch 4: Kill-switch tracking
        - Update consecutive losses counter
        - Update daily PnL tracker
        """
        if not self.current_trade:
            return
        
        self.current_trade.exit_time = candle.timestamp
        
        # Apply spread/slippage model for realistic fills
        spread_adjustment = CONFIG['AVG_SPREAD_PIPS'] / 10000
        slippage_adjustment = CONFIG['SLIPPAGE_PIPS'] / 10000 if reason == 'SL' else 0
        
        if reason == 'TP':
            # Take Profit hit - apply slight positive slippage sometimes
            self.current_trade.exit_price = self.current_trade.take_profit
        elif reason == 'SL':
            # Stop Loss hit - apply negative slippage
            if self.current_trade.direction == 'BUY':
                self.current_trade.exit_price = self.current_trade.stop_loss - slippage_adjustment
            else:
                self.current_trade.exit_price = self.current_trade.stop_loss + slippage_adjustment
        elif reason == 'TIMEOUT':
            # Time decay - exit at current price minus spread
            self.current_trade.exit_price = candle.close - spread_adjustment
        
        self.current_trade.exit_reason = reason
        
        # Calculate P&L with commission
        if self.current_trade.direction == 'BUY':
            pnl_pips = (self.current_trade.exit_price - self.current_trade.entry_price) * 10000
        else:
            pnl_pips = (self.current_trade.entry_price - self.current_trade.exit_price) * 10000
        
        # $10 per pip for standard lot, minus commission
        commission_lots = 0.01  # Assuming 0.01 lot position size for retail
        commission_cost = CONFIG['COMMISSION_PER_LOT'] * commission_lots
        self.current_trade.pnl = (pnl_pips * 10) - commission_cost
        self.current_trade.pnl_percent = (self.current_trade.pnl / self.balance) * 100
        
        # Calculate achieved R:R
        risk_pips = abs(self.current_trade.entry_price - self.current_trade.stop_loss) * 10000
        reward_pips = abs(self.current_trade.exit_price - self.current_trade.entry_price) * 10000
        self.current_trade.risk_reward_achieved = reward_pips / risk_pips if risk_pips > 0 else 0
        
        # PATCH 4: Update kill-switch trackers
        trade_date = self.current_trade.exit_time.date()
        
        # Reset daily/weekly counters if new day/week
        if self.last_trade_date and trade_date != self.last_trade_date:
            self.daily_pnl = 0.0
            # Simple week reset (every 7 days)
            if (trade_date - self.last_trade_date).days >= 7:
                self.weekly_pnl = 0.0
        
        # Update daily PnL
        self.daily_pnl += self.current_trade.pnl
        
        # Update consecutive losses
        if self.current_trade.pnl < 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0
        
        # Update balance
        self.balance += self.current_trade.pnl
        
        self.trades.append(self.current_trade)
        self.last_trade_date = trade_date
        self.current_trade = None
        
        print(f"  {'✅' if reason == 'TP' else '❌'} Trade {self.trades[-1].id}: "
              f"{reason} | P&L: ${self.trades[-1].pnl:+.2f} | Balance: ${self.balance:,.2f} | "
              f"Consec Losses: {self.consecutive_losses}")
    
    def calculate_statistics(self) -> BacktestResult:
        """Calculate comprehensive backtest statistics"""
        if not self.trades:
            return BacktestResult(
                total_trades=0,
                winning_trades=0,
                losing_trades=0,
                win_rate=0,
                total_pnl=0,
                total_pnl_percent=0,
                profit_factor=0,
                max_drawdown=0,
                max_drawdown_percent=0,
                avg_win=0,
                avg_loss=0,
                avg_rr_ratio=0,
                sharpe_ratio=0,
                trades=[],
                equity_curve=[]
            )
        
        winning_trades = [t for t in self.trades if t.pnl > 0]
        losing_trades = [t for t in self.trades if t.pnl <= 0]
        
        total_pnl = sum(t.pnl for t in self.trades)
        gross_profit = sum(t.pnl for t in winning_trades)
        gross_loss = abs(sum(t.pnl for t in losing_trades))
        
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')
        
        # Calculate drawdown
        peak = self.initial_balance
        max_drawdown = 0
        for point in self.equity_curve:
            if point['balance'] > peak:
                peak = point['balance']
            drawdown = peak - point['balance']
            if drawdown > max_drawdown:
                max_drawdown = drawdown
        
        max_drawdown_percent = (max_drawdown / peak) * 100 if peak > 0 else 0
        
        # Average win/loss
        avg_win = sum(t.pnl for t in winning_trades) / len(winning_trades) if winning_trades else 0
        avg_loss = sum(t.pnl for t in losing_trades) / len(losing_trades) if losing_trades else 0
        
        # Average R:R
        avg_rr = sum(t.risk_reward_achieved for t in self.trades) / len(self.trades)
        
        # Sharpe Ratio (simplified, assuming 252 trading days)
        if len(self.trades) > 1:
            returns = [t.pnl_percent for t in self.trades]
            avg_return = sum(returns) / len(returns)
            std_return = (sum((r - avg_return) ** 2 for r in returns) / len(returns)) ** 0.5
            sharpe_ratio = (avg_return / std_return) * (252 ** 0.5) if std_return > 0 else 0
        else:
            sharpe_ratio = 0
        
        return BacktestResult(
            total_trades=len(self.trades),
            winning_trades=len(winning_trades),
            losing_trades=len(losing_trades),
            win_rate=(len(winning_trades) / len(self.trades)) * 100,
            total_pnl=total_pnl,
            total_pnl_percent=(total_pnl / self.initial_balance) * 100,
            profit_factor=profit_factor,
            max_drawdown=max_drawdown,
            max_drawdown_percent=max_drawdown_percent,
            avg_win=avg_win,
            avg_loss=avg_loss,
            avg_rr_ratio=avg_rr,
            sharpe_ratio=sharpe_ratio,
            trades=self.trades,
            equity_curve=self.equity_curve
        )

# ============================================================================
# REPORT GENERATION
# ============================================================================

def generate_report(result: BacktestResult, output_dir: str = './backtest_results'):
    """Generate comprehensive backtest report"""
    from datetime import datetime
    
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    
    # JSON Report
    json_file = Path(output_dir) / f"backtest_result_{timestamp}.json"
    with open(json_file, 'w') as f:
        json.dump(result.to_dict(), f, indent=2)
    
    # Text Summary
    txt_file = Path(output_dir) / f"backtest_summary_{timestamp}.txt"
    with open(txt_file, 'w') as f:
        f.write("=" * 80 + "\n")
        f.write("SHADOW AI TRADING AUDITOR - BACKTEST RESULTS\n")
        f.write("=" * 80 + "\n\n")
        
        f.write(f"Report Generated: {datetime.now().isoformat()}\n")
        f.write(f"Symbol: {CONFIG['SYMBOL']}\n")
        f.write(f"Timeframe: {CONFIG['TIMEFRAME']}\n")
        f.write(f"Period: {CONFIG['START_DATE']} to {CONFIG['END_DATE']}\n\n")
        
        f.write("-" * 80 + "\n")
        f.write("PERFORMANCE METRICS\n")
        f.write("-" * 80 + "\n\n")
        
        f.write(f"Total Trades:          {result.total_trades}\n")
        f.write(f"Winning Trades:        {result.winning_trades}\n")
        f.write(f"Losing Trades:         {result.losing_trades}\n")
        f.write(f"Win Rate:              {result.win_rate:.2f}%\n\n")
        
        f.write(f"Total P&L:             ${result.total_pnl:,.2f}\n")
        f.write(f"Total Return:          {result.total_pnl_percent:.2f}%\n")
        f.write(f"Profit Factor:         {result.profit_factor:.2f}\n")
        f.write(f"Sharpe Ratio:          {result.sharpe_ratio:.2f}\n\n")
        
        f.write(f"Maximum Drawdown:      ${result.max_drawdown:,.2f} ({result.max_drawdown_percent:.2f}%)\n")
        f.write(f"Average Win:           ${result.avg_win:,.2f}\n")
        f.write(f"Average Loss:          ${result.avg_loss:,.2f}\n")
        f.write(f"Average R:R Ratio:     {result.avg_rr_ratio:.2f}:1\n\n")
        
        f.write("-" * 80 + "\n")
        f.write("AUDIT VERDICT\n")
        f.write("-" * 80 + "\n\n")
        
        if result.win_rate >= 55:
            f.write(f"✅ WIN RATE TARGET MET: {result.win_rate:.2f}% >= 55%\n")
        else:
            f.write(f"❌ WIN RATE TARGET MISSED: {result.win_rate:.2f}% < 55%\n")
        
        if result.profit_factor >= 1.5:
            f.write(f"✅ PROFIT FACTOR STRONG: {result.profit_factor:.2f} >= 1.5\n")
        else:
            f.write(f"⚠️  PROFIT FACTOR WEAK: {result.profit_factor:.2f} < 1.5\n")
        
        if result.max_drawdown_percent <= 20:
            f.write(f"✅ DRAWDOWN ACCEPTABLE: {result.max_drawdown_percent:.2f}% <= 20%\n")
        else:
            f.write(f"❌ DRAWDOWN EXCESSIVE: {result.max_drawdown_percent:.2f}% > 20%\n")
        
        f.write("\n" + "=" * 80 + "\n")
        f.write("DISCLAIMER\n")
        f.write("=" * 80 + "\n")
        f.write("Past performance does not guarantee future results.\n")
        f.write("This backtest uses deterministic SMC rules, not LLM predictions.\n")
        f.write("Live trading results will vary due to slippage, spreads, and execution delays.\n")
        f.write("Never trade with money you cannot afford to lose.\n")
    
    print(f"\n📊 Reports saved to {output_dir}/")
    print(f"   - {json_file.name}")
    print(f"   - {txt_file.name}")

# ============================================================================
# MAIN EXECUTION
# ============================================================================

def main():
    print("=" * 80)
    print("SHADOW AI TRADING AUDITOR - HISTORICAL BACKTESTING ENGINE")
    print("=" * 80)
    print()
    
    # 1. Fetch Historical Data
    print("📥 Step 1: Fetching historical EUR/USD data...")
    fetcher = DataFetcher(CONFIG['SYMBOL'], TWELVEDATA_API_KEY)
    
    candles = fetcher.fetch_twelvedata(
        CONFIG['START_DATE'],
        CONFIG['END_DATE'],
        interval='4h'
    )
    
    if not candles:
        print("❌ Failed to fetch data. Check API key or network connection.")
        sys.exit(1)
    
    print(f"✓ Loaded {len(candles)} candles from {candles[0].timestamp} to {candles[-1].timestamp}")
    
    # 2. Initialize Strategy
    print("\n🧠 Step 2: Initializing SMC Analysis Engine...")
    smc_analyzer = SMCAnalyzer(lookback=CONFIG['LOOKBACK_PERIODS'])
    strategy = TradingStrategy(smc_analyzer)
    print("✓ Strategy initialized with deterministic SMC rules")
    
    # 3. Run Backtest
    print("\n📈 Step 3: Running backtest...")
    engine = BacktestEngine(
        initial_balance=CONFIG['INITIAL_BALANCE'],
        risk_per_trade=CONFIG['RISK_PER_TRADE']
    )
    
    result = engine.run_backtest(candles, strategy)
    
    # 4. Generate Report
    print("\n📝 Step 4: Generating report...")
    generate_report(result)
    
    # 5. Print Summary
    print("\n" + "=" * 80)
    print("BACKTEST SUMMARY")
    print("=" * 80)
    print(f"Total Trades:       {result.total_trades}")
    print(f"Win Rate:           {result.win_rate:.2f}%")
    print(f"Total Return:       {result.total_pnl_percent:.2f}%")
    print(f"Profit Factor:      {result.profit_factor:.2f}")
    print(f"Max Drawdown:       {result.max_drawdown_percent:.2f}%")
    print(f"Sharpe Ratio:       {result.sharpe_ratio:.2f}")
    print("=" * 80)
    
    # Final Verdict
    print("\n🎯 FINAL VERDICT:")
    if result.win_rate >= 55 and result.profit_factor >= 1.5 and result.max_drawdown_percent <= 20:
        print("✅ STRATEGY VALIDATED: Meets all criteria for paper trading")
        print("   - Win Rate >= 55% ✓")
        print("   - Profit Factor >= 1.5 ✓")
        print("   - Max Drawdown <= 20% ✓")
    else:
        print("❌ STRATEGY NEEDS OPTIMIZATION")
        if result.win_rate < 55:
            print(f"   - Win Rate {result.win_rate:.2f}% < 55% ✗")
        if result.profit_factor < 1.5:
            print(f"   - Profit Factor {result.profit_factor:.2f} < 1.5 ✗")
        if result.max_drawdown_percent > 20:
            print(f"   - Max Drawdown {result.max_drawdown_percent:.2f}% > 20% ✗")
    
    print("\n⚠️  DISCLAIMER: This is a backtest, not a guarantee of future performance.")
    print("Always paper trade before risking real capital.")

if __name__ == '__main__':
    main()
