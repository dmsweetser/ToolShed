#!/usr/bin/env python3
"""
Uniswap Trading Bot with Portfolio Management
- Runs price_monitor.py in a background thread for live price data.
- Manages a portfolio based on real-time prices.
- Supports pattern detection, trade simulation, and state persistence.
"""

import json
import os
import sys
import time
import logging
import argparse
import threading
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any
from config import Config
from dataclasses import dataclass, field, asdict
from collections import defaultdict

# Import the price monitor
from price_monitor import (
    UniswapV3LiveMonitor,
    CHAINS,
    KNOWN_TOKENS,
    CONFIG as MONITOR_CONFIG,
    BotState as MonitorBotState,
    TokenState,
)

# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class Trade:
    """Represents a trade (buy or sell)."""
    id: str
    timestamp: str
    token: str
    token_address: str
    trade_type: str  # 'buy' or 'sell'
    price: float
    amount_usd: float
    token_amount: float
    fee: float
    status: str = "open"
    tx_hash: str = ""
    pnl: float = 0.0
    pattern: str = ""
    gas_price: float = 0.0
    network: str = ""


@dataclass
class Portfolio:
    """Represents the bot's portfolio."""
    holdings: Dict[str, float] = field(default_factory=dict)  # symbol: amount
    cash: float = 10000.0  # Default starting cash
    total_value: float = 0.0


@dataclass
class BotState:
    """Global state of the trading bot."""
    is_running: bool = False
    network: str = "arbitrum"
    current_chain_key: str = "arbitrum"
    prices: Dict[str, float] = field(default_factory=dict)
    price_history: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
    address_to_symbol: Dict[str, str] = field(default_factory=dict)
    symbol_to_address: Dict[str, str] = field(default_factory=dict)
    trades: List[Dict[str, Any]] = field(default_factory=list)
    portfolio: Portfolio = field(default_factory=Portfolio)
    start_time: Optional[str] = None
    last_price_update: Optional[str] = None
    last_trade_time: Optional[float] = None
    state_lock: threading.Lock = field(default_factory=threading.Lock)


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def norm(a: str) -> str:
    """Normalize address to lowercase string."""
    return str(a).lower()


def generate_symbol(address: str) -> str:
    """Generate a symbol from an address (for unknown tokens)."""
    return f"TKN_{address[:4].upper()}"


def short(a: str) -> str:
    """Shorten address for display."""
    if not a:
        return ""
    return f"{a[:6]}...{a[-4:]}"


def setup_logging(debug_mode: str = "none") -> logging.Logger:
    """Configure logging based on debug mode."""
    log_levels = {"none": logging.INFO, "basic": logging.INFO, "verbose": logging.DEBUG}
    level = log_levels.get(debug_mode, logging.INFO)

    logger = logging.getLogger("trading_bot")
    logger.setLevel(level)

    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    formatter = logging.Formatter(
        "%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    file_handler = logging.FileHandler("trading_bot.log")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger


def load_config(config_path: str = "./config.json") -> Dict[str, Any]:
    """Load configuration from .env file (falls back to defaults)."""
    return Config.as_dict()


def save_config(config: Dict[str, Any], config_path: str = "config.json") -> None:
    """Save configuration to JSON file."""
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)


def save_state(state: BotState, state_path: str = "trading_bot_state.json") -> None:
    """Save bot state to JSON file (excludes the lock)."""
    state_dict = {
        "is_running": state.is_running,
        "network": state.network,
        "current_chain_key": state.current_chain_key,
        "prices": state.prices,
        "price_history": state.price_history,
        "address_to_symbol": state.address_to_symbol,
        "symbol_to_address": state.symbol_to_address,
        "trades": state.trades,
        "portfolio": {
            "holdings": state.portfolio.holdings,
            "cash": state.portfolio.cash,
            "total_value": state.portfolio.total_value,
        },
        "start_time": state.start_time,
        "last_price_update": state.last_price_update,
        "last_trade_time": state.last_trade_time,
    }
    with open(state_path, "w") as f:
        json.dump(state_dict, f, indent=2)


