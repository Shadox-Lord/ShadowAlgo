"""
Shadow Portfolio Hub - Signal Router
=====================================
Main orchestration endpoint triggered by Vercel Cron.

Pipeline:
1. Fetch OHLCV data
2. Kronos Gate (Directional Confidence)
3. Qwen 3.6-Plus (SMC Audit)
4. Calculate Lots (Risk Manager)
5. Send Telegram Alert

Removal: NO automated order execution (OANDA/MT5 removed).
Logging: Insert record into trade_executions with status SIGNAL_SENT immediately after calculation.

Alert Format: Exact layout for rapid mobile copy-pasting.
"""

import os
import json
import logging
from datetime import datetime
from typing import Dict, Any, Optional, List

from supabase import create_client, Client

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("signal_router")


def get_supabase_client() -> Client:
    """Initialize Supabase client from environment variables"""
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    
    if not supabase_url or not supabase_key:
        raise ValueError("Supabase credentials not configured")
    
    return create_client(supabase_url, supabase_key)


async def fetch_ohlcv(asset: str, timeframe: str, limit: int = 100) -> List[Dict]:
    """
    Fetch OHLCV data for asset/timeframe.
    In production, this would call TwelveData, AlphaVantage, or broker API.
    For now, returns simulated data structure.
    """
    # TODO: Replace with actual API call to TwelveData or similar
    # This is a placeholder that returns empty data
    logger.info(f"Fetching OHLCV for {asset} {timeframe}")
    
    # Simulated candle structure
    base_prices = {
        'NQ': 17850.0,
        'US100': 17850.0,
        'XAUUSD': 2035.50,
        'GOLD': 2035.50,
        'EURUSD': 1.0850,
        'GBPUSD': 1.2650,
        'USDJPY': 151.20,
        'AUDUSD': 0.6580,
    }
    
    base = base_prices.get(asset.upper(), 1.0)
    candles = []
    
    import random
    for i in range(limit):
        noise = random.uniform(-0.002, 0.002)
        close = base * (1 + noise)
        open_price = base * (1 + random.uniform(-0.001, 0.001))
        high = max(open_price, close) * (1 + random.uniform(0, 0.001))
        low = min(open_price, close) * (1 - random.uniform(0, 0.001))
        
        candles.append({
            'time': datetime.utcnow().isoformat(),
            'open': round(open_price, 5),
            'high': round(high, 5),
            'low': round(low, 5),
            'close': round(close, 5),
            'volume': random.randint(100, 10000)
        })
    
    return candles


def kronos_gate(asset: str, timeframe: str, ohlcv: List[Dict]) -> Dict[str, Any]:
    """
    Kronos forecasting gate - directional confidence check.
    Returns direction, confidence, and approval status.
    """
    try:
        # Import the Kronos engine
        import sys
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from lib.kronos_engine import get_kronos_forecaster
        
        forecaster = get_kronos_forecaster()
        
        # Ingest candles
        for candle in ohlcv[-20:]:
            forecaster.ingest_candle(asset, timeframe, candle)
        
        # Get forecast
        forecast = forecaster.forecast(asset, timeframe)
        
        if not forecast:
            return {
                'approved': False,
                'direction': None,
                'confidence': 0,
                'rejection_reason': 'No forecast available'
            }
        
        return {
            'approved': forecast.is_approved,
            'direction': forecast.direction.name if forecast.direction else None,
            'confidence': forecast.confidence,
            'predicted_move_pct': forecast.predicted_move_pct,
            'rejection_reason': forecast.rejection_reason
        }
        
    except Exception as e:
        logger.error(f"Kronos gate error: {e}")
        return {
            'approved': False,
            'direction': None,
            'confidence': 0,
            'rejection_reason': f'Kronos error: {str(e)}'
        }


