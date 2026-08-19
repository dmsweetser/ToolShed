#!/usr/bin/env python3
"""
Uniswap V3 Live Activity Monitor
A Python implementation of the HTML/JS blockchain monitoring example.
Focuses on real-time monitoring of Uniswap V3 swaps, token discovery, and price tracking.

Core Features:
- WebSocket monitoring of Uniswap V3 swaps
- Dynamic token discovery
- Price tracking from on-chain data
- Live activity display
- Separate WebSocket connections for subscriptions and RPC calls
"""

import json
import sys
import time
import logging
import asyncio
import websockets
from datetime import datetime
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
    factory: str
    wrapped_native: str
    quote_mode: str
    quote_label: str
    stables: List[str]

@dataclass
class TokenState:
    """Runtime state for a token."""
    address: str
    symbol: str = ""
    name: str = ""
    decimals: int = 18
    swaps: List[float] = field(default_factory=list)
    volume_quote: float = 0.0
    price_quote: Optional[float] = None
    history: List[Dict[str, Any]] = field(default_factory=list)
    last_seen: float = 0.0

@dataclass
class BotState:
    """Global state of the monitor."""
    is_running: bool = False
    network: str = "ethereum"
    current_chain_key: str = "ethereum"
    prices: Dict[str, float] = field(default_factory=dict)
    price_history: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
    address_to_symbol: Dict[str, str] = field(default_factory=dict)
    symbol_to_address: Dict[str, str] = field(default_factory=dict)
    start_time: Optional[str] = None
    last_price_update: Optional[str] = None
    block_count: int = 0
    pools_seen: int = 0
    tokens_seen: int = 0
    swaps_count: int = 0
    last_processed_block: Optional[int] = None
    rpc_head: int = 0

# =============================================================================
# CONSTANTS
# =============================================================================

UNISWAP_V3_FACTORY = "0x1F98431c8aD98523631AE4a59f267346ea31F984"
UNISWAP_V3_SWAP_TOPIC = "0xc42079f94a6350d7e6235f29174924f928cc2ac818eb64fed8004e115fbcca67"

# Known token configurations (for initial symbol hints)
KNOWN_TOKENS: Dict[str, Dict[str, Any]] = {
    # Ethereum
    "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2": {"symbol": "WETH", "name": "Wrapped ETH", "decimals": 18},
    "0x2260fac5e5542a773aa44fbcd444c101374479c8c": {"symbol": "WBTC", "name": "Wrapped BTC", "decimals": 8},
    "0x1f9840a85d5af5bf1d1762f925bdaddc4201f984": {"symbol": "UNI", "name": "Uniswap", "decimals": 18},
    "0x514910771af9ca656af840dff83e8264ecf986ca": {"symbol": "LINK", "name": "Chainlink", "decimals": 18},
    "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48": {"symbol": "USDC", "name": "USD Coin", "decimals": 6},
    "0xdac17f958d2ee523a2206206994597c13d831ec7": {"symbol": "USDT", "name": "Tether", "decimals": 6},
    "0x6b175474e89094c44da98b954eedeac495271d0f": {"symbol": "DAI", "name": "DAI Stablecoin", "decimals": 18},
    # Arbitrum
    "0x82af49447d8a07e3bd95bd0d56f35241523fbab1": {"symbol": "WETH", "name": "Wrapped ETH", "decimals": 18},
    "0x2f2a2543b76a416654947aab75b4e35b52a17231": {"symbol": "WBTC", "name": "Wrapped BTC", "decimals": 8},
    "0xaf88d065e77c8cc2239327c5edb3a432268e5831": {"symbol": "USDC", "name": "USD Coin", "decimals": 6},
    "0xfd086bc7cd5c481dcc9c85ebe478a1c0b69fcbb9": {"symbol": "USDT", "name": "Tether", "decimals": 6},
    "0xf97f4df75117a78c1a5a0dbb814af92458539fb4": {"symbol": "LINK", "name": "Chainlink", "decimals": 18},
    "0x912ce59144196c11c48067255325c5414506085a": {"symbol": "ARB", "name": "Arbitrum", "decimals": 18},
    "0xfc5a1a6eb076a2c7ad06ed22c5c769a78b3fa3a1": {"symbol": "GMX", "name": "GMX", "decimals": 18},
    # Base
    "0x4200000000000000000000000000000000000006": {"symbol": "WETH", "name": "Wrapped ETH", "decimals": 18},
    "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913": {"symbol": "USDC", "name": "USD Coin", "decimals": 6},
    "0x58880446d272457458b5444919133349044884f7": {"symbol": "USDT", "name": "Tether", "decimals": 6},
    # Optimism
    "0x4200000000000000000000000000000000000006": {"symbol": "WETH", "name": "Wrapped ETH", "decimals": 18},
    "0x0b2c639c533813f4aa9d7837caf62653d097ff85": {"symbol": "USDC", "name": "USD Coin", "decimals": 6},
    "0x7f5c764cbc14f9669b88837ca1490cCa17c31607": {"symbol": "USDT", "name": "Tether", "decimals": 6},
    # Polygon
    "0x0d500b1d8e8ef31e21c99d1db9a6444d3adf1270": {"symbol": "WPOL", "name": "Wrapped POL", "decimals": 18},
    "0x2791bca1f2de4661ed88a30c99a7a9449aa84174": {"symbol": "USDC", "name": "USD Coin", "decimals": 6},
    "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359": {"symbol": "USDT", "name": "Tether", "decimals": 6},
}