def load_state(state_path: str = "trading_bot_state.json") -> BotState:
    """Load bot state from JSON file (recreates the lock)."""
    if Path(state_path).exists():
        with open(state_path, "r") as f:
            state_dict = json.load(f)
            portfolio_dict = state_dict.get("portfolio", {})
            portfolio = Portfolio(
                holdings=portfolio_dict.get("holdings", {}),
                cash=portfolio_dict.get("cash", 10000.0),
                total_value=portfolio_dict.get("total_value", 0.0),
            )
            return BotState(
                is_running=state_dict.get("is_running", False),
                network=state_dict.get("network", "arbitrum"),
                current_chain_key=state_dict.get("current_chain_key", "arbitrum"),
                prices=state_dict.get("prices", {}),
                price_history=state_dict.get("price_history", {}),
                address_to_symbol=state_dict.get("address_to_symbol", {}),
                symbol_to_address=state_dict.get("symbol_to_address", {}),
                trades=state_dict.get("trades", []),
                portfolio=portfolio,
                start_time=state_dict.get("start_time"),
                last_price_update=state_dict.get("last_price_update"),
                last_trade_time=state_dict.get("last_trade_time"),
            )
    return BotState()


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
# PORTFOLIO MANAGER
# =============================================================================

class PortfolioManager:
    """Manages the bot's portfolio and calculates its value."""

    def __init__(self, state: BotState, logger: logging.Logger):
        self.state = state
        self.logger = logger

    def update_value(self) -> None:
        """Update the portfolio's total value based on current prices."""
        with self.state.state_lock:
            total = self.state.portfolio.cash
            for symbol, amount in self.state.portfolio.holdings.items():
                price = self.state.prices.get(symbol)
                if price is not None:
                    total += amount * price
            self.state.portfolio.total_value = total
            self.logger.debug(f"Portfolio value updated: ${total:.2f}")

    def get_value(self) -> float:
        """Get the current portfolio value."""
        with self.state.state_lock:
            return self.state.portfolio.total_value

    def get_holdings(self) -> Dict[str, float]:
        """Get current token holdings."""
        with self.state.state_lock:
            return dict(self.state.portfolio.holdings)

    def add_token(self, symbol: str, amount: float) -> None:
        """Add tokens to the portfolio."""
        with self.state.state_lock:
            self.state.portfolio.holdings[symbol] = self.state.portfolio.holdings.get(symbol, 0.0) + amount
            self.logger.info(f"Added {amount:.6f} {symbol} to portfolio")

    def remove_token(self, symbol: str, amount: float) -> None:
        """Remove tokens from the portfolio."""
        with self.state.state_lock:
            if symbol in self.state.portfolio.holdings:
                self.state.portfolio.holdings[symbol] -= amount
                if self.state.portfolio.holdings[symbol] <= 0:
                    del self.state.portfolio.holdings[symbol]
                self.logger.info(f"Removed {amount:.6f} {symbol} from portfolio")

    def add_cash(self, amount: float) -> None:
        """Add cash to the portfolio."""
        with self.state.state_lock:
            self.state.portfolio.cash += amount
            self.logger.info(f"Added ${amount:.2f} cash to portfolio")

    def remove_cash(self, amount: float) -> None:
        """Remove cash from the portfolio."""
        with self.state.state_lock:
            self.state.portfolio.cash -= amount
            self.logger.info(f"Removed ${amount:.2f} cash from portfolio")


# =============================================================================
# TRADE EXECUTOR
# =============================================================================

