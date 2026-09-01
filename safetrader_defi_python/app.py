import os
import json
import time
import random
import math
import asyncio
import threading
import logging
import requests
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set, Tuple, Any
from dotenv import load_dotenv
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware

# Load environment variables
load_dotenv()

# Configure logging with enhanced verbosity
logging.basicConfig(
    level=logging.INFO,  # Set to DEBUG for maximum verbosity
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    handlers=[
        logging.FileHandler("app.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

# ========== UTILITY FUNCTIONS ==========
def norm(a: str) -> str:
    """Normalize address to lowercase."""
    return a.lower() if a else ""

def short(a: str) -> str:
    """Shorten address for display."""
    if not a:
        return ""
    return f"{a[:6]}...{a[-4:]}"

def to_checksum_address(address: str) -> str:
    """Convert an Ethereum address to checksum format."""
    if not address or not isinstance(address, str):
        return address
    try:
        return Web3.to_checksum_address(address.lower())
    except Exception:
        return address

# ========== COINGECKO TOKEN FETCHER ==========
def fetch_coingecko_tokens(chain_id: int = 42161) -> List[Dict[str, Any]]:
    """Fetch tokens from CoinGecko's Arbitrum token list."""
    url = "https://tokens.coingecko.com/arbitrum-one/all.json"
    try:
        logger.debug(f"Fetching CoinGecko tokens from {url}")
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        data = response.json()
        tokens = data.get("tokens", [])
        logger.info(f"Fetched {len(tokens)} tokens from CoinGecko")
        return [token for token in tokens if token.get("chainId") == chain_id]
    except Exception as e:
        logger.error(f"Failed to fetch CoinGecko tokens: {e}", exc_info=True)
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

DEFAULT_PARAMETER_RANGES = {
    "MIN_PRICE_CHANGE": ParameterRange(min=0.01, max=0.5, step=0.01),  # Lowered for testing
    "MIN_TIME_WINDOW": ParameterRange(min=2, max=30, step=2),
    "MAX_TIME_WINDOW": ParameterRange(min=30, max=300, step=30),  # Reduced for testing
    "MIN_OCCURRENCES": ParameterRange(min=1, max=3, step=1),
    "MIN_PROFIT_PERCENT": ParameterRange(min=0.1, max=5.0, step=0.1),  # Lowered for testing
}

class ParameterGenerator:
    def __init__(self, ranges: Optional[Dict[str, ParameterRange]] = None, max_combinations: int = 50):
        self.ranges = ranges or DEFAULT_PARAMETER_RANGES
        self.max_combinations = max_combinations
        self.parameter_sets = self._generate_parameter_sets()
        logger.info(f"Generated {len(self.parameter_sets)} parameter sets")

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
    MIN_PRICE_CHANGE: float = 0.1  # Lowered for testing
    MIN_TIME_WINDOW: int = 5
    MAX_TIME_WINDOW: int = 120
    MIN_OCCURRENCES: int = 2
    MIN_PROFIT_PERCENT: float = 1.0  # Lowered for testing
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

# Known token symbols and their addresses for Arbitrum
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

# Arbitrum RPC endpoints with fallback
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

# ========== STATE MANAGEMENT ==========
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
        logger.info("State initialized with starting ETH: %.12f", config.STARTING_ETH)

    def get_token_symbol(self, token: str) -> str:
        """Get symbol for a token (handles both symbols and addresses)."""
        if token in self.token_symbols:
            return self.token_symbols[token]
        checksummed = to_checksum_address(token)
        if checksummed in self.token_symbols:
            return self.token_symbols[checksummed]
        for symbol, addr in self.token_addresses.items():
            if norm(token) == norm(addr):
                return symbol
        return short(token)

    def get_token_address(self, token: str) -> Optional[str]:
        """Get address for a token (handles both symbols and addresses)."""
        if token in self.token_addresses.values():
            return to_checksum_address(token)
        if norm(token) in [norm(addr) for addr in self.token_addresses.values()]:
            return to_checksum_address(token)
        if token in self.token_addresses:
            return to_checksum_address(self.token_addresses[token])
        return None

    def get_token_price(self, token: str) -> Optional[float]:
        """Get price for a token (handles both symbols and addresses)."""
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
        for symbol, addr in self.token_addresses.items():
            if norm(token) == norm(addr):
                if addr in self.prices:
                    return self.prices[addr]
                checksummed_addr = to_checksum_address(addr)
                if checksummed_addr in self.prices:
                    return self.prices[checksummed_addr]
        return None

    def get_token_history(self, token: str) -> Optional[List[Dict[str, Any]]]:
        """Get price history for a token (handles both symbols and addresses)."""
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
        for symbol, addr in self.token_addresses.items():
            if norm(token) == norm(addr):
                if addr in self.price_history:
                    return self.price_history[addr]
                checksummed_addr = to_checksum_address(addr)
                if checksummed_addr in self.price_history:
                    return self.price_history[checksummed_addr]
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "config": asdict(self.config),
            "is_running": self.is_running,
            "current_network": self.current_network,
            "prices": self.prices,
            "price_history": {k: v for k, v in self.price_history.items()},
            "trades": self.trades,
            "active_patterns": self.active_patterns,
            "portfolio": self.portfolio,
            "last_traded_token": self.last_traded_token,
            "last_trade_times": self.last_trade_times,
            "start_time": self.start_time,
            "last_price_update": self.last_price_update,
            "current_gas_price": self.current_gas_price,
            "observed_tokens": list(self.observed_tokens),
            "pattern_stats": self.pattern_stats,
            "open_buy_orders": self.open_buy_orders,
            "token_symbols": self.token_symbols,
            "token_addresses": self.token_addresses,
            "timestamp": datetime.now().isoformat(),
        }

    def from_dict(self, state_dict: Dict[str, Any]):
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
            logger.debug(
                f"Updated performance for set #{parameter_set_index}: "
                f"Profit={self.performance[parameter_set_index]['profit']:.6f}, "
                f"Trades={self.performance[parameter_set_index]['trades']}, "
                f"Winning={self.performance[parameter_set_index]['winning_trades']}"
            )

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
        """Test if an RPC endpoint is working."""
        try:
            if rpc_url.startswith("wss://"):
                w3 = Web3(Web3.WebsocketProvider(rpc_url, websocket_timeout=5))
            else:
                w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={'timeout': 5}))
            
            # Test with a simple call
            block_number = w3.eth.block_number
            logger.info(f"RPC endpoint {rpc_url} is working (block: {block_number})")
            return True
        except Exception as e:
            logger.warning(f"RPC endpoint {rpc_url} failed: {e}")
            return False

    def _initialize_providers(self):
        """Initialize Web3 providers with fallback."""
        chain_key = self.state.current_chain_key
        if chain_key not in self.chains:
            logger.error(f"Chain {chain_key} not found in CHAINS configuration")
            return

        chain_config = self.chains[chain_key]
        rpc_urls = chain_config["rpcs"]
        
        for rpc_url in rpc_urls:
            if self._test_rpc_endpoint(rpc_url):
                if chain_key in ["polygon", "arbitrum", "base", "optimism"]:
                    if rpc_url.startswith("wss://"):
                        provider = Web3.WebsocketProvider(rpc_url, websocket_timeout=10)
                    else:
                        provider = Web3.HTTPProvider(rpc_url, request_kwargs={'timeout': 10})
                    w3 = Web3(provider)
                    w3.middleware_onion.inject(ExtraDataToPOAMiddleware(), layer=0, name="extradata_to_poa")
                else:
                    if rpc_url.startswith("wss://"):
                        provider = Web3.WebsocketProvider(rpc_url, websocket_timeout=10)
                    else:
                        provider = Web3.HTTPProvider(rpc_url, request_kwargs={'timeout': 10})
                    w3 = Web3(provider)
                
                self.web3_providers[chain_key] = w3
                logger.info(f"Using RPC endpoint: {rpc_url}")
                break
        else:
            logger.error(f"All RPC endpoints failed for {chain_key}")
            # Fallback to first endpoint even if it failed
            rpc_url = rpc_urls[0]
            if rpc_url.startswith("wss://"):
                provider = Web3.WebsocketProvider(rpc_url, websocket_timeout=10)
            else:
                provider = Web3.HTTPProvider(rpc_url, request_kwargs={'timeout': 10})
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
            factory_contract = w3.eth.contract(
                address=factory_address,
                abi=UNISWAP_V3_FACTORY_ABI,
            )
            self.factory_contracts[chain_key] = factory_contract
            logger.debug(f"Factory contract initialized for {chain_key} at {factory_address}")
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
            logger.debug(f"Pool contract initialized for {short(pool_address)}")
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
            logger.debug(f"Token contract initialized for {short(token_address)}")
            return token_contract
        except Exception as e:
            logger.error(f"Failed to initialize token contract for {short(token_address)}: {e}")
            return None

    async def get_pool_address(self, token0: str, token1: str, fee: int, chain_key: str) -> Optional[str]:
        try:
            factory = await self.get_factory_contract(chain_key)
            if not factory:
                logger.error(f"No factory contract for {chain_key}")
                return None
            
            token0_checksum = to_checksum_address(token0)
            token1_checksum = to_checksum_address(token1)
            pool_address = factory.functions.getPool(token0_checksum, token1_checksum, fee).call()
            if pool_address == "0x0000000000000000000000000000000000000000":
                logger.debug(f"No pool found for {short(token0)}-{short(token1)} with fee {fee}")
                return None
            logger.debug(f"Found pool for {short(token0)}-{short(token1)}: {short(pool_address)}")
            return pool_address
        except Exception as e:
            logger.error(f"Error getting pool address for {short(token0)}-{short(token1)}: {e}", exc_info=True)
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
            logger.debug(f"Got price from pool {short(pool_address)}: {price}")
            return price
        except Exception as e:
            logger.error(f"Error getting price from pool {short(pool_address)}: {e}", exc_info=True)
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
            self.state.token_decimals[token_address] = decimals
            logger.debug(f"Got decimals for {short(token_address)}: {decimals}")
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
            self.state.token_symbols[token_address] = symbol
            self.state.token_addresses[symbol] = token_address
            logger.debug(f"Got symbol for {short(token_address)}: {symbol}")
            return symbol
        except Exception as e:
            logger.error(f"Error getting token symbol for {short(token_address)}: {e}")
            return short(token_address)

