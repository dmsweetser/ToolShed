# Uniswap Quick Swap Trader v7.2.0 - Algorithm Breakdown

---

## **Overview**

**Uniswap Quick Swap Trader** is a **profit-only** trading bot designed to **buy dips** and **sell exclusively at a profit** on the **Arbitrum** network using **Uniswap v3**. It leverages **pattern detection** to identify optimal entry points and executes trades only when predefined profit targets are met.

---

## **Core Algorithm Workflow**

### **1. Initialization &amp; Setup**

- **Network**: Arbitrum One (`chainId: 42161`)
- **DEX**: Uniswap v3 (`factory: 0x1F98431c8aD98523631AE4a59f267346ea31F984`)
- **Quote Asset**: ETH (native mode)
- **Supported Tokens**: ETH, WETH, WBTC, UNI, LINK, ARB, GMX, USDC, USDT

#### **Key Configurations**


| Parameter                | Value        | Description                                |
| ------------------------ | ------------ | ------------------------------------------ |
| `STARTING_ETH`           | `0.0033 ETH` | Initial portfolio balance                  |
| `TRADE_AMOUNT_PERCENT`   | `0.5%`       | % of available ETH per trade               |
| `MIN_TRADE_AMOUNT_ETH`   | `0.0003 ETH` | Minimum trade size                         |
| `MAX_TRADES`             | `5`          | Maximum concurrent open trades             |
| `MIN_PROFIT_PERCENT`     | `2.0%`       | Minimum profit to sell                     |
| `MAX_SLIPPAGE`           | `0.5%`       | Maximum allowed slippage                   |
| `MAX_GAS_PRICE`          | `200 gwei`   | Maximum gas price to execute trades        |
| `TRADE_COOLDOWN`         | `60s`        | Cooldown between trades for the same token |
| `PRICE_HISTORY_DURATION` | `24h`        | Duration of price history stored           |
| `MAX_PRICE_HISTORY`      | `20,000`     | Maximum price history entries per token    |


---

## **2. Pattern Detection Engine**

The bot **scans price history** for **buy patterns** (dips) and executes trades **only when a profitable exit is guaranteed**.

### **How Patterns Are Detected**

1. **Price History Analysis**
  - Collects price data for all observed tokens via **Uniswap swap events** and **RPC polling**.
  - Stores price history for each token (`state.priceHistory`).
2. **Dip Identification**
  - Looks for **local minima** (low points) in price history.
  - A **valid dip** must satisfy:
    - **Drop**: Price drops by **≥ `MIN_PRICE_CHANGE` (1%)** over a time window of **`MIN_TIME_WINDOW` (1s) to `MAX_TIME_WINDOW` (3600s)**.
    - **Recovery**: Price rises by **≥ `MIN_PROFIT_PERCENT` (2%)** after the dip.
  - **Pattern Validation**:
    - `dropPct` and `risePct` must be **&gt; 0** and **≤ 100%**.
    - `dropTime` and `riseTime` must be **≥ 1s** and **≤ 100s**.
3. **Pattern Storage**
  - Detected patterns are stored in `state.activePatterns` (a `Map` of pattern keys to pattern objects).
  - Each pattern includes:
    - `dropPct`: % price drop
    - `dropTime`: Duration of the drop (seconds)
    - `risePct`: % price rise (must be ≥ `MIN_PROFIT_PERCENT`)
    - `riseTime`: Duration of the rise (seconds)
    - `token`: Token symbol
    - `occurrences`: How many times this pattern was detected
4. **Pattern Matching**
  - For each token, the bot checks if the **current price action matches any stored pattern**.
  - If a match is found, a **buy trade is triggered** (if no open position exists for that token).

---

## **3. Trading Logic**

### **Buy Conditions**

A **buy trade is executed** if:

1. The bot is **running** (`state.isRunning = true`).
2. A **valid buy pattern** is detected for a token.
3. **No open position** exists for that token.
4. **No recent trade** was made for that token (cooldown: `TRADE_COOLDOWN`).
5. **Max trades limit** (`MAX_TRADES = 5`) is not reached.
6. **Gas price** is below `MAX_GAS_PRICE` (200 gwei).
7. **Sufficient ETH balance** is available (including gas + fees).

### **Sell Conditions**

A **sell trade is executed** if:

1. An **open position** exists for the token.
2. The **current profit** (unrealized PnL) **≥ `MIN_PROFIT_PERCENT` (2%)**.
3. The **price impact** and **slippage** are within limits (`MAX_SLIPPAGE = 0.5%`).

