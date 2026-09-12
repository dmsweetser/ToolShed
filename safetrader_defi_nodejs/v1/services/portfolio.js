const { POOL_FEES } = require('../config/config');

// Global references
let stateRef;
let configRef;
let dbRef;

function initPortfolio(db, config) {
  dbRef = db;
  configRef = config;
  
  // Initialize portfolio structure
  const portfolio = {
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
  
  return portfolio;
}

function initPortfolioService(state, config, db) {
  stateRef = state;
  configRef = config;
  dbRef = db;
  
  return {
    updatePortfolioUI,
    updatePortfolioEquity,
    updateTradeStatistics,
    updatePositionDetails,
    getPortfolioSummary,
    getPortfolioBalances,
    getOpenPositions,
    getTradeHistory
  };
}

// Format helpers
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

// Update portfolio UI data (returns data for frontend)
function updatePortfolioUI() {
  try {
    const portfolio = stateRef.portfolio;
    
    return {
      startingEth: formatETH(portfolio.startingEth),
      currentEth: formatETH(portfolio.currentEth),
      realizedPnL: {
        value: formatETH(portfolio.realizedPnL),
        class: portfolio.realizedPnL >= 0 ? 'price-up' : 'price-down'
      },
      unrealizedPnL: {
        value: formatETH(portfolio.unrealizedPnL),
        class: portfolio.unrealizedPnL >= 0 ? 'price-up' : 'price-down'
      },
      netPnL: {
        value: formatETH(portfolio.realizedPnL + portfolio.unrealizedPnL),
        class: (portfolio.realizedPnL + portfolio.unrealizedPnL) >= 0 ? 'price-up' : 'price-down'
      },
      portfolioReturn: {
        value: formatPercent((portfolio.realizedPnL + portfolio.unrealizedPnL) / portfolio.startingEth * 100),
        class: (portfolio.realizedPnL + portfolio.unrealizedPnL) >= 0 ? 'price-up' : 'price-down'
      },
      gasSpent: formatETH(portfolio.gasSpent),
      dexFees: formatETH(portfolio.feesPaid),
      totalFees: formatETH(portfolio.gasSpent + portfolio.feesPaid)
    };
  } catch (e) {
    console.error('Error updating portfolio UI:', e);
    return {};
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
    
    // Save to database
    savePortfolioToDB();
    
    return { currentEth: totalWETH, unrealizedPnL };
  } catch (e) {
    console.error('Error updating portfolio equity:', e);
    return { currentEth: 0, unrealizedPnL: 0 };
  }
}

// Update trade statistics
function updateTradeStatistics() {
  try {
    const portfolio = stateRef.portfolio;
    const totalTrades = portfolio.totalTrades;
    const winningTrades = portfolio.winningTrades;
    const losingTrades = portfolio.losingTrades;
    const failedTrades = portfolio.failedTrades;

    const successfulTrades = winningTrades + losingTrades;
    const winRate = successfulTrades > 0 ? ((winningTrades / successfulTrades) * 100) : 0;
    const avgProfit = successfulTrades > 0 
      ? formatETH(portfolio.realizedPnL / successfulTrades)
      : '0 WETH';

    return {
      totalTrades,
      winningTrades,
      losingTrades,
      failedTrades,
      winRate: formatPercent(winRate),
      avgProfit
    };
  } catch (e) {
    console.error('Error updating trade statistics:', e);
    return {};
  }
}

// Update position details
function updatePositionDetails() {
  try {
    const openPositions = stateRef.portfolio.positions.filter(p => p.status === 'open');
    
    const positionsData = openPositions.map(position => {
      const currentPrice = stateRef.prices[position.token] || position.entryPrice;
      const currentValue = position.amount * currentPrice;
      const unrealizedPnL = currentValue - (position.amount * position.entryPrice) - position.feesPaid - position.gasPaid;
      const returnPct = (unrealizedPnL / (position.amount * position.entryPrice + position.feesPaid + position.gasPaid)) * 100;
      const ageSeconds = ((Date.now() - position.entryTime) / 1000);

      let validationIndicator = '';
      if (position.validationCount > 0) {
        const accuracy = (position.validationSuccesses / position.validationCount) * 100;
        const validationClass = accuracy >= configRef.MIN_PREDICTION_ACCURACY ? 'validation-success' :
          accuracy >= 50 ? 'validation-pending' : 'validation-failed';
        validationIndicator = { class: validationClass, accuracy: accuracy.toFixed(0) };
      }

      return {
        token: position.token,
        entryPrice: formatNumber(position.entryPrice, 8),
        amount: formatNumber(position.amount, 4),
        currentValue: formatETH(currentValue, 8),
        unrealizedPnL: {
          value: formatETH(unrealizedPnL, 8),
          percent: formatPercent(returnPct),
          class: unrealizedPnL >= 0 ? 'price-up' : 'price-down'
        },
        pattern: position.pattern || 'Manual',
        validation: validationIndicator,
        age: Math.round(ageSeconds)
      };
    });

    return {
      hasPositions: openPositions.length > 0,
      positions: positionsData
    };
  } catch (e) {
    console.error('Error updating position details:', e);
    return { hasPositions: false, positions: [] };
  }
}

// Get portfolio summary
function getPortfolioSummary() {
  try {
    const portfolio = stateRef.portfolio;
    return {
      startingEth: portfolio.startingEth,
      currentEth: portfolio.currentEth,
      realizedPnL: portfolio.realizedPnL,
      unrealizedPnL: portfolio.unrealizedPnL,
      gasSpent: portfolio.gasSpent,
      feesPaid: portfolio.feesPaid,
      totalFees: portfolio.gasSpent + portfolio.feesPaid,
      totalTrades: portfolio.totalTrades,
      winningTrades: portfolio.winningTrades,
      losingTrades: portfolio.losingTrades,
      failedTrades: portfolio.failedTrades
    };
  } catch (e) {
    console.error('Error getting portfolio summary:', e);
    return {};
  }
}

// Get portfolio balances
function getPortfolioBalances() {
  try {
    return stateRef.portfolio.balances || {};
  } catch (e) {
    console.error('Error getting portfolio balances:', e);
    return {};
  }
}

// Get open positions
function getOpenPositions() {
  try {
    return stateRef.portfolio.positions.filter(p => p.status === 'open');
  } catch (e) {
    console.error('Error getting open positions:', e);
    return [];
  }
}

// Get trade history
function getTradeHistory(limit = 20) {
  try {
    return [...stateRef.trades]
      .sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp))
      .slice(0, limit);
  } catch (e) {
    console.error('Error getting trade history:', e);
    return [];
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
    
    // Save portfolio summary to app_state
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

module.exports = { initPortfolio, initPortfolioService };