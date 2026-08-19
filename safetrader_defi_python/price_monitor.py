#!/usr/bin/env python3
"""
Uniswap V3 Live Activity Monitor (Subscription-Only)
- Uses only WebSocket subscriptions (no RPC calls for logs/blocks).
- Fetches real token names/symbols/decimals via WebSocket eth_call.
- Outputs token states to token_states.json periodically.
- Fully compatible with main.py.
"""

import json
import time
import logging
import asyncio
import websockets
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
from config import Config
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

# ERC-20 function selectors
SYMBOL_SELECTOR = "0x95d89b41"
NAME_SELECTOR = "0x06fdde03"
DECIMALS_SELECTOR = "0x313ce567"

# Known token configurations
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
    "WINDOW_MS": 15 * 60 * 1000,
    "HISTORY_MS": 15 * 60 * 1000,
    "MAX_HISTORY_POINTS": 180,
    "MAX_PRICE_PATH_DEPTH": 4,
    "RETRY_DELAY_MS": 3000,
    "HEAD_RETRY_MS": 700,
    "MAX_HEAD_RETRIES": 5,
    "LOG_CONCURRENCY": 4,
    "RENDER_INTERVAL_MS": 1000,
    "TOKEN_STATE_FILE": "token_states.json",
    "ETH_CALL_TIMEOUT": 10.0,
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
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    return logger


def load_config(config_path: str = "config.json") -> Dict[str, Any]:
    """Load configuration from .env file (falls back to defaults)."""
    return Config.as_dict()


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


def save_token_states(tokens: Dict[str, TokenState], filepath: str = "token_states.json") -> None:
    """Save all token states to a JSON file."""
    token_data = {}
    for addr, token in tokens.items():
        token_data[addr] = {
            "symbol": token.symbol,
            "name": token.name,
            "decimals": token.decimals,
            "address": token.address,
            "price_quote": token.price_quote,
            "volume_quote": token.volume_quote,
            "last_seen": token.last_seen,
            "swaps_count": len(token.swaps),
            "history": token.history,
        }
    with open(filepath, "w") as f:
        json.dump(token_data, f, indent=2)


# =============================================================================
# CORE MONITOR CLASS
# =============================================================================

