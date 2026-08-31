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

    # Pattern Detection (Default Parameters)
    MIN_PRICE_CHANGE: float = 0.5  # %
    MIN_TIME_WINDOW: int = 5       # seconds
    MAX_TIME_WINDOW: int = 120     # seconds
    MIN_OCCURRENCES: int = 2

    # Profit Targets (PROFIT-ONLY MODE)
    MIN_PROFIT_PERCENT: float = 2.0  # Sell only if profit >= 2%

    # Safety
    MAX_SLIPPAGE: float = 0.5  # %
    MAX_GAS_PRICE: int = 200    # gwei
    GAS_LIMIT: int = 300000
    PREVENT_SEQUENTIAL_TRADES: bool = True

    # Data
    PRICE_HISTORY_DURATION: int = 24  # hours
    MAX_PRICE_HISTORY: int = 5000

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
            # Arbitrum top pools by liquidity (token0, token1, fee)
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
        self.web3_providers: Dict[str, Web3] = {}
        self.token_decimals: Dict[str, int] = {}
        self.token_symbols: Dict[str, str] = {}  # address -> symbol

    def to_dict(self) -> Dict[str, Any]:
        return {
            "config": asdict(self.config),
            "is_running": self.is_running,
            "current_network": self.current_network,
            "prices": self.prices,
            "price_history": self.price_history,
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
            "timestamp": datetime.now().isoformat(),
        }

