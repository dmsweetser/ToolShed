const express = require('express');
const router = express.Router();

module.exports = function (state, config, blockchain, patternDetection, tradeExecution, saveState) {

    // ======================
    // BOT CONTROL ENDPOINTS
    // ======================

    // Start bot
    router.post('/start', async (req, res) => {
        try {
            if (state.isRunning) {
                return res.status(400).json({ success: false, message: 'Trading is already running.' });
            }

            state.currentChainKey = 'arbitrum';
            state.isRunning = true;
            state.wasRunningBeforeReload = true;
            state.startTime = new Date();
            state.lastTradedToken = null;
            state.openBuyOrders.clear();
            state.reconnectAttempts = 0;
            state.predictionValidation.clear();
            state.pendingValidations.clear();

            // Connect to blockchain
            await blockchain.connect();

            // Start various monitors
            await blockchain.updateGasPrice();
            patternDetection.startPatternDetection();
            tradeExecution.startProfitTakingMonitor();

            // Save state
            saveState();

            res.json({
                success: true,
                message: 'Trading started successfully',
                isRunning: true,
                mode: process.env.PRIVATE_KEY ? 'LIVE' : 'PAPER'
            });
        } catch (error) {
            state.isRunning = false;
            console.error('Start bot error:', error);
            res.status(500).json({ success: false, message: error.message || 'Failed to start bot' });
        }
    });

    // Stop bot
    router.post('/stop', async (req, res) => {
        try {
            if (!state.isRunning) {
                return res.status(400).json({ success: false, message: 'Trading is not running.' });
            }

            state.isRunning = false;
            state.wasRunningBeforeReload = false;
            state.manuallyStopped = true;

            // Stop all monitors
            patternDetection.stopPatternDetection();
            tradeExecution.stopProfitTakingMonitor();
            await blockchain.disconnect();
            state.openBuyOrders.clear();

            // Save state
            saveState();

            res.json({ success: true, message: 'Trading stopped successfully', isRunning: false });
        } catch (error) {
            console.error('Stop bot error:', error);
            res.status(500).json({ success: false, message: error.message || 'Failed to stop bot' });
        }
    });

    // Reset app
    router.post('/reset', (req, res) => {
        try {
            if (state.isRunning) {
                return res.status(400).json({ success: false, message: 'Cannot reset while bot is running. Stop the bot first.' });
            }

            // Reset all state
            state.trades = [];
            state.portfolio = {
                balances: { 'WETH': config.STARTING_ETH },
                positions: [],
                realizedPnL: 0,
                unrealizedPnL: 0,
                gasSpent: 0,
                feesPaid: 0,
                startingEth: config.STARTING_ETH,
                currentEth: config.STARTING_ETH,
                equityHistory: [{ timestamp: Date.now(), ethValue: config.STARTING_ETH }],
                totalTrades: 0,
                winningTrades: 0,
                losingTrades: 0,
                failedTrades: 0,
                totalFees: 0
            };
            state.activePatterns.clear();
            state.patternStats = { totalPatterns: 0, tokensWithPatterns: 0 };
            state.observedTokens.clear();
            state.prices = {};
            state.priceHistory = {};
            state.lastTradedToken = null;
            state.lastTradeTimes = {};
            state.openBuyOrders.clear();
            state.lastDetectionTime = null;
            state.lastSwaps = [];
            state.lastSwapDetected = null;
            state.wasRunningBeforeReload = false;
            state.predictionValidation.clear();
            state.pendingValidations.clear();
            state.lastRecoveryTime = null;

            // Clear database
            const db = require('../db/database');
            db.initDatabase().exec('DELETE FROM app_state');
            db.initDatabase().exec('DELETE FROM trades');
            db.initDatabase().exec('DELETE FROM positions');
            db.initDatabase().exec('DELETE FROM price_history');
            db.initDatabase().exec('DELETE FROM swaps');
            db.initDatabase().exec('DELETE FROM patterns');
            db.initDatabase().exec('DELETE FROM portfolio_balances');

            // Save empty state
            saveState();

            res.json({ success: true, message: 'App has been reset!' });
        } catch (error) {
            console.error('Reset error:', error);
            res.status(500).json({ success: false, message: error.message || 'Failed to reset app' });
        }
    });

    // ======================
    // STATE ENDPOINTS
    // ======================

    // Get full app state
    router.get('/state', (req, res) => {
        try {
            const portfolioUI = require('../services/portfolio').initPortfolioService(state, config).updatePortfolioUI();
            const tradeStats = require('../services/portfolio').initPortfolioService(state, config).updateTradeStatistics();
            const positionDetails = require('../services/portfolio').initPortfolioService(state, config).updatePositionDetails();

            res.json({
                success: true,
                state: {
                    isRunning: state.isRunning,
                    walletConnected: state.walletConnected,
                    currentNetwork: state.currentNetwork,
                    currentGasPrice: state.currentGasPrice || config.MAX_GAS_PRICE,
                    prices: state.prices,
                    observedTokens: Array.from(state.observedTokens),
                    patternStats: state.patternStats,
                    lastDetectionTime: state.lastDetectionTime?.toISOString(),
                    lastPriceUpdate: state.lastPriceUpdate?.toISOString(),
                    lastRecoveryTime: state.lastRecoveryTime?.toISOString(),
                    startTime: state.startTime?.toISOString(),
                    uptime: state.startTime ? getUptime(state.startTime) : '00:00:00',
                    tradeAmount: require('../services/tradeExecution').initTradeExecution(state, config).calculateTradeAmount()
                },
                portfolio: portfolioUI,
                tradeStats: tradeStats,
                positions: positionDetails,
                recentTrades: state.trades.slice(0, 20).map(trade => ({
                    timestamp: trade.timestamp,
                    token: trade.token,
                    type: trade.type,
                    price: trade.price,
                    tokenAmount: trade.tokenAmount,
                    amountETH: trade.amountETH,
                    pnl: trade.pnl,
                    pattern: trade.pattern,
                    status: trade.status
                })),
                lastSwaps: state.lastSwaps.slice(0, 10)
            });
        } catch (error) {
            console.error('Error getting state:', error);
            res.status(500).json({ success: false, message: error.message });
        }
    });

    // Get portfolio summary
    router.get('/portfolio/summary', (req, res) => {
        try {
            const portfolioService = require('../services/portfolio').initPortfolioService(state, config);
            const summary = portfolioService.getPortfolioSummary();
            res.json({ success: true, ...summary });
        } catch (error) {
            console.error('Error getting portfolio summary:', error);
            res.status(500).json({ success: false, message: error.message });
        }
    });

    // Get portfolio balances
    router.get('/portfolio/balances', (req, res) => {
        try {
            const portfolioService = require('../services/portfolio').initPortfolioService(state, config);
            const balances = portfolioService.getPortfolioBalances();
            res.json({ success: true, balances });
        } catch (error) {
            console.error('Error getting portfolio balances:', error);
            res.status(500).json({ success: false, message: error.message });
        }
    });

    // Get open positions
    router.get('/portfolio/positions', (req, res) => {
        try {
            const portfolioService = require('../services/portfolio').initPortfolioService(state, config);
            const positions = portfolioService.getOpenPositions();
            res.json({ success: true, positions });
        } catch (error) {
            console.error('Error getting open positions:', error);
            res.status(500).json({ success: false, message: error.message });
        }
    });

    // Get trade history
    router.get('/trades', (req, res) => {
        try {
            const limit = parseInt(req.query.limit) || 20;
            const portfolioService = require('../services/portfolio').initPortfolioService(state, config);
            const trades = portfolioService.getTradeHistory(limit);
            res.json({ success: true, trades });
        } catch (error) {
            console.error('Error getting trade history:', error);
            res.status(500).json({ success: false, message: error.message });
        }
    });

    // Get recent swaps
    router.get('/swaps', (req, res) => {
        try {
            const limit = parseInt(req.query.limit) || 10;
            const swaps = state.lastSwaps.slice(0, limit);
            res.json({ success: true, swaps });
        } catch (error) {
            console.error('Error getting swaps:', error);
            res.status(500).json({ success: false, message: error.message });
        }
    });

    // Get patterns
    router.get('/patterns', (req, res) => {
        try {
            const patterns = Array.from(state.activePatterns.values());
            res.json({ success: true, patterns, stats: state.patternStats });
        } catch (error) {
            console.error('Error getting patterns:', error);
            res.status(500).json({ success: false, message: error.message });
        }
    });

    // Get gas price
    router.get('/gas-price', (req, res) => {
        try {
            res.json({ success: true, gasPrice: state.currentGasPrice || config.MAX_GAS_PRICE });
        } catch (error) {
            console.error('Error getting gas price:', error);
            res.status(500).json({ success: false, message: error.message });
        }
    });

    // ======================
    // TRADE ENDPOINTS
    // ======================

    // Execute trade
    router.post('/trade/execute', async (req, res) => {
        try {
            const { token, action, patternDescription, amountWETH, pattern } = req.body;

            if (!token || !action) {
                return res.status(400).json({ success: false, message: 'Token and action are required' });
            }

            if (!['buy', 'sell'].includes(action)) {
                return res.status(400).json({ success: false, message: 'Invalid action. Must be buy or sell' });
            }

            const trade = await tradeExecution.executeTrade(token, action, patternDescription, amountWETH, pattern);

            if (!trade) {
                return res.json({ success: false, message: 'Trade execution failed' });
            }

            // Save state
            saveState();

            res.json({ success: true, trade });
        } catch (error) {
            console.error('Trade execution error:', error);
            res.status(500).json({ success: false, message: error.message || 'Trade execution failed' });
        }
    });

    // Get trade amount
    router.get('/trade/amount', (req, res) => {
        try {
            const tradeExecutionService = require('../services/tradeExecution').initTradeExecution(state, config);
            const amount = tradeExecutionService.calculateTradeAmount();
            res.json({ success: true, amount });
        } catch (error) {
            console.error('Error getting trade amount:', error);
            res.status(500).json({ success: false, message: error.message });
        }
    });

    // ======================
    // WALLET ENDPOINTS
    // ======================

    // Connect wallet (for live trading)
    router.post('/wallet/connect', async (req, res) => {
        try {
            if (!process.env.PRIVATE_KEY) {
                return res.status(400).json({
                    success: false,
                    message: 'No PRIVATE_KEY in .env. Running in paper trading mode.'
                });
            }

            const provider = blockchain.getProvider();
            if (!provider) {
                return res.status(400).json({ success: false, message: 'Blockchain not connected' });
            }

            const signer = new ethers.Wallet(process.env.PRIVATE_KEY, provider);
            const address = await signer.getAddress();

            state.walletConnected = true;
            state.signer = signer;

            // Check balance
            const wethAddress = require('../config/config').NETWORK_TOKENS.arbitrum.WETH;
            const wethContract = new ethers.Contract(wethAddress, require('../config/config').ERC20_ABI, provider);
            const wethBalance = await wethContract.balanceOf(address);
            const ethBalance = await provider.getBalance(address);

            res.json({
                success: true,
                walletConnected: true,
                address,
                ethBalance: ethers.formatEther(ethBalance),
                wethBalance: ethers.formatEther(wethBalance)
            });
        } catch (error) {
            console.error('Wallet connection error:', error);
            res.status(500).json({ success: false, message: error.message || 'Failed to connect wallet' });
        }
    });

    // ======================
    // CONFIGURATION ENDPOINTS
    // ======================

    // Get configuration
    router.get('/config', (req, res) => {
        try {
            res.json({
                success: true,
                config: {
                    BLOCKCHAIN_NETWORK: config.BLOCKCHAIN_NETWORK,
                    STARTING_ETH: config.STARTING_ETH,
                    TRADE_AMOUNT_PERCENT: config.TRADE_AMOUNT_PERCENT,
                    MIN_TRADE_AMOUNT_ETH: config.MIN_TRADE_AMOUNT_ETH,
                    MAX_TRADES: config.MAX_TRADES,
                    MIN_PROFIT_PERCENT: config.MIN_PROFIT_PERCENT,
                    MAX_SLIPPAGE: config.MAX_SLIPPAGE,
                    MAX_GAS_PRICE: config.MAX_GAS_PRICE,
                    WINDOW_SIZE: config.WINDOW_SIZE,
                    MARGIN_OF_ERROR: config.MARGIN_OF_ERROR,
                    REGRESSION_DEGREE: config.REGRESSION_DEGREE,
                    PREDICTION_VALIDATION_COUNT: config.PREDICTION_VALIDATION_COUNT,
                    MIN_PREDICTION_ACCURACY: config.MIN_PREDICTION_ACCURACY,
                    mode: process.env.PRIVATE_KEY ? 'LIVE' : 'PAPER'
                }
            });
        } catch (error) {
            console.error('Error getting config:', error);
            res.status(500).json({ success: false, message: error.message });
        }
    });

    // ======================
    // UTILITY ENDPOINTS
    // ======================

    // Get uptime
    function getUptime(startTime) {
        const now = new Date();
        const diff = now - startTime;
        const h = Math.floor(diff / (1000 * 60 * 60)).toString().padStart(2, '0');
        const m = Math.floor((diff % (1000 * 60 * 60)) / (1000 * 60)).toString().padStart(2, '0');
        const s = Math.floor((diff % (1000 * 60)) / 1000).toString().padStart(2, '0');
        return `${h}:${m}:${s}`;
    }

    // Health check
    router.get('/health', (req, res) => {
        res.json({
            success: true,
            status: 'healthy',
            isRunning: state.isRunning,
            walletConnected: state.walletConnected,
            blockchainConnected: state.activeSession?.connected || false,
            uptime: state.startTime ? getUptime(state.startTime) : null
        });
    });

    return router;
};