import os
import json
import time
import random
import asyncio
import threading
import logging
import requests
import hashlib
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set, Tuple, Any

from dotenv import load_dotenv
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware
import sqlite3
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    handlers=[
        logging.FileHandler("app.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

# ========== UTILITY FUNCTIONS ==========
def norm(a: str) -> str:
    return a.lower() if a else ""

def short(a: str) -> str:
    if not a:
        return ""
    return f"{a[:6]}...{a[-4:]}"

def to_checksum_address(address: str) -> str:
    if not address or not isinstance(address, str):
        return address
    try:
        return Web3.to_checksum_address(address.lower())
    except Exception:
        return address

# ========== COINGECKO TOKEN FETCHER ==========
import json
from pathlib import Path

TOKEN_LIST_URL = "https://tokens.coingecko.com/arbitrum-one/all.json"
LOCAL_TOKEN_FILE = Path("data/arbitrum_tokens.json")

def fetch_coingecko_tokens(chain_id: int = 42161) -> List[Dict[str, Any]]:
    # Try local file first
    if LOCAL_TOKEN_FILE.exists():
        try:
            with open(LOCAL_TOKEN_FILE, "r") as f:
                data = json.load(f)
                tokens = data.get("tokens", [])
                logger.info(f"Loaded {len(tokens)} tokens from local cache")
                return [token for token in tokens if token.get("chainId") == chain_id]
        except Exception as e:
            logger.warning(f"Failed to load local token cache: {e}")

    # Fall back to API with retry
    try:
        logger.info("Fetching fresh token list from CoinGecko...")
        session = requests.Session()
        retry = Retry(total=3, backoff_factor=5, status_forcelist=[429])
        session.mount("https://", HTTPAdapter(max_retries=retry))

        response = session.get(TOKEN_LIST_URL, timeout=15)
        response.raise_for_status()
        data = response.json()

        # Save to local file
        LOCAL_TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOCAL_TOKEN_FILE, "w") as f:
            json.dump(data, f, indent=2)

        tokens = data.get("tokens", [])
        logger.info(f"Fetched and cached {len(tokens)} tokens from CoinGecko")
        return [token for token in tokens if token.get("chainId") == chain_id]
    except Exception as e:
        logger.error(f"Failed to fetch CoinGecko tokens: {e}")
        return []

# ========== PARAMETER GENERATION ==========
@dataclass
class ParameterRange:
    min: float
    max: float
    step: float

    def generate_values(self) -> List[float]:
        values = []
        current = self.min
        while current <= self.max + 1e-9:
            values.append(current)
            current += self.step
        return values

# Aggressive parameter ranges + explicit aggressive set
DEFAULT_PARAMETER_RANGES = {
    "MIN_PRICE_CHANGE":    ParameterRange(min=0.001, max=0.5,  step=0.499),
    "MIN_TIME_WINDOW":     ParameterRange(min=1,     max=30,   step=29),
    "MAX_TIME_WINDOW":     ParameterRange(min=60,    max=300,  step=240),
    "MIN_OCCURRENCES":     ParameterRange(min=1,     max=3,    step=1),
    "MIN_PROFIT_PERCENT":  ParameterRange(min=0.01,  max=5.0,  step=4.99),
}

class ParameterGenerator:
    def __init__(self, ranges: Optional[Dict[str, ParameterRange]] = None, max_combinations: int = 50):
        self.ranges = ranges or DEFAULT_PARAMETER_RANGES
        self.max_combinations = max_combinations
        self.parameter_sets = self._generate_parameter_sets()
        # Add explicit aggressive set
        aggressive_set = {
            "MIN_PRICE_CHANGE": 0.001,
            "MIN_TIME_WINDOW": 1,
            "MAX_TIME_WINDOW": 60,
            "MIN_OCCURRENCES": 1,
            "MIN_PROFIT_PERCENT": 0.01
        }
        if aggressive_set not in [dict(p) for p in self.parameter_sets]:
            self.parameter_sets.append(aggressive_set)
            if len(self.parameter_sets) > self.max_combinations:
                self.parameter_sets.pop(0)
        logger.info(f"Generated {len(self.parameter_sets)} parameter sets (including aggressive set)")

    def _generate_parameter_sets(self) -> List[Dict[str, float]]:
        param_values = {name: rng.generate_values() for name, rng in self.ranges.items()}
        total_combinations = 1
        for values in param_values.values():
            total_combinations *= len(values)
        if total_combinations <= self.max_combinations:
            return self._generate_all_combinations(param_values)
        else:
            logger.info(f"Total combinations ({total_combinations}) exceeds max ({self.max_combinations}), sampling...")
            return self._sample_combinations(param_values, self.max_combinations)

    def _generate_all_combinations(self, param_values: Dict[str, List[float]]) -> List[Dict[str, float]]:
        from itertools import product
        param_names = list(param_values.keys())
        value_lists = [param_values[name] for name in param_names]
        return [dict(zip(param_names, combo)) for combo in product(*value_lists)]

    def _sample_combinations(self, param_values: Dict[str, List[float]], count: int) -> List[Dict[str, float]]:
        param_names = list(param_values.keys())
        value_lists = [param_values[name] for name in param_names]
        combinations = set()
        while len(combinations) < count:
            combo = tuple(random.choice(values) for values in value_lists)
            combinations.add(combo)
        return [dict(zip(param_names, combo)) for combo in combinations]

    def get_parameter_sets(self) -> List[Dict[str, float]]:
        return self.parameter_sets

# ========== CONFIGURATION ==========
@dataclass
class Config:
    BLOCKCHAIN_NETWORK: str = "arbitrum"
    UNISWAP_VERSION: str = "v3"
    STARTING_ETH: float = 0.0033
    TRADE_AMOUNT_PERCENT: float = 0.5
    MIN_TRADE_AMOUNT_ETH: float = 0.0003
    MAX_TRADES: int = 10
    TRADE_COOLDOWN: int = 60
    MIN_PRICE_CHANGE: float = 0.1
    MIN_TIME_WINDOW: int = 5
    MAX_TIME_WINDOW: int = 120
    MIN_OCCURRENCES: int = 2
    MIN_PROFIT_PERCENT: float = 1.0
    MAX_SLIPPAGE: float = 0.5
    MAX_GAS_PRICE: int = 200
    GAS_LIMIT: int = 300000
    PREVENT_SEQUENTIAL_TRADES: bool = True
    PRICE_HISTORY_DURATION: int = 24
    MAX_PRICE_HISTORY: int = 5000
    OPTIMIZATION_INTERVAL: int = 300
    MAX_PARAMETER_SETS: int = 50

# ========== CONSTANTS ==========
POOL_FEES = {"LOW": 500, "MEDIUM": 3000, "HIGH": 10000}
PATTERN_TYPES = {"BUY": "buy"}

NETWORK_TOKENS = {
    "arbitrum": {
        "WETH": "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1",
        "WBTC": "0x2f2a2543B76A416654947aaB75B4e35b52a17231",
        "UNI": "0xfa7F8980b0f1E64A2062791cc3b0871572f1F7f0",
        "LINK": "0xf97f4df75117a78c1A5a0DBb814Af92458539FB4",
        "ARB": "0x912CE59144196C11c48067255325c5414506085A",
        "GMX": "0xfc5A1A6EB076a2C7aD06eD22C5C769A78b3Fa3A1",
        "USDC": "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
        "USDT": "0xFd086bC7CD5C481DCC9C85ebE478A1C0b69FCbb9"
    }
}

ARBITRUM_RPC_ENDPOINTS = [
    "https://arbitrum-mainnet.public.blastapi.io",
    "https://arb1.arbitrum.io/rpc",
    "https://arbitrum-mainnet.rpcfast.com",
    "wss://arbitrum-one-rpc.publicnode.com"
]

CHAINS = {
    "arbitrum": {
        "name": "Arbitrum One",
        "chainId": 42161,
        "rpcs": ARBITRUM_RPC_ENDPOINTS,
        "factory": "0x1F98431c8aD98523631AE4a59f267346ea31F984",
        "wrappedNative": "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1",
        "quoteMode": "native",
        "quoteLabel": "ETH",
        "stables": [
            "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
            "0xFd086bC7CD5C481DCC9C85ebE478A1C0b69FCbb9"
        ],
        "topPools": [
            ("0x82aF49447D8a07e3bd95BD0d56f35241523fBab1", "0x2f2a2543B76A416654947aaB75B4e35b52a17231", 3000),
            ("0x82aF49447D8a07e3bd95BD0d56f35241523fBab1", "0xfa7F8980b0f1E64A2062791cc3b0871572f1F7f0", 3000),
            ("0x82aF49447D8a07e3bd95BD0d56f35241523fBab1", "0xf97f4df75117a78c1A5a0DBb814Af92458539FB4", 3000),
            ("0x82aF49447D8a07e3bd95BD0d56f35241523fBab1", "0x912CE59144196C11c48067255325c5414506085A", 3000),
            ("0x82aF49447D8a07e3bd95BD0d56f35241523fBab1", "0xfc5A1A6EB076a2C7aD06eD22C5C769A78b3Fa3A1", 3000),
            ("0x82aF49447D8a07e3bd95BD0d56f35241523fBab1", "0xaf88d065e77c8cC2239327C5EDb3A432268e5831", 500),
            ("0x82aF49447D8a07e3bd95BD0d56f35241523fBab1", "0xFd086bC7CD5C481DCC9C85ebE478A1C0b69FCbb9", 500)
        ]
    }
}

# ABI definitions
UNISWAP_V3_FACTORY_ABI = json.loads('''
[
    {
        "inputs": [
            {"internalType": "address", "name": "tokenA", "type": "address"},
            {"internalType": "address", "name": "tokenB", "type": "address"},
            {"internalType": "uint24", "name": "fee", "type": "uint24"}
        ],
        "name": "getPool",
        "outputs": [{"internalType": "address", "name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function"
    }
]
''')

UNISWAP_V3_POOL_ABI = json.loads('''
[
    {
        "inputs": [],
        "name": "slot0",
        "outputs": [
            {"internalType": "uint160", "name": "sqrtPriceX96", "type": "uint160"},
            {"internalType": "int24", "name": "tick", "type": "int24"},
            {"internalType": "uint16", "name": "observationIndex", "type": "uint16"},
            {"internalType": "uint16", "name": "observationCardinality", "type": "uint16"},
            {"internalType": "uint16", "name": "observationCardinalityNext", "type": "uint16"},
            {"internalType": "uint8", "name": "feeProtocol", "type": "uint8"},
            {"internalType": "bool", "name": "unlocked", "type": "bool"}
        ],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [],
        "name": "token0",
        "outputs": [{"internalType": "address", "name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [],
        "name": "token1",
        "outputs": [{"internalType": "address", "name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [],
        "name": "fee",
        "outputs": [{"internalType": "uint24", "name": "", "type": "uint24"}],
        "stateMutability": "view",
        "type": "function"
    }
]
''')

ERC20_ABI = json.loads('''
[
    {"inputs": [], "name": "symbol", "outputs": [{"internalType": "string", "name": "", "type": "string"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "decimals", "outputs": [{"internalType": "uint8", "name": "", "type": "uint8"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "name", "outputs": [{"internalType": "string", "name": "", "type": "string"}], "stateMutability": "view", "type": "function"},
    {"inputs": [{"internalType": "address", "name": "account"}], "name": "balanceOf", "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"}
]
''')

# ========== STATE MANAGEMENT (THREAD-SAFE) ==========
class State:
    def __init__(self, config: Config):
        self.config = config
        self.is_running = False
        self.current_network = config.BLOCKCHAIN_NETWORK
        self.current_chain_key = config.BLOCKCHAIN_NETWORK
        self.prices: Dict[str, float] = {}
        self.price_history: Dict[str, List[Dict[str, Any]]] = {}
        self.trades: List[Dict[str, Any]] = []
        self.active_patterns: Dict[str, Dict[str, Any]] = {}
        self.portfolio: Dict[str, Any] = {
            "balances": {"ETH": config.STARTING_ETH},
            "positions": [],
            "realized_pnl": 0,
            "unrealized_pnl": 0,
            "gas_spent": 0,
            "fees_paid": 0,
            "starting_eth": config.STARTING_ETH,
            "current_eth": config.STARTING_ETH,
            "equity_history": [{"timestamp": time.time(), "eth_value": config.STARTING_ETH}],
            "total_trades": 0,
            "winning_trades": 0,
            "losing_trades": 0,
            "failed_trades": 0,
            "total_fees": 0,
        }
        self.last_traded_token = None
        self.last_trade_times: Dict[str, float] = {}
        self.start_time = None
        self.last_price_update = None
        self.current_gas_price = 0.02
        self.manually_stopped = True
        self.observed_tokens: Set[str] = set()
        self.pattern_stats: Dict[str, int] = {"total_patterns": 0, "tokens_with_patterns": 0}
        self.open_buy_orders: Dict[str, Dict[str, Any]] = {}
        self.pattern_detection_active = False
        self.wallet_connected = False
        self.live_mode = False
        self.token_decimals: Dict[str, int] = {}
        self.token_symbols: Dict[str, str] = {}
        self.token_addresses: Dict[str, str] = {}
        self._lock = threading.Lock()  # Thread safety lock
        logger.info("State initialized with starting ETH: %.12f", config.STARTING_ETH)

    def get_token_symbol(self, token: str) -> str:
        with self._lock:
            if token in self.token_symbols:
                return self.token_symbols[token]
            checksummed = to_checksum_address(token)
            if checksummed in self.token_symbols:
                return self.token_symbols[checksummed]
            for symbol, addr in list(self.token_addresses.items()):
                if norm(token) == norm(addr):
                    return symbol
            return short(token)

    def get_token_address(self, token: str) -> Optional[str]:
        with self._lock:
            if token in self.token_addresses.values():
                return to_checksum_address(token)
            if norm(token) in [norm(addr) for addr in list(self.token_addresses.values())]:
                return to_checksum_address(token)
            if token in self.token_addresses:
                return to_checksum_address(self.token_addresses[token])
            return None

    def get_token_price(self, token: str) -> Optional[float]:
        with self._lock:
            if token in self.prices:
                return self.prices[token]
            checksummed = to_checksum_address(token)
            if checksummed in self.prices:
                return self.prices[checksummed]
            if token in self.token_addresses:
                addr = self.token_addresses[token]
                if addr in self.prices:
                    return self.prices[addr]
                checksummed_addr = to_checksum_address(addr)
                if checksummed_addr in self.prices:
                    return self.prices[checksummed_addr]
            for symbol, addr in list(self.token_addresses.items()):
                if norm(token) == norm(addr):
                    if addr in self.prices:
                        return self.prices[addr]
                    checksummed_addr = to_checksum_address(addr)
                    if checksummed_addr in self.prices:
                        return self.prices[checksummed_addr]
            return None

    def get_token_history(self, token: str) -> Optional[List[Dict[str, Any]]]:
        with self._lock:
            if token in self.price_history:
                return self.price_history[token]
            checksummed = to_checksum_address(token)
            if checksummed in self.price_history:
                return self.price_history[checksummed]
            if token in self.token_addresses:
                addr = self.token_addresses[token]
                if addr in self.price_history:
                    return self.price_history[addr]
                checksummed_addr = to_checksum_address(addr)
                if checksummed_addr in self.price_history:
                    return self.price_history[checksummed_addr]
            for symbol, addr in list(self.token_addresses.items()):
                if norm(token) == norm(addr):
                    if addr in self.price_history:
                        return self.price_history[addr]
                    checksummed_addr = to_checksum_address(addr)
                    if checksummed_addr in self.price_history:
                        return self.price_history[checksummed_addr]
            return None

    def to_dict(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "config": asdict(self.config),
                "is_running": self.is_running,
                "current_network": self.current_network,
                "prices": dict(self.prices),
                "price_history": {k: v for k, v in self.price_history.items()},
                "trades": list(self.trades),
                "active_patterns": dict(self.active_patterns),
                "portfolio": dict(self.portfolio),
                "last_traded_token": self.last_traded_token,
                "last_trade_times": dict(self.last_trade_times),
                "start_time": self.start_time,
                "last_price_update": self.last_price_update,
                "current_gas_price": self.current_gas_price,
                "observed_tokens": list(self.observed_tokens),
                "pattern_stats": dict(self.pattern_stats),
                "open_buy_orders": dict(self.open_buy_orders),
                "token_symbols": dict(self.token_symbols),
                "token_addresses": dict(self.token_addresses),
                "timestamp": datetime.now().isoformat(),
            }

    def from_dict(self, state_dict: Dict[str, Any]):
        with self._lock:
            self.config = Config(**state_dict["config"])
            self.is_running = state_dict["is_running"]
            self.current_network = state_dict["current_network"]
            self.prices = state_dict["prices"]
            self.price_history = state_dict["price_history"]
            self.trades = state_dict["trades"]
            self.active_patterns = state_dict["active_patterns"]
            self.portfolio = state_dict["portfolio"]
            self.last_traded_token = state_dict["last_traded_token"]
            self.last_trade_times = state_dict["last_trade_times"]
            self.start_time = state_dict["start_time"]
            self.last_price_update = state_dict["last_price_update"]
            self.current_gas_price = state_dict["current_gas_price"]
            self.observed_tokens = set(state_dict["observed_tokens"])
            self.pattern_stats = state_dict["pattern_stats"]
            self.open_buy_orders = state_dict["open_buy_orders"]
            self.token_symbols = state_dict.get("token_symbols", {})
            self.token_addresses = state_dict.get("token_addresses", {})
            logger.info("State loaded from dictionary")

# ========== PARAMETER OPTIMIZER ==========
class ParameterOptimizer:
    def __init__(self, state: State, parameter_ranges: Optional[Dict[str, ParameterRange]] = None):
        self.state = state
        self.parameter_generator = ParameterGenerator(parameter_ranges, state.config.MAX_PARAMETER_SETS)
        self.parameter_sets = self.parameter_generator.get_parameter_sets()
        self.performance: Dict[int, Dict[str, Any]] = {}
        for i, params in enumerate(self.parameter_sets):
            self.performance[i] = {
                "profit": 0.0,
                "trades": 0,
                "winning_trades": 0,
                "parameter_set": params
            }
        self.best_set_index = 0
        self.last_optimization_time = 0
        self.optimization_interval = state.config.OPTIMIZATION_INTERVAL
        self.current_set_index = 0
        logger.info(f"ParameterOptimizer initialized with {len(self.parameter_sets)} parameter sets")

    def get_current_best_parameters(self) -> Dict[str, float]:
        if not self.parameter_sets:
            logger.warning("No parameter sets available")
            return {}
        best_index = 0
        best_score = -float('inf')
        for i, perf in self.performance.items():
            if perf["trades"] == 0:
                continue
            win_rate = perf["winning_trades"] / perf["trades"] if perf["trades"] > 0 else 0
            score = perf["profit"] * win_rate
            if score > best_score:
                best_score = score
                best_index = i
        self.best_set_index = best_index
        if best_score != -float('inf'):
            logger.info(
                f"Best parameter set #{best_index}: {self.parameter_sets[best_index]} "
                f"(Score: {best_score:.6f}, Profit: {self.performance[best_index]['profit']:.6f} ETH, "
                f"Trades: {self.performance[best_index]['trades']}, Winning: {self.performance[best_index]['winning_trades']})"
            )
        else:
            logger.warning("No valid parameter sets found (all have 0 trades)")
        return self.parameter_sets[best_index]

    def get_next_parameter_set(self) -> Tuple[int, Dict[str, float]]:
        index = self.current_set_index
        param_set = self.parameter_sets[index]
        self.current_set_index = (self.current_set_index + 1) % len(self.parameter_sets)
        logger.debug(f"Using parameter set #{index}: {param_set}")
        return index, param_set

    def update_performance(self, parameter_set_index: int, profit: float, is_winning: bool):
        if parameter_set_index in self.performance:
            self.performance[parameter_set_index]["profit"] += profit
            self.performance[parameter_set_index]["trades"] += 1
            if is_winning:
                self.performance[parameter_set_index]["winning_trades"] += 1

    def optimize(self):
        current_time = time.time()
        if current_time - self.last_optimization_time < self.optimization_interval:
            return
        logger.info("Running parameter optimization...")
        self.get_current_best_parameters()
        self.last_optimization_time = current_time

# ========== BLOCKCHAIN HELPERS ==========
class BlockchainHelper:
    def __init__(self, state: State):
        self.state = state
        self.chains = CHAINS
        self.web3_providers: Dict[str, Web3] = {}
        self.factory_contracts: Dict[str, Any] = {}
        self.pool_contracts: Dict[str, Any] = {}
        self.token_contracts: Dict[str, Any] = {}
        self._initialize_providers()

    def _test_rpc_endpoint(self, rpc_url: str) -> bool:
        try:
            if rpc_url.startswith("wss://"):
                w3 = Web3(Web3.WebsocketProvider(rpc_url, websocket_timeout=5))
            else:
                w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={'timeout': 5}))
            block_number = w3.eth.block_number
            logger.info(f"RPC endpoint {rpc_url} is working (block: {block_number})")
            return True
        except Exception as e:
            logger.warning(f"RPC endpoint {rpc_url} failed: {e}")
            return False

    def _initialize_providers(self):
        chain_key = self.state.current_chain_key
        if chain_key not in self.chains:
            logger.error(f"Chain {chain_key} not found in CHAINS configuration")
            return
        chain_config = self.chains[chain_key]
        rpc_urls = chain_config["rpcs"]
        for rpc_url in rpc_urls:
            if self._test_rpc_endpoint(rpc_url):
                provider = Web3.WebsocketProvider(rpc_url, websocket_timeout=10) if rpc_url.startswith("wss://") else Web3.HTTPProvider(rpc_url, request_kwargs={'timeout': 10})
                w3 = Web3(provider)
                if chain_key in ["polygon", "arbitrum", "base", "optimism"]:
                    w3.middleware_onion.inject(ExtraDataToPOAMiddleware(), layer=0, name="extradata_to_poa")
                self.web3_providers[chain_key] = w3
                logger.info(f"Using RPC endpoint: {rpc_url}")
                break
        else:
            logger.error(f"All RPC endpoints failed for {chain_key}")
            rpc_url = rpc_urls[0]
            provider = Web3.WebsocketProvider(rpc_url, websocket_timeout=10) if rpc_url.startswith("wss://") else Web3.HTTPProvider(rpc_url, request_kwargs={'timeout': 10})
            w3 = Web3(provider)
            if chain_key in ["polygon", "arbitrum", "base", "optimism"]:
                w3.middleware_onion.inject(ExtraDataToPOAMiddleware(), layer=0, name="extradata_to_poa")
            self.web3_providers[chain_key] = w3
            logger.warning(f"Falling back to {rpc_url} despite failure")

    def get_web3(self, chain_key: str) -> Web3:
        if chain_key not in self.web3_providers:
            logger.warning(f"Web3 provider for {chain_key} not initialized, reinitializing...")
            self._initialize_providers()
        return self.web3_providers.get(chain_key)

    async def get_factory_contract(self, chain_key: str) -> Any:
        if chain_key in self.factory_contracts:
            return self.factory_contracts[chain_key]
        w3 = self.get_web3(chain_key)
        if not w3:
            logger.error(f"No Web3 provider for {chain_key}")
            return None
        chain_config = self.chains[chain_key]
        factory_address = to_checksum_address(chain_config["factory"])
        try:
            factory_contract = w3.eth.contract(address=factory_address, abi=UNISWAP_V3_FACTORY_ABI)
            self.factory_contracts[chain_key] = factory_contract
            return factory_contract
        except Exception as e:
            logger.error(f"Failed to initialize factory contract for {chain_key}: {e}")
            return None

    async def get_pool_contract(self, pool_address: str, chain_key: str) -> Any:
        pool_address = to_checksum_address(pool_address)
        cache_key = f"{chain_key}_{pool_address}"
        if cache_key in self.pool_contracts:
            return self.pool_contracts[cache_key]
        w3 = self.get_web3(chain_key)
        if not w3:
            logger.error(f"No Web3 provider for {chain_key}")
            return None
        try:
            pool_contract = w3.eth.contract(address=pool_address, abi=UNISWAP_V3_POOL_ABI)
            self.pool_contracts[cache_key] = pool_contract
            return pool_contract
        except Exception as e:
            logger.error(f"Failed to initialize pool contract for {short(pool_address)}: {e}")
            return None

    async def get_token_contract(self, token_address: str, chain_key: str) -> Any:
        token_address = to_checksum_address(token_address)
        cache_key = f"{chain_key}_{token_address}"
        if cache_key in self.token_contracts:
            return self.token_contracts[cache_key]
        w3 = self.get_web3(chain_key)
        if not w3:
            logger.error(f"No Web3 provider for {chain_key}")
            return None
        try:
            token_contract = w3.eth.contract(address=token_address, abi=ERC20_ABI)
            self.token_contracts[cache_key] = token_contract
            return token_contract
        except Exception as e:
            logger.error(f"Failed to initialize token contract for {short(token_address)}: {e}")
            return None

    async def get_pool_address(self, token0: str, token1: str, fee: int, chain_key: str) -> Optional[str]:
        try:
            factory = await self.get_factory_contract(chain_key)
            if not factory:
                return None
            token0_checksum = to_checksum_address(token0)
            token1_checksum = to_checksum_address(token1)
            pool_address = factory.functions.getPool(token0_checksum, token1_checksum, fee).call()
            if pool_address == "0x0000000000000000000000000000000000000000":
                return None
            return pool_address
        except Exception as e:
            logger.error(f"Error getting pool address for {short(token0)}-{short(token1)}: {e}")
            return None

    async def get_pool_price(self, pool_address: str, chain_key: str) -> Optional[float]:
        try:
            pool_address_checksum = to_checksum_address(pool_address)
            pool = await self.get_pool_contract(pool_address_checksum, chain_key)
            if not pool:
                return None
            slot0 = pool.functions.slot0().call()
            sqrt_price_x96 = slot0[0]
            price = self._sqrt_price_x96_to_price(sqrt_price_x96)
            return price
        except Exception as e:
            logger.error(f"Error getting price from pool {short(pool_address)}: {e}")
            return None

    def _sqrt_price_x96_to_price(self, sqrt_price_x96: int) -> float:
        sqrt_price = sqrt_price_x96 / (2**96)
        return sqrt_price * sqrt_price

    async def get_token_decimals(self, token_address: str, chain_key: str) -> int:
        if token_address in self.state.token_decimals:
            return self.state.token_decimals[token_address]
        try:
            token_contract = await self.get_token_contract(token_address, chain_key)
            if not token_contract:
                return 18
            decimals = token_contract.functions.decimals().call()
            with self.state._lock:
                self.state.token_decimals[token_address] = decimals
            return decimals
        except Exception as e:
            logger.error(f"Error getting token decimals for {short(token_address)}: {e}")
            return 18

    async def get_token_symbol(self, token_address: str, chain_key: str) -> str:
        if token_address in self.state.token_symbols:
            return self.state.token_symbols[token_address]
        try:
            token_contract = await self.get_token_contract(token_address, chain_key)
            if not token_contract:
                return short(token_address)
            symbol = token_contract.functions.symbol().call()
            with self.state._lock:
                self.state.token_symbols[token_address] = symbol
                self.state.token_addresses[symbol] = token_address
            return symbol
        except Exception as e:
            logger.error(f"Error getting token symbol for {short(token_address)}: {e}")
            return short(token_address)