# ========== TOKEN DISCOVERY ==========
class TokenDiscovery:
    def __init__(self, state: State, blockchain: BlockchainHelper):
        self.state = state
        self.blockchain = blockchain
        self.active_pools: Set[str] = set()
        self.last_block: Dict[str, int] = {}
        self.swap_topic = "0xc42079f94a6436c4e6930f05045148f3556048be474e7962b362652246f71625"

    async def initialize_known_tokens(self, chain_key: str):
        """Initialize with WETH, stables, top pool tokens, and CoinGecko tokens."""
        logger.info(f"Initializing known tokens for {chain_key}")
        chain_config = CHAINS[chain_key]
        wrapped_native = to_checksum_address(chain_config["wrappedNative"])
        quote_label = chain_config["quoteLabel"]

        # Add WETH/ETH
        if wrapped_native not in self.state.token_symbols:
            self.state.token_symbols[wrapped_native] = quote_label
            self.state.token_addresses[quote_label] = wrapped_native
            logger.debug(f"Added WETH: {wrapped_native}")
        if wrapped_native not in self.state.observed_tokens:
            self.state.observed_tokens.add(wrapped_native)
            logger.debug(f"Added WETH to observed tokens")
        if wrapped_native not in self.state.prices:
            self.state.prices[wrapped_native] = 1.0
            self._update_price_history(wrapped_native, 1.0)
            logger.debug(f"Set WETH price to 1.0")

        # Add known tokens from NETWORK_TOKENS
        for symbol, address in NETWORK_TOKENS.get(chain_key, {}).items():
            checksum_addr = to_checksum_address(address)
            if checksum_addr not in self.state.token_symbols:
                self.state.token_symbols[checksum_addr] = symbol
                self.state.token_addresses[symbol] = checksum_addr
                logger.debug(f"Added known token: {symbol} ({short(checksum_addr)})")
            if checksum_addr not in self.state.observed_tokens:
                self.state.observed_tokens.add(checksum_addr)
                logger.debug(f"Added {symbol} to observed tokens")

        # Add stables
        for stable in chain_config.get("stables", []):
            stable = to_checksum_address(stable)
            if stable not in self.state.observed_tokens:
                self.state.observed_tokens.add(stable)
                logger.debug(f"Added stablecoin to observed tokens: {short(stable)}")

        # Add top pool tokens
        await self._add_top_pool_tokens(chain_key)

        # Add tokens from CoinGecko
        await self._add_coingecko_tokens(chain_key)
        
        logger.info(f"Initialized {len(self.state.observed_tokens)} known tokens")

    async def _add_coingecko_tokens(self, chain_key: str):
        """Add tokens from CoinGecko's Arbitrum list."""
        logger.info("Adding tokens from CoinGecko...")
        coingecko_tokens = fetch_coingecko_tokens()
        for token in coingecko_tokens:
            address = to_checksum_address(token["address"])
            symbol = token.get("symbol", short(address))
            if address not in self.state.observed_tokens:
                self.state.observed_tokens.add(address)
                self.state.token_symbols[address] = symbol
                self.state.token_addresses[symbol] = address
                logger.debug(f"Added CoinGecko token: {symbol} ({short(address)})")
        logger.info(f"Added {len(coingecko_tokens)} tokens from CoinGecko")

    async def _add_top_pool_tokens(self, chain_key: str):
        """Add tokens from the top pools for the chain."""
        chain_config = CHAINS[chain_key]
        for token0, token1, _ in chain_config.get("topPools", []):
            for token_addr in [to_checksum_address(token0), to_checksum_address(token1)]:
                if token_addr not in self.state.observed_tokens:
                    self.state.observed_tokens.add(token_addr)
                    logger.debug(f"Added top pool token to observed tokens: {short(token_addr)}")

    async def discover_tokens_from_blocks(self, chain_key: str, blocks_to_scan: int = 5):
        """Scan recent blocks for Swap events to discover new tokens."""
        try:
            w3 = self.blockchain.get_web3(chain_key)
            if not w3:
                logger.error(f"No Web3 provider for {chain_key}")
                return
            
            current_block = w3.eth.block_number
            last_scanned = self.last_block.get(chain_key, current_block - blocks_to_scan)

            if current_block <= last_scanned:
                logger.debug(f"No new blocks to scan on {chain_key} (current: {current_block}, last scanned: {last_scanned})")
                return

            from_block = max(0, current_block - blocks_to_scan)
            to_block = current_block
            logger.info(f"Scanning blocks {from_block} to {to_block} on {chain_key} for Swap events...")

            try:
                logs = w3.eth.get_logs({
                    'fromBlock': from_block,
                    'toBlock': to_block,
                    'topics': [self.swap_topic]
                })
                logger.debug(f"Found {len(logs)} Swap logs in blocks {from_block}-{to_block}")
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
                    logger.debug(f"Found new pool: {short(pool_address)}")

                    pool_contract = await self.blockchain.get_pool_contract(pool_address, chain_key)
                    if not pool_contract:
                        continue
                    
                    token0 = to_checksum_address(pool_contract.functions.token0().call())
                    token1 = to_checksum_address(pool_contract.functions.token1().call())
                    new_tokens.update([token0, token1])
                    logger.debug(f"Discovered tokens in pool {short(pool_address)}: {short(token0)}, {short(token1)}")
                except Exception as e:
                    logger.warning(f"Error processing Swap log: {e}")
                    continue

            for token_addr in new_tokens:
                if token_addr not in self.state.observed_tokens:
                    self.state.observed_tokens.add(token_addr)
                    logger.info(f"Discovered new token: {short(token_addr)}")

            self.last_block[chain_key] = current_block
            logger.info(f"Token discovery complete. Total observed tokens: {len(self.state.observed_tokens)}")
        except Exception as e:
            logger.error(f"Error in token discovery: {e}", exc_info=True)

    def _update_price_history(self, token: str, price: float):
        """Update price history for a token."""
        if token not in self.state.price_history:
            self.state.price_history[token] = []
        self.state.price_history[token].append({"price": price, "timestamp": time.time()})
        if len(self.state.price_history[token]) > self.state.config.MAX_PRICE_HISTORY:
            self.state.price_history[token] = self.state.price_history[token][-self.state.config.MAX_PRICE_HISTORY:]
        logger.debug(f"Updated price history for {short(token)}: {price}")