def qwen_smc_audit(
    asset: str,
    timeframe: str,
    ohlcv: List[Dict],
    kronos_direction: str
) -> Dict[str, Any]:
    """
    Qwen 3.6-Plus SMC audit - validates market structure.
    Returns structure validity, entry/SL/TP levels, and reasoning.
    """
    try:
        # Import Qwen engine
        import sys
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from lib.qwen_engine import get_qwen_engine
        
        engine = get_qwen_engine()
        
        # Split data for H4 and H1 analysis (simplified)
        h4_data = ohlcv[-50:]  # Last 50 candles as H4 proxy
        h1_data = ohlcv[-20:]  # Last 20 candles as H1 proxy
        
        # Call Qwen for analysis
        result = engine.analyze_market(
            asset=asset,
            h4_data=h4_data,
            h1_data=h1_data,
            macro_context="",
            regime_status=""
        )
        
        if not result.get('success'):
            return {
                'structure_valid': False,
                'direction': None,
                'entry': None,
                'stop_loss': None,
                'take_profit': None,
                'confidence': 0,
                'reasoning': result.get('error', 'Unknown error'),
                'rr_ratio': 0
            }
        
        data = result.get('data', {})
        
        # Check alignment with Kronos direction
        qwen_direction = data.get('direction')
        if qwen_direction and kronos_direction:
            if qwen_direction != kronos_direction.upper():
                return {
                    'structure_valid': False,
                    'direction': qwen_direction,
                    'entry': data.get('entry'),
                    'stop_loss': data.get('stop_loss'),
                    'take_profit': data.get('take_profit'),
                    'confidence': data.get('confidence', 0),
                    'reasoning': f"Direction mismatch: Qwen={qwen_direction}, Kronos={kronos_direction}",
                    'rr_ratio': data.get('rr_ratio', 0)
                }
        
        return {
            'structure_valid': data.get('structure_valid', False),
            'direction': qwen_direction,
            'entry': data.get('entry'),
            'stop_loss': data.get('stop_loss'),
            'take_profit': data.get('take_profit'),
            'confidence': data.get('confidence', 0),
            'reasoning': data.get('reasoning', '')[:200],  # Truncate for storage
            'rr_ratio': data.get('rr_ratio', 0),
            'liquidity_sweep': data.get('liquidity_sweep', False),
            'bos_confirmed': data.get('bos_confirmed', False)
        }
        
    except Exception as e:
        logger.error(f"Qwen SMC audit error: {e}")
        return {
            'structure_valid': False,
            'direction': None,
            'entry': None,
            'stop_loss': None,
            'take_profit': None,
            'confidence': 0,
            'reasoning': f'Qwen error: {str(e)}',
            'rr_ratio': 0
        }


def calculate_lots_and_signal(
    asset: str,
    entry: float,
    stop_loss: float,
    take_profit: float,
    balance: float
) -> Dict[str, Any]:
    """
    Calculate lot size using risk manager.
    Returns complete signal with lot sizing.
    """
    try:
        # Import risk manager
        import sys
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from lib.risk_manager import calculate_risk_metrics, calculate_sl_distance_pips
        
        metrics = calculate_risk_metrics(
            asset=asset,
            entry_price=entry,
            stop_loss=stop_loss,
            take_profit=take_profit,
            current_balance=balance
        )
        
        sl_pips = calculate_sl_distance_pips(entry, stop_loss, asset)
        
        return {
            'lot_size': metrics['lot_size'],
            'risk_amount': metrics['risk_amount'],
            'reward_amount': metrics['reward_amount'],
            'rr_ratio': metrics['rr_ratio'],
            'sl_distance_pips': sl_pips,
            'entry': entry,
            'stop_loss': stop_loss,
            'take_profit': take_profit,
            'direction': 'long' if entry < take_profit else 'short'
        }
        
    except Exception as e:
        logger.error(f"Lot calculation error: {e}")
        return None


