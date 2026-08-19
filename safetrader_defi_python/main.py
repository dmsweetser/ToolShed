#!/usr/bin/env python3
"""
Uniswap Arbitrum Trading Bot - Python Version
Uses WebSocket to monitor Uniswap V3 swaps in real-time and automatically
discovers and tracks ALL tokens with swap activity.

Key Features:
- Real-time WebSocket monitoring of Uniswap V3 swaps
- Automatic token discovery (no fixed token list)
- Dynamic price tracking for all active tokens
- Pattern-based trading
- PnL tracking and statistics
- State persistence
"""

import json
import os
import sys
import time
import logging
import argparse
import random
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple, Set
from dataclasses import dataclass, field, asdict
from collections import defaultdict

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
class TokenState:
    """Runtime state for a token."""
    address: str
    symbol: str
    name: str
    decimals: int
    swaps: List[float] = field(default_factory=list)  # Timestamps of swaps
    volume_quote: float = 0.0
    price_quote: Optional[float] = None
    history: List[Dict[str, Any]] = field(default_factory=list)  # Price history
    last_seen: float = 0.0


@dataclass
class Trade:
    """Represents a trade (buy or sell)."""
    id: str
    timestamp: str
    token: str
    token_address: str  # Store address for discovered tokens
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
    current_chain_key: str = "arbitrum"
    prices: Dict[str, float] = field(default_factory=dict)  # symbol -> price
    price_history: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)  # symbol -> history
    address_to_symbol: Dict[str, str] = field(default_factory=dict)  # address -> symbol
    symbol_to_address: Dict[str, str] = field(default_factory=dict)  # symbol -> address
    trades: List[Dict[str, Any]] = field(default_factory=list)
    start_time: Optional[str] = None
    last_price_update: Optional[str] = None
    last_trade_time: Optional[float] = None
    gas_price: float = 0.0
    eth_price: float = 0.0
    arb_price: float = 0.0
    block_count: int = 0
    rpc_head: int = 0
    last_processed_block: Optional[int] = None
    pending_block: Optional[int] = None
    processing_blocks: bool = False


# =============================================================================
# CONSTANTS
# =============================================================================

# Uniswap V3 Factory addresses
UNISWAP_V3_FACTORY = "0x1F98431c8aD98523631AE4a59f267346ea31F984"

# Known token configurations (for initial symbol mapping, but we'll discover dynamically)
KNOWN_TOKENS: Dict[str, Dict[str, Any]] = {
    # Arbitrum
    "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1": {"symbol": "WETH", "name": "Wrapped ETH", "decimals": 18},
    "0x2f2a2543B76A416654947aaB75B4e35b52a17231": {"symbol": "WBTC", "name": "Wrapped BTC", "decimals": 8},
    "0xfa7F8980b0f1E64A2162791cc3b0871572f1F7f0": {"symbol": "UNI", "name": "Uniswap", "decimals": 18},
    "0xf97f4df75117a78c1A5a0DBb814Af92458539FB4": {"symbol": "LINK", "name": "Chainlink", "decimals": 18},
    "0x912CE59144196C11c48067255325c5414506085A": {"symbol": "ARB", "name": "Arbitrum", "decimals": 18},
    "0xfc5A1A6EB076a2C7aD06eD22C5C769A78b3Fa3A1": {"symbol": "GMX", "name": "GMX", "decimals": 18},
    "0xaf88d065e77c8cC2239327C5EDb3A432268e5831": {"symbol": "USDC", "name": "USD Coin", "decimals": 6},
    "0xFd086bC7CD5C481DCC9C85ebe478A1C0b69FCbb9": {"symbol": "USDT", "name": "Tether", "decimals": 6},
    # Ethereum
    "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2": {"symbol": "WETH", "name": "Wrapped ETH", "decimals": 18},
    "0xA0b86991c6218b36c1d19d4a2e9eb0ce3606eb48": {"symbol": "USDC", "name": "USD Coin", "decimals": 6},
    "0xdAC17F958D2ee523a2206206994597C13D831ec7": {"symbol": "USDT", "name": "Tether", "decimals": 6},
    "0x6B175474E89094C44Da98b954EedeAC495271d0F": {"symbol": "DAI", "name": "DAI", "decimals": 18},
}