# ========== TOKEN DISCOVERY (THREAD-SAFE) ==========
class TokenDiscovery:
    def __init__(self, state: State, blockchain: BlockchainHelper):
        self.state = state
        self.blockchain = blockchain
        self.active_pools: Set[str] = set()
        self.last_block: Dict[str, int] = {}
        self.swap_topic = "0xc42079f94a6436c4e6930f05045148f3556048be474e7962b362652246f71625"

    async def initialize_known_tokens(self, chain_key: str):
        logger.info(f"Initializing known tokens for {chain_key}")
        chain_config = CHAINS[chain_key]
        wrapped_native = to_checksum_address(chain_config["wrappedNative"])
        quote_label = chain_config["quoteLabel"]

        with self.state._lock:
            if wrapped_native not in self.state.token_symbols:
                self.state.token_symbols[wrapped_native] = quote_label
                self.state.token_addresses[quote_label] = wrapped_native
            if wrapped_native not in self.state.observed_tokens:
                self.state.observed_tokens.add(wrapped_native)
            if wrapped_native not in self.state.prices:
                self.state.prices[wrapped_native] = 1.0
                self._update_price_history(wrapped_native, 1.0)

            for symbol, address in NETWORK_TOKENS.get(chain_key, {}).items():
                checksum_addr = to_checksum_address(address)
                if checksum_addr not in self.state.token_symbols:
                    self.state.token_symbols[checksum_addr] = symbol
                    self.state.token_addresses[symbol] = checksum_addr
                if checksum_addr not in self.state.observed_tokens:
                    self.state.observed_tokens.add(checksum_addr)

            for stable in chain_config.get("stables", []):
                stable = to_checksum_address(stable)
                if stable not in self.state.observed_tokens:
                    self.state.observed_tokens.add(stable)

        await self._add_top_pool_tokens(chain_key)
        await self._add_coingecko_tokens(chain_key)
        logger.info(f"Initialized {len(self.state.observed_tokens)} known tokens")

    async def _add_coingecko_tokens(self, chain_key: str):
        logger.info("Adding tokens from CoinGecko...")
        coingecko_tokens = fetch_coingecko_tokens()
        with self.state._lock:
            for token in coingecko_tokens:
                address = to_checksum_address(token["address"])
                symbol = token.get("symbol", short(address))
                if address not in self.state.observed_tokens:
                    self.state.observed_tokens.add(address)
                    self.state.token_symbols[address] = symbol
                    self.state.token_addresses[symbol] = address
        logger.info(f"Added {len(coingecko_tokens)} tokens from CoinGecko")

    async def _add_top_pool_tokens(self, chain_key: str):
        chain_config = CHAINS[chain_key]
        with self.state._lock:
            for token0, token1, _ in chain_config.get("topPools", []):
                for token_addr in [to_checksum_address(token0), to_checksum_address(token1)]:
                    if token_addr not in self.state.observed_tokens:
                        self.state.observed_tokens.add(token_addr)

    async def discover_tokens_from_blocks(self, chain_key: str, blocks_to_scan: int = 5):
        try:
            w3 = self.blockchain.get_web3(chain_key)
            if not w3:
                return
            current_block = w3.eth.block_number
            last_scanned = self.last_block.get(chain_key, current_block - blocks_to_scan)
            if current_block <= last_scanned:
                return
            from_block = max(0, current_block - blocks_to_scan)
            to_block = current_block
            try:
                logs = w3.eth.get_logs({'fromBlock': from_block, 'toBlock': to_block, 'topics': [self.swap_topic]})
            except Exception as e:
                logger.warning(f"Error fetching Swap logs: {e}")
                return
            new_tokens = set()
            for log in logs:
                try:
                    pool_address = to_checksum_address(log['address'])
                    if pool_address in self.active_pools:
                        continue
                    self.active_pools.add(pool_address)
                    pool_contract = await self.blockchain.get_pool_contract(pool_address, chain_key)
                    if not pool_contract:
                        continue
                    token0 = to_checksum_address(pool_contract.functions.token0().call())
                    token1 = to_checksum_address(pool_contract.functions.token1().call())
                    new_tokens.update([token0, token1])
                except Exception:
                    continue
            with self.state._lock:
                for token_addr in new_tokens:
                    if token_addr not in self.state.observed_tokens:
                        self.state.observed_tokens.add(token_addr)
            self.last_block[chain_key] = current_block
        except Exception as e:
            logger.error(f"Error in token discovery: {e}")

    def _update_price_history(self, token: str, price: float):
        with self.state._lock:
            if token not in self.state.price_history:
                self.state.price_history[token] = []
            self.state.price_history[token].append({"price": price, "timestamp": time.time()})
            if len(self.state.price_history[token]) > self.state.config.MAX_PRICE_HISTORY:
                self.state.price_history[token] = self.state.price_history[token][-self.state.config.MAX_PRICE_HISTORY:]

