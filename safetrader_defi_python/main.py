#!/usr/bin/env python3
"""
Uniswap Arbitrum Trading Bot - Python Version
A command-line trading bot that monitors prices, detects patterns, and simulates trades.
Equivalent functionality to the provided JavaScript page but without UI.

Features:
- Real-time price monitoring via CoinGecko API
- Pattern-based trading (buy/sell triggers)
- Trade simulation with PnL tracking
- State persistence (JSON files)
- Auto-backup functionality
- CLI interface for manual actions
"""

import json
import os
import sys
import time
import logging
import argparse
import random
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field, asdict


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class ChainConfig:
    """Configuration for a blockchain network."""
    name: str
    chain_id: int
    ws: str
    http: str
    factory: str
    wrapped_native: str
    quote_mode: str
    quote_label: str
    stables: List[str]


@dataclass
class TokenConfig:
    """Configuration for a token."""
    address: Optional[str]
    decimals: int
    symbol: str
    is_native: bool = False
    cg_id: Optional[str] = None  # CoinGecko ID


@dataclass
class Trade:
    """Represents a trade (buy or sell)."""
    id: str
    timestamp: str
    token: str
    trade_type: str  # 'buy' or 'sell'
    price: float
    amount_usd: float
    token_amount: float
    fee: float
    status: str = "open"  # 'open' or 'closed'
    tx_hash: str = ""
    pnl: float = 0.0
    pattern: str = ""
    gas_price: float = 0.0
    price_impact: float = 0.0
    slippage: float = 0.0
    network: str = ""
    closed_at: Optional[str] = None
    closed_price: Optional[float] = None
    stopped_out: bool = False
    take_profit: bool = False
    stop_loss: bool = False


@dataclass
class BotState:
    """Global state of the trading bot."""
    is_running: bool = False
    is_connected: bool = False
    wallet_address: Optional[str] = None
    network: str = "arbitrum"
    prices: Dict[str, float] = field(default_factory=dict)
    price_history: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
    trades: List[Dict[str, Any]] = field(default_factory=list)
    start_time: Optional[str] = None
    last_price_update: Optional[str] = None
    last_trade_time: Optional[float] = None
    gas_price: float = 0.0
    eth_price: float = 0.0
    arb_price: float = 0.0


# =============================================================================
# CONSTANTS
# =============================================================================

# Chain configurations
CHAINS: Dict[str, ChainConfig] = {
    "arbitrum": ChainConfig(
        name="Arbitrum",
        chain_id=42161,
        ws="wss://arb1.arbitrum.io/ws",
        http="https://arb1.arbitrum.io/rpc",
        factory="0x1F98431c8aD98523631AE4a59f267346ea31F984",
        wrapped_native="0x82aF49447D8a07e3bd95BD0d56f35241523fBab1",
        quote_mode="native",
        quote_label="WETH",
        stables=[
            "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",  # USDC
            "0xFd086bC7CD5C481DCC9C85ebe478A1C0b69FCbb9",  # USDT
        ],
    ),
    "ethereum": ChainConfig(
        name="Ethereum",
        chain_id=1,
        ws="wss://eth-mainnet.publicnode.com",
        http="https://eth-mainnet.publicnode.com",
        factory="0x1F98431c8aD98523631AE4a59f267346ea31F984",
        wrapped_native="0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
        quote_mode="usd",
        quote_label="USD",
        stables=[
            "0xA0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",  # USDC
            "0xdAC17F958D2ee523a2206206994597C13D831ec7",  # USDT
            "0x6B175474E89094C44Da98b954EedeAC495271d0F",  # DAI
        ],
    ),
    "base": ChainConfig(
        name="Base",
        chain_id=8453,
        ws="wss://base-mainnet.publicnode.com",
        http="https://base-mainnet.publicnode.com",
        factory="0x33128a8fC17869897dcE68Ed026d694621f6FDfD",
        wrapped_native="0x4200000000000000000000000000000000000006",
        quote_mode="native",
        quote_label="WETH",
        stables=[
            "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",  # USDC
            "0x60a3e35cc302bfa44cb288bc5a4f316fdb1adb42",  # DAI
        ],
    ),
    "optimism": ChainConfig(
        name="Optimism",
        chain_id=10,
        ws="wss://optimism-mainnet.publicnode.com",
        http="https://optimism-mainnet.publicnode.com",
        factory="0x1F98431c8aD98523631AE4a59f267346ea31F984",
        wrapped_native="0x4200000000000000000000000000000000000006",
        quote_mode="native",
        quote_label="WETH",
        stables=[
            "0x0b2C639c533813f4aAa9D7837CAf62653d097Ff85",  # USDC
            "0x7F5c764cBc14f9669B88837ca1490cCa17c31607",  # USDT
        ],
    ),
    "polygon": ChainConfig(
        name="Polygon",
        chain_id=137,
        ws="wss://polygon-bor.publicnode.com",
        http="https://polygon-bor.publicnode.com",
        factory="0x1F98431c8aD98523631AE4a59f267346ea31F984",
        wrapped_native="0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270",
        quote_mode="native",
        quote_label="WPOL",
        stables=[
            "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174",  # USDC
            "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359",  # USDT
        ],
    ),
}


