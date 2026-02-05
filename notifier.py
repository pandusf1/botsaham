import httpx
import os
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("8573171957:AAHgHuUBEgblCtCg0BxzzZhNKkOqx7R4GJc")
CHAT_ID = os.getenv("1280983606")

async def send_telegram_msg(message: str):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(url, json=payload)
            return response.json()
        except Exception as e:
            print(f"Gagal kirim Telegram: {e}")