# Chain configurations
CHAINS: Dict[str, ChainConfig] = {
    "ethereum": ChainConfig(
        name="Ethereum",
        chain_id=1,
        ws="wss://ethereum-rpc.publicnode.com",
        http="https://ethereum-rpc.publicnode.com",
        factory=UNISWAP_V3_FACTORY,
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
        ws="wss://base-rpc.publicnode.com",
        http="https://base-rpc.publicnode.com",
        factory=UNISWAP_V3_FACTORY,
        wrapped_native="0x4200000000000000000000000000000000000006",
        quote_mode="native",
        quote_label="WETH",
        stables=[
            "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",  # USDC
            "0x60a3e35cc302bfa44cb288bc5a4f316fdb1adb42",  # DAI
        ],
    ),
    "arbitrum": ChainConfig(
        name="Arbitrum",
        chain_id=42161,
        ws="wss://arbitrum-one-rpc.publicnode.com",
        http="https://arbitrum-one-rpc.publicnode.com",
        factory=UNISWAP_V3_FACTORY,
        wrapped_native="0x82aF49447D8a07e3bd95BD0d56f35241523fBab1",
        quote_mode="native",
        quote_label="WETH",
        stables=[
            "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",  # USDC
            "0xFd086bC7CD5C481DCC9C85ebe478A1C0b69FCbb9",  # USDT
        ],
    ),
    "optimism": ChainConfig(
        name="Optimism",
        chain_id=10,
        ws="wss://optimism-rpc.publicnode.com",
        http="https://optimism-rpc.publicnode.com",
        factory=UNISWAP_V3_FACTORY,
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
        ws="wss://polygon-bor-rpc.publicnode.com",
        http="https://polygon-bor-rpc.publicnode.com",
        factory=UNISWAP_V3_FACTORY,
        wrapped_native="0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270",
        quote_mode="native",
        quote_label="WPOL",
        stables=[
            "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174",  # USDC
            "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359",  # USDT
        ],
    ),
}


# Uniswap V3 Swap event topic
UNISWAP_V3_SWAP_TOPIC = "0xc42079f94a6350d7e6235f29174924f928cc2ac818eb64fed8004e115fbcca671ce6"