# Default token configurations (addresses for Arbitrum)
TOKENS: Dict[str, TokenConfig] = {
    "ETH": TokenConfig(address=None, decimals=18, symbol="ETH", is_native=True, cg_id="ethereum"),
    "WBTC": TokenConfig(address="0x2f2a2543B76A416654947aaB75B4e35b52a17231", decimals=8, symbol="WBTC", cg_id="wrapped-bitcoin"),
    "UNI": TokenConfig(address="0xfa7F8980b0f1E64A2162791cc3b0871572f1F7f0", decimals=18, symbol="UNI", cg_id="uniswap"),
    "LINK": TokenConfig(address="0xf97f4df75117a78c1A5a0DBb814Af92458539FB4", decimals=18, symbol="LINK", cg_id="chainlink"),
    "ARB": TokenConfig(address="0x912CE59144196C11c48067255325c5414506085A", decimals=18, symbol="ARB", cg_id="arbitrum"),
    "GMX": TokenConfig(address="0xfc5A1A6EB076a2C7aD06eD22C5C769A78b3Fa3A1", decimals=18, symbol="GMX", cg_id="gmx"),
    "USDC": TokenConfig(address="0xaf88d065e77c8cC2239327C5EDb3A432268e5831", decimals=6, symbol="USDC", cg_id="usd-coin"),
    "USDT": TokenConfig(address="0xFd086bC7CD5C481DCC9C85ebe478A1C0b69FCbb9", decimals=6, symbol="USDT", cg_id="tether"),
}


# =============================================================================
# LOGGING SETUP
# =============================================================================

def setup_logging(debug_mode: str = "none") -> logging.Logger:
    """Configure logging based on debug mode."""
    log_levels = {
        "none": logging.INFO,
        "basic": logging.INFO,
        "verbose": logging.DEBUG,
    }
    level = log_levels.get(debug_mode, logging.INFO)

    # Create logger
    logger = logging.getLogger("trading_bot")
    logger.setLevel(level)

    # Clear existing handlers
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    # Create formatters
    formatter = logging.Formatter(
        "%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # File handler
    file_handler = logging.FileHandler("trading_bot.log")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger


# =============================================================================
# CONFIGURATION MANAGEMENT
# =============================================================================

def load_config(config_path: str = "config.json") -> Dict[str, Any]:
    """Load configuration from JSON file."""
    if not Path(config_path).exists():
        raise FileNotFoundError(f"Configuration file {config_path} not found.")
    with open(config_path, "r") as f:
        return json.load(f)


def save_config(config: Dict[str, Any], config_path: str = "config.json") -> None:
    """Save configuration to JSON file."""
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)


# =============================================================================
# STATE MANAGEMENT
# =============================================================================

def load_state(state_path: str = "state.json") -> BotState:
    """Load bot state from JSON file."""
    if Path(state_path).exists():
        with open(state_path, "r") as f:
            state_dict = json.load(f)
            # Convert to BotState
            return BotState(
                is_running=state_dict.get("is_running", False),
                is_connected=state_dict.get("is_connected", False),
                wallet_address=state_dict.get("wallet_address"),
                network=state_dict.get("network", "arbitrum"),
                prices=state_dict.get("prices", {}),
                price_history=state_dict.get("price_history", {}),
                trades=state_dict.get("trades", []),
                start_time=state_dict.get("start_time"),
                last_price_update=state_dict.get("last_price_update"),
                last_trade_time=state_dict.get("last_trade_time"),
                gas_price=state_dict.get("gas_price", 0.0),
                eth_price=state_dict.get("eth_price", 0.0),
                arb_price=state_dict.get("arb_price", 0.0),
            )
    return BotState()


def save_state(state: BotState, state_path: str = "state.json") -> None:
    """Save bot state to JSON file."""
    with open(state_path, "w") as f:
        json.dump(asdict(state), f, indent=2)


def load_trades(trades_path: str = "trades.json") -> List[Dict[str, Any]]:
    """Load trade history from JSON file."""
    if Path(trades_path).exists():
        with open(trades_path, "r") as f:
            return json.load(f)
    return []