async def send_telegram_alert(signal: Dict[str, Any]) -> Optional[int]:
    """
    Send signal alert to Telegram.
    Returns message_id if successful.
    """
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    
    if not bot_token or not chat_id:
        logger.error("Telegram credentials not configured")
        return None
    
    # Format alert message for rapid mobile copy-pasting
    direction_emoji = "🟢" if signal['direction'].upper() == 'LONG' else "🔴"
    
    message = f"""{direction_emoji} **{signal['asset']} {signal['timeframe'].upper()}** {signal['direction'].upper()}

📊 **ENTRY:** `{signal['entry']}`
🛑 **SL:** `{signal['stop_loss']}`
✅ **TP:** `{signal['take_profit']}`

📐 **Lot Size:** `{signal['lot_size']}`
💰 **Risk:** `${signal['risk_amount']}` (0.30%)
📈 **RR:** 1:{signal['rr_ratio']}

⏰ **Time:** {datetime.utcnow().strftime('%H:%M UTC')}
⚠️ **Manual Execute:** Copy to MT5 within 60 seconds!

#Signal #{signal.get('execution_id', 'N/A')[-8:]}"""
    
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    
    import httpx
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                url,
                json={
                    "chat_id": chat_id,
                    "text": message,
                    "parse_mode": "Markdown"
                },
                timeout=10.0
            )
            result = response.json()
            if result.get('ok'):
                return result['result']['message_id']
            return None
        except Exception as e:
            logger.error(f"Failed to send Telegram alert: {e}")
            return None


def insert_trade_execution(
    supabase: Client,
    signal: Dict[str, Any],
    telegram_message_id: Optional[int]
) -> str:
    """Insert signal record into trade_executions table"""
    try:
        result = supabase.table("trade_executions").insert({
            "asset": signal['asset'],
            "timeframe": signal['timeframe'],
            "direction": signal['direction'].lower(),
            "entry_price": signal['entry'],
            "stop_loss": signal['stop_loss'],
            "take_profit": signal['take_profit'],
            "lot_size": signal['lot_size'],
            "risk_amount": signal['risk_amount'],
            "sl_distance_pips": signal['sl_distance_pips'],
            "status": "SIGNAL_SENT",
            "kronos_confidence": signal.get('kronos_confidence'),
            "qwen_confidence": signal.get('qwen_confidence'),
            "qwen_reasoning": signal.get('qwen_reasoning'),
            "telegram_message_id": telegram_message_id,
            "metadata": {
                "rr_ratio": signal['rr_ratio'],
                "reward_amount": signal['reward_amount']
            }
        }).execute()
        
        execution_id = result.data[0]['execution_id'] if result.data else None
        logger.info(f"Trade execution inserted: {execution_id}")
        return execution_id
        
    except Exception as e:
        logger.error(f"Failed to insert trade execution: {e}")
        return None


async def process_signal(
    supabase: Client,
    asset: str,
    timeframe: str,
    balance: float
) -> Optional[Dict[str, Any]]:
    """Process a single asset/timeframe through the full pipeline"""
    
    logger.info(f"Processing {asset} {timeframe}")
    
    # Step 1: Fetch OHLCV
    ohlcv = await fetch_ohlcv(asset, timeframe)
    if not ohlcv:
        logger.warning(f"No OHLCV data for {asset} {timeframe}")
        return None
    
    # Step 2: Kronos Gate
    kronos_result = kronos_gate(asset, timeframe, ohlcv)
    if not kronos_result['approved']:
        logger.info(f"Kronos rejected {asset} {timeframe}: {kronos_result.get('rejection_reason')}")
        return None
    
    # Step 3: Qwen SMC Audit
    qwen_result = qwen_smc_audit(
        asset=asset,
        timeframe=timeframe,
        ohlcv=ohlcv,
        kronos_direction=kronos_result['direction']
    )
    
    if not qwen_result['structure_valid']:
        logger.info(f"Qwen rejected {asset} {timeframe}: {qwen_result.get('reasoning')}")
        return None
    
    if not qwen_result['entry'] or not qwen_result['stop_loss'] or not qwen_result['take_profit']:
        logger.warning(f"Qwen did not provide valid levels for {asset} {timeframe}")
        return None
    
    # Step 4: Calculate Lots
    signal_data = calculate_lots_and_signal(
        asset=asset,
        entry=qwen_result['entry'],
        stop_loss=qwen_result['stop_loss'],
        take_profit=qwen_result['take_profit'],
        balance=balance
    )
    
    if not signal_data:
        logger.error(f"Lot calculation failed for {asset} {timeframe}")
        return None
    
    # Build complete signal object
    signal = {
        'asset': asset,
        'timeframe': timeframe,
        'direction': signal_data['direction'],
        'entry': signal_data['entry'],
        'stop_loss': signal_data['stop_loss'],
        'take_profit': signal_data['take_profit'],
        'lot_size': signal_data['lot_size'],
        'risk_amount': signal_data['risk_amount'],
        'reward_amount': signal_data['reward_amount'],
        'rr_ratio': signal_data['rr_ratio'],
        'sl_distance_pips': signal_data['sl_distance_pips'],
        'kronos_confidence': kronos_result['confidence'],
        'qwen_confidence': qwen_result['confidence'],
        'qwen_reasoning': qwen_result['reasoning']
    }
    
    # Step 5: Send Telegram Alert
    telegram_message_id = await send_telegram_alert(signal)
    
    # Step 6: Log to database
    execution_id = insert_trade_execution(supabase, signal, telegram_message_id)
    signal['execution_id'] = execution_id
    
    logger.info(f"Signal generated for {asset} {timeframe}: {signal['direction']} | Lot: {signal['lot_size']}")
    
    return signal


