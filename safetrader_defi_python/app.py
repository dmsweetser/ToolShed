# app.py
import os
import time
import math
import random
import string
import asyncio
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from enum import Enum
from flask import Flask, render_template, jsonify, request
from web3 import Web3, Account
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


# ====================
# ENUMS AND MODELS
# ====================

class TradeType(Enum):
    BUY = "buy"
    SELL = "sell"


class TradeStatus(Enum):
    OPEN = "open"
    CLOSED = "closed"
    FAILED = "failed"


class PatternType(Enum):
    BUY = "buy"
    SWELL = "swell"


@dataclass
class Trade:
    id: str
    timestamp: float
    token: str
    trade_type: TradeType
    price: float
    token_amount: float
    amount_eth: float
    fee: float
    gas_used: int
    gas_price: float
    price_impact: float
    slippage: float
    status: TradeStatus
    reason: Optional[str] = None
    pnl: float = 0.0
    pattern: Optional[str] = None
    pattern_obj: Optional[Dict] = None
    tx_hash: Optional[str] = None
    network: str = "arbitrum"
    entry_time: float = field(default_factory=time.time)


@dataclass
class Position:
    id: str
    token: str
    entry_price: float
    amount: float
    usd_value: float
    entry_time: float
    gas_paid: float
    fees_paid: float
    status: str = "open"
    trade_id: Optional[str] = None
    pattern: Optional[str] = None
    pattern_obj: Optional[Dict] = None
    exit_price: Optional[float] = None
    exit_time: Optional[float] = None
    pnl: float = 0.0
    sell_trade_id: Optional[str] = None


@dataclass
class Portfolio:
    balances: Dict[str, float] = field(default_factory=dict)
    positions: List[Position] = field(default_factory=list)
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    gas_spent: float = 0.0
    fees_paid: float = 0.0
    starting_eth: float = 0.01
    current_eth: float = 0.01
    equity_history: List[Dict[str, Any]] = field(default_factory=list)
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    failed_trades: int = 0
    total_fees: float = 0.0
    usdc_balance: float = 0.0
    usdc_profit: float = 0.0


@dataclass
class Pattern:
    type: PatternType
    token: str
    timestamp: float
    drop_pct: Optional[float] = None
    drop_time: Optional[float] = None
    rise_pct: Optional[float] = None
    rise_time: Optional[float] = None
    first_rise_pct: Optional[float] = None
    first_rise_time: Optional[float] = None
    second_rise_pct: Optional[float] = None
    second_rise_time: Optional[float] = None
    occurrences: int = 1
    first_seen: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)


@dataclass
class SwapRecord:
    timestamp: float
    token_in: str
    token_out: str
    amount_in: float
    amount_out: float
    pool: str


@dataclass
class AppState:
    is_running: bool = False
    current_network: str = "arbitrum"
    current_chain_key: str = "arbitrum"
    prices: Dict[str, float] = field(default_factory=dict)
    price_history: Dict[str, List[Dict[str, float]]] = field(default_factory=dict)
    trades: List[Trade] = field(default_factory=list)
    active_patterns: Dict[str, Pattern] = field(default_factory=dict)
    last_swaps: List[SwapRecord] = field(default_factory=list)
    portfolio: Portfolio = field(default_factory=Portfolio)
    last_traded_token: Optional[str] = None
    last_trade_times: Dict[str, float] = field(default_factory=dict)
    start_time: Optional[float] = None
    last_price_update: Optional[float] = None
    current_gas_price: float = 0.02
    manually_stopped: bool = True
    observed_tokens: set = field(default_factory=set)
    pattern_stats: Dict[str, int] = field(default_factory=dict)
    open_buy_orders: Dict[str, Dict] = field(default_factory=dict)
    pattern_detection_active: bool = False
    reconnect_attempts: int = 0
    max_reconnect_attempts: int = 10
    reconnect_delay: int = 1000
    wallet_connected: bool = False
    live_mode: bool = False
    provider: Optional[Any] = None
    signer: Optional[Any] = None
    session_serial: int = 0
    active_session: Optional[Any] = None
    current_rpc_index: int = 0
    last_detection_time: Optional[float] = None
    last_max_trade_toast: Optional[float] = None
    last_usdc_conversion: Optional[float] = None


# ====================
# CONFIGURATION
# ====================

class Config:
    # Wallet Configuration
    PRIVATE_KEY = os.getenv("PRIVATE_KEY")
    WALLET_ADDRESS = os.getenv("WALLET_ADDRESS")

    # Blockchain Configuration
    BLOCKCHAIN_NETWORK = os.getenv("BLOCKCHAIN_NETWORK", "arbitrum")
    RPC_URL = os.getenv("RPC_URL", "https://arbitrum-mainnet.public.blastapi.io")
    CHAIN_ID = int(os.getenv("CHAIN_ID", 42161))

    # Uniswap Configuration
    UNISWAP_VERSION = os.getenv("UNISWAP_VERSION", "v3")
    UNISWAP_ROUTER_ADDRESS = os.getenv("UNISWAP_ROUTER_ADDRESS", "0xE592427A0AEce92De3Edee1F18E0157C05861564")

    # Trading Configuration
    STARTING_ETH = float(os.getenv("STARTING_ETH", 0.01))
    TRADE_AMOUNT_PERCENT = int(os.getenv("TRADE_AMOUNT_PERCENT", 10))
    MIN_TRADE_AMOUNT_ETH = float(os.getenv("MIN_TRADE_AMOUNT_ETH", 0.001))
    MAX_TRADES = int(os.getenv("MAX_TRADES", 5))
    MIN_PROFIT_PERCENT = float(os.getenv("MIN_PROFIT_PERCENT", 0.5))
    MAX_SLIPPAGE = float(os.getenv("MAX_SLIPPAGE", 0.5))
    MAX_GAS_PRICE = int(os.getenv("MAX_GAS_PRICE", 500))
    GAS_LIMIT = int(os.getenv("GAS_LIMIT", 300000))
    TRADE_COOLDOWN = 60
    PREVENT_SEQUENTIAL_TRADES = True

    # Pattern Detection
    MIN_PRICE_CHANGE = 1.0
    MIN_TIME_WINDOW = 5
    MAX_TIME_WINDOW = 60
    MIN_OCCURRENCES = 2
    PRICE_HISTORY_DURATION = 24  # hours
    MAX_PRICE_HISTORY = 20000
    PATTERN_MODE = os.getenv("PATTERN_MODE", "both")  # 'both', 'dip', or 'swell'

    # USDC Configuration
    USDC_PROFIT_TARGET = float(os.getenv("USDC_PROFIT_TARGET", 1.0))
    USDC_ADDRESS = os.getenv("USDC_ADDRESS", "0xaf88d065e77c8cC2239327C5EDb3A432268e5831")
    WETH_ADDRESS = os.getenv("WETH_ADDRESS", "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1")
    USDC_CONVERSION_INTERVAL = 300000  # 5 minutes in milliseconds
    MIN_LIQUIDITY = 50000

    # Token Addresses
    NETWORK_TOKENS = {
        "arbitrum": {
            "WETH": "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1",
            "WBTC": "0x2f2a2543B76A416654947aaB75B4e35b52a17231",
            "UNI": "0xfa7F8980b0f1E64A2062791cc3b0871572f1F7f0",
            "LINK": "0xf97f4df75117a78c1A5a0DBb814Af92458539FB4",
            "ARB": "0x912CE59144196C11c48067255325c5414506085A",
            "GMX": "0xfc5A1A6EB076a2C7aD06eD22C5C769A78b3Fa3A1",
            "USDC": "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
            "USDT": "0xFd086bC7CD5C481DCC9C85ebE478A1C0b69FCbb9",
            "LEVY": "0x709232b2084659408421a351439f8462d450416f",
            "APEX": "0x5063C83912b5A8d352226578e47F845B1a8d5a2F",
        }
    }

    # Pool Fees
    POOL_FEES = {"LOW": 500, "MEDIUM": 3000, "HIGH": 10000}


