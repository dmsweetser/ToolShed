# Uniswap Quick Swap Trader (Flask Version)

A **Python/Flask** implementation of the Uniswap Quick Swap Trader, designed to detect trading patterns (dips and swells) on Uniswap and execute trades automatically. This version replaces MetaMask with a `.env`-based private key for live transactions.

## Features
- **WETH-Centric Trading**: All trades are denominated in WETH.
- **USDC Profit Funneling**: Automatically converts profits to USDC when targets are met.
- **Pattern Detection**: Detects **dip** (buy low, sell high) and **swell** (price surge) patterns.
- **Live Mode**: Execute real trades on the Arbitrum network using a private key.
- **Simulated Mode**: Test strategies without spending real funds.
- **Portfolio Tracking**: Monitor open positions, PnL, and trade statistics.
- **Gas Optimization**: Adjusts trade amounts based on current gas prices.

## Setup Instructions

### 1. Clone the Repository
```bash
git clone <repository-url>
cd uniswap_trader