def save_trades(trades: List[Dict[str, Any]], trades_path: str = "trades.json") -> None:
    """Save trade history to JSON file."""
    with open(trades_path, "w") as f:
        json.dump(trades, f, indent=2)


# =============================================================================
# PRICE FEED
# =============================================================================

class PriceFeed:
    """Handles price updates from CoinGecko API."""

    COINGECKO_URL = "https://api.coingecko.com/api/v3"

    def __init__(self, config: Dict[str, Any], state: BotState, logger: logging.Logger):
        self.config = config
        self.state = state
        self.logger = logger
        self.session = None

    def _get_coingecko_id(self, symbol: str) -> str:
        """Get CoinGecko ID for a token symbol."""
        token_config = TOKENS.get(symbol)
        if token_config and token_config.cg_id:
            return token_config.cg_id
        # Fallback: use lowercase symbol
        return symbol.lower()

    def update_prices(self) -> None:
        """Update token prices from CoinGecko API."""
        try:
            import requests
            if self.session is None:
                self.session = requests.Session()

            # Get all token symbols that need prices
            symbols_to_update = []
            for symbol in self.config.get("tokens", list(TOKENS.keys())):
                if symbol not in self.state.prices:
                    symbols_to_update.append(symbol)
                # Always update to get fresh prices
                symbols_to_update.append(symbol)

            if not symbols_to_update:
                return

            # Map symbols to CoinGecko IDs
            cg_ids = [self._get_coingecko_id(s) for s in symbols_to_update]
            cg_ids_str = ",".join(cg_ids)

            # Fetch prices from CoinGecko
            url = f"{self.COINGECKO_URL}/simple/price"
            params = {
                "ids": cg_ids_str,
                "vs_currencies": "usd",
            }
            if self.config.get("coingecko_api_key"):
                params["x_cg_demo_api_key"] = self.config["coingecko_api_key"]

            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            # Update prices
            for symbol in symbols_to_update:
                cg_id = self._get_coingecko_id(symbol)
                if cg_id in data and "usd" in data[cg_id]:
                    new_price = float(data[cg_id]["usd"])
                    old_price = self.state.prices.get(symbol, new_price)
                    self.state.prices[symbol] = new_price

                    # Update price history
                    if symbol not in self.state.price_history:
                        self.state.price_history[symbol] = []

                    self.state.price_history[symbol].append({
                        "price": new_price,
                        "timestamp": datetime.utcnow().isoformat(),
                    })

                    # Keep only the last N price points
                    max_history = 1000
                    if len(self.state.price_history[symbol]) > max_history:
                        self.state.price_history[symbol] = self.state.price_history[symbol][-max_history:]

                    self.logger.debug(f"Updated {symbol} price: ${old_price:.6f} -> ${new_price:.6f}")

            self.state.last_price_update = datetime.utcnow().isoformat()
            self.logger.info(f"Updated prices for {len(symbols_to_update)} tokens")

        except Exception as e:
            self.logger.error(f"Error updating prices: {e}")

    def update_eth_price(self) -> None:
        """Update ETH price specifically."""
        try:
            import requests
            if self.session is None:
                self.session = requests.Session()

            url = f"{self.COINGECKO_URL}/simple/price"
            params = {
                "ids": "ethereum",
                "vs_currencies": "usd",
            }
            response = requests.get(url, params=params, timeout=10)
            data = response.json()
            if "ethereum" in data and "usd" in data["ethereum"]:
                self.state.eth_price = float(data["ethereum"]["usd"])
                self.logger.info(f"Updated ETH price: ${self.state.eth_price:.2f}")
        except Exception as e:
            self.logger.error(f"Error updating ETH price: {e}")

    def update_gas_price(self) -> None:
        """Update gas price (simulated in test mode)."""
        try:
            if self.config.get("is_test_mode", True):
                # Simulate gas price in test mode
                self.state.gas_price = random.uniform(10, 50)
            else:
                # In real mode, would fetch from RPC
                # For now, use a placeholder
                self.state.gas_price = 50.0
            self.logger.debug(f"Gas price updated: {self.state.gas_price:.2f} gwei")
        except Exception as e:
            self.logger.error(f"Error updating gas price: {e}")


# =============================================================================
# PATTERN DETECTION
# =============================================================================