class TradeExecutor:
    """Handles trade execution (simulated only)."""

    def __init__(self, config: Dict[str, Any], state: BotState, logger: logging.Logger, portfolio_manager: PortfolioManager):
        self.config = config
        self.state = state
        self.logger = logger
        self.portfolio_manager = portfolio_manager

    def execute_trade(self, symbol: str, address: str, trade_type: str, amount_usd: float, pattern: str = "") -> Optional[Dict[str, Any]]:
        """Execute a simulated trade."""
        with self.state.state_lock:
            if not self.state.is_running:
                self.logger.warning("Bot is not running. Trade not executed.")
                return None

            # Check if token is in allowed tokens list
            allowed_tokens = self.config.get("tokens", [])
            if allowed_tokens and symbol not in allowed_tokens:
                self.logger.info(f"Token {symbol} not in allowed tokens list. Skipping trade.")
                return None

            # Check cooldown
            if self.state.last_trade_time and (time.time() - self.state.last_trade_time) < self.config.get("trade_cooldown", 60):
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
            gas_price = 50.0  # Default simulated gas price
            gas_limit = self.config.get("gas_limit", 500000)
            gas_fee_eth = (gas_limit * gas_price) / 1e9 / 1e18
            eth_price = self.state.prices.get("WETH", 3000.0)  # Use WETH price if available
            gas_fee_usd = gas_fee_eth * eth_price

            # Check if we have enough cash for a buy
            if trade_type == "buy" and (amount_usd + gas_fee_usd) > self.state.portfolio.cash:
                self.logger.warning(f"Not enough cash for buy: ${amount_usd + gas_fee_usd:.2f} needed, ${self.state.portfolio.cash:.2f} available")
                return None

            # Check if we have enough tokens for a sell
            if trade_type == "sell" and token_amount > self.state.portfolio.holdings.get(symbol, 0):
                self.logger.warning(f"Not enough {symbol} for sell: {token_amount:.6f} needed, {self.state.portfolio.holdings.get(symbol, 0):.6f} available")
                return None

            # Create trade
            trade = {
                "id": f"trade_{int(time.time() * 1000)}",
                "timestamp": datetime.utcnow().isoformat(),
                "token": symbol,
                "token_address": address,
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
                "network": self.state.network,
            }

            if self.config.get("is_test_mode", True):
                self.logger.info(f"[TEST MODE] Simulated {trade_type} {token_amount:.6f} {symbol} at ${price:.2f} (Pattern: {pattern})")
            else:
                self.logger.warning("[PROD MODE] Real trade execution not implemented.")

            # Update portfolio
            if trade_type == "buy":
                self.portfolio_manager.remove_cash(amount_usd + gas_fee_usd)
                self.portfolio_manager.add_token(symbol, token_amount)
            elif trade_type == "sell":
                self.portfolio_manager.remove_token(symbol, token_amount)
                self.portfolio_manager.add_cash(amount_usd - gas_fee_usd)

            self.state.trades.append(trade)
            self.state.last_trade_time = time.time()

            # Auto-settle if it's a sell trade
            if trade_type == "sell":
                self._try_settle_trade(trade)

            return trade

    def _try_settle_trade(self, sell_trade: Dict[str, Any]) -> None:
        """Try to settle a sell trade with a matching buy trade."""
        with self.state.state_lock:
            buy_trade = None
            for trade in reversed(self.state.trades):
                if (trade["status"] == "open" and trade["type"] == "buy" and
                    trade["token"] == sell_trade["token"] and trade["id"] != sell_trade["id"]):
                    buy_trade = trade
                    break

            if not buy_trade:
                return

            buy_trade["status"] = "closed"
            buy_trade["closed_at"] = sell_trade["timestamp"]
            buy_trade["closed_price"] = sell_trade["price"]

            pnl = (sell_trade["token_amount"] * sell_trade["price"] -
                   buy_trade["token_amount"] * buy_trade["price"] -
                   buy_trade["fee"] - sell_trade["fee"])
            buy_trade["pnl"] = pnl
            sell_trade["pnl"] = pnl

            stop_loss_pct = self.config.get("stop_loss", 2)
            take_profit_pct = self.config.get("take_profit", 5)

            if pnl < 0:
                loss_pct = abs(pnl) / (buy_trade["token_amount"] * buy_trade["price"]) * 100
                if loss_pct >= stop_loss_pct:
                    buy_trade["stopped_out"] = True
                    self.logger.info(f"Stop-loss triggered for {buy_trade['token']}: -{loss_pct:.2f}%")
            else:
                profit_pct = pnl / (buy_trade["token_amount"] * buy_trade["price"]) * 100
                if profit_pct >= take_profit_pct:
                    buy_trade["take_profit"] = True
                    self.logger.info(f"Take-profit triggered for {buy_trade['token']}: +{profit_pct:.2f}%")

            self.logger.info(f"Trade settled: {buy_trade['token']} PnL: ${pnl:.2f}")

    def close_all_open_trades(self) -> None:
        """Close all open trades."""
        with self.state.state_lock:
            for trade in self.state.trades:
                if trade["status"] == "open":
                    trade["status"] = "closed"
                    trade["closed_at"] = datetime.utcnow().isoformat()
                    trade["closed_price"] = self.state.prices.get(trade["token"], trade["price"])
                    trade["pnl"] = 0.0

    def get_open_trades(self) -> List[Dict[str, Any]]:
        with self.state.state_lock:
            return [t for t in self.state.trades if t["status"] == "open"]

    def get_closed_trades(self) -> List[Dict[str, Any]]:
        with self.state.state_lock:
            return [t for t in self.state.trades if t["status"] == "closed"]