# ========== PATTERN DETECTION ==========
class PatternDetector:
    def __init__(self, state: State, optimizer: ParameterOptimizer):
        self.state = state
        self.optimizer = optimizer

    def detect_all_patterns(self):
        logger.info(f"Starting pattern detection for {len(self.state.observed_tokens)} tokens")
        tokens = list(self.state.observed_tokens)
        new_active_patterns = {}
        best_params = self.optimizer.get_current_best_parameters()
        for token in tokens:
            history = self.state.get_token_history(token)
            if history is None or len(history) < 5:
                continue
            buy_patterns = self._detect_buy_patterns(history, token, best_params)
            for pattern in buy_patterns:
                if not self._is_valid_pattern(pattern, best_params):
                    continue
                pattern_key = self._get_pattern_key(pattern)
                existing_key = f"{token}_{pattern_key}"
                if existing_key not in new_active_patterns:
                    new_active_patterns[existing_key] = {
                        **pattern,
                        "token": token,
                        "occurrences": 1,
                        "first_seen": pattern["timestamp"],
                        "last_seen": pattern["timestamp"]
                    }
                else:
                    existing = new_active_patterns[existing_key]
                    existing["occurrences"] += 1
                    existing["last_seen"] = max(existing["last_seen"], pattern["timestamp"])
        self._validate_patterns(new_active_patterns, best_params)
        with self.state._lock:
            self.state.active_patterns = new_active_patterns
        self._update_pattern_stats()
        logger.info(f"Pattern detection complete. Found {len(new_active_patterns)} active patterns")

    def _detect_buy_patterns(self, history: List[Dict[str, Any]], token: str, params: Dict[str, float]) -> List[Dict[str, Any]]:
        patterns = []
        min_change = params["MIN_PRICE_CHANGE"] / 100
        min_time = params["MIN_TIME_WINDOW"]
        max_time = params["MAX_TIME_WINDOW"]
        min_profit = params["MIN_PROFIT_PERCENT"]
        for i in range(2, len(history) - 2):
            current = history[i]
            is_minima = (
                current["price"] <= history[i - 1]["price"]
                and current["price"] <= history[i - 2]["price"]
                and current["price"] <= history[i + 1]["price"]
                and current["price"] <= history[i + 2]["price"]
            )
            if is_minima:
                for j in range(i - 1, max(0, i - 5), -1):
                    prev = history[j]
                    drop_pct = (current["price"] - prev["price"]) / prev["price"]
                    time_diff = current["timestamp"] - prev["timestamp"]
                    if drop_pct <= -min_change and min_time <= time_diff <= max_time:
                        for k in range(i + 1, min(len(history), i + 6)):
                            next_point = history[k]
                            rise_pct = (next_point["price"] - current["price"]) / current["price"]
                            rise_time = next_point["timestamp"] - current["timestamp"]
                            if rise_pct >= (min_profit / 100) and min_time <= rise_time <= max_time:
                                patterns.append({
                                    "type": "buy",
                                    "drop_pct": abs(drop_pct) * 100,
                                    "drop_time": time_diff,
                                    "rise_pct": rise_pct * 100,
                                    "rise_time": rise_time,
                                    "timestamp": current["timestamp"],
                                })
                                break
                        break
        return patterns

    def _is_valid_pattern(self, pattern: Dict[str, Any], params: Dict[str, float]) -> bool:
        if pattern["drop_pct"] > 100 or pattern["rise_pct"] > 100:
            return False
        if pattern["drop_pct"] < 0 or pattern["rise_pct"] < 0:
            return False
        if pattern["drop_time"] > 600 or pattern["rise_time"] > 600:
            return False
        if pattern["drop_time"] < 1 or pattern["rise_time"] < 1:
            return False
        if pattern["rise_pct"] < params["MIN_PROFIT_PERCENT"]:
            return False
        return True

    def _get_pattern_key(self, pattern: Dict[str, Any]) -> str:
        return (
            f"BUY_{round(pattern['drop_pct'] * 10) / 10}%"
            f"_{round(pattern['drop_time'])}s_"
            f"{round(pattern['rise_pct'] * 10) / 10}%"
            f"_{round(pattern['rise_time'])}s"
        )

    def _validate_patterns(self, patterns: Dict[str, Dict[str, Any]], params: Dict[str, float]):
        keys_to_delete = [
            key for key, pattern in patterns.items()
            if pattern["drop_pct"] <= 0 or pattern["rise_pct"] <= 0
            or pattern["rise_pct"] < params["MIN_PROFIT_PERCENT"]
        ]
        for key in keys_to_delete:
            del patterns[key]

    def _update_pattern_stats(self):
        patterns_list = list(self.state.active_patterns.values())
        with self.state._lock:
            self.state.pattern_stats["total_patterns"] = len(patterns_list)
            self.state.pattern_stats["tokens_with_patterns"] = len({p["token"] for p in patterns_list})

