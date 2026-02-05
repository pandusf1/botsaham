from database import get_portfolio, update_portfolio, get_connection

def process_trade_logic(ticker, action, current_price):
    portfolio = get_portfolio()
    # Cari apakah saham sudah ada di porto
    stock_in_porto = next((item for item in portfolio if item['ticker'] == ticker), None)
    
    if action == "BUY":
        # JIKA BELUM PUNYA (Entry Tahap 1 - 30%)
        if not stock_in_porto:
            if len(portfolio) >= 5: return False, "Porto Penuh"
            
            lot_tahap_1 = 30 # Misal 30 lot (30%)
            # Simpan ke DB dengan entry_phase = 1
            execute_db_entry(ticker, current_price, lot_tahap_1, 1)
            return True, f"Entry Tahap 1 (30%) Berhasil di {current_price}"

        # JIKA SUDAH PUNYA (Cek untuk Tahap 2 - Tambah 70%)
        elif stock_in_porto['entry_phase'] == 1:
            avg_buy = float(stock_in_porto['avg_buy_price'])
            # Syarat Tahap 2: Harga naik +2% dari pembelian pertama
            if current_price >= (avg_buy * 1.02):
                lot_tahap_2 = 70 # Tambah 70 lot
                execute_db_entry(ticker, current_price, lot_tahap_2, 2)
                return True, f"Entry Tahap 2 (70%) Berhasil! Harga sudah naik +2%"
            else:
                return False, "Menunggu harga naik +2% untuk Scale-up"

    elif action == "SELL":
        if stock_in_porto:
            execute_db_exit(ticker)
            return True, f"Jual Seluruh Posisi {ticker} di {current_price}"
            
    return False, "No Action"

def execute_db_entry(ticker, price, lot, phase):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO my_portfolio (ticker, avg_buy_price, total_lot, entry_phase, last_buy_price)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (ticker) DO UPDATE SET
            avg_buy_price = (my_portfolio.avg_buy_price + EXCLUDED.avg_buy_price) / 2,
            total_lot = my_portfolio.total_lot + EXCLUDED.total_lot,
            entry_phase = EXCLUDED.entry_phase,
            last_buy_price = EXCLUDED.last_buy_price
    """, (ticker, price, lot, phase, price))
    conn.commit()
    cur.close()
    conn.close()

def execute_db_exit(ticker):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM my_portfolio WHERE ticker = %s", (ticker,))
    conn.commit()
    cur.close()
    conn.close()