# ====================
# UTILITY FUNCTIONS
# ====================

def generate_unique_trade_id() -> str:
    return f"trade_{int(time.time())}_{''.join(random.choices(string.ascii_lowercase + string.digits, k=9))}"


def format_number(num: float, decimals: int = 8) -> str:
    if num is None:
        return "0"
    return f"{num:.{decimals}f}"


def format_eth(value: float, decimals: int = 8) -> str:
    if value is None:
        return "0.00000000 WETH"
    return f"{value:.{decimals}f} WETH"


def format_usdc(value: float, decimals: int = 2) -> str:
    if value is None:
        return "0.00 USDC"
    return f"{value:.{decimals}f} USDC"


def format_percent(value: float, decimals: int = 2) -> str:
    if value is None:
        return "0.00%"
    return f"{value:.{decimals}f}%"


def format_uptime(start_time: float) -> str:
    if not start_time:
        return "00:00:00"
    now = time.time()
    diff = now - start_time
    hours = int(diff // 3600)
    minutes = int((diff % 3600) // 60)
    seconds = int(diff % 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


# ====================
# WALLET MANAGEMENT
# ====================

def connect_wallet(app_state: AppState) -> bool:
    try:
        private_key = Config.PRIVATE_KEY
        if not private_key:
            raise ValueError("PRIVATE_KEY not set in .env file")

        w3 = Web3(Web3.HTTPProvider(Config.RPC_URL))
        if not w3.is_connected():
            raise ConnectionError("Failed to connect to the blockchain network")

        account = Account.from_key(private_key)
        app_state.signer = account
        app_state.provider = w3
        app_state.wallet_connected = True
        app_state.wallet_address = account.address

        return True
    except Exception as e:
        print(f"Error connecting wallet: {e}")
        app_state.wallet_connected = False
        return False


def get_wallet_address(app_state: AppState) -> str:
    if app_state.signer:
        return app_state.signer.address
    return ""


def sign_transaction(app_state: AppState, tx: dict) -> str:
    if not app_state.signer:
        raise ValueError("Wallet not connected")
    if not app_state.provider:
        raise ValueError("Provider not initialized")

    try:
        tx["from"] = app_state.signer.address
        tx["chainId"] = Config.CHAIN_ID
        signed_tx = app_state.signer.sign_transaction(tx)
        return signed_tx.rawTransaction.hex()
    except Exception as e:
        print(f"Error signing transaction: {e}")
        raise


# ====================
# PATTERN DETECTION
# ====================

def detect_buy_patterns_for_token(history: List[Dict[str, float]], token: str) -> List[Pattern]:
    if not history or len(history) < 5:
        return []

    min_change = Config.MIN_PRICE_CHANGE / 100
    min_time = Config.MIN_TIME_WINDOW * 1000
    max_time = Config.MAX_TIME_WINDOW * 1000
    patterns = []

    for i in range(2, len(history) - 2):
        current = history[i]
        is_minima = (
            current["price"] <= history[i - 1]["price"] and
            current["price"] <= history[i - 2]["price"] and
            current["price"] <= history[i + 1]["price"] and
            current["price"] <= history[i + 2]["price"]
        )

        if is_minima:
            for j in range(i - 1, max(0, i - 5) - 1, -1):
                prev = history[j]
                drop_pct = (current["price"] - prev["price"]) / prev["price"]
                time_diff = current["timestamp"] - prev["timestamp"]

                if drop_pct <= -min_change and min_time <= time_diff <= max_time:
                    for k in range(i + 1, min(len(history), i + 6)):
                        next_point = history[k]
                        rise_pct = (next_point["price"] - current["price"]) / current["price"]
                        rise_time = next_point["timestamp"] - current["timestamp"]

                        if rise_pct >= Config.MIN_PROFIT_PERCENT / 100 and min_time <= rise_time <= max_time:
                            patterns.append(Pattern(
                                type=PatternType.BUY,
                                token=token,
                                timestamp=current["timestamp"],
                                drop_pct=abs(drop_pct) * 100,
                                drop_time=time_diff / 1000,
                                rise_pct=rise_pct * 100,
                                rise_time=rise_time / 1000
                            ))
                            break
                    break
    return patterns


def detect_swell_patterns_for_token(history: List[Dict[str, float]], token: str) -> List[Pattern]:
    if not history or len(history) < 5:
        return []

    min_change = Config.MIN_PRICE_CHANGE / 100
    min_time = Config.MIN_TIME_WINDOW * 1000
    max_time = Config.MAX_TIME_WINDOW * 1000
    patterns = []

    for i in range(2, len(history) - 2):
        current = history[i]

        for j in range(i - 1, max(0, i - 5) - 1, -1):
            prev = history[j]
            first_rise_pct = (current["price"] - prev["price"]) / prev["price"]
            first_rise_time = current["timestamp"] - prev["timestamp"]

            if first_rise_pct >= min_change and min_time <= first_rise_time <= max_time:
                for k in range(i + 1, min(len(history), i + 6)):
                    next_point = history[k]
                    second_rise_pct = (next_point["price"] - current["price"]) / current["price"]
                    second_rise_time = next_point["timestamp"] - current["timestamp"]

                    if second_rise_pct >= min_change and min_time <= second_rise_time <= max_time:
                        patterns.append(Pattern(
                            type=PatternType.SWELL,
                            token=token,
                            timestamp=current["timestamp"],
                            first_rise_pct=first_rise_pct * 100,
                            first_rise_time=first_rise_time / 1000,
                            second_rise_pct=second_rise_pct * 100,
                            second_rise_time=second_rise_time / 1000
                        ))
                        break
                break
    return patterns


def get_pattern_key(pattern: Pattern) -> str:
    if pattern.type == PatternType.BUY:
        return (
            f"BUY_{math.floor(pattern.drop_pct * 10) / 10}%_"
            f"{math.floor(pattern.drop_time)}s_"
            f"{math.floor(pattern.rise_pct * 10) / 10}%_"
            f"{math.floor(pattern.rise_time)}s"
        )
    elif pattern.type == PatternType.SWELL:
        return (
            f"SWELL_{math.floor(pattern.first_rise_pct * 10) / 10}%_"
            f"{math.floor(pattern.first_rise_time)}s_"
            f"{math.floor(pattern.second_rise_pct * 10) / 10}%_"
            f"{math.floor(pattern.second_rise_time)}s"
        )
    return "UNKNOWN"


def get_pattern_description(pattern: Pattern) -> str:
    if pattern.type == PatternType.BUY:
        return (
            f"Buy dip: {pattern.drop_pct:.2f}% over {pattern.drop_time}s, "
            f"target {pattern.rise_pct:.2f}% rise"
        )
    elif pattern.type == PatternType.SWELL:
        return (
            f"Swell: {pattern.first_rise_pct:.2f}% rise over {pattern.first_rise_time}s, "
            f"then {pattern.second_rise_pct:.2f}% rise"
        )
    return "Manual"


def is_pattern_valid(pattern: Pattern) -> bool:
    if pattern.type == PatternType.BUY:
        return pattern.drop_pct > 0 and pattern.rise_pct >= Config.MIN_PROFIT_PERCENT
    elif pattern.type == PatternType.SWELL:
        return pattern.first_rise_pct > 0 and pattern.second_rise_pct >= Config.MIN_PROFIT_PERCENT
    return False


# ====================
# TRADE EXECUTION
# ====================

def calculate_trade_amount(app_state: AppState) -> float:
    try:
        gas_price = app_state.current_gas_price or Config.MAX_GAS_PRICE
        gas_limit = Config.GAS_LIMIT
        available_weth = app_state.portfolio.current_eth or Config.STARTING_ETH
        gas_cost_per_trade = (gas_price * gas_limit) / 1e18
        max_trades = Config.MAX_TRADES
        total_gas_cost = gas_cost_per_trade * max_trades

        percent_based_amount = available_weth * (Config.TRADE_AMOUNT_PERCENT / 100)
        min_trade_amount_weth = Config.MIN_TRADE_AMOUNT_ETH

        trade_amount = max(
            percent_based_amount - (total_gas_cost / max_trades),
            min_trade_amount_weth
        )
        trade_amount = min(trade_amount, available_weth * 0.95)

        return trade_amount
    except Exception as e:
        print(f"Error calculating trade amount: {e}")
        return Config.MIN_TRADE_AMOUNT_ETH


def create_trade_object(
    token: str,
    action: TradeType,
    price: float,
    token_amount: float,
    amount_weth: float,
    pattern: Optional[str],
    status: TradeStatus,
    reason: Optional[str] = None,
    gas_used: int = 0,
    gas_price: float = 0,
    fee_amount: float = 0,
    price_impact: float = 0,
    slippage: float = 0,
    pattern_obj: Optional[Dict] = None
) -> Trade:
    return Trade(
        id=generate_unique_trade_id(),
        timestamp=time.time(),
        token=token,
        trade_type=action,
        price=price,
        token_amount=token_amount,
        amount_eth=amount_weth,
        fee=fee_amount,
        gas_used=gas_used,
        gas_price=gas_price,
        price_impact=price_impact,
        slippage=slippage,
        status=status,
        reason=reason,
        pnl=0.0,
        pattern=pattern,
        pattern_obj=pattern_obj,
        tx_hash=None,
        network=app_state.current_network,
        entry_time=time.time()
    )


def simulate_realistic_trade(
    app_state: AppState,
    token: str,
    action: TradeType,
    token_amount: float,
    current_price: float,
    pool_info: Dict,
    latency: float = 0
) -> Dict:
    result = {
        "success": True,
        "tokenAmount": token_amount,
        "amountETH": token_amount * current_price,
        "executionPrice": current_price,
        "gasUsed": 0,
        "gasPrice": Config.MAX_GAS_PRICE,
        "feeAmount": 0,
        "priceImpact": 0,
        "slippage": 0,
        "reason": None
    }

    try:
        if not pool_info or pool_info.get("liquidity", 0) < Config.MIN_LIQUIDITY:
            result["success"] = False
            result["reason"] = f"Low liquidity ({pool_info.get('liquidity', 0)})"
            return result

        result["gasUsed"] = estimate_swap_gas(action, token)
        fee_tier = pool_info.get("feeTier", Config.POOL_FEES["MEDIUM"])
        result["feeAmount"] = result["amountETH"] * (fee_tier / 1000000)
        result["priceImpact"] = calculate_price_impact(token, token_amount, pool_info)

        base_slippage = result["priceImpact"]
        latency_slippage = (latency / 1000) * 0.01 if latency > 0 else 0
        result["slippage"] = base_slippage + latency_slippage

        if result["slippage"] > Config.MAX_SLIPPAGE:
            result["success"] = False
            result["reason"] = (
                f"Price moved too much ({result['slippage']:.2f}% > "
                f"{Config.MAX_SLIPPAGE}%)"
            )
            return result

        result["executionPrice"] = (
            current_price * (1 + result["slippage"] / 100)
            if action == TradeType.BUY
            else current_price * (1 - result["slippage"] / 100)
        )
        result["amountETH"] = token_amount * result["executionPrice"]
        result["tokenAmount"] = (
            (result["amountETH"] / result["executionPrice"])
            if action == TradeType.BUY
            else token_amount
        )

        return result
    except Exception as e:
        result["success"] = False
        result["reason"] = str(e)
        return result


def estimate_swap_gas(action: TradeType, token: str) -> int:
    base_gas = 120000
    if token in ["WBTC", "WETH"]:
        base_gas += 20000
    elif token in ["UNI", "LINK"]:
        base_gas += 8000
    else:
        base_gas += 5000

    if action == TradeType.BUY:
        base_gas += 10000

    base_gas += int(random.uniform(0, 15000))
    return min(base_gas, Config.GAS_LIMIT)


def calculate_price_impact(token: str, token_amount: float, pool_info: Dict) -> float:
    token_price = app_state.prices.get(token, 0)
    token_value_weth = token_amount * token_price
    liquidity_weth = pool_info.get("liquidity", 100000)

    if liquidity_weth <= 0:
        return 0
    return min((token_value_weth / liquidity_weth) * 100, 2)


async def execute_live_trade(
    app_state: AppState,
    token: str,
    action: TradeType,
    token_amount: float,
    current_price: float,
    pool_info: Dict,
    gas_price_gwei: float
) -> Dict:
    try:
        w3 = Web3(Web3.HTTPProvider(Config.RPC_URL))
        router_address = Config.UNISWAP_ROUTER_ADDRESS

        token_address = Config.NETWORK_TOKENS[Config.BLOCKCHAIN_NETWORK].get(token)
        weth_address = Config.WETH_ADDRESS

        if not token_address:
            return {
                "success": False,
                "reason": f"Token address not found for {token}"
            }

        # Get token decimals
        ERC20_ABI = [
            {"constant": True, "inputs": [], "name": "decimals", "outputs": [{"name": "", "type": "uint8"}], "type": "function"}
        ]
        token_contract = w3.eth.contract(address=token_address, abi=ERC20_ABI)
        decimals = token_contract.functions.decimals().call()

        # Calculate amount in wei
        amount_in_wei = int(token_amount * (10 ** decimals))

        # Build the transaction
        UNISWAP_ROUTER_ABI = [
            {
                "inputs": [
                    {"internalType": "address", "name": "tokenIn", "type": "address"},
                    {"internalType": "address", "name": "tokenOut", "type": "address"},
                    {"internalType": "uint24", "name": "fee", "type": "uint24"},
                    {"internalType": "address", "name": "recipient", "type": "address"},
                    {"internalType": "uint256", "name": "amountIn", "type": "uint256"},
                    {"internalType": "uint256", "name": "amountOutMinimum", "type": "uint256"},
                    {"internalType": "uint160", "name": "sqrtPriceLimitX96", "type": "uint160"},
                ],
                "name": "exactInputSingle",
                "outputs": [{"internalType": "uint256", "name": "amountOut", "type": "uint256"}],
                "stateMutability": "nonpayable",
                "type": "function"
            }
        ]
        router_contract = w3.eth.contract(address=router_address, abi=UNISWAP_ROUTER_ABI)

        tx = {
            "to": router_address,
            "value": amount_in_wei if token == "WETH" else 0,
            "gas": Config.GAS_LIMIT,
            "gasPrice": int(gas_price_gwei * 1e9),
            "nonce": w3.eth.get_transaction_count(app_state.signer.address),
        }

        if action == TradeType.BUY:
            tx["data"] = router_contract.encodeABI(
                "exactInputSingle",
                args=(
                    weth_address,
                    token_address,
                    Config.POOL_FEES["LOW"],
                    app_state.signer.address,
                    amount_in_wei,
                    0,
                    0
                )
            )
        else:
            tx["data"] = router_contract.encodeABI(
                "exactInputSingle",
                args=(
                    token_address,
                    weth_address,
                    Config.POOL_FEES["LOW"],
                    app_state.signer.address,
                    amount_in_wei,
                    0,
                    0
                )
            )

        signed_tx = sign_transaction(app_state, tx)
        tx_hash = w3.eth.send_raw_transaction(signed_tx)

        return {
            "success": True,
            "tokenAmount": token_amount,
            "amountETH": token_amount * current_price,
            "executionPrice": current_price,
            "gasUsed": Config.GAS_LIMIT,
            "gasPrice": gas_price_gwei,
            "feeAmount": 0,
            "priceImpact": 0,
            "slippage": 0,
            "txHash": tx_hash.hex(),
            "reason": None
        }
    except Exception as e:
        return {
            "success": False,
            "reason": str(e)
        }


async def execute_trade(
    app_state: AppState,
    token: str,
    action: TradeType,
    pattern_description: str = "Manual",
    amount_weth: Optional[float] = None,
    pattern: Optional[Pattern] = None
) -> Optional[Trade]:
    try:
        if not app_state.is_running:
            return None

        if action == TradeType.BUY:
            if Config.PREVENT_SEQUENTIAL_TRADES and app_state.last_traded_token == token:
                last_trade_time = app_state.last_trade_times.get(token, 0)
                if last_trade_time and (time.time() - last_trade_time) < 60:
                    print(f"Blocked buy for {token}: Recent trade.")
                    return None

            if token in app_state.open_buy_orders:
                print(f"Blocked buy for {token}: Open buy order exists.")
                return None

            existing_position = next(
                (p for p in app_state.portfolio.positions if p.token == token and p.status == "open"),
                None
            )
            if existing_position:
                print(f"Blocked buy for {token}: Already has an open position.")
                return None

            if pattern:
                if Config.PATTERN_MODE == "dip" and pattern.type != PatternType.BUY:
                    print(f"Blocked buy for {token}: Pattern mode is set to dips only.")
                    return None
                if Config.PATTERN_MODE == "swell" and pattern.type != PatternType.SWELL:
                    print(f"Blocked buy for {token}: Pattern mode is set to swells only.")
                    return None

        await update_gas_price(app_state)
        current_gas_price = app_state.current_gas_price or Config.MAX_GAS_PRICE

        if current_gas_price > Config.MAX_GAS_PRICE:
            print(f"Gas price too high: {current_gas_price} gwei > {Config.MAX_GAS_PRICE} gwei max")
            return None

        if amount_weth is None:
            amount_weth = calculate_trade_amount(app_state)

        current_price = app_state.prices.get(token, 0)
        if not current_price or amount_weth <= 0:
            return None

        total_open_positions = len(
            [p for p in app_state.portfolio.positions if p.status == "open"]
        )
        if total_open_positions >= Config.MAX_TRADES:
            if not app_state.last_max_trade_toast or (time.time() - app_state.last_max_trade_toast) > 10:
                print(f"Max trades ({Config.MAX_TRADES}) reached")
                app_state.last_max_trade_toast = time.time()
            return None

        last_trade_time = app_state.last_trade_times.get(token, 0)
        if last_trade_time and (time.time() - last_trade_time) < (Config.TRADE_COOLDOWN * 1000):
            if action == TradeType.BUY:
                print(f"Blocked buy for {token}: Cooldown active.")
                return None

        pool_info = await get_enhanced_pool_info(token)
        if not pool_info:
            return None

        if action == TradeType.SELL:
            token_balance = app_state.portfolio.balances.get(token, 0)
            if token_balance <= 0:
                return None
            sellable_amount = min(amount_weth / current_price, token_balance)
            if sellable_amount <= 0:
                return None
            token_amount = sellable_amount
            amount_weth = sellable_amount * current_price
        else:
            token_amount = amount_weth / current_price

        if app_state.live_mode and app_state.wallet_connected and app_state.signer:
            trade_result = await execute_live_trade(
                app_state, token, action, token_amount, current_price, pool_info, current_gas_price
            )
        else:
            trade_result = simulate_realistic_trade(
                app_state, token, action, token_amount, current_price, pool_info, 0, current_gas_price
            )

        if not trade_result.get("success"):
            failed_trade = create_trade_object(
                token, action, current_price, token_amount, amount_weth,
                pattern_description, TradeStatus.FAILED, trade_result.get("reason"),
                trade_result.get("gasUsed", 0), trade_result.get("gasPrice", 0),
                trade_result.get("feeAmount", 0), trade_result.get("priceImpact", 0),
                trade_result.get("slippage", 0), pattern
            )
            app_state.trades.append(failed_trade)
            app_state.portfolio.failed_trades += 1
            return failed_trade

        trade = create_trade_object(
            token, action, trade_result["executionPrice"], trade_result["tokenAmount"],
            trade_result["amountETH"], pattern_description, TradeStatus.OPEN, None,
            trade_result.get("gasUsed", 0), trade_result.get("gasPrice", 0),
            trade_result.get("feeAmount", 0), trade_result.get("priceImpact", 0),
            trade_result.get("slippage", 0), pattern
        )

        update_portfolio_for_trade(app_state, trade, action, trade_result)
        app_state.trades.append(trade)

        if action == TradeType.BUY:
            app_state.last_traded_token = token
            app_state.last_trade_times[token] = time.time()
            app_state.open_buy_orders[token] = {
                "tradeId": trade.id,
                "pattern": pattern,
                "entryPrice": trade_result["executionPrice"],
                "entryTime": time.time()
            }
        else:
            app_state.open_buy_orders.pop(token, None)

        return trade
    except Exception as e:
        print(f"Error executing trade: {e}")
        return None


def update_portfolio_for_trade(
    app_state: AppState,
    trade: Trade,
    action: TradeType,
    trade_result: Dict
) -> None:
    try:
        token = trade.token
        token_symbol = token
        gas_cost_weth = trade_result.get("gasUsed", 0) * trade_result.get("gasPrice", 0) / 1e18
        fee_cost_weth = trade_result.get("feeAmount", 0)
        total_cost_weth = gas_cost_weth + fee_cost_weth

        if action == TradeType.BUY:
            weth_balance = app_state.portfolio.balances.get("WETH", 0)
            total_trade_cost = trade_result["amountETH"] + total_cost_weth

            if weth_balance < total_trade_cost:
                trade.status = TradeStatus.FAILED
                trade.reason = "Not enough WETH (including fees)"
                app_state.portfolio.failed_trades += 1
                app_state.trades.append(trade)
                return

            app_state.portfolio.balances["WETH"] = weth_balance - total_trade_cost
            if token_symbol not in app_state.portfolio.balances:
                app_state.portfolio.balances[token_symbol] = 0
            app_state.portfolio.balances[token_symbol] += trade_result["tokenAmount"]

            position = next(
                (p for p in app_state.portfolio.positions if p.token == token_symbol and p.status == "open"),
                None
            )
            if not position:
                position = Position(
                    id=trade.id,
                    token=token_symbol,
                    entry_price=trade_result["executionPrice"],
                    amount=trade_result["tokenAmount"],
                    usd_value=trade_result["amountETH"],
                    entry_time=time.time(),
                    gas_paid=gas_cost_weth,
                    fees_paid=fee_cost_weth,
                    status="open",
                    trade_id=trade.id,
                    pattern=trade.pattern,
                    pattern_obj=trade.pattern_obj
                )
                app_state.portfolio.positions.append(position)
            else:
                position.amount += trade_result["tokenAmount"]
                position.usd_value += trade_result["amountETH"]
                position.gas_paid += gas_cost_weth
                position.fees_paid += fee_cost_weth

            app_state.portfolio.gas_spent += gas_cost_weth
            app_state.portfolio.fees_paid += fee_cost_weth
            app_state.portfolio.total_fees += total_cost_weth

        elif action == TradeType.SELL:
            open_positions = sorted(
                [p for p in app_state.portfolio.positions if p.token == token_symbol and p.status == "open"],
                key=lambda x: x.entry_time
            )

            if not open_positions:
                trade.status = TradeStatus.FAILED
                trade.reason = "No open position to sell"
                app_state.portfolio.failed_trades += 1
                app_state.trades.append(trade)
                return

            position = open_positions[0]
            amount_to_sell = min(trade_result["tokenAmount"], position.amount)
            sell_value_weth = amount_to_sell * trade_result["executionPrice"]
            cost_basis = (amount_to_sell * position.entry_price) + (
                (amount_to_sell / position.amount) * (position.fees_paid + position.gas_paid)
            )
            pnl = sell_value_weth - cost_basis - total_cost_weth

            position.amount -= amount_to_sell
            position.fees_paid += fee_cost_weth
            position.gas_paid += gas_cost_weth

            if position.amount <= 0.000001:
                position.status = "closed"
                position.exit_price = trade_result["executionPrice"]
                position.exit_time = time.time()
                position.pnl = pnl
                position.sell_trade_id = trade.id
                app_state.portfolio.realized_pnl += pnl
                if pnl > 0:
                    app_state.portfolio.winning_trades += 1
                elif pnl < 0:
                    app_state.portfolio.losing_trades += 1

            app_state.portfolio.balances["WETH"] = (
                app_state.portfolio.balances.get("WETH", 0) + sell_value_weth - total_cost_weth
            )
            trade.pnl = pnl
            trade.status = TradeStatus.CLOSED

            if token_symbol in app_state.portfolio.balances:
                app_state.portfolio.balances[token_symbol] -= amount_to_sell
                if app_state.portfolio.balances[token_symbol] < 0.000001:
                    del app_state.portfolio.balances[token_symbol]

            app_state.portfolio.gas_spent += gas_cost_weth
            app_state.portfolio.fees_paid += fee_cost_weth
            app_state.portfolio.total_fees += total_cost_weth

        app_state.portfolio.total_trades += 1
        update_portfolio_equity(app_state)
    except Exception as e:
        print(f"Error updating portfolio for trade: {e}")


def update_portfolio_equity(app_state: AppState) -> None:
    try:
        total_weth = app_state.portfolio.balances.get("WETH", 0)
        unrealized_pnl = 0

        for token_symbol, amount in app_state.portfolio.balances.items():
            if token_symbol == "WETH":
                continue
            price = app_state.prices.get(token_symbol, 0)
            total_weth += amount * price

        for position in app_state.portfolio.positions:
            if position.status == "open":
                current_price = app_state.prices.get(position.token, position.entry_price)
                current_value = position.amount * current_price
                cost_basis = (position.amount * position.entry_price) + position.fees_paid + position.gas_paid
                unrealized_pnl += current_value - cost_basis

        app_state.portfolio.current_eth = total_weth
        app_state.portfolio.unrealized_pnl = unrealized_pnl
        app_state.portfolio.equity_history.append({
            "timestamp": time.time(),
            "ethValue": total_weth
        })
        if len(app_state.portfolio.equity_history) > 1000:
            app_state.portfolio.equity_history.pop(0)
    except Exception as e:
        print(f"Error updating portfolio equity: {e}")


# ====================
# USDC PROFIT FUNNELING
# ====================

async def get_usdc_price_in_weth(app_state: AppState) -> Optional[float]:
    try:
        if "USDC" in app_state.prices:
            return app_state.prices["USDC"]
        fallback_price = 0.0005
        app_state.prices["USDC"] = fallback_price
        return fallback_price
    except Exception as e:
        print(f"Error fetching USDC price: {e}")
        return 0.0005


async def execute_trade_for_usdc(app_state: AppState, amount_weth: float, usdc_price_in_weth: float) -> Dict:
    try:
        if not app_state.live_mode or not app_state.wallet_connected or not app_state.signer:
            usdc_amount = amount_weth / usdc_price_in_weth
            return {
                "success": True,
                "amountWETH": amount_weth,
                "usdcAmount": usdc_amount,
                "reason": None
            }

        usdc_address = Config.USDC_ADDRESS
        weth_address = Config.WETH_ADDRESS

        w3 = Web3(Web3.HTTPProvider(Config.RPC_URL))
        router_address = Config.UNISWAP_ROUTER_ADDRESS

        UNISWAP_ROUTER_ABI = [
            {
                "inputs": [
                    {"internalType": "address", "name": "tokenIn", "type": "address"},
                    {"internalType": "address", "name": "tokenOut", "type": "address"},
                    {"internalType": "uint24", "name": "fee", "type": "uint24"},
                    {"internalType": "address", "name": "recipient", "type": "address"},
                    {"internalType": "uint256", "name": "amountIn", "type": "uint256"},
                    {"internalType": "uint256", "name": "amountOutMinimum", "type": "uint256"},
                    {"internalType": "uint160", "name": "sqrtPriceLimitX96", "type": "uint160"},
                ],
                "name": "exactInputSingle",
                "outputs": [{"internalType": "uint256", "name": "amountOut", "type": "uint256"}],
                "stateMutability": "nonpayable",
                "type": "function"
            }
        ]
        router_contract = w3.eth.contract(address=router_address, abi=UNISWAP_ROUTER_ABI)

        weth_contract = w3.eth.contract(address=weth_address, abi=[
            {"constant": True, "inputs": [{"name": "_owner", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "balance", "type": "uint256"}], "type": "function"}
        ])
        weth_balance = weth_contract.functions.balanceOf(app_state.signer.address).call()
        if w3.from_wei(weth_balance, "ether") < amount_weth:
            return {
                "success": False,
                "reason": "Not enough WETH balance"
            }

        amount_in = w3.to_wei(amount_weth, "ether")
        min_amount_out = w3.to_wei((amount_weth / usdc_price_in_weth) * 0.995, "mwei")

        tx = router_contract.functions.exactInputSingle(
            weth_address,
            usdc_address,
            500,
            app_state.signer.address,
            amount_in,
            min_amount_out,
            0
        ).build_transaction({
            "from": app_state.signer.address,
            "gas": Config.GAS_LIMIT,
            "gasPrice": w3.to_wei(Config.MAX_GAS_PRICE, "gwei"),
            "nonce": w3.eth.get_transaction_count(app_state.signer.address)
        })

        signed_tx = sign_transaction(app_state, tx)
        tx_hash = w3.eth.send_raw_transaction(signed_tx)

        return {
            "success": True,
            "usdcAmount": amount_weth / usdc_price_in_weth,
            "txHash": tx_hash.hex()
        }
    except Exception as e:
        print(f"Error executing trade for USDC: {e}")
        return {
            "success": False,
            "reason": str(e)
        }


async def check_and_convert_to_usdc(app_state: AppState) -> None:
    try:
        if not app_state.is_running:
            return

        usdc_price_in_weth = await get_usdc_price_in_weth(app_state)
        if not usdc_price_in_weth:
            print("Could not fetch USDC/WETH price.")
            return

        total_profit_weth = app_state.portfolio.realized_pnl + app_state.portfolio.unrealized_pnl
        if total_profit_weth <= 0:
            print("No profit to convert to USDC.")
            return

        usdc_target = Config.USDC_PROFIT_TARGET
        weth_needed_for_1_usdc = usdc_target * usdc_price_in_weth

        if total_profit_weth >= weth_needed_for_1_usdc:
            print(f"Converting {weth_needed_for_1_usdc} WETH to {usdc_target} USDC...")

            trade_result = await execute_trade_for_usdc(app_state, weth_needed_for_1_usdc, usdc_price_in_weth)
            if trade_result["success"]:
                app_state.portfolio.usdc_profit += usdc_target
                app_state.portfolio.usdc_balance = (
                    app_state.portfolio.usdc_balance + usdc_target
                )
                app_state.last_usdc_conversion = time.time()
                print(f"Converted {format_eth(weth_needed_for_1_usdc)} to {format_usdc(usdc_target)}")
            else:
                print(f"Failed to convert to USDC: {trade_result.get('reason')}")
    except Exception as e:
        print(f"Error in check_and_convert_to_usdc: {e}")


# ====================
# BOT CONTROLS
# ====================

async def start_bot(app_state: AppState) -> None:
    try:
        if app_state.is_running:
            print("Trading is already running.")
            return

        app_state.is_running = True
        app_state.start_time = time.time()
        app_state.last_traded_token = None
        app_state.open_buy_orders.clear()
        app_state.reconnect_attempts = 0

        if app_state.live_mode:
            connect_wallet(app_state)

        await update_gas_price(app_state)
        start_price_polling(app_state)
        start_pattern_detection(app_state)
        start_usdc_conversion_timer(app_state)

        print("Started! Watching Arbitrum for quick swap opportunities.")
    except Exception as e:
        app_state.is_running = False
        print(f"Failed to start: {e}")
        raise


def stop_bot(app_state: AppState) -> None:
    try:
        if not app_state.is_running:
            print("Trading is not running.")
            return

        app_state.is_running = False
        app_state.manually_stopped = True
        stop_pattern_detection(app_state)
        stop_price_polling(app_state)
        stop_usdc_conversion_timer(app_state)

        app_state.open_buy_orders.clear()
        print("Trading stopped!")
    except Exception as e:
        print(f"Failed to stop: {e}")
        raise


def reset_app(app_state: AppState) -> None:
    if app_state.is_running:
        print("Cannot reset while bot is running. Stop the bot first.")
        return

    app_state.trades = []
    app_state.portfolio = Portfolio(
        balances={"WETH": Config.STARTING_ETH},
        starting_eth=Config.STARTING_ETH,
        current_eth=Config.STARTING_ETH,
        equity_history=[{"timestamp": time.time(), "ethValue": Config.STARTING_ETH}]
    )
    app_state.active_patterns = {}
    app_state.pattern_stats = {"total_patterns": 0, "tokens_with_patterns": 0}
    app_state.observed_tokens = set()
    app_state.prices = {}
    app_state.price_history = {}
    app_state.last_traded_token = None
    app_state.last_trade_times = {}
    app_state.open_buy_orders = {}
    app_state.last_detection_time = None
    app_state.last_swaps = []
    app_state.last_usdc_conversion = None

    print("App has been reset!")


# ====================
# PRICE AND GAS UPDATES
# ====================

async def update_gas_price(app_state: AppState) -> None:
    try:
        w3 = Web3(Web3.HTTPProvider(Config.RPC_URL))
        gas_price = w3.eth.gas_price
        app_state.current_gas_price = w3.from_wei(gas_price, "gwei")
    except Exception as e:
        print(f"Failed to update gas price: {e}")
        app_state.current_gas_price = Config.MAX_GAS_PRICE


async def get_enhanced_pool_info(token: str) -> Dict:
    defaults = {
        "WETH": {"liquidity": 1000000, "feeTier": Config.POOL_FEES["LOW"], "token0": "WETH", "token1": "WETH"},
        "ETH": {"liquidity": 1000000, "feeTier": Config.POOL_FEES["LOW"], "token0": "WETH", "token1": "WETH"},
        "WBTC": {"liquidity": 500000, "feeTier": Config.POOL_FEES["MEDIUM"], "token0": "WETH", "token1": "WBTC"},
        "UNI": {"liquidity": 1000000, "feeTier": Config.POOL_FEES["MEDIUM"], "token0": "WETH", "token1": "UNI"},
        "LINK": {"liquidity": 800000, "feeTier": Config.POOL_FEES["MEDIUM"], "token0": "WETH", "token1": "LINK"},
        "ARB": {"liquidity": 1500000, "feeTier": Config.POOL_FEES["MEDIUM"], "token0": "WETH", "token1": "ARB"},
        "GMX": {"liquidity": 400000, "feeTier": Config.POOL_FEES["MEDIUM"], "token0": "WETH", "token1": "GMX"},
        "USDC": {"liquidity": 50000000, "feeTier": Config.POOL_FEES["LOW"], "token0": "WETH", "token1": "USDC"},
        "USDT": {"liquidity": 50000000, "feeTier": Config.POOL_FEES["LOW"], "token0": "WETH", "token1": "USDT"},
        "LEVY": {"liquidity": 100000, "feeTier": Config.POOL_FEES["MEDIUM"], "token0": "WETH", "token1": "LEVY"},
        "APEX": {"liquidity": 200000, "feeTier": Config.POOL_FEES["MEDIUM"], "token0": "WETH", "token1": "APEX"}
    }
    return defaults.get(token, {"liquidity": 75000, "feeTier": Config.POOL_FEES["MEDIUM"], "token0": "WETH", "token1": token})


# ====================
# TIMERS AND POLLING
# ====================

def start_price_polling(app_state: AppState) -> None:
    if hasattr(app_state, "price_update_timer"):
        app_state.price_update_timer.cancel()

    async def poll_prices():
        while app_state.is_running:
            try:
                for token_symbol in list(app_state.observed_tokens):
                    await check_patterns_for_token(app_state, token_symbol)
                app_state.last_price_update = time.time()
            except Exception as e:
                print(f"Error in price polling: {e}")
            await asyncio.sleep(3)

    app_state.price_update_timer = asyncio.create_task(poll_prices())


def stop_price_polling(app_state: AppState) -> None:
    if hasattr(app_state, "price_update_timer"):
        app_state.price_update_timer.cancel()


def start_pattern_detection(app_state: AppState) -> None:
    if app_state.pattern_detection_active:
        return

    app_state.pattern_detection_active = True

    async def detect_patterns():
        while app_state.is_running:
            try:
                await detect_all_patterns(app_state)
                for token in list(app_state.observed_tokens):
                    await check_patterns_for_token(app_state, token)
            except Exception as e:
                print(f"Error in pattern detection: {e}")
            await asyncio.sleep(3)

    app_state.pattern_detection_timer = asyncio.create_task(detect_patterns())


def stop_pattern_detection(app_state: AppState) -> None:
    if hasattr(app_state, "pattern_detection_timer"):
        app_state.pattern_detection_timer.cancel()
    app_state.pattern_detection_active = False


def start_usdc_conversion_timer(app_state: AppState) -> None:
    if hasattr(app_state, "usdc_conversion_timer"):
        app_state.usdc_conversion_timer.cancel()

    async def convert_usdc():
        while app_state.is_running:
            try:
                await check_and_convert_to_usdc(app_state)
            except Exception as e:
                print(f"Error in USDC conversion timer: {e}")
            await asyncio.sleep(Config.USDC_CONVERSION_INTERVAL / 1000)

    app_state.usdc_conversion_timer = asyncio.create_task(convert_usdc())


def stop_usdc_conversion_timer(app_state: AppState) -> None:
    if hasattr(app_state, "usdc_conversion_timer"):
        app_state.usdc_conversion_timer.cancel()


# ====================
# PATTERN DETECTION
# ====================

async def detect_all_patterns(app_state: AppState) -> None:
    tokens = list(app_state.observed_tokens)
    new_active_patterns = {}

    for token in tokens:
        history = app_state.price_history.get(token, [])
        if not history or len(history) < 5:
            continue

        patterns = []
        if Config.PATTERN_MODE in ["both", "dip"]:
            patterns.extend(detect_buy_patterns_for_token(history, token))
        if Config.PATTERN_MODE in ["both", "swell"]:
            patterns.extend(detect_swell_patterns_for_token(history, token))

        for pattern in patterns:
            if not is_pattern_valid(pattern):
                continue

            pattern_key = get_pattern_key(pattern)
            existing_pattern_key = f"{token}_{pattern_key}"

            if existing_pattern_key not in new_active_patterns:
                new_active_patterns[existing_pattern_key] = Pattern(
                    type=pattern.type,
                    token=token,
                    timestamp=pattern.timestamp,
                    drop_pct=pattern.drop_pct,
                    drop_time=pattern.drop_time,
                    rise_pct=pattern.rise_pct,
                    rise_time=pattern.rise_time,
                    first_rise_pct=pattern.first_rise_pct,
                    first_rise_time=pattern.first_rise_time,
                    second_rise_pct=pattern.second_rise_pct,
                    second_rise_time=pattern.second_rise_time,
                    occurrences=1,
                    first_seen=pattern.timestamp,
                    last_seen=pattern.timestamp
                )
            else:
                existing = new_active_patterns[existing_pattern_key]
                existing.occurrences += 1
                existing.last_seen = max(existing.last_seen, pattern.timestamp)

    app_state.active_patterns = new_active_patterns
    app_state.pattern_stats["total_patterns"] = len(new_active_patterns)
    app_state.pattern_stats["tokens_with_patterns"] = len(
        set(p.token for p in new_active_patterns.values())
    )
    app_state.last_detection_time = time.time()


async def check_patterns_for_token(app_state: AppState, token: str) -> None:
    try:
        if not app_state.is_running:
            return

        history = app_state.price_history.get(token, [])
        if not history or len(history) < 2:
            return

        current_price = app_state.prices.get(token, 0)
        if not current_price:
            return

        open_position = next(
            (p for p in app_state.portfolio.positions if p.token == token and p.status == "open"),
            None
        )

        if open_position:
            current_value = open_position.amount * current_price
            cost_basis = (open_position.amount * open_position.entry_price) + open_position.fees_paid + open_position.gas_paid
            profit_weth = current_value - cost_basis
            profit_percent = (profit_weth / cost_basis) * 100

            if profit_percent >= Config.MIN_PROFIT_PERCENT and profit_weth > 0:
                await execute_trade(
                    app_state,
                    token,
                    TradeType.SELL,
                    f"Profit target ({format_percent(profit_percent)}) reached"
                )
            return

        token_patterns = [p for p in app_state.active_patterns.values() if p.token == token]
        for pattern in token_patterns:
            if Config.PATTERN_MODE == "dip" and pattern.type != PatternType.BUY:
                continue
            if Config.PATTERN_MODE == "swell" and pattern.type != PatternType.SWELL:
                continue

            if token in app_state.open_buy_orders:
                break

            existing_position = next(
                (p for p in app_state.portfolio.positions if p.token == token and p.status == "open"),
                None
            )
            if existing_position:
                break

            trade = await execute_trade(
                app_state,
                token,
                TradeType.BUY,
                get_pattern_description(pattern),
                calculate_trade_amount(app_state),
                pattern
            )

            if trade and trade.status == TradeStatus.OPEN:
                app_state.open_buy_orders[token] = {
                    "tradeId": trade.id,
                    "pattern": pattern,
                    "entryPrice": trade.price,
                    "entryTime": time.time()
                }
                break
    except Exception as e:
        print(f"Error checking patterns for token {token}: {e}")


# ====================
# DASHBOARD UPDATES
# ====================

async def update_dashboard(app_state: AppState) -> Dict:
    try:
        observed_tokens = list(app_state.observed_tokens)
        return {
            "tracked_tokens_count": len(observed_tokens),
            "last_price_update": time.ctime(app_state.last_price_update) if app_state.last_price_update else "Never",
            "current_gas_price": f"{app_state.current_gas_price:.2f} gwei",
            "trade_amount_display": format_eth(calculate_trade_amount(app_state)),
            "uptime": format_uptime(app_state.start_time) if app_state.start_time else "00:00:00"
        }
    except Exception as e:
        print(f"Error updating dashboard: {e}")
        return {}


def get_portfolio_status(app_state: AppState) -> Dict:
    try:
        return {
            "starting_eth": format_eth(app_state.portfolio.starting_eth),
            "current_eth": format_eth(app_state.portfolio.current_eth),
            "realized_pnl": format_eth(app_state.portfolio.realized_pnl),
            "unrealized_pnl": format_eth(app_state.portfolio.unrealized_pnl),
            "net_pnl": format_eth(app_state.portfolio.realized_pnl + app_state.portfolio.unrealized_pnl),
            "portfolio_return": format_percent(
                ((app_state.portfolio.current_eth - app_state.portfolio.starting_eth) / app_state.portfolio.starting_eth) * 100
            ),
            "usdc_profit": format_usdc(app_state.portfolio.usdc_profit),
            "usdc_balance": format_usdc(app_state.portfolio.usdc_balance),
            "gas_spent": format_eth(app_state.portfolio.gas_spent),
            "dex_fees": format_eth(app_state.portfolio.fees_paid),
            "total_fees": format_eth(app_state.portfolio.gas_spent + app_state.portfolio.fees_paid)
        }
    except Exception as e:
        print(f"Error getting portfolio status: {e}")
        return {}


def get_recent_trades(app_state: AppState) -> List[Dict]:
    try:
        trades = sorted(app_state.trades, key=lambda x: x.timestamp, reverse=True)[:20]
        return [
            {
                "time": time.ctime(trade.timestamp),
                "token": trade.token,
                "action": trade.trade_type.value.upper(),
                "price": format_number(trade.price, 8),
                "amount": format_number(trade.token_amount, 4),
                "pattern": trade.pattern or "Manual",
                "profit": format_eth(trade.pnl, 8)
            }
            for trade in trades
        ]
    except Exception as e:
        print(f"Error getting recent trades: {e}")
        return []


def get_last_swaps(app_state: AppState) -> List[Dict]:
    try:
        return [
            {
                "time": time.ctime(swap.timestamp),
                "token_in": swap.token_in,
                "token_out": swap.token_out,
                "amount_in": format_number(swap.amount_in, 6),
                "amount_out": format_number(swap.amount_out, 6),
                "pool": swap.pool
            }
            for swap in app_state.last_swaps[:10]
        ]
    except Exception as e:
        print(f"Error getting last swaps: {e}")
        return []


def get_pattern_stats(app_state: AppState) -> Dict:
    try:
        return {
            "total_patterns": app_state.pattern_stats.get("total_patterns", 0),
            "tokens_with_patterns": app_state.pattern_stats.get("tokens_with_patterns", 0),
            "active_patterns_count": len(app_state.active_patterns),
            "last_detection_time": time.ctime(app_state.last_detection_time) if app_state.last_detection_time else "Never"
        }
    except Exception as e:
        print(f"Error getting pattern stats: {e}")
        return {}


def get_config_data(app_state: AppState) -> Dict:
    try:
        return {
            "starting_eth": Config.STARTING_ETH,
            "trade_percent": Config.TRADE_AMOUNT_PERCENT,
            "min_trade": Config.MIN_TRADE_AMOUNT_ETH,
            "max_trades": Config.MAX_TRADES,
            "min_price_change": Config.MIN_PRICE_CHANGE,
            "min_time_window": Config.MIN_TIME_WINDOW,
            "max_time_window": Config.MAX_TIME_WINDOW,
            "min_occurrences": Config.MIN_OCCURRENCES,
            "min_profit": Config.MIN_PROFIT_PERCENT,
            "max_slippage": Config.MAX_SLIPPAGE,
            "max_gas_price": Config.MAX_GAS_PRICE,
            "price_history_duration": Config.PRICE_HISTORY_DURATION,
            "max_price_history": Config.MAX_PRICE_HISTORY,
            "usdc_target": Config.USDC_PROFIT_TARGET,
            "pattern_mode": Config.PATTERN_MODE
        }
    except Exception as e:
        print(f"Error getting config: {e}")
        return {}


def update_config_data(app_state: AppState, new_config: Dict) -> None:
    try:
        for key, value in new_config.items():
            if hasattr(Config, key.upper()):
                setattr(Config, key.upper(), value)
    except Exception as e:
        print(f"Error updating config: {e}")


# ====================
# FLASK APP
# ====================

app = Flask(__name__)
app_state = AppState()


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/start', methods=['POST'])
def start():
    try:
        asyncio.run(start_bot(app_state))
        return jsonify({"status": "success", "message": "Bot started successfully"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/stop', methods=['POST'])
def stop():
    try:
        stop_bot(app_state)
        return jsonify({"status": "success", "message": "Bot stopped successfully"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/reset', methods=['POST'])
def reset():
    try:
        reset_app(app_state)
        return jsonify({"status": "success", "message": "App reset successfully"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/status')
def status():
    try:
        dashboard_data = asyncio.run(update_dashboard(app_state))
        portfolio_status = get_portfolio_status(app_state)
        recent_trades = get_recent_trades(app_state)
        last_swaps = get_last_swaps(app_state)
        pattern_stats = get_pattern_stats(app_state)

        return jsonify({
            "status": "success",
            "data": {
                "dashboard": dashboard_data,
                "portfolio": portfolio_status,
                "recent_trades": recent_trades,
                "last_swaps": last_swaps,
                "pattern_stats": pattern_stats,
                "is_running": app_state.is_running,
                "wallet_connected": app_state.wallet_connected,
                "live_mode": app_state.live_mode,
            }
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/config', methods=['GET', 'POST'])
def config():
    if request.method == 'GET':
        try:
            config_data = get_config_data(app_state)
            return jsonify({"status": "success", "config": config_data})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500
    elif request.method == 'POST':
        try:
            new_config = request.json
            update_config_data(app_state, new_config)
            return jsonify({"status": "success", "message": "Config updated successfully"})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/connect_wallet', methods=['POST'])
def connect_wallet_route():
    try:
        success = connect_wallet(app_state)
        if success:
            return jsonify({"status": "success", "message": "Wallet connected successfully"})
        else:
            return jsonify({"status": "error", "message": "Failed to connect wallet"}), 500
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/toggle_live_mode', methods=['POST'])
def toggle_live_mode():
    try:
        app_state.live_mode = not app_state.live_mode
        return jsonify({
            "status": "success",
            "message": f"Live mode {'enabled' if app_state.live_mode else 'disabled'}",
            "live_mode": app_state.live_mode
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=6767, debug=True)