CHAINS: Dict[str, ChainConfig] = {
    "ethereum": ChainConfig(
        name="Ethereum",
        chain_id=1,
        ws="wss://ethereum-rpc.publicnode.com",
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
        factory=UNISWAP_V3_FACTORY,
        wrapped_native="0x4200000000000000000000000000000000000006",
        quote_mode="native",
        quote_label="WETH",
        stables=[
            "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
            "0x58880446d272457458b5444919133349044884f7",
        ],
    ),
    "arbitrum": ChainConfig(
        name="Arbitrum",
        chain_id=42161,
        ws="wss://arbitrum-one-rpc.publicnode.com",
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

CONFIG = {
    "MAX_TOKENS": 100,
    "WINDOW_MS": 15 * 60 * 1000,  # 15 minutes
    "HISTORY_MS": 15 * 60 * 1000,
    "MAX_HISTORY_POINTS": 180,
    "MAX_PRICE_PATH_DEPTH": 4,
    "RETRY_DELAY_MS": 3000,
    "HEAD_RETRY_MS": 700,
    "MAX_HEAD_RETRIES": 5,
    "LOG_CONCURRENCY": 4,
    "RENDER_INTERVAL_MS": 1000,
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

def setup_logging(debug_mode: str = "none") -> logging.Logger:
    """Configure logging based on debug mode."""
    log_levels = {"none": logging.INFO, "basic": logging.INFO, "verbose": logging.DEBUG}
    level = log_levels.get(debug_mode, logging.INFO)

    logger = logging.getLogger("uniswap_monitor")
    logger.setLevel(level)

    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    formatter = logging.Formatter(
        "%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    file_handler = logging.FileHandler("uniswap_monitor.log")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger

# =============================================================================
# STATE MANAGEMENT
# =============================================================================

def load_config(config_path: str = "config.json") -> Dict[str, Any]:
    """Load configuration from JSON file."""
    if not Path(config_path).exists():
        return {
            "network": "ethereum",
            "primary_price_source": "ethereum",
            "debug_mode": "none",
        }
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
                network=state_dict.get("network", "ethereum"),
                current_chain_key=state_dict.get("current_chain_key", "ethereum"),
                prices=state_dict.get("prices", {}),
                price_history=state_dict.get("price_history", {}),
                address_to_symbol=state_dict.get("address_to_symbol", {}),
                symbol_to_address=state_dict.get("symbol_to_address", {}),
                start_time=state_dict.get("start_time"),
                last_price_update=state_dict.get("last_price_update"),
                block_count=state_dict.get("block_count", 0),
                pools_seen=state_dict.get("pools_seen", 0),
                tokens_seen=state_dict.get("tokens_seen", 0),
                swaps_count=state_dict.get("swaps_count", 0),
                last_processed_block=state_dict.get("last_processed_block"),
                rpc_head=state_dict.get("rpc_head", 0),
            )
    return BotState()

def save_state(state: BotState, state_path: str = "state.json") -> None:
    """Save bot state to JSON file."""
    with open(state_path, "w") as f:
        json.dump(asdict(state), f, indent=2)

# =============================================================================
# CORE MONITOR CLASS
# =============================================================================

class UniswapMonitor:
    """
    Core class: Manages WebSocket connection to monitor Uniswap V3 swaps.
    Uses separate connections for subscriptions and RPC calls.
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
        self.session_serial = 0

        # WebSocket connections
        self.subscription_ws = None  # For newHeads subscription
        self.rpc_ws = None           # For eth_getLogs RPC calls

        # Data structures
        self.pools: Dict[str, Dict[str, Any]] = {}
        self.tokens: Dict[str, TokenState] = {}
        self.pair_prices: Dict[str, Dict[str, Dict[str, Any]]] = defaultdict(dict)
        self.metadata_in_flight: Dict[str, Any] = {}
        self.swaps: List[float] = []

        # Block processing
        self.pending_block: Optional[int] = None
        self.processing_blocks = False
        self.last_processed_block: Optional[int] = None

    def _normalize_topic_address(self, topic: str) -> str:
        """Extract Ethereum address from a topic (32-byte value)."""
        topic_clean = topic.lower().replace("0x", "")
        address = topic_clean[-40:]  # Take last 40 chars (20 bytes)
        return norm("0x" + address.zfill(40))

    async def start(self) -> None:
        """Start the WebSocket session."""
        if not self.chain:
            self.logger.error(f"Chain {self.chain_key} not configured")
            return

        self.session_serial += 1
        current_serial = self.session_serial
        self.state.is_running = True
        self.state.current_chain_key = self.chain_key
        self.state.network = self.chain_key

        try:
            # Connect for subscriptions (newHeads)
            self.subscription_ws = await websockets.connect(
                self.chain.ws,
                ping_interval=20,
                ping_timeout=10,
                close_timeout=1
            )
            self.logger.info(f"Connected to {self.chain.name} (subscriptions)")

            # Connect for RPC calls (eth_getLogs)
            self.rpc_ws = await websockets.connect(
                self.chain.ws,
                ping_interval=20,
                ping_timeout=10,
                close_timeout=1
            )
            self.logger.info(f"Connected to {self.chain.name} (RPC)")

            # Subscribe to new blocks
            await self._subscribe_to_blocks()

            # Get current head
            head = await self._get_block_number()
            if current_serial != self.session_serial:
                return

            self.state.rpc_head = head
            self.state.block_count = head
            self.logger.info(f"Current block: {head}")

            # Load the quote token immediately for L2 chains
            if self.chain.quote_mode == "native":
                await self._load_token(self.chain.wrapped_native)

            # Start listening for subscription messages
            await self._listen_for_messages(current_serial)

        except websockets.exceptions.ConnectionClosed as e:
            if current_serial != self.session_serial:
                return
            self.logger.error(f"WebSocket connection closed: {e}")
            self.connected = False
            self.state.is_running = False
            await self._schedule_reconnect(current_serial)
        except Exception as e:
            if current_serial != self.session_serial:
                return
            self.logger.error(f"Connection failed: {e}")
            self.connected = False
            self.state.is_running = False
            await self._schedule_reconnect(current_serial)

    async def stop(self) -> None:
        """Stop the WebSocket session."""
        self.active = False
        self.state.is_running = False
        self.session_serial += 1
        self.connected = False

        for ws in [self.subscription_ws, self.rpc_ws]:
            if ws:
                try:
                    await ws.close()
                except Exception:
                    pass
        self.subscription_ws = None
        self.rpc_ws = None
        self.logger.info(f"Disconnected from {self.chain.name}")

    async def _schedule_reconnect(self, current_serial: int) -> None:
        """Schedule a reconnection attempt."""
        if not self.active or current_serial != self.session_serial:
            return

        self.logger.info(f"Scheduling reconnect in {CONFIG['RETRY_DELAY_MS'] / 1000} seconds...")
        await asyncio.sleep(CONFIG["RETRY_DELAY_MS"] / 1000)
        if self.active and current_serial == self.session_serial:
            await self.start()

    async def _subscribe_to_blocks(self) -> None:
        """Subscribe to new block headers."""
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "eth_subscribe",
            "params": ["newHeads"]
        }
        try:
            await self.subscription_ws.send(json.dumps(request))
            self.logger.info("Subscribed to new block headers")
        except Exception as e:
            self.logger.error(f"Error subscribing to blocks: {e}")

    async def _get_block_number(self) -> int:
        """Get the current block number (using RPC connection)."""
        request = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "eth_blockNumber",
            "params": []
        }
        try:
            await self.rpc_ws.send(json.dumps(request))
            response = await self.rpc_ws.recv()
            data = json.loads(response)
            if "error" in data:
                self.logger.error(f"RPC error getting block number: {data['error']}")
                return 0
            return int(data["result"], 16)
        except Exception as e:
            self.logger.error(f"Failed to get block number: {e}")
            return 0

    async def _listen_for_messages(self, current_serial: int) -> None:
        """Listen for subscription messages (newHeads) only."""
        try:
            async for message in self.subscription_ws:
                if not self.active or current_serial != self.session_serial:
                    break

                try:
                    data = json.loads(message)

                    # Handle block notifications (from subscription)
                    if "params" in data and "result" in data["params"]:
                        block = data["params"]["result"]
                        if isinstance(block, dict) and "number" in block:
                            block_number = int(block["number"], 16)
                            await self._queue_block(block_number)

                except json.JSONDecodeError:
                    self.logger.debug("Received non-JSON message")
                except Exception as e:
                    self.logger.error(f"Error processing message: {e}")

        except websockets.exceptions.ConnectionClosed:
            if current_serial == self.session_serial:
                self.logger.error("Subscription WebSocket connection closed")
                self.connected = False
                await self._schedule_reconnect(current_serial)
        except Exception as e:
            if current_serial == self.session_serial:
                self.logger.error(f"Subscription WebSocket error: {e}")
                self.connected = False
                await self._schedule_reconnect(current_serial)

    async def _queue_block(self, block_number: int) -> None:
        """Queue a block for processing."""
        if not self.active:
            return

        if self.last_processed_block is not None and block_number <= self.last_processed_block:
            return

        self.pending_block = max(self.pending_block or 0, block_number)
        await self._process_pending()

    async def _process_pending(self) -> None:
        """Process pending blocks."""
        if self.processing_blocks or not self.active:
            return

        self.processing_blocks = True

        try:
            while self.pending_block is not None and self.active:
                target = self.pending_block
                self.pending_block = None

                # Get current head
                try:
                    head = await self._get_block_number()
                except Exception:
                    self.pending_block = target
                    await asyncio.sleep(CONFIG["HEAD_RETRY_MS"] / 1000)
                    continue

                self.state.rpc_head = head
                self.state.block_count = max(self.state.block_count, head)

                if target > head:
                    self.pending_block = target
                    await asyncio.sleep(CONFIG["HEAD_RETRY_MS"] / 1000)
                    continue

                if self.last_processed_block is not None and target <= self.last_processed_block:
                    continue

                await self._process_block(target)

                if not self.active:
                    break

                self.last_processed_block = target
                self.state.last_processed_block = target

        finally:
            self.processing_blocks = False

    async def _process_block(self, block_number: int) -> None:
        """Process a single block and its swap events."""
        if not self.active:
            return

        self.logger.debug(f"Processing block {block_number}")

        try:
            logs = await self._fetch_swap_logs(block_number)
            if logs:
                self.logger.info(f"Found {len(logs)} swap events in block {block_number}")
                self.state.swaps_count += len(logs)

                # Process logs concurrently
                tasks = []
                for log in logs:
                    tasks.append(self._process_swap_log(log))

                await asyncio.gather(*tasks)

        except Exception as e:
            self.logger.error(f"Error processing block {block_number}: {e}")

    async def _fetch_swap_logs(self, block_number: int) -> List[Dict[str, Any]]:
        """Fetch Uniswap V3 Swap logs for a block (using RPC connection)."""
        request = {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "eth_getLogs",
            "params": [{
                "fromBlock": hex(block_number),
                "toBlock": hex(block_number),
                "topics": [UNISWAP_V3_SWAP_TOPIC]  # Topic without 0x prefix
            }]
        }
        try:
            await self.rpc_ws.send(json.dumps(request))
            response = await self.rpc_ws.recv()
            data = json.loads(response)
            if "error" in data:
                self.logger.error(f"RPC error fetching logs: {data.get('error', {})}")
                return []
            logs = data.get("result", [])
            if not isinstance(logs, list):
                self.logger.error(f"Unexpected logs format: {type(logs)}")
                return []
            return logs
        except Exception as e:
            self.logger.error(f"Failed to fetch swap logs: {e}")
            return []

    async def _process_swap_log(self, log: Dict[str, Any]) -> None:
        """Process a single Uniswap V3 Swap event log."""
        if not self.active:
            return

        if not isinstance(log, dict):
            self.logger.error(f"Invalid log format: {type(log)}")
            return

        # Extract token addresses from topics
        topics = log.get("topics", [])
        if len(topics) < 3:
            self.logger.debug(f"Skipping log with insufficient topics: {topics}")
            return

        # Extract addresses from topics (32-byte values, take last 20 bytes)
        token0_addr = self._normalize_topic_address(topics[1])
        token1_addr = self._normalize_topic_address(topics[2])

        # Load the tokens
        token0 = await self._load_token(token0_addr)
        token1 = await self._load_token(token1_addr)
        if not token0 or not token1:
            return

        # Extract swap data from log
        try:
            data_hex = log.get("data", "0x")
            if data_hex == "0x":
                return
            data_hex = data_hex[2:]  # Remove 0x prefix

            if len(data_hex) < 192:  # Need at least 192 chars for first 3 params
                return

            # Extract amount0 (first 64 chars)
            amount0 = int(data_hex[:64], 16)
            # Extract amount1 (next 64 chars)
            amount1 = int(data_hex[64:128], 16)
            # Extract sqrtPriceX96 (next 64 chars)
            sqrt_price_x96 = int(data_hex[128:192], 16)

            # Calculate price
            price = self._pool_price(sqrt_price_x96, token0.decimals, token1.decimals)
            if price is None:
                return

            # Set the pair price
            self._set_pair(token0.address, token1.address, price)

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
            except Exception:
                n0 = 0
                n1 = 0

            # Get quote prices
            p0 = self._quote_price(token0.address)
            p1 = self._quote_price(token1.address)

            if p0 is not None:
                token0.price_quote = p0
                self._add_point(token0, p0)

            if p1 is not None:
                token1.price_quote = p1
                self._add_point(token1, p1)

            # Calculate volume in quote currency
            volume = None
            if p0 is not None and p1 is not None:
                volume = (n0 * p0 + n1 * p1) / 2
            elif p0 is not None:
                volume = n0 * p0
            elif p1 is not None:
                volume = n1 * p1

            if volume is not None and volume > 0:
                token0.volume_quote += volume
                token1.volume_quote += volume
                self.logger.debug(
                    f"Swap: {n0:.6f} {token0.symbol} <-> {n1:.6f} {token1.symbol} "
                    f"at price {price:.6f}, volume=${volume:.2f}"
                )

        except Exception as e:
            self.logger.error(f"Error processing swap log: {e}")

    async def _load_token(self, address: str) -> Optional[TokenState]:
        """Load token metadata. Creates tokens dynamically for any address."""
        address = norm(address)

        if address in self.tokens:
            return self.tokens[address]

        key = f"token:{address}"
        if key in self.metadata_in_flight:
            return await self.metadata_in_flight[key]

        async def load():
            symbol = generate_symbol(address)
            name = f"Token {short(address)}"
            decimals = 18

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
            self.state.tokens_seen += 1

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
        except Exception:
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

    def get_lag(self) -> int:
        """Calculate blocks behind."""
        processed = self.last_processed_block if self.last_processed_block is not None else self.state.block_count
        return max(0, (self.state.rpc_head or 0) - (processed or 0))

# =============================================================================
# MAIN MONITOR CLASS
# =============================================================================

class UniswapV3LiveMonitor:
    """Main monitoring class - Aligned with the HTML/JS example."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.logger = setup_logging(config.get("debug_mode", "none"))

        self.state = load_state()
        self.state.is_test_mode = config.get("is_test_mode", True)

        if not self.state.network:
            self.state.network = config.get("network", "ethereum")
        if not self.state.current_chain_key:
            self.state.current_chain_key = config.get("primary_price_source", "ethereum")

        self.monitor: Optional[UniswapMonitor] = None

        self.logger.info("Uniswap V3 Live Activity Monitor initialized")
        self.logger.info(f"Mode: {'TEST' if self.state.is_test_mode else 'PROD'}")
        self.logger.info(f"Network: {self.state.network}")

    async def start(self) -> None:
        """Start the monitoring."""
        self.state.is_running = True
        self.state.start_time = datetime.utcnow().isoformat()
        self.logger.info("Starting Uniswap V3 monitor...")

        chain_key = self.config.get("primary_price_source", "ethereum")
        self.monitor = UniswapMonitor(chain_key, self.config, self.state, self.logger)
        await self.monitor.start()

        try:
            while self.state.is_running:
                if self.monitor:
                    self.monitor.update_state_prices()
                    self._print_stats()

                save_state(self.state)
                await asyncio.sleep(CONFIG["RENDER_INTERVAL_MS"] / 1000)

        except KeyboardInterrupt:
            self.logger.info("Shutting down...")
            await self.stop()

    async def stop(self) -> None:
        """Stop the monitoring."""
        self.state.is_running = False
        if self.monitor:
            await self.monitor.stop()
            self.monitor = None
        save_state(self.state)
        self.logger.info("Monitor stopped. State saved.")

    def _print_stats(self) -> None:
        """Print current monitoring stats to the terminal."""
        if not self.monitor:
            return

        lag = self.monitor.get_lag()
        active_tokens = self.monitor.get_active_tokens()

        # Clear screen (works in most terminals)
        print("\033[H\033[J", end="")

        print("=" * 100)
        print("UNISWAP V3 LIVE ACTIVITY MONITOR")
        print("=" * 100)
        print(f"Chain: {self.state.network}")
        print(f"Block: {self.state.block_count:,}")
        print(f"Pools Seen: {self.state.pools_seen:,}")
        print(f"Tokens Seen: {self.state.tokens_seen:,}")
        print(f"Swaps / 15m: {len(self.monitor.swaps):,}")
        print(f"Blocks Behind: {lag:,}")
        print("=" * 100)
        print(f"{'#':<4} {'Token':<10} {'Price':>12} {'1m':>8} {'5m':>8} {'15m':>8} {'Activity':>12} {'Volume':>12}")
        print("-" * 100)

        for i, token in enumerate(active_tokens[:50]):  # Show top 50 tokens
            price = token.price_quote
            price_str = f"${price:,.6f}" if price is not None else "No quote"

            # Calculate percentage changes
            pct_1m = self._calculate_pct_change(token, 60000)
            pct_5m = self._calculate_pct_change(token, 300000)
            pct_15m = self._calculate_pct_change(token, 900000)

            pct_1m_str = f"{pct_1m:+.2f}%" if pct_1m is not None else "—"
            pct_5m_str = f"{pct_5m:+.2f}%" if pct_5m is not None else "—"
            pct_15m_str = f"{pct_15m:+.2f}%" if pct_15m is not None else "—"

            activity = f"{len(token.swaps)} swaps"
            volume = f"${token.volume_quote:,.2f}" if token.volume_quote > 0 else "—"

            print(f"{i+1:<4} {token.symbol:<10} {price_str:>12} {pct_1m_str:>8} {pct_5m_str:>8} {pct_15m_str:>8} {activity:>12} {volume:>12}")

        print("=" * 100)
        print("Press Ctrl+C to stop")

    def _calculate_pct_change(self, token: TokenState, ms: int) -> Optional[float]:
        """Calculate percentage change over a time period."""
        if token.price_quote is None:
            return None

        target_time = time.time() * 1000 - ms
        old_price = None

        for point in reversed(token.history):
            if point["t"] <= target_time:
                old_price = point["price"]
                break

        if old_price is None or old_price <= 0:
            return None

        return ((token.price_quote - old_price) / old_price) * 100

    def get_discovered_tokens(self) -> List[str]:
        if self.monitor:
            return self.monitor.get_all_token_symbols()
        return list(self.state.prices.keys())

    def change_chain(self, chain_key: str) -> None:
        """Change the monitored chain."""
        if chain_key in CHAINS:
            self.config["primary_price_source"] = chain_key
            self.state.current_chain_key = chain_key
            self.state.network = chain_key
            self.logger.info(f"Changed chain to {chain_key}")
        else:
            self.logger.warning(f"Chain {chain_key} not configured")

# =============================================================================
# CLI INTERFACE
# =============================================================================

def parse_args():
    import argparse
    import sys
    parser = argparse.ArgumentParser(description="Uniswap V3 Live Activity Monitor")
    parser.add_argument("--config", type=str, default="config.json", help="Path to config file")
    parser.add_argument("--test", action="store_true", help="Force test mode")
    parser.add_argument("--chain", type=str, default=None,
                        help="Chain to monitor (ethereum, arbitrum, base, optimism, polygon)")
    parser.add_argument("--status", action="store_true", help="Show status and exit")
    parser.add_argument("--tokens", action="store_true", help="Show discovered tokens and exit")
    return parser.parse_args()

def main():
    import sys
    args = parse_args()
    config = load_config(args.config)

    if args.test:
        config["is_test_mode"] = True

    if args.chain:
        config["primary_price_source"] = args.chain
        config["network"] = args.chain

    # Initialize monitor
    monitor = UniswapV3LiveMonitor(config)

    # Handle CLI commands
    if args.status:
        print("=" * 60)
        print("STATUS")
        print("=" * 60)
        print(f"Mode: {'TEST' if config.get('is_test_mode', True) else 'PROD'}")
        print(f"Network: {monitor.state.network}")
        print(f"Running: {monitor.state.is_running}")
        print(f"Tokens: {len(monitor.get_discovered_tokens())}")
        print(f"Pools Seen: {monitor.state.pools_seen}")
        print(f"Tokens Seen: {monitor.state.tokens_seen}")
        print(f"Swaps Count: {monitor.state.swaps_count}")
        print("=" * 60)
        sys.exit(0)

    if args.tokens:
        for symbol in monitor.get_discovered_tokens():
            address = monitor.state.symbol_to_address.get(symbol, "N/A")
            price = monitor.state.prices.get(symbol, 0)
            print(f"{symbol:8} | ${price:>10.4f} | {address}")
        sys.exit(0)

    # Start the monitor
    print("=" * 60)
    print("UNISWAP V3 LIVE ACTIVITY MONITOR")
    print("=" * 60)
    print(f"Mode: {'TEST' if config.get('is_test_mode', True) else 'PROD'}")
    print(f"Network: {config.get('network', 'ethereum')}")
    print(f"Press Ctrl+C to stop")
    print("=" * 60)

    try:
        asyncio.run(monitor.start())
    except KeyboardInterrupt:
        asyncio.run(monitor.stop())
    except Exception as e:
        monitor.logger.error(f"Fatal error: {e}")
        asyncio.run(monitor.stop())
        sys.exit(1)

if __name__ == "__main__":
    main()