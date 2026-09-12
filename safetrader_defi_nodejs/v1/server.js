require('dotenv').config();
const express = require('express');
const cors = require('cors');
const path = require('path');
const { initDatabase } = require('./db/database');
const { initBlockchain } = require('./services/blockchain');
const { initPatternDetection } = require('./services/patternDetection');
const { initTradeExecution } = require('./services/tradeExecution');
const { initPortfolio } = require('./services/portfolio');
const apiRouter = require('./routes/api');

// Initialize Express app
const app = express();
const PORT = process.env.PORT || 3000;

// Middleware
app.use(cors());
app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

// Global state
const state = {
    isRunning: false,
    walletConnected: false,
    provider: null,
    signer: null,
    currentNetwork: process.env.BLOCKCHAIN_NETWORK || 'arbitrum',
    currentGasPrice: 0.02,
    prices: {},
    priceHistory: {},
    trades: [],
    activePatterns: new Map(),
    lastSwaps: [],
    portfolio: null,
    observedTokens: new Set(),
    patternStats: { totalPatterns: 0, tokensWithPatterns: 0 },
    openBuyOrders: new Map(),
    predictionValidation: new Map(),
    pendingValidations: new Map(),
    lastDetectionTime: null,
    lastPriceUpdate: null,
    lastRecoveryTime: null,
    startTime: null,
    lastTradedToken: null,
    lastTradeTimes: {},
    sessionSerial: 0,
    activeSession: null,
    currentRpcIndex: 0,
    manuallyStopped: true,
    reconnectAttempts: 0,
    maxReconnectAttempts: parseInt(process.env.MAX_RECONNECT_ATTEMPTS) || 10,
    reconnectDelay: parseInt(process.env.RECONNECT_DELAY) || 1000
};

// Initialize database
const db = initDatabase();

// Initialize services
const config = {
    BLOCKCHAIN_NETWORK: process.env.BLOCKCHAIN_NETWORK || 'arbitrum',
    UNISWAP_VERSION: process.env.UNISWAP_VERSION || 'v3',
    STARTING_ETH: parseFloat(process.env.STARTING_ETH) || 0.01,
    TRADE_AMOUNT_PERCENT: parseInt(process.env.TRADE_AMOUNT_PERCENT) || 10,
    MIN_TRADE_AMOUNT_ETH: parseFloat(process.env.MIN_TRADE_AMOUNT_ETH) || 0.001,
    MAX_TRADES: parseInt(process.env.MAX_TRADES) || 10,
    TRADE_COOLDOWN: 60,
    MIN_PRICE_CHANGE: 1,
    MIN_TIME_WINDOW: 5,
    MAX_TIME_WINDOW: 60,
    MIN_OCCURRENCES: 2,
    MIN_PROFIT_PERCENT: parseFloat(process.env.MIN_PROFIT_PERCENT) || 0.5,
    MAX_SLIPPAGE: parseFloat(process.env.MAX_SLIPPAGE) || 0.5,
    MAX_GAS_PRICE: parseInt(process.env.MAX_GAS_PRICE) || 500,
    GAS_LIMIT: parseInt(process.env.GAS_LIMIT) || 300000,
    PREVENT_SEQUENTIAL_TRADES: true,
    PRICE_HISTORY_DURATION: parseInt(process.env.PRICE_HISTORY_DURATION) || 24,
    MAX_PRICE_HISTORY: parseInt(process.env.MAX_PRICE_HISTORY) || 1000,
    WINDOW_SIZE: parseInt(process.env.WINDOW_SIZE) || 90,
    MARGIN_OF_ERROR: parseFloat(process.env.MARGIN_OF_ERROR) || 3,
    REGRESSION_DEGREE: parseInt(process.env.REGRESSION_DEGREE) || 3,
    MIN_LIQUIDITY: 50000,
    PATTERN_MODE: 'regression',
    PREDICTION_VALIDATION_COUNT: parseInt(process.env.PREDICTION_VALIDATION_COUNT) || 3,
    MIN_PREDICTION_ACCURACY: parseInt(process.env.MIN_PREDICTION_ACCURACY) || 95
};

// Initialize portfolio
state.portfolio = initPortfolio(db, config);

// Initialize blockchain service
const blockchain = initBlockchain(state, config);

// Initialize pattern detection
const patternDetection = initPatternDetection(state, config, blockchain);

// Initialize trade execution
const tradeExecution = initTradeExecution(state, config, blockchain, db);

// Load state from database
function loadState() {
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
        console.error('Error loading state:', e);
    }
}

// Save state to database
function saveState() {
    try {
        const stmt = db.prepare(`
      INSERT OR REPLACE INTO app_state 
      (id, portfolio, trades, active_patterns, last_swaps, prices, price_history, 
       observed_tokens, pattern_stats, last_detection_time, last_price_update, 
       last_recovery_time, start_time, last_traded_token, last_trade_times, 
       open_buy_orders, prediction_validation, pending_validations, updated_at)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
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
            pending_validations: JSON.stringify(Array.from(state.pendingValidations.entries()))
        });
    } catch (e) {
        console.error('Error saving state:', e);
    }
}

// API Routes
app.use('/api', apiRouter(state, config, blockchain, patternDetection, tradeExecution, saveState));

// Serve frontend
app.get('/', (req, res) => {
    res.sendFile(path.join(__dirname, 'public', 'index.html'));
});

// Start server
app.listen(PORT, () => {
    console.log(`Uniswap Quick Swap Trader v${config.version || '11.1.0'} running on port ${PORT}`);
    console.log(`Mode: ${process.env.PRIVATE_KEY ? 'LIVE TRADING' : 'PAPER TRADING'}`);

    // Load state on startup
    loadState();

    // Initialize blockchain connection if running
    if (state.isRunning) {
        blockchain.connect();
    }
});

// Graceful shutdown
process.on('SIGINT', () => {
    console.log('\nShutting down gracefully...');
    state.isRunning = false;
    state.manuallyStopped = true;
    blockchain.disconnect();
    saveState();
    process.exit(0);
});

module.exports = { app, state, config, saveState };