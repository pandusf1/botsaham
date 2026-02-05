import os
import asyncio
import time
import psycopg2
from psycopg2 import extras
import httpx
import pandas as pd
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from tradingview_ta import TA_Handler, Interval
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import datetime

# 1. LOAD CONFIGURATION
load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("MY_CHAT_ID")

# 2. DATABASE LAYER
def get_connection():
    return psycopg2.connect(
        dbname=os.getenv("DB_NAME"), 
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASS"), 
        host=os.getenv("DB_HOST"), 
        port=os.getenv("DB_PORT")
    )

def get_balance():
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT value FROM bot_settings WHERE key = 'virtual_balance'")
        val = cur.fetchone()[0]
        cur.close()
        conn.close()
        return float(val)
    except Exception as e:
        print(f"Error Get Balance: {e}")
        return 0

def update_balance(amount):
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("UPDATE bot_settings SET value = value + %s WHERE key = 'virtual_balance'", (amount,))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Error Update Balance: {e}")

def get_portfolio():
    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=extras.RealDictCursor)
        cur.execute("SELECT * FROM my_portfolio")
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return rows
    except Exception as e:
        print(f"Error Get Portfolio: {e}")
        return []

def save_signal_log(ticker, action, price, reason):
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO trade_history (ticker, action, price, reason) VALUES (%s, %s, %s, %s)",
            (ticker, action, price, reason)
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"DB Error (Log): {e}")

# 3. NOTIFIER LAYER
async def send_telegram_msg(message: str):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown"}
    async with httpx.AsyncClient() as client:
        try:
            await client.post(url, json=payload)
        except Exception as e:
            print(f"Telegram Error: {e}")

# 4. TRADING CALCULATOR
def calculate_lot(price, allocation_amount):
    if allocation_amount <= 0: return 0
    available_lots = int(allocation_amount / (price * 100))
    return available_lots

# 5. TRADING LOGIC (SCALED ENTRY 30/70)
def process_trade_logic(ticker, action, current_price):
    portfolio = get_portfolio()
    stock_in_porto = next((item for item in portfolio if item['ticker'] == ticker), None)
    balance = get_balance()
    
    TOTAL_CAPITAL = 100000000 # Contoh Rp 100jt
    MAX_PER_STOCK = TOTAL_CAPITAL * 0.20 

    conn = get_connection()
    cur = conn.cursor()

    try:
        if action == "BUY":
            if not stock_in_porto:
                nominal_buy = MAX_PER_STOCK * 0.30
                lot_to_buy = calculate_lot(current_price, nominal_buy)
                total_cost = lot_to_buy * current_price * 100

                if balance >= total_cost and lot_to_buy > 0:
                    cur.execute("""
                        INSERT INTO my_portfolio (ticker, avg_buy_price, total_lot, entry_phase, last_buy_price)
                        VALUES (%s, %s, %s, 1, %s)
                    """, (ticker, current_price, lot_to_buy, current_price))
                    update_balance(-total_cost)
                    conn.commit()
                    return True, f"ENTRY TAHAP 1: Beli {lot_to_buy} Lot. Sisa Saldo: Rp {get_balance():,.0f}"
                return False, "Saldo tidak cukup"

            elif stock_in_porto['entry_phase'] == 1:
                if current_price >= (float(stock_in_porto['avg_buy_price']) * 1.02):
                    nominal_buy = MAX_PER_STOCK * 0.70
                    lot_to_buy = calculate_lot(current_price, nominal_buy)
                    total_cost = lot_to_buy * current_price * 100
                    
                    if balance >= total_cost and lot_to_buy > 0:
                        cur.execute("""
                            UPDATE my_portfolio SET 
                            avg_buy_price = ((avg_buy_price * total_lot) + (%s * %s)) / (total_lot + %s),
                            total_lot = total_lot + %s, entry_phase = 2, last_buy_price = %s
                            WHERE ticker = %s
                        """, (current_price, lot_to_buy, lot_to_buy, lot_to_buy, current_price, ticker))
                        update_balance(-total_cost)
                        conn.commit()
                        return True, f"ENTRY TAHAP 2 (Pyramid): Tambah {lot_to_buy} Lot. Sisa Saldo: Rp {get_balance():,.0f}"
            
        elif action == "SELL":
            if stock_in_porto:
                total_return = stock_in_porto['total_lot'] * current_price * 100
                cur.execute("DELETE FROM my_portfolio WHERE ticker = %s", (ticker,))
                update_balance(total_return)
                conn.commit()
                return True, f"SELL ALL: Cair Rp {total_return:,.0f}. Sisa Saldo: Rp {get_balance():,.0f}"

        return False, "No Execution"
    except Exception as e: 
        return False, f"Error Logic: {e}"
    finally:
        cur.close()
        conn.close()

# 6. SCANNER & ANALYSIS
def analyze_god_mode(symbol):
    try:
        h15 = TA_Handler(symbol=symbol, exchange="IDX", screener="indonesia", interval=Interval.INTERVAL_15_MINUTES, timeout=10)
        hD = TA_Handler(symbol=symbol, exchange="IDX", screener="indonesia", interval=Interval.INTERVAL_1_DAY, timeout=10)
        
        i15 = h15.get_analysis().indicators
        iD = hD.get_analysis().indicators
        price = i15["close"]

        is_uptrend = (i15["EMA20"] > i15["EMA50"]) and (iD["EMA20"] > iD["EMA50"])
        is_momentum = 40 <= i15["RSI"] <= 65

        if is_uptrend and is_momentum:
            return "BUY", price, "Trend & Momentum Confirmed"
        elif price < i15["EMA50"]:
            return "SELL", price, "Trend Patah (Below EMA50)"
        return "HOLD", price, ""
    except:
        return "SKIP", 0, ""

