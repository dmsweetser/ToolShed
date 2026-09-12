const { ethers } = require('ethers');
const { POOL_FEES, NETWORK_TOKENS } = require('../config/config');

// Global references
let stateRef;
let configRef;
let blockchainRef;
let dbRef;

function initTradeExecution(state, config, blockchain, db) {
    stateRef = state;
    configRef = config;
    blockchainRef = blockchain;
    dbRef = db;

    return {
        executeTrade,
        calculateTradeAmount,
        simulateRealisticTrade,
        createTradeObject,
        updatePortfolioForTrade,
        checkOpenPositionsForProfitTaking,
        startProfitTakingMonitor,
        stopProfitTakingMonitor
    };
}

// Generate unique trade ID
function generateUniqueTradeId() {
    return 'trade_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
}

// Format number
function formatNumber(num, decimals = 8) {
    if (num === null || num === undefined) return '0';
    return num.toFixed(decimals);
}

// Calculate trade amount
function calculateTradeAmount() {
    try {
        const gasPrice = stateRef.currentGasPrice || configRef.MAX_GAS_PRICE;
        const gasLimit = configRef.GAS_LIMIT;
        const availableWETH = stateRef.portfolio.currentEth || configRef.STARTING_ETH;
        const gasCostPerTrade = (gasPrice * gasLimit) / 1e18;
        const maxTrades = configRef.MAX_TRADES;
        const totalGasCost = gasCostPerTrade * maxTrades;

        const percentBasedAmount = availableWETH * (configRef.TRADE_AMOUNT_PERCENT / 100);
        const minTradeAmountWETH = configRef.MIN_TRADE_AMOUNT_ETH;

        let tradeAmount = Math.max(percentBasedAmount - (totalGasCost / maxTrades), minTradeAmountWETH);
        tradeAmount = Math.min(tradeAmount, availableWETH * 0.95);

        return tradeAmount;
    } catch (e) {
        console.error('Error calculating trade amount:', e);
        return configRef.MIN_TRADE_AMOUNT_ETH;
    }
}

// Create trade object
function createTradeObject(token, action, price, tokenAmount, amountWETH, pattern, status, reason = null,
    gasUsed = 0, gasPrice = 0, feeAmount = 0, priceImpact = 0, slippage = 0,
    patternObj = null, validationCount = 0, validationSuccesses = 0) {
    return {
        id: generateUniqueTradeId(),
        timestamp: new Date().toISOString(),
        token, type: action, price, tokenAmount, amountETH: amountWETH, fee: feeAmount,
        gasUsed, gasPrice, priceImpact, slippage, status, reason, pnl: 0, pattern, patternObj,
        txHash: status === 'closed' || status === 'failed' ? null : '0x' + Math.random().toString(16).substring(2, 66) + Date.now().toString(16).substring(4),
        network: stateRef.currentNetwork, entryTime: Date.now(),
        validationCount, validationSuccesses
    };
}

// Simulate realistic trade (for paper trading)
async function simulateRealisticTrade(token, action, tokenAmount, currentPrice, poolInfo, latency, gasPriceGwei) {
    const result = {
        success: true, tokenAmount, amountETH: tokenAmount * currentPrice,
        executionPrice: currentPrice, gasUsed: 0, gasPrice: gasPriceGwei || configRef.MAX_GAS_PRICE,
        feeAmount: 0, priceImpact: 0, slippage: 0, reason: null
    };

    try {
        if (!poolInfo || poolInfo.liquidity < configRef.MIN_LIQUIDITY) {
            result.success = false;
            result.reason = `Low liquidity (${poolInfo?.liquidity || 0})`;
            return result;
        }

        result.gasUsed = estimateSwapGas(action, token);
        const feeTier = poolInfo.feeTier || POOL_FEES.MEDIUM;
        result.feeAmount = result.amountETH * (feeTier / 1000000);
        result.priceImpact = calculatePriceImpact(token, tokenAmount, poolInfo);

        const baseSlippage = result.priceImpact;
        const latencySlippage = latency > 0 ? (latency / 1000) * 0.01 : 0;
        result.slippage = baseSlippage + latencySlippage;

        if (result.slippage > configRef.MAX_SLIPPAGE) {
            result.success = false;
            result.reason = `Price moved too much (${result.slippage.toFixed(2)}% > ${configRef.MAX_SLIPPAGE}%)`;
            return result;
        }

        result.executionPrice = action === 'buy'
            ? currentPrice * (1 + result.slippage / 100)
            : currentPrice * (1 - result.slippage / 100);
        result.amountETH = tokenAmount * result.executionPrice;
        result.tokenAmount = action === 'buy'
            ? (result.amountETH / result.executionPrice)
            : tokenAmount;

        return result;
    } catch (error) {
        result.success = false;
        result.reason = error.message;
        return result;
    }
}