async def main_handler(request) -> Dict[str, Any]:
    """
    Main handler for Vercel serverless function.
    Triggered by cron jobs with timeframe parameter.
    """
    try:
        # Parse query parameters
        if hasattr(request, 'query'):
            timeframe = request.query.get('timeframe', '15m')
        elif hasattr(request, 'url'):
            from urllib.parse import parse_qs, urlparse
            parsed = urlparse(request.url)
            params = parse_qs(parsed.query)
            timeframe = params.get('timeframe', ['15m'])[0]
        else:
            timeframe = '15m'
        
        logger.info(f"Signal router triggered with timeframe: {timeframe}")
        
        # Initialize Supabase
        supabase = get_supabase_client()
        
        # Check if trading is halted
        state_result = supabase.table("system_state").select("is_trading_halted").eq("id", 1).execute()
        if state_result.data and state_result.data[0].get("is_trading_halted"):
            logger.warning("Trading is halted. Skipping signal generation.")
            return {"statusCode": 200, "body": json.dumps({"status": "halted"})}
        
        # Get target balance
        balance_result = supabase.table("system_state").select("target_initial_balance").eq("id", 1).execute()
        balance = balance_result.data[0]['target_initial_balance'] if balance_result.data else 5000.0
        
        # Define assets to process based on timeframe
        asset_timeframes = {
            '5m': ['XAUUSD'],
            '15m': ['NQ', 'XAUUSD', 'EURUSD', 'GBPUSD', 'USDJPY', 'AUDUSD'],
            '1h': ['NQ', 'XAUUSD', 'EURUSD', 'GBPUSD', 'USDJPY', 'AUDUSD'],
        }
        
        assets = asset_timeframes.get(timeframe, ['EURUSD'])
        
        # Check pause states
        pause_result = supabase.table("module_pause_states").select("module_name,is_paused").execute()
        paused_modules = set()
        for mod in (pause_result.data or []):
            if mod.get("is_paused"):
                paused_modules.add(mod['module_name'])
        
        # Process each asset
        signals_generated = []
        for asset in assets:
            if asset in paused_modules:
                logger.info(f"Skipping paused module: {asset}")
                continue
            
            signal = await process_signal(supabase, asset, timeframe, balance)
            if signal:
                signals_generated.append(signal)
        
        logger.info(f"Generated {len(signals_generated)} signals")
        
        return {
            "statusCode": 200,
            "body": json.dumps({
                "status": "ok",
                "timeframe": timeframe,
                "signals_generated": len(signals_generated),
                "assets_processed": assets,
                "timestamp": datetime.utcnow().isoformat()
            })
        }
        
    except Exception as e:
        logger.error(f"Signal router error: {e}")
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)})
        }


# Vercel serverless function entry point
def GET(request):
    """HTTP GET handler for Vercel cron triggers"""
    import asyncio
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    result = loop.run_until_complete(main_handler(request))
    return result


# For local testing
if __name__ == "__main__":
    class MockRequest:
        url = "http://localhost:3000/api/signal_router?timeframe=15m"
    
    result = GET(MockRequest())
    print(f"Test result: {result}")