# =============================================================================
# PATTERN DETECTOR
# =============================================================================

class PatternDetector:
    """Detects buy/sell patterns based on price history."""

    def __init__(self, config: Dict[str, Any], state: BotState, logger: logging.Logger, trade_executor: TradeExecutor):
        self.config = config
        self.state = state
        self.logger = logger
        self.trade_executor = trade_executor

    def check_patterns(self) -> None:
        """Check all tokens for buy/sell patterns."""
        with self.state.state_lock:
            buy_patterns = self._parse_patterns(self.config.get("buy_patterns", ""))
            sell_patterns = self._parse_patterns(self.config.get("sell_patterns", ""))

            for symbol, history in self.state.price_history.items():
                if len(history) < 2:
                    continue
                self._check_token_patterns(symbol, history, buy_patterns, sell_patterns)

    def _parse_patterns(self, pattern_str: str) -> List[Dict[str, Any]]:
        """Parse pattern strings into structured patterns."""
        patterns = []
        if not pattern_str:
            return patterns

        for pattern in pattern_str.split(","):
            pattern = pattern.strip()
            if not pattern:
                continue

            if pattern.startswith("<_"):
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
        self, symbol: str, history: List[Dict[str, Any]],
        buy_patterns: List[Dict[str, Any]], sell_patterns: List[Dict[str, Any]]
    ) -> None:
        """Check price history for a token against patterns."""
        if len(history) < 2:
            return

        latest = history[-1]
        previous = history[-2]

        if previous["price"] == 0:
            return
        price_change_pct = ((latest["price"] - previous["price"]) / previous["price"]) * 100

        for pattern in buy_patterns:
            if price_change_pct < pattern["threshold"]:
                self.logger.info(f"Buy pattern matched for {symbol}: {pattern['raw']} (Change: {price_change_pct:.2f}%)")
                address = self.state.symbol_to_address.get(symbol)
                if address:
                    self.trade_executor.execute_trade(
                        symbol, address, "buy", self.config.get("trade_step", 3.0), pattern["raw"]
                    )

        for pattern in sell_patterns:
            if price_change_pct > pattern["threshold"]:
                self.logger.info(f"Sell pattern matched for {symbol}: {pattern['raw']} (Change: {price_change_pct:.2f}%)")
                address = self.state.symbol_to_address.get(symbol)
                if address:
                    self.trade_executor.execute_trade(
                        symbol, address, "sell", self.config.get("trade_step", 3.0), pattern["raw"]
                    )


# =============================================================================
# MAIN TRADING BOT CLASS
# =============================================================================