---

## **4. Trade Execution**

### **Trade Amount Calculation**

The bot dynamically calculates the **trade size** based on:

1. **Percentage of Available ETH**:  
 `tradeAmount = availableETH * (TRADE_AMOUNT_PERCENT / 100)`
2. **Gas Cost Adjustment**:
  - Estimates gas cost for `MAX_TRADES` (default: 5).
  - Subtracts total gas cost from the trade amount.
3. **Minimum Trade Constraint**:
  - Ensures trade amount **≥ `MIN_TRADE_AMOUNT_ETH` (0.0003 ETH)**.
4. **Safety Cap**:
  - Trade amount **≤ 95% of available ETH**.

**Final Trade Amount Formula**:

```
tradeAmount = min(
  (availableETH * 0.005) - (totalGasCost / MAX_TRADES),
  availableETH * 0.95
)
tradeAmount = max(tradeAmount, MIN_TRADE_AMOUNT_ETH)
```

### **Trade Simulation (Non-Live Mode)**

- If **Live Mode is OFF**, trades are **simulated** with realistic:
  - **Gas estimation** (varies by token).
  - **Price impact** (based on pool liquidity).
  - **Slippage** (randomized, capped at `MAX_SLIPPAGE`).
  - **Fee calculation** (based on Uniswap v3 pool fee tier).

### **Live Trade Execution (Live Mode)**

- If **Live Mode is ON** and **wallet is connected**, trades are executed on-chain via:
  - **MetaMask** (BrowserProvider).
  - **Uniswap Router** (for swaps).
  - **Gas price** is fetched in real-time from the network.

---

## **5. Portfolio Management**

### **Portfolio Tracking**

- **Balances**: Tracks ETH and token balances (`state.portfolio.balances`).
- **Positions**: Open trades with entry price, amount, and pattern used (`state.portfolio.positions`).
- **PnL Calculation**:
  - **Realized PnL**: Profit from **closed trades** (sold at profit).
  - **Unrealized PnL**: Profit from **open positions** (current value vs. entry price).
  - **Total PnL**: `realizedPnL + unrealizedPnL`.
  - **Return %**: `(Total PnL / STARTING_ETH) * 100`.

### **Fees &amp; Costs**

- **Gas Spent**: Total ETH spent on gas (`state.portfolio.gasSpent`).
- **DEX Fees**: Total fees paid to Uniswap (`state.portfolio.feesPaid`).
- **Total Fees**: `gasSpent + feesPaid`.

---

## **6. Risk Management**

### **Safety Mechanisms**


| Mechanism                       | Description                                                                          |
| ------------------------------- | ------------------------------------------------------------------------------------ |
| **Max Trades Limit**            | Only `5` concurrent trades allowed.                                                  |
| **Trade Cooldown**              | `60s` cooldown between trades for the same token.                                    |
| **Sequential Trade Prevention** | Prevents back-to-back trades on the same token (`PREVENT_SEQUENTIAL_TRADES = true`). |
| **Gas Price Limit**             | Trades **paused** if gas price &gt; `200 gwei`.                                      |
| **Slippage Limit**              | Trades **rejected** if slippage &gt; `0.5%`.                                         |
| **Min Profit Requirement**      | Only sells if profit ≥ `2%`.                                                         |
| **Min Trade Size**              | Ensures trades are ≥ `0.0003 ETH`.                                                   |


---

## **7. Data Flow &amp; Connectivity**

### **Blockchain Connection**

1. **RPC Providers**: Uses multiple Arbitrum RPC endpoints (fallback if one fails).
2. **WebSocket Support**: Real-time updates via WebSocket (if available).
3. **Reconnection Logic**: Auto-reconnects with exponential backoff (max 10 attempts).

### **Price Updates**

- **Polling Interval**: Every `10s` (for all observed tokens).
- **Swap Event Listening**: Real-time price updates from Uniswap swap events.
- **Price History**: Stores up to `20,000` price points per token (24h window).

### **Pattern Detection Loop**

- Runs every **3 seconds** (`detectAllPatterns()`).
- Scans all observed tokens for new patterns.
- Validates and updates `state.activePatterns`.

---

## **8. User Interface (UI) Updates**

### **Real-Time Updates**

- **Dashboard**: Shows tracked tokens, price changes, patterns, and trade history.
- **Portfolio**: Displays balances, PnL, and return %. 
- **Trade Statistics**: Win rate, total trades, avg profit per trade.
- **Open Positions**: Current investments with unrealized PnL.
- **Recent Trades**: Last 20 trades with timestamps, actions, and profits.

