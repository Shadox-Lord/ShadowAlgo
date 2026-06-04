"""Shadow AI Trading System - Core Libraries"""
from .trading_core import (
    RegimeFilter,
    RiskManager,
    MarketRegime,
    TradeSignal,
    RegimeMetrics,
    FEW_SHOT_FAILURE_SIGNATURES
)
from .qwen_engine import QwenEngine, get_qwen_engine
from .oanda_bridge import OANDABridge, PaperOrder, PaperPosition, OrderStatus
from .strategies import (
    BaseStrategy,
    StrategySignal,
    StrategyNQORB,
    StrategyGoldPullback,
    StrategyGradingBot
)

__all__ = [
    'RegimeFilter',
    'RiskManager', 
    'MarketRegime',
    'TradeSignal',
    'RegimeMetrics',
    'FEW_SHOT_FAILURE_SIGNATURES',
    'QwenEngine',
    'get_qwen_engine',
    'OANDABridge',
    'PaperOrder',
    'PaperPosition',
    'OrderStatus',
    'BaseStrategy',
    'StrategySignal',
    'StrategyNQORB',
    'StrategyGoldPullback',
    'StrategyGradingBot'
]