class TradingBot:
    """Main trading bot class with portfolio management."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.logger = setup_logging(config.get("debug_mode", "none"))

        # Load state
        self.state = load_state()
        self.state.trades = load_trades()

        if not self.state.network:
            self.state.network = config.get("network", "arbitrum")
        if not self.state.current_chain_key:
            self.state.current_chain_key = config.get("primary_price_source", "arbitrum")
        self.state.is_test_mode = config.get("is_test_mode", True)

        # Initialize portfolio manager
        self.portfolio_manager = PortfolioManager(self.state, self.logger)

        # Initialize trade executor
        self.trade_executor = TradeExecutor(config, self.state, self.logger, self.portfolio_manager)

        # Initialize pattern detector
        self.pattern_detector = PatternDetector(config, self.state, self.logger, self.trade_executor)

        # Initialize price monitor
        monitor_config = {
            **config,
            "primary_price_source": config.get("primary_price_source", "arbitrum"),
            "network": config.get("network", "arbitrum"),
        }
        self.monitor = UniswapV3LiveMonitor(monitor_config)

        # Start monitor in a separate thread
        self.monitor_thread: Optional[threading.Thread] = None
        self._start_monitor_thread()

        self.logger.info("Trading bot initialized")
        self.logger.info(f"Mode: {'TEST' if self.state.is_test_mode else 'PROD'}")
        self.logger.info(f"Network: {self.state.network}")

    def _start_monitor_thread(self) -> None:
        """Start the price monitor in a background thread."""
        self.monitor_thread = threading.Thread(target=self._run_monitor, daemon=True)
        self.monitor_thread.start()
        # Give it a moment to initialize
        time.sleep(1)

    def _run_monitor(self) -> None:
        """Run the price monitor in a separate thread."""
        asyncio.run(self.monitor.start())

    def _stop_monitor(self) -> None:
        """Stop the price monitor thread."""
        if self.monitor:
            # Signal the monitor to stop
            self.monitor.state.is_running = False
            # Wait for the thread to finish
            if self.monitor_thread and self.monitor_thread.is_alive():
                self.monitor_thread.join(timeout=5)

    def start(self) -> None:
        """Start the trading bot's main loop."""
        self.state.is_running = True
        self.state.start_time = datetime.utcnow().isoformat()
        self.logger.info("Starting trading bot...")

        try:
            while self.state.is_running:
                # Sync state from monitor to bot state
                self._sync_monitor_state()

                # Update portfolio value
                self.portfolio_manager.update_value()

                # Check patterns and execute trades
                self.pattern_detector.check_patterns()

                # Save state periodically
                save_state(self.state)
                save_trades(self.state.trades)

                time.sleep(5)  # Check every 5 seconds

        except KeyboardInterrupt:
            self.logger.info("Shutting down...")
            self.stop()

    def stop(self) -> None:
        """Stop the trading bot."""
        self.state.is_running = False
        self._stop_monitor()
        self.trade_executor.close_all_open_trades()
        save_state(self.state)
        save_trades(self.state.trades)
        self.logger.info("Bot stopped. State saved.")

    def _sync_monitor_state(self) -> None:
        """Synchronize state from the price monitor."""
        with self.state.state_lock:
            # Safely copy prices and metadata from monitor
            if self.monitor and self.monitor.state:
                self.state.prices = dict(self.monitor.state.prices)
                self.state.price_history = {k: v.copy() for k, v in self.monitor.state.price_history.items()}
                self.state.address_to_symbol = dict(self.monitor.state.address_to_symbol)
                self.state.symbol_to_address = dict(self.monitor.state.symbol_to_address)
                self.state.block_count = self.monitor.state.block_count
                self.state.last_price_update = self.monitor.state.last_price_update

    def simulate_trade(self, symbol: str, trade_type: str, amount_usd: float) -> Optional[Dict[str, Any]]:
        """Simulate a trade (for CLI)."""
        address = self.state.symbol_to_address.get(symbol)
        if not address:
            self.logger.warning(f"Symbol {symbol} not found.")
            return None
        return self.trade_executor.execute_trade(symbol, address, trade_type, amount_usd, "Manual")

    def get_discovered_tokens(self) -> List[str]:
        """Get list of discovered tokens."""
        with self.state.state_lock:
            if self.monitor:
                return self.monitor.get_discovered_tokens()
            return list(self.state.prices.keys())

    def get_open_trades(self) -> List[Dict[str, Any]]:
        return self.trade_executor.get_open_trades()

    def get_closed_trades(self) -> List[Dict[str, Any]]:
        return self.trade_executor.get_closed_trades()

    def get_portfolio_value(self) -> float:
        """Get current portfolio value."""
        return self.portfolio_manager.get_value()

    def get_portfolio_holdings(self) -> Dict[str, float]:
        """Get current token holdings."""
        return self.portfolio_manager.get_holdings()


# =============================================================================
# OPTIONAL FEATURES
# =============================================================================

