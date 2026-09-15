# 🚀 GOLIVE.md - SafeTrader DeFi NodeJS v11.1.0

## 📋 Prerequisites & Requirements

### 1. Network Configuration
- **Network:** Arbitrum One (Chain ID: 42161)
- **RPC Endpoints:** Use reliable, high-uptime WebSocket RPCs. Recommended providers:
  - `wss://arbitrum-one-rpc.publicnode.com`
  - `wss://arb1.arbitrum.io/ws`
  - `wss://arbitrum-mainnet.public.blastapi.io`
- **Factory Address:** `0x1F98431c8aD98523631AE4a59f267346ea31F984` (Uniswap V3)
- **Wrapped Native:** `0x82aF49447D8a07e3bd95BD0d56f35241523fBab1` (WETH)

### 2. Private Key & Security
- **Environment Variable:** `PRIVATE_KEY` in `.env`
- **Format:** Hex string without `0x` prefix (e.g., `a1b2c3...`)
- **Security Warning:** 
  - NEVER commit `.env` to version control.
  - Use a dedicated trading wallet with limited funds.
  - Enable hardware wallet signing if possible (requires adapter changes).
  - Set `PAPER_TRADING=false` in `.env` to enable live mode.

### 3. Token Selection & Liquidity
- **Recommended Tokens:** Focus on high-liquidity pairs with stable trading volume:
  - `ARB`, `GMX`, `UNI`, `LINK`, `WBTC`, `USDC`, `USDT`
  - Avoid low-cap/meme tokens with < $500k liquidity or high slippage.
- **Liquidity Filter:** The bot automatically skips pools with < `MIN_LIQUIDITY` (default: 50,000 WETH equivalent).
- **Slippage Tolerance:** Keep `MAX_SLIPPAGE=0.5` for major pairs. Increase to `1.0` only for volatile mid-caps.

### 4. Gas & Transaction Optimization
- **Gas Price Limit:** `MAX_GAS_PRICE=500` gwei. Adjust based on network congestion.
- **Gas Limit:** `GAS_LIMIT=300000`. Uniswap V3 swaps typically use 150k-250k.
- **Batching:** The bot processes swaps sequentially. For high-frequency trading, consider increasing `TRADE_COOLDOWN`.

### 5. Trading Parameters (Tuning)
- **Starting ETH:** `STARTING_ETH=0.01` (Adjust based on wallet balance)
- **Trade Size:** `TRADE_AMOUNT_PERCENT=10` (10% of portfolio per trade)
- **Min Profit Target:** `MIN_PROFIT_PERCENT=1.0` (Increased from 0.5 to prevent selling at a loss)
- **Pattern Detection:**
  - `WINDOW_SIZE=90` seconds
  - `MARGIN_OF_ERROR=3%`
  - `REGRESSION_DEGREE=3` (Cubic)
  - `PREDICTION_VALIDATION_COUNT=3`
  - `MIN_PREDICTION_ACCURACY=95%`

### 6. Database & Persistence
- **SQLite Path:** `SQLITE_PATH=./db/trader.db`
- **WAL Mode:** Enabled for concurrent read/write performance.
- **Backup:** Regularly backup `trader.db` before major updates.

### 7. Deployment Checklist
- [ ] Set `PRIVATE_KEY` in `.env`
- [ ] Set `PAPER_TRADING=false`
- [ ] Verify RPC endpoints are responsive via `curl` or `wscat`
- [ ] Test with `STARTING_ETH=0.001` to verify trade execution
- [ ] Monitor `logs/` or console for `Profit-Taking` and `Pattern Detection` messages
- [ ] Set up systemd/pm2 for auto-restart on crash
- [ ] Configure firewall to block inbound traffic except for monitoring ports

### 8. Troubleshooting
- **Connection Drops:** Check RPC rate limits. Rotate endpoints in `RPC_URL_1/2/3`.
- **High Slippage:** Token may have low liquidity. Reduce `TRADE_AMOUNT_PERCENT`.
- **DB Errors:** Ensure `better-sqlite3` is compiled for your Node version. Run `npm rebuild better-sqlite3`.
- **Profit Taking Fails:** Verify `MIN_PROFIT_PERCENT` isn't set too high for the token's volatility.

## ⚠️ Disclaimer
This bot uses algorithmic pattern detection and executes trades automatically. Past performance does not guarantee future results. DeFi trading carries high risk of loss. Use only funds you can afford to lose. Always test thoroughly in paper trading mode before going live.