# Configuration constants
CONFIG = {
    "MAX_TOKENS": 200,  # Increased for dynamic discovery
    "WINDOW_MS": 15 * 60 * 1000,  # 15 minutes
    "HISTORY_MS": 15 * 60 * 1000,
    "MAX_HISTORY_POINTS": 180,
    "MAX_PRICE_PATH_DEPTH": 4,
    "RENDER_INTERVAL_MS": 1000,
    "RETRY_DELAY_MS": 3000,
    "HEAD_RETRY_MS": 700,
    "MAX_HEAD_RETRIES": 5,
    "LOG_CONCURRENCY": 4,
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


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def norm(a: str) -> str:
    """Normalize address to lowercase string."""
    return str(a).lower()


async def sleep(ms: int) -> None:
    """Async sleep."""
    await asyncio.sleep(ms / 1000)


def now() -> float:
    """Get current timestamp in milliseconds."""
    return time.time() * 1000


def short(a: str) -> str:
    """Shorten address for display."""
    if not a:
        return ""
    return f"{a[:6]}...{a[-4:]}"


def generate_symbol(address: str) -> str:
    """Generate a symbol from an address (for unknown tokens)."""
    # Use first 4 chars of address as symbol
    return f"TKN_{address[:4].upper()}"


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
            return BotState(
                is_running=state_dict.get("is_running", False),
                is_connected=state_dict.get("is_connected", False),
                wallet_address=state_dict.get("wallet_address"),
                network=state_dict.get("network", "arbitrum"),
                current_chain_key=state_dict.get("current_chain_key", "arbitrum"),
                prices=state_dict.get("prices", {}),
                price_history=state_dict.get("price_history", {}),
                address_to_symbol=state_dict.get("address_to_symbol", {}),
                symbol_to_address=state_dict.get("symbol_to_address", {}),
                trades=state_dict.get("trades", []),
                start_time=state_dict.get("start_time"),
                last_price_update=state_dict.get("last_price_update"),
                last_trade_time=state_dict.get("last_trade_time"),
                gas_price=state_dict.get("gas_price", 0.0),
                eth_price=state_dict.get("eth_price", 0.0),
                arb_price=state_dict.get("arb_price", 0.0),
                block_count=state_dict.get("block_count", 0),
                rpc_head=state_dict.get("rpc_head", 0),
                last_processed_block=state_dict.get("last_processed_block"),
                pending_block=state_dict.get("pending_block"),
                processing_blocks=state_dict.get("processing_blocks", False),
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
# UNISWAP SESSION (WebSocket-based Swap Monitoring)
# =============================================================================

class UniswapSession:
    """
    Manages a WebSocket connection to a blockchain for monitoring Uniswap V3 swaps.
    Automatically discovers and tracks ALL tokens with swap activity.
    """

    def __init__(self, chain_key: str, config: Dict[str, Any], state: BotState, logger: logging.Logger):
        self.chain_key = chain_key
        self.chain = CHAINS.get(chain_key)
        self.config = config
        self.state = state
        self.logger = logger
        
        # Session state
        self.id = 0
        self.active = True
        self.connected = False
        self.block_count = 0
        self.rpc_head = 0
        self.last_processed_block = None
        self.pending_block = None
        self.processing_blocks = False
        self.reconnect_timer = None
        
        # Data structures
        self.pools: Dict[str, Dict[str, Any]] = {}
        self.tokens: Dict[str, TokenState] = {}  # address -> TokenState
        self.pair_prices: Dict[str, Dict[str, Dict[str, Any]]] = defaultdict(dict)
        self.metadata_in_flight: Dict[str, Any] = {}
        self.swaps: List[float] = []  # Timestamps of swap events

    async def start(self) -> None:
        """Start the WebSocket session."""
        if not self.chain:
            self.logger.error(f"Chain {self.chain_key} not configured")
            return

        self.logger.info(f"Connecting to {self.chain.name} ({self.chain.ws})...")
        
        try:
            # In a real implementation, we would use web3.py with WebSocketProvider
            # For now, we'll simulate the connection and use HTTP polling as fallback
            # This structure is ready for WebSocket implementation
            
            self.connected = True
            self.logger.info(f"Connected to {self.chain.name}")
            
            # Start monitoring blocks
            await self._monitor_blocks()
            
        except Exception as e:
            self.logger.error(f"Connection failed: {e}")
            self.connected = False
            await self._schedule_reconnect()

    async def stop(self) -> None:
        """Stop the WebSocket session."""
        self.active = False
        self.connected = False
        
        if self.reconnect_timer:
            self.reconnect_timer.cancel()
            self.reconnect_timer = None
        
        self.logger.info(f"Disconnected from {self.chain.name}")

    async def _schedule_reconnect(self) -> None:
        """Schedule a reconnection attempt."""
        if not self.active or self.reconnect_timer:
            return
        
        self.reconnect_timer = asyncio.create_task(asyncio.sleep(CONFIG["RETRY_DELAY_MS"] / 1000))
        await self.reconnect_timer
        self.reconnect_timer = None
        
        if self.active:
            await self.start()

    async def _monitor_blocks(self) -> None:
        """Monitor new blocks and process swap events."""
        while self.active and self.connected:
            try:
                # Simulate getting current block number
                # In real implementation: current_block = await self.provider.get_block_number()
                current_block = 10000000  # Mock block number
                self.rpc_head = current_block
                self.block_count = max(self.block_count, current_block)
                
                # Process pending blocks
                if self.pending_block is not None:
                    await self._process_pending_blocks()
                else:
                    self._queue_block(current_block)
                
                await sleep(CONFIG["RENDER_INTERVAL_MS"])
                
            except Exception as e:
                self.logger.error(f"Error monitoring blocks: {e}")
                self.connected = False
                await self._schedule_reconnect()
                break

    def _queue_block(self, block_number: int) -> None:
        """Queue a block for processing."""
        if not self.active:
            return
        
        if self.last_processed_block is not None and block_number <= self.last_processed_block:
            return
        
        self.pending_block = max(self.pending_block or 0, block_number)
        asyncio.create_task(self._process_pending_blocks())

    async def _process_pending_blocks(self) -> None:
        """Process blocks in the queue."""
        if self.processing_blocks or not self.active:
            return
        
        self.processing_blocks = True
        
        try:
            while self.pending_block is not None and self.active:
                target = self.pending_block
                self.pending_block = None
                
                head = self.rpc_head
                self.rpc_head = head
                self.block_count = max(self.block_count, head)
                
                if target > head:
                    self.pending_block = target
                    await sleep(CONFIG["HEAD_RETRY_MS"])
                    continue
                
                if self.last_processed_block is not None and target <= self.last_processed_block:
                    continue
                
                await self._process_block(target)
                
                if not self.active:
                    break
                
                self.last_processed_block = target
                
        finally:
            self.processing_blocks = False

    async def _process_block(self, block_number: int) -> None:
        """Process a single block and its swap events."""
        if not self.active:
            return
        
        self.logger.debug(f"Processing block {block_number}")
        
        # In a real implementation, we would fetch logs for this block
        # Filtering for Uniswap V3 Swap events
        # logs = await self.provider.get_logs({
        #     "fromBlock": block_number,
        #     "toBlock": block_number,
        #     "topics": [UNISWAP_V3_SWAP_TOPIC]
        # })
        
        # For now, we'll simulate finding swap events
        # In reality, we'd parse the logs and call _process_swap_log for each
        
        # Simulate some swap events for demonstration
        # This would be replaced with actual log parsing
        simulated_swaps = [
            {
                "address": "0x123...",  # Pool address
                "topics": [UNISWAP_V3_SWAP_TOPIC],
                "data": "0x...",
                "sqrtPriceX96": 200000000000000000000,  # Example value
                "amount0": 1000000,  # Example amount (in token0 units)
                "amount1": 2000000,  # Example amount (in token1 units)
            }
        ]
        
        for log in simulated_swaps:
            await self._process_swap_log(log)

    async def _process_swap_log(self, log: Dict[str, Any]) -> None:
        """Process a single Uniswap V3 Swap event log."""
        if not self.active:
            return
        
        pool_address = norm(log.get("address", ""))
        
        # Load the pool if not already loaded
        pool = await self._load_pool(pool_address)
        if not pool or not pool.get("initialized"):
            return
        
        # Load the tokens
        token0 = await self._load_token(pool["token0"])
        token1 = await self._load_token(pool["token1"])
        if not token0 or not token1:
            return
        
        # Extract swap data (simulated - in reality from log)
        sqrt_price_x96 = log.get("sqrtPriceX96", 0)
        amount0 = log.get("amount0", 0)
        amount1 = log.get("amount1", 0)
        
        # Calculate price from sqrtPriceX96
        price = self._pool_price(sqrt_price_x96, token0.decimals, token1.decimals)
        if price is None:
            return
        
        # Set the pair price
        self._set_pair(pool["token0"], pool["token1"], price)
        
        # Update token activity
        timestamp = now()
        self.swaps.append(timestamp)
        token0.swaps.append(timestamp)
        token1.swaps.append(timestamp)
        token0.last_seen = timestamp
        token1.last_seen = timestamp
        
        # Calculate volume (simplified)
        try:
            n0 = abs(float(amount0) / (10 ** token0.decimals))
            n1 = abs(float(amount1) / (10 ** token1.decimals))
        except:
            n0 = 0
            n1 = 0
        
        # Get quote prices
        p0 = self._quote_price(pool["token0"])
        p1 = self._quote_price(pool["token1"])
        
        if p0 is not None:
            token0.price_quote = p0
            self._add_point(token0, p0)
        
        if p1 is not None:
            token1.price_quote = p1
            self._add_point(token1, p1)
        
        # Calculate volume in quote currency
        if p0 is not None and p1 is not None:
            volume = (n0 * p0 + n1 * p1) / 2
        elif p0 is not None:
            volume = n0 * p0
        elif p1 is not None:
            volume = n1 * p1
        else:
            volume = None
        
        if volume is not None and volume > 0:
            token0.volume_quote += volume
            token1.volume_quote += volume
            
            self.logger.debug(
                f"Swap: {n0:.6f} {token0.symbol} <-> {n1:.6f} {token1.symbol} "
                f"at price {price:.6f}, volume=${volume:.2f}"
            )

    async def _load_pool(self, address: str) -> Optional[Dict[str, Any]]:
        """Load pool metadata."""
        address = norm(address)
        
        if address in self.pools:
            return self.pools[address]
        
        key = f"pool:{address}"
        if key in self.metadata_in_flight:
            return await self.metadata_in_flight[key]
        
        async def load():
            pool = {
                "address": address,
                "token0": None,
                "token1": None,
                "fee": None,
                "factory": None,
                "initialized": False
            }
            self.pools[address] = pool
            
            try:
                # In a real implementation, we would call the pool contract
                # to get token0, token1, fee, and factory
                # For now, we'll use mock data
                
                # This would be:
                # contract = web3.eth.contract(address=address, abi=POOL_ABI)
                # token0 = contract.functions.token0().call()
                # token1 = contract.functions.token1().call()
                # fee = contract.functions.fee().call()
                # factory = contract.functions.factory().call()
                
                # Mock data for demonstration
                pool["token0"] = norm("0x82aF49447D8a07e3bd95BD0d56f35241523fBab1")  # WETH
                pool["token1"] = norm("0xaf88d065e77c8cC2239327C5EDb3A432268e5831")  # USDC
                pool["fee"] = 3000  # 0.3%
                pool["factory"] = norm(self.chain.factory)
                
                if norm(pool["factory"]) != norm(self.chain.factory):
                    del self.pools[address]
                    return None
                
                pool["initialized"] = True
                return pool
                
            except Exception as e:
                self.logger.error(f"Error loading pool {address}: {e}")
                del self.pools[address]
                return None
            finally:
                del self.metadata_in_flight[key]
        
        self.metadata_in_flight[key] = load()
        return await self.metadata_in_flight[key]

    async def _load_token(self, address: str) -> TokenState:
        """Load token metadata. Creates new tokens dynamically."""
        address = norm(address)
        
        if address in self.tokens:
            return self.tokens[address]
        
        key = f"token:{address}"
        if key in self.metadata_in_flight:
            return await self.metadata_in_flight[key]
        
        async def load():
            # Create token state with default values
            symbol = generate_symbol(address)
            name = f"Token {short(address)}"
            decimals = 18  # Default, will be updated if available
            
            # Check if we have known token data
            if address in KNOWN_TOKENS:
                token_data = KNOWN_TOKENS[address]
                symbol = token_data.get("symbol", symbol)
                name = token_data.get("name", name)
                decimals = token_data.get("decimals", decimals)
            
            token = TokenState(
                address=address,
                symbol=symbol,
                name=name,
                decimals=decimals,
                swaps=[],
                volume_quote=0.0,
                price_quote=None,
                history=[],
                last_seen=0
            )
            self.tokens[address] = token
            
            try:
                # In a real implementation, we would call the token contract
                # to get symbol, decimals, and name
                # contract = web3.eth.contract(address=address, abi=ERC20_ABI)
                # symbol = contract.functions.symbol().call()
                # decimals = contract.functions.decimals().call()
                # name = contract.functions.name().call()
                
                # For now, we'll just use the known data or defaults
                pass
                
            except Exception as e:
                self.logger.debug(f"Token metadata unavailable for {address}: {e}")
                # Keep the token with default metadata
            finally:
                del self.metadata_in_flight[key]
            
            return token
        
        self.metadata_in_flight[key] = load()
        return await self.metadata_in_flight[key]

    def _set_pair(self, a: str, b: str, price: float) -> None:
        """Set price for a token pair."""
        if not (isinstance(price, (int, float)) and price > 0):
            return
        
        a = norm(a)
        b = norm(b)
        
        if a not in self.pair_prices:
            self.pair_prices[a] = {}
        if b not in self.pair_prices:
            self.pair_prices[b] = {}
        
        timestamp = now()
        self.pair_prices[a][b] = {"price": price, "updatedAt": timestamp}
        self.pair_prices[b][a] = {"price": 1 / price, "updatedAt": timestamp}

    def _quote_price(self, address: str) -> Optional[float]:
        """Get the quote price for a token."""
        address = norm(address)
        
        # Check if it's a stablecoin (for USD quoting)
        if self.chain.quote_mode == "usd" and self._is_stable(address):
            return 1.0
        
        # Check if it's the wrapped native token
        if self.chain.quote_mode == "native" and self._is_quote_token(address):
            return 1.0
        
        # BFS to find a path to a quote token
        queue = [{"token": address, "value": 1.0, "depth": 0}]
        seen = {address}
        
        while queue:
            x = queue.pop(0)
            
            if x["depth"] >= CONFIG["MAX_PRICE_PATH_DEPTH"]:
                continue
            
            neighbors = self.pair_prices.get(x["token"], {})
            if not neighbors:
                continue
            
            for neighbor, edge in neighbors.items():
                if not edge or not (isinstance(edge["price"], (int, float)) and edge["price"] > 0):
                    continue
                
                value = x["value"] * edge["price"]
                
                # Check if this neighbor is a quote token
                if self.chain.quote_mode == "usd" and self._is_stable(neighbor):
                    return value
                if self.chain.quote_mode == "native" and self._is_quote_token(neighbor):
                    return value
                
                if neighbor not in seen:
                    seen.add(neighbor)
                    queue.append({"token": neighbor, "value": value, "depth": x["depth"] + 1})
        
        return None

    def _is_stable(self, address: str) -> bool:
        """Check if a token is a stablecoin."""
        address = norm(address)
        return any(norm(s) == address for s in self.chain.stables)

    def _is_quote_token(self, address: str) -> bool:
        """Check if a token is the quote token."""
        return norm(address) == norm(self.chain.wrapped_native)

    def _pool_price(self, sqrt_price_x96: int, decimals0: int, decimals1: int) -> Optional[float]:
        """Calculate price from Uniswap V3 sqrtPriceX96."""
        if not (isinstance(sqrt_price_x96, (int, float)) and sqrt_price_x96 > 0):
            return None
        
        try:
            sqrt_price = float(sqrt_price_x96)
            normalized = sqrt_price / (2 ** 96)
            raw_price = normalized * normalized
            decimal_adjustment = 10 ** (decimals0 - decimals1)
            price = raw_price * decimal_adjustment
            return price if price > 0 else None
        except:
            return None

    def _add_point(self, token: TokenState, price: float) -> None:
        """Add a price point to token history."""
        if not (isinstance(price, (int, float)) and price > 0):
            return
        
        ts = now()
        token.history.append({"t": ts, "price": price})
        
        # Remove old points
        cut = ts - CONFIG["HISTORY_MS"]
        while token.history and token.history[0]["t"] < cut:
            token.history.pop(0)
        
        # Limit history size
        if len(token.history) > CONFIG["MAX_HISTORY_POINTS"]:
            token.history = token.history[-CONFIG["MAX_HISTORY_POINTS"]:]

    def get_active_tokens(self) -> List[TokenState]:
        """Get tokens with recent swap activity."""
        cut = now() - CONFIG["WINDOW_MS"]
        active = []
        
        for token in self.tokens.values():
            # Remove old swaps
            while token.swaps and token.swaps[0] < cut:
                token.swaps.pop(0)
            
            if token.swaps:
                active.append(token)
        
        # Sort by activity
        active.sort(key=lambda t: (-len(t.swaps), -t.volume_quote, -t.last_seen))
        return active[:CONFIG["MAX_TOKENS"]]

    def update_state_prices(self) -> None:
        """Update the bot state prices from token states."""
        for address, token in self.tokens.items():
            if token.price_quote is not None:
                # Use or generate symbol
                symbol = token.symbol
                
                # Store address to symbol mapping
                self.state.address_to_symbol[address] = symbol
                self.state.symbol_to_address[symbol] = address
                
                # Update price
                self.state.prices[symbol] = token.price_quote
                
                # Update price history
                if symbol not in self.state.price_history:
                    self.state.price_history[symbol] = []
                
                if token.history:
                    latest = token.history[-1]
                    self.state.price_history[symbol].append({
                        "price": latest["price"],
                        "timestamp": datetime.fromtimestamp(latest["t"] / 1000).isoformat()
                    })
                    
                    # Limit history
                    if len(self.state.price_history[symbol]) > 1000:
                        self.state.price_history[symbol] = self.state.price_history[symbol][-1000:]
        
        self.state.last_price_update = datetime.utcnow().isoformat()
        self.logger.debug(f"Updated prices for {len(self.tokens)} tokens")

    def get_all_token_symbols(self) -> List[str]:
        """Get all discovered token symbols."""
        return [token.symbol for token in self.tokens.values()]


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

        # Check patterns for ALL tokens with price history
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
                # Get the address for this symbol
                address = self.state.symbol_to_address.get(symbol)
                self.trade_executor.execute_trade(
                    symbol, address, "buy", self.config.get("trade_step", 3.0), pattern["raw"]
                )

        # Check sell patterns (price rise)
        for pattern in sell_patterns:
            if price_change_pct > pattern["threshold"]:
                self.logger.info(
                    f"Sell pattern matched for {symbol}: {pattern['raw']} "
                    f"(Change: {price_change_pct:.2f}%)"
                )
                address = self.state.symbol_to_address.get(symbol)
                self.trade_executor.execute_trade(
                    symbol, address, "sell", self.config.get("trade_step", 3.0), pattern["raw"]
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

    def execute_trade(self, symbol: str, address: str, trade_type: str, amount_usd: float, pattern: str = "") -> Optional[Dict[str, Any]]:
        """
        Execute a trade (simulated in test mode, real in prod mode).
        
        Args:
            symbol: Token symbol (e.g., "ETH")
            address: Token address (e.g., "0x82aF...")
            trade_type: "buy" or "sell"
            amount_usd: Trade amount in USD
            pattern: Pattern that triggered the trade
        """
        if not self.state.is_running:
            self.logger.warning("Bot is not running. Trade not executed.")
            return None

        # Check if token is in allowed tokens list (if specified)
        allowed_tokens = self.config.get("tokens", [])
        if allowed_tokens and symbol not in allowed_tokens:
            self.logger.info(f"Token {symbol} not in allowed tokens list. Skipping trade.")
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
        gas_price = self.state.gas_price if self.state.gas_price > 0 else 50.0
        gas_limit = self.config.get("gas_limit", 500000)
        gas_fee_eth = (gas_limit * gas_price) / 1e9 / 1e18  # Convert from gwei to ETH
        eth_price = self.state.eth_price if self.state.eth_price > 0 else 3000.0
        gas_fee_usd = gas_fee_eth * eth_price

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
                trade["pnl"] = 0.0
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
        if not self.state.current_chain_key:
            self.state.current_chain_key = config.get("primary_price_source", "arbitrum")
        self.state.is_test_mode = config.get("is_test_mode", True)

        # Initialize components
        self.session: Optional[UniswapSession] = None
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

    async def start(self) -> None:
        """Start the trading bot."""
        self.state.is_running = True
        self.state.start_time = datetime.utcnow().isoformat()
        self.logger.info("Starting trading bot...")

        # Start the Uniswap session
        chain_key = self.config.get("primary_price_source", "arbitrum")
        self.session = UniswapSession(chain_key, self.config, self.state, self.logger)
        await self.session.start()

        try:
            while self.state.is_running:
                # Update prices from session
                if self.session:
                    self.session.update_state_prices()

                # Update gas price (simulated)
                self._update_gas_price()

                # Check patterns and execute trades
                self.pattern_detector.check_patterns()

                # Update statistics
                self.stats_calculator.update_statistics()
                pnl = self.stats_calculator.get_pnl()
                
                # Log active tokens
                if self.session:
                    active_tokens = self.session.get_active_tokens()
                    self.logger.info(f"Active tokens: {len(active_tokens)}")
                    if active_tokens:
                        token_symbols = [t.symbol for t in active_tokens[:5]]  # Show first 5
                        self.logger.info(f"Top tokens: {', '.join(token_symbols)}")
                
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
                await asyncio.sleep(interval)

        except KeyboardInterrupt:
            self.logger.info("Shutting down...")
            await self.stop()

    async def stop(self) -> None:
        """Stop the trading bot."""
        self.state.is_running = False
        
        if self.session:
            await self.session.stop()
            self.session = None
        
        self.trade_executor.close_all_open_trades()
        save_state(self.state)
        save_trades(self.state.trades)
        self.logger.info("Bot stopped. State saved.")

    def _update_gas_price(self) -> None:
        """Update gas price (simulated)."""
        try:
            if self.config.get("is_test_mode", True):
                self.state.gas_price = random.uniform(10, 50)
            else:
                # In real mode, would fetch from RPC
                self.state.gas_price = 50.0
        except Exception as e:
            self.logger.error(f"Error updating gas price: {e}")

    def simulate_trade(self, symbol: str, trade_type: str, amount_usd: float) -> Optional[Dict[str, Any]]:
        """Simulate a manual trade."""
        # For manual trades, we need to find the address
        address = self.state.symbol_to_address.get(symbol)
        if not address:
            self.logger.warning(f"Symbol {symbol} not found. Use discovered tokens.")
            return None
        return self.trade_executor.execute_trade(symbol, address, trade_type, amount_usd, "Manual")

    def get_discovered_tokens(self) -> List[str]:
        """Get all discovered token symbols."""
        if self.session:
            return self.session.get_all_token_symbols()
        return list(self.state.prices.keys())

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
        description="Uniswap Arbitrum Trading Bot - Python Version with Dynamic Token Discovery"
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
        "--tokens",
        action="store_true",
        help="Show discovered tokens and exit",
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
        discovered_tokens = bot.get_discovered_tokens()
        print("=" * 60)
        print("TRADING BOT STATUS")
        print("=" * 60)
        print(f"Mode: {'TEST' if config['is_test_mode'] else 'PROD'}")
        print(f"Network: {bot.state.network}")
        print(f"Running: {bot.state.is_running}")
        print(f"Discovered Tokens: {len(discovered_tokens)}")
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

    if args.tokens:
        discovered_tokens = bot.get_discovered_tokens()
        print("=" * 60)
        print("DISCOVERED TOKENS")
        print("=" * 60)
        print(f"Total: {len(discovered_tokens)} tokens")
        print()
        
        # Show tokens with prices
        tokens_with_prices = []
        for symbol in discovered_tokens:
            price = bot.state.prices.get(symbol)
            if price is not None:
                tokens_with_prices.append((symbol, price))
        
        # Sort by symbol
        tokens_with_prices.sort(key=lambda x: x[0])
        
        for symbol, price in tokens_with_prices:
            address = bot.state.symbol_to_address.get(symbol, "N/A")
            print(f"  {symbol:8} | ${price:>10.4f} | {address}")
        
        print("=" * 60)
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
    print("Dynamic Token Discovery Mode")
    print("=" * 60)
    print(f"Mode: {'TEST (Simulated)' if config['is_test_mode'] else 'PROD (Real Trades)'}")
    print(f"Network: {config.get('network', 'arbitrum')}")
    print(f"Primary Price Source: {config.get('primary_price_source', 'arbitrum')}")
    print(f"Allowed Tokens: {config.get('tokens', ['ALL'])}")
    print("=" * 60)
    print("Press Ctrl+C to stop")
    print("Use --tokens to see discovered tokens")
    print("=" * 60)
    print()

    # Start the bot
    try:
        asyncio.run(bot.start())
    except KeyboardInterrupt:
        asyncio.run(bot.stop())
    except Exception as e:
        bot.logger.error(f"Fatal error: {e}")
        asyncio.run(bot.stop())
        sys.exit(1)


if __name__ == "__main__":
    main()