class OptionalFeatures:
    """Optional features that can be removed without affecting core functionality."""

    def __init__(self, config: Dict[str, Any], state: BotState, logger: logging.Logger, trade_executor: TradeExecutor):
        self.config = config
        self.state = state
        self.logger = logger
        self.trade_executor = trade_executor
        self.backup_dir = Path("backups")
        self.backup_dir.mkdir(exist_ok=True)

    def create_backup(self) -> None:
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
        with open(backup_file, "r") as f:
            backup_data = json.load(f)
        self.config.update(backup_data["config"])
        # Reconstruct state
        portfolio_dict = backup_data["state"].get("portfolio", {})
        portfolio = Portfolio(
            holdings=portfolio_dict.get("holdings", {}),
            cash=portfolio_dict.get("cash", 10000.0),
            total_value=portfolio_dict.get("total_value", 0.0)
        )
        self.state = BotState(
            is_running=backup_data["state"].get("is_running", False),
            network=backup_data["state"].get("network", "arbitrum"),
            current_chain_key=backup_data["state"].get("current_chain_key", "arbitrum"),
            prices=backup_data["state"].get("prices", {}),
            price_history=backup_data["state"].get("price_history", {}),
            address_to_symbol=backup_data["state"].get("address_to_symbol", {}),
            symbol_to_address=backup_data["state"].get("symbol_to_address", {}),
            trades=backup_data["trades"],
            portfolio=portfolio,
            start_time=backup_data["state"].get("start_time"),
            last_price_update=backup_data["state"].get("last_price_update"),
            last_trade_time=backup_data["state"].get("last_trade_time"),
        )
        self.logger.info(f"Restored from backup: {backup_file}")

    def auto_backup(self) -> None:
        if self.config.get("auto_backup", False):
            self.create_backup()

    def list_backups(self) -> List[str]:
        return [str(f) for f in self.backup_dir.glob("*.json")]

    def get_pnl(self) -> Dict[str, float]:
        """Calculate PnL statistics."""
        with self.state.state_lock:
            closed_trades = [t for t in self.state.trades if t["status"] == "closed"]
            total_pnl = sum(t["pnl"] for t in closed_trades)

            now = datetime.utcnow()
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            week_start = now - timedelta(days=7)
            month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

            daily_pnl = sum(t["pnl"] for t in closed_trades
                           if t.get("closed_at") and datetime.fromisoformat(t["closed_at"]) >= today_start)
            weekly_pnl = sum(t["pnl"] for t in closed_trades
                            if t.get("closed_at") and datetime.fromisoformat(t["closed_at"]) >= week_start)
            monthly_pnl = sum(t["pnl"] for t in closed_trades
                             if t.get("closed_at") and datetime.fromisoformat(t["closed_at"]) >= month_start)

            return {"total": total_pnl, "daily": daily_pnl, "weekly": weekly_pnl, "monthly": monthly_pnl}

    def get_portfolio_value(self) -> float:
        """Get current portfolio value (from PortfolioManager)."""
        return self.trade_executor.portfolio_manager.get_value()

    def update_statistics(self) -> None:
        """Log current statistics."""
        with self.state.state_lock:
            closed_trades = [t for t in self.state.trades if t["status"] == "closed"]
            open_trades = [t for t in self.state.trades if t["status"] == "open"]
            total_pnl = sum(t["pnl"] for t in closed_trades)
            winning = [t for t in closed_trades if t["pnl"] > 0]
            losing = [t for t in closed_trades if t["pnl"] < 0]
            win_rate = (len(winning) / len(closed_trades) * 100) if closed_trades else 0.0
            self.logger.info(f"Stats: Trades={len(closed_trades)}, Open={len(open_trades)}, Win={win_rate:.1f}%, PnL=${total_pnl:.2f}")


# =============================================================================
# CLI INTERFACE
# =============================================================================

def parse_args():
    parser = argparse.ArgumentParser(description="Uniswap Trading Bot with Portfolio Management")
    parser.add_argument("--config", type=str, default="config.json", help="Path to config file")
    parser.add_argument("--test", action="store_true", help="Force test mode")
    parser.add_argument("--simulate", nargs=3, metavar=("SYMBOL", "TYPE", "AMOUNT"),
                       help="Simulate a trade and exit")
    parser.add_argument("--status", action="store_true", help="Show status and exit")
    parser.add_argument("--trades", action="store_true", help="Show trade history and exit")
    parser.add_argument("--tokens", action="store_true", help="Show discovered tokens and exit")
    parser.add_argument("--portfolio", action="store_true", help="Show portfolio and exit")
    # Optional features CLI args
    parser.add_argument("--backup", action="store_true", help="Create backup and exit")
    parser.add_argument("--restore", type=str, metavar="FILE", help="Restore from backup and exit")
    parser.add_argument("--list-backups", action="store_true", help="List backups and exit")
    return parser.parse_args()


