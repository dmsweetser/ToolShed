# Uniswap Micro-Scalping Bot

---

## **Overview**

The **Uniswap Micro-Scalping Bot** is a high-frequency trading bot designed to execute micro-scalping strategies on the **Uniswap DEX** (Decentralized Exchange). It monitors **ALL tokens** observed on the blockchain, identifies short-term price patterns, and executes trades to capitalize on small price movements. The bot supports **Paper (Virtual), Shadow (Live Quotes), and Live (Real Transactions)** modes, allowing users to test strategies before deploying real funds.

---

## **Key Features**

### **1. Trading Modes**
- **Paper Mode**: Simulates trades using virtual funds. Ideal for testing strategies without risk.
- **Shadow Mode**: Uses live market data but does not execute real trades. Helps validate patterns and performance.
- **Live Mode**: Executes real transactions on the blockchain using your connected wallet.

### **2. Strategy**
- **Micro-Scalping**: Buys and sells tokens based on short-term price movements (e.g., 0.1%–0.5% changes over 5–120 seconds).
- **Pattern Matching**: Uses configurable buy/sell patterns (e.g., `>_+0.1_10-60` means "sell if the price rises by 0.1% over 10–60 seconds").
- **Sequential Trade Prevention**: Avoids consecutive trades on the same asset to reduce risk.
- **Age-Based Selling**: Automatically sells positions if they exceed a configurable age (default: 300 seconds) **and** are profitable.

### **3. Portfolio Management**
- **Real-Time PnL Tracking**: Monitors realized and unrealized profits/losses.
- **Asset Caps**: Limits exposure to any single token (e.g., max 10% of portfolio in non-ETH tokens).
- **Gas & Fee Tracking**: Accounts for real network gas fees and DEX trading fees.
- **Equity Curve**: Visualizes portfolio performance over time.

### **4. Supported Networks**
- **Arbitrum One** (Default)
- **Ethereum Mainnet**
- **Base**
- **Optimism**
- **Polygon**

### **5. Simulation Fidelity**
- **Gas Modeling**: Uses real network gas prices for accurate simulations.
- **Liquidity & Pool Fees**: Factors in Uniswap pool liquidity and fees.
- **Latency Simulation**: Simulates network delays for realistic testing.

---

## **Quick Start**

