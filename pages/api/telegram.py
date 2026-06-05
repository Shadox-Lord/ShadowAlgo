"""
Shadow Portfolio Hub - Telegram Webhook Handler
================================================
Vercel Serverless Function for handling Telegram bot commands.

Security: Middleware verifies message.from.id matches TELEGRAM_CHAT_ID env var.
Commands:
- /setbalance [value]: Updates target_initial_balance in Supabase
- /status: Returns current balance config, active modules, last signal time
- /estop: Flags global halt in Supabase
- /pause [module]: Temporarily disables specific asset class

Fallback: If no balance is set in DB, default to $5,000.
"""

import os
import json
import logging
from datetime import datetime
from typing import Dict, Any, Optional

from supabase import create_client, Client

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("telegram_webhook")


def get_supabase_client() -> Client:
    """Initialize Supabase client from environment variables"""
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    
    if not supabase_url or not supabase_key:
        raise ValueError("Supabase credentials not configured")
    
    return create_client(supabase_url, supabase_key)


def verify_security(update: Dict[str, Any]) -> bool:
    """
    CRITICAL SECURITY GATE.
    Verify message originates from authorized TELEGRAM_CHAT_ID.
    """
    allowed_chat_id = os.getenv("TELEGRAM_CHAT_ID")
    
    if not allowed_chat_id:
        logger.error("TELEGRAM_CHAT_ID not configured")
        return False
    
    message = update.get("message", {})
    from_user = message.get("from", {})
    user_id = str(from_user.get("id", ""))
    chat_id = str(message.get("chat", {}).get("id", ""))
    
    if user_id != allowed_chat_id and chat_id != allowed_chat_id:
        logger.warning(f"Unauthorized access attempt from User ID: {user_id}, Chat ID: {chat_id}")
        return False
    
    return True


async def send_telegram_message(chat_id: str, text: str, parse_mode: str = "Markdown") -> Dict:
    """Send message to Telegram using bot API"""
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    
    if not bot_token:
        logger.error("TELEGRAM_BOT_TOKEN not configured")
        return {"ok": False, "error": "Bot token not configured"}
    
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    
    import httpx
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                url,
                json={
                    "chat_id": chat_id,
                    "text": text,
                    "parse_mode": parse_mode
                },
                timeout=10.0
            )
            return response.json()
        except Exception as e:
            logger.error(f"Failed to send Telegram message: {e}")
            return {"ok": False, "error": str(e)}


def cmd_setbalance(supabase: Client, chat_id: str, args: list) -> tuple[str, bool]:
    """
    /setbalance [value]
    Updates target_initial_balance in Supabase.
    Robust validation against non-numeric inputs.
    """
    if not args:
        return "❌ Usage: /setbalance [amount]\nExample: /setbalance 5000", False
    
    try:
        # Validate numeric input
        new_balance = float(args[0].replace(",", ""))
        
        if new_balance <= 0:
            return "❌ Balance must be a positive number", False
        
        if new_balance < 100:
            return "⚠️ Warning: Balance below $100 may result in zero lot sizes", False
        
        # Update Supabase
        result = supabase.table("system_state").update({
            "target_initial_balance": new_balance,
            "updated_at": datetime.utcnow().isoformat()
        }).eq("id", 1).execute()
        
        logger.info(f"Balance updated to ${new_balance:.2f} by user {chat_id}")
        
        return (
            f"✅ **BALANCE UPDATED**\n\n"
            f"New Target Balance: **${new_balance:,.2f}**\n"
            f"Risk Per Trade (0.30%): **${new_balance * 0.003:,.2f}**\n\n"
            f"This balance will be used for all future position sizing calculations."
        ), True
        
    except ValueError:
        return "❌ Invalid input. Please enter a valid number (e.g., 5000 or 5,000)", False
    except Exception as e:
        logger.error(f"Error updating balance: {e}")
        return f"❌ Error updating balance: {str(e)}", False