def main():
    args = parse_args()
    config = load_config(args.config)

    if args.test:
        config["is_test_mode"] = True

    # Initialize core bot
    bot = TradingBot(config)

    # Initialize optional features
    optional = OptionalFeatures(config, bot.state, bot.logger, bot.trade_executor)

    # Handle CLI commands
    if args.simulate:
        symbol, trade_type, amount_usd = args.simulate
        if trade_type not in ["buy", "sell"]:
            print("Error: TYPE must be 'buy' or 'sell'")
            sys.exit(1)
        trade = bot.simulate_trade(symbol, trade_type, float(amount_usd))
        if trade:
            print(f"Simulated: {trade_type} {trade['token_amount']:.6f} {symbol} at ${trade['price']:.2f}")
        sys.exit(0)

    if args.status:
        pnl = optional.get_pnl()
        portfolio_value = optional.get_portfolio_value()
        open_trades = bot.get_open_trades()
        tokens = bot.get_discovered_tokens()
        print("=" * 60)
        print("STATUS")
        print("=" * 60)
        print(f"Mode: {'TEST' if config.get('is_test_mode', True) else 'PROD'}")
        print(f"Network: {bot.state.network}")
        print(f"Running: {bot.state.is_running}")
        print(f"Tokens: {len(tokens)}")
        print(f"Open Trades: {len(open_trades)}")
        print(f"Portfolio Value: ${portfolio_value:.2f}")
        print(f"PnL: Total=${pnl['total']:.2f}, Daily=${pnl['daily']:.2f}")
        print("=" * 60)
        sys.exit(0)

    if args.trades:
        print("=" * 80)
        print("TRADE HISTORY")
        print("=" * 80)
        print(f"{'Type':<6} {'Token':<8} {'Price':>10} {'Amount':>10} {'Value':>10} {'PnL':>10} {'Status':>10}")
        print("-" * 80)
        for trade in bot.get_open_trades():
            pnl_str = f"${trade['pnl']:+.2f}" if trade.get('pnl') else "—"
            print(f"{trade['type']:<6} {trade['token']:<8} ${trade['price']:>9.2f} {trade['token_amount']:>10.6f} ${trade['amount_usd']:>9.2f} {pnl_str:>10} {'OPEN':>10}")
        for trade in bot.get_closed_trades():
            pnl_str = f"${trade['pnl']:+.2f}" if trade.get('pnl') else "—"
            print(f"{trade['type']:<6} {trade['token']:<8} ${trade['price']:>9.2f} {trade['token_amount']:>10.6f} ${trade['amount_usd']:>9.2f} {pnl_str:>10} {'CLOSED':>10}")
        print("=" * 80)
        sys.exit(0)

    if args.tokens:
        print("=" * 80)
        print("DISCOVERED TOKENS")
        print("=" * 80)
        print(f"{'Symbol':<10} {'Price':>12} {'Address':>42}")
        print("-" * 80)
        for symbol in bot.get_discovered_tokens():
            address = bot.state.symbol_to_address.get(symbol, "N/A")
            price = bot.state.prices.get(symbol, 0)
            print(f"{symbol:<10} ${price:>11.4f} {address:>42}")
        print("=" * 80)
        sys.exit(0)

    if args.portfolio:
        holdings = bot.get_portfolio_holdings()
        portfolio_value = bot.get_portfolio_value()
        print("=" * 80)
        print("PORTFOLIO")
        print("=" * 80)
        print(f"{'Token':<10} {'Amount':>12} {'Value':>12}")
        print("-" * 80)
        for symbol, amount in holdings.items():
            price = bot.state.prices.get(symbol, 0)
            value = amount * price
            print(f"{symbol:<10} {amount:>12.6f} ${value:>11.2f}")
        print("-" * 80)
        print(f"{'Cash':<10} {'':>12} ${bot.state.portfolio.cash:>11.2f}")
        print(f"{'TOTAL':<10} {'':>12} ${portfolio_value:>11.2f}")
        print("=" * 80)
        sys.exit(0)

    # Optional features CLI
    if args.backup:
        optional.create_backup()
        print("Backup created.")
        sys.exit(0)
    if args.restore:
        optional.restore_backup(args.restore)
        print(f"Restored from {args.restore}")
        sys.exit(0)
    if args.list_backups:
        for b in optional.list_backups():
            print(b)
        sys.exit(0)

    # Start the bot
    print("=" * 60)
    print("UNISWAP TRADING BOT WITH PORTFOLIO MANAGEMENT")
    print("=" * 60)
    print(f"Mode: {'TEST' if config.get('is_test_mode', True) else 'PROD'}")
    print(f"Network: {config.get('network', 'arbitrum')}")
    print(f"Press Ctrl+C to stop")
    print("=" * 60)

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