class UniswapMonitor:
    """
    Manages WebSocket connection to monitor Uniswap V3 swaps.
    Uses only subscriptions (no RPC calls for logs/blocks).
    Fetches token metadata via WebSocket eth_call.
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

        # Single WebSocket connection
        self.ws = None

        # Data structures
        self.pools: Dict[str, Dict[str, Any]] = {}
        self.tokens: Dict[str, TokenState] = {}
        self.pair_prices: Dict[str, Dict[str, Dict[str, Any]]] = defaultdict(dict)
        self.metadata_in_flight: Dict[str, Any] = {}
        self.swaps: List[float] = []

        # Block tracking
        self.last_processed_block: Optional[int] = None

        # For eth_call responses
        self.pending_requests: Dict[int, asyncio.Future] = {}
        self.request_id_counter = 10000  # Start high to avoid conflicts with subscription IDs (1, 2)

    def _normalize_topic_address(self, topic: str) -> str:
        """Extract Ethereum address from a topic (32-byte value)."""
        topic_clean = topic.lower().replace("0x", "")
        address = topic_clean[-40:]  # Take last 40 chars (20 bytes)
        return norm("0x" + address.zfill(40))

    async def _call_contract(self, address: str, data: str, timeout: float = 10.0) -> Optional[str]:
        """Call a contract method via WebSocket eth_call."""
        if not self.ws:
            return None

        self.request_id_counter += 1
        request_id = self.request_id_counter

        request = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "eth_call",
            "params": [{"to": address, "data": data}, "latest"]
        }

        # Create a future to await the response
        future = asyncio.Future()
        self.pending_requests[request_id] = future

        try:
            await self.ws.send(json.dumps(request))
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            self.logger.debug(f"eth_call timeout for {address}")
            return None
        except Exception as e:
            self.logger.debug(f"eth_call failed for {address}: {e}")
            return None
        finally:
            self.pending_requests.pop(request_id, None)

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
            # Single WebSocket connection
            self.ws = await websockets.connect(
                self.chain.ws,
                ping_interval=20,
                ping_timeout=10,
                close_timeout=1
            )
            self.logger.info(f"Connected to {self.chain.name}")

            # Subscribe to newHeads and logs
            await self._subscribe_to_events()

            # Start listening for messages
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
        if self.ws:
            try:
                await self.ws.close()
            except Exception:
                pass
        self.ws = None
        self.logger.info(f"Disconnected from {self.chain.name}")

    async def _schedule_reconnect(self, current_serial: int) -> None:
        """Schedule a reconnection attempt."""
        if not self.active or current_serial != self.session_serial:
            return

        self.logger.info(f"Scheduling reconnect in {CONFIG['RETRY_DELAY_MS'] / 1000} seconds...")
        await asyncio.sleep(CONFIG["RETRY_DELAY_MS"] / 1000)
        if self.active and current_serial == self.session_serial:
            await self.start()

    async def _subscribe_to_events(self) -> None:
        """Subscribe to newHeads and Uniswap V3 Swap logs."""
        # Subscribe to newHeads (ID 1)
        new_heads_request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "eth_subscribe",
            "params": ["newHeads"]
        }
        await self.ws.send(json.dumps(new_heads_request))
        self.logger.info("Subscribed to new block headers")

        # Subscribe to Uniswap V3 Swap logs (ID 2)
        logs_request = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "eth_subscribe",
            "params": [
                "logs",
                {
                    "topics": [UNISWAP_V3_SWAP_TOPIC]
                }
            ]
        }
        await self.ws.send(json.dumps(logs_request))
        self.logger.info("Subscribed to Uniswap V3 Swap logs")

    async def _listen_for_messages(self, current_serial: int) -> None:
        """Listen for subscription messages and eth_call responses."""
        try:
            async for message in self.ws:
                if not self.active or current_serial != self.session_serial:
                    break

                try:
                    data = json.loads(message)

                    # Handle eth_call responses FIRST
                    if "id" in data and data["id"] in self.pending_requests:
                        future = self.pending_requests.pop(data["id"])
                        future.set_result(data.get("result"))
                        continue

                    # Skip ONLY subscription confirmations (IDs 1 and 2)
                    if "id" in data and data["id"] in {1, 2}:
                        continue

                    # Handle notifications (newHeads and logs)
                    if "params" in data and "result" in data.get("params", {}):
                        result = data["params"]["result"]
                        if isinstance(result, dict):
                            if "number" in result:  # Block notification
                                block_number = int(result["number"], 16)
                                self.state.block_count = block_number
                                self.state.rpc_head = block_number
                                self.last_processed_block = block_number
                                self.logger.info(f"New block: {block_number}")
                            elif "topics" in result:  # Log notification (swap)
                                await self._process_swap_log(result)

                except json.JSONDecodeError:
                    self.logger.debug("Received non-JSON message")
                except Exception as e:
                    self.logger.error(f"Error processing message: {e}")

        except websockets.exceptions.ConnectionClosed:
            if current_serial == self.session_serial:
                self.logger.error("WebSocket connection closed")
                self.connected = False
                await self._schedule_reconnect(current_serial)
        except Exception as e:
            if current_serial == self.session_serial:
                self.logger.error(f"WebSocket error: {e}")
                self.connected = False
                await self._schedule_reconnect(current_serial)

    async def _process_swap_log(self, log: Dict[str, Any]) -> None:
        """Process a single Uniswap V3 Swap event log."""
        if not self.active:
            return

        if not isinstance(log, dict):
            self.logger.error(f"Invalid log format: {type(log)}")
            return

        topics = log.get("topics", [])
        if len(topics) < 3:
            self.logger.debug(f"Skipping log with insufficient topics: {topics}")
            return

        token0_addr = self._normalize_topic_address(topics[1])
        token1_addr = self._normalize_topic_address(topics[2])

        token0 = await self._load_token(token0_addr)
        token1 = await self._load_token(token1_addr)
        if not token0 or not token1:
            return

        try:
            data_hex = log.get("data", "0x")
            if data_hex == "0x":
                return
            data_hex = data_hex[2:]

            if len(data_hex) < 192:
                return

            amount0 = int(data_hex[:64], 16)
            amount1 = int(data_hex[64:128], 16)
            sqrt_price_x96 = int(data_hex[128:192], 16)

            price = self._pool_price(sqrt_price_x96, token0.decimals, token1.decimals)
            if price is None:
                return

            self._set_pair(token0.address, token1.address, price)

            timestamp = time.time() * 1000
            self.swaps.append(timestamp)
            token0.swaps.append(timestamp)
            token1.swaps.append(timestamp)
            token0.last_seen = timestamp
            token1.last_seen = timestamp

            try:
                n0 = abs(float(amount0) / (10 ** token0.decimals))
                n1 = abs(float(amount1) / (10 ** token1.decimals))
            except Exception:
                n0 = 0
                n1 = 0

            p0 = self._quote_price(token0.address)
            p1 = self._quote_price(token1.address)

            if p0 is not None:
                token0.price_quote = p0
                self._add_point(token0, p0)

            if p1 is not None:
                token1.price_quote = p1
                self._add_point(token1, p1)

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

        except Exception as e:
            self.logger.error(f"Error processing swap log: {e}")

    async def _load_token(self, address: str) -> Optional[TokenState]:
        """Load token metadata, fetching from chain if unknown."""
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

            # Check known tokens first
            if address in KNOWN_TOKENS:
                token_data = KNOWN_TOKENS[address]
                symbol = token_data.get("symbol", symbol)
                name = token_data.get("name", name)
                decimals = token_data.get("decimals", decimals)
            else:
                # Fetch from chain via WebSocket eth_call
                try:
                    # symbol()
                    symbol_hex = await self._call_contract(address, SYMBOL_SELECTOR, timeout=CONFIG["ETH_CALL_TIMEOUT"])
                    if symbol_hex and symbol_hex != "0x":
                        try:
                            symbol = bytes.fromhex(symbol_hex[2:]).decode('utf-8', errors='replace').strip('\x00')
                        except (ValueError, UnicodeDecodeError):
                            pass

                    # name()
                    name_hex = await self._call_contract(address, NAME_SELECTOR, timeout=CONFIG["ETH_CALL_TIMEOUT"])
                    if name_hex and name_hex != "0x":
                        try:
                            name = bytes.fromhex(name_hex[2:]).decode('utf-8', errors='replace').strip('\x00')
                        except (ValueError, UnicodeDecodeError):
                            pass

                    # decimals()
                    decimals_hex = await self._call_contract(address, DECIMALS_SELECTOR, timeout=CONFIG["ETH_CALL_TIMEOUT"])
                    if decimals_hex and decimals_hex != "0x":
                        try:
                            decimals = int(decimals_hex, 16)
                        except ValueError:
                            pass

                except Exception as e:
                    self.logger.debug(f"Failed to fetch token metadata for {address}: {e}")

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

            self.logger.info(f"Discovered new token: {symbol} ({name}) at {address}")
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

    def save_token_states(self) -> None:
        """Save all token states to a JSON file."""
        save_token_states(self.tokens, CONFIG["TOKEN_STATE_FILE"])


# =============================================================================
# MAIN MONITOR CLASS
# =============================================================================

class UniswapV3LiveMonitor:
    """Main monitoring class."""

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
                    self.monitor.save_token_states()

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
            self.monitor.save_token_states()
            self.monitor = None
        save_state(self.state)
        self.logger.info("Monitor stopped. State saved.")

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

    monitor = UniswapV3LiveMonitor(config)

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