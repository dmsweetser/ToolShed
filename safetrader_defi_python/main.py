#!/usr/bin/env python3
"""
Uniswap Arbitrum Trading Bot - Minimal Version
Drop-in replacement with core functionality only. Optional features are isolated
in the OptionalFeatures class and can be entirely removed.

Core Features:
- WebSocket monitoring of Uniswap V3 swaps
- Dynamic token discovery
- Price tracking from on-chain data
- Pattern detection and trade simulation
- Basic state persistence

Optional Features (in OptionalFeatures class):
- Backup management
- Advanced statistics
- Portfolio calculations
- Additional CLI commands
"""

import json
import os
import sys
import time
import logging
import argparse
import random
import asyncio
import websockets
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any
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
    swaps: List[float] = field(default_factory=list)
    volume_quote: float = 0.0
    price_quote: Optional[float] = None
    history: List[Dict[str, Any]] = field(default_factory=list)
    last_seen: float = 0.0


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
    start_time: Optional[str] = None
    last_price_update: Optional[str] = None
    last_trade_time: Optional[float] = None


# =============================================================================
# CONSTANTS
# =============================================================================

# Uniswap V3 Factory addresses
UNISWAP_V3_FACTORY = "0x1F98431c8aD98523631AE4a59f267346ea31F984"

# Uniswap V3 Swap event topic (WITHOUT 0x prefix - 64 char hex string)
UNISWAP_V3_SWAP_TOPIC = "c42079f94a6350d7e6235f29174924f928cc2ac818eb64fed8004e115fbcca671ce6"

# Known token configurations (for initial symbol hints)
KNOWN_TOKENS: Dict[str, Dict[str, Any]] = {
    # Arbitrum
    "0x82af49447d8a07e3bd95bd0d56f35241523fbab1": {"symbol": "WETH", "name": "Wrapped ETH", "decimals": 18},
    "0x2f2a2543b76a416654947aab75b4e35b52a17231": {"symbol": "WBTC", "name": "Wrapped BTC", "decimals": 8},
    "0xfa7f8980b0f1e64a2162791cc3b0871572f1f7f0": {"symbol": "UNI", "name": "Uniswap", "decimals": 18},
    "0xf97f4df75117a78c1a5a0dbb814af92458539fb4": {"symbol": "LINK", "name": "Chainlink", "decimals": 18},
    "0x912ce59144196c11c48067255325c5414506085a": {"symbol": "ARB", "name": "Arbitrum", "decimals": 18},
    "0xfc5a1a6eb076a2c7ad06ed22c5c769a78b3fa3a1": {"symbol": "GMX", "name": "GMX", "decimals": 18},
    "0xaf88d065e77c8cc2239327c5edb3a432268e5831": {"symbol": "USDC", "name": "USD Coin", "decimals": 6},
    "0xfd086bc7cd5c481dcc9c85ebe478a1c0b69fcbb9": {"symbol": "USDT", "name": "Tether", "decimals": 6},
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
            "0xA0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",
            "0xdAC17F958D2ee523a2206206994597C13D831ec7",
            "0x6B175474E89094C44Da98b954EedeAC495271d0F",
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
            "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
            "0x60a3e35cc302bfa44cb288bc5a4f316fdb1adb42",
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
            "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
            "0xFd086bC7CD5C481DCC9C85ebe478A1C0b69FCbb9",
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
            "0x0b2C639c533813f4aAa9D7837CAf62653d097Ff85",
            "0x7F5c764cBc14f9669B88837ca1490cCa17c31607",
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
            "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174",
            "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359",
        ],
    ),
}

# Configuration constants
CONFIG = {
    "MAX_TOKENS": 200,
    "WINDOW_MS": 15 * 60 * 1000,  # 15 minutes
    "HISTORY_MS": 15 * 60 * 1000,
    "MAX_HISTORY_POINTS": 180,
    "MAX_PRICE_PATH_DEPTH": 4,
    "RETRY_DELAY_MS": 3000,
    "WEB3_PROVIDER_TIMEOUT": 30,
}


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


# =============================================================================
# LOGGING SETUP
# =============================================================================

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


# =============================================================================
# CONFIGURATION & STATE MANAGEMENT
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


