// ======================
// UNISWAP QUICK SWAP TRADER - FRONTEND (AJAX)
// ======================

const API_BASE = '/api';
let pollInterval;
let isRunning = false;

// ======================
// UTILITY FUNCTIONS
// ======================

function formatNumber(num, decimals = 8) {
    if (num === null || num === undefined) return '0';
    return num.toFixed(decimals);
}

function formatETH(value, decimals = 8) {
    if (value === null || value === undefined) return '0.00000000 WETH';
    return formatNumber(value, decimals) + ' WETH';
}

function formatPercent(value, decimals = 2) {
    if (value === null || value === undefined) return '0.00%';
    return value.toFixed(decimals) + '%';
}

function safeSetText(elementId, text) {
    const el = document.getElementById(elementId);
    if (el) el.textContent = text;
}

function safeSetHTML(elementId, html) {
    const el = document.getElementById(elementId);
    if (el) el.innerHTML = html;
}

// ======================
// TOAST NOTIFICATIONS
// ======================

function showToast(type, message, duration = 5000) {
    try {
        const container = document.getElementById('toastContainer');
        if (!container) return;

        const toast = document.createElement('div');
        toast.className = `toast ${type}`;
        const icons = { success: '✓', error: '✗', warning: '⚠', info: 'ℹ' };
        toast.innerHTML = `<span>${icons[type] || 'ℹ'}</span><span style="flex: 1;">${message}</span><span style="cursor:pointer; font-weight: bold;" onclick="this.parentElement.remove()">×</span>`;
        container.appendChild(toast);

        setTimeout(() => {
            toast.classList.add('hiding');
            setTimeout(() => toast.remove(), 300);
        }, duration);
    } catch (e) {
        console.error('Error showing toast:', e);
    }
}

// ======================
// AJAX HELPERS
// ======================

async function apiRequest(method, endpoint, data = null) {
    try {
        const options = {
            method,
            headers: { 'Content-Type': 'application/json' }
        };

        if (data) {
            options.body = JSON.stringify(data);
        }

        const response = await fetch(API_BASE + endpoint, options);
        return await response.json();
    } catch (error) {
        console.error('API request error:', error);
        showToast('error', 'API request failed: ' + error.message);
        return { success: false, message: error.message };
    }
}

// ======================
// BOT CONTROLS
// ======================

async function connectWallet() {
    showToast('info', 'Connecting wallet...');
    const result = await apiRequest('POST', '/wallet/connect');

    if (result.success) {
        const btn = document.getElementById('connectWalletBtn');
        if (btn) {
            btn.textContent = 'Wallet Connected';
            btn.disabled = true;
        }
        showToast('success', 'Wallet connected successfully!');
        updateTradingMode();
    } else {
        showToast('error', result.message || 'Failed to connect wallet');
    }
}

async function startBot() {
    const btn = document.getElementById('startBotBtn');
    const spinner = document.getElementById('startSpinner');

    if (btn) btn.disabled = true;
    if (spinner) spinner.style.display = 'inline-block';

    showToast('info', 'Starting bot...');

    const result = await apiRequest('POST', '/start');

    if (spinner) spinner.style.display = 'none';
    if (btn) btn.disabled = false;

    if (result.success) {
        isRunning = true;
        updateBotStatus();
        startPolling();
        showToast('success', result.message);
    } else {
        showToast('error', result.message || 'Failed to start bot');
    }
}

async function stopBot() {
    const btn = document.getElementById('stopBotBtn');
    const spinner = document.getElementById('stopSpinner');

    if (btn) btn.disabled = true;
    if (spinner) spinner.style.display = 'inline-block';

    showToast('info', 'Stopping bot...');

    const result = await apiRequest('POST', '/stop');

    if (spinner) spinner.style.display = 'none';
    if (btn) btn.disabled = false;

    if (result.success) {
        isRunning = false;
        updateBotStatus();
        stopPolling();
        showToast('success', result.message);
    } else {
        showToast('error', result.message || 'Failed to stop bot');
    }
}

async function resetApp() {
    if (isRunning) {
        showToast('error', 'Cannot reset while bot is running. Stop the bot first.');
        return;
    }

    if (confirm('Are you sure you want to reset the app? This will clear all trade history and portfolio data.')) {
        const result = await apiRequest('POST', '/reset');

        if (result.success) {
            showToast('success', 'App has been reset!');
            // Refresh the page to reflect changes
            setTimeout(() => location.reload(), 1000);
        } else {
            showToast('error', result.message || 'Failed to reset app');
        }
    }
}

async function restartConnection() {
    if (!isRunning) return;

    showToast('info', 'Restarting connection...');
    const result = await apiRequest('POST', '/start');

    if (result.success) {
        showToast('success', 'Connection restarted');
    } else {
        showToast('error', result.message || 'Failed to restart connection');
    }
}