def get_all_idx_stocks():
    print("🔄 Mengambil daftar 500+ saham dari database publik...")
    try:
        url = "https://raw.githubusercontent.com/manbeee/indonesia-stock-list/main/stock_list.csv"
        df = pd.read_csv(url)
        tickers = df['code'].tolist() 
        return tickers
    except Exception as e:
        print(f"⚠️ Gagal ambil list otomatis, menggunakan list backup: {e}")
        return ["ASII", "BBRI", "TLKM", "GOTO", "UNVR", "BBCA", "BMRI", "ADRO"]

async def market_scanner(stock_list):
    print(f"🚀 Scanner aktif memantau {len(stock_list)} saham...")
    while True:
        for stock in stock_list:
            action, price, reason = analyze_god_mode(stock)
            if action in ["BUY", "SELL"]:
                success, msg = process_trade_logic(stock, action, price)
                if success:
                    save_signal_log(stock, action, price, f"{reason} | {msg}")
                    await send_telegram_msg(f"✨ *{action} SIGNAL*\nStock: {stock}\nPrice: {price}\nStatus: {msg}")
            
            await asyncio.sleep(0.5)
        
        print("✅ Scan Cycle Selesai. Istirahat 15 Menit...")
        await asyncio.sleep(900)

# 7. TELEGRAM COMMANDS
async def porto_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    p = get_portfolio()
    bal = get_balance()
    msg = f"💰 *SALDO VIRTUAL:* Rp {bal:,.0f}\n\n"
    if not p:
        msg += "Portofolio Kosong."
    else:
        for i in p:
            msg += f"🔹 *{i['ticker']}*\n   {i['total_lot']} Lot | Phase {i['entry_phase']}\n   Avg: Rp {float(i['avg_buy_price']):,.0f}\n"
    await update.message.reply_markdown(msg)

async def history_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=extras.RealDictCursor)
        cur.execute("SELECT * FROM trade_history ORDER BY id DESC LIMIT 10")
        rows = cur.fetchall()
        cur.close()
        conn.close()

        if not rows:
            await update.message.reply_text("Belum ada riwayat transaksi.")
            return

        msg = "📜 *10 TRANSAKSI TERAKHIR*\n━━━━━━━━━━━━━━━\n"
        for r in rows:
            icon = "🟢" if r['action'] == "BUY" else "🔴"
            time_str = r['created_at'].strftime("%H:%M") if r['created_at'] else "--:--"
            msg += f"{icon} {time_str} | *{r['ticker']}* {r['action']} @{r['price']}\n"
        
        await update.message.reply_markdown(msg)
    except Exception as e:
        await update.message.reply_text(f"Error History: {e}")

async def send_daily_recap():
    p = get_portfolio()
    bal = get_balance()
    total_asset_value = 0
    msg = f"🏁 *REKAP AKHIR HARI* ({datetime.now().strftime('%d %b %Y')})\n━━━━━━━━━━━━━━━\n"
    
    if not p:
        msg += "Hari ini tidak ada posisi saham yang dipegang.\n"
    else:
        msg += "🏠 *Posisi Portofolio:*\n"
        for i in p:
            val = i['total_lot'] * float(i['avg_buy_price']) * 100
            total_asset_value += val
            msg += f"• {i['ticker']}: {i['total_lot']} Lot (Nilai: Rp {val:,.0f})\n"

    total_equity = bal + total_asset_value
    msg += f"\n💰 *Ringkasan Dana:*\n💵 Cash: Rp {bal:,.0f}\n📈 Saham: Rp {total_asset_value:,.0f}\n📊 Total Equity: Rp {total_equity:,.0f}\n"
    msg += "━━━━━━━━━━━━━━━\nBot akan beristirahat."
    await send_telegram_msg(msg)

async def send_heartbeat():
    bal = get_balance()
    now = datetime.now().strftime("%H:%M")
    msg = f"🤖 *Bot Heartbeat* [{now}]\nStatus: Active ✅\nBalance: Rp {bal:,.0f}"
    await send_telegram_msg(msg)
        
# 8. MAIN RUNNER
async def main():
    print("🤖 Menginisialisasi Saham Euyy V2: THE GOD MODE...")
    
    stocks = get_all_idx_stocks()
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", lambda u, c: u.message.reply_text("Bot Aktif! Pakai /porto atau /history")))
    app.add_handler(CommandHandler("porto", porto_cmd))
    app.add_handler(CommandHandler("history", history_cmd))

    scheduler = AsyncIOScheduler(timezone="Asia/Jakarta")
    scheduler.add_job(send_daily_recap, 'cron', day_of_week='mon-fri', hour=16, minute=15)
    scheduler.add_job(send_heartbeat, 'cron', day_of_week='mon-fri', hour='9-16', minute=0)
    scheduler.start()

    await app.initialize()
    await app.start()
    
    polling_task = asyncio.create_task(app.updater.start_polling())
    scanner_task = asyncio.create_task(market_scanner(stocks))
    
    print("✅ Bot Telegram, Scheduler & Scanner Berjalan!")
    await asyncio.gather(polling_task, scanner_task)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("\nBot dimatikan.")