### **Prerequisites**
1. **MetaMask Wallet**: Install the [MetaMask browser extension](https://metamask.io/).
2. **Arbitrum Network**: Add the Arbitrum network to MetaMask (see [Adding Arbitrum to MetaMask](#adding-arbitrum-to-metamask)).
3. **ETH in Wallet**: Fund your MetaMask wallet with **ETH** (for gas fees) and optionally other tokens.

---

## **Setup Guide**

### **Step 1: Install and Launch the Bot**
1. **Download the Bot**: Save the HTML file to your local machine and open it in a modern browser (Chrome, Firefox, Edge).
2. **No Installation Required**: The bot runs entirely in your browser.

### **Step 2: Connect MetaMask**
1. Click the **"Connect MetaMask"** button in the **Settings > Wallet & Network** tab.
2. Approve the connection request in the MetaMask popup.
3. Ensure your wallet is on the **Arbitrum network** (or another supported network).

### **Step 3: Configure Trading Settings**
Navigate to the **Trading** tab and configure the following:

#### **Buy/Sell Patterns**
- **Buy Patterns**: Define conditions for buying (e.g., `<_-0.1_10-60` buys if the price drops by 0.1% over 10–60 seconds).
- **Sell Patterns**: Define conditions for selling (e.g., `>_+0.1_10-60` sells if the price rises by 0.1% over 10–60 seconds).
- **Default Patterns**: Click **"Load Defaults"** to use pre-configured patterns.

#### **Execution Settings**
- **Starting ETH**: Amount of ETH to use for trading (automatically set to your wallet balance in **Live Mode**).
- **Trade Amount (%)**: Percentage of starting ETH to use per trade (default: 1%).
- **Max Open Trades**: Maximum number of simultaneous positions (default: 50).
- **Max Slippage (%)**: Maximum allowed slippage before a trade is rejected (default: 0.2%).
- **Latency Simulation**: Simulate network delays for realistic testing (default: None).
- **Min Profit for Selling (%)**: Minimum profit required to sell (default: 2%).
- **Max Position Age (seconds)**: Auto-sell if position is older than this **and** profitable (default: 300 seconds).
- **Prevent Sequential Trades**: Enable to avoid consecutive trades on the same asset.

#### **Asset Caps**
- **ETH Cap (%)**: Maximum % of portfolio in ETH (default: 100%).
- **Other Tokens Cap (%)**: Maximum % of portfolio in any other single token (default: 5%).

#### **Save Settings**
Click **"Save Settings"** to apply your configuration.

---

## **Funding Your MetaMask Wallet**

### **Adding Arbitrum to MetaMask**
If Arbitrum is not already added to your MetaMask:
1. Open MetaMask and click the network dropdown (top-left).
2. Click **"Add Network"** > **"Add a network manually"**. 
3. Enter the following details:
   - **Network Name**: Arbitrum One
   - **RPC URL**: `https://arbitrum-mainnet.infura.io/v3/YOUR_INFURA_KEY` (or use a public RPC like `https://arb1.arbitrum.io/rpc`)
   - **Chain ID**: `42161`
   - **Currency Symbol**: ETH
   - **Block Explorer URL**: `https://arbiscan.io/`
4. Click **"Save"**. Arbitrum is now added to your MetaMask.

---

### **Funding with ETH from Coinbase**
1. **Buy ETH on Coinbase**:
   - Log in to your [Coinbase account](https://www.coinbase.com/).
   - Navigate to **"Buy & Sell"** and purchase **ETH** (Ethereum).

2. **Withdraw ETH to MetaMask**:
   - In Coinbase, go to **"Assets"** > **"ETH"** > **"Send"**. 
   - Enter your **MetaMask Arbitrum wallet address** (starts with `0x...`).
     - **Important**: Ensure you are sending ETH to the **Ethereum Mainnet** version of your MetaMask address (not Arbitrum). Coinbase does not support direct withdrawals to Arbitrum.
   - Confirm the transaction. Coinbase will charge a network fee.

3. **Bridge ETH to Arbitrum**:
   Since Coinbase only supports Ethereum Mainnet withdrawals, you must bridge your ETH to Arbitrum:
   - Go to the [Arbitrum Bridge](https://bridge.arbitrum.io/).
   - Connect your MetaMask wallet (ensure it is set to **Ethereum Mainnet**).
   - Enter the amount of ETH to bridge and click **"Deposit"**. 
   - Confirm the transaction in MetaMask. This will take ~10–15 minutes to complete.
   - Once the transaction is confirmed, switch your MetaMask to **Arbitrum One** to see your bridged ETH.

   **Alternative Bridges**:
   - [Hop Protocol](https://hop.exchange/)
   - [Across](https://across.to/)

---

## **Sending Proceeds Back to Coinbase**

### **Step 1: Bridge ETH from Arbitrum to Ethereum Mainnet**
1. Ensure your MetaMask is set to **Arbitrum One**. 
2. Go to the [Arbitrum Bridge](https://bridge.arbitrum.io/).
3. Connect your MetaMask wallet.
4. Select **"Withdraw"** and enter the amount of ETH to bridge back to Ethereum Mainnet.
5. Confirm the transaction in MetaMask. This will take ~10–15 minutes.

### **Step 2: Send ETH from MetaMask to Coinbase**
1. Switch your MetaMask to **Ethereum Mainnet**. 
2. Copy your **Coinbase ETH deposit address** (find this in Coinbase under **"Assets"** > **"ETH"** > **"Receive"**).
3. In MetaMask, click **"Send"** and paste your Coinbase address.
4. Enter the amount of ETH to send and confirm the transaction.
5. Wait for the transaction to confirm on Ethereum (~5–10 minutes).
6. The ETH will appear in your Coinbase account once confirmed.

---

## **Running the Bot in Live Mode**

### **Step 1: Switch to Live Mode**
1. In the **Dashboard** tab, select **"Live (Real Transactions)"** from the **Execution Mode** dropdown.
2. Ensure your MetaMask is **connected** and on the **Arbitrum network** (or your chosen network).

### **Step 2: Start the Bot**
1. Click the **"Start"** button in the **Dashboard** tab.
2. The bot will begin monitoring the blockchain for trading opportunities based on your configured patterns.

### **Step 3: Monitor Performance**
- **Dashboard**: View real-time PnL, active positions, and recent trades.
- **Portfolio Tab**: Track balances, allocations, and performance metrics.
- **History Tab**: Review all executed trades and export trade history as CSV.
- **Logs Tab**: Debug and monitor bot activity.

---

## **Safety & Risk Management**

### **Key Risks**
1. **Smart Contract Risk**: Uniswap and bridging protocols are audited but not risk-free.
2. **Gas Fees**: High network congestion can lead to expensive transactions.
3. **Impermanent Loss**: Holding tokens in liquidity pools may result in impermanent loss.
4. **Market Volatility**: Rapid price swings can lead to losses, especially with leverage or high-frequency trading.

### **Mitigation Strategies**
- **Start Small**: Use a small amount of ETH (e.g., 0.01 ETH) for your first live trades.
- **Test in Shadow Mode**: Validate patterns and performance before switching to Live Mode.
- **Set Asset Caps**: Limit exposure to any single token (e.g., max 10% of portfolio).
- **Use Stop-Loss Patterns**: Configure sell patterns to exit losing positions quickly.
- **Monitor Gas Fees**: Avoid trading during high gas periods (check [Etherscan Gas Tracker](https://etherscan.io/gastracker)).

---

## **Troubleshooting**

### **Common Issues**
| Issue | Solution |
|-------|----------|
| **MetaMask not connecting** | Ensure MetaMask is installed and unlocked. Refresh the page. |
| **Bot not starting** | Check that you have valid buy/sell patterns configured. |
| **No trades executing** | Verify the bot is in **Live Mode** and your wallet has sufficient ETH for gas fees. |
| **High gas fees** | Reduce trade frequency or wait for lower gas periods. |
| **Failed transactions** | Increase **Max Slippage** or **Gas Limit** in settings. |
| **Tokens not appearing** | Ensure the bot is running and connected to the correct network. |

### **Debugging**
1. Open the **Logs** tab to view real-time bot activity.
2. Enable **Debug Mode** in **Settings > Advanced Settings** for detailed logs.
3. Check the browser console (**F12 > Console**) for errors.

---

## **FAQ**

### **Q: Can I use this bot on mobile?**
A: No, the bot is designed for desktop browsers. MetaMask mobile does not support all required features.

### **Q: How much ETH do I need to start?**
A: We recommend starting with **0.01–0.1 ETH** to cover gas fees and initial trades. Arbitrum gas fees are typically lower than Ethereum Mainnet.

### **Q: Can I run the bot 24/7?**
A: Yes, but ensure your computer remains online and the browser tab stays open. For uninterrupted operation, consider running the bot on a cloud server or a dedicated machine.

### **Q: Are profits automatically sent to my wallet?**
A: In **Live Mode**, profits are realized in your connected wallet. You can manually withdraw them to Coinbase or another address.

### **Q: Can I customize the trading strategy?**
A: Yes! Modify the **buy/sell patterns**, **trade amount**, **asset caps**, and other settings in the **Trading** tab.

### **Q: What happens if the bot crashes?**
A: The bot saves your settings and trade history locally. If the page refreshes or crashes, reload the HTML file to resume. For critical operations, use **Auto-Backup** in **Settings > Backup & Security**.

---

## **Disclaimer**

> **⚠️ Use at Your Own Risk**
> This bot is provided for **educational and testing purposes only**. Trading cryptocurrencies involves significant risk, including the potential loss of your entire investment. The developers are **not responsible** for any losses, damages, or liabilities arising from the use of this software.
>
> - **Not Financial Advice**: This is not investment advice. Always do your own research (DYOR).
> - **No Guarantees**: Past performance is not indicative of future results. The bot does not guarantee profits.
> - **Test Thoroughly**: Always test in **Paper Mode** or **Shadow Mode** before using real funds.

---

## **Support & Contributions**

### **Reporting Issues**
- Open an issue on the [GitHub repository](https://github.com/your-repo/uniswap-micro-scalping-bot) (if available).
- Include logs from the **Logs** tab and steps to reproduce the issue.

### **Contributing**
- Fork the repository and submit pull requests for bug fixes or new features.
- Suggestions for improvements are welcome!

---

## **License**

This project is licensed under the **MIT License**. See [LICENSE](LICENSE) for details.

---

## **Changelog**

| Version | Date | Changes |
|---------|------|---------|
| 8.1.0 | 2026-08-22 | Initial release. |

---

*Happy Trading! 🚀*