class PatternDetector:
    """Detects buy/sell patterns based on price history."""

    def __init__(self, config: Dict[str, Any], state: BotState, logger: logging.Logger, trade_executor: "TradeExecutor"):
        self.config = config
        self.state = state
        self.logger = logger
        self.trade_executor = trade_executor

    def check_patterns(self) -> None:
        """Check all tokens for buy/sell patterns."""
        buy_patterns = self._parse_patterns(self.config.get("buy_patterns", ""))
        sell_patterns = self._parse_patterns(self.config.get("sell_patterns", ""))

        for symbol, history in self.state.price_history.items():
            if len(history) < 2:
                continue
            self._check_token_patterns(symbol, history, buy_patterns, sell_patterns)

    def _parse_patterns(self, pattern_str: str) -> List[Dict[str, Any]]:
        """
        Parse pattern strings into structured patterns.
        
        Pattern format:
        - Buy: <_-0.5_150-450 (price drops 0.5% over 150-450 seconds)
        - Sell: >_+0.5_60-300 (price rises 0.5% over 60-300 seconds)
        """
        patterns = []
        if not pattern_str:
            return patterns

        for pattern in pattern_str.split(","):
            pattern = pattern.strip()
            if not pattern:
                continue

            if pattern.startswith("<_"):
                # Buy pattern: <_-0.5_150-450
                parts = pattern[2:].split("_")
                if len(parts) >= 2:
                    try:
                        threshold = float(parts[0])
                        time_range = parts[1].split("-")
                        min_sec = int(time_range[0]) if len(time_range) > 0 else 0
                        max_sec = int(time_range[1]) if len(time_range) > 1 else 0
                        patterns.append({
                            "type": "buy",
                            "threshold": threshold,
                            "min_sec": min_sec,
                            "max_sec": max_sec,
                            "raw": pattern,
                        })
                    except (ValueError, IndexError) as e:
                        self.logger.warning(f"Invalid buy pattern: {pattern} ({e})")

            elif pattern.startswith(">_"):
                # Sell pattern: >_+0.5_60-300
                parts = pattern[2:].split("_")
                if len(parts) >= 2:
                    try:
                        threshold = float(parts[0])
                        time_range = parts[1].split("-")
                        min_sec = int(time_range[0]) if len(time_range) > 0 else 0
                        max_sec = int(time_range[1]) if len(time_range) > 1 else 0
                        patterns.append({
                            "type": "sell",
                            "threshold": threshold,
                            "min_sec": min_sec,
                            "max_sec": max_sec,
                            "raw": pattern,
                        })
                    except (ValueError, IndexError) as e:
                        self.logger.warning(f"Invalid sell pattern: {pattern} ({e})")

        return patterns

    def _check_token_patterns(
        self,
        symbol: str,
        history: List[Dict[str, Any]],
        buy_patterns: List[Dict[str, Any]],
        sell_patterns: List[Dict[str, Any]],
    ) -> None:
        """Check price history for a token against patterns."""
        # Need at least 2 price points to calculate change
        if len(history) < 2:
            return

        # Get the two most recent price points
        latest = history[-1]
        previous = history[-2]

        # Calculate percentage change
        if previous["price"] == 0:
            return
        price_change_pct = ((latest["price"] - previous["price"]) / previous["price"]) * 100

        # Check buy patterns (price drop)
        for pattern in buy_patterns:
            if price_change_pct < pattern["threshold"]:
                self.logger.info(
                    f"Buy pattern matched for {symbol}: {pattern['raw']} "
                    f"(Change: {price_change_pct:.2f}%)"
                )
                self.trade_executor.execute_trade(
                    symbol, "buy", self.config.get("trade_step", 3.0), pattern["raw"]
                )

        # Check sell patterns (price rise)
        for pattern in sell_patterns:
            if price_change_pct > pattern["threshold"]:
                self.logger.info(
                    f"Sell pattern matched for {symbol}: {pattern['raw']} "
                    f"(Change: {price_change_pct:.2f}%)"
                )
                self.trade_executor.execute_trade(
                    symbol, "sell", self.config.get("trade_step", 3.0), pattern["raw"]
                )


# =============================================================================
# TRADE EXECUTION
# =============================================================================