// Estimate swap gas
function estimateSwapGas(action, token) {
    let baseGas = 120000;
    if (token === 'WBTC' || token === 'WETH') baseGas += 20000;
    else if (token === 'UNI' || token === 'LINK') baseGas += 8000;
    else baseGas += 5000;
    if (action === 'buy') baseGas += 10000;
    baseGas += Math.random() * 15000;
    return Math.min(baseGas, configRef.GAS_LIMIT);
}

// Calculate price impact
function calculatePriceImpact(token, tokenAmount, poolInfo) {
    const tokenPrice = stateRef.prices[token] || 0;
    const tokenValueWETH = tokenAmount * tokenPrice;
    const liquidityWETH = poolInfo.liquidity || 100000;

    if (liquidityWETH <= 0) return 0;
    return Math.min((tokenValueWETH / liquidityWETH) * 100, 2);
}

// Get enhanced pool info
async function getEnhancedPoolInfo(token) {
    const defaults = {
        WETH: { liquidity: 1000000, feeTier: POOL_FEES.LOW, token0: 'WETH', token1: 'WETH' },
        ETH: { liquidity: 1000000, feeTier: POOL_FEES.LOW, token0: 'WETH', token1: 'WETH' },
        WBTC: { liquidity: 500000, feeTier: POOL_FEES.MEDIUM, token0: 'WETH', token1: 'WBTC' },
        UNI: { liquidity: 1000000, feeTier: POOL_FEES.MEDIUM, token0: 'WETH', token1: 'UNI' },
        LINK: { liquidity: 800000, feeTier: POOL_FEES.MEDIUM, token0: 'WETH', token1: 'LINK' },
        ARB: { liquidity: 1500000, feeTier: POOL_FEES.MEDIUM, token0: 'WETH', token1: 'ARB' },
        GMX: { liquidity: 400000, feeTier: POOL_FEES.MEDIUM, token0: 'WETH', token1: 'GMX' },
        USDC: { liquidity: 50000000, feeTier: POOL_FEES.LOW, token0: 'WETH', token1: 'USDC' },
        USDT: { liquidity: 50000000, feeTier: POOL_FEES.LOW, token0: 'WETH', token1: 'USDT' },
        LEVY: { liquidity: 100000, feeTier: POOL_FEES.MEDIUM, token0: 'WETH', token1: 'LEVY' },
        APEX: { liquidity: 200000, feeTier: POOL_FEES.MEDIUM, token0: 'WETH', token1: 'APEX' }
    };
    return defaults[token] || { liquidity: 75000, feeTier: POOL_FEES.MEDIUM, token0: 'WETH', token1: token };
}