// ======================
// STATUS UPDATES
// ======================

function updateBotStatus() {
    const si = document.getElementById('statusIndicator');
    const st = document.getElementById('botStatusText');
    const sb = document.getElementById('startBotBtn');
    const stopb = document.getElementById('stopBotBtn');
    const reconnectBtn = document.getElementById('reconnectBtn');

    // Check if connected (we'll get this from polling)
    const isConnected = false; // Will be updated by polling

    if (isRunning && isConnected) {
        if (si) si.className = 'status status-connected';
        if (st) st.textContent = 'Running';
        if (sb) sb.disabled = true;
        if (stopb) stopb.disabled = false;
        if (reconnectBtn) reconnectBtn.style.display = 'none';
    } else {
        if (si) si.className = 'status status-disconnected';
        if (st) st.textContent = isConnected ? 'Paused' : 'Disconnected';
        if (sb) sb.disabled = false;
        if (stopb) stopb.disabled = true;
        if (reconnectBtn) reconnectBtn.style.display = (isRunning && !isConnected) ? 'inline-block' : 'none';
    }
    updateConnectionStatus();
}

function updateConnectionStatus() {
    const us = document.getElementById('blockchainStatus');
    const ps = document.getElementById('priceFeedStatus');
    const connected = false; // Will be updated by polling

    if (us) us.innerHTML = connected ? 'Market Connection ✓' : '<span class="loading-spinner"></span> Market Connection';
    if (ps) ps.innerHTML = connected ? 'Price Updates ✓' : '<span class="loading-spinner"></span> Price Updates';
}

function updateTradingMode() {
    const modeEl = document.getElementById('tradingMode');
    if (modeEl) {
        modeEl.textContent = isRunning ? (window.tradingMode === 'LIVE' ? ' | LIVE MODE' : ' | PAPER MODE') : '';
    }
}

// ======================
// POLLING
// ======================

async function fetchState() {
    try {
        const result = await apiRequest('GET', '/state');

        if (result.success) {
            updateUIWithState(result.state);
            updatePortfolioUI(result.portfolio);
            updateTradeStats(result.tradeStats);
            updatePositions(result.positions);
            updateRecentTrades(result.recentTrades);
            updateLastSwaps(result.lastSwaps);
            updatePatterns(result.state.patternStats);
        }
    } catch (error) {
        console.error('Error fetching state:', error);
    }
}

function startPolling() {
    // Initial fetch
    fetchState();

    // Poll every 2 seconds
    if (pollInterval) clearInterval(pollInterval);
    pollInterval = setInterval(fetchState, 2000);
}

function stopPolling() {
    if (pollInterval) {
        clearInterval(pollInterval);
        pollInterval = null;
    }
}

// ======================
// UI UPDATES
// ======================

function updateUIWithState(stateData) {
    // Update status indicators
    isRunning = stateData.isRunning;

    const si = document.getElementById('statusIndicator');
    const st = document.getElementById('botStatusText');
    const sb = document.getElementById('startBotBtn');
    const stopb = document.getElementById('stopBotBtn');
    const reconnectBtn = document.getElementById('reconnectBtn');
    const connected = false; // TODO: Get from backend

    if (isRunning && connected) {
        if (si) si.className = 'status status-connected';
        if (st) st.textContent = 'Running';
        if (sb) sb.disabled = true;
        if (stopb) stopb.disabled = false;
        if (reconnectBtn) reconnectBtn.style.display = 'none';
    } else {
        if (si) si.className = 'status status-disconnected';
        if (st) st.textContent = connected ? 'Paused' : 'Disconnected';
        if (sb) sb.disabled = false;
        if (stopb) stopb.disabled = true;
        if (reconnectBtn) reconnectBtn.style.display = (isRunning && !connected) ? 'inline-block' : 'none';
    }

    // Update metrics
    safeSetText('uptime', stateData.uptime || '00:00:00');
    safeSetText('lastPriceUpdate', stateData.lastPriceUpdate ? new Date(stateData.lastPriceUpdate).toLocaleTimeString() : 'Never');
    safeSetText('currentGasPrice', (stateData.currentGasPrice || 0).toFixed(2) + ' gwei');
    safeSetText('trackedTokensCount', stateData.observedTokens ? stateData.observedTokens.length : 0);
    safeSetText('activePatternsCount', stateData.patternStats ? stateData.patternStats.totalPatterns : 0);
    safeSetText('lastDetectionTime', stateData.lastDetectionTime ? new Date(stateData.lastDetectionTime).toLocaleTimeString() : 'Never');
    safeSetText('tradeAmountDisplay', formatETH(stateData.tradeAmount || 0));

    // Update trading mode
    updateTradingMode();
}