def load_state(state_path: str = "state.json") -> BotState:
    """Load bot state from JSON file."""
    if Path(state_path).exists():
        with open(state_path, "r") as f:
            state_dict = json.load(f)
            return BotState(
                is_running=state_dict.get("is_running", False),
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
# CORE: UNISWAP SESSION (WebSocket-based Swap Monitoring)
# =============================================================================

class UniswapSession:
    """
    Core class: Manages WebSocket connection to monitor Uniswap V3 swaps.
    """

    def __init__(self, chain_key: str, config: Dict[str, Any], state: BotState, logger: logging.Logger):
        self.chain_key = chain_key
        self.chain = CHAINS.get(chain_key)
        self.config = config
        self.state = state
        self.logger = logger
        
        # Session state
        self.active = True
        self.connected = False
        self.ws = None
        
        # Data structures
        self.pools: Dict[str, Dict[str, Any]] = {}
        self.tokens: Dict[str, TokenState] = {}
        self.pair_prices: Dict[str, Dict[str, Dict[str, Any]]] = defaultdict(dict)
        self.metadata_in_flight: Dict[str, Any] = {}
        self.swaps: List[float] = []
        
        # Request tracking
        self.pending_requests: Dict[int, Dict[str, Any]] = {}
        self.next_request_id = 1

    async def start(self) -> None:
        """Start the WebSocket session."""
        if not self.chain:
            self.logger.error(f"Chain {self.chain_key} not configured")
            return

        self.logger.info(f"Connecting to {self.chain.name} ({self.chain.ws})...")
        
        try:
            self.ws = await websockets.connect(
                self.chain.ws,
                ping_interval=20,
                ping_timeout=10,
                close_timeout=1
            )
            self.connected = True
            self.logger.info(f"Connected to {self.chain.name}")
            
            # Subscribe to new blocks
            await self._subscribe_to_blocks()
            
            # Start listening for messages
            await self._listen_for_messages()
            
        except websockets.exceptions.ConnectionClosed as e:
            self.logger.error(f"WebSocket connection closed: {e}")
            self.connected = False
            await self._schedule_reconnect()
        except Exception as e:
            self.logger.error(f"Connection failed: {e}")
            self.connected = False
            await self._schedule_reconnect()

    async def stop(self) -> None:
        """Stop the WebSocket session."""
        self.active = False
        self.connected = False
        
        if self.ws:
            try:
                await self.ws.close()
            except Exception:
                pass
            self.ws = None
        
        self.logger.info(f"Disconnected from {self.chain.name}")

    async def _schedule_reconnect(self) -> None:
        """Schedule a reconnection attempt."""
        if not self.active or self.next_request_id == 0:
            return
        
        self.logger.info(f"Scheduling reconnect in {CONFIG['RETRY_DELAY_MS'] / 1000} seconds...")
        await asyncio.sleep(CONFIG["RETRY_DELAY_MS"] / 1000)
        if self.active:
            await self.start()

    async def _subscribe_to_blocks(self) -> None:
        """Subscribe to new block headers."""
        request_id = self.next_request_id
        self.next_request_id += 1
        
        subscribe_msg = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "eth_subscribe",
            "params": ["newHeads"]
        }
        
        try:
            await self.ws.send(json.dumps(subscribe_msg))
            self.logger.info("Subscribed to new block headers")
        except Exception as e:
            self.logger.error(f"Error subscribing to blocks: {e}")

    async def _listen_for_messages(self) -> None:
        """Listen for WebSocket messages and process them."""
        try:
            async for message in self.ws:
                if not self.active:
                    break
                
                try:
                    data = json.loads(message)
                    
                    # Handle block notifications (from subscription)
                    if "params" in data and "result" in data["params"]:
                        block = data["params"]["result"]
                        block_number = int(block["number"], 16)
                        await self._process_block(block_number)
                    
                    # Handle RPC responses
                    elif "id" in data:
                        request_id = data["id"]
                        if request_id in self.pending_requests:
                            pending = self.pending_requests[request_id]
                            if "result" in data:
                                pending["future"].set_result(data["result"])
                            elif "error" in data:
                                pending["future"].set_exception(Exception(data["error"].get("message", "Unknown error")))
                            del self.pending_requests[request_id]
                        else:
                            self.logger.debug(f"Unexpected response ID: {request_id}")
                    
                except json.JSONDecodeError:
                    self.logger.debug(f"Received non-JSON message")
                except Exception as e:
                    self.logger.error(f"Error processing message: {e}")
        
        except websockets.exceptions.ConnectionClosed:
            self.logger.error("WebSocket connection closed")
            self.connected = False
            await self._schedule_reconnect()
        except Exception as e:
            self.logger.error(f"WebSocket error: {e}")
            self.connected = False
            await self._schedule_reconnect()

    async def _process_block(self, block_number: int) -> None:
        """Process a single block and its swap events."""
        if not self.active:
            return
        
        self.logger.debug(f"Processing block {block_number}")
        self.state.block_count = block_number
        self.state.rpc_head = block_number
        
        try:
            logs = await self._fetch_swap_logs(block_number)
            if logs:
                self.logger.info(f"Found {len(logs)} swap events in block {block_number}")
                for log in logs:
                    await self._process_swap_log(log)
        except Exception as e:
            self.logger.error(f"Error processing block {block_number}: {e}")

    async def _fetch_swap_logs(self, block_number: int) -> List[Dict[str, Any]]:
        """Fetch Uniswap V3 Swap logs for a block."""
        request_id = self.next_request_id
        self.next_request_id += 1
        
        # Create a future to await the response
        loop = asyncio.get_event_loop()
        future = loop.create_future()
        self.pending_requests[request_id] = {"future": future}
        
        # Send the request
        request = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "eth_getLogs",
            "params": [{
                "fromBlock": hex(block_number),
                "toBlock": hex(block_number),
                "topics": [UNISWAP_V3_SWAP_TOPIC]  # NO 0x prefix!
            }]
        }
        
        try:
            await self.ws.send(json.dumps(request))
            return await future
        except Exception as e:
            if request_id in self.pending_requests:
                del self.pending_requests[request_id]
            raise e

    async def _process_swap_log(self, log: Dict[str, Any]) -> None:
        """Process a single Uniswap V3 Swap event log."""
        if not self.active:
            return
        
        pool_address = norm(log.get("address", ""))
        
        # Load the pool
        pool = await self._load_pool(pool_address)
        if not pool or not pool.get("initialized"):
            return
        
        # Load the tokens
        token0 = await self._load_token(pool["token0"])
        token1 = await self._load_token(pool["token1"])
        if not token0 or not token1:
            return
        
        # Extract swap data from log
        try:
            # The log data contains the swap parameters as hex
            # We need to decode: amount0, amount1, sqrtPriceX96, liquidity, tick
            data_hex = log.get("data", "0x")
            if data_hex == "0x":
                return
            
            # Remove 0x prefix
            data_hex = data_hex[2:]
            
            # Each parameter is 32 bytes (64 hex chars)
            # amount0: int256 (32 bytes)
            # amount1: int256 (32 bytes)
            # sqrtPriceX96: uint160 (20 bytes, but padded to 32)
            # liquidity: uint128 (16 bytes, padded to 32)
            # tick: int24 (3 bytes, padded to 32)
            
            if len(data_hex) < 160:  # Need at least 160 chars for first 2 params
                return
            
            # Extract amount0 (first 64 chars)
            amount0_hex = data_hex[:64]
            amount0 = int(amount0_hex, 16)
            
            # Extract amount1 (next 64 chars)
            amount1_hex = data_hex[64:128]
            amount1 = int(amount1_hex, 16)
            
            # Extract sqrtPriceX96 (next 64 chars)
            sqrt_price_x96_hex = data_hex[128:192]
            sqrt_price_x96 = int(sqrt_price_x96_hex, 16)
            
            # Calculate price
            price = self._pool_price(sqrt_price_x96, token0.decimals, token1.decimals)
            if price is None:
                return
            
            # Set the pair price
            self._set_pair(pool["token0"], pool["token1"], price)
            
            # Update token activity
            timestamp = time.time() * 1000
            self.swaps.append(timestamp)
            token0.swaps.append(timestamp)
            token1.swaps.append(timestamp)
            token0.last_seen = timestamp
            token1.last_seen = timestamp
            
            # Calculate amounts in token units
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
        
        except Exception as e:
            self.logger.error(f"Error processing swap log: {e}")

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
                # For now, we'll use a placeholder implementation
                # In production, you'd use web3.py to call the pool contract
                # This is a simplified version that assumes we can't fetch pool data
                # but we can still process the swap from the log
                
                # We can't get token0/token1 without contract calls, so we'll skip
                # For now, just mark as initialized with dummy data
                pool["token0"] = norm(log.get("topics", [""])[1]) if log.get("topics") else None
                pool["token1"] = norm(log.get("topics", [""])[2]) if len(log.get("topics", [])) > 2 else None
                pool["fee"] = 3000
                pool["factory"] = norm(self.chain.factory)
                
                if pool["token0"] and pool["token1"]:
                    pool["initialized"] = True
                    return pool
                else:
                    del self.pools[address]
                    return None
                
            except Exception as e:
                self.logger.error(f"Error loading pool {address}: {e}")
                del self.pools[address]
                return None
            finally:
                if key in self.metadata_in_flight:
                    del self.metadata_in_flight[key]
        
        self.metadata_in_flight[key] = load()
        return await self.metadata_in_flight[key]

    async def _load_token(self, address: str) -> TokenState:
        """Load token metadata. Creates tokens dynamically for any address."""
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
            decimals = 18
            
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
            
            # Update address to symbol mapping
            self.state.address_to_symbol[address] = symbol
            self.state.symbol_to_address[symbol] = address
            
            self.logger.info(f"Discovered new token: {symbol} ({address})")
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
        
        timestamp = time.time() * 1000
        self.pair_prices[a][b] = {"price": price, "updatedAt": timestamp}
        self.pair_prices[b][a] = {"price": 1 / price, "updatedAt": timestamp}

    def _quote_price(self, address: str) -> Optional[float]:
        """Get the quote price for a token."""
        address = norm(address)
        
        if self.chain.quote_mode == "usd" and self._is_stable(address):
            return 1.0
        
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
        
        ts = time.time() * 1000
        token.history.append({"t": ts, "price": price})
        
        cut = ts - CONFIG["HISTORY_MS"]
        while token.history and token.history[0]["t"] < cut:
            token.history.pop(0)
        
        if len(token.history) > CONFIG["MAX_HISTORY_POINTS"]:
            token.history = token.history[-CONFIG["MAX_HISTORY_POINTS"]:]

    def update_state_prices(self) -> None:
        """Update the bot state prices from token states."""
        for address, token in self.tokens.items():
            if token.price_quote is not None:
                symbol = token.symbol
                self.state.address_to_symbol[address] = symbol
                self.state.symbol_to_address[symbol] = address
                self.state.prices[symbol] = token.price_quote
                
                if symbol not in self.state.price_history:
                    self.state.price_history[symbol] = []
                
                if token.history:
                    latest = token.history[-1]
                    self.state.price_history[symbol].append({
                        "price": latest["price"],
                        "timestamp": datetime.fromtimestamp(latest["t"] / 1000).isoformat()
                    })
                    
                    if len(self.state.price_history[symbol]) > 1000:
                        self.state.price_history[symbol] = self.state.price_history[symbol][-1000:]
        
        self.state.last_price_update = datetime.utcnow().isoformat()

    def get_active_tokens(self) -> List[TokenState]:
        """Get tokens with recent swap activity."""
        cut = time.time() * 1000 - CONFIG["WINDOW_MS"]
        active = []
        
        for token in self.tokens.values():
            while token.swaps and token.swaps[0] < cut:
                token.swaps.pop(0)
            
            if token.swaps:
                active.append(token)
        
        active.sort(key=lambda t: (-len(t.swaps), -t.volume_quote, -t.last_seen))
        return active[:CONFIG["MAX_TOKENS"]]

    def get_all_token_symbols(self) -> List[str]:
        """Get all discovered token symbols."""
        return [token.symbol for token in self.tokens.values()]