def cmd_status(supabase: Client, chat_id: str) -> tuple[str, bool]:
    """
    /status
    Returns current balance config, active modules, and last signal time.
    """
    try:
        # Get system state
        state_result = supabase.table("system_state").select("*").eq("id", 1).execute()
        state = state_result.data[0] if state_result.data else {}
        
        current_balance = state.get("target_initial_balance", 5000.0)
        is_halted = state.get("is_trading_halted", False)
        
        # Get module states
        modules_result = supabase.table("module_pause_states").select("*").execute()
        modules = modules_result.data or []
        
        # Get last signal
        last_signal_result = supabase.table("trade_executions").select(
            "asset,direction,created_at,status"
        ).order("created_at", desc=True).limit(1).execute()
        last_signal = last_signal_result.data[0] if last_signal_result.data else None
        
        # Build status message
        msg = f"📊 **SYSTEM STATUS**\n\n"
        msg += f"💰 **Target Balance:** ${current_balance:,.2f}\n"
        msg += f"⚠️ **Risk Per Trade:** ${current_balance * 0.003:,.2f} (0.30%)\n"
        msg += f"🛑 **Trading Halted:** {'YES ⚠️' if is_halted else 'NO'}\n\n"
        
        msg += "**MODULES:**\n"
        for mod in modules:
            status_icon = "⏸️ PAUSED" if mod.get("is_paused") else "✅ ACTIVE"
            msg += f"- {mod['module_name']}: {status_icon}\n"
        
        if last_signal:
            created = last_signal.get("created_at", "")[:19].replace("T", " ")
            msg += f"\n📡 **Last Signal:**\n"
            msg += f"   {last_signal['direction']} {last_signal['asset']}\n"
            msg += f"   Status: {last_signal['status']}\n"
            msg += f"   Time: {created} UTC"
        else:
            msg += "\n📡 **Last Signal:** No signals generated yet"
        
        return msg, True
        
    except Exception as e:
        logger.error(f"Error fetching status: {e}")
        return f"❌ Error retrieving status: {str(e)}", False


def cmd_estop(supabase: Client, chat_id: str) -> tuple[str, bool]:
    """
    /estop
    Flags a global halt in Supabase (prevents new signals).
    """
    try:
        # Update system state to halt trading
        supabase.table("system_state").update({
            "is_trading_halted": True,
            "halted_at": datetime.utcnow().isoformat(),
            "halted_reason": "Manual E-Stop via Telegram"
        }).eq("id", 1).execute()
        
        # Log the event
        supabase.table("system_logs").insert({
            "level": "critical",
            "module": "telegram_estop",
            "message": "Emergency stop triggered via Telegram",
            "metadata": {"chat_id": chat_id}
        }).execute()
        
        logger.critical(f"E-Stop triggered by user {chat_id}")
        
        return (
            "🚨 **EMERGENCY STOP ACTIVATED**\n\n"
            "All new signal generation has been halted.\n"
            "Existing signals remain in SIGNAL_SENT status.\n\n"
            "Contact administrator to resume trading."
        ), True
        
    except Exception as e:
        logger.error(f"Error executing E-Stop: {e}")
        return f"❌ Error executing E-Stop: {str(e)}", False


def cmd_pause(supabase: Client, chat_id: str, module: str) -> tuple[str, bool]:
    """
    /pause [module]
    Temporarily disables a specific asset class.
    """
    if not module:
        return "❌ Usage: /pause [MODULE]\nExamples: /pause NQ, /pause XAUUSD", False
    
    module_upper = module.upper()
    
    try:
        # Check if module exists
        existing = supabase.table("module_pause_states").select("module_name").eq("module_name", module_upper).execute()
        
        if not existing.data:
            return f"❌ Unknown module: {module_upper}\nAvailable: NQ, XAUUSD, EURUSD, GBPUSD, USDJPY, AUDUSD", False
        
        # Update pause state
        supabase.table("module_pause_states").update({
            "is_paused": True,
            "paused_by": chat_id,
            "paused_at": datetime.utcnow().isoformat(),
            "pause_reason": "Manual pause via Telegram"
        }).eq("module_name", module_upper).execute()
        
        logger.info(f"Module {module_upper} paused by user {chat_id}")
        
        return f"⏸️ Module **{module_upper}** has been paused.\nNo new signals will be generated for this asset.", True
        
    except Exception as e:
        logger.error(f"Error pausing module: {e}")
        return f"❌ Error pausing module: {str(e)}", False


