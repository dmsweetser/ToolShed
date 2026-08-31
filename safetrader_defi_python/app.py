import os
import json
import time
import random
import math
import asyncio
import threading
import logging
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set, Tuple, Any
from dotenv import load_dotenv
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("app.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

# ========== PARAMETER GENERATION ==========
@dataclass
class ParameterRange:
    """Defines a range for a parameter (min, max, step)."""
    min: float
    max: float
    step: float

    def generate_values(self) -> List[float]:
        """Generate values from min to max with step."""
        values = []
        current = self.min
        while current <= self.max + 1e-9:  # Account for floating-point precision
            values.append(current)
            current += self.step
        return values

# Default parameter ranges for optimization
DEFAULT_PARAMETER_RANGES = {
    "MIN_PRICE_CHANGE": ParameterRange(min=0.05, max=2.0, step=0.05),
    "MIN_TIME_WINDOW": ParameterRange(min=2, max=30, step=2),
    "MAX_TIME_WINDOW": ParameterRange(min=30, max=600, step=30),
    "MIN_OCCURRENCES": ParameterRange(min=1, max=3, step=1),
    "MIN_PROFIT_PERCENT": ParameterRange(min=0.5, max=10.0, step=0.5),
}

class ParameterGenerator:
    """Generates parameter sets from defined ranges."""
    def __init__(self, ranges: Optional[Dict[str, ParameterRange]] = None, max_combinations: int = 50):
        self.ranges = ranges or DEFAULT_PARAMETER_RANGES
        self.max_combinations = max_combinations
        self.parameter_sets = self._generate_parameter_sets()

    def _generate_parameter_sets(self) -> List[Dict[str, float]]:
        """Generate all or sampled combinations from ranges."""
        param_values = {name: rng.generate_values() for name, rng in self.ranges.items()}
        total_combinations = 1
        for values in param_values.values():
            total_combinations *= len(values)

        if total_combinations <= self.max_combinations:
            return self._generate_all_combinations(param_values)
        else:
            return self._sample_combinations(param_values, self.max_combinations)

    def _generate_all_combinations(self, param_values: Dict[str, List[float]]) -> List[Dict[str, float]]:
        """Generate all possible combinations (cartesian product)."""
        from itertools import product
        param_names = list(param_values.keys())
        value_lists = [param_values[name] for name in param_names]
        return [dict(zip(param_names, combo)) for combo in product(*value_lists)]

    def _sample_combinations(self, param_values: Dict[str, List[float]], count: int) -> List[Dict[str, float]]:
        """Randomly sample combinations from the parameter space."""
        param_names = list(param_values.keys())
        value_lists = [param_values[name] for name in param_names]
        combinations = set()
        while len(combinations) < count:
            combo = tuple(random.choice(values) for values in value_lists)
            combinations.add(combo)
        return [dict(zip(param_names, combo)) for combo in combinations]

    def get_parameter_sets(self) -> List[Dict[str, float]]:
        """Return all generated parameter sets."""
        return self.parameter_sets

# ========== CONFIGURATION ==========
@dataclass
class Config:
    # Network
    BLOCKCHAIN_NETWORK: str = "arbitrum"
    UNISWAP_VERSION: str = "v3"

    # Trading Budget
    STARTING_ETH: float = 0.0033
    TRADE_AMOUNT_PERCENT: float = 0.5
    MIN_TRADE_AMOUNT_ETH: float = 0.0003
    MAX_TRADES: int = 10
    TRADE_COOLDOWN: int = 60  # seconds

    # Pattern Detection
    MIN_PRICE_CHANGE: float = 0.5
    MIN_TIME_WINDOW: int = 5
    MAX_TIME_WINDOW: int = 120
    MIN_OCCURRENCES: int = 2

    # Profit Targets (PROFIT-ONLY MODE)
    MIN_PROFIT_PERCENT: float = 2.0

    # Safety
    MAX_SLIPPAGE: float = 0.5
    MAX_GAS_PRICE: int = 200
    GAS_LIMIT: int = 300000
    PREVENT_SEQUENTIAL_TRADES: bool = True

    # Data
    PRICE_HISTORY_DURATION: int = 24  # hours
    MAX_PRICE_HISTORY: int = 5000

    # Optimization
    OPTIMIZATION_INTERVAL: int = 300  # 5 minutes
    MAX_PARAMETER_SETS: int = 50

# ========== CONSTANTS ==========
POOL_FEES = {"LOW": 500, "MEDIUM": 3000, "HIGH": 10000}
PATTERN_TYPES = {"BUY": "buy"}

# Chain Configurations
CHAINS = {
    "arbitrum": {
        "name": "Arbitrum One",
        "chainId": 42161,
        "rpcs": [
            os.getenv("ARBITRUM_RPC_URL", "https://arb1.arbitrum.io/rpc"),
            "https://arbitrum-mainnet.public.blastapi.io",
            "wss://arbitrum-one-rpc.publicnode.com"
        ],
        "factory": "0x1F98431c8aD98523631AE4a59f267346ea31F984",
        "wrappedNative": "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1",
        "quoteMode": "native",
        "quoteLabel": "ETH",
        "stables": [
            "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",  # USDC
            "0xFd086bC7CD5C481DCC9C85ebE478A1C0b69FCbb9",  # USDT
        ],
        "topPools": [
            ("0x82aF49447D8a07e3bd95BD0d56f35241523fBab1", "0x2f2a2543B76A416654947aaB75B4e35b52a17231", 3000),  # WETH/WBTC
            ("0x82aF49447D8a07e3bd95BD0d56f35241523fBab1", "0xfa7F8980b0f1E64A2062791cc3b0871572f1F7f0", 3000),  # WETH/UNI
            ("0x82aF49447D8a07e3bd95BD0d56f35241523fBab1", "0xf97f4df75117a78c1A5a0DBb814Af92458539FB4", 3000),  # WETH/LINK
            ("0x82aF49447D8a07e3bd95BD0d56f35241523fBab1", "0x912CE59144196C11c48067255325c5414506085A", 3000),  # WETH/ARB
            ("0x82aF49447D8a07e3bd95BD0d56f35241523fBab1", "0xfc5A1A6EB076a2C7aD06eD22C5C769A78b3Fa3A1", 3000),  # WETH/GMX
            ("0x82aF49447D8a07e3bd95BD0d56f35241523fBab1", "0xaf88d065e77c8cC2239327C5EDb3A432268e5831", 500),   # WETH/USDC
            ("0x82aF49447D8a07e3bd95BD0d56f35241523fBab1", "0xFd086bC7CD5C481DCC9C85ebE478A1C0b69FCbb9", 500),   # WETH/USDT
        ]
    },
    "ethereum": {
        "name": "Ethereum Mainnet",
        "chainId": 1,
        "rpcs": [
            os.getenv("ETHEREUM_RPC_URL", "https://eth.llamarpc.com"),
            "https://ethereum.publicnode.com",
        ],
        "factory": "0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f",
        "wrappedNative": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
        "quoteMode": "native",
        "quoteLabel": "ETH",
        "stables": [
            "0xA0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",  # USDC
            "0xdAC17F958D2ee523a2206206994597C13D831ec7",  # USDT
        ],
        "topPools": [
            ("0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2", "0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599", 3000),  # WETH/WBTC
            ("0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2", "0x1f9840a85d5aF5bf1D1762F925BDADDd9702f158", 3000),  # WETH/UNI
            ("0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2", "0x514910771AF9Ca656af840dff83E8264EcF986CA", 3000),  # WETH/LINK
            ("0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2", "0xA0b86991c6218b36c1d19d4a2e9eb0ce3606eb48", 500),   # WETH/USDC
            ("0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2", "0xdAC17F958D2ee523a2206206994597C13D831ec7", 500),   # WETH/USDT
        ]
    },
    "base": {
        "name": "Base",
        "chainId": 8453,
        "rpcs": [
            os.getenv("BASE_RPC_URL", "https://base-mainnet.public.blastapi.io"),
            "https://base-rpc.publicnode.com",
        ],
        "factory": "0x33128a8fC17869897dcE68Ed026d694621f6FDfD",
        "wrappedNative": "0x4200000000000000000000000000000000000006",
        "quoteMode": "native",
        "quoteLabel": "ETH",
        "stables": [
            "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",  # USDC
            "0x60a3e35cc302bfa44cb288bc5a4f316fdb1adb42",  # USDT
        ],
        "topPools": [
            ("0x4200000000000000000000000000000000000006", "0x6025518810202842D4E7b537291033197F2B498c", 3000),  # WETH/WBTC
            ("0x4200000000000000000000000000000000000006", "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913", 500),   # WETH/USDC
            ("0x4200000000000000000000000000000000000006", "0x60a3e35cc302bfa44cb288bc5a4f316fdb1adb42", 500),   # WETH/USDT
        ]
    },
    "optimism": {
        "name": "Optimism",
        "chainId": 10,
        "rpcs": [
            os.getenv("OPTIMISM_RPC_URL", "https://optimism-mainnet.public.blastapi.io"),
            "https://optimism-rpc.publicnode.com",
        ],
        "factory": "0x1F98431c8aD98523631AE4a59f267346ea31F984",
        "wrappedNative": "0x4200000000000000000000000000000000000006",
        "quoteMode": "native",
        "quoteLabel": "ETH",
        "stables": [
            "0x0b2C639c533813f4AaA9D7837CAf62653d097Ff85",  # USDC
            "0x7F5c764cBc14f9669B88837ca1490cCa17c31607",  # USDT
        ],
        "topPools": [
            ("0x4200000000000000000000000000000000000006", "0x68f180fcCe6836688e9084f035309fC299A09C00", 3000),  # WETH/WBTC
            ("0x4200000000000000000000000000000000000006", "0x0b2C639c533813f4AaA9D7837CAf62653d097Ff85", 500),   # WETH/USDC
            ("0x4200000000000000000000000000000000000006", "0x7F5c764cBc14f9669B88837ca1490cCa17c31607", 500),   # WETH/USDT
        ]
    },
    "polygon": {
        "name": "Polygon",
        "chainId": 137,
        "rpcs": [
            os.getenv("POLYGON_RPC_URL", "https://polygon-rpc.com"),
            "https://polygon-mainnet.public.blastapi.io",
        ],
        "factory": "0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f",
        "wrappedNative": "0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270",
        "quoteMode": "native",
        "quoteLabel": "WPOL",
        "stables": [
            "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174",  # USDC
            "0xc2132D05D31c914a87C6611C10748AEb04B58e8F",  # USDT
        ],
        "topPools": [
            ("0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270", "0x1BFD67037B42Cf73acF2047067bd4F2C47D9BfD6", 3000),  # WETH/WBTC
            ("0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270", "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174", 500),   # WETH/USDC
            ("0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270", "0xc2132D05D31c914a87C6611C10748AEb04B58e8F", 500),   # WETH/USDT
        ]
    },
}

# Uniswap V3 ABI snippets
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
    },
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
    }
]
''')

ERC20_ABI = json.loads('''
[
    {"inputs": [], "name": "symbol", "outputs": [{"internalType": "string", "name": "", "type": "string"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "decimals", "outputs": [{"internalType": "uint8", "name": "", "type": "uint8"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "name", "outputs": [{"internalType": "string", "name": "", "type": "string"}], "stateMutability": "view", "type": "function"},
    {"inputs": [{"internalType": "address", "name": "account", "type": "address"}], "name": "balanceOf", "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"}
]
''')

# ========== UTILITY FUNCTIONS ==========
def norm(a: str) -> str:
    """Normalize address to lowercase."""
    return a.lower() if a else ""

def short(a: str) -> str:
    """Shorten address for display."""
    if not a:
        return ""
    return f"{a[:6]}...{a[-4:]}"

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
        self.token_symbols: Dict[str, str] = {}  # address -> symbol
        self.token_addresses: Dict[str, str] = {}  # symbol -> address

    def to_dict(self) -> Dict[str, Any]:
        return {
            "config": asdict(self.config),
            "is_running": self.is_running,
            "current_network": self.current_network,
            "prices": self.prices,
            "price_history": {k: v for k, v in self.price_history.items()},  # Ensure JSON-serializable
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
        """Load state from dictionary."""
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

    def get_current_best_parameters(self) -> Dict[str, float]:
        """Find and return the best-performing parameter set."""
        if not self.parameter_sets:
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
        logger.info(
            f"Best parameter set #{best_index}: {self.parameter_sets[best_index]} "
            f"(Score: {best_score:.6f}, Profit: {self.performance[best_index]['profit']:.6f} ETH, "
            f"Trades: {self.performance[best_index]['trades']}, Winning: {self.performance[best_index]['winning_trades']})"
        )
        return self.parameter_sets[best_index]

    def get_next_parameter_set(self) -> Tuple[int, Dict[str, float]]:
        """Get the next parameter set for round-robin testing."""
        index = self.current_set_index
        param_set = self.parameter_sets[index]
        self.current_set_index = (self.current_set_index + 1) % len(self.parameter_sets)
        return index, param_set

    def update_performance(self, parameter_set_index: int, profit: float, is_winning: bool):
        """Update performance tracking for a parameter set."""
        if parameter_set_index in self.performance:
            self.performance[parameter_set_index]["profit"] += profit
            self.performance[parameter_set_index]["trades"] += 1
            if is_winning:
                self.performance[parameter_set_index]["winning_trades"] += 1

    def optimize(self):
        """Run optimization to update the best parameter set."""
        current_time = time.time()
        if current_time - self.last_optimization_time < self.optimization_interval:
            return
        self.get_current_best_parameters()
        self.last_optimization_time = current_time

# ========== TOKEN DISCOVERY ==========
class TokenDiscovery:
    def __init__(self, state: State, blockchain: 'BlockchainHelper'):
        self.state = state
        self.blockchain = blockchain
        self.active_pools: Set[str] = set()
        self.last_block: Dict[str, int] = {}
        self.swap_topic = "0xc42079f94a6436c4e6930f05045148f3556048be474e7962b362652246f71625"  # Uniswap V3 Swap event topic

    async def initialize_known_tokens(self, chain_key: str):
        """Initialize with WETH, stables, and top pool tokens."""
        chain_config = CHAINS[chain_key]
        wrapped_native = norm(chain_config["wrappedNative"])

        # Add WETH/ETH
        if wrapped_native not in self.state.observed_tokens:
            self.state.observed_tokens.add(wrapped_native)
            self.state.token_symbols[wrapped_native] = chain_config["quoteLabel"]
            self.state.token_addresses[chain_config["quoteLabel"]] = wrapped_native
            self.state.prices[wrapped_native] = 1.0
            self._update_price_history(wrapped_native, 1.0)

        # Add stables
        for stable in chain_config.get("stables", []):
            stable = norm(stable)
            if stable not in self.state.observed_tokens:
                self.state.observed_tokens.add(stable)
                try:
                    symbol = await self.blockchain.get_token_symbol(stable, chain_key)
                    self.state.token_symbols[stable] = symbol
                    self.state.token_addresses[symbol] = stable
                except Exception as e:
                    logger.warning(f"Could not get symbol for stable {short(stable)}: {e}")
                    self.state.token_symbols[stable] = "STABLE"
                    self.state.token_addresses["STABLE"] = stable

        # Add top pool tokens
        await self._add_top_pool_tokens(chain_key)

    async def _add_top_pool_tokens(self, chain_key: str):
        """Add tokens from the top pools for the chain."""
        chain_config = CHAINS[chain_key]
        for token0, token1, _ in chain_config.get("topPools", []):
            for token_addr in [norm(token0), norm(token1)]:
                if token_addr not in self.state.observed_tokens:
                    self.state.observed_tokens.add(token_addr)
                    try:
                        symbol = await self.blockchain.get_token_symbol(token_addr, chain_key)
                        if symbol and symbol != short(token_addr):
                            self.state.token_symbols[token_addr] = symbol
                            self.state.token_addresses[symbol] = token_addr
                    except Exception as e:
                        logger.warning(f"Could not get symbol for {short(token_addr)}: {e}")

    async def discover_tokens_from_blocks(self, chain_key: str, blocks_to_scan: int = 5):
        """Scan recent blocks for Swap events to discover new tokens."""
        try:
            w3 = self.blockchain.get_web3(chain_key)
            current_block = w3.eth.block_number
            last_scanned = self.last_block.get(chain_key, current_block - blocks_to_scan)

            if current_block <= last_scanned:
                return

            from_block = max(0, current_block - blocks_to_scan)
            to_block = current_block

            logger.debug(f"Scanning blocks {from_block} to {to_block} on {chain_key} for Swap events...")

            try:
                logs = w3.eth.get_logs({
                    'fromBlock': from_block,
                    'toBlock': to_block,
                    'topics': [self.swap_topic]
                })
            except Exception as e:
                logger.warning(f"Error fetching Swap logs: {e}")
                return

            new_tokens = set()
            for log in logs:
                try:
                    pool_address = norm(log['address'])
                    if pool_address in self.active_pools:
                        continue
                    self.active_pools.add(pool_address)

                    pool_contract = await self.blockchain.get_pool_contract(pool_address, chain_key)
                    token0 = norm(pool_contract.functions.token0().call())
                    token1 = norm(pool_contract.functions.token1().call())

                    new_tokens.update([token0, token1])
                except Exception as e:
                    logger.warning(f"Error processing Swap log: {e}")
                    continue

            for token_addr in new_tokens:
                if token_addr not in self.state.observed_tokens:
                    self.state.observed_tokens.add(token_addr)
                    logger.info(f"Discovered new token: {short(token_addr)}")
                    try:
                        symbol = await self.blockchain.get_token_symbol(token_addr, chain_key)
                        if symbol and symbol != short(token_addr):
                            self.state.token_symbols[token_addr] = symbol
                            self.state.token_addresses[symbol] = token_addr
                    except Exception as e:
                        logger.warning(f"Could not get symbol for {short(token_addr)}: {e}")

            self.last_block[chain_key] = current_block
        except Exception as e:
            logger.error(f"Error in token discovery: {e}")

    def _update_price_history(self, token: str, price: float):
        """Update price history for a token."""
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
        """Detect patterns for all observed tokens using the best parameter set."""
        tokens = list(self.state.observed_tokens)
        new_active_patterns = {}
        best_set_index, best_params = self.optimizer.get_next_parameter_set()

        for token in tokens:
            history = self.state.price_history.get(token, [])
            if len(history) < 5:
                continue
            buy_patterns = self._detect_buy_patterns(history, token, best_params, best_set_index)
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
                        "last_seen": pattern["timestamp"],
                        "parameter_set_index": best_set_index,
                    }
                else:
                    existing = new_active_patterns[existing_key]
                    existing["occurrences"] += 1
                    existing["last_seen"] = max(existing["last_seen"], pattern["timestamp"])

        self._validate_patterns(new_active_patterns, best_params)
        self.state.active_patterns = new_active_patterns
        self._update_pattern_stats()
        self.state.last_detection_time = time.time()

    def _detect_buy_patterns(
        self, history: List[Dict[str, Any]], token: str, params: Dict[str, float], set_index: int
    ) -> List[Dict[str, Any]]:
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
                                    "parameter_set_index": set_index,
                                })
                                break
                        break
        return patterns

    def _is_valid_pattern(self, pattern: Dict[str, Any], params: Dict[str, float]) -> bool:
        """Check if a pattern meets validity criteria."""
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
            del patterns[key]

    def _update_pattern_stats(self):
        """Update pattern statistics."""
        patterns_list = list(self.state.active_patterns.values())
        self.state.pattern_stats["total_patterns"] = len(patterns_list)
        self.state.pattern_stats["tokens_with_patterns"] = len({p["token"] for p in patterns_list})

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

    def _initialize_providers(self):
        for chain_key, chain_config in self.chains.items():
            rpc_url = chain_config["rpcs"][0]
            if "wss:" in rpc_url:
                provider = Web3.WebsocketProvider(rpc_url)
            else:
                provider = Web3.HTTPProvider(rpc_url)
            w3 = Web3(provider)
            if chain_key in ["polygon", "arbitrum", "base", "optimism"]:
                w3.middleware_onion.inject(ExtraDataToPOAMiddleware(), layer=0, name="extradata_to_poa")
            self.web3_providers[chain_key] = w3

    def get_web3(self, chain_key: str) -> Web3:
        if chain_key not in self.web3_providers:
            self._initialize_providers()
        return self.web3_providers[chain_key]

    async def get_factory_contract(self, chain_key: str) -> Any:
        if chain_key in self.factory_contracts:
            return self.factory_contracts[chain_key]
        w3 = self.get_web3(chain_key)
        chain_config = self.chains[chain_key]
        factory_contract = w3.eth.contract(
            address=Web3.to_checksum_address(chain_config["factory"]),
            abi=UNISWAP_V3_FACTORY_ABI,
        )
        self.factory_contracts[chain_key] = factory_contract
        return factory_contract

    async def get_pool_contract(self, pool_address: str, chain_key: str) -> Any:
        pool_address = Web3.to_checksum_address(pool_address)
        cache_key = f"{chain_key}_{pool_address}"
        if cache_key in self.pool_contracts:
            return self.pool_contracts[cache_key]
        w3 = self.get_web3(chain_key)
        pool_contract = w3.eth.contract(address=pool_address, abi=UNISWAP_V3_POOL_ABI)
        self.pool_contracts[cache_key] = pool_contract
        return pool_contract

    async def get_token_contract(self, token_address: str, chain_key: str) -> Any:
        token_address = Web3.to_checksum_address(token_address)
        cache_key = f"{chain_key}_{token_address}"
        if cache_key in self.token_contracts:
            return self.token_contracts[cache_key]
        w3 = self.get_web3(chain_key)
        token_contract = w3.eth.contract(address=token_address, abi=ERC20_ABI)
        self.token_contracts[cache_key] = token_contract
        return token_contract

    async def get_pool_address(self, token0: str, token1: str, fee: int, chain_key: str) -> Optional[str]:
        try:
            factory = await self.get_factory_contract(chain_key)
            pool_address = factory.functions.getPool(token0, token1, fee).call()
            if pool_address == "0x0000000000000000000000000000000000000000":
                return None
            return pool_address
        except Exception as e:
            logger.error(f"Error getting pool address: {e}")
            return None

    async def get_pool_price(self, pool_address: str, chain_key: str) -> Optional[float]:
        try:
            pool = await self.get_pool_contract(pool_address, chain_key)
            slot0 = pool.functions.slot0().call()
            sqrt_price_x96 = slot0[0]
            return self._sqrt_price_x96_to_price(sqrt_price_x96)
        except Exception as e:
            logger.error(f"Error getting pool price: {e}")
            return None

    def _sqrt_price_x96_to_price(self, sqrt_price_x96: int) -> float:
        sqrt_price = sqrt_price_x96 / (2**96)
        return sqrt_price * sqrt_price

    async def get_token_decimals(self, token_address: str, chain_key: str) -> int:
        if token_address in self.state.token_decimals:
            return self.state.token_decimals[token_address]
        try:
            token_contract = await self.get_token_contract(token_address, chain_key)
            decimals = token_contract.functions.decimals().call()
            self.state.token_decimals[token_address] = decimals
            return decimals
        except Exception as e:
            logger.error(f"Error getting token decimals: {e}")
            return 18

    async def get_token_symbol(self, token_address: str, chain_key: str) -> str:
        if token_address in self.state.token_symbols:
            return self.state.token_symbols[token_address]
        try:
            token_contract = await self.get_token_contract(token_address, chain_key)
            symbol = token_contract.functions.symbol().call()
            self.state.token_symbols[token_address] = symbol
            self.state.token_addresses[symbol] = token_address
            return symbol
        except Exception as e:
            logger.error(f"Error getting token symbol: {e}")
            return short(token_address)

# ========== TRADE EXECUTION & PORTFOLIO ==========
class Trader:
    def __init__(self, state: State, optimizer: ParameterOptimizer):
        self.state = state
        self.config = state.config
        self.optimizer = optimizer
        self.detector = PatternDetector(state, optimizer)
        self.blockchain = BlockchainHelper(state)
        self.token_discovery = TokenDiscovery(state, self.blockchain)
        self.live_mode = os.getenv("PRIVATE_KEY") is not None
        logger.info(f"Live mode: {'ON' if self.live_mode else 'OFF (shadow mode)'}")

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
        token_price = self.state.prices.get(token, 1.0)
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

    def _get_token_address(self, token: str) -> Optional[str]:
        """Resolve token to address (handles both symbols and addresses)."""
        if token in self.state.token_addresses:
            return self.state.token_addresses[token]
        if token in self.state.token_symbols:
            return token
        return None

    def _get_token_price(self, token: str) -> Optional[float]:
        """Get price for a token (handles both symbols and addresses)."""
        if token in self.state.prices:
            return self.state.prices[token]
        token_addr = self._get_token_address(token)
        if token_addr and token_addr in self.state.prices:
            return self.state.prices[token_addr]
        return None

    def _get_token_history(self, token: str) -> Optional[List[Dict[str, Any]]]:
        """Get price history for a token (handles both symbols and addresses)."""
        if token in self.state.price_history:
            return self.state.price_history[token]
        token_addr = self._get_token_address(token)
        if token_addr and token_addr in self.state.price_history:
            return self.state.price_history[token_addr]
        return None

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
                    "parameter_set_index": trade.get("parameter_set_index"),
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
            price_in_eth = self._get_token_price(token)
            if price_in_eth is not None:
                total_eth += amount * price_in_eth
        for position in self.state.portfolio["positions"]:
            if position["status"] == "open":
                current_price = self._get_token_price(position["token"]) or position["entry_price"]
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

    async def execute_trade(
        self, token: str, action: str, pattern_desc: str = "Manual",
        amount_eth: Optional[float] = None, pattern: Optional[Dict[str, Any]] = None,
        parameter_set_index: Optional[int] = None
    ) -> Optional[Dict[str, Any]]:
        if not self.state.is_running:
            return None
        if amount_eth is None:
            amount_eth = self.calculate_trade_amount()
        current_price = self._get_token_price(token)
        if current_price is None:
            logger.warning(f"No price available for token {token}")
            return None
        if amount_eth <= 0:
            return None
        open_positions = len([p for p in self.state.portfolio["positions"] if p["status"] == "open"])
        if open_positions >= self.config.MAX_TRADES:
            logger.info(f"Max trades ({self.config.MAX_TRADES}) reached")
            return None
        last_trade_time = self.state.last_trade_times.get(token)
        if last_trade_time and (time.time() - last_trade_time) < self.config.TRADE_COOLDOWN:
            return None
        if self.state.current_gas_price > self.config.MAX_GAS_PRICE:
            logger.info(f"Gas price too high: {self.state.current_gas_price:.2f} gwei > {self.config.MAX_GAS_PRICE} gwei")
            return None
        if action == "sell":
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
            self.state.trades.append(failed_trade)
            self.state.portfolio["failed_trades"] += 1
            self.state.portfolio["total_trades"] += 1
            logger.warning(f"Trade failed: {trade_result['reason']}")
            return failed_trade
        if self.config.PREVENT_SEQUENTIAL_TRADES and self.state.last_traded_token == token:
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
            logger.info(f"[Set {parameter_set_index}] Bought {trade_result['token_amount']:.6f} {token} at {trade_result['execution_price']:.8f} ETH")
        if action == "sell":
            if token in self.state.open_buy_orders:
                del self.state.open_buy_orders[token]
            pnl_text = f"+{trade['pnl']:.8f}" if trade["pnl"] >= 0 else f"{trade['pnl']:.8f}"
            logger.info(f"[Set {parameter_set_index}] Sold {trade_result['token_amount']:.6f} {token} at {trade_result['execution_price']:.8f} ETH (PnL: {pnl_text} ETH)")
        return trade

    async def check_patterns_for_token(self, token: str):
        """Check for buy/sell opportunities for a token."""
        if not self.state.is_running:
            return
        history = self._get_token_history(token)
        if history is None or len(history) < 2:
            return
        current_price = self._get_token_price(token)
        if current_price is None:
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
            if profit_pct >= best_params["MIN_PROFIT_PERCENT"] and profit_eth > 0:
                sell_amount_eth = open_position["amount"] * current_price
                parameter_set_index = open_position.get("parameter_set_index", 0)
                await self.execute_trade(
                    token, "sell", f"Profit target ({profit_pct:.2f}%) reached",
                    sell_amount_eth, None, parameter_set_index
                )
                return
        token_patterns = [
            p for p in self.state.active_patterns.values()
            if p["token"] == token and p.get("parameter_set_index") == self.optimizer.best_set_index
        ]
        buy_patterns = [p for p in token_patterns if p["type"] == "buy"]
        for pattern in buy_patterns:
            if self._check_pattern_match(token, pattern):
                if self.config.PREVENT_SEQUENTIAL_TRADES and self.state.last_traded_token == token:
                    continue
                if token in self.state.open_buy_orders:
                    continue
                trade_amount = self.calculate_trade_amount()
                await self.execute_trade(
                    token, "buy", f"Buy dip: {pattern['drop_pct']:.2f}% drop, {pattern['rise_pct']:.2f}% target",
                    trade_amount, pattern, pattern.get("parameter_set_index")
                )

    def _check_pattern_match(self, token: str, pattern: Dict[str, Any]) -> bool:
        """Check if current price matches a pattern."""
        history = self._get_token_history(token)
        if history is None or len(history) < 2:
            return False
        current_price = self._get_token_price(token)
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
        """Start the pattern detection loop."""
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
        """Stop the pattern detection loop."""
        self.state.pattern_detection_active = False

# ========== PRICE UPDATER ==========
class PriceUpdater:
    def __init__(self, state: State):
        self.state = state
        self.blockchain = BlockchainHelper(state)
        self.token_discovery = TokenDiscovery(state, self.blockchain)
        self.price_update_lock = threading.Lock()

    async def update_prices(self):
        """Update prices for all observed tokens and discover new ones."""
        with self.price_update_lock:
            try:
                chain_key = self.state.current_network
                chain_config = CHAINS[chain_key]
                w3 = self.blockchain.get_web3(chain_key)
                gas_price_wei = w3.eth.gas_price
                self.state.current_gas_price = gas_price_wei / 1e9
                wrapped_native = norm(chain_config["wrappedNative"])
                if not self.state.observed_tokens:
                    await self.token_discovery.initialize_known_tokens(chain_key)
                await self.token_discovery.discover_tokens_from_blocks(chain_key, blocks_to_scan=5)
                tokens_to_update = set(self.state.observed_tokens)
                for token in list(tokens_to_update):
                    try:
                        if token in self.state.prices:
                            continue
                        if norm(token) == wrapped_native:
                            self.state.prices[token] = 1.0
                            self.token_discovery._update_price_history(token, 1.0)
                            continue
                        pool_address = await self.blockchain.get_pool_address(
                            token, wrapped_native, POOL_FEES["MEDIUM"], chain_key
                        )
                        if not pool_address:
                            for fee in [POOL_FEES["LOW"], POOL_FEES["HIGH"]]:
                                pool_address = await self.blockchain.get_pool_address(
                                    token, wrapped_native, fee, chain_key
                                )
                                if pool_address:
                                    break
                        if pool_address:
                            price = await self.blockchain.get_pool_price(pool_address, chain_key)
                            if price is not None:
                                self.state.prices[token] = price
                                self.token_discovery._update_price_history(token, price)
                                continue
                        if token in self.state.observed_tokens:
                            logger.warning(f"Removed {short(token)}: No pool found.")
                            self.state.observed_tokens.remove(token)
                    except Exception as e:
                        logger.error(f"Error updating price for {short(token)}: {e}")
                        continue
                self.state.last_price_update = time.time()
            except Exception as e:
                logger.error(f"Error updating prices: {e}")

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
            logger.info("State saved to data/full_state.json.")
        except Exception as e:
            logger.error(f"Error saving state: {e}")

    def load_state(self) -> bool:
        try:
            full_state_path = os.path.join(self.data_dir, "full_state.json")
            if not os.path.exists(full_state_path):
                return False
            with open(full_state_path, "r") as f:
                state_dict = json.load(f)
            self.state.from_dict(state_dict)
            logger.info("State loaded from data/full_state.json.")
            return True
        except Exception as e:
            logger.error(f"Error loading state: {e}")
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

    def start(self):
        if self.running:
            logger.info("Bot is already running")
            return
        logger.info("Starting Uniswap Quick Swap Trader (Profit-Only Mode)...")
        logger.info(f"Generated {len(self.optimizer.parameter_sets)} parameter sets from ranges.")
        self.running = True
        self.state.is_running = True
        self.state.start_time = time.time()
        asyncio.run_coroutine_threadsafe(
            self.trader.token_discovery.initialize_known_tokens(self.state.current_chain_key),
            asyncio.new_event_loop()
        )
        async def price_loop():
            while self.running:
                await self.price_updater.update_prices()
                await asyncio.sleep(10)
        asyncio.run_coroutine_threadsafe(price_loop(), asyncio.new_event_loop())
        self.trader.start_pattern_detection()
        def state_saver():
            while self.running:
                self.state_manager.save_state()
                time.sleep(30)
        threading.Thread(target=state_saver, daemon=True).start()
        async def pattern_checker():
            while self.running:
                for token in list(self.state.observed_tokens):
                    await self.trader.check_patterns_for_token(token)
                await asyncio.sleep(1)
        asyncio.run_coroutine_threadsafe(pattern_checker(), asyncio.new_event_loop())
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
                    print("Commands: status, prices, params, stop, reset, help")
                elif cmd:
                    print("Unknown command. Type 'help' for options.")
        except KeyboardInterrupt:
            self.stop()

    def print_status(self):
        status = self._get_status()
        print("\n=== Uniswap Quick Swap Trader v7.0.0 - Profit-Only Mode ===")
        print(f"Status: {'Running' if status['is_running'] else 'Stopped'}")
        print(f"Uptime: {status['uptime']}")
        print(f"Live Mode: {'ON' if self.trader.live_mode else 'OFF (shadow mode)'}")
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
                current_price = self.trader._get_token_price(pos["token"]) or pos["entry_price"]
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
    print("Uniswap Quick Swap Trader v7.0.0 - Python Console Version")
    print("Profit-Only Mode: Buys dips and sells ONLY at profit")
    print("Dynamic Token Discovery: Monitors any detected tokens from swap events.")
    print("Parameter Optimization: Tests multiple parameter sets from ranges and uses the best performer.\n")
    logger.info("Uniswap Quick Swap Trader v7.0.0 started.")
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