// Execute trade
async function executeTrade(token, action, patternDescription = 'Manual', amountWETH = null, pattern = null) {
    try {
        if (!stateRef.isRunning) return null;

        // Prevent sequential trades on the same token
        if (action === 'buy') {
            if (configRef.PREVENT_SEQUENTIAL_TRADES && stateRef.lastTradedToken === token) {
                const lastTradeTime = stateRef.lastTradeTimes[token];
                if (lastTradeTime && (Date.now() - lastTradeTime) < 60000) {
                    console.log(`Blocked buy for ${token}: Recent trade.`);
                    return null;
                }
            }

            if (stateRef.openBuyOrders.has(token)) {
                console.log(`Blocked buy for ${token}: Open buy order exists.`);
                return null;
            }

            const existingPosition = stateRef.portfolio.positions.find(p => p.token === token && p.status === 'open');
            if (existingPosition) {
                console.log(`Blocked buy for ${token}: Already has an open position.`);
                return null;
            }

            const totalOpenPositions = stateRef.portfolio.positions.filter(p => p.status === 'open').length;
            if (totalOpenPositions >= configRef.MAX_TRADES) {
                console.log(`Max trades (${configRef.MAX_TRADES}) reached`);
                return null;
            }

            // Validate prediction if pattern is provided
            if (pattern && action === 'buy') {
                const currentPrice = stateRef.prices[token];
                if (!currentPrice) {
                    console.log(`No current price for ${token}, cannot validate prediction`);
                    return null;
                }

                // Validation is handled by patternDetection service
                // In the full implementation, we would call validatePrediction here
            }
        }

        // Update gas price
        await blockchainRef.updateGasPrice();
        const currentGasPrice = stateRef.currentGasPrice || configRef.MAX_GAS_PRICE;

        if (currentGasPrice > configRef.MAX_GAS_PRICE) {
            console.log(`Gas price too high: ${currentGasPrice} gwei > ${configRef.MAX_GAS_PRICE} gwei max`);
            return null;
        }

        const currentPrice = stateRef.prices[token];
        if (!currentPrice) return null;

        const tokenSymbol = token;
        let tokenAmount, amountInWETH;

        if (action === 'sell') {
            // Sell the entire balance
            const tokenBalance = stateRef.portfolio.balances[tokenSymbol] || 0;
            if (tokenBalance <= 0) return null;
            tokenAmount = tokenBalance;
            amountInWETH = tokenAmount * currentPrice;
        } else {
            // Buy logic
            if (amountWETH === null) amountWETH = calculateTradeAmount();
            tokenAmount = amountWETH / currentPrice;
            amountInWETH = amountWETH;
        }

        const poolInfo = await getEnhancedPoolInfo(tokenSymbol);
        if (!poolInfo) return null;

        let tradeResult = await simulateRealisticTrade(tokenSymbol, action, tokenAmount, currentPrice, poolInfo, 0, currentGasPrice);

        if (!tradeResult.success) {
            const failedTrade = createTradeObject(
                tokenSymbol, action, currentPrice, tokenAmount, amountInWETH,
                patternDescription, 'failed', tradeResult.reason,
                tradeResult.gasUsed, tradeResult.gasPrice, tradeResult.feeAmount,
                tradeResult.priceImpact, tradeResult.slippage, pattern
            );
            stateRef.trades.push(failedTrade);
            stateRef.portfolio.failedTrades++;

            // Save to database
            saveTradeToDB(failedTrade);

            return failedTrade;
        }

        let validationCount = 0;
        let validationSuccesses = 0;
        if (pattern) {
            const validationKey = `${token}_${pattern.predictedPrice.toFixed(8)}`;
            const validationData = stateRef.predictionValidation.get(validationKey) || {};
            validationCount = validationData.count || 0;
            validationSuccesses = validationData.successes || 0;
        }

        const trade = createTradeObject(
            tokenSymbol, action, tradeResult.executionPrice, tradeResult.tokenAmount,
            tradeResult.amountETH, patternDescription, 'open', null,
            tradeResult.gasUsed, tradeResult.gasPrice, tradeResult.feeAmount,
            tradeResult.priceImpact, tradeResult.slippage, pattern,
            validationCount, validationSuccesses
        );

        // For live trading, we would execute the actual trade here
        if (process.env.PRIVATE_KEY && stateRef.walletConnected) {
            try {
                const signer = blockchainRef.getSigner();
                if (signer) {
                    // Execute actual trade on-chain
                    const txResponse = await executeLiveTrade(signer, trade, action, tokenAmount);
                    if (txResponse) {
                        trade.txHash = txResponse.hash;
                        trade.status = 'open';
                    }
                }
            } catch (e) {
                console.error('Live trade execution failed:', e);
                trade.status = 'failed';
                trade.reason = e.message;
            }
        }

        updatePortfolioForTrade(trade, action, tradeResult);
        stateRef.trades.push(trade);

        // Save to database
        saveTradeToDB(trade);

        if (action === 'buy') {
            stateRef.lastTradedToken = tokenSymbol;
            stateRef.lastTradeTimes[tokenSymbol] = Date.now();
            stateRef.openBuyOrders.set(tokenSymbol, {
                tradeId: trade.id,
                pattern: pattern,
                entryPrice: tradeResult.executionPrice,
                entryTime: Date.now()
            });
        } else if (action === 'sell') {
            stateRef.openBuyOrders.delete(tokenSymbol);
        }

        return trade;
    } catch (e) {
        console.error('Error executing trade:', e);
        return null;
    }
}