class TradeExecutor:
    """Handles trade execution (simulated or real)."""

    def __init__(self, config: Dict[str, Any], state: BotState, logger: logging.Logger):
        self.config = config
        self.state = state
        self.logger = logger

    def execute_trade(self, symbol: str, trade_type: str, amount_usd: float, pattern: str = "") -> Optional[Dict[str, Any]]:
        """
        Execute a trade (simulated in test mode, real in prod mode).
        
        Args:
            symbol: Token symbol (e.g., "ETH")
            trade_type: "buy" or "sell"
            amount_usd: Trade amount in USD
            pattern: Pattern that triggered the trade
        """
        # Check if trading is enabled
        if not self.state.is_running:
            self.logger.warning("Bot is not running. Trade not executed.")
            return None

        # Check cooldown
        if (
            self.state.last_trade_time
            and time.time() - self.state.last_trade_time < self.config.get("trade_cooldown", 60)
        ):
            self.logger.info(f"Trade cooldown active for {symbol}. Skipping.")
            return None

        # Check max open trades
        open_trades = [t for t in self.state.trades if t["status"] == "open"]
        if len(open_trades) >= self.config.get("max_trades", 5):
            self.logger.info(f"Max open trades ({len(open_trades)}) reached. Skipping.")
            return None

        # Get current price
        price = self.state.prices.get(symbol)
        if price is None or price <= 0:
            self.logger.warning(f"No valid price for {symbol}. Trade not executed.")
            return None

        # Calculate token amount
        token_amount = amount_usd / price

        # Calculate gas fee (simulated)
        gas_price = self.state.gas_price
        gas_limit = self.config.get("gas_limit", 500000)
        gas_fee_eth = (gas_limit * gas_price) / 1e9 / 1e18  # Convert from gwei to ETH
        eth_price = self.state.eth_price if self.state.eth_price > 0 else 3000  # Default ETH price
        gas_fee_usd = gas_fee_eth * eth_price

        # Create trade
        trade = {
            "id": f"trade_{int(time.time() * 1000)}",
            "timestamp": datetime.utcnow().isoformat(),
            "token": symbol,
            "type": trade_type,
            "price": price,
            "amount_usd": amount_usd,
            "token_amount": token_amount,
            "fee": gas_fee_usd,
            "status": "open",
            "tx_hash": f"0x{os.urandom(16).hex()}",
            "pnl": 0.0,
            "pattern": pattern,
            "gas_price": gas_price,
            "price_impact": 0.0,
            "slippage": self.config.get("slippage", 0.5),
            "network": self.state.network,
            "stopped_out": False,
            "take_profit": False,
            "stop_loss": False,
        }

        # In test mode, just simulate
        if self.config.get("is_test_mode", True):
            self.logger.info(
                f"[TEST MODE] Simulated {trade_type} {token_amount:.6f} {symbol} "
                f"at ${price:.2f} (Gas Fee: ${gas_fee_usd:.4f}, Pattern: {pattern})"
            )
        else:
            # In real mode, would execute actual trade
            self.logger.warning(
                f"[PROD MODE] Real trade execution not implemented. "
                f"Trade would be: {trade_type} {token_amount:.6f} {symbol} at ${price:.2f}"
            )

        # Add trade to state
        self.state.trades.append(trade)
        self.state.last_trade_time = time.time()

        # Auto-settle if it's a sell trade (find matching buy)
        if trade_type == "sell":
            self._try_settle_trade(trade)

        return trade

    def _try_settle_trade(self, sell_trade: Dict[str, Any]) -> None:
        """Try to settle a sell trade with a matching buy trade."""
        # Find the most recent open buy trade for the same token
        buy_trade = None
        for trade in reversed(self.state.trades):
            if (
                trade["status"] == "open"
                and trade["type"] == "buy"
                and trade["token"] == sell_trade["token"]
                and trade["id"] != sell_trade["id"]
            ):
                buy_trade = trade
                break

        if not buy_trade:
            self.logger.debug(f"No matching buy trade found for {sell_trade['token']}")
            return

        # Settle the trades
        buy_trade["status"] = "closed"
        buy_trade["closed_at"] = sell_trade["timestamp"]
        buy_trade["closed_price"] = sell_trade["price"]

        # Calculate PnL
        pnl = (
            sell_trade["token_amount"] * sell_trade["price"]
            - buy_trade["token_amount"] * buy_trade["price"]
            - buy_trade["fee"]
            - sell_trade["fee"]
        )
        buy_trade["pnl"] = pnl
        sell_trade["pnl"] = pnl

        # Check stop-loss and take-profit
        stop_loss_pct = self.config.get("stop_loss", 2)
        take_profit_pct = self.config.get("take_profit", 5)

        if pnl < 0:
            loss_pct = abs(pnl) / (buy_trade["token_amount"] * buy_trade["price"]) * 100
            if loss_pct >= stop_loss_pct:
                buy_trade["stopped_out"] = True
                sell_trade["stop_loss"] = True
                self.logger.info(f"Stop-loss triggered for {buy_trade['token']}: -{loss_pct:.2f}%")
        else:
            profit_pct = pnl / (buy_trade["token_amount"] * buy_trade["price"]) * 100
            if profit_pct >= take_profit_pct:
                buy_trade["take_profit"] = True
                sell_trade["take_profit"] = True
                self.logger.info(f"Take-profit triggered for {buy_trade['token']}: +{profit_pct:.2f}%")

        self.logger.info(
            f"Trade settled: {buy_trade['token']} {buy_trade['type']} -> {sell_trade['type']}, "
            f"PnL: ${pnl:.2f} ({pnl/(buy_trade['token_amount'] * buy_trade['price'])*100:.2f}%)"
        )

    def close_all_open_trades(self) -> None:
        """Close all open trades (for cleanup)."""
        for trade in self.state.trades:
            if trade["status"] == "open":
                trade["status"] = "closed"
                trade["closed_at"] = datetime.utcnow().isoformat()
                trade["closed_price"] = self.state.prices.get(trade["token"], trade["price"])
                trade["pnl"] = 0.0  # Simplified
        self.logger.info(f"Closed {len([t for t in self.state.trades if t['status'] == 'closed'])} open trades.")

    def get_open_trades(self) -> List[Dict[str, Any]]:
        """Get all open trades."""
        return [t for t in self.state.trades if t["status"] == "open"]

    def get_closed_trades(self) -> List[Dict[str, Any]]:
        """Get all closed trades."""
        return [t for t in self.state.trades if t["status"] == "closed"]


