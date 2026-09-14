const Database = require('better-sqlite3');
const path = require('path');
const fs = require('fs');
const logger = require('../services/logger');

const DB_PATH = process.env.SQLITE_PATH || '../instance/db/trader.db';

const dbDir = path.dirname(DB_PATH);
if (!fs.existsSync(dbDir)) {
    fs.mkdirSync(dbDir, { recursive: true });
}

function initDatabase() {
    const db = new Database(DB_PATH);
    db.pragma('journal_mode = WAL');
    db.exec(`
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
        CREATE TABLE IF NOT EXISTS trades (
          id TEXT PRIMARY KEY,
          timestamp TEXT NOT NULL,
          token TEXT NOT NULL,
          type TEXT NOT NULL,
          price REAL NOT NULL,
          token_amount REAL NOT NULL,
          amount_eth REAL NOT NULL,
          fee REAL NOT NULL,
          gas_used INTEGER NOT NULL,
          gas_price REAL NOT NULL,
          price_impact REAL NOT NULL,
          slippage REAL NOT NULL,
          status TEXT NOT NULL,
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
          status TEXT NOT NULL,
          pnl REAL,
          trade_id TEXT,
          pattern TEXT,
          validation_count INTEGER DEFAULT 0,
          validation_successes INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS price_history (
          token TEXT NOT NULL,
          price REAL NOT NULL,
          timestamp INTEGER NOT NULL,
          PRIMARY KEY (token, timestamp)
        );
        CREATE TABLE IF NOT EXISTS swaps (
          timestamp INTEGER NOT NULL,
          token_in TEXT NOT NULL,
          token_out TEXT NOT NULL,
          amount_in REAL NOT NULL,
          amount_out REAL NOT NULL,
          pool TEXT NOT NULL
        );
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
        CREATE TABLE IF NOT EXISTS portfolio_balances (
          token TEXT PRIMARY KEY,
          amount REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS gas_prices (
          timestamp INTEGER NOT NULL,
          price REAL NOT NULL,
          PRIMARY KEY (timestamp)
        );
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

function loadState(db, state) {
    try {
        const savedState = db.prepare('SELECT * FROM app_state LIMIT 1').get();
        if (savedState) {
            state.portfolio = JSON.parse(savedState.portfolio);
            state.trades = JSON.parse(savedState.trades) || [];
            state.activePatterns = new Map(JSON.parse(savedState.active_patterns) || []);
            state.lastSwaps = JSON.parse(savedState.last_swaps) || [];
            state.prices = JSON.parse(savedState.prices) || {};
            state.priceHistory = JSON.parse(savedState.price_history) || {};
            state.observedTokens = new Set(JSON.parse(savedState.observed_tokens) || []);
            state.patternStats = JSON.parse(savedState.pattern_stats) || { totalPatterns: 0, tokensWithPatterns: 0 };
            state.lastDetectionTime = savedState.last_detection_time ? new Date(savedState.last_detection_time) : null;
            state.lastPriceUpdate = savedState.last_price_update ? new Date(savedState.last_price_update) : null;
            state.lastRecoveryTime = savedState.last_recovery_time ? new Date(savedState.last_recovery_time) : null;
            state.startTime = savedState.start_time ? new Date(savedState.start_time) : null;
            state.lastTradedToken = savedState.last_traded_token || null;
            state.lastTradeTimes = JSON.parse(savedState.last_trade_times) || {};
            state.openBuyOrders = new Map(JSON.parse(savedState.open_buy_orders) || []);
            state.predictionValidation = new Map(JSON.parse(savedState.prediction_validation) || []);
            state.pendingValidations = new Map(JSON.parse(savedState.pending_validations) || []);
        }
    } catch (e) {
        logger.error(`Error loading state: ${e.message}`);
    }
}

function saveState(db, state) {
    try {
        const stmt = db.prepare(`
            INSERT OR REPLACE INTO app_state 
            (id, portfolio, trades, active_patterns, last_swaps, prices, price_history, 
             observed_tokens, pattern_stats, last_detection_time, last_price_update, 
             last_recovery_time, start_time, last_traded_token, last_trade_times, 
             open_buy_orders, prediction_validation, pending_validations, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        `);
        stmt.run({
            id: 1,
            portfolio: JSON.stringify(state.portfolio),
            trades: JSON.stringify(state.trades),
            active_patterns: JSON.stringify(Array.from(state.activePatterns.entries())),
            last_swaps: JSON.stringify(state.lastSwaps),
            prices: JSON.stringify(state.prices),
            price_history: JSON.stringify(state.priceHistory),
            observed_tokens: JSON.stringify(Array.from(state.observedTokens)),
            pattern_stats: JSON.stringify(state.patternStats),
            last_detection_time: state.lastDetectionTime?.toISOString(),
            last_price_update: state.lastPriceUpdate?.toISOString(),
            last_recovery_time: state.lastRecoveryTime?.toISOString(),
            start_time: state.startTime?.toISOString(),
            last_traded_token: state.lastTradedToken,
            last_trade_times: JSON.stringify(state.lastTradeTimes),
            open_buy_orders: JSON.stringify(Array.from(state.openBuyOrders.entries())),
            prediction_validation: JSON.stringify(Array.from(state.predictionValidation.entries())),
            pending_validations: JSON.stringify(Array.from(state.pendingValidations.entries())),
            updated_at: new Date().toISOString()
        });
    } catch (e) {
        logger.error(`Error saving state: ${e.message}`);
    }
}

module.exports = { initDatabase, loadState, saveState };