# ========== TRADE EXECUTION ==========
class Trader:
    def __init__(self, state: State, optimizer: ParameterOptimizer, shared_blockchain: Optional[BlockchainHelper] = None):
        self.state = state
        self.config = state.config
        self.optimizer = optimizer
        self.detector = PatternDetector(state, optimizer)
        self.blockchain = shared_blockchain if shared_blockchain else BlockchainHelper(state)
        self.token_discovery = TokenDiscovery(state, self.blockchain)
        self.live_mode = os.getenv("PRIVATE_KEY", "") != ""

    def calculate_trade_amount(self) -> float:
        try:
            gas_price = self.state.current_gas_price or self.config.MAX_GAS_PRICE
            gas_limit = self.config.GAS_LIMIT
            available_eth = self.state.portfolio["current_eth"] or self.config.STARTING_ETH
            gas_cost_per_trade = (gas_price * gas_limit * 2) / 1e9
            max_trades = self.config.MAX_TRADES
            total_gas_cost = gas_cost_per_trade * max_trades
            percent_amount = available_eth * (self.config.TRADE_AMOUNT_PERCENT / 100)
            min_trade = self.config.MIN_TRADE_AMOUNT_ETH
            amount_after_fees = percent_amount - (total_gas_cost / max_trades)
            trade_amount = max(min(percent_amount, amount_after_fees), min_trade)
            return min(trade_amount, available_eth * 0.95)
        except Exception as e:
            logger.error(f"Error calculating trade amount: {e}")
            return self.config.MIN_TRADE_AMOUNT_ETH

    def simulate_trade(self, token: str, action: str, token_amount: float, current_price: float) -> Dict[str, Any]:
        result = {
            "success": True,
            "token_amount": token_amount,
            "amount_eth": token_amount * current_price,
            "execution_price": current_price,
            "gas_used": self._estimate_gas(action, token),
            "gas_price": self.state.current_gas_price or self.config.MAX_GAS_PRICE,
            "fee_amount": 0,
            "price_impact": 0,
            "slippage": 0,
            "reason": None,
        }
        fee_tier = POOL_FEES["MEDIUM"]
        fee_percent = fee_tier / 1e6
        result["fee_amount"] = result["amount_eth"] * fee_percent
        result["price_impact"] = self._calculate_price_impact(token, token_amount)
        result["slippage"] = result["price_impact"] + random.uniform(0, 0.1)
        if result["slippage"] > self.config.MAX_SLIPPAGE:
            result["success"] = False
            result["reason"] = f"Slippage too high: {result['slippage']:.4f}% > {self.config.MAX_SLIPPAGE}%"
            return result
        if action == "buy":
            result["execution_price"] = current_price * (1 + result["slippage"] / 100)
        else:
            result["execution_price"] = current_price * (1 - result["slippage"] / 100)
        result["amount_eth"] = token_amount * result["execution_price"]
        if action == "buy":
            result["token_amount"] = result["amount_eth"] / result["execution_price"]
        return result

    def _estimate_gas(self, action: str, token: str) -> int:
        base_gas = 120000
        if token in ["WBTC", "ETH"]:
            base_gas += 20000
        elif token in ["UNI", "LINK"]:
            base_gas += 8000
        else:
            base_gas += 5000
        if action == "buy":
            base_gas += 10000
        base_gas += random.randint(0, 15000)
        return min(base_gas, self.config.GAS_LIMIT)

    def _calculate_price_impact(self, token: str, token_amount: float) -> float:
        token_price = self.state.get_token_price(token) or 1.0
        token_value_eth = token_amount * token_price
        liquidity_eth = 100000
        return min((token_value_eth / liquidity_eth) * 100, 2.0)

    def create_trade(
        self, token: str, action: str, price: float, token_amount: float, amount_eth: float,
        pattern: str, status: str, reason: Optional[str] = None,
        parameter_set_index: Optional[int] = None, **kwargs
    ) -> Dict[str, Any]:
        return {
            "id": f"trade_{int(time.time())}_{random.randint(1000, 9999)}",
            "timestamp": datetime.now().isoformat(),
            "token": token,
            "type": action,
            "price": price,
            "token_amount": token_amount,
            "amount_eth": amount_eth,
            "fee": kwargs.get("fee_amount", 0),
            "gas_used": kwargs.get("gas_used", 0),
            "gas_price": kwargs.get("gas_price", self.state.current_gas_price),
            "price_impact": kwargs.get("price_impact", 0),
            "slippage": kwargs.get("slippage", 0),
            "status": status,
            "reason": reason,
            "pnl": 0,
            "pattern": pattern,
            "parameter_set_index": parameter_set_index,
            "network": self.state.current_network,
        }

    def update_portfolio(self, trade: Dict[str, Any], action: str, trade_result: Dict[str, Any]):
        token = trade["token"]
        gas_cost_eth = trade_result["gas_used"] * trade_result["gas_price"] / 1e9
        fee_cost_eth = trade_result["fee_amount"]
        total_cost_eth = gas_cost_eth + fee_cost_eth

        if action == "buy":
            eth_balance = self.state.portfolio["balances"].get("ETH", 0)
            total_trade_cost = trade_result["amount_eth"] + total_cost_eth
            if eth_balance < total_trade_cost:
                trade["status"] = "failed"
                trade["reason"] = "Insufficient ETH (including fees)"
                with self.state._lock:
                    self.state.portfolio["failed_trades"] += 1
                    self.state.trades.append(trade)
                return
            with self.state._lock:
                self.state.portfolio["balances"]["ETH"] = eth_balance - total_trade_cost
                if token not in self.state.portfolio["balances"]:
                    self.state.portfolio["balances"][token] = 0
                self.state.portfolio["balances"][token] += trade_result["token_amount"]
                position = next(
                    (p for p in self.state.portfolio["positions"] if p["token"] == token and p["status"] == "open"),
                    None,
                )
                if not position:
                    position = {
                        "token": token,
                        "entry_price": trade_result["execution_price"],
                        "amount": trade_result["token_amount"],
                        "usd_value": trade_result["amount_eth"],
                        "entry_time": time.time(),
                        "gas_paid": gas_cost_eth,
                        "fees_paid": fee_cost_eth,
                        "status": "open",
                        "trade_id": trade["id"],
                        "pattern": trade["pattern"],
                        "parameter_set_index": trade.get("parameter_set_index")
                    }
                    self.state.portfolio["positions"].append(position)
                else:
                    position["amount"] += trade_result["token_amount"]
                    position["usd_value"] += trade_result["amount_eth"]
                    position["gas_paid"] += gas_cost_eth
                    position["fees_paid"] += fee_cost_eth
                self.state.portfolio["gas_spent"] += gas_cost_eth
                self.state.portfolio["fees_paid"] += fee_cost_eth
                self.state.portfolio["total_fees"] += total_cost_eth
        elif action == "sell":
            with self.state._lock:
                open_positions = sorted(
                    [p for p in self.state.portfolio["positions"] if p["token"] == token and p["status"] == "open"],
                    key=lambda x: x["entry_time"],
                )
                if not open_positions:
                    trade["status"] = "failed"
                    trade["reason"] = "No open position to sell"
                    self.state.portfolio["failed_trades"] += 1
                    self.state.trades.append(trade)
                    return
                position = open_positions[0]
                amount_to_sell = min(trade_result["token_amount"], position["amount"])
                sell_value_eth = amount_to_sell * trade_result["execution_price"]
                cost_basis = (amount_to_sell * position["entry_price"]) + (
                    (amount_to_sell / position["amount"]) * (position["fees_paid"] + position["gas_paid"])
                )
                pnl = sell_value_eth - cost_basis - total_cost_eth
                trade["pnl"] = pnl
                position["amount"] -= amount_to_sell
                position["fees_paid"] += fee_cost_eth
                position["gas_paid"] += gas_cost_eth
                if position["amount"] <= 0.000001:
                    position["status"] = "closed"
                    position["exit_price"] = trade_result["execution_price"]
                    position["exit_time"] = time.time()
                    position["pnl"] = pnl
                    position["sell_trade_id"] = trade["id"]
                    self.state.portfolio["realized_pnl"] += pnl
                    if pnl > 0:
                        self.state.portfolio["winning_trades"] += 1
                    elif pnl < 0:
                        self.state.portfolio["losing_trades"] += 1
                self.state.portfolio["balances"]["ETH"] = self.state.portfolio["balances"].get("ETH", 0) + (
                    sell_value_eth - total_cost_eth
                )
                if token in self.state.portfolio["balances"]:
                    self.state.portfolio["balances"][token] -= amount_to_sell
                    if self.state.portfolio["balances"][token] < 0.000001:
                        del self.state.portfolio["balances"][token]
                self.state.portfolio["gas_spent"] += gas_cost_eth
                self.state.portfolio["fees_paid"] += fee_cost_eth
                self.state.portfolio["total_fees"] += total_cost_eth
        self._update_portfolio_equity()
        trade["status"] = "closed" if action == "sell" else "open"
        with self.state._lock:
            self.state.trades.append(trade)
        if "parameter_set_index" in trade:
            self.optimizer.update_performance(
                trade["parameter_set_index"],
                trade.get("pnl", 0),
                trade.get("pnl", 0) > 0
            )

    def _update_portfolio_equity(self):
        total_eth = self.state.portfolio["balances"].get("ETH", 0)
        for token, amount in self.state.portfolio["balances"].items():
            if token == "ETH":
                continue
            price_in_eth = self.state.get_token_price(token)
            if price_in_eth is not None:
                total_eth += amount * price_in_eth
        for position in self.state.portfolio["positions"]:
            if position["status"] == "open":
                current_price = self.state.get_token_price(position["token"]) or position["entry_price"]
                current_value = position["amount"] * current_price
                unrealized_pnl = (
                    current_value - (position["amount"] * position["entry_price"]) - position["fees_paid"] - position["gas_paid"]
                )
                total_eth += unrealized_pnl
        with self.state._lock:
            self.state.portfolio["current_eth"] = total_eth
            self.state.portfolio["unrealized_pnl"] = (
                total_eth - self.state.portfolio["starting_eth"] - self.state.portfolio["realized_pnl"]
            )
            self.state.portfolio["equity_history"].append({"timestamp": time.time(), "eth_value": total_eth})
            if len(self.state.portfolio["equity_history"]) > 1000:
                self.state.portfolio["equity_history"] = self.state.portfolio["equity_history"][-1000:]

    async def execute_trade(
        self, token: str, action: str, pattern_desc: str = "Manual",
        amount_eth: Optional[float] = None, pattern: Optional[Dict[str, Any]] = None,
        parameter_set_index: Optional[int] = None
    ) -> Optional[Dict[str, Any]]:
        if not self.state.is_running:
            return None
        if amount_eth is None:
            amount_eth = self.calculate_trade_amount()
        current_price = self.state.get_token_price(token)
        if current_price is None:
            return None
        if amount_eth <= 0:
            return None
        open_positions = len([p for p in self.state.portfolio["positions"] if p["status"] == "open"])
        if open_positions >= self.config.MAX_TRADES:
            return None
        last_trade_time = self.state.last_trade_times.get(token)
        if last_trade_time and (time.time() - last_trade_time) < self.config.TRADE_COOLDOWN:
            return None
        if self.state.current_gas_price > self.config.MAX_GAS_PRICE:
            return None
        if action == "sell":
            with self.state._lock:
                token_balance = self.state.portfolio["balances"].get(token, 0)
            if token_balance <= 0:
                return None
        token_amount = amount_eth / current_price
        trade_result = self.simulate_trade(token, action, token_amount, current_price)
        if not trade_result["success"]:
            failed_trade = self.create_trade(
                token, action, current_price, token_amount, amount_eth, pattern_desc,
                "failed", trade_result["reason"], parameter_set_index, **trade_result
            )
            with self.state._lock:
                self.state.trades.append(failed_trade)
                self.state.portfolio["failed_trades"] += 1
                self.state.portfolio["total_trades"] += 1
            return failed_trade
        if self.config.PREVENT_SEQUENTIAL_TRADES and self.state.last_traded_token == token:
            return None
        token_amount = trade_result["token_amount"]
        trade = self.create_trade(
            token, action, trade_result["execution_price"], token_amount,
            trade_result["amount_eth"], pattern_desc, "open", parameter_set_index=parameter_set_index, **trade_result
        )
        self.update_portfolio(trade, action, trade_result)
        with self.state._lock:
            self.state.portfolio["total_trades"] += 1
            self.state.last_traded_token = token
            self.state.last_trade_times[token] = time.time()
        if action == "buy":
            with self.state._lock:
                self.state.open_buy_orders[token] = {
                    "trade_id": trade["id"],
                    "pattern": pattern,
                    "entry_price": trade_result["execution_price"],
                    "entry_time": time.time(),
                    "parameter_set_index": parameter_set_index,
                }
        if action == "sell":
            with self.state._lock:
                if token in self.state.open_buy_orders:
                    del self.state.open_buy_orders[token]
        return trade

    async def check_patterns_for_token(self, token: str):
        if not self.state.is_running:
            return
        history = self.state.get_token_history(token)
        if history is None or len(history) < 2:
            return
        current_price = self.state.get_token_price(token)
        if current_price is None:
            return
        best_params = self.optimizer.get_current_best_parameters()
        with self.state._lock:
            open_position = next(
                (p for p in self.state.portfolio["positions"] if p["token"] == token and p["status"] == "open"),
                None,
            )
        if open_position:
            current_value = open_position["amount"] * current_price
            cost_basis = (open_position["amount"] * open_position["entry_price"]) + open_position["fees_paid"] + open_position["gas_paid"]
            profit_eth = current_value - cost_basis
            profit_pct = (profit_eth / cost_basis) * 100 if cost_basis > 0 else 0
            if profit_pct >= best_params["MIN_PROFIT_PERCENT"] and profit_eth > 0:
                sell_amount_eth = open_position["amount"] * current_price
                parameter_set_index = open_position.get("parameter_set_index", 0)
                await self.execute_trade(
                    token, "sell", f"Profit target ({profit_pct:.2f}%) reached",
                    sell_amount_eth, None, parameter_set_index
                )
                return
        token_patterns = [p for p in self.state.active_patterns.values() if p["token"] == token]
        buy_patterns = [p for p in token_patterns if p["type"] == "buy"]
        for pattern in buy_patterns:
            if self._check_pattern_match(token, pattern):
                if self.config.PREVENT_SEQUENTIAL_TRADES and self.state.last_traded_token == token:
                    continue
                with self.state._lock:
                    if token in self.state.open_buy_orders:
                        continue
                trade_amount = self.calculate_trade_amount()
                await self.execute_trade(
                    token, "buy", f"Buy dip: {pattern['drop_pct']:.2f}% drop, {pattern['rise_pct']:.2f}% target",
                    trade_amount, pattern, pattern.get("parameter_set_index")
                )

    def _check_pattern_match(self, token: str, pattern: Dict[str, Any]) -> bool:
        history = self.state.get_token_history(token)
        if history is None or len(history) < 2:
            return False
        current_price = self.state.get_token_price(token)
        if current_price is None:
            return False
        recent_history = history[-10:]
        for i in range(len(recent_history) - 1, -1, -1):
            current = recent_history[i]
            for j in range(i - 1, max(0, i - 5), -1):
                prev = recent_history[j]
                drop_pct = (current["price"] - prev["price"]) / prev["price"]
                time_diff = current["timestamp"] - prev["timestamp"]
                if (
                    abs(drop_pct) >= pattern["drop_pct"] / 100
                    and pattern["drop_time"] - 2 <= time_diff <= pattern["drop_time"] + 2
                ):
                    price_diff = abs(current_price - current["price"]) / current["price"]
                    if price_diff < 0.02:
                        return True
        return False

    def start_pattern_detection(self):
        if self.state.pattern_detection_active:
            return
        self.state.pattern_detection_active = True
        self.detector.detect_all_patterns()
        def loop():
            while self.state.is_running and self.state.pattern_detection_active:
                self.detector.detect_all_patterns()
                self.optimizer.optimize()
                time.sleep(3)
        threading.Thread(target=loop, daemon=True).start()

    def stop_pattern_detection(self):
        self.state.pattern_detection_active = False