# ========== PATTERN DETECTION ==========
class PatternDetector:
    def __init__(self, state: State, optimizer: ParameterOptimizer):
        self.state = state
        self.optimizer = optimizer

    def detect_all_patterns(self):
        """Detect patterns for all observed tokens using the current parameter set."""
        logger.info(f"Starting pattern detection for {len(self.state.observed_tokens)} tokens")
        tokens = list(self.state.observed_tokens)
        new_active_patterns = {}
        best_params = self.optimizer.get_current_best_parameters()

        for token in tokens:
            history = self.state.get_token_history(token)
            if history is None or len(history) < 5:
                logger.debug(f"Skipping {short(token)}: insufficient history ({len(history) if history else 0} points)")
                continue
            buy_patterns = self._detect_buy_patterns(history, token, best_params)
            logger.debug(f"Found {len(buy_patterns)} buy patterns for {short(token)}")
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
                    logger.debug(f"Added new pattern for {short(token)}: {pattern_key}")
                else:
                    existing = new_active_patterns[existing_key]
                    existing["occurrences"] += 1
                    existing["last_seen"] = max(existing["last_seen"], pattern["timestamp"])
                    logger.debug(f"Updated existing pattern for {short(token)}: {pattern_key}")

        self._validate_patterns(new_active_patterns, best_params)
        self.state.active_patterns = new_active_patterns
        self._update_pattern_stats()
        self.state.last_detection_time = time.time()
        logger.info(f"Pattern detection complete. Found {len(new_active_patterns)} active patterns")

    def _detect_buy_patterns(self, history: List[Dict[str, Any]], token: str, params: Dict[str, float]) -> List[Dict[str, Any]]:
        """Detect buy patterns (dips + rises) for a token."""
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
                                logger.debug(
                                    f"Detected buy pattern for {short(token)}: "
                                    f"drop={abs(drop_pct)*100:.2f}%, rise={rise_pct*100:.2f}%"
                                )
                                break
                        break
        return patterns

    def _is_valid_pattern(self, pattern: Dict[str, Any], params: Dict[str, float]) -> bool:
        """Check if a pattern meets validity criteria."""
        if pattern["drop_pct"] > 100 or pattern["rise_pct"] > 100:
            logger.debug(f"Invalid pattern: drop_pct or rise_pct > 100")
            return False
        if pattern["drop_pct"] < 0 or pattern["rise_pct"] < 0:
            logger.debug(f"Invalid pattern: negative drop_pct or rise_pct")
            return False
        if pattern["drop_time"] > 600 or pattern["rise_time"] > 600:
            logger.debug(f"Invalid pattern: drop_time or rise_time > 600")
            return False
        if pattern["drop_time"] < 1 or pattern["rise_time"] < 1:
            logger.debug(f"Invalid pattern: drop_time or rise_time < 1")
            return False
        if pattern["rise_pct"] < params["MIN_PROFIT_PERCENT"]:
            logger.debug(f"Invalid pattern: rise_pct < MIN_PROFIT_PERCENT")
            return False
        return True

    def _get_pattern_key(self, pattern: Dict[str, Any]) -> str:
        """Generate a unique key for a pattern."""
        return (
            f"BUY_{round(pattern['drop_pct'] * 10) / 10}%"
            f"_{round(pattern['drop_time'])}s_"
            f"{round(pattern['rise_pct'] * 10) / 10}%"
            f"_{round(pattern['rise_time'])}s"
        )

    def _validate_patterns(self, patterns: Dict[str, Dict[str, Any]], params: Dict[str, float]):
        """Remove invalid patterns."""
        keys_to_delete = [
            key for key, pattern in patterns.items()
            if pattern["drop_pct"] <= 0 or pattern["rise_pct"] <= 0
            or pattern["rise_pct"] < params["MIN_PROFIT_PERCENT"]
        ]
        for key in keys_to_delete:
            logger.debug(f"Removing invalid pattern: {key}")
            del patterns[key]

    def _update_pattern_stats(self):
        """Update pattern statistics."""
        patterns_list = list(self.state.active_patterns.values())
        self.state.pattern_stats["total_patterns"] = len(patterns_list)
        self.state.pattern_stats["tokens_with_patterns"] = len({p["token"] for p in patterns_list})
        logger.debug(f"Updated pattern stats: {self.state.pattern_stats}")

