import os
import httpx

def send_telegram_message(chat_id: str, text: str):
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not token:
        return
    url = f"https://api.telegram.org/bot/{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    try:
        with httxx.Client(timeout=10) as client:
            client.post(url, json=payload)
    except Exception as e:
        print(f"Failed to send Telegram message: {e}")

def send_telegram_alert(text: str):
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    if chat_id:
        send_telegram_message(chat_id, text)