# ========== PRICE UPDATER (THREAD-SAFE) ==========
class PriceUpdater:
    def __init__(self, state: State, shared_blockchain: Optional[BlockchainHelper] = None):
        self.state = state
        self.blockchain = shared_blockchain if shared_blockchain else BlockchainHelper(state)
        self.token_discovery = TokenDiscovery(state, self.blockchain)
        self.price_update_lock = threading.Lock()
        self.last_price_update: Dict[str, float] = {}

    async def update_prices(self):
        with self.price_update_lock:
            try:
                chain_key = self.state.current_network
                chain_config = CHAINS[chain_key]
                w3 = self.blockchain.get_web3(chain_key)
                if not w3:
                    return
                try:
                    gas_price_wei = w3.eth.gas_price
                    with self.state._lock:
                        self.state.current_gas_price = gas_price_wei / 1e9
                except Exception as e:
                    with self.state._lock:
                        self.state.current_gas_price = self.state.config.MAX_GAS_PRICE
                wrapped_native = to_checksum_address(chain_config["wrappedNative"])
                with self.state._lock:
                    if not self.state.observed_tokens:
                        self.token_discovery.initialize_known_tokens(chain_key)
                await self.token_discovery.discover_tokens_from_blocks(chain_key, blocks_to_scan=5)
                current_time = time.time()
                with self.state._lock:
                    tokens_to_update = list(self.state.observed_tokens)
                for token in tokens_to_update:
                    try:
                        if norm(token) == norm(wrapped_native):
                            with self.state._lock:
                                self.state.prices[token] = 1.0
                                self.token_discovery._update_price_history(token, 1.0)
                                self.last_price_update[token] = current_time
                            continue
                        price = await self._get_price_for_token(token, chain_key)
                        if price is not None:
                            with self.state._lock:
                                self.state.prices[token] = price
                                self.token_discovery._update_price_history(token, price)
                                self.last_price_update[token] = current_time
                    except Exception as e:
                        continue
                with self.state._lock:
                    self.state.last_price_update = current_time
            except Exception as e:
                logger.error(f"Error in price update: {e}")

    async def _get_price_for_token(self, token: str, chain_key: str) -> Optional[float]:
        chain_config = CHAINS[chain_key]
        wrapped_native = to_checksum_address(chain_config["wrappedNative"])
        token_checksum = to_checksum_address(token)
        for fee in [POOL_FEES["MEDIUM"], POOL_FEES["LOW"], POOL_FEES["HIGH"]]:
            try:
                pool_address = await self.blockchain.get_pool_address(token_checksum, wrapped_native, fee, chain_key)
                if pool_address:
                    price = await self.blockchain.get_pool_price(pool_address, chain_key)
                    if price is not None:
                        return price
            except Exception:
                continue
        return None