# ========== TRADE EXECUTION ==========
class Trader:
    def __init__(self, state: State, optimizer: ParameterOptimizer):
        self.state = state
        self.config = state.config
        self.optimizer = optimizer
        self.detector = PatternDetector(state, optimizer)
        self.blockchain = BlockchainHelper(state)
        self.token_discovery = TokenDiscovery(state, self.blockchain)
        self.live_mode = os.getenv("PRIVATE_KEY", "") != ""
        logger.info(f"Trader initialized - Live mode: {'ON' if self.live_mode else 'OFF (shadow mode)'}")

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
            result = min(trade_amount, available_eth * 0.95)
            logger.debug(f"Calculated trade amount: {result:.12f} ETH (gas_cost_per_trade: {gas_cost_per_trade:.12f}, total_gas_cost: {total_gas_cost:.12f})")
            return result
        except Exception as e:
            logger.error(f"Error calculating trade amount: {e}", exc_info=True)
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
            logger.warning(f"Trade simulation failed for {short(token)}: {result['reason']}")
            return result
        if action == "buy":
            result["execution_price"] = current_price * (1 + result["slippage"] / 100)
        else:
            result["execution_price"] = current_price * (1 - result["slippage"] / 100)
        result["amount_eth"] = token_amount * result["execution_price"]
        if action == "buy":
            result["token_amount"] = result["amount_eth"] / result["execution_price"]
        logger.debug(f"Simulated {action} trade for {short(token)}: amount_eth={result['amount_eth']:.12f}, execution_price={result['execution_price']:.8f}, slippage={result['slippage']:.4f}%")
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
        result = min(base_gas, self.config.GAS_LIMIT)
        logger.debug(f"Estimated gas for {action} {short(token)}: {result}")
        return result

    def _calculate_price_impact(self, token: str, token_amount: float) -> float:
        token_price = self.state.get_token_price(token) or 1.0
        token_value_eth = token_amount * token_price
        liquidity_eth = 100000
        result = min((token_value_eth / liquidity_eth) * 100, 2.0)
        logger.debug(f"Calculated price impact for {short(token)}: {result:.4f}%")
        return result

    def create_trade(
        self, token: str, action: str, price: float, token_amount: float, amount_eth: float,
        pattern: str, status: str, reason: Optional[str] = None,
        parameter_set_index: Optional[int] = None, **kwargs
    ) -> Dict[str, Any]:
        trade = {
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
        logger.debug(f"Created trade: {trade['id']} - {action} {token_amount:.8f} {short(token)} at {price:.8f} ETH")
        return trade

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
                self.state.portfolio["failed_trades"] += 1
                self.state.trades.append(trade)
                logger.warning(f"Trade failed: {trade['reason']}")
                return
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
                logger.info(f"Opened new position: {trade_result['token_amount']:.8f} {short(token)} at {trade_result['execution_price']:.8f} ETH")
            else:
                position["amount"] += trade_result["token_amount"]
                position["usd_value"] += trade_result["amount_eth"]
                position["gas_paid"] += gas_cost_eth
                position["fees_paid"] += fee_cost_eth
                logger.info(f"Added to existing position: {trade_result['token_amount']:.8f} {short(token)}")
            self.state.portfolio["gas_spent"] += gas_cost_eth
            self.state.portfolio["fees_paid"] += fee_cost_eth
            self.state.portfolio["total_fees"] += total_cost_eth
        elif action == "sell":
            open_positions = sorted(
                [p for p in self.state.portfolio["positions"] if p["token"] == token and p["status"] == "open"],
                key=lambda x: x["entry_time"],
            )
            if not open_positions:
                trade["status"] = "failed"
                trade["reason"] = "No open position to sell"
                self.state.portfolio["failed_trades"] += 1
                self.state.trades.append(trade)
                logger.warning(f"Trade failed: {trade['reason']}")
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
                    logger.info(f"Closed position with profit: +{pnl:.12f} ETH")
                elif pnl < 0:
                    self.state.portfolio["losing_trades"] += 1
                    logger.info(f"Closed position with loss: {pnl:.12f} ETH")
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
        self.state.trades.append(trade)
        if "parameter_set_index" in trade:
            self.optimizer.update_performance(
                trade["parameter_set_index"],
                trade.get("pnl", 0),
                trade.get("pnl", 0) > 0
            )
        logger.info(f"Trade {trade['id']} {action} {trade['token_amount']:.8f} {short(token)} - Status: {trade['status']}, PnL: {trade.get('pnl', 0):+.12f} ETH")

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
        self.state.portfolio["current_eth"] = total_eth
        self.state.portfolio["unrealized_pnl"] = (
            total_eth - self.state.portfolio["starting_eth"] - self.state.portfolio["realized_pnl"]
        )
        self.state.portfolio["equity_history"].append({"timestamp": time.time(), "eth_value": total_eth})
        if len(self.state.portfolio["equity_history"]) > 1000:
            self.state.portfolio["equity_history"] = self.state.portfolio["equity_history"][-1000:]
        logger.debug(f"Updated portfolio equity: {total_eth:.12f} ETH (realized_pnl: {self.state.portfolio['realized_pnl']:.12f}, unrealized_pnl: {self.state.portfolio['unrealized_pnl']:.12f})")

    async def execute_trade(
        self, token: str, action: str, pattern_desc: str = "Manual",
        amount_eth: Optional[float] = None, pattern: Optional[Dict[str, Any]] = None,
        parameter_set_index: Optional[int] = None
    ) -> Optional[Dict[str, Any]]:
        if not self.state.is_running:
            logger.warning(f"Cannot execute trade: bot is not running")
            return None
        if amount_eth is None:
            amount_eth = self.calculate_trade_amount()
        current_price = self.state.get_token_price(token)
        if current_price is None:
            logger.warning(f"No price available for token {short(token)}")
            return None
        if amount_eth <= 0:
            logger.warning(f"Trade amount is <= 0: {amount_eth}")
            return None
        open_positions = len([p for p in self.state.portfolio["positions"] if p["status"] == "open"])
        if open_positions >= self.config.MAX_TRADES:
            logger.info(f"Max trades ({self.config.MAX_TRADES}) reached")
            return None
        last_trade_time = self.state.last_trade_times.get(token)
        if last_trade_time and (time.time() - last_trade_time) < self.config.TRADE_COOLDOWN:
            logger.info(f"Trade cooldown active for {short(token)} (last trade: {time.time() - last_trade_time:.0f}s ago)")
            return None
        if self.state.current_gas_price > self.config.MAX_GAS_PRICE:
            logger.info(f"Gas price too high: {self.state.current_gas_price:.2f} gwei > {self.config.MAX_GAS_PRICE} gwei")
            return None
        if action == "sell":
            token_balance = self.state.portfolio["balances"].get(token, 0)
            if token_balance <= 0:
                logger.warning(f"Cannot sell {short(token)}: balance is 0")
                return None
        token_amount = amount_eth / current_price
        trade_result = self.simulate_trade(token, action, token_amount, current_price)
        if not trade_result["success"]:
            failed_trade = self.create_trade(
                token, action, current_price, token_amount, amount_eth, pattern_desc,
                "failed", trade_result["reason"], parameter_set_index, **trade_result
            )
            self.state.trades.append(failed_trade)
            self.state.portfolio["failed_trades"] += 1
            self.state.portfolio["total_trades"] += 1
            logger.warning(f"Trade failed: {trade_result['reason']}")
            return failed_trade
        if self.config.PREVENT_SEQUENTIAL_TRADES and self.state.last_traded_token == token:
            logger.info(f"Prevented sequential trade for {short(token)}")
            return None
        token_amount = trade_result["token_amount"]
        trade = self.create_trade(
            token, action, trade_result["execution_price"], token_amount,
            trade_result["amount_eth"], pattern_desc, "open", parameter_set_index=parameter_set_index, **trade_result
        )
        self.update_portfolio(trade, action, trade_result)
        self.state.portfolio["total_trades"] += 1
        self.state.last_traded_token = token
        self.state.last_trade_times[token] = time.time()
        if action == "buy":
            self.state.open_buy_orders[token] = {
                "trade_id": trade["id"],
                "pattern": pattern,
                "entry_price": trade_result["execution_price"],
                "entry_time": time.time(),
                "parameter_set_index": parameter_set_index,
            }
            logger.info(f"[Set {parameter_set_index}] Bought {trade_result['token_amount']:.6f} {short(token)} at {trade_result['execution_price']:.8f} ETH")
        if action == "sell":
            if token in self.state.open_buy_orders:
                del self.state.open_buy_orders[token]
            pnl_text = f"+{trade['pnl']:.8f}" if trade["pnl"] >= 0 else f"{trade['pnl']:.8f}"
            logger.info(f"[Set {parameter_set_index}] Sold {trade_result['token_amount']:.6f} {short(token)} at {trade_result['execution_price']:.8f} ETH (PnL: {pnl_text} ETH)")
        return trade

    async def check_patterns_for_token(self, token: str):
        """Check for buy/sell opportunities for a token."""
        if not self.state.is_running:
            return
        history = self.state.get_token_history(token)
        if history is None or len(history) < 2:
            logger.debug(f"Skipping pattern check for {short(token)}: insufficient history")
            return
        current_price = self.state.get_token_price(token)
        if current_price is None:
            logger.debug(f"Skipping pattern check for {short(token)}: no price")
            return
        best_params = self.optimizer.get_current_best_parameters()
        open_position = next(
            (p for p in self.state.portfolio["positions"] if p["token"] == token and p["status"] == "open"),
            None,
        )
        if open_position:
            current_value = open_position["amount"] * current_price
            cost_basis = (open_position["amount"] * open_position["entry_price"]) + open_position["fees_paid"] + open_position["gas_paid"]
            profit_eth = current_value - cost_basis
            profit_pct = (profit_eth / cost_basis) * 100 if cost_basis > 0 else 0
            logger.debug(f"Open position for {short(token)}: value={current_value:.12f}, cost_basis={cost_basis:.12f}, profit_pct={profit_pct:.2f}%")
            if profit_pct >= best_params["MIN_PROFIT_PERCENT"] and profit_eth > 0:
                sell_amount_eth = open_position["amount"] * current_price
                parameter_set_index = open_position.get("parameter_set_index", 0)
                logger.info(f"Profit target reached for {short(token)}: {profit_pct:.2f}% - Selling...")
                await self.execute_trade(
                    token, "sell", f"Profit target ({profit_pct:.2f}%) reached",
                    sell_amount_eth, None, parameter_set_index
                )
                return
        token_patterns = [
            p for p in self.state.active_patterns.values()
            if p["token"] == token
        ]
        buy_patterns = [p for p in token_patterns if p["type"] == "buy"]
        logger.debug(f"Found {len(buy_patterns)} buy patterns for {short(token)}")
        for pattern in buy_patterns:
            if self._check_pattern_match(token, pattern):
                if self.config.PREVENT_SEQUENTIAL_TRADES and self.state.last_traded_token == token:
                    logger.debug(f"Skipping pattern for {short(token)}: sequential trades prevented")
                    continue
                if token in self.state.open_buy_orders:
                    logger.debug(f"Skipping pattern for {short(token)}: open buy order exists")
                    continue
                trade_amount = self.calculate_trade_amount()
                logger.info(f"Executing buy trade for {short(token)} based on pattern: {pattern}")
                await self.execute_trade(
                    token, "buy", f"Buy dip: {pattern['drop_pct']:.2f}% drop, {pattern['rise_pct']:.2f}% target",
                    trade_amount, pattern, pattern.get("parameter_set_index")
                )

    def _check_pattern_match(self, token: str, pattern: Dict[str, Any]) -> bool:
        """Check if current price matches a pattern."""
        history = self.state.get_token_history(token)
        if history is None or len(history) < 2:
            logger.debug(f"Cannot check pattern match for {short(token)}: insufficient history")
            return False
        current_price = self.state.get_token_price(token)
        if current_price is None:
            logger.debug(f"Cannot check pattern match for {short(token)}: no price")
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
                        logger.debug(f"Pattern match found for {short(token)}: drop_pct={abs(drop_pct)*100:.2f}%, time_diff={time_diff:.0f}s")
                        return True
        logger.debug(f"No pattern match found for {short(token)}")
        return False

    def start_pattern_detection(self):
        """Start the pattern detection loop."""
        if self.state.pattern_detection_active:
            logger.warning("Pattern detection is already active")
            return
        self.state.pattern_detection_active = True
        self.detector.detect_all_patterns()
        def loop():
            while self.state.is_running and self.state.pattern_detection_active:
                logger.debug("Running pattern detection loop...")
                self.detector.detect_all_patterns()
                self.optimizer.optimize()
                time.sleep(3)
        threading.Thread(target=loop, daemon=True).start()
        logger.info("Pattern detection started")

    def stop_pattern_detection(self):
        """Stop the pattern detection loop."""
        self.state.pattern_detection_active = False
        logger.info("Pattern detection stopped")

# ========== PRICE UPDATER ==========
class PriceUpdater:
    def __init__(self, state: State):
        self.state = state
        self.blockchain = BlockchainHelper(state)
        self.token_discovery = TokenDiscovery(state, self.blockchain)
        self.price_update_lock = threading.Lock()
        self.last_price_update: Dict[str, float] = {}

    async def update_prices(self):
        """Update prices for all observed tokens."""
        with self.price_update_lock:
            try:
                logger.info("Starting price update...")
                chain_key = self.state.current_network
                chain_config = CHAINS[chain_key]
                w3 = self.blockchain.get_web3(chain_key)
                if not w3:
                    logger.error(f"No Web3 provider for {chain_key}")
                    return

                # Get gas price
                try:
                    gas_price_wei = w3.eth.gas_price
                    self.state.current_gas_price = gas_price_wei / 1e9
                    logger.info(f"Gas price: {self.state.current_gas_price:.2f} gwei")
                except Exception as e:
                    logger.warning(f"Could not fetch gas price: {e}")
                    self.state.current_gas_price = self.state.config.MAX_GAS_PRICE

                wrapped_native = to_checksum_address(chain_config["wrappedNative"])

                # Initialize with known tokens if empty
                if not self.state.observed_tokens:
                    logger.info("No observed tokens, initializing known tokens...")
                    await self.token_discovery.initialize_known_tokens(chain_key)

                # Discover new tokens from blocks
                await self.token_discovery.discover_tokens_from_blocks(chain_key, blocks_to_scan=5)

                # Get all tokens that need price updates
                current_time = time.time()
                tokens_to_update = []
                for token in self.state.observed_tokens:
                    last_updated = self.last_price_update.get(token, 0)
                    if current_time - last_updated > 10:
                        tokens_to_update.append(token)

                logger.info(f"Updating prices for {len(tokens_to_update)} tokens")
                # Update prices for tokens that need it
                for token in tokens_to_update:
                    try:
                        # Skip WETH/ETH as price is always 1.0
                        if norm(token) == norm(wrapped_native):
                            self.state.prices[token] = 1.0
                            self.token_discovery._update_price_history(token, 1.0)
                            self.last_price_update[token] = current_time
                            continue

                        # Try to get price from existing pools
                        price = await self._get_price_for_token(token, chain_key)
                        if price is not None:
                            self.state.prices[token] = price
                            self.token_discovery._update_price_history(token, price)
                            self.last_price_update[token] = current_time
                            logger.info(f"Updated price for {short(token)}: {price:.8f} ETH")
                            continue

                        # If we still don't have a price, log but don't remove the token
                        if token not in self.state.prices:
                            logger.debug(f"No price found for {short(token)} (will retry)")

                    except Exception as e:
                        logger.error(f"Error updating price for {short(token)}: {e}", exc_info=True)
                        continue

                self.state.last_price_update = current_time
                logger.info(f"Price update complete. Updated {len(tokens_to_update)} tokens")

            except Exception as e:
                logger.error(f"Error in price update: {e}", exc_info=True)

    async def _get_price_for_token(self, token: str, chain_key: str) -> Optional[float]:
        """Get price for a token by finding its pool with WETH."""
        chain_config = CHAINS[chain_key]
        wrapped_native = to_checksum_address(chain_config["wrappedNative"])

        # First, try to get the checksummed address
        token_checksum = to_checksum_address(token)

        # Try all fee tiers
        for fee in [POOL_FEES["MEDIUM"], POOL_FEES["LOW"], POOL_FEES["HIGH"]]:
            try:
                pool_address = await self.blockchain.get_pool_address(
                    token_checksum, wrapped_native, fee, chain_key
                )
                if pool_address:
                    price = await self.blockchain.get_pool_price(pool_address, chain_key)
                    if price is not None:
                        logger.debug(f"Got price for {short(token)} from pool {short(pool_address)} (fee: {fee}): {price}")
                        return price
            except Exception as e:
                logger.debug(f"Error getting price for {short(token)} at fee {fee}: {e}")
                continue

        logger.debug(f"No price found for {short(token)} after trying all fee tiers")
        return None

# ========== STATE PERSISTENCE ==========
class StateManager:
    def __init__(self, state: State):
        self.state = state
        self.data_dir = "data"
        os.makedirs(self.data_dir, exist_ok=True)

    def save_state(self):
        try:
            with open(os.path.join(self.data_dir, "full_state.json"), "w") as f:
                json.dump(self.state.to_dict(), f, indent=2)
            logger.info("State saved to data/full_state.json")
        except Exception as e:
            logger.error(f"Error saving state: {e}", exc_info=True)

    def load_state(self) -> bool:
        try:
            full_state_path = os.path.join(self.data_dir, "full_state.json")
            if not os.path.exists(full_state_path):
                logger.info("No saved state found")
                return False
            with open(full_state_path, "r") as f:
                state_dict = json.load(f)
            self.state.from_dict(state_dict)
            logger.info("State loaded from data/full_state.json")
            return True
        except Exception as e:
            logger.error(f"Error loading state: {e}", exc_info=True)
            return False

# ========== MAIN BOT CLASS ==========
class Bot:
    def __init__(self, config: Optional[Config] = None, parameter_ranges: Optional[Dict[str, ParameterRange]] = None):
        self.config = config or Config()
        self.state = State(self.config)
        self.parameter_ranges = parameter_ranges or DEFAULT_PARAMETER_RANGES
        self.optimizer = ParameterOptimizer(self.state, self.parameter_ranges)
        self.trader = Trader(self.state, self.optimizer)
        self.price_updater = PriceUpdater(self.state)
        self.state_manager = StateManager(self.state)
        self.running = False
        self._event_loop = None
        self._event_loop_thread = None

    def _start_event_loop(self):
        """Start a dedicated event loop in a background thread."""
        if self._event_loop is not None:
            logger.warning("Event loop already started")
            return

        def run_loop():
            self._event_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._event_loop)
            logger.info("Event loop started in background thread")
            self._event_loop.run_forever()

        self._event_loop_thread = threading.Thread(target=run_loop, daemon=True)
        self._event_loop_thread.start()
        time.sleep(0.1)  # Give the loop time to start
        logger.info("Background event loop initialized")

    def _stop_event_loop(self):
        """Stop the event loop."""
        if self._event_loop is not None:
            logger.info("Stopping event loop...")
            self._event_loop.call_soon_threadsafe(self._event_loop.stop)
            if self._event_loop_thread:
                self._event_loop_thread.join(timeout=1)
            self._event_loop = None
            self._event_loop_thread = None
            logger.info("Event loop stopped")

    def start(self):
        if self.running:
            logger.info("Bot is already running")
            return

        logger.info("Starting Uniswap Quick Swap Trader (Profit-Only Mode)...")
        logger.info(f"Generated {len(self.optimizer.parameter_sets)} parameter sets from ranges.")

        self._start_event_loop()

        self.running = True
        self.state.is_running = True
        self.state.start_time = time.time()

        # Initialize known tokens
        logger.info("Initializing known tokens...")
        asyncio.run_coroutine_threadsafe(
            self.trader.token_discovery.initialize_known_tokens(self.state.current_chain_key),
            self._event_loop
        )

        # Start price updates
        async def price_loop():
            while self.running:
                logger.debug("Running price update loop...")
                await self.price_updater.update_prices()
                await asyncio.sleep(10)

        asyncio.run_coroutine_threadsafe(price_loop(), self._event_loop)

        # Start pattern detection
        self.trader.start_pattern_detection()

        # Start state saving
        def state_saver():
            while self.running:
                logger.debug("Saving state...")
                self.state_manager.save_state()
                time.sleep(30)

        threading.Thread(target=state_saver, daemon=True).start()

        # Start pattern checking
        async def pattern_checker():
            while self.running:
                logger.debug("Running pattern checker...")
                for token in list(self.state.observed_tokens):
                    await self.trader.check_patterns_for_token(token)
                await asyncio.sleep(1)

        asyncio.run_coroutine_threadsafe(pattern_checker(), self._event_loop)

        logger.info("Bot started! Press Ctrl+C to stop.")
        logger.info("Commands: status, prices, params, stop, reset, help")
        self._interactive_loop()

    def stop(self):
        if not self.running:
            logger.info("Bot is not running")
            return

        logger.info("Stopping bot...")
        self.running = False
        self.state.is_running = False
        self.state.manually_stopped = True
        self.trader.stop_pattern_detection()
        self._stop_event_loop()
        self.state_manager.save_state()
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
        status = self._get_status()
        print("\n=== Uniswap Quick Swap Trader v7.0.0 - Enhanced Debug Mode ===")
        print(f"Status: {'Running' if status['is_running'] else 'Stopped'}")
        print(f"Uptime: {status['uptime']}")
        print(f"Live Mode: {'ON' if self.trader.live_mode else 'OFF (shadow mode)'}")
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
        print("\n--- Parameter Set Performance ---")
        for i, params in enumerate(self.optimizer.parameter_sets):
            perf = self.optimizer.performance[i]
            marker = " (BEST)" if i == self.optimizer.best_set_index else ""
            print(f"Set {i}{marker}: Profit={perf['profit']:.6f} ETH, Trades={perf['trades']}, Winning={perf['winning_trades']}")

        open_positions = [p for p in self.state.portfolio["positions"] if p["status"] == "open"]
        if open_positions:
            print("\n--- Open Positions ---")
            for pos in open_positions:
                current_price = self.trader.state.get_token_price(pos["token"]) or pos["entry_price"]
                current_value = pos["amount"] * current_price
                unrealized_pnl = current_value - (pos["amount"] * pos["entry_price"]) - pos["fees_paid"] - pos["gas_paid"]
                cost_basis = (pos["amount"] * pos["entry_price"]) + pos["fees_paid"] + pos["gas_paid"]
                return_pct = (unrealized_pnl / cost_basis) * 100 if cost_basis > 0 else 0
                age = int(time.time() - pos["entry_time"])
                set_index = pos.get("parameter_set_index", "N/A")
                print(f"{pos['token']}: Bought at {pos['entry_price']:.8f}, Amount: {pos['amount']:.8f}, Value: {current_value:.8f} ETH, PnL: {unrealized_pnl:+.8f} ETH ({return_pct:+.2f}%), Age: {age}s, Param Set: {set_index}")

        if self.state.trades:
            print("\n--- Recent Trades ---")
            for trade in self.state.trades[-5:]:
                pnl_str = f"+{trade['pnl']:.8f}" if trade["pnl"] >= 0 else f"{trade['pnl']:.8f}"
                set_index = trade.get("parameter_set_index", "N/A")
                print(f"{trade['timestamp'][:19]} | {trade['token']} | {trade['type'].upper()} | Price: {trade['price']:.8f} | Amount: {trade['token_amount']:.8f} | PnL: {pnl_str} | Param Set: {set_index}")

    def print_prices(self):
        print("\n--- Current Prices ---")
        addr_to_symbol = {**self.state.token_symbols, **{v: k for k, v in self.state.token_addresses.items()}}
        for token, price in sorted(self.state.prices.items()):
            symbol = addr_to_symbol.get(token, short(token))
            history = self.state.price_history.get(token, [])
            change_pct = 0
            if len(history) >= 2:
                oldest = history[0]
                newest = history[-1]
                if newest["timestamp"] > oldest["timestamp"]:
                    change_pct = ((newest["price"] - oldest["price"]) / oldest["price"]) * 100
            change_symbol = "↑" if change_pct > 0 else "↓" if change_pct < 0 else " "
            print(f"{symbol}: {price:.8f} ETH ({change_symbol}{abs(change_pct):.2f}%)")

    def print_parameters(self):
        print("\n--- Parameter Sets ---")
        for i, params in enumerate(self.optimizer.parameter_sets):
            perf = self.optimizer.performance[i]
            is_best = " (BEST)" if i == self.optimizer.best_set_index else ""
            print(f"\nSet {i}{is_best}:")
            for key, value in params.items():
                print(f"  {key}: {value}")
            print(f"  Performance: Profit={perf['profit']:.6f} ETH, Trades={perf['trades']}, Winning={perf['winning_trades']}")

    def reset(self):
        if self.running:
            print("Cannot reset while bot is running. Stop the bot first.")
            return
        if input("Are you sure you want to reset? This will clear all data. (y/n): ").lower() == "y":
            self._stop_event_loop()
            self.state = State(self.config)
            self.optimizer = ParameterOptimizer(self.state, self.parameter_ranges)
            self.trader = Trader(self.state, self.optimizer)
            self.price_updater = PriceUpdater(self.state)
            self.state_manager = StateManager(self.state)
            os.makedirs("data", exist_ok=True)
            for f in os.listdir("data"):
                os.remove(os.path.join("data", f))
            print("Bot reset!")
            logger.info("Bot reset by user.")

    def _get_status(self) -> Dict[str, Any]:
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
    print("Uniswap Quick Swap Trader v7.0.0 - Enhanced Debug Version")
    print("Profit-Only Mode: Buys dips and sells ONLY at profit")
    print("Arbitrum-Only Mode: Only works on Arbitrum network")
    print("Dynamic Token Discovery: Populates tokens from CoinGecko's Arbitrum list.")
    print("Enhanced Logging: Detailed logs for debugging\n")
    logger.info("Uniswap Quick Swap Trader v7.0.0 (Enhanced Debug) started.")

    bot = Bot()
    bot.state_manager.load_state()

    print("Commands:")
    print("  start   - Start the bot")
    print("  stop    - Stop the bot")
    print("  status  - Show current status")
    print("  prices  - Show current prices")
    print("  params  - Show parameter set performance")
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