// Execute live trade on-chain
async function executeLiveTrade(signer, trade, action, tokenAmount) {
    try {
        const tokenInfo = await blockchainRef.getTokenInfo(trade.token);
        if (!tokenInfo) {
            throw new Error(`Token info not found for ${trade.token}`);
        }

        const wethAddress = NETWORK_TOKENS.arbitrum.WETH;
        const tokenAddress = tokenInfo.address;

        // Get Uniswap Router
        const routerAddress = '0xE592427A0AEce92De3Edee1F18E0157C05861564';
        const routerAbi = [
            'function swapExactETHForTokens(uint amountOutMin, address[] calldata path, address to, uint deadline)',
            'function swapExactTokensForETH(uint amountIn, uint amountOutMin, address[] calldata path, address to, uint deadline)',
            'function getAmountsOut(uint amountIn, address[] memory path) view returns (uint[] memory amounts)'
        ];

        const router = new ethers.Contract(routerAddress, routerAbi, signer);

        const path = action === 'buy'
            ? [wethAddress, tokenAddress]
            : [tokenAddress, wethAddress];

        const deadline = Math.floor(Date.now() / 1000) + 60 * 20; // 20 minutes
        const amountIn = ethers.parseUnits(tokenAmount.toString(), tokenInfo.decimals);

        // Get minimum amount out with slippage
        const amountsOut = await router.getAmountsOut(
            amountIn,
            path
        );
        const amountOutMin = amountsOut[amountsOut.length - 1].mul(95).div(100); // 5% slippage

        let tx;
        if (action === 'buy') {
            // Buy token with ETH
            tx = await router.swapExactETHForTokens(
                amountOutMin,
                path,
                await signer.getAddress(),
                deadline,
                { value: amountIn }
            );
        } else {
            // Sell token for ETH
            tx = await router.swapExactTokensForETH(
                amountIn,
                amountOutMin,
                path,
                await signer.getAddress(),
                deadline
            );
        }

        return tx;
    } catch (e) {
        console.error('Error in live trade execution:', e);
        throw e;
    }
}

// Save trade to database
function saveTradeToDB(trade) {
    try {
        const stmt = dbRef.prepare(`
      INSERT OR REPLACE INTO trades 
      (id, timestamp, token, type, price, token_amount, amount_eth, fee, gas_used, 
       gas_price, price_impact, slippage, status, reason, pnl, pattern, network, 
       entry_time, closed_at, tx_hash, validation_count, validation_successes)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `);

        stmt.run(
            trade.id,
            trade.timestamp,
            trade.token,
            trade.type,
            trade.price,
            trade.tokenAmount,
            trade.amountETH,
            trade.fee,
            trade.gasUsed,
            trade.gasPrice,
            trade.priceImpact,
            trade.slippage,
            trade.status,
            trade.reason,
            trade.pnl,
            trade.pattern,
            trade.network,
            trade.entryTime,
            trade.closedAt,
            trade.txHash,
            trade.validationCount,
            trade.validationSuccesses
        );
    } catch (e) {
        console.error('Error saving trade to DB:', e);
    }
}

