CREATE TABLE IF NOT EXISTS bot_settings (
    key TEXT PRIMARY KEY,
    value DECIMAL
);

-- Masukkan modal awal virtual kamu, misal Rp 100.000.000
INSERT INTO bot_settings (key, value) VALUES ('virtual_balance', 100000000)
ON CONFLICT (key) DO NOTHING;