# =============================================================================
# CORE: PATTERN DETECTION
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
                self.trade_executor.execute_trade(
                    symbol, address, "buy", self.config.get("trade_step", 3.0), pattern["raw"]
                )

        for pattern in sell_patterns:
            if price_change_pct > pattern["threshold"]:
                self.logger.info(f"Sell pattern matched for {symbol}: {pattern['raw']} (Change: {price_change_pct:.2f}%)")
                address = self.state.symbol_to_address.get(symbol)
                self.trade_executor.execute_trade(
                    symbol, address, "sell", self.config.get("trade_step", 3.0), pattern["raw"]
                )


# =============================================================================
# CORE: TRADE EXECUTION
# =============================================================================

class TradeExecutor:
    """Handles trade execution (simulated only)."""

    def __init__(self, config: Dict[str, Any], state: BotState, logger: logging.Logger):
        self.config = config
        self.state = state
        self.logger = logger

    def execute_trade(self, symbol: str, address: str, trade_type: str, amount_usd: float, pattern: str = "") -> Optional[Dict[str, Any]]:
        """Execute a simulated trade."""
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
        eth_price = 3000.0  # Default ETH price
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
            "network": self.state.network,
        }

        if self.config.get("is_test_mode", True):
            self.logger.info(f"[TEST MODE] Simulated {trade_type} {token_amount:.6f} {symbol} at ${price:.2f} (Pattern: {pattern})")
        else:
            self.logger.warning("[PROD MODE] Real trade execution not implemented.")

        self.state.trades.append(trade)
        self.state.last_trade_time = time.time()

        # Auto-settle if it's a sell trade
        if trade_type == "sell":
            self._try_settle_trade(trade)

        return trade

    def _try_settle_trade(self, sell_trade: Dict[str, Any]) -> None:
        """Try to settle a sell trade with a matching buy trade."""
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
        for trade in self.state.trades:
            if trade["status"] == "open":
                trade["status"] = "closed"
                trade["closed_at"] = datetime.utcnow().isoformat()
                trade["closed_price"] = self.state.prices.get(trade["token"], trade["price"])
                trade["pnl"] = 0.0

    def get_open_trades(self) -> List[Dict[str, Any]]:
        return [t for t in self.state.trades if t["status"] == "open"]

    def get_closed_trades(self) -> List[Dict[str, Any]]:
        return [t for t in self.state.trades if t["status"] == "closed"]


