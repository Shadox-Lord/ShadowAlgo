"""
Shadow AI Trading System - OANDA Paper Trading Bridge
======================================================

Production-grade paper trading interface with realistic slippage modeling,
partial fill handling, and real-time equity tracking for prop firm compliance.

Features:
- Real-world slippage modeling (spread + volatility-based)
- Partial fill simulation
- Floating equity calculation for daily DD monitoring
- Connection to OANDA v20 API (demo/paper accounts)
"""

import os
import time
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
import requests
from enum import Enum


class OrderStatus(Enum):
    PENDING = "pending"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


@dataclass
class PaperOrder:
    """Paper trading order record"""
    id: str
    symbol: str
    direction: str  # 'BUY' or 'SELL'
    order_type: str  # 'MARKET' or 'LIMIT'
    requested_lots: float
    filled_lots: float
    entry_price: Optional[float]
    stop_loss: Optional[float]
    take_profit: Optional[float]
    status: OrderStatus
    created_at: datetime
    filled_at: Optional[datetime]
    slippage_pips: float
    commission: float
    strategy_id: str
    
    def to_dict(self):
        d = asdict(self)
        d['created_at'] = self.created_at.isoformat()
        d['filled_at'] = self.filled_at.isoformat() if self.filled_at else None
        d['status'] = self.status.value
        return d


@dataclass
class PaperPosition:
    """Active paper trading position"""
    order_id: str
    symbol: str
    direction: str
    lots: float
    entry_price: float
    current_price: float
    stop_loss: Optional[float]
    take_profit: Optional[float]
    unrealized_pnl: float
    opened_at: datetime
    strategy_id: str
    
    def to_dict(self):
        d = asdict(self)
        d['opened_at'] = self.opened_at.isoformat()
        return d


