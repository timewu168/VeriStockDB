PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS daily_close (
  trade_date TEXT NOT NULL,
  stock_id TEXT NOT NULL,
  stock_name TEXT,
  market TEXT NOT NULL CHECK (market IN ('TWSE', 'TPEX')),
  open INTEGER,
  high INTEGER,
  low INTEGER,
  close INTEGER,
  volume INTEGER,
  amount INTEGER,
  transactions INTEGER,
  PRIMARY KEY (trade_date, stock_id, market)
);

CREATE INDEX IF NOT EXISTS idx_daily_close_date ON daily_close(trade_date);
CREATE INDEX IF NOT EXISTS idx_daily_close_stock ON daily_close(stock_id);

CREATE TABLE IF NOT EXISTS import_batches (
  batch_id TEXT PRIMARY KEY,
  dataset TEXT NOT NULL,
  market TEXT,
  period TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('OK', 'BLOCKED', 'RECHECK', 'FIXED', 'MISSING')),
  row_count INTEGER,
  error_summary TEXT,
  source_file TEXT,
  source_sha256 TEXT,
  retry_count INTEGER NOT NULL DEFAULT 0,
  archived_zip TEXT,
  checked_at TEXT NOT NULL,
  manual_approved INTEGER NOT NULL DEFAULT 0,
  manual_approved_at TEXT,
  manual_approved_reason TEXT,
  note TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_import_batches_scope
ON import_batches(dataset, market, period);

CREATE TABLE IF NOT EXISTS import_errors (
  error_id TEXT PRIMARY KEY,
  batch_id TEXT NOT NULL,
  severity TEXT NOT NULL CHECK (severity IN ('WARN', 'BLOCK')),
  code TEXT NOT NULL,
  message TEXT NOT NULL,
  sample_stock_id TEXT,
  sample_value TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY (batch_id) REFERENCES import_batches(batch_id)
);

CREATE TABLE IF NOT EXISTS data_events (
  event_id TEXT PRIMARY KEY,
  batch_id TEXT NOT NULL,
  dataset TEXT NOT NULL,
  market TEXT,
  period TEXT NOT NULL,
  stock_id TEXT,
  stock_name TEXT,
  event_type TEXT NOT NULL,
  source_open TEXT,
  source_high TEXT,
  source_low TEXT,
  source_close TEXT,
  stored_open INTEGER,
  stored_high INTEGER,
  stored_low INTEGER,
  stored_close INTEGER,
  reference_period TEXT,
  reference_value INTEGER,
  note TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY (batch_id) REFERENCES import_batches(batch_id)
);

CREATE INDEX IF NOT EXISTS idx_data_events_scope
ON data_events(dataset, market, period);

CREATE INDEX IF NOT EXISTS idx_data_events_stock
ON data_events(dataset, stock_id);

CREATE INDEX IF NOT EXISTS idx_data_events_type
ON data_events(event_type);

CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS trading_days (
  trade_date TEXT PRIMARY KEY,
  is_open INTEGER NOT NULL,
  source TEXT NOT NULL,
  note TEXT
);