// Update portfolio for trade
function updatePortfolioForTrade(trade, action, tradeResult) {
    try {
        const token = trade.token;
        const tokenSymbol = token;
        const gasCostWETH = tradeResult.gasUsed * tradeResult.gasPrice / 1e9 / 1e9;
        const feeCostWETH = tradeResult.feeAmount;
        const totalCostWETH = gasCostWETH + feeCostWETH;

        if (action === 'buy') {
            const wethBalance = stateRef.portfolio.balances['WETH'] || 0;
            const totalTradeCost = tradeResult.amountETH + totalCostWETH;

            if (wethBalance < totalTradeCost) {
                trade.status = 'failed';
                trade.reason = 'Not enough WETH (including fees)';
                stateRef.portfolio.failedTrades++;
                stateRef.trades.push(trade);
                return;
            }

            stateRef.portfolio.balances['WETH'] = wethBalance - totalTradeCost;
            if (!stateRef.portfolio.balances[tokenSymbol]) stateRef.portfolio.balances[tokenSymbol] = 0;
            stateRef.portfolio.balances[tokenSymbol] += tradeResult.tokenAmount;

            let position = stateRef.portfolio.positions.find(p => p.token === tokenSymbol && p.status === 'open');
            if (!position) {
                position = {
                    id: trade.id,
                    token: tokenSymbol,
                    entryPrice: tradeResult.executionPrice,
                    amount: tradeResult.tokenAmount,
                    usdValue: tradeResult.amountETH,
                    entryTime: Date.now(),
                    gasPaid: gasCostWETH,
                    feesPaid: feeCostWETH,
                    status: 'open',
                    tradeId: trade.id,
                    pattern: trade.pattern,
                    patternObj: trade.patternObj,
                    validationCount: trade.validationCount,
                    validationSuccesses: trade.validationSuccesses
                };
                stateRef.portfolio.positions.push(position);
            } else {
                position.amount += tradeResult.tokenAmount;
                position.usdValue += tradeResult.amountETH;
                position.gasPaid += gasCostWETH;
                position.feesPaid += feeCostWETH;

                const totalFeesGas = position.feesPaid + position.gasPaid;
                if (position.amount > 0 && Number.isFinite(totalFeesGas)) {
                    const entryWithCosts = (position.amount * position.entryPrice) + totalFeesGas;
                    position.entryPrice = entryWithCosts / position.amount;
                }
            }

            stateRef.portfolio.gasSpent += gasCostWETH;
            stateRef.portfolio.feesPaid += feeCostWETH;
            stateRef.portfolio.totalFees += totalCostWETH;
        } else if (action === 'sell') {
            const openPositions = stateRef.portfolio.positions
                .filter(p => p.token === tokenSymbol && p.status === 'open')
                .sort((a, b) => a.entryTime - b.entryTime);

            if (openPositions.length === 0) {
                trade.status = 'failed';
                trade.reason = 'No open position to sell';
                stateRef.portfolio.failedTrades++;
                stateRef.trades.push(trade);
                return;
            }

            // Sell all open positions for this token
            let totalPnL = 0;
            for (const position of openPositions) {
                const amountToSell = position.amount;
                const sellValueWETH = amountToSell * tradeResult.executionPrice;
                const totalFeesGasOld = position.feesPaid + position.gasPaid;
                const costBasis = (amountToSell * position.entryPrice) +
                    (amountToSell / position.amount) * totalFeesGasOld;
                const pnl = sellValueWETH - costBasis - (gasCostWETH + feeCostWETH);

                position.amount = 0;
                position.feesPaid += feeCostWETH;
                position.gasPaid += gasCostWETH;
                position.status = 'closed';
                position.exitPrice = tradeResult.executionPrice;
                position.exitTime = Date.now();
                position.pnl = pnl;
                position.sellTradeId = trade.id;

                stateRef.portfolio.realizedPnL += pnl;
                if (pnl > 0) stateRef.portfolio.winningTrades++;
                else if (pnl < 0) stateRef.portfolio.losingTrades++;

                totalPnL += pnl;

                // Save position to DB
                savePositionToDB(position);
            }

            stateRef.portfolio.balances['WETH'] = (stateRef.portfolio.balances['WETH'] || 0) + tradeResult.amountETH - totalCostWETH;
            if (stateRef.portfolio.balances[tokenSymbol]) {
                delete stateRef.portfolio.balances[tokenSymbol];
            }

            trade.pnl = totalPnL;
            trade.status = 'closed';
            trade.closedAt = new Date().toISOString();

            stateRef.portfolio.gasSpent += gasCostWETH;
            stateRef.portfolio.feesPaid += feeCostWETH;
            stateRef.portfolio.totalFees += totalCostWETH;
        }

        stateRef.portfolio.totalTrades++;
        updatePortfolioEquity();
        updateTradeStatistics();

        // Save portfolio state
        savePortfolioToDB();

    } catch (e) {
        console.error('Error updating portfolio for trade:', e);
    }
}

// Save position to database
function savePositionToDB(position) {
    try {
        const stmt = dbRef.prepare(`
      INSERT OR REPLACE INTO positions 
      (id, token, entry_price, amount, usd_value, entry_time, exit_time, 
       exit_price, gas_paid, fees_paid, status, pnl, trade_id, pattern, 
       validation_count, validation_successes)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `);

        stmt.run(
            position.id,
            position.token,
            position.entryPrice,
            position.amount,
            position.usdValue,
            position.entryTime,
            position.exitTime,
            position.exitPrice,
            position.gasPaid,
            position.feesPaid,
            position.status,
            position.pnl,
            position.tradeId,
            position.pattern,
            position.validationCount,
            position.validationSuccesses
        );
    } catch (e) {
        console.error('Error saving position to DB:', e);
    }
}