# ========== PARAMETER OPTIMIZER ==========
class ParameterOptimizer:
    def __init__(self, state: State):
        self.state = state
        self.parameter_sets = self._generate_parameter_sets()
        self.performance: Dict[int, Dict[str, float]] = {
            i: {"profit": 0.0, "trades": 0, "winning_trades": 0}
            for i in range(len(self.parameter_sets))
        }
        self.best_set_index = 0
        self.last_optimization_time = 0
        self.optimization_interval = 300  # 5 minutes

    def _generate_parameter_sets(self) -> List[Dict[str, float]]:
        """Generate a list of parameter sets to test."""
        return [
            # Aggressive: Low thresholds, quick trades
            {
                "MIN_PRICE_CHANGE": 0.1,
                "MIN_TIME_WINDOW": 3,
                "MAX_TIME_WINDOW": 60,
                "MIN_OCCURRENCES": 2,
                "MIN_PROFIT_PERCENT": 1.0,
            },
            # Moderate: Balanced
            {
                "MIN_PRICE_CHANGE": 0.5,
                "MIN_TIME_WINDOW": 5,
                "MAX_TIME_WINDOW": 120,
                "MIN_OCCURRENCES": 2,
                "MIN_PROFIT_PERCENT": 2.0,
            },
            # Conservative: High thresholds, safer trades
            {
                "MIN_PRICE_CHANGE": 1.0,
                "MIN_TIME_WINDOW": 10,
                "MAX_TIME_WINDOW": 300,
                "MIN_OCCURRENCES": 2,
                "MIN_PROFIT_PERCENT": 3.0,
            },
            # Very Aggressive
            {
                "MIN_PRICE_CHANGE": 0.05,
                "MIN_TIME_WINDOW": 2,
                "MAX_TIME_WINDOW": 30,
                "MIN_OCCURRENCES": 1,
                "MIN_PROFIT_PERCENT": 0.5,
            },
            # Long-term
            {
                "MIN_PRICE_CHANGE": 0.5,
                "MIN_TIME_WINDOW": 30,
                "MAX_TIME_WINDOW": 600,
                "MIN_OCCURRENCES": 2,
                "MIN_PROFIT_PERCENT": 5.0,
            },
        ]

    def detect_patterns_for_all_sets(self, token: str, history: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Run pattern detection with all parameter sets for a token."""
        if len(history) < 5:
            return []

        all_patterns = []
        for i, params in enumerate(self.parameter_sets):
            patterns = self._detect_patterns_with_params(history, token, params)
            for pattern in patterns:
                pattern["parameter_set_index"] = i
                all_patterns.append(pattern)

        return all_patterns

    def _detect_patterns_with_params(
        self, history: List[Dict[str, Any]], token: str, params: Dict[str, float]
    ) -> List[Dict[str, Any]]:
        """Detect patterns using specific parameters."""
        patterns = []
        min_change = params["MIN_PRICE_CHANGE"] / 100
        min_time = params["MIN_TIME_WINDOW"]
        max_time = params["MAX_TIME_WINDOW"]
        min_occurrences = params["MIN_OCCURRENCES"]
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

                            if (
                                rise_pct >= (min_profit / 100)
                                and min_time <= rise_time <= max_time
                            ):
                                patterns.append(
                                    {
                                        "type": "buy",
                                        "drop_pct": abs(drop_pct) * 100,
                                        "drop_time": time_diff,
                                        "rise_pct": rise_pct * 100,
                                        "rise_time": rise_time,
                                        "timestamp": current["timestamp"],
                                        "parameter_set_index": self.parameter_sets.index(params),
                                    }
                                )
                                break
                        break
        return patterns

    def update_performance(self, parameter_set_index: int, profit: float, is_winning: bool):
        """Update performance tracking for a parameter set."""
        if parameter_set_index in self.performance:
            self.performance[parameter_set_index]["profit"] += profit
            self.performance[parameter_set_index]["trades"] += 1
            if is_winning:
                self.performance[parameter_set_index]["winning_trades"] += 1

    def get_best_parameter_set(self) -> Dict[str, float]:
        """Get the best performing parameter set."""
        best_index = 0
        best_score = -float("inf")

        for i, perf in self.performance.items():
            # Score = profit * win_rate (avoid division by zero)
            win_rate = perf["winning_trades"] / perf["trades"] if perf["trades"] > 0 else 0
            score = perf["profit"] * win_rate
            if score > best_score:
                best_score = score
                best_index = i

        self.best_set_index = best_index
        logger.info(
            f"Best parameter set: {self.parameter_sets[best_index]} (Score: {best_score:.6f}, "
            f"Profit: {self.performance[best_index]['profit']:.6f}, "
            f"Trades: {self.performance[best_index]['trades']})"
        )
        return self.parameter_sets[best_index]

    def get_current_best_parameters(self) -> Dict[str, float]:
        """Get the current best parameters."""
        return self.parameter_sets[self.best_set_index]

    def optimize(self):
        """Run optimization to update the best parameter set."""
        if time.time() - self.last_optimization_time < self.optimization_interval:
            return

        self.get_best_parameter_set()
        self.last_optimization_time = time.time()

# ========== PATTERN DETECTION ==========
class PatternDetector:
    def __init__(self, state: State, optimizer: ParameterOptimizer):
        self.state = state
        self.config = state.config
        self.optimizer = optimizer

    def detect_all_patterns(self):
        """Detect patterns for all observed tokens using the best parameter set."""
        tokens = list(self.state.observed_tokens)
        new_active_patterns = {}
        best_params = self.optimizer.get_current_best_parameters()

        for token in tokens:
            history = self.state.price_history.get(token, [])
            if len(history) < 5:
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
                        "last_seen": pattern["timestamp"],
                        "parameter_set_index": self.optimizer.best_set_index,
                    }
                else:
                    existing = new_active_patterns[existing_key]
                    existing["occurrences"] += 1
                    existing["last_seen"] = max(existing["last_seen"], pattern["timestamp"])

        self._validate_patterns(new_active_patterns, best_params)
        self.state.active_patterns = new_active_patterns
        self._update_pattern_stats()
        self.state.last_detection_time = time.time()
        logger.info(
            f"Detected {len(new_active_patterns)} patterns across {len(tokens)} tokens "
            f"using parameter set {self.optimizer.best_set_index}."
        )

    def _detect_buy_patterns(
        self, history: List[Dict[str, Any]], token: str, params: Dict[str, float]
    ) -> List[Dict[str, Any]]:
        """Detect buy patterns (dips + rises) for a token using specific parameters."""
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

                            if (
                                rise_pct >= (min_profit / 100)
                                and min_time <= rise_time <= max_time
                            ):
                                patterns.append(
                                    {
                                        "type": "buy",
                                        "drop_pct": abs(drop_pct) * 100,
                                        "drop_time": time_diff,
                                        "rise_pct": rise_pct * 100,
                                        "rise_time": rise_time,
                                        "timestamp": current["timestamp"],
                                    }
                                )
                                break
                        break
        return patterns

    def _is_valid_pattern(self, pattern: Dict[str, Any], params: Dict[str, float]) -> bool:
        """Check if a pattern meets validity criteria."""
        if pattern["drop_pct"] > 100 or pattern["rise_pct"] > 100:
            return False
        if pattern["drop_pct"] < 0 or pattern["rise_pct"] < 0:
            return False
        if pattern["drop_time"] > 100 or pattern["rise_time"] > 100:
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
        keys_to_delete = []
        for key, pattern in patterns.items():
            if pattern["drop_pct"] <= 0 or pattern["rise_pct"] <= 0:
                keys_to_delete.append(key)
            elif pattern["rise_pct"] < params["MIN_PROFIT_PERCENT"]:
                keys_to_delete.append(key)
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
        self.config = state.config
        self.chains = CHAINS
        self.web3_providers: Dict[str, Web3] = {}
        self.factory_contracts: Dict[str, Any] = {}
        self.pool_contracts: Dict[str, Any] = {}
        self.token_contracts: Dict[str, Any] = {}
        self._initialize_providers()

    def _initialize_providers(self):
        from web3.middleware import ExtraDataToPOAMiddleware

        for chain_key, chain_config in self.chains.items():
            rpc_url = chain_config["rpcs"][0]
            if "wss:" in rpc_url:
                provider = Web3.WebsocketProvider(rpc_url)
            else:
                provider = Web3.HTTPProvider(rpc_url)
            w3 = Web3(provider)

            # Inject POA middleware for POA chains (Arbitrum, Base, Optimism, Polygon)
            if chain_key in ["polygon", "arbitrum", "base", "optimism"]:
                # FIXED: Pass an instance () and provide a unique string name
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

    async def get_pool_address(
        self, token0: str, token1: str, fee: int, chain_key: str
    ) -> Optional[str]:
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
            return 18  # Default to 18

    async def get_token_symbol(self, token_address: str, chain_key: str) -> str:
        if token_address in self.state.token_symbols:
            return self.state.token_symbols[token_address]
        try:
            token_contract = await self.get_token_contract(token_address, chain_key)
            symbol = token_contract.functions.symbol().call()
            self.state.token_symbols[token_address] = symbol
            return symbol
        except Exception as e:
            logger.error(f"Error getting token symbol: {e}")
            return short(token_address)

    def get_eth_price_in_wei(self, chain_key: str) -> int:
        w3 = self.get_web3(chain_key)
        return w3.eth.gas_price

    async def send_transaction(self, tx: Dict[str, Any], chain_key: str) -> Optional[str]:
        try:
            if not os.getenv("PRIVATE_KEY"):
                logger.warning("No PRIVATE_KEY set. Running in shadow mode (simulated trades only).")
                return None

            w3 = self.get_web3(chain_key)
            private_key = os.getenv("PRIVATE_KEY")
            account = w3.eth.account.from_key(private_key)
            tx["from"] = account.address
            tx["nonce"] = w3.eth.get_transaction_count(account.address)
            tx["gasPrice"] = w3.eth.gas_price
            tx["chainId"] = self.chains[chain_key]["chainId"]

            signed_tx = account.sign_transaction(tx)
            tx_hash = w3.eth.send_raw_transaction(signed_tx.rawTransaction)
            return tx_hash.hex()
        except Exception as e:
            logger.error(f"Error sending transaction: {e}")
            return None

def norm(a: str) -> str:
    return a.lower() if a else ""

def short(a: str) -> str:
    if not a:
        return ""
    return a[:6] + "..." + a[-4:]

# ========== TRADE EXECUTION & PORTFOLIO ==========
class Trader:
    def __init__(self, state: State, optimizer: ParameterOptimizer):
        self.state = state
        self.config = state.config
        self.optimizer = optimizer
        self.detector = PatternDetector(state, optimizer)
        self.blockchain = BlockchainHelper(state)
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
            trade_amount = min(trade_amount, available_eth * 0.95)
            return trade_amount
        except Exception as e:
            logger.error(f"Error calculating trade amount: {e}")
            return self.config.MIN_TRADE_AMOUNT_ETH

    def simulate_trade(
        self, token: str, action: str, token_amount: float, current_price: float
    ) -> Dict[str, Any]:
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
        self,
        token: str,
        action: str,
        price: float,
        token_amount: float,
        amount_eth: float,
        pattern: str,
        status: str,
        reason: Optional[str] = None,
        parameter_set_index: Optional[int] = None,
        **kwargs,
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
                [
                    p
                    for p in self.state.portfolio["positions"]
                    if p["token"] == token and p["status"] == "open"
                ],
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

        # Update parameter optimizer performance
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
            price_in_eth = self.state.prices.get(token, 0)
            total_eth += amount * price_in_eth

        for position in self.state.portfolio["positions"]:
            if position["status"] == "open":
                current_price = self.state.prices.get(position["token"], position["entry_price"])
                current_value = position["amount"] * current_price
                unrealized_pnl = (
                    current_value - (position["amount"] * position["entry_price"]) - position["fees_paid"] - position["gas_paid"]
                )
                total_eth += unrealized_pnl

        self.state.portfolio["current_eth"] = total_eth
        self.state.portfolio["unrealized_pnl"] = (
            total_eth - self.state.portfolio["starting_eth"] - self.state.portfolio["realized_pnl"]
        )

        self.state.portfolio["equity_history"].append(
            {"timestamp": time.time(), "eth_value": total_eth}
        )
        if len(self.state.portfolio["equity_history"]) > 1000:
            self.state.portfolio["equity_history"] = self.state.portfolio["equity_history"][-1000:]

    async def execute_trade(
        self,
        token: str,
        action: str,
        pattern_desc: str = "Manual",
        amount_eth: Optional[float] = None,
        pattern: Optional[Dict[str, Any]] = None,
        parameter_set_index: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        if not self.state.is_running:
            return None

        if amount_eth is None:
            amount_eth = self.calculate_trade_amount()

        current_price = self.state.prices.get(token)
        if current_price is None:
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
            logger.info(
                f"Gas price too high: {self.state.current_gas_price:.2f} gwei > {self.config.MAX_GAS_PRICE} gwei"
            )
            return None

        if action == "sell":
            token_balance = self.state.portfolio["balances"].get(token, 0)
            if token_balance <= 0:
                return None

        token_amount = amount_eth / current_price
        trade_result = self.simulate_trade(token, action, token_amount, current_price)
        if not trade_result["success"]:
            failed_trade = self.create_trade(
                token,
                action,
                current_price,
                token_amount,
                amount_eth,
                pattern_desc,
                "failed",
                trade_result["reason"],
                parameter_set_index,
                **trade_result,
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
            token,
            action,
            trade_result["execution_price"],
            token_amount,
            trade_result["amount_eth"],
            pattern_desc,
            "open",
            parameter_set_index=parameter_set_index,
            **trade_result,
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
            logger.info(
                f"[Set {parameter_set_index}] Bought {trade_result['token_amount']:.6f} {token} "
                f"at {trade_result['execution_price']:.8f} ETH"
            )

        if action == "sell":
            if token in self.state.open_buy_orders:
                del self.state.open_buy_orders[token]
            pnl_text = f"+{trade['pnl']:.8f}" if trade["pnl"] >= 0 else f"{trade['pnl']:.8f}"
            logger.info(
                f"[Set {parameter_set_index}] Sold {trade_result['token_amount']:.6f} {token} "
                f"at {trade_result['execution_price']:.8f} ETH (PnL: {pnl_text} ETH)"
            )
        return trade

    async def check_patterns_for_token(self, token: str):
        """Check for buy/sell opportunities for a token using the best parameter set."""
        if not self.state.is_running:
            return

        history = self.state.price_history.get(token, [])
        if len(history) < 2:
            return

        current_price = self.state.prices.get(token)
        if current_price is None:
            return

        best_params = self.optimizer.get_current_best_parameters()

        # Check for open position to sell at profit
        open_position = next(
            (p for p in self.state.portfolio["positions"] if p["token"] == token and p["status"] == "open"),
            None,
        )
        if open_position:
            current_value = open_position["amount"] * current_price
            cost_basis = (
                open_position["amount"] * open_position["entry_price"]
            ) + open_position["fees_paid"] + open_position["gas_paid"]
            profit_eth = current_value - cost_basis
            profit_pct = (profit_eth / cost_basis) * 100 if cost_basis > 0 else 0

            # Sell only if profit target is met
            if profit_pct >= best_params["MIN_PROFIT_PERCENT"] and profit_eth > 0:
                sell_amount_eth = open_position["amount"] * current_price
                parameter_set_index = open_position.get("parameter_set_index", 0)
                await self.execute_trade(
                    token,
                    "sell",
                    f"Profit target ({profit_pct:.2f}%) reached",
                    sell_amount_eth,
                    None,
                    parameter_set_index,
                )
                return

        # Check for buy opportunities using the best parameter set
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
                    token,
                    "buy",
                    f"Buy dip: {pattern['drop_pct']:.2f}% drop, {pattern['rise_pct']:.2f}% target",
                    trade_amount,
                    pattern,
                    pattern.get("parameter_set_index"),
                )

    def _check_pattern_match(self, token: str, pattern: Dict[str, Any]) -> bool:
        """Check if current price matches a pattern."""
        history = self.state.price_history.get(token, [])
        if len(history) < 2:
            return False

        current_price = self.state.prices.get(token)
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
                    if price_diff < 0.02:  # Within 2% of current price
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
                self.optimizer.optimize()  # Optimize parameters periodically
                time.sleep(3)

        threading.Thread(target=loop, daemon=True).start()

    def stop_pattern_detection(self):
        """Stop the pattern detection loop."""
        self.state.pattern_detection_active = False

# ========== PRICE UPDATER (DYNAMIC TOKEN DISCOVERY) ==========
class PriceUpdater:
    def __init__(self, state: State):
        self.state = state
        self.config = state.config
        self.blockchain = BlockchainHelper(state)
        self.chains = CHAINS
        self._initialize_known_tokens()

    def _initialize_known_tokens(self):
        """Initialize with top pools for the current chain."""
        chain_key = self.state.current_chain_key
        if chain_key in self.chains:
            for token0, token1, fee in self.chains[chain_key]["topPools"]:
                self.state.observed_tokens.add(token0)
                self.state.observed_tokens.add(token1)

    async def update_prices(self):
        """Update prices for all observed tokens and discover new tokens from pools."""
        try:
            chain_key = self.state.current_network
            chain_config = self.chains[chain_key]
            w3 = self.blockchain.get_web3(chain_key)

            # Get gas price
            gas_price_wei = w3.eth.gas_price
            self.state.current_gas_price = gas_price_wei / 1e9  # Convert to gwei
            logger.info(f"Gas price: {self.state.current_gas_price:.2f} gwei")

            # Get all observed tokens (including newly discovered ones)
            tokens_to_update = list(self.state.observed_tokens)
            wrapped_native = chain_config["wrappedNative"]

            # Always ensure wrapped native is in the list
            if wrapped_native not in tokens_to_update:
                tokens_to_update.append(wrapped_native)

            # Update prices for all tokens
            for token_address in tokens_to_update:
                try:
                    # Skip if we already have a recent price
                    if token_address in self.state.prices:
                        continue

                    # For WETH/ETH, price is 1.0
                    if token_address.lower() == wrapped_native.lower():
                        self.state.prices[token_address] = 1.0
                        self._update_price_history(token_address, 1.0)
                        continue

                    # Try to find a pool with this token and WETH
                    pool_address = await self.blockchain.get_pool_address(
                        token_address, wrapped_native, POOL_FEES["MEDIUM"], chain_key
                    )
                    if not pool_address:
                        # Try other fee tiers
                        for fee in [POOL_FEES["LOW"], POOL_FEES["HIGH"]]:
                            pool_address = await self.blockchain.get_pool_address(
                                token_address, wrapped_native, fee, chain_key
                            )
                            if pool_address:
                                break

                    if pool_address:
                        price = await self.blockchain.get_pool_price(pool_address, chain_key)
                        if price is not None:
                            self.state.prices[token_address] = price
                            self._update_price_history(token_address, price)

                            # Get token symbol
                            symbol = await self.blockchain.get_token_symbol(token_address, chain_key)
                            if symbol and symbol != short(token_address):
                                # Map address to symbol
                                self.state.token_symbols[token_address] = symbol
                                # Also add symbol to observed_tokens for easier reference
                                if symbol not in self.state.observed_tokens:
                                    self.state.observed_tokens.add(symbol)
                            continue

                    # If no pool found, remove from observed tokens
                    if token_address in self.state.observed_tokens:
                        self.state.observed_tokens.remove(token_address)
                        logger.warning(f"Removed {short(token_address)}: No pool found.")

                except Exception as e:
                    logger.error(f"Error updating price for {short(token_address)}: {e}")
                    continue

            # Discover new tokens from top pools
            await self._discover_new_tokens(chain_key)

            self.state.last_price_update = time.time()
        except Exception as e:
            logger.error(f"Error updating prices: {e}")

    async def _discover_new_tokens(self, chain_key: str):
        """Discover new tokens from top pools on the chain."""
        try:
            chain_config = self.chains[chain_key]
            wrapped_native = chain_config["wrappedNative"]

            # Get factory contract
            factory = await self.blockchain.get_factory_contract(chain_key)

            # Try to get some pool addresses from the factory
            # Note: This is a simplified approach. In production, you'd want to use a subgraph or event logs.
            # For now, we'll just use the topPools from the chain config.
            for token0, token1, fee in chain_config.get("topPools", []):
                # Ensure both tokens are in observed_tokens
                for token_addr in [token0, token1]:
                    if token_addr not in self.state.observed_tokens:
                        self.state.observed_tokens.add(token_addr)
                        logger.info(f"Discovered new token: {short(token_addr)}")

        except Exception as e:
            logger.error(f"Error discovering new tokens: {e}")

    def _update_price_history(self, token: str, price: float):
        """Update price history for a token."""
        if token not in self.state.price_history:
            self.state.price_history[token] = []
        self.state.price_history[token].append({"price": price, "timestamp": time.time()})

        # Trim by length
        if len(self.state.price_history[token]) > self.config.MAX_PRICE_HISTORY:
            self.state.price_history[token] = self.state.price_history[token][-self.config.MAX_PRICE_HISTORY :]

        # Trim by time
        duration_sec = self.config.PRICE_HISTORY_DURATION * 3600
        cutoff = time.time() - duration_sec
        while self.state.price_history[token] and self.state.price_history[token][0]["timestamp"] < cutoff:
            self.state.price_history[token].pop(0)

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
            self.state.config = Config(**state_dict["config"])
            self.state.is_running = state_dict["is_running"]
            self.state.current_network = state_dict["current_network"]
            self.state.prices = state_dict["prices"]
            self.state.price_history = state_dict["price_history"]
            self.state.trades = state_dict["trades"]
            self.state.active_patterns = state_dict["active_patterns"]
            self.state.portfolio = state_dict["portfolio"]
            self.state.last_traded_token = state_dict["last_traded_token"]
            self.state.last_trade_times = state_dict["last_trade_times"]
            self.state.start_time = state_dict["start_time"]
            self.state.last_price_update = state_dict["last_price_update"]
            self.state.current_gas_price = state_dict["current_gas_price"]
            self.state.observed_tokens = set(state_dict["observed_tokens"])
            self.state.pattern_stats = state_dict["pattern_stats"]
            self.state.open_buy_orders = state_dict["open_buy_orders"]
            self.state.token_symbols = state_dict.get("token_symbols", {})
            logger.info("State loaded from data/full_state.json.")
            return True
        except Exception as e:
            logger.error(f"Error loading state: {e}")
            return False

# ========== MAIN BOT CLASS ==========
class Bot:
    def __init__(self, config: Optional[Config] = None):
        self.config = config or Config()
        self.state = State(self.config)
        self.optimizer = ParameterOptimizer(self.state)
        self.trader = Trader(self.state, self.optimizer)
        self.price_updater = PriceUpdater(self.state)
        self.state_manager = StateManager(self.state)
        self.running = False

    def start(self):
        if self.running:
            logger.info("Bot is already running")
            return

        logger.info("Starting Uniswap Quick Swap Trader (Profit-Only Mode)...")
        logger.info(f"Using best parameter set: {self.optimizer.get_current_best_parameters()}")
        self.running = True
        self.state.is_running = True
        self.state.start_time = time.time()
        self.state.last_traded_token = None
        self.state.open_buy_orders = {}

        # Start price updates
        async def price_loop():
            while self.running:
                await self.price_updater.update_prices()
                await asyncio.sleep(10)  # Update every 10 seconds

        asyncio.run_coroutine_threadsafe(price_loop(), asyncio.new_event_loop())

        # Start pattern detection
        self.trader.start_pattern_detection()

        # Start state saving
        def state_saver():
            while self.running:
                self.state_manager.save_state()
                time.sleep(30)

        threading.Thread(target=state_saver, daemon=True).start()

        # Start pattern checking
        async def pattern_checker():
            while self.running:
                for token in list(self.state.observed_tokens):
                    await self.trader.check_patterns_for_token(token)
                await asyncio.sleep(1)

        asyncio.run_coroutine_threadsafe(pattern_checker(), asyncio.new_event_loop())

        logger.info("Bot started! Press Ctrl+C to stop.")
        logger.info("Commands: status, prices, stop, reset, help, params")

        # Start interactive loop
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

        # Print parameter set performance
        print("\n--- Parameter Set Performance ---")
        for i, params in enumerate(self.optimizer.parameter_sets):
            perf = self.optimizer.performance[i]
            print(
                f"Set {i}: Profit={perf['profit']:.6f} ETH, "
                f"Trades={perf['trades']}, "
                f"Winning={perf['winning_trades']}"
            )

        open_positions = [p for p in self.state.portfolio["positions"] if p["status"] == "open"]
        if open_positions:
            print("\n--- Open Positions ---")
            for pos in open_positions:
                current_price = self.state.prices.get(pos["token"], pos["entry_price"])
                current_value = pos["amount"] * current_price
                unrealized_pnl = (
                    current_value - (pos["amount"] * pos["entry_price"]) - pos["fees_paid"] - pos["gas_paid"]
                )
                cost_basis = (pos["amount"] * pos["entry_price"]) + pos["fees_paid"] + pos["gas_paid"]
                return_pct = (unrealized_pnl / cost_basis) * 100 if cost_basis > 0 else 0
                age = int(time.time() - pos["entry_time"])
                set_index = pos.get("parameter_set_index", "N/A")
                print(
                    f"{pos['token']}: Bought at {pos['entry_price']:.8f}, "
                    f"Amount: {pos['amount']:.8f}, Value: {current_value:.8f} ETH, "
                    f"PnL: {unrealized_pnl:+.8f} ETH ({return_pct:+.2f}%), "
                    f"Age: {age}s, Pattern: {pos.get('pattern', 'Manual')}, "
                    f"Param Set: {set_index}"
                )

        if self.state.trades:
            print("\n--- Recent Trades ---")
            for trade in self.state.trades[-5:]:
                pnl_str = f"+{trade['pnl']:.8f}" if trade["pnl"] >= 0 else f"{trade['pnl']:.8f}"
                set_index = trade.get("parameter_set_index", "N/A")
                print(
                    f"{trade['timestamp'][:19]} | {trade['token']} | {trade['type'].upper()} | "
                    f"Price: {trade['price']:.8f} | Amount: {trade['token_amount']:.8f} | "
                    f"PnL: {pnl_str} | Param Set: {set_index}"
                )

    def print_prices(self):
        print("\n--- Current Prices ---")
        for token, price in sorted(self.state.prices.items()):
            # Get symbol if available
            symbol = None
            for addr, sym in self.state.token_symbols.items():
                if addr.lower() == token.lower():
                    symbol = sym
                    break
            if not symbol:
                symbol = short(token)

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
            self.optimizer = ParameterOptimizer(self.state)
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
            "uptime": str(timedelta(seconds=int(time.time() - self.state.start_time)))
            if self.state.start_time
            else "00:00:00",
            "current_eth": self.state.portfolio["current_eth"],
            "realized_pnl": self.state.portfolio["realized_pnl"],
            "unrealized_pnl": self.state.portfolio["unrealized_pnl"],
            "net_pnl": net_pnl,
            "portfolio_return": (
                (net_pnl / self.state.portfolio["starting_eth"] * 100)
                if self.state.portfolio["starting_eth"] > 0
                else 0
            ),
            "total_trades": self.state.portfolio["total_trades"],
            "winning_trades": self.state.portfolio["winning_trades"],
            "losing_trades": self.state.portfolio["losing_trades"],
            "failed_trades": self.state.portfolio["failed_trades"],
            "win_rate": win_rate,
            "open_positions": len([p for p in self.state.portfolio["positions"] if p["status"] == "open"]),
            "tracked_tokens": len(self.state.observed_tokens),
            "active_patterns": self.state.pattern_stats["total_patterns"],
            "last_price_update": (
                datetime.fromtimestamp(self.state.last_price_update).strftime("%Y-%m-%d %H:%M:%S")
                if self.state.last_price_update
                else "Never"
            ),
            "current_gas_price": f"{self.state.current_gas_price:.2f} gwei",
        }

# ========== MAIN ==========
def main():
    print("Uniswap Quick Swap Trader v7.0.0 - Python Console Version")
    print("Profit-Only Mode: Buys dips and sells ONLY at profit\n")
    print("Dynamic Token Discovery: Monitors any detected tokens.")
    print("Parameter Optimization: Uses the best-performing pattern detection parameters.\n")
    logger.info("Uniswap Quick Swap Trader v7.0.0 started.")

    bot = Bot()
    bot.state_manager.load_state()  # Load previous state if available

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