### **Status Indicators**

- **Bot Status**: Running / Not Running (with uptime timer).
- **Blockchain Connection**: ✅ (connected) or ⏳ (connecting).
- **Price Feed**: ✅ (active) or ⏳ (loading).

---

## **9. Backup &amp; Persistence**

- **Local Storage**: Saves trades, portfolio, and patterns every **60 seconds**.
- **Auto-Backup**: Triggers on page unload (`beforeunload` event).
- **Data Restored**: Loads from `localStorage` on page reload.

---

## **10. Key Functions Summary**


| Function                    | Purpose                                                           |
| --------------------------- | ----------------------------------------------------------------- |
| `connectWallet()`           | Connects MetaMask wallet.                                         |
| `startBot()`                | Initializes the bot, starts pattern detection, and price polling. |
| `stopBot()`                 | Stops all trading activities and clears open orders.              |
| `detectAllPatterns()`       | Scans all tokens for buy patterns.                                |
| `executeTrade()`            | Executes a buy/sell trade (simulated or live).                    |
| `checkPatternsForToken()`   | Checks if current price matches any pattern for a token.          |
| `updatePortfolioForTrade()` | Updates portfolio balances and PnL after a trade.                 |
| `updatePortfolioEquity()`   | Recalculates total portfolio value and unrealized PnL.            |
| `calculateTradeAmount()`    | Dynamically computes the trade size.                              |
| `simulateRealisticTrade()`  | Simulates a trade with gas, fees, and slippage.                   |
| `backupData()`              | Saves state to `localStorage`.                                    |


---

## **11. Example Trade Flow**

1. **Bot Starts** → Connects to Arbitrum, loads price history.
2. **Pattern Detected** → ETH drops **2%** over **30s**, then rises **3%** over **1m**.
3. **Buy Trade Executed** → Buys **0.001 ETH** worth of UNI at `0.02 ETH/UNI`.
4. **Price Rises** → UNI price increases to `0.0204 ETH` (**2% profit**).
5. **Sell Trade Triggered** → Sells UNI at `0.0204 ETH`, locking in **2% profit**.
6. **PnL Updated** → `realizedPnL += 0.00002 ETH` (profit from the trade).

---

## **12. Limitations &amp; Assumptions**

- **Profit-Only Mode**: **Never sells at a loss** (only when `MIN_PROFIT_PERCENT` is met).
- **No Shorting**: Only **long positions** (buys low, sells high).
- **No Stop-Loss**: Relies on pattern detection to avoid bad trades.
- **Gas Costs**: High gas prices **pause trading** (no dynamic adjustment).
- **Slippage**: Trades are **rejected** if slippage exceeds `0.5%`.
- **Token Liquidity**: Assumes sufficient liquidity for all supported tokens.

---

## **13. How to Use**

1. **Connect Wallet**: Click "Connect Wallet" to link MetaMask (Arbitrum network required).
2. **Start Bot**: Click "Start Trading" to begin pattern detection.
3. **Toggle Live Mode**: Enable "Live Mode" to execute real trades (otherwise, trades are simulated).
4. **Monitor Dashboard**: Watch for detected patterns, open positions, and profits.
5. **Stop Bot**: Click "Stop Trading" to halt all activities.
6. **Reset App**: Clears all data (trades, portfolio, patterns).

---

## **14. Future Improvements**

- **Dynamic Gas Adjustment**: Adjust trade amounts based on real-time gas costs.
- **Stop-Loss Mechanism**: Sell at a predefined loss to limit downside.
- **Multi-Network Support**: Expand beyond Arbitrum (e.g., Ethereum, Polygon).
- **Advanced Patterns**: Detect more complex patterns (e.g., breakouts, reversals).
- **Backtesting**: Simulate performance on historical data.
- **Telegram Alerts**: Notify users of trades via Telegram bot.

---

## **15. Technical Stack**

- **Frontend**: Vanilla HTML/CSS/JS
- **Blockchain**: [ethers.js v6.17.0](https://docs.ethers.org/v6/)
- **DEX**: Uniswap v3
- **Network**: Arbitrum One
- **Storage**: `localStorage` (client-side)

---

> **Note**: This is a **simulation-heavy** bot. For **live trading**, ensure:
>
> - You are on the **Arbitrum network** in MetaMask.
> - You have **sufficient ETH** for gas fees.
> - You understand the **risks** of automated trading.