# ========== STATE PERSISTENCE (INCREMENTAL + TXT FILES) ==========
class StateManager:
    def __init__(self, state: State, data_dir: str = "data"):
        self.state = state
        self.data_dir = data_dir
        self.db_path = os.path.join(data_dir, "state.db")
        self.max_backups = 100
        self.last_component_hashes: Dict[str, str] = {
            "config": "",
            "prices": "",
            "portfolio": "",
            "trades": "",
            "patterns": "",
            "misc": ""
        }
        os.makedirs(data_dir, exist_ok=True)
        self._init_db()
        self._cleanup_old_states()

    def _init_db(self):
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS state_config (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL DEFAULT (datetime('now')),
                        config_data TEXT NOT NULL
                    )
                ''')
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS state_prices (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL DEFAULT (datetime('now')),
                        prices_data TEXT NOT NULL,
                        price_history_data TEXT NOT NULL
                    )
                ''')
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS state_portfolio (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL DEFAULT (datetime('now')),
                        portfolio_data TEXT NOT NULL
                    )
                ''')
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS state_trades (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL DEFAULT (datetime('now')),
                        trades_data TEXT NOT NULL
                    )
                ''')
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS state_patterns (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL DEFAULT (datetime('now')),
                        patterns_data TEXT NOT NULL,
                        pattern_stats_data TEXT NOT NULL
                    )
                ''')
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS state_misc (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL DEFAULT (datetime('now')),
                        misc_data TEXT NOT NULL
                    )
                ''')
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS bot_state (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL DEFAULT (datetime('now')),
                        state_data TEXT NOT NULL,
                        version INTEGER DEFAULT 1
                    )
                ''')
                conn.commit()
        except Exception as e:
            logger.error(f"Error initializing SQLite database: {e}")

    def _cleanup_old_states(self):
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                for table in ["bot_state", "state_config", "state_prices", "state_portfolio", "state_trades", "state_patterns", "state_misc"]:
                    cursor.execute(f'''
                        DELETE FROM {table}
                        WHERE id NOT IN (
                            SELECT id FROM {table}
                            ORDER BY timestamp DESC
                            LIMIT ?
                        )
                    ''', (self.max_backups,))
                conn.commit()
        except Exception as e:
            logger.error(f"Error cleaning up old states: {e}")

    def save_state(self):
        try:
            state_dict = self.state.to_dict()
            self._save_component("config", {"config": asdict(self.state.config)})
            self._save_component("prices", {
                "prices": state_dict["prices"],
                "price_history": {k: v for k, v in state_dict["price_history"].items()}
            })
            self._save_component("portfolio", state_dict["portfolio"])
            self._save_component("trades", state_dict["trades"])
            self._save_component("patterns", {
                "active_patterns": state_dict["active_patterns"],
                "pattern_stats": state_dict["pattern_stats"]
            })
            self._save_component("misc", {
                "is_running": state_dict["is_running"],
                "current_network": state_dict["current_network"],
                "last_traded_token": state_dict["last_traded_token"],
                "last_trade_times": state_dict["last_trade_times"],
                "start_time": state_dict["start_time"],
                "last_price_update": state_dict["last_price_update"],
                "current_gas_price": state_dict["current_gas_price"],
                "observed_tokens": list(state_dict["observed_tokens"]),
                "open_buy_orders": state_dict["open_buy_orders"],
                "token_symbols": state_dict["token_symbols"],
                "token_addresses": state_dict["token_addresses"],
                "timestamp": state_dict["timestamp"]
            })
            state_json = json.dumps(state_dict, default=str, indent=2)
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO bot_state (state_data, timestamp)
                    VALUES (?, datetime('now'))
                ''', (state_json,))
                conn.commit()
                self._cleanup_old_states()
        except Exception as e:
            logger.error(f"Error saving state to SQLite: {e}")

    def _save_component(self, component_name: str, data: Any):
        try:
            if component_name == "prices":
                prices_data = json.dumps(data.get("prices", {}), default=str, indent=2)
                price_history_data = json.dumps(data.get("price_history", {}), default=str, indent=2)
                data_hash = hashlib.md5((prices_data + price_history_data).encode()).hexdigest()
                if data_hash == self.last_component_hashes[component_name]:
                    return
                with sqlite3.connect(self.db_path) as conn:
                    cursor = conn.cursor()
                    cursor.execute('''
                        INSERT INTO state_prices (timestamp, prices_data, price_history_data)
                        VALUES (datetime('now'), ?, ?)
                    ''', (prices_data, price_history_data))
                    conn.commit()
                    self.last_component_hashes[component_name] = data_hash

            elif component_name == "patterns":
                patterns_data = json.dumps(data.get("active_patterns", {}), default=str, indent=2)
                pattern_stats_data = json.dumps(data.get("pattern_stats", {}), default=str, indent=2)
                data_hash = hashlib.md5((patterns_data + pattern_stats_data).encode()).hexdigest()
                if data_hash == self.last_component_hashes[component_name]:
                    return
                with sqlite3.connect(self.db_path) as conn:
                    cursor = conn.cursor()
                    cursor.execute('''
                        INSERT INTO state_patterns (timestamp, patterns_data, pattern_stats_data)
                        VALUES (datetime('now'), ?, ?)
                    ''', (patterns_data, pattern_stats_data))
                    conn.commit()
                    self.last_component_hashes[component_name] = data_hash

            else:
                data_json = json.dumps(data, default=str, indent=2)
                data_hash = hashlib.md5(data_json.encode()).hexdigest()
                if data_hash == self.last_component_hashes[component_name]:
                    return
                table_name = f"state_{component_name}"
                column_name = f"{component_name}_data"
                with sqlite3.connect(self.db_path) as conn:
                    cursor = conn.cursor()
                    cursor.execute(f'''
                        INSERT INTO {table_name} (timestamp, {column_name})
                        VALUES (datetime('now'), ?)
                    ''', (data_json,))
                    conn.commit()
                    self.last_component_hashes[component_name] = data_hash
        except Exception as e:
            logger.error(f"Error saving component {component_name} to SQLite: {e}")

    def emit_state_files(self):
        try:
            os.makedirs(self.data_dir, exist_ok=True)
            with open(os.path.join(self.data_dir, "prices.txt"), "w") as f:
                f.write("=== Current Token Prices ===\n")
                f.write(f"Last Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                with self.state._lock:
                    for token, price in sorted(self.state.prices.items()):
                        symbol = self.state.get_token_symbol(token)
                        f.write(f"{symbol}: {price:.8f} ETH\n")
            with open(os.path.join(self.data_dir, "holdings.txt"), "w") as f:
                f.write("=== Portfolio Balances ===\n")
                f.write(f"Last Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                f.write("Balances:\n")
                with self.state._lock:
                    for token, amount in self.state.portfolio["balances"].items():
                        symbol = self.state.get_token_symbol(token)
                        f.write(f"  {symbol}: {amount:.12f}\n")
                    f.write("\nOpen Positions:\n")
                    for pos in self.state.portfolio["positions"]:
                        if pos["status"] == "open":
                            symbol = self.state.get_token_symbol(pos["token"])
                            current_price = self.state.get_token_price(pos["token"]) or pos["entry_price"]
                            current_value = pos["amount"] * current_price
                            f.write(f"  {symbol}: {pos['amount']:.12f} @ {pos['entry_price']:.8f} ETH (Value: {current_value:.12f} ETH)\n")
            with open(os.path.join(self.data_dir, "pnl.txt"), "w") as f:
                f.write("=== Profit & Loss ===\n")
                f.write(f"Last Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                with self.state._lock:
                    f.write(f"Starting ETH: {self.state.portfolio['starting_eth']:.12f} ETH\n")
                    f.write(f"Current ETH: {self.state.portfolio['current_eth']:.12f} ETH\n")
                    f.write(f"Realized PnL: {self.state.portfolio['realized_pnl']:.12f} ETH\n")
                    f.write(f"Unrealized PnL: {self.state.portfolio['unrealized_pnl']:.12f} ETH\n")
                    total_pnl = self.state.portfolio['realized_pnl'] + self.state.portfolio['unrealized_pnl']
                    f.write(f"Total PnL: {total_pnl:.12f} ETH\n")
                    if self.state.portfolio['starting_eth'] > 0:
                        return_pct = (total_pnl / self.state.portfolio['starting_eth']) * 100
                        f.write(f"Return: {return_pct:.2f}%\n")
        except Exception as e:
            logger.error(f"Error emitting state files: {e}")

    def load_state(self) -> bool:
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                state_dict = {}
                cursor.execute('SELECT config_data FROM state_config ORDER BY timestamp DESC LIMIT 1')
                result = cursor.fetchone()
                if result:
                    state_dict["config"] = json.loads(result[0])["config"]
                cursor.execute('SELECT prices_data, price_history_data FROM state_prices ORDER BY timestamp DESC LIMIT 1')
                result = cursor.fetchone()
                if result:
                    state_dict["prices"] = json.loads(result[0])
                    state_dict["price_history"] = json.loads(result[1])
                cursor.execute('SELECT portfolio_data FROM state_portfolio ORDER BY timestamp DESC LIMIT 1')
                result = cursor.fetchone()
                if result:
                    state_dict["portfolio"] = json.loads(result[0])
                cursor.execute('SELECT trades_data FROM state_trades ORDER BY timestamp DESC LIMIT 1')
                result = cursor.fetchone()
                if result:
                    state_dict["trades"] = json.loads(result[0])
                cursor.execute('SELECT patterns_data, pattern_stats_data FROM state_patterns ORDER BY timestamp DESC LIMIT 1')
                result = cursor.fetchone()
                if result:
                    state_dict["active_patterns"] = json.loads(result[0])
                    state_dict["pattern_stats"] = json.loads(result[1])
                cursor.execute('SELECT misc_data FROM state_misc ORDER BY timestamp DESC LIMIT 1')
                result = cursor.fetchone()
                if result:
                    misc_data = json.loads(result[0])
                    for key, value in misc_data.items():
                        state_dict[key] = value
                if state_dict:
                    if "observed_tokens" in state_dict and isinstance(state_dict["observed_tokens"], list):
                        state_dict["observed_tokens"] = set(state_dict["observed_tokens"])
                    self.state.from_dict(state_dict)
                    return True
            return False
        except Exception as e:
            logger.error(f"Error loading state from SQLite: {e}")
            return False

# ========== SIMULATOR (Parallel Parameter Set) ==========
class Simulator:
    def __init__(self, param_set_index: int, param_set: Dict[str, float],
                 shared_state: State, shared_blockchain: BlockchainHelper, base_data_dir: str = "data"):
        self.param_set_index = param_set_index
        self.param_set = param_set
        self.shared_state = shared_state
        self.shared_blockchain = shared_blockchain
        self.data_dir = os.path.join(base_data_dir, f"param_set_{param_set_index}")
        os.makedirs(self.data_dir, exist_ok=True)

        # Initialize config with this parameter set
        self.config = Config()
        for key, value in param_set.items():
            setattr(self.config, key, value)

        # Initialize isolated state
        self.state = State(self.config)
        # Reference shared blockchain data (read-only)
        self.state.prices = shared_state.prices
        self.state.price_history = shared_state.price_history
        self.state.observed_tokens = shared_state.observed_tokens
        self.state.token_symbols = shared_state.token_symbols
        self.state.token_addresses = shared_state.token_addresses
        self.state.token_decimals = shared_state.token_decimals
        self.state.current_gas_price = shared_state.current_gas_price
        self.state.last_price_update = shared_state.last_price_update

        # Initialize optimizer with just this parameter set
        self.optimizer = ParameterOptimizer(self.state, {})
        self.optimizer.parameter_sets = [param_set]
        self.optimizer.current_set_index = 0

        # Initialize trader with shared blockchain helper
        self.trader = Trader(self.state, self.optimizer, self.shared_blockchain)
        self.price_updater = PriceUpdater(self.state, self.shared_blockchain)
        self.state_manager = StateManager(self.state, self.data_dir)

        self.running = False
        self.thread = None
        self._event_loop = None
        self._event_loop_thread = None

    def _start_event_loop(self):
        if self._event_loop is not None:
            return
        def run_loop():
            self._event_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._event_loop)
            self._event_loop.run_forever()
        self._event_loop_thread = threading.Thread(target=run_loop, daemon=True)
        self._event_loop_thread.start()
        time.sleep(0.1)

    def _stop_event_loop(self):
        if self._event_loop is not None:
            self._event_loop.call_soon_threadsafe(self._event_loop.stop)
            if self._event_loop_thread:
                self._event_loop_thread.join(timeout=1)
            self._event_loop = None
            self._event_loop_thread = None

    def start(self):
        if self.running:
            return
        self.running = True
        self.state.is_running = True
        self.state.start_time = time.time()
        self._start_event_loop()

        # Initialize known tokens (only once, shared across all simulators)
        asyncio.run_coroutine_threadsafe(
            self.trader.token_discovery.initialize_known_tokens(self.state.current_chain_key),
            self._event_loop
        )

        # Start pattern detection
        self.trader.start_pattern_detection()

        # Start trade checking
        async def trade_loop():
            while self.running:
                with self.shared_state._lock:
                    tokens = list(self.shared_state.observed_tokens)
                for token in tokens:
                    await self.trader.check_patterns_for_token(token)
                await asyncio.sleep(1)
        asyncio.run_coroutine_threadsafe(trade_loop(), self._event_loop)

        # Start state saving
        def state_saver():
            while self.running:
                self.state_manager.save_state()
                self.state_manager.emit_state_files()
                time.sleep(30)
        threading.Thread(target=state_saver, daemon=True).start()

    def stop(self):
        if not self.running:
            return
        self.running = False
        self.state.is_running = False
        self.trader.stop_pattern_detection()
        self._stop_event_loop()
        self.state_manager.save_state()
        self.state_manager.emit_state_files()

    def get_status(self) -> Dict[str, Any]:
        with self.state._lock:
            net_pnl = self.state.portfolio["realized_pnl"] + self.state.portfolio["unrealized_pnl"]
            successful_trades = self.state.portfolio["winning_trades"] + self.state.portfolio["losing_trades"]
            win_rate = (self.state.portfolio["winning_trades"] / successful_trades * 100) if successful_trades > 0 else 0
            return {
                "param_set_index": self.param_set_index,
                "param_set": self.param_set,
                "is_running": self.state.is_running,
                "current_eth": self.state.portfolio["current_eth"],
                "realized_pnl": self.state.portfolio["realized_pnl"],
                "unrealized_pnl": self.state.portfolio["unrealized_pnl"],
                "net_pnl": net_pnl,
                "portfolio_return": (net_pnl / self.state.portfolio["starting_eth"] * 100) if self.state.portfolio["starting_eth"] > 0 else 0,
                "total_trades": self.state.portfolio["total_trades"],
                "winning_trades": self.state.portfolio["winning_trades"],
                "losing_trades": self.state.portfolio["losing_trades"],
                "failed_trades": self.state.portfolio["failed_trades"],
                "win_rate": win_rate,
                "open_positions": len([p for p in self.state.portfolio["positions"] if p["status"] == "open"]),
                "data_dir": self.data_dir,
            }

# ========== MAIN BOT CLASS ==========
class Bot:
    def __init__(self, config: Optional[Config] = None, parameter_ranges: Optional[Dict[str, ParameterRange]] = None):
        self.config = config or Config()
        self.parameter_ranges = parameter_ranges or DEFAULT_PARAMETER_RANGES
        self.parameter_generator = ParameterGenerator(self.parameter_ranges, self.config.MAX_PARAMETER_SETS)
        self.parameter_sets = self.parameter_generator.get_parameter_sets()

        # Shared state for blockchain data (prices, tokens, etc.)
        self.shared_state = State(self.config)
        self.shared_blockchain = BlockchainHelper(self.shared_state)

        # In non-live mode, create a simulator for each parameter set
        self.live_mode = os.getenv("PRIVATE_KEY", "") != ""
        self.simulators: List[Simulator] = []

        if not self.live_mode:
            for i, param_set in enumerate(self.parameter_sets):
                simulator = Simulator(
                    param_set_index=i,
                    param_set=param_set,
                    shared_state=self.shared_state,
                    shared_blockchain=self.shared_blockchain,
                    base_data_dir="data"
                )
                self.simulators.append(simulator)
            logger.info(f"Initialized {len(self.simulators)} parallel parameter set simulators")
        else:
            # Live mode: use a single state and trader
            self.state = State(self.config)
            self.optimizer = ParameterOptimizer(self.state, self.parameter_ranges)
            self.trader = Trader(self.state, self.optimizer)
            self.price_updater = PriceUpdater(self.state)
            self.state_manager = StateManager(self.state)
            logger.info("Running in LIVE MODE (single parameter set)")

        self.running = False
        self._event_loop = None
        self._event_loop_thread = None

    def _start_event_loop(self):
        if self._event_loop is not None:
            return
        def run_loop():
            self._event_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._event_loop)
            self._event_loop.run_forever()
        self._event_loop_thread = threading.Thread(target=run_loop, daemon=True)
        self._event_loop_thread.start()
        time.sleep(0.1)

    def _stop_event_loop(self):
        if self._event_loop is not None:
            self._event_loop.call_soon_threadsafe(self._event_loop.stop)
            if self._event_loop_thread:
                self._event_loop_thread.join(timeout=1)
            self._event_loop = None
            self._event_loop_thread = None

    def start(self):
        if self.running:
            logger.info("Bot is already running")
            return

        logger.info("Starting Uniswap Quick Swap Trader...")
        self._start_event_loop()
        self.running = True

        if not self.live_mode:
            # Start all simulators in parallel
            logger.info(f"Starting {len(self.simulators)} parallel parameter set simulations")
            for simulator in self.simulators:
                simulator.start()

            # Start shared price updates
            async def shared_price_loop():
                while self.running:
                    await self._update_shared_prices()
                    await asyncio.sleep(10)
            asyncio.run_coroutine_threadsafe(shared_price_loop(), self._event_loop)
        else:
            # Live mode: original behavior
            self.state.is_running = True
            self.state.start_time = time.time()

            asyncio.run_coroutine_threadsafe(
                self.trader.token_discovery.initialize_known_tokens(self.state.current_chain_key),
                self._event_loop
            )

            async def price_loop():
                while self.running:
                    await self.price_updater.update_prices()
                    await asyncio.sleep(10)
            asyncio.run_coroutine_threadsafe(price_loop(), self._event_loop)

            self.trader.start_pattern_detection()

            def state_saver():
                while self.running:
                    self.state_manager.save_state()
                    self.state_manager.emit_state_files()
                    time.sleep(30)
            threading.Thread(target=state_saver, daemon=True).start()

            async def pattern_checker():
                while self.running:
                    with self.state._lock:
                        tokens = list(self.state.observed_tokens)
                    for token in tokens:
                        await self.trader.check_patterns_for_token(token)
                    await asyncio.sleep(1)
            asyncio.run_coroutine_threadsafe(pattern_checker(), self._event_loop)

        logger.info("Bot started! Press Ctrl+C to stop.")
        logger.info("Commands: start, stop, status, prices, params, reset, help")
        self._interactive_loop()

    async def _update_shared_prices(self):
        """Update shared prices for all simulators."""
        try:
            chain_key = self.shared_state.current_network
            chain_config = CHAINS[chain_key]
            w3 = self.shared_blockchain.get_web3(chain_key)
            if not w3:
                return
            try:
                gas_price_wei = w3.eth.gas_price
                with self.shared_state._lock:
                    self.shared_state.current_gas_price = gas_price_wei / 1e9
            except Exception:
                with self.shared_state._lock:
                    self.shared_state.current_gas_price = self.config.MAX_GAS_PRICE

            # Update prices in shared state
            with self.shared_state._lock:
                if not self.shared_state.observed_tokens:
                    self.shared_blockchain.token_discovery.initialize_known_tokens(chain_key)
            await self.shared_blockchain.token_discovery.discover_tokens_from_blocks(chain_key, blocks_to_scan=5)

            current_time = time.time()
            with self.shared_state._lock:
                tokens_to_update = list(self.shared_state.observed_tokens)
            for token in tokens_to_update:
                price = await self._get_price_for_token(token, chain_key)
                if price is not None:
                    with self.shared_state._lock:
                        self.shared_state.prices[token] = price
                        self.shared_blockchain.token_discovery._update_price_history(token, price)
                        self.shared_blockchain.token_discovery.last_price_update[token] = current_time

            # Propagate shared prices to all simulators
            with self.shared_state._lock:
                for simulator in self.simulators:
                    simulator.state.current_gas_price = self.shared_state.current_gas_price
                    simulator.state.last_price_update = current_time
                self.shared_state.last_price_update = current_time
        except Exception as e:
            logger.error(f"Error in shared price update: {e}")

    async def _get_price_for_token(self, token: str, chain_key: str) -> Optional[float]:
        chain_config = CHAINS[chain_key]
        wrapped_native = to_checksum_address(chain_config["wrappedNative"])
        token_checksum = to_checksum_address(token)
        for fee in [POOL_FEES["MEDIUM"], POOL_FEES["LOW"], POOL_FEES["HIGH"]]:
            try:
                pool_address = await self.shared_blockchain.get_pool_address(token_checksum, wrapped_native, fee, chain_key)
                if pool_address:
                    price = await self.shared_blockchain.get_pool_price(pool_address, chain_key)
                    if price is not None:
                        return price
            except Exception:
                continue
        return None

    def stop(self):
        if not self.running:
            logger.info("Bot is not running")
            return

        logger.info("Stopping bot...")
        self.running = False

        if not self.live_mode:
            for simulator in self.simulators:
                simulator.stop()
        else:
            self.state.is_running = False
            self.state.manually_stopped = True
            self.trader.stop_pattern_detection()

        self._stop_event_loop()
        logger.info("Bot stopped!")

    def _interactive_loop(self):
        try:
            while self.running:
                cmd = input("> ").strip().lower()
                if cmd == "stop":
                    self.stop()
                elif cmd == "status":
                    self.print_status()
                elif cmd == "prices":
                    self.print_prices()
                elif cmd == "params":
                    self.print_parameters()
                elif cmd == "reset":
                    self.reset()
                elif cmd == "help":
                    print("Commands: start, stop, status, prices, params, reset, help")
                elif cmd:
                    print("Unknown command. Type 'help' for options.")
        except KeyboardInterrupt:
            self.stop()

    def print_status(self):
        if not self.live_mode:
            print("\n=== Parallel Parameter Set Simulations ===")
            for simulator in self.simulators:
                status = simulator.get_status()
                is_aggressive = (
                    status["param_set"].get("MIN_PRICE_CHANGE", 1) == 0.001 and
                    status["param_set"].get("MIN_PROFIT_PERCENT", 1) == 0.01
                )
                marker = " (AGGRESSIVE)" if is_aggressive else ""
                print(f"\n--- Parameter Set #{status['param_set_index']}{marker} ---")
                print(f"Params: {status['param_set']}")
                print(f"Status: {'Running' if status['is_running'] else 'Stopped'}")
                print(f"Current ETH: {status['current_eth']:.12f}")
                print(f"Realized PnL: {status['realized_pnl']:.12f} ETH")
                print(f"Unrealized PnL: {status['unrealized_pnl']:.12f} ETH")
                print(f"Total PnL: {status['net_pnl']:.12f} ETH")
                print(f"Return: {status['portfolio_return']:.2f}%")
                print(f"Trades: {status['total_trades']} (Win: {status['winning_trades']}, Lose: {status['losing_trades']}, Fail: {status['failed_trades']})")
                print(f"Win Rate: {status['win_rate']:.2f}%")
                print(f"Open Positions: {status['open_positions']}")
                print(f"Data Dir: {status['data_dir']}")

                # Show open positions
                with simulator.state._lock:
                    open_positions = [p for p in simulator.state.portfolio["positions"] if p["status"] == "open"]
                if open_positions:
                    print("Open Positions:")
                    for pos in open_positions:
                        symbol = simulator.state.get_token_symbol(pos["token"])
                        current_price = simulator.state.get_token_price(pos["token"]) or pos["entry_price"]
                        current_value = pos["amount"] * current_price
                        unrealized_pnl = current_value - (pos["amount"] * pos["entry_price"]) - pos["fees_paid"] - pos["gas_paid"]
                        cost_basis = (pos["amount"] * pos["entry_price"]) + pos["fees_paid"] + pos["gas_paid"]
                        return_pct = (unrealized_pnl / cost_basis) * 100 if cost_basis > 0 else 0
                        age = int(time.time() - pos["entry_time"])
                        print(f"  {symbol}: {pos['amount']:.8f} @ {pos['entry_price']:.8f} (Value: {current_value:.8f}, PnL: {unrealized_pnl:+.8f} ({return_pct:+.2f}%), Age: {age}s)")

                # Show recent trades
                with simulator.state._lock:
                    recent_trades = simulator.state.trades[-3:]
                if recent_trades:
                    print("Recent Trades:")
                    for trade in recent_trades:
                        pnl_str = f"+{trade['pnl']:.8f}" if trade.get("pnl", 0) >= 0 else f"{trade.get('pnl', 0):.8f}"
                        print(f"  {trade['timestamp'][:19]} | {trade['type'].upper()} {trade['token_amount']:.8f} {trade['token']} @ {trade['price']:.8f} | PnL: {pnl_str}")
        else:
            # Live mode: original status printing
            status = self._get_status()
            print("\n=== Uniswap Quick Swap Trader v7.2.0 - LIVE MODE ===")
            print(f"Status: {'Running' if status['is_running'] else 'Stopped'}")
            print(f"Uptime: {status['uptime']}")
            print(f"Network: {self.state.current_network}")
            print(f"Best Parameter Set: {self.optimizer.best_set_index}")
            print("\n--- Portfolio ---")
            print(f"Current Value: {status['current_eth']:.12f} ETH")
            print(f"Starting Budget: {self.state.portfolio['starting_eth']:.12f} ETH")
            print(f"Realized PnL: {status['realized_pnl']:.12f} ETH")
            print(f"Unrealized PnL: {status['unrealized_pnl']:.12f} ETH")
            print(f"Total Profit: {status['net_pnl']:.12f} ETH")
            print(f"Return: {status['portfolio_return']:.2f}%")
            print("\n--- Trading Stats ---")
            print(f"Total Trades: {status['total_trades']}")
            print(f"Winning Trades: {status['winning_trades']}")
            print(f"Losing Trades: {status['losing_trades']}")
            print(f"Failed Trades: {status['failed_trades']}")
            print(f"Win Rate: {status['win_rate']:.2f}%")
            print("\n--- Market ---")
            print(f"Tracked Tokens: {status['tracked_tokens']}")
            print(f"Active Patterns: {status['active_patterns']}")
            print(f"Open Positions: {status['open_positions']}")
            print(f"Last Price Update: {status['last_price_update']}")
            print(f"Gas Price: {status['current_gas_price']}")

            with self.state._lock:
                open_positions = [p for p in self.state.portfolio["positions"] if p["status"] == "open"]
            if open_positions:
                print("\n--- Open Positions ---")
                for pos in open_positions:
                    current_price = self.state.get_token_price(pos["token"]) or pos["entry_price"]
                    current_value = pos["amount"] * current_price
                    unrealized_pnl = current_value - (pos["amount"] * pos["entry_price"]) - pos["fees_paid"] - pos["gas_paid"]
                    cost_basis = (pos["amount"] * pos["entry_price"]) + pos["fees_paid"] + pos["gas_paid"]
                    return_pct = (unrealized_pnl / cost_basis) * 100 if cost_basis > 0 else 0
                    age = int(time.time() - pos["entry_time"])
                    set_index = pos.get("parameter_set_index", "N/A")
                    print(f"{pos['token']}: {pos['amount']:.8f} @ {pos['entry_price']:.8f} (Value: {current_value:.8f}, PnL: {unrealized_pnl:+.8f} ({return_pct:+.2f}%), Age: {age}s)")

            with self.state._lock:
                recent_trades = self.state.trades[-5:]
            if recent_trades:
                print("\n--- Recent Trades ---")
                for trade in recent_trades:
                    pnl_str = f"+{trade['pnl']:.8f}" if trade.get("pnl", 0) >= 0 else f"{trade.get('pnl', 0):.8f}"
                    set_index = trade.get("parameter_set_index", "N/A")
                    print(f"{trade['timestamp'][:19]} | {trade['token']} | {trade['type'].upper()} | {trade['token_amount']:.8f} @ {trade['price']:.8f} | PnL: {pnl_str} | Set: {set_index}")

    def print_prices(self):
        if not self.live_mode and self.simulators:
            # Use the first simulator's shared state for prices
            simulator = self.simulators[0]
            print("\n--- Current Prices (Shared Across All Simulators) ---")
            with simulator.state._lock:
                for token, price in sorted(simulator.state.prices.items()):
                    symbol = simulator.state.get_token_symbol(token)
                    print(f"{symbol}: {price:.8f} ETH")
        elif self.live_mode:
            print("\n--- Current Prices ---")
            with self.state._lock:
                for token, price in sorted(self.state.prices.items()):
                    symbol = self.state.get_token_symbol(token)
                    print(f"{symbol}: {price:.8f} ETH")

    def print_parameters(self):
        if not self.live_mode:
            print("\n--- All Parameter Sets (Parallel Simulations) ---")
            for i, param_set in enumerate(self.parameter_sets):
                is_aggressive = (
                    param_set.get("MIN_PRICE_CHANGE", 1) == 0.001 and
                    param_set.get("MIN_PROFIT_PERCENT", 1) == 0.01
                )
                marker = " (AGGRESSIVE)" if is_aggressive else ""
                print(f"\nSet {i}{marker}:")
                for key, value in param_set.items():
                    print(f"  {key}: {value}")
                if i < len(self.simulators):
                    status = self.simulators[i].get_status()
                    print(f"  Performance: PnL={status['net_pnl']:.6f} ETH, Trades={status['total_trades']}, Win Rate={status['win_rate']:.2f}%")
        else:
            print("\n--- Parameter Sets (Live Mode) ---")
            for i, params in enumerate(self.optimizer.parameter_sets):
                perf = self.optimizer.performance[i]
                is_best = " (BEST)" if i == self.optimizer.best_set_index else ""
                is_aggressive = (
                    params.get("MIN_PRICE_CHANGE", 1) == 0.001 and
                    params.get("MIN_PROFIT_PERCENT", 1) == 0.01
                )
                aggressive_marker = " (AGGRESSIVE)" if is_aggressive else ""
                print(f"\nSet {i}{is_best}{aggressive_marker}:")
                for key, value in params.items():
                    print(f"  {key}: {value}")
                print(f"  Performance: Profit={perf['profit']:.6f} ETH, Trades={perf['trades']}, Winning={perf['winning_trades']}")

    def reset(self):
        if self.running:
            print("Cannot reset while bot is running. Stop the bot first.")
            return
        if input("Are you sure you want to reset? This will clear all data. (y/n): ").lower() == "y":
            self._stop_event_loop()
            if not self.live_mode:
                for simulator in self.simulators:
                    simulator.stop()
                self.simulators = []
                self.parameter_generator = ParameterGenerator(self.parameter_ranges, self.config.MAX_PARAMETER_SETS)
                self.parameter_sets = self.parameter_generator.get_parameter_sets()
                for i, param_set in enumerate(self.parameter_sets):
                    simulator = Simulator(
                        param_set_index=i,
                        param_set=param_set,
                        shared_state=self.shared_state,
                        shared_blockchain=self.shared_blockchain,
                        base_data_dir="data"
                    )
                    self.simulators.append(simulator)
            else:
                self.state = State(self.config)
                self.optimizer = ParameterOptimizer(self.state, self.parameter_ranges)
                self.trader = Trader(self.state, self.optimizer)
                self.price_updater = PriceUpdater(self.state)
                self.state_manager = StateManager(self.state)
            # Clear all data directories
            if os.path.exists("data"):
                for item in os.listdir("data"):
                    item_path = os.path.join("data", item)
                    if os.path.isdir(item_path):
                        for f in os.listdir(item_path):
                            os.remove(os.path.join(item_path, f))
                        os.rmdir(item_path)
            print("Bot reset!")

    def _get_status(self) -> Dict[str, Any]:
        with self.state._lock:
            net_pnl = self.state.portfolio["realized_pnl"] + self.state.portfolio["unrealized_pnl"]
            successful_trades = self.state.portfolio["winning_trades"] + self.state.portfolio["losing_trades"]
            win_rate = (self.state.portfolio["winning_trades"] / successful_trades * 100) if successful_trades > 0 else 0
            return {
                "is_running": self.state.is_running,
                "uptime": str(timedelta(seconds=int(time.time() - self.state.start_time))) if self.state.start_time else "00:00:00",
                "current_eth": self.state.portfolio["current_eth"],
                "realized_pnl": self.state.portfolio["realized_pnl"],
                "unrealized_pnl": self.state.portfolio["unrealized_pnl"],
                "net_pnl": net_pnl,
                "portfolio_return": (net_pnl / self.state.portfolio["starting_eth"] * 100) if self.state.portfolio["starting_eth"] > 0 else 0,
                "total_trades": self.state.portfolio["total_trades"],
                "winning_trades": self.state.portfolio["winning_trades"],
                "losing_trades": self.state.portfolio["losing_trades"],
                "failed_trades": self.state.portfolio["failed_trades"],
                "win_rate": win_rate,
                "open_positions": len([p for p in self.state.portfolio["positions"] if p["status"] == "open"]),
                "tracked_tokens": len(self.state.observed_tokens),
                "active_patterns": self.state.pattern_stats["total_patterns"],
                "last_price_update": datetime.fromtimestamp(self.state.last_price_update).strftime("%Y-%m-%d %H:%M:%S") if self.state.last_price_update else "Never",
                "current_gas_price": f"{self.state.current_gas_price:.2f} gwei",
            }

# ========== MAIN ==========
def main():
    print("Uniswap Quick Swap Trader v7.2.0 - Parallel Parameter Set Simulations")
    print("Profit-Only Mode: Buys dips and sells ONLY at profit")
    print("Arbitrum-Only Mode: Only works on Arbitrum network")
    print("Parallel Simulations: Each parameter set runs independently in non-live mode")
    print("Thread-Safe: Fixed dictionary iteration errors")
    print("Isolated Persistence: Each parameter set saves to its own data/param_set_X/ directory\n")
    logger.info("Uniswap Quick Swap Trader v7.2.0 (Parallel Simulations + Thread-Safe) started.")

    bot = Bot()
    if not bot.live_mode:
        for simulator in bot.simulators:
            simulator.state_manager.load_state()
    else:
        bot.state_manager.load_state()

    print("Commands:")
    print("  start   - Start the bot")
    print("  stop    - Stop the bot")
    print("  status  - Show status of all parameter sets (or live mode)")
    print("  prices  - Show current prices")
    print("  params  - Show parameter sets and their performance")
    print("  reset   - Reset all data")
    print("  help    - Show this help\n")

    while True:
        cmd = input("> ").strip().lower()
        if cmd == "start":
            if not bot.running:
                bot.start()
            else:
                print("Bot is already running")
        elif cmd == "stop":
            if bot.running:
                bot.stop()
            else:
                print("Bot is not running")
        elif cmd == "status":
            bot.print_status()
        elif cmd == "prices":
            bot.print_prices()
        elif cmd == "params":
            bot.print_parameters()
        elif cmd == "reset":
            bot.reset()
        elif cmd == "help":
            print("Commands: start, stop, status, prices, params, reset, help")
        elif cmd:
            print("Unknown command. Type 'help' for options.")

if __name__ == "__main__":
    main()