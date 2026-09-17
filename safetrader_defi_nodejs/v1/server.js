require('dotenv').config();
const express = require('express');
const cors = require('cors');
const path = require('path');
const logger = require('./services/logger');
const { initDatabase, loadState, saveState } = require('./db/database');
const { initBlockchain } = require('./services/blockchain');
const { initPatternDetection } = require('./services/patternDetection');
const { initTradeExecution } = require('./services/tradeExecution');
const { initPortfolio } = require('./services/portfolio');

// Initialize Express app
const app = express();
const PORT = process.env.PORT || 3000;

// Middleware
app.use(cors());
app.use(express.json());

// Global state
const state = {
    isRunning: true,
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
    manuallyStopped: false,
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
    MIN_PREDICTION_ACCURACY: parseInt(process.env.MIN_PREDICTION_ACCURACY) || 95,
    version: '11.1.0'
};

// Initialize portfolio
state.portfolio = initPortfolio(db, config);

// Initialize blockchain service
const blockchain = initBlockchain(state, config);

// Initialize trade execution
const tradeExecution = initTradeExecution(state, config, blockchain, db);

// Initialize pattern detection
const patternDetection = initPatternDetection(state, config, blockchain, tradeExecution);

// Load state on startup
loadState(db, state);

// Auto-start trading on boot
async function startTrading() {
    state.startTime = new Date();
    state.isRunning = true;
    state.manuallyStopped = false;
    logger.info('Auto-starting trading bot...');
    try {
        await blockchain.connect();
        patternDetection.startPatternDetection();
        tradeExecution.startProfitTakingMonitor();
        logger.info('Trading bot started successfully.');
    } catch (error) {
        logger.error('Failed to start trading bot:', error);
        state.isRunning = false;
    }
}

startTrading().catch(err => logger.error('Unhandled startTrading error:', err));

// Start server (headless mode)
app.listen(PORT, () => {
    logger.info(`Uniswap Quick Swap Trader v${config.version} running headless on port ${PORT}`);
    logger.info(`Mode: ${process.env.PRIVATE_KEY ? 'LIVE TRADING' : 'PAPER TRADING'}`);
});

// Graceful shutdown
process.on('SIGINT', () => {
    console.log('\nShutting down gracefully...');
    state.isRunning = false;
    state.manuallyStopped = true;
    blockchain.disconnect();
    patternDetection.stopPatternDetection();
    tradeExecution.stopProfitTakingMonitor();
    saveState(db, state);
    process.exit(0);
});

module.exports = { app, state, config, saveState };