# =============================================================================
# STATISTICS CALCULATOR
# =============================================================================

class StatisticsCalculator:
    """Calculates and tracks bot statistics."""

    def __init__(self, config: Dict[str, Any], state: BotState, logger: logging.Logger):
        self.config = config
        self.state = state
        self.logger = logger

    def update_statistics(self) -> None:
        """Update and log bot statistics."""
        closed_trades = self.get_closed_trades()
        open_trades = self.get_open_trades()

        total_pnl = sum(t["pnl"] for t in closed_trades)
        winning_trades = [t for t in closed_trades if t["pnl"] > 0]
        losing_trades = [t for t in closed_trades if t["pnl"] < 0]

        win_rate = (
            len(winning_trades) / len(closed_trades) * 100
            if closed_trades
            else 0.0
        )

        self.logger.info(
            f"Statistics: Total Trades={len(closed_trades)}, "
            f"Open={len(open_trades)}, Win Rate={win_rate:.1f}%, "
            f"Winning={len(winning_trades)}, Losing={len(losing_trades)}, "
            f"Total PnL=${total_pnl:.2f}"
        )

    def get_pnl(self) -> Dict[str, float]:
        """Get PnL metrics (total, daily, weekly, monthly)."""
        closed_trades = self.get_closed_trades()
        total_pnl = sum(t["pnl"] for t in closed_trades)

        now = datetime.utcnow()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = now - timedelta(days=7)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        daily_pnl = sum(
            t["pnl"] for t in closed_trades
            if t.get("closed_at") and datetime.fromisoformat(t["closed_at"]) >= today_start
        )
        weekly_pnl = sum(
            t["pnl"] for t in closed_trades
            if t.get("closed_at") and datetime.fromisoformat(t["closed_at"]) >= week_start
        )
        monthly_pnl = sum(
            t["pnl"] for t in closed_trades
            if t.get("closed_at") and datetime.fromisoformat(t["closed_at"]) >= month_start
        )

        return {
            "total": total_pnl,
            "daily": daily_pnl,
            "weekly": weekly_pnl,
            "monthly": monthly_pnl,
        }

    def get_closed_trades(self) -> List[Dict[str, Any]]:
        """Get all closed trades."""
        return [t for t in self.state.trades if t["status"] == "closed"]

    def get_open_trades(self) -> List[Dict[str, Any]]:
        """Get all open trades."""
        return [t for t in self.state.trades if t["status"] == "open"]

    def get_portfolio_value(self) -> float:
        """Calculate current portfolio value."""
        open_trades = self.get_open_trades()
        total_value = 0.0
        for trade in open_trades:
            if trade["type"] == "buy":
                current_price = self.state.prices.get(trade["token"], trade["price"])
                total_value += trade["token_amount"] * current_price
        return total_value


# =============================================================================
# BACKUP MANAGER
# =============================================================================

class BackupManager:
    """Handles backup and restore of bot data."""

    def __init__(self, config: Dict[str, Any], state: BotState, logger: logging.Logger):
        self.config = config
        self.state = state
        self.logger = logger
        self.backup_dir = Path("backups")
        self.backup_dir.mkdir(exist_ok=True)

    def create_backup(self) -> None:
        """Create a backup of the current state."""
        backup_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "config": self.config,
            "state": asdict(self.state),
            "trades": self.state.trades,
        }

        filename = self.backup_dir / f"backup_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
        with open(filename, "w") as f:
            json.dump(backup_data, f, indent=2)
        self.logger.info(f"Backup created: {filename}")

    def restore_backup(self, backup_file: str) -> None:
        """Restore state from a backup file."""
        with open(backup_file, "r") as f:
            backup_data = json.load(f)

        self.config.update(backup_data["config"])
        self.state = BotState(**backup_data["state"])
        self.state.trades = backup_data["trades"]
        self.logger.info(f"Restored from backup: {backup_file}")

    def auto_backup(self) -> None:
        """Auto-backup if enabled."""
        if self.config.get("auto_backup", False):
            self.create_backup()

    def list_backups(self) -> List[str]:
        """List all backup files."""
        return [str(f) for f in self.backup_dir.glob("*.json")]