# =============================================================================
# CORE: MAIN BOT CLASS
# =============================================================================

class TradingBot:
    """Main trading bot class - Core functionality only."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.logger = setup_logging(config.get("debug_mode", "none"))

        self.state = load_state()
        self.state.trades = load_trades()

        if not self.state.network:
            self.state.network = config.get("network", "arbitrum")
        if not self.state.current_chain_key:
            self.state.current_chain_key = config.get("primary_price_source", "arbitrum")
        self.state.is_test_mode = config.get("is_test_mode", True)

        self.session: Optional[UniswapSession] = None
        self.trade_executor = TradeExecutor(config, self.state, self.logger)
        self.pattern_detector = PatternDetector(config, self.state, self.logger, self.trade_executor)

        self.logger.info("Trading bot initialized")
        self.logger.info(f"Mode: {'TEST' if self.state.is_test_mode else 'PROD'}")
        self.logger.info(f"Network: {self.state.network}")

    async def start(self) -> None:
        """Start the trading bot."""
        self.state.is_running = True
        self.state.start_time = datetime.utcnow().isoformat()
        self.logger.info("Starting trading bot...")

        chain_key = self.config.get("primary_price_source", "arbitrum")
        self.session = UniswapSession(chain_key, self.config, self.state, self.logger)
        await self.session.start()

        try:
            while self.state.is_running:
                if self.session:
                    self.session.update_state_prices()
                self.pattern_detector.check_patterns()

                # Save state periodically
                save_state(self.state)
                save_trades(self.state.trades)

                await asyncio.sleep(5)  # Check every 5 seconds

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

    def simulate_trade(self, symbol: str, trade_type: str, amount_usd: float) -> Optional[Dict[str, Any]]:
        address = self.state.symbol_to_address.get(symbol)
        if not address:
            self.logger.warning(f"Symbol {symbol} not found.")
            return None
        return self.trade_executor.execute_trade(symbol, address, trade_type, amount_usd, "Manual")

    def get_discovered_tokens(self) -> List[str]:
        if self.session:
            return self.session.get_all_token_symbols()
        return list(self.state.prices.keys())

    def get_open_trades(self) -> List[Dict[str, Any]]:
        return self.trade_executor.get_open_trades()

    def get_closed_trades(self) -> List[Dict[str, Any]]:
        return self.trade_executor.get_closed_trades()


# =============================================================================
# OPTIONAL FEATURES (Can be entirely removed)
# =============================================================================

class OptionalFeatures:
    """
    Optional features that can be removed without affecting core functionality.
    To remove: Delete this entire class and all references to it.
    """

    def __init__(self, config: Dict[str, Any], state: BotState, logger: logging.Logger, trade_executor: TradeExecutor):
        self.config = config
        self.state = state
        self.logger = logger
        self.trade_executor = trade_executor
        self.backup_dir = Path("backups")
        self.backup_dir.mkdir(exist_ok=True)

    # --- Backup Management ---
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
        self.state = BotState(**backup_data["state"])
        self.state.trades = backup_data["trades"]
        self.logger.info(f"Restored from backup: {backup_file}")

    def auto_backup(self) -> None:
        if self.config.get("auto_backup", False):
            self.create_backup()

    def list_backups(self) -> List[str]:
        return [str(f) for f in self.backup_dir.glob("*.json")]

    # --- Statistics ---
    def get_pnl(self) -> Dict[str, float]:
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
        open_trades = [t for t in self.state.trades if t["status"] == "open"]
        return sum(t["token_amount"] * self.state.prices.get(t["token"], t["price"]) for t in open_trades if t["type"] == "buy")

    def update_statistics(self) -> None:
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
    parser = argparse.ArgumentParser(description="Uniswap Arbitrum Trading Bot")
    parser.add_argument("--config", type=str, default="config.json", help="Path to config file")
    parser.add_argument("--test", action="store_true", help="Force test mode")
    parser.add_argument("--simulate", nargs=3, metavar=("SYMBOL", "TYPE", "AMOUNT"),
                       help="Simulate a trade and exit")
    parser.add_argument("--status", action="store_true", help="Show status and exit")
    parser.add_argument("--trades", action="store_true", help="Show trade history and exit")
    parser.add_argument("--tokens", action="store_true", help="Show discovered tokens and exit")
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

    # Initialize optional features (can be removed)
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
        portfolio = optional.get_portfolio_value()
        open_trades = bot.get_open_trades()
        tokens = bot.get_discovered_tokens()
        print("=" * 60)
        print("STATUS")
        print("=" * 60)
        print(f"Mode: {'TEST' if config['is_test_mode'] else 'PROD'}")
        print(f"Network: {bot.state.network}")
        print(f"Running: {bot.state.is_running}")
        print(f"Tokens: {len(tokens)}")
        print(f"Open Trades: {len(open_trades)}")
        print(f"Portfolio: ${portfolio:.2f}")
        print(f"PnL: Total=${pnl['total']:.2f}, Daily=${pnl['daily']:.2f}")
        print("=" * 60)
        sys.exit(0)

    if args.trades:
        for trade in bot.get_open_trades():
            print(f"OPEN: {trade['timestamp']} {trade['type']:4} {trade['token']:6} ${trade['price']:8.2f}")
        for trade in bot.get_closed_trades():
            print(f"CLOSED: {trade['timestamp']} {trade['type']:4} {trade['token']:6} ${trade['price']:8.2f} PnL=${trade['pnl']:+.2f}")
        sys.exit(0)

    if args.tokens:
        for symbol in bot.get_discovered_tokens():
            address = bot.state.symbol_to_address.get(symbol, "N/A")
            price = bot.state.prices.get(symbol, 0)
            print(f"{symbol:8} | ${price:>10.4f} | {address}")
        sys.exit(0)

    # Optional features CLI
    if args.backup:
        optional.create_backup()
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
    print("UNISWAP TRADING BOT - MINIMAL VERSION")
    print("=" * 60)
    print(f"Mode: {'TEST' if config['is_test_mode'] else 'PROD'}")
    print(f"Network: {config.get('network', 'arbitrum')}")
    print(f"Press Ctrl+C to stop")
    print("=" * 60)

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