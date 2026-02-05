import psycopg2
from psycopg2 import extras
import os
from dotenv import load_dotenv

load_dotenv()

def get_connection():
    return psycopg2.connect(
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASS"),
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT")
    )

def save_signal_log(ticker, action, price, reason):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO trade_history (ticker, action, price, reason) VALUES (%s, %s, %s, %s)",
        (ticker, action, price, reason)
    )
    conn.commit()
    cur.close()
    conn.close()

def get_portfolio():
    conn = get_connection()
    cur = conn.cursor(cursor_factory=extras.RealDictCursor)
    cur.execute("SELECT * FROM my_portfolio")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows

def update_portfolio(ticker, price, lot, action):
    conn = get_connection()
    cur = conn.cursor()
    if action == "BUY":
        # Logika sederhana: jika sudah ada, update. Jika belum, insert.
        cur.execute("""
            INSERT INTO my_portfolio (ticker, avg_buy_price, total_lot)
            VALUES (%s, %s, %s)
            ON CONFLICT (ticker) DO UPDATE 
            SET avg_buy_price = (my_portfolio.avg_buy_price + EXCLUDED.avg_buy_price) / 2,
                total_lot = my_portfolio.total_lot + EXCLUDED.total_lot
        """, (ticker, price, lot))
    elif action == "SELL":
        cur.execute("DELETE FROM my_portfolio WHERE ticker = %s", (ticker,))
    
    conn.commit()
    cur.close()
    conn.close()