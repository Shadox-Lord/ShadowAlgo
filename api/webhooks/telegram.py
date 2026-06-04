import os
import json
from http.server import BaseHTTPRequestHandler
from api.lib.supabase_client import get_supabase
from api.lib.telegram_notifier import send_telegram_message

class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length)
        update = json.loads(body)
        result = self.handle_update(update)
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(result).encode())

    def handle_update(self, update):
        message = update.get('message', {})
        chat_id = str(message.get('chat', {}).get('id', ''))
        text = message.get('text', '').strip()
        from_user = message.get('from', {}).get('username', 'unknown')
        allowed_chat_id = os.getenv('TELEGRAM_CHAT_ID', '')
        supabase = get_supabase()
        supabase.table("telegram_commands").insert({
            "command": text,
            "from_user": from_user,
            "chat_id": chat_id,
            "response": ""
        }).execute()
        if chat_id != allowed_chat_id:
            return {"status": "ignored", "reason": "unauthorized"}
        if text == '/status':
            return self.cmd_status(supabase, chat_id)
        elif text == '/estop':
            return self.cmd_estop(supabase, chat_id)
        elif text.startswith('/pause'):
            module = text.replace('/pause', '').strip()
            return self.cmd_pause(supabase, chat_id, module)
        elif text.startswith('/resume'):
            module = text.replace('/resume', '').strip()
            return self.cmd_resume(supabase, chat_id, module)
        else:
            send_telegram_message(chat_id, "Unknown command. Available: /status, /estop, /pause [module], /resume [module]")
            return {"status": "unknown_command"}

    def cmd_status(self, supabase, chat_id):
        open_trades = supabase.table("trades").select("count", count="exact").eq("status", "open").execute()
        modules = supabase.table("module_states").select("*").execute()
        module_status = "\n".join([f"{m['module_name']}: {m['state']}" for m in (modules.data or [])])
        msg = f"SYSTEM STATUS\n\nOpen Trades: {getattr(open_trades, 'count', 0)}\n\nModules:\n{module_status}"
        send_telegram_message(chat_id, msg)
        return {"status": "ok", "action": "status_sent"}

    def cmd_estop(self, supabase, chat_id):
        supabase.table("system_logs").insert({
            "level": "error",
            "module": "telegram_estop",
            "message": "Emergency stop triggered via Telegram"
        }).execute()
        send_telegram_message(chat_id, "EMERGENCY STOP EXECUTED\nAll trading halted.")
        return {"status": "ok", "action": "estop_executed"}

    def cmd_pause(self, supabase, chat_id, module):
        if not module:
            send_telegram_message(chat_id, "Specify a module: /pause kronos_engine")
            return {"status": "error", "reason": "no_module"}
        supabase.table("module_states").update({
            "state": "paused",
            "paused_by": "telegram",
            "paused_at": "now()"
        }).eq("module_name", module).execute()
        send_telegram_message(chat_id, f"Module '{module}' paused.")
        return {"status": "ok", "action": "paused", "module": module}

    def cmd_resume(self, supabase, chat_id, module):
        if not module:
            send_telegram_message(chat_id, "Specify a module: /resume kronos_engine")
            return {"status": "error", "reason": "no_module"}
        supabase.table("module_states").update({
            "state": "active",
            "paused_by": None,
            "paused_at": None
        }).eq("module_name", module).execute()
        send_telegram_message(chat_id, f"Module '{module}' resumed.")
        return {"status": "ok", "action": "resumed", "module": module}