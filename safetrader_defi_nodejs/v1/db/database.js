const Database = require('better-sqlite3');
const path = require('path');
const fs = require('fs');

const DB_PATH = process.env.SQLITE_PATH || './db/trader.db';

// Ensure directory exists
const dbDir = path.dirname(DB_PATH);
if (!fs.existsSync(dbDir)) {
    fs.mkdirSync(dbDir, { recursive: true });
}

// Initialize database
function initDatabase() {
    const db = new Database(DB_PATH);

    // Enable WAL mode for better performance
    db.pragma('journal_mode = WAL');

    // Create tables
    db.exec(`
    -- App state table
    CREATE TABLE IF NOT EXISTS app_state (
      id INTEGER PRIMARY KEY,
      portfolio TEXT NOT NULL,
      trades TEXT NOT NULL,
      active_patterns TEXT NOT NULL,
      last_swaps TEXT NOT NULL,
      prices TEXT NOT NULL,
      price_history TEXT NOT NULL,
      observed_tokens TEXT NOT NULL,
      pattern_stats TEXT NOT NULL,
      last_detection_time TEXT,
      last_price_update TEXT,
      last_recovery_time TEXT,
      start_time TEXT,
      last_traded_token TEXT,
      last_trade_times TEXT,
      open_buy_orders TEXT,
      prediction_validation TEXT,
      pending_validations TEXT,
      updated_at TEXT NOT NULL
    );

    -- Trades history table (for querying)
    CREATE TABLE IF NOT EXISTS trades (
      id TEXT PRIMARY KEY,
      timestamp TEXT NOT NULL,
      token TEXT NOT NULL,
      type TEXT NOT NULL,  -- 'buy' or 'sell'
      price REAL NOT NULL,
      token_amount REAL NOT NULL,
      amount_eth REAL NOT NULL,
      fee REAL NOT NULL,
      gas_used INTEGER NOT NULL,
      gas_price REAL NOT NULL,
      price_impact REAL NOT NULL,
      slippage REAL NOT NULL,
      status TEXT NOT NULL,  -- 'open', 'closed', 'failed'
      reason TEXT,
      pnl REAL NOT NULL,
      pattern TEXT,
      network TEXT NOT NULL,
      entry_time INTEGER NOT NULL,
      closed_at TEXT,
      tx_hash TEXT,
      validation_count INTEGER DEFAULT 0,
      validation_successes INTEGER DEFAULT 0
    );

    -- Portfolio positions table
    CREATE TABLE IF NOT EXISTS positions (
      id TEXT PRIMARY KEY,
      token TEXT NOT NULL,
      entry_price REAL NOT NULL,
      amount REAL NOT NULL,
      usd_value REAL NOT NULL,
      entry_time INTEGER NOT NULL,
      exit_time INTEGER,
      exit_price REAL,
      gas_paid REAL NOT NULL,
      fees_paid REAL NOT NULL,
      status TEXT NOT NULL,  -- 'open' or 'closed'
      pnl REAL,
      trade_id TEXT,
      pattern TEXT,
      validation_count INTEGER DEFAULT 0,
      validation_successes INTEGER DEFAULT 0
    );

    -- Price history table
    CREATE TABLE IF NOT EXISTS price_history (
      token TEXT NOT NULL,
      price REAL NOT NULL,
      timestamp INTEGER NOT NULL,
      PRIMARY KEY (token, timestamp)
    );

    -- Swap history table
    CREATE TABLE IF NOT EXISTS swaps (
      timestamp INTEGER NOT NULL,
      token_in TEXT NOT NULL,
      token_out TEXT NOT NULL,
      amount_in REAL NOT NULL,
      amount_out REAL NOT NULL,
      pool TEXT NOT NULL
    );

    -- Patterns table
    CREATE TABLE IF NOT EXISTS patterns (
      key TEXT PRIMARY KEY,
      token TEXT NOT NULL,
      type TEXT NOT NULL,
      predicted_price REAL NOT NULL,
      current_price REAL NOT NULL,
      slope REAL,
      intercept REAL,
      quadratic_term REAL,
      cubic_term REAL,
      window_size REAL NOT NULL,
      margin_of_error REAL NOT NULL,
      regression_degree INTEGER NOT NULL,
      timestamp INTEGER NOT NULL,
      predicted_profit_percent REAL NOT NULL,
      occurrences INTEGER DEFAULT 1,
      first_seen INTEGER NOT NULL,
      last_seen INTEGER NOT NULL
    );

    -- Portfolio balances table
    CREATE TABLE IF NOT EXISTS portfolio_balances (
      token TEXT PRIMARY KEY,
      amount REAL NOT NULL
    );

    -- Gas price history
    CREATE TABLE IF NOT EXISTS gas_prices (
      timestamp INTEGER NOT NULL,
      price REAL NOT NULL,
      PRIMARY KEY (timestamp)
    );

    -- Indexes for performance
    CREATE INDEX IF NOT EXISTS idx_trades_token ON trades(token);
    CREATE INDEX IF NOT EXISTS idx_trades_timestamp ON trades(timestamp);
    CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status);
    CREATE INDEX IF NOT EXISTS idx_positions_token ON positions(token);
    CREATE INDEX IF NOT EXISTS idx_positions_status ON positions(status);
    CREATE INDEX IF NOT EXISTS idx_price_history_token ON price_history(token);
    CREATE INDEX IF NOT EXISTS idx_price_history_timestamp ON price_history(timestamp);
    CREATE INDEX IF NOT EXISTS idx_swaps_timestamp ON swaps(timestamp);
    CREATE INDEX IF NOT EXISTS idx_patterns_token ON patterns(token);
  `);

    return db;
}