class OANDABridge:
    """
    OANDA Paper Trading Bridge
    
    Provides realistic paper trading execution with:
    - Slippage modeling based on spread and volatility
    - Partial fill simulation (5-15% probability)
    - Real-time equity tracking
    - Prop firm guardrail enforcement (floating equity DD)
    """
    
    def __init__(self, 
                 api_key: Optional[str] = None,
                 account_id: Optional[str] = None,
                 initial_balance: float = 10000.0,
                 use_demo_data: bool = True):
        """
        Initialize OANDA Bridge
        
        Args:
            api_key: OANDA v20 API key (optional if using demo data)
            account_id: OANDA account ID (optional if using demo data)
            initial_balance: Starting balance for paper trading
            use_demo_data: If True, simulate without real API calls
        """
        self.api_key = api_key or os.getenv('OANDA_API_KEY', 'demo')
        self.account_id = account_id or os.getenv('OANDA_ACCOUNT_ID', 'demo')
        self.initial_balance = initial_balance
        self.use_demo_data = use_demo_data
        
        # State tracking
        self.balance = initial_balance
        self.equity = initial_balance
        self.daily_start_balance = initial_balance
        self.positions: Dict[str, PaperPosition] = {}
        self.orders: Dict[str, PaperOrder] = {}
        self.order_counter = 0
        
        # Slippage model parameters
        self.base_slippage_pips = 0.3
        self.volatility_slippage_factor = 0.15
        self.partial_fill_probability = 0.12  # 12% chance of partial fill
        self.partial_fill_range = (0.85, 0.95)  # 85-95% fill ratio
        
        # Spread model (dynamic based on session)
        self.spread_models = {
            'EURUSD': {'base': 0.8, 'peak_multiplier': 2.5},
            'XAUUSD': {'base': 2.5, 'peak_multiplier': 3.0},
            'US100': {'base': 1.5, 'peak_multiplier': 2.0},
        }
        
        print(f"[OANDA Bridge] Initialized | Balance: ${initial_balance:.2f} | Demo Mode: {use_demo_data}")
    
    def _get_current_spread(self, symbol: str) -> float:
        """
        Get current spread with session-based widening
        
        Returns spread in pips
        """
        base_spread = self.spread_models.get(symbol, {'base': 1.0, 'peak_multiplier': 2.0})['base']
        
        # Widen spreads during rollover (21:00-22:00 UTC) and news events
        current_hour = datetime.utcnow().hour
        is_rollover = 21 <= current_hour <= 22
        is_asian_session = 0 <= current_hour <= 7
        
        if is_rollover:
            multiplier = self.spread_models.get(symbol, {'peak_multiplier': 2.0})['peak_multiplier']
        elif is_asian_session:
            multiplier = 1.5
        else:
            multiplier = 1.0
        
        return base_spread * multiplier
    
    def _calculate_slippage(self, symbol: str, lots: float, is_market_order: bool = True) -> float:
        """
        Calculate realistic slippage
        
        Components:
        1. Base slippage (0.2-0.5 pips)
        2. Volatility slippage (ATR-based)
        3. Size slippage (larger orders = more slippage)
        4. Random noise
        
        Returns slippage in pips
        """
        if not is_market_order:
            return 0.0
        
        # Base slippage
        slippage = self.base_slippage_pips
        
        # Add spread component (half spread for entry)
        spread = self._get_current_spread(symbol)
        slippage += spread * 0.5
        
        # Volatility component (simplified - would use real ATR in production)
        vol_adjustment = 0.2  # Would fetch real ATR
        slippage += vol_adjustment * self.volatility_slippage_factor
        
        # Size component (orders > 1 lot get more slippage)
        if lots > 1.0:
            slippage += (lots - 1.0) * 0.1
        
        # Random noise (±0.2 pips)
        import random
        slippage += random.uniform(-0.2, 0.2)
        
        return max(0.1, slippage)  # Minimum 0.1 pips
    
    def _simulate_partial_fill(self, requested_lots: float) -> Tuple[float, bool]:
        """
        Simulate partial fill scenario
        
        Returns:
            Tuple[float, bool]: (filled_lots, is_partial)
        """
        import random
        
        if random.random() > self.partial_fill_probability:
            # Full fill
            return requested_lots, False
        
        # Partial fill
        fill_ratio = random.uniform(*self.partial_fill_range)
        filled_lots = round(requested_lots * fill_ratio, 2)
        
        return max(0.01, filled_lots), True
    
    def _fetch_live_price(self, symbol: str) -> Optional[float]:
        """
        Fetch live price from OANDA API or simulate
        
        Returns mid-price
        """
        if self.use_demo_data:
            # Simulate price based on last known + random walk
            # In production, this would cache real prices
            base_prices = {
                'EURUSD': 1.0850,
                'XAUUSD': 2035.50,
                'US100': 17850.0,
            }
            import random
            base = base_prices.get(symbol, 1.0)
            noise = random.uniform(-0.0005, 0.0005) * base
            return round(base + noise, 5)
        
        # Real API call
        try:
            url = f"https://api-fxpractice.oanda.com/v3/instruments/{symbol}/price"
            headers = {'Authorization': f'Bearer {self.api_key}'}
            response = requests.get(url, headers=headers, timeout=5)
            
            if response.status_code == 200:
                data = response.json()
                bids = float(data['prices'][0]['bids'][0]['price'])
                asks = float(data['prices'][0]['asks'][0]['price'])
                return (bids + asks) / 2
        except Exception as e:
            print(f"[OANDA Bridge] Price fetch error: {e}")
        
        return None
    
    def execute_order(self,
                     symbol: str,
                     direction: str,
                     lots: float,
                     stop_loss: Optional[float] = None,
                     take_profit: Optional[float] = None,
                     order_type: str = 'MARKET',
                     strategy_id: str = 'UNKNOWN') -> Optional[PaperOrder]:
        """
        Execute a paper trading order
        
        Args:
            symbol: Trading instrument (EURUSD, XAUUSD, etc.)
            direction: 'BUY' or 'SELL'
            lots: Position size
            stop_loss: Stop loss price
            take_profit: Take profit price
            order_type: 'MARKET' or 'LIMIT'
            strategy_id: Originating strategy identifier
            
        Returns:
            PaperOrder object or None if rejected
        """
        # Validate inputs
        if direction not in ['BUY', 'SELL']:
            print(f"[OANDA Bridge] Invalid direction: {direction}")
            return None
        
        if lots < 0.01:
            print(f"[OANDA Bridge] Invalid lot size: {lots}")
            return None
        
        # Fetch current price
        current_price = self._fetch_live_price(symbol)
        if current_price is None:
            print(f"[OANDA Bridge] Cannot fetch price for {symbol}")
            return None
        
        # Calculate slippage
        slippage_pips = self._calculate_slippage(symbol, lots, order_type == 'MARKET')
        
        # Convert slippage to price units
        if symbol in ['XAUUSD', 'GOLD']:
            slippage_amount = slippage_pips * 0.01  # Gold: $0.01 per pip
        elif symbol in ['US100', 'NQ']:
            slippage_amount = slippage_pips * 0.1  # Indices: $0.1 per pip
        else:
            slippage_amount = slippage_pips * 0.0001  # Forex: 0.0001 per pip
        
        # Apply slippage to entry price
        if direction == 'BUY':
            entry_price = current_price + slippage_amount
        else:
            entry_price = current_price - slippage_amount
        
        # Check for partial fill
        filled_lots, is_partial = self._simulate_partial_fill(lots)
        
        # Create order
        self.order_counter += 1
        order_id = f"PAPER_{self.order_counter:06d}"
        
        now = datetime.utcnow()
        order = PaperOrder(
            id=order_id,
            symbol=symbol,
            direction=direction,
            order_type=order_type,
            requested_lots=lots,
            filled_lots=filled_lots,
            entry_price=round(entry_price, 5),
            stop_loss=stop_loss,
            take_profit=take_profit,
            status=OrderStatus.PARTIALLY_FILLED if is_partial else OrderStatus.FILLED,
            created_at=now,
            filled_at=now,
            slippage_pips=round(slippage_pips, 2),
            commission=self._calculate_commission(symbol, filled_lots),
            strategy_id=strategy_id
        )
        
        # Store order
        self.orders[order_id] = order
        
        # Create position
        position = PaperPosition(
            order_id=order_id,
            symbol=symbol,
            direction=direction,
            lots=filled_lots,
            entry_price=order.entry_price,
            current_price=current_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            unrealized_pnl=0.0,
            opened_at=now,
            strategy_id=strategy_id
        )
        
        self.positions[order_id] = position
        
        # Update equity
        self._update_equity()
        
        print(f"[OANDA Bridge] Order Executed: {order_id} | {direction} {filled_lots:.2f} {symbol} @ {entry_price:.5f} | SL: {slippage_pips:.2f} pips")
        
        return order
    
    def _calculate_commission(self, symbol: str, lots: float) -> float:
        """Calculate commission based on symbol and lot size"""
        # Typical prop firm commission structure
        commission_rates = {
            'EURUSD': 7.0,  # $7 per lot
            'GBPUSD': 7.0,
            'XAUUSD': 10.0,  # $10 per lot for gold
            'US100': 5.0,   # $5 per lot for indices
        }
        
        rate = commission_rates.get(symbol, 7.0)
        return round(rate * lots, 2)
    
    def _update_equity(self):
        """Update floating equity based on current positions"""
        total_unrealized_pnl = 0.0
        
        for position in self.positions.values():
            # Fetch current price
            current_price = self._fetch_live_price(position.symbol)
            if current_price is None:
                continue
            
            position.current_price = current_price
            
            # Calculate unrealized PnL
            if position.direction == 'BUY':
                pnl_points = current_price - position.entry_price
            else:
                pnl_points = position.entry_price - current_price
            
            # Convert to dollar value
            if position.symbol in ['XAUUSD', 'GOLD']:
                pnl_value = pnl_points * position.lots * 100  # $100 per lot per point
            elif position.symbol in ['US100', 'NQ']:
                pnl_value = pnl_points * position.lots * 1  # $1 per lot per point
            else:
                pnl_value = pnl_points * position.lots * 100000  # $100k per lot for forex
            
            position.unrealized_pnl = pnl_value
            total_unrealized_pnl += pnl_value
        
        # Equity = Balance + Unrealized PnL
        self.equity = self.balance + total_unrealized_pnl
    
    def get_floating_drawdown(self) -> Tuple[float, float]:
        """
        Calculate current drawdown from daily start balance
        
        Returns:
            Tuple[float, float]: (drawdown_amount, drawdown_percent)
        """
        self._update_equity()
        
        drawdown_amount = self.daily_start_balance - self.equity
        drawdown_percent = drawdown_amount / self.daily_start_balance
        
        return drawdown_amount, drawdown_percent
    
    def check_daily_dd_limit(self, limit_percent: float = 0.006) -> Tuple[bool, str]:
        """
        Check if floating equity drawdown exceeds limit
        
        Args:
            limit_percent: Maximum allowed drawdown (default 0.6%)
            
        Returns:
            Tuple[bool, str]: (is_breached, message)
        """
        _, dd_percent = self.get_floating_drawdown()
        
        if dd_percent >= limit_percent:
            return True, f"DAILY DD BREACH: Floating equity drawdown {dd_percent:.2%} >= {limit_percent:.2%} limit"
        
        return False, f"DD OK: {dd_percent:.2%}"
    
    def close_position(self, order_id: str, reason: str = 'MANUAL') -> Optional[float]:
        """
        Close an existing position
        
        Returns realized PnL
        """
        if order_id not in self.positions:
            print(f"[OANDA Bridge] Position not found: {order_id}")
            return None
        
        position = self.positions[order_id]
        
        # Fetch exit price
        exit_price = self._fetch_live_price(position.symbol)
        if exit_price is None:
            return None
        
        # Calculate PnL
        if position.direction == 'BUY':
            pnl_points = exit_price - position.entry_price
        else:
            pnl_points = position.entry_price - exit_price
        
        # Convert to dollars
        if position.symbol in ['XAUUSD', 'GOLD']:
            pnl_value = pnl_points * position.lots * 100
        elif position.symbol in ['US100', 'NQ']:
            pnl_value = pnl_points * position.lots * 1
        else:
            pnl_value = pnl_points * position.lots * 100000
        
        # Subtract commission
        order = self.orders.get(order_id)
        if order:
            pnl_value -= order.commission
        
        # Update balance
        self.balance += pnl_value
        
        # Remove position
        del self.positions[order_id]
        
        # Update order status
        if order:
            order.status = OrderStatus.CANCELLED
        
        # Update equity
        self._update_equity()
        
        print(f"[OANDA Bridge] Position Closed: {order_id} | PnL: ${pnl_value:.2f} | Reason: {reason}")
        
        return pnl_value
    
    def close_all_positions(self, reason: str = 'E-STOP') -> List[float]:
        """
        Close all open positions (emergency stop)
        
        Returns list of realized PnL for each position
        """
        pnl_results = []
        
        # Copy keys to avoid modification during iteration
        order_ids = list(self.positions.keys())
        
        for order_id in order_ids:
            pnl = self.close_position(order_id, reason)
            if pnl is not None:
                pnl_results.append(pnl)
        
        print(f"[OANDA Bridge] All Positions Closed | Count: {len(pnl_results)} | Reason: {reason}")
        
        return pnl_results
    
    def reset_daily_counters(self):
        """Reset daily start balance (call at start of each trading day)"""
        self.daily_start_balance = self.balance
        print(f"[OANDA Bridge] Daily counters reset | New start balance: ${self.balance:.2f}")
    
    def get_account_summary(self) -> Dict:
        """Get comprehensive account summary"""
        self._update_equity()
        dd_amount, dd_percent = self.get_floating_drawdown()
        
        return {
            'balance': round(self.balance, 2),
            'equity': round(self.equity, 2),
            'daily_start_balance': round(self.daily_start_balance, 2),
            'unrealized_pnl': round(self.equity - self.balance, 2),
            'daily_drawdown_amount': round(dd_amount, 2),
            'daily_drawdown_percent': round(dd_percent * 100, 3),
            'open_positions': len(self.positions),
            'total_orders_today': len(self.orders),
        }
    
    def export_trade_log(self, filepath: str = 'paper_trading_log.csv'):
        """Export all trades to CSV for audit trail"""
        import csv
        
        with open(filepath, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                'OrderID', 'Symbol', 'Direction', 'Lots', 'EntryPrice', 'SL', 'TP',
                'Status', 'SlippagePips', 'Commission', 'StrategyID', 'CreatedAt'
            ])
            
            for order in self.orders.values():
                writer.writerow([
                    order.id,
                    order.symbol,
                    order.direction,
                    order.filled_lots,
                    order.entry_price,
                    order.stop_loss or '',
                    order.take_profit or '',
                    order.status.value,
                    order.slippage_pips,
                    order.commission,
                    order.strategy_id,
                    order.created_at.isoformat()
                ])
        
        print(f"[OANDA Bridge] Trade log exported: {filepath}")