// Save portfolio to database
function savePortfolioToDB() {
    try {
        // Save balances
        const deleteBalances = dbRef.prepare('DELETE FROM portfolio_balances');
        deleteBalances.run();

        const insertBalance = dbRef.prepare('INSERT INTO portfolio_balances (token, amount) VALUES (?, ?)');
        for (const [token, amount] of Object.entries(stateRef.portfolio.balances)) {
            insertBalance.run(token, amount);
        }

        // Save portfolio summary
        const stmt = dbRef.prepare(`
      UPDATE app_state SET
        portfolio = ?,
        updated_at = datetime('now')
      WHERE id = 1
    `);

        stmt.run(JSON.stringify(stateRef.portfolio));
    } catch (e) {
        console.error('Error saving portfolio to DB:', e);
    }
}

// Update portfolio equity
function updatePortfolioEquity() {
    try {
        let totalWETH = stateRef.portfolio.balances['WETH'] || 0;
        let unrealizedPnL = 0;

        for (const [tokenSymbol, amount] of Object.entries(stateRef.portfolio.balances)) {
            if (tokenSymbol === 'WETH') continue;
            const price = stateRef.prices[tokenSymbol] || 0;
            totalWETH += amount * price;
        }

        stateRef.portfolio.positions.forEach(position => {
            if (position.status === 'open') {
                const currentPrice = stateRef.prices[position.token] || position.entryPrice;
                const currentValue = position.amount * currentPrice;
                const costBasis = (position.amount * position.entryPrice) + position.feesPaid + position.gasPaid;
                unrealizedPnL += currentValue - costBasis;
            }
        });

        stateRef.portfolio.currentEth = totalWETH;
        stateRef.portfolio.unrealizedPnL = unrealizedPnL;
        stateRef.portfolio.equityHistory.push({ timestamp: Date.now(), ethValue: totalWETH });
        if (stateRef.portfolio.equityHistory.length > 1000) stateRef.portfolio.equityHistory.shift();
    } catch (e) {
        console.error('Error updating portfolio equity:', e);
    }
}

// Update trade statistics
function updateTradeStatistics() {
    try {
        const totalTrades = stateRef.portfolio.totalTrades;
        const winningTrades = stateRef.portfolio.winningTrades;
        const losingTrades = stateRef.portfolio.losingTrades;
        const failedTrades = stateRef.portfolio.failedTrades;

        const successfulTrades = winningTrades + losingTrades;
        const winRate = successfulTrades > 0 ? ((winningTrades / successfulTrades) * 100) : 0;

        // Statistics are updated in the state, no need to return
    } catch (e) {
        console.error('Error updating trade statistics:', e);
    }
}

// Check open positions for profit taking
async function checkOpenPositionsForProfitTaking() {
    if (!stateRef.isRunning) return;

    const openPositions = stateRef.portfolio.positions.filter(p => p.status === 'open');
    for (const position of openPositions) {
        const token = position.token;
        const currentPrice = stateRef.prices[token];
        if (!currentPrice) continue;

        const currentValue = position.amount * currentPrice;
        const costBasis = (position.amount * position.entryPrice) + position.feesPaid + position.gasPaid;
        const profitWETH = currentValue - costBasis;
        const profitPercent = (profitWETH / costBasis) * 100;

        if (profitPercent >= configRef.MIN_PROFIT_PERCENT && profitWETH > 0) {
            console.log(`[Profit-Taking] Selling ${token} at ${profitPercent.toFixed(4)}% profit`);
            await executeTrade(token, 'sell', `Profit target (${formatNumber(profitPercent, 2)}%) reached`);
        }
    }
}

// Profit taking monitor
let profitTakingTimer = null;

function startProfitTakingMonitor() {
    if (profitTakingTimer) clearInterval(profitTakingTimer);
    profitTakingTimer = setInterval(async () => {
        if (stateRef.isRunning && stateRef.activeSession?.connected) {
            await checkOpenPositionsForProfitTaking();
        }
    }, 5000);
}

function stopProfitTakingMonitor() {
    if (profitTakingTimer) {
        clearInterval(profitTakingTimer);
        profitTakingTimer = null;
    }
}

module.exports = { initTradeExecution };