# =============================================================================
# MAIN BOT CLASS
# =============================================================================

class TradingBot:
    """Main trading bot class."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.logger = setup_logging(config.get("debug_mode", "none"))

        # Load state
        self.state = load_state()
        self.state.trades = load_trades()

        # Override state with config if needed
        if not self.state.network:
            self.state.network = config.get("network", "arbitrum")
        self.state.is_test_mode = config.get("is_test_mode", True)

        # Initialize components
        self.price_feed = PriceFeed(config, self.state, self.logger)
        self.trade_executor = TradeExecutor(config, self.state, self.logger)
        self.pattern_detector = PatternDetector(
            config, self.state, self.logger, self.trade_executor
        )
        self.stats_calculator = StatisticsCalculator(config, self.state, self.logger)
        self.backup_manager = BackupManager(config, self.state, self.logger)

        self.logger.info("Trading bot initialized")
        self.logger.info(f"Mode: {'TEST' if self.state.is_test_mode else 'PROD'}")
        self.logger.info(f"Network: {self.state.network}")
        self.logger.info(f"Primary price source: {config.get('primary_price_source', 'arbitrum')}")

    def start(self) -> None:
        """Start the trading bot."""
        self.state.is_running = True
        self.state.start_time = datetime.utcnow().isoformat()
        self.logger.info("Starting trading bot...")

        try:
            while self.state.is_running:
                # Update prices
                self.price_feed.update_prices()
                self.price_feed.update_eth_price()
                self.price_feed.update_gas_price()

                # Check patterns and execute trades
                self.pattern_detector.check_patterns()

                # Update statistics
                self.stats_calculator.update_statistics()
                pnl = self.stats_calculator.get_pnl()
                self.logger.info(
                    f"PnL: Total=${pnl['total']:.2f}, "
                    f"Daily=${pnl['daily']:.2f}, Weekly=${pnl['weekly']:.2f}, Monthly=${pnl['monthly']:.2f}"
                )

                # Auto-backup
                self.backup_manager.auto_backup()

                # Save state periodically
                save_state(self.state)
                save_trades(self.state.trades)

                # Sleep until next update
                interval = self.config.get("price_interval", 5000) / 1000
                time.sleep(interval)

        except KeyboardInterrupt:
            self.logger.info("Shutting down...")
            self.stop()

    def stop(self) -> None:
        """Stop the trading bot."""
        self.state.is_running = False
        self.trade_executor.close_all_open_trades()
        save_state(self.state)
        save_trades(self.state.trades)
        self.logger.info("Bot stopped. State saved.")

    def simulate_trade(self, symbol: str, trade_type: str, amount_usd: float) -> Optional[Dict[str, Any]]:
        """Simulate a manual trade."""
        return self.trade_executor.execute_trade(symbol, trade_type, amount_usd, "Manual")

    def get_open_trades(self) -> List[Dict[str, Any]]:
        """Get all open trades."""
        return self.trade_executor.get_open_trades()

    def get_closed_trades(self) -> List[Dict[str, Any]]:
        """Get all closed trades."""
        return self.trade_executor.get_closed_trades()

    def get_pnl(self) -> Dict[str, float]:
        """Get PnL metrics."""
        return self.stats_calculator.get_pnl()

    def get_portfolio_value(self) -> float:
        """Get current portfolio value."""
        return self.stats_calculator.get_portfolio_value()


# =============================================================================
# CLI INTERFACE
# =============================================================================

def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Uniswap Arbitrum Trading Bot - Python Version"
    )
    parser.add_argument(
        "--config",
        type=str,
        default="config.json",
        help="Path to config file (default: config.json)",
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Force test mode (simulated trades only)",
    )
    parser.add_argument(
        "--simulate",
        nargs=3,
        metavar=("SYMBOL", "TYPE", "AMOUNT"),
        help="Simulate a trade and exit (e.g., --simulate ETH buy 100)",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Show current status and exit",
    )
    parser.add_argument(
        "--trades",
        action="store_true",
        help="Show trade history and exit",
    )
    parser.add_argument(
        "--backup",
        action="store_true",
        help="Create a backup and exit",
    )
    parser.add_argument(
        "--restore",
        type=str,
        metavar="BACKUP_FILE",
        help="Restore from a backup file and exit",
    )
    parser.add_argument(
        "--list-backups",
        action="store_true",
        help="List all backup files and exit",
    )
    return parser.parse_args()


def main():
    """Main entry point."""
    args = parse_args()

    # Load configuration
    config = load_config(args.config)

    # Override with command line args
    if args.test:
        config["is_test_mode"] = True

    # Initialize bot
    bot = TradingBot(config)

    # Handle CLI commands
    if args.simulate:
        symbol, trade_type, amount_usd = args.simulate
        if trade_type not in ["buy", "sell"]:
            print("Error: TYPE must be 'buy' or 'sell'")
            sys.exit(1)
        try:
            trade = bot.simulate_trade(symbol, trade_type, float(amount_usd))
            if trade:
                print(f"Trade simulated: {trade_type} {trade['token_amount']:.6f} {symbol} at ${trade['price']:.2f}")
            else:
                print("Trade simulation failed")
        except Exception as e:
            print(f"Error: {e}")
            sys.exit(1)
        sys.exit(0)

    if args.status:
        pnl = bot.get_pnl()
        portfolio_value = bot.get_portfolio_value()
        open_trades = bot.get_open_trades()
        print("=" * 60)
        print("TRADING BOT STATUS")
        print("=" * 60)
        print(f"Mode: {'TEST' if config['is_test_mode'] else 'PROD'}")
        print(f"Network: {bot.state.network}")
        print(f"Running: {bot.state.is_running}")
        print(f"Last Price Update: {bot.state.last_price_update or 'Never'}")
        print(f"Gas Price: {bot.state.gas_price:.2f} gwei")
        print(f"ETH Price: ${bot.state.eth_price:.2f}")
        print(f"Open Trades: {len(open_trades)}")
        print(f"Portfolio Value: ${portfolio_value:.2f}")
        print(f"Total PnL: ${pnl['total']:.2f}")
        print(f"Daily PnL: ${pnl['daily']:.2f}")
        print(f"Weekly PnL: ${pnl['weekly']:.2f}")
        print(f"Monthly PnL: ${pnl['monthly']:.2f}")
        print("=" * 60)
        sys.exit(0)

    if args.trades:
        closed_trades = bot.get_closed_trades()
        open_trades = bot.get_open_trades()
        print("=" * 80)
        print("TRADE HISTORY")
        print("=" * 80)
        print(f"\nOpen Trades ({len(open_trades)}):")
        for trade in open_trades:
            print(
                f"  {trade['timestamp']} | {trade['type'].upper():4} | "
                f"{trade['token']:6} | ${trade['price']:8.2f} | "
                f"{trade['token_amount']:10.6f} | Pattern: {trade['pattern']}"
            )
        print(f"\nClosed Trades ({len(closed_trades)}):")
        for trade in closed_trades:
            pnl_str = f"${trade['pnl']:+.2f}"
            print(
                f"  {trade['timestamp']} | {trade['type'].upper():4} | "
                f"{trade['token']:6} | ${trade['price']:8.2f} | "
                f"{trade['token_amount']:10.6f} | PnL: {pnl_str:>10} | Pattern: {trade['pattern']}"
            )
        print("=" * 80)
        sys.exit(0)

    if args.backup:
        bot.backup_manager.create_backup()
        sys.exit(0)

    if args.restore:
        if not os.path.exists(args.restore):
            print(f"Error: Backup file {args.restore} not found")
            sys.exit(1)
        bot.backup_manager.restore_backup(args.restore)
        print(f"Restored from {args.restore}")
        sys.exit(0)

    if args.list_backups:
        backups = bot.backup_manager.list_backups()
        print("Available backups:")
        for backup in backups:
            print(f"  {backup}")
        sys.exit(0)

    # If no command specified, start the bot
    print("=" * 60)
    print("UNISWAP ARBITRUM TRADING BOT")
    print("=" * 60)
    print(f"Mode: {'TEST (Simulated)' if config['is_test_mode'] else 'PROD (Real Trades)'}")
    print(f"Network: {config.get('network', 'arbitrum')}")
    print(f"Primary Price Source: {config.get('primary_price_source', 'arbitrum')}")
    print(f"Tokens: {', '.join(config.get('tokens', []))}")
    print("=" * 60)
    print("Press Ctrl+C to stop")
    print("=" * 60)
    print()

    # Start the bot
    try:
        bot.start()
    except KeyboardInterrupt:
        bot.stop()
    except Exception as e:
        bot.logger.error(f"Fatal error: {e}")
        bot.stop()
        sys.exit(1)


if __name__ == "__main__":
    main()