// Helper functions for database operations
function getTrades(db, limit = 20) {
    const stmt = db.prepare(`
    SELECT * FROM trades 
    ORDER BY timestamp DESC 
    LIMIT ?
  `);
    return stmt.all(limit);
}

function getPositions(db, status = null) {
    let query = 'SELECT * FROM positions';
    const params = [];

    if (status) {
        query += ' WHERE status = ?';
        params.push(status);
    }

    query += ' ORDER BY entry_time DESC';
    const stmt = db.prepare(query);
    return stmt.all(...params);
}

function getPriceHistory(db, token, limit = 100) {
    const stmt = db.prepare(`
    SELECT * FROM price_history 
    WHERE token = ? 
    ORDER BY timestamp DESC 
    LIMIT ?
  `);
    return stmt.all(token, limit);
}

function getSwaps(db, limit = 10) {
    const stmt = db.prepare(`
    SELECT * FROM swaps 
    ORDER BY timestamp DESC 
    LIMIT ?
  `);
    return stmt.all(limit);
}

function getPatterns(db, token = null) {
    let query = 'SELECT * FROM patterns';
    const params = [];

    if (token) {
        query += ' WHERE token = ?';
        params.push(token);
    }

    query += ' ORDER BY last_seen DESC';
    const stmt = db.prepare(query);
    return stmt.all(...params);
}

function getPortfolioBalances(db) {
    const stmt = db.prepare('SELECT * FROM portfolio_balances');
    return stmt.all();
}

function getPortfolioSummary(db) {
    const stmt = db.prepare(`
    SELECT 
      (SELECT amount FROM portfolio_balances WHERE token = 'WETH') as weth_balance,
      (SELECT COUNT(*) FROM positions WHERE status = 'open') as open_positions,
      (SELECT COUNT(*) FROM trades WHERE status = 'closed' AND pnl > 0) as winning_trades,
      (SELECT COUNT(*) FROM trades WHERE status = 'closed' AND pnl < 0) as losing_trades,
      (SELECT COUNT(*) FROM trades WHERE status = 'failed') as failed_trades,
      (SELECT SUM(pnl) FROM trades WHERE status = 'closed') as realized_pnl,
      (SELECT SUM(pnl) FROM positions WHERE status = 'open') as unrealized_pnl
    FROM dual
  `);
    return stmt.get();
}

module.exports = {
    initDatabase,
    getTrades,
    getPositions,
    getPriceHistory,
    getSwaps,
    getPatterns,
    getPortfolioBalances,
    getPortfolioSummary
};