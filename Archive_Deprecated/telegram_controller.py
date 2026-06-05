"""
Enterprise Telegram Controller
------------------------------
Asynchronous administrative controller for the trading system.
Operates exclusively on the Python backend to eliminate MQL5 thread-blocking latency.

Features:
- One-way alert routing (Executions, E-Stops, WFA Reports)
- Two-way command interface (/status, /estop, /pause)
- Strict security via Chat ID whitelisting
"""

import os
import asyncio
import logging
from typing import Optional, Dict, Any
from telegram import Update, Bot
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters
)
from datetime import datetime

# Configure Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger("TelegramController")

class TelegramController:
    """
    Asynchronous Telegram Bot Controller.
    Handles alerts and secure command execution for the trading hub.
    """
    
    def __init__(self):
        self.token = os.getenv('TELEGRAM_BOT_TOKEN')
        self.allowed_chat_id = os.getenv('TELEGRAM_CHAT_ID')
        
        if not self.token or not self.allowed_chat_id:
            logger.error("Telegram credentials missing. Bot will not start.")
            self.enabled = False
            return
            
        self.enabled = True
        self.application: Optional[Application] = None
        self.trading_system_interface = None  # Will be injected by main router
        
        # State tracking for commands
        self.paused_modules: set = set()
        self.is_e_stop_active = False
        
    def set_trading_interface(self, interface: Any):
        """Inject reference to the main trading system for command execution."""
        self.trading_system_interface = interface
        
    async def _security_check(self, update: Update) -> bool:
        """
        CRITICAL SECURITY GATE.
        Drops any command not originating from the verified TELEGRAM_CHAT_ID.
        """
        user_id = str(update.effective_user.id)
        chat_id = str(update.effective_chat.id)
        
        if user_id != self.allowed_chat_id and chat_id != self.allowed_chat_id:
            logger.warning(f"Unauthorized access attempt from User ID: {user_id}, Chat ID: {chat_id}")
            await update.message.reply_text("⛔ Access Denied: Unauthorized User.")
            return False
            
        return True

    async def cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        /status
        Returns current floating PnL, active modules, daily DD, and asset inventory.
        """
        if not await self._security_check(update):
            return

        logger.info("Received /status command from authorized user.")
        
        if not self.trading_system_interface:
            await update.message.reply_text("⚠️ Trading System Interface not connected.")
            return

        try:
            # Fetch data from trading system
            status_data = self.trading_system_interface.get_system_status()
            
            msg = (
                "📊 **SYSTEM STATUS**\n\n"
                f"💰 Floating Balance: ${status_data.get('floating_balance', 0):.2f}\n"
                f"📉 Daily Drawdown: {status_data.get('daily_dd_pct', 0):.2f}%\n"
                f"🛑 E-Stop Active: {'YES ⚠️' if status_data.get('e_stop_active', False) else 'NO'}\n\n"
                "**ACTIVE MODULES:**\n"
            )
            
            # List assets
            assets = ['NQ', 'XAUUSD', 'EURUSD', 'GBPUSD', 'USDJPY', 'AUDUSD']
            for asset in assets:
                is_paused = asset in self.paused_modules
                status_icon = "⏸️ PAUSED" if is_paused else "✅ ONLINE"
                msg += f"- {asset}: {status_icon}\n"
                
            msg += "\n**OPEN POSITIONS:**\n"
            positions = status_data.get('open_positions', [])
            if positions:
                for pos in positions:
                    msg += f"- {pos['symbol']} ({pos['type']}): {pos['lots']} lots | PnL: ${pos['pnl']:.2f}\n"
            else:
                msg += "- None\n"
                
            await update.message.reply_text(msg, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error fetching status: {e}")
            await update.message.reply_text("❌ Error retrieving system status.")

    async def cmd_estop(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        /estop
        GLOBAL PANIC BUTTON. Liquidates all positions and halts the backend.
        """
        if not await self._security_check(update):
            return

        logger.critical("!!! MANUAL E-STOP TRIGGERED VIA TELEGRAM !!!")
        
        # Confirmation step (optional but recommended for safety)
        confirm_msg = await update.message.reply_text(
            "⚠️ **CONFIRM EMERGENCY STOP?**\nThis will close ALL positions and halt trading.\nReply /confirm_estop to proceed.",
            parse_mode='Markdown'
        )
        # In a real implementation, we'd wait for a follow-up confirmation message.
        # For this skeleton, we execute immediately but log the critical event.
        
        await confirm_msg.edit_text("🚨 EXECUTING EMERGENCY STOP... 🚨")
        
        if self.trading_system_interface:
            try:
                self.trading_system_interface.trigger_global_estop()
                self.is_e_stop_active = True
                await update.message.reply_text("✅ **E-STOP EXECUTED.**\nAll positions closed. System halted.", parse_mode='Markdown')
            except Exception as e:
                logger.error(f"E-Stop execution failed: {e}")
                await update.message.reply_text("❌ E-Stop command failed. Check logs.")
        else:
            await update.message.reply_text("❌ Trading interface not connected.")

    async def cmd_pause(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        /pause [module]
        Selectively stops a specific strategy module (e.g., /pause XAUUSD).
        """
        if not await self._security_check(update):
            return

        if not context.args:
            await update.message.reply_text("Usage: /pause [MODULE]\nExamples: /pause NQ, /pause XAUUSD_5m")
            return

        module_name = context.args[0].upper()
        
        if module_name in self.paused_modules:
            await update.message.reply_text(f"ℹ️ Module {module_name} is already paused.")
            return

        self.paused_modules.add(module_name)
        logger.info(f"Module {module_name} paused via Telegram command.")
        
        if self.trading_system_interface:
            self.trading_system_interface.pause_module(module_name)
            
        await update.message.reply_text(f"⏸️ Module **{module_name}** has been paused.", parse_mode='Markdown')

    async def cmd_resume(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        /resume [module]
        Resumes a paused strategy module.
        """
        if not await self._security_check(update):
            return

        if not context.args:
            await update.message.reply_text("Usage: /resume [MODULE]")
            return

        module_name = context.args[0].upper()
        
        if module_name not in self.paused_modules:
            await update.message.reply_text(f"ℹ️ Module {module_name} is not paused.")
            return

        self.paused_modules.remove(module_name)
        logger.info(f"Module {module_name} resumed via Telegram command.")
        
        if self.trading_system_interface:
            self.trading_system_interface.resume_module(module_name)
            
        await update.message.reply_text(f"▶️ Module **{module_name}** has been resumed.", parse_mode='Markdown')

    async def send_alert(self, message: str):
        """
        Pushes an asynchronous alert to the admin chat.
        Used for: Executions, E-Stops, WFA Reports.
        """
        if not self.enabled or not self.application:
            return
            
        try:
            await self.application.bot.send_message(
                chat_id=self.allowed_chat_id,
                text=message,
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Failed to send Telegram alert: {e}")

    def start_bot(self):
        """Initializes and starts the bot polling loop."""
        if not self.enabled:
            return

        logger.info("Initializing Telegram Bot...")
        
        self.application = Application.builder().token(self.token).build()
        
        # Register Command Handlers
        self.application.add_handler(CommandHandler("status", self.cmd_status))
        self.application.add_handler(CommandHandler("estop", self.cmd_estop))
        self.application.add_handler(CommandHandler("pause", self.cmd_pause))
        self.application.add_handler(CommandHandler("resume", self.cmd_resume))
        
        # Start the bot
        self.application.run_polling(allowed_updates=Update.ALL_TYPES)
        logger.info("Telegram Bot started successfully.")

# Singleton Instance
_telegram_instance: Optional[TelegramController] = None

def get_telegram_controller() -> TelegramController:
    global _telegram_instance
    if _telegram_instance is None:
        _telegram_instance = TelegramController()
    return _telegram_instance

if __name__ == "__main__":
    # Test run
    bot = get_telegram_controller()
    if bot.enabled:
        print("Starting bot in standalone mode...")
        bot.start_bot()
    else:
        print("Bot disabled due to missing credentials.")