function updatePortfolioUI(portfolioData) {
    if (!portfolioData) return;

    safeSetText('startingEthDisplay', portfolioData.startingEth || '0.01 WETH');
    safeSetText('currentEth', portfolioData.currentEth || '0.01 WETH');

    // Realized PnL
    const realizedPnLEl = document.getElementById('realizedPnL');
    if (realizedPnLEl) {
        realizedPnLEl.textContent = portfolioData.realizedPnL?.value || '0.000000 WETH';
        realizedPnLEl.className = (portfolioData.realizedPnL?.class || '') + (portfolioData.realizedPnL?.value?.includes('-') ? ' price-down' : ' price-up');
    }

    // Unrealized PnL
    const unrealizedPnLEl = document.getElementById('unrealizedPnL');
    if (unrealizedPnLEl) {
        unrealizedPnLEl.textContent = portfolioData.unrealizedPnL?.value || '0.000000 WETH';
        unrealizedPnLEl.className = (portfolioData.unrealizedPnL?.class || '') + (portfolioData.unrealizedPnL?.value?.includes('-') ? ' price-down' : '');
    }

    // Net PnL
    const netPnLEl = document.getElementById('netPnL');
    if (netPnLEl) {
        netPnLEl.textContent = portfolioData.netPnL?.value || '0.000000 WETH';
        netPnLEl.className = (portfolioData.netPnL?.class || '') + (portfolioData.netPnL?.value?.includes('-') ? ' price-down' : ' price-up');
    }

    // Portfolio Return
    const portfolioReturnEl = document.getElementById('portfolioReturn');
    if (portfolioReturnEl) {
        portfolioReturnEl.textContent = portfolioData.portfolioReturn?.value || '0.00%';
        portfolioReturnEl.className = (portfolioData.portfolioReturn?.class || '') + (portfolioData.portfolioReturn?.value?.includes('-') ? ' price-down' : ' price-up');
    }

    // Fees
    safeSetText('gasSpent', portfolioData.gasSpent || '0.00000000 WETH');
    safeSetText('dexFees', portfolioData.dexFees || '0.00000000 WETH');
    safeSetText('totalFees', portfolioData.totalFees || '0.00000000 WETH');
}

function updateTradeStats(tradeStats) {
    if (!tradeStats) return;

    safeSetText('totalTradesCount', tradeStats.totalTrades || 0);
    safeSetText('winningTradesCount', tradeStats.winningTrades || 0);
    safeSetText('losingTradesCount', tradeStats.losingTrades || 0);
    safeSetText('failedTradesCount', tradeStats.failedTrades || 0);
    safeSetText('winRate', tradeStats.winRate || '0%');
    safeSetText('avgProfit', tradeStats.avgProfit || '0 WETH');
}

function updatePositions(positionsData) {
    if (!positionsData) return;

    const positionsTable = document.getElementById('activePositions');
    if (!positionsTable) return;

    if (!positionsData.hasPositions || positionsData.positions.length === 0) {
        if (!positionsTable.innerHTML.includes('No open investments')) {
            positionsTable.innerHTML = '<p style="color: #94a3b8; text-align: center; padding: 20px;">No open investments</p>';
        }
        return;
    }

    let html = '<table><thead><tr><th>Token</th><th>Bought At</th><th>Amount</th><th>Current Value</th><th>Profit/Loss</th><th>Pattern</th><th>Validation</th><th>Age</th></tr></thead><tbody>';

    positionsData.positions.forEach(position => {
        let validationIndicator = '';
        if (position.validation.class) {
            validationIndicator = `<span class="validation-indicator ${position.validation.class}" title="Validation: ${position.validation.accuracy}%"></span>`;
        }

        html += `<tr>
        <td><strong>${position.token}</strong></td>
        <td>${position.entryPrice}</td>
        <td>${position.amount}</td>
        <td>${position.currentValue}</td>
        <td class="${position.unrealizedPnL.class}">${position.unrealizedPnL.value} (${position.unrealizedPnL.percent})</td>
        <td><small>${position.pattern || 'Manual'}</small></td>
        <td>${validationIndicator}</td>
        <td>${position.age}s</td>
    </tr>`;
    });

    html += '</tbody></table>';
    positionsTable.innerHTML = html;
}