def cmd_resume(supabase: Client, chat_id: str, module: str) -> tuple[str, bool]:
    """
    /resume [module]
    Resumes a paused asset class.
    """
    if not module:
        return "❌ Usage: /resume [MODULE]", False
    
    module_upper = module.upper()
    
    try:
        # Update pause state
        supabase.table("module_pause_states").update({
            "is_paused": False,
            "paused_by": None,
            "paused_at": None,
            "pause_reason": None
        }).eq("module_name", module_upper).execute()
        
        logger.info(f"Module {module_upper} resumed by user {chat_id}")
        
        return f"▶️ Module **{module_upper}** has been resumed.", True
        
    except Exception as e:
        logger.error(f"Error resuming module: {e}")
        return f"❌ Error resuming module: {str(e)}", False


def main(handler_request) -> Dict[str, Any]:
    """
    Main handler for Vercel serverless function.
    Processes incoming Telegram webhook updates.
    """
    try:
        # Parse request body
        if hasattr(handler_request, 'body'):
            body = json.loads(handler_request.body)
        elif hasattr(handler_request, 'json'):
            body = handler_request.json()
        else:
            body = handler_request
        
        update = body if isinstance(body, dict) else json.loads(body)
        
    except Exception as e:
        logger.error(f"Failed to parse request body: {e}")
        return {"statusCode": 400, "body": json.dumps({"error": "Invalid request body"})}
    
    # Security check
    if not verify_security(update):
        return {"statusCode": 403, "body": json.dumps({"status": "forbidden"})}
    
    # Extract message data
    message = update.get("message", {})
    chat_id = str(message.get("chat", {}).get("id", ""))
    text = message.get("text", "").strip()
    
    if not text:
        return {"statusCode": 200, "body": json.dumps({"status": "no_message"})}
    
    # Initialize Supabase
    try:
        supabase = get_supabase_client()
    except Exception as e:
        logger.error(f"Supabase initialization failed: {e}")
        return {"statusCode": 500, "body": json.dumps({"error": "Database connection failed"})}
    
    # Parse command
    parts = text.split(maxsplit=1)
    command = parts[0].lower()
    args = parts[1].split() if len(parts) > 1 else []
    
    # Route commands
    response_text = ""
    success = False
    
    if command == "/setbalance":
        response_text, success = cmd_setbalance(supabase, chat_id, args)
    elif command == "/status":
        response_text, success = cmd_status(supabase, chat_id)
    elif command == "/estop":
        response_text, success = cmd_estop(supabase, chat_id)
    elif command == "/pause":
        module = args[0] if args else ""
        response_text, success = cmd_pause(supabase, chat_id, module)
    elif command == "/resume":
        module = args[0] if args else ""
        response_text, success = cmd_resume(supabase, chat_id, module)
    else:
        response_text = (
            "❓ **Unknown Command**\n\n"
            "**Available Commands:**\n"
            "/setbalance [amount] - Set target balance\n"
            "/status - View system status\n"
            "/estop - Emergency stop (halts all signals)\n"
            "/pause [MODULE] - Pause an asset class\n"
            "/resume [MODULE] - Resume a paused asset"
        )
    
    # Send response via Telegram
    import asyncio
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    loop.run_until_complete(send_telegram_message(chat_id, response_text))
    
    return {"statusCode": 200, "body": json.dumps({"status": "ok", "command": command})}


# Vercel serverless function entry point
def POST(request):
    """HTTP POST handler for Vercel"""
    return main(request)


# For local testing
if __name__ == "__main__":
    # Test payload
    test_update = {
        "message": {
            "chat": {"id": "123456"},
            "from": {"id": "123456"},
            "text": "/status"
        }
    }
    
    class MockRequest:
        body = json.dumps(test_update)
    
    result = POST(MockRequest())
    print(f"Test result: {result}")