function updateRecentTrades(trades) {
    if (!trades) return;

    const recentTradesEl = document.getElementById('recentTrades');
    if (!recentTradesEl) return;

    if (trades.length === 0) {
        recentTradesEl.innerHTML = '<tr><td colspan="8" style="text-align: center; color: #94a3b8;">No trades yet</td></tr>';
        return;
    }

    let html = '';
    trades.forEach(trade => {
        const pnlClass = trade.pnl >= 0 ? 'price-up' : trade.pnl < 0 ? 'price-down' : '';
        const typeClass = trade.type === 'buy' ? 'btn-success' : 'btn-danger';
        const pnlText = trade.pnl !== 0 ? formatETH(trade.pnl, 8) : '0';

        let validationIndicator = '';
        // Validation indicator would be added here if we had that data

        html += `<tr>
        <td>${new Date(trade.timestamp).toLocaleTimeString()}</td>
        <td><strong>${trade.token}</strong></td>
        <td><span class="btn ${typeClass} btn-sm">${trade.type === 'buy' ? 'BUY' : 'SELL'}</span></td>
        <td>${formatNumber(trade.price, 8)}</td>
        <td>${formatNumber(trade.tokenAmount, 4)}</td>
        <td><small>${trade.pattern || 'Manual'}</small></td>
        <td>${validationIndicator}</td>
        <td class="${pnlClass}">${pnlText}</td>
    </tr>`;
    });

    recentTradesEl.innerHTML = html;
}

function updateLastSwaps(swaps) {
    if (!swaps) return;

    const lastSwapsEl = document.getElementById('lastSwaps');
    if (!lastSwapsEl) return;

    if (swaps.length === 0) {
        lastSwapsEl.innerHTML = '<tr><td colspan="6" style="text-align: center; color: #94a3b8;">No swaps observed yet</td></tr>';
        return;
    }

    let html = '';
    swaps.forEach(swap => {
        html += `<tr>
        <td>${new Date(swap.timestamp).toLocaleTimeString()}</td>
        <td><strong>${swap.tokenIn}</strong></td>
        <td><strong>${swap.tokenOut}</strong></td>
        <td>${formatNumber(swap.amountIn, 6)}</td>
        <td>${formatNumber(swap.amountOut, 6)}</td>
        <td><small>${swap.pool}</small></td>
    </tr>`;
    });

    lastSwapsEl.innerHTML = html;
}

function updatePatterns(patternStats) {
    if (!patternStats) return;

    safeSetText('totalPatterns', patternStats.totalPatterns || 0);
    safeSetText('tokensWithPatterns', patternStats.tokensWithPatterns || 0);
}

// ======================
// CONFIGURATION
// ======================

async function loadConfig() {
    try {
        const result = await apiRequest('GET', '/config');

        if (result.success) {
            window.tradingMode = result.config.mode;
            updateTradingMode();

            // Update config display
            safeSetText('targetProfitPercent', result.config.MIN_PROFIT_PERCENT + '%');
            safeSetText('predictionValidationCount', result.config.PREDICTION_VALIDATION_COUNT);

            // Set input values
            const inputs = {
                inputStartingEth: result.config.STARTING_ETH,
                inputTradePercent: result.config.TRADE_AMOUNT_PERCENT,
                inputMinTrade: result.config.MIN_TRADE_AMOUNT_ETH,
                inputMaxTrades: result.config.MAX_TRADES,
                inputWindowSize: result.config.WINDOW_SIZE,
                inputMarginOfError: result.config.MARGIN_OF_ERROR,
                inputMinProfit: result.config.MIN_PROFIT_PERCENT,
                inputMaxSlippage: result.config.MAX_SLIPPAGE,
                inputMaxGasPrice: result.config.MAX_GAS_PRICE
            };

            for (const [id, value] of Object.entries(inputs)) {
                const el = document.getElementById(id);
                if (el) el.value = value;
            }
        }
    } catch (error) {
        console.error('Error loading config:', error);
    }
}

// ======================
// INITIALIZATION
// ======================

async function initializeApp() {
    // Load configuration
    await loadConfig();

    // Check initial state
    const stateResult = await apiRequest('GET', '/state');
    if (stateResult.success) {
        isRunning = stateResult.state.isRunning;
        updateBotStatus();

        if (isRunning) {
            startPolling();
        }
    }

    // Set up event listeners
    setupEventListeners();

    // Update UI
    updateBotStatus();
    updateConnectionStatus();
}

function setupEventListeners() {
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && e.target.tagName !== 'TEXTAREA') e.preventDefault();
    });

    // Visibility API listener for machine lock/unlock
    document.addEventListener('visibilitychange', async () => {
        if (document.visibilityState === 'visible' && isRunning) {
            console.log('[Visibility] Tab is visible again. Checking connection...');
            // Re-fetch state
            await fetchState();
        }
    });
}

// ======================
// START THE APP
// ======================

document.addEventListener('DOMContentLoaded', function () {
    initializeApp();
});

// Make functions available globally for button onclick handlers
window.connectWallet = connectWallet;
window.startBot = startBot;
window.stopBot = stopBot;
window.resetApp = resetApp;
window.restartConnection = restartConnection;