# app.py
from flask import Flask, jsonify, request, render_template
import json
import time
import math
from datetime import datetime, timedelta
from collections import defaultdict
import random
import threading
from web3 import Web3
import os
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.config['TEMPLATES_AUTO_RELOAD'] = True

# ======================
# Configuration Constants
# ======================
BLOCKCHAIN_NETWORK = os.getenv('BLOCKCHAIN_NETWORK', 'arbitrum')
UNISWAP_VERSION = 'v3'
STARTING_ETH = float(os.getenv('STARTING_ETH', 0.0033))
TRADE_AMOUNT_PERCENT = float(os.getenv('TRADE_AMOUNT_PERCENT', 10))
MIN_TRADE_AMOUNT_ETH = float(os.getenv('MIN_TRADE_AMOUNT_ETH', 0.00001))
MAX_TRADES = int(os.getenv('MAX_TRADES', 3))
TRADE_COOLDOWN = int(os.getenv('TRADE_COOLDOWN', 60))
MIN_PRICE_CHANGE = float(os.getenv('MIN_PRICE_CHANGE', 1.0))
MIN_TIME_WINDOW = int(os.getenv('MIN_TIME_WINDOW', 10))
MAX_TIME_WINDOW = int(os.getenv('MAX_TIME_WINDOW', 300))
MIN_OCCURRENCES = int(os.getenv('MIN_OCCURRENCES', 2))
MIN_WIN_RATE = float(os.getenv('MIN_WIN_RATE', 60))
BACKTEST_PERIOD = int(os.getenv('BACKTEST_PERIOD', 24))
TARGET_PROFIT_PERCENT = float(os.getenv('TARGET_PROFIT_PERCENT', 1.0))
MIN_PROFITABILITY = float(os.getenv('MIN_PROFITABILITY', 1.5))
MAX_PATTERNS_PER_TOKEN = int(os.getenv('MAX_PATTERNS_PER_TOKEN', 5))
MAX_SLIPPAGE = float(os.getenv('MAX_SLIPPAGE', 0.5))
MIN_PROFIT_PERCENT = float(os.getenv('MIN_PROFIT_PERCENT', 0.5))
MAX_POSITION_AGE = int(os.getenv('MAX_POSITION_AGE', 600))
MAX_GAS_PRICE = float(os.getenv('MAX_GAS_PRICE', 200))
GAS_LIMIT = int(os.getenv('GAS_LIMIT', 200000))
PREVENT_SEQUENTIAL_TRADES = os.getenv('PREVENT_SEQUENTIAL_TRADES', 'true').lower() == 'true'
PRICE_HISTORY_DURATION = int(os.getenv('PRICE_HISTORY_DURATION', 24))
MAX_PRICE_HISTORY = int(os.getenv('MAX_PRICE_HISTORY', 10000))

# Chain configurations
CHAINS = {
    'arbitrum': {
        'name': 'Arbitrum One',
        'chainId': 42161,
        'ws': 'wss://arbitrum-one-rpc.publicnode.com',
        'factory': '0x1F98431c8aD98523631AE4a59f267346ea31F984',
        'wrappedNative': '0x82aF49447D8a07e3bd95BD0d56f35241523fBab1',
        'quoteMode': 'native',
        'quoteLabel': 'ETH',
        'stables': ['0xaf88d065e77c8cC2239327C5EDb3A432268e5831', '0xFd086bC7CD5C481DCC9C85ebE478A1C0b69FCbb9']
    },
    'ethereum': {
        'name': 'Ethereum Mainnet',
        'chainId': 1,
        'ws': 'wss://ethereum-rpc.publicnode.com',
        'factory': '0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f',
        'wrappedNative': '0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2',
        'quoteMode': 'native',
        'quoteLabel': 'ETH',
        'stables': ['0xA0b86991c6218b36c1d19d4a2e9eb0ce3606eb48', '0xdAC17F958D2ee523a2206206994597C13D831ec7']
    },
    'base': {
        'name': 'Base',
        'chainId': 8453,
        'ws': 'wss://base-rpc.publicnode.com',
        'factory': '0x33128a8fC17869897dcE68Ed026d694621f6FDfD',
        'wrappedNative': '0x4200000000000000000000000000000000000006',
        'quoteMode': 'native',
        'quoteLabel': 'ETH',
        'stables': ['0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913', '0x60a3e35cc302bfa44cb288bc5a4f316fdb1adb42']
    },
    'optimism': {
        'name': 'Optimism',
        'chainId': 10,
        'ws': 'wss://optimism-rpc.publicnode.com',
        'factory': '0x1F98431c8aD98523631AE4a59f267346ea31F984',
        'wrappedNative': '0x4200000000000000000000000000000000000006',
        'quoteMode': 'native',
        'quoteLabel': 'ETH',
        'stables': ['0x0b2C639c533813f4AaA9D7837CAf62653d097Ff85', '0x7F5c764cBc14f9669B88837ca1490cCa17c31607']
    },
    'polygon': {
        'name': 'Polygon',
        'chainId': 137,
        'ws': 'wss://polygon-bor-rpc.publicnode.com',
        'factory': '0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f',
        'wrappedNative': '0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270',
        'quoteMode': 'native',
        'quoteLabel': 'WPOL',
        'stables': ['0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174', '0xc2132D05D31c914a87C6611C10748AEb04B58e8F']
    }
}

# Known tokens
KNOWN_TOKENS = {
    'ETH': {'address': None, 'decimals': 18, 'symbol': 'ETH', 'name': 'Ethereum'},
    'WETH': {'address': None, 'decimals': 18, 'symbol': 'WETH', 'name': 'Wrapped ETH'},
    'WBTC': {'address': None, 'decimals': 8, 'symbol': 'WBTC', 'name': 'Wrapped BTC'},
    'UNI': {'address': None, 'decimals': 18, 'symbol': 'UNI', 'name': 'Uniswap'},
    'LINK': {'address': None, 'decimals': 18, 'symbol': 'LINK', 'name': 'Chainlink'},
    'ARB': {'address': None, 'decimals': 18, 'symbol': 'ARB', 'name': 'Arbitrum'},
    'GMX': {'address': None, 'decimals': 18, 'symbol': 'GMX', 'name': 'GMX'},
    'USDC': {'address': None, 'decimals': 6, 'symbol': 'USDC', 'name': 'USD Coin'},
    'USDT': {'address': None, 'decimals': 6, 'symbol': 'USDT', 'name': 'Tether'}
}

# Initialize known tokens with addresses
def initialize_known_tokens():
    network_tokens = {
        'arbitrum': {
            'WETH': '0x82aF49447D8a07e3bd95BD0d56f35241523fBab1',
            'WBTC': '0x2f2a2543B76A416654947aaB75B4e35b52a17231',
            'UNI': '0xfa7F8980b0f1E64A2062791cc3b0871572f1F7f0',
            'LINK': '0xf97f4df75117a78c1A5a0DBb814Af92458539FB4',
            'ARB': '0x912CE59144196C11c48067255325c5414506085A',
            'GMX': '0xfc5A1A6EB076a2C7aD06eD22C5C769A78b3Fa3A1',
            'USDC': '0xaf88d065e77c8cC2239327C5EDb3A432268e5831',
            'USDT': '0xFd086bC7CD5C481DCC9C85ebE478A1C0b69FCbb9'
        },
        'ethereum': {
            'WETH': '0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2',
            'WBTC': '0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599',
            'UNI': '0x1f9840a85d5aF5bf1D1762F925BDADDd9702f158',
            'LINK': '0x514910771AF9Ca656af840dff83E8264EcF986CA',
            'USDC': '0xA0b86991c6218b36c1d19d4a2e9eb0ce3606eb48',
            'USDT': '0xdAC17F958D2ee523a2206206994597C13D831ec7'
        },
        'base': {
            'WETH': '0x4200000000000000000000000000000000000006',
            'WBTC': '0x6025518810202842D4E7b537291033197F2B498c',
            'USDC': '0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913',
            'USDT': '0x60a3e35cc302bfa44cb288bc5a4f316fdb1adb42'
        },
        'optimism': {
            'WETH': '0x4200000000000000000000000000000000000006',
            'WBTC': '0x68f180fcCe6836688e9084f035309fC299A09C00',
            'UNI': '0x6fd9d7AD17242c41f7131d257212c54A0e816691',
            'LINK': '0x350a791Bfc2C21F9Ed5d10980Dad2e2638ffa7f6',
            'USDC': '0x0b2C639c533813f4AaA9D7837CAf62653d097Ff85',
            'USDT': '0x7F5c764cBc14f9669B88837ca1490cCa17c31607'
        },
        'polygon': {
            'WETH': '0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270',
            'WBTC': '0x1BFD67037B42Cf73acF2047067bd4F2C47D9BfD6',
            'UNI': '0xb33EaAd8d922B1083446DC23f610c2567fB5180',
            'LINK': '0x53E0bca35eC356BD5ddDFebbD1Fc0fD03Fad3981',
            'USDC': '0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174',
            'USDT': '0xc2132D05D31c914a87C6611C10748AEb04B58e8F'
        }
    }
    network = CHAINS.get(BLOCKCHAIN_NETWORK, {})
    if network and network_tokens.get(BLOCKCHAIN_NETWORK):
        for symbol, address in network_tokens[BLOCKCHAIN_NETWORK].items():
            if symbol in KNOWN_TOKENS:
                KNOWN_TOKENS[symbol]['address'] = address

# ======================
# State Management
# ======================
state = {
    'is_running': False,
    'current_network': BLOCKCHAIN_NETWORK,
    'prices': {},
    'price_history': defaultdict(list),
    'trades': [],
    'active_patterns': {},
    'portfolio': {
        'balances': {'ETH': STARTING_ETH},
        'positions': [],
        'realized_pnl': 0,
        'unrealized_pnl': 0,
        'gas_spent': 0,
        'fees_paid': 0,
        'starting_eth': STARTING_ETH,
        'current_eth': STARTING_ETH,
        'equity_history': [{'timestamp': int(time.time() * 1000), 'eth_value': STARTING_ETH}],
        'total_trades': 0,
        'winning_trades': 0,
        'losing_trades': 0,
        'failed_trades': 0,
        'total_fees': 0
    },
    'last_traded_token': None,
    'last_trade_times': {},
    'start_time': None,
    'last_price_update': None,
    'current_gas_price': 0.02,
    'manually_stopped': True,
    'observed_tokens': set(),
    'pattern_stats': {'total_patterns': 0, 'buy_patterns': 0, 'sell_patterns': 0, 'tokens_with_patterns': 0},
    'open_buy_orders': {},
    'pattern_detection_active': False,
    'live_mode': False,
    'wallet_connected': False,
    'session_serial': 0,
    'active_session': None
}

# ======================
# Helper Functions
# ======================
def norm(a):
    return str(a).lower()

def short(a):
    if not a:
        return ''
    return a[:6] + '...' + a[-4:]

def calculate_trade_amount():
    gas_price = state['current_gas_price'] or MAX_GAS_PRICE
    multiplier = 1
    gas_limit = GAS_LIMIT
    available_eth = state['portfolio']['current_eth'] or STARTING_ETH
    gas_cost_per_trade = (gas_price * gas_limit * 2) / 1e9 / 1e9
    max_trades = MAX_TRADES
    total_gas_cost = gas_cost_per_trade * max_trades * multiplier
    percent_based_amount = available_eth * (TRADE_AMOUNT_PERCENT / 100)
    min_trade_amount_eth = MIN_TRADE_AMOUNT_ETH
    amount_after_fees = percent_based_amount - (total_gas_cost / max_trades)
    trade_amount = min(percent_based_amount, amount_after_fees)
    trade_amount = max(trade_amount, min_trade_amount_eth)
    trade_amount = min(trade_amount, available_eth * 0.95)
    return trade_amount

def update_portfolio_equity():
    total_eth = state['portfolio']['balances'].get('ETH', 0)
    for token_symbol, amount in state['portfolio']['balances'].items():
        if token_symbol == 'ETH':
            continue
        price_in_eth = state['prices'].get(token_symbol, 0)
        total_eth += amount * price_in_eth
    for position in state['portfolio']['positions']:
        if position['status'] != 'open':
            continue
        current_price = state['prices'].get(position['token'], position['entry_price'])
        current_value = position['amount'] * current_price
        unrealized_pnl = current_value - (position['amount'] * position['entry_price']) - position['fees_paid'] - position['gas_paid']
        total_eth += unrealized_pnl
    state['portfolio']['current_eth'] = total_eth
    state['portfolio']['unrealized_pnl'] = total_eth - state['portfolio']['starting_eth'] - state['portfolio']['realized_pnl']
    state['portfolio']['equity_history'].append({
        'timestamp': int(time.time() * 1000),
        'eth_value': state['portfolio']['current_eth']
    })
    if len(state['portfolio']['equity_history']) > 1000:
        state['portfolio']['equity_history'].pop(0)

def update_price_history(token, price, timestamp=None):
    if price is None or not isinstance(price, (int, float)):
        return
    if timestamp is None:
        timestamp = int(time.time() * 1000)
    state['price_history'][token].append({'price': price, 'timestamp': timestamp})
    max_history = MAX_PRICE_HISTORY
    if len(state['price_history'][token]) > max_history:
        state['price_history'][token].pop(0)
    duration_ms = PRICE_HISTORY_DURATION * 60 * 60 * 1000
    cutoff = timestamp - duration_ms
    while state['price_history'][token] and state['price_history'][token][0]['timestamp'] < cutoff:
        state['price_history'][token].pop(0)

def get_pattern_key(pattern):
    if pattern['type'] == 'buy':
        rounded_drop = round(pattern['drop_pct'] * 10) / 10
        rounded_rise = round(pattern['rise_pct'] * 10) / 10
        rounded_drop_time = round(pattern['drop_time'])
        rounded_rise_time = round(pattern['rise_time'])
        return f"BUY_{rounded_drop}%_{rounded_drop_time}s_{rounded_rise}%_{rounded_rise_time}s"
    else:
        rounded_rise = round(pattern['rise_pct'] * 10) / 10
        rounded_rise_time = round(pattern['rise_time'])
        return f"SELL_{rounded_rise}%_{rounded_rise_time}s"

def get_pattern_description(pattern):
    if pattern['type'] == 'buy':
        return f"Buy when price drops {pattern['drop_pct']:.1f}% over {pattern['drop_time']:.0f}s, expecting {pattern['rise_pct']:.1f}% rise"
    else:
        return f"Sell when price rises {pattern['rise_pct']:.1f}% over {pattern['rise_time']:.0f}s"

# ======================
# Pattern Detection
# ======================
def detect_buy_patterns_for_token(history, token):
    if not history or len(history) < 10:
        return []
    min_change = MIN_PRICE_CHANGE / 100
    min_time = MIN_TIME_WINDOW * 1000
    max_time = MAX_TIME_WINDOW * 1000
    patterns = []
    for i in range(5, len(history) - 5):
        current = history[i]
        is_minima = (
            current['price'] <= history[i - 1]['price'] and
            current['price'] <= history[i - 2]['price'] and
            current['price'] <= history[i + 1]['price'] and
            current['price'] <= history[i + 2]['price']
        )
        if is_minima:
            for j in range(i - 1, max(0, i - 10) - 1, -1):
                prev = history[j]
                drop_pct = (current['price'] - prev['price']) / prev['price']
                time_diff = current['timestamp'] - prev['timestamp']
                if drop_pct <= -min_change and min_time <= time_diff <= max_time:
                    for k in range(i + 1, min(len(history), i + 11)):
                        next_point = history[k]
                        rise_pct = (next_point['price'] - current['price']) / current['price']
                        rise_time = next_point['timestamp'] - current['timestamp']
                        min_required_rise = abs(drop_pct) + (MIN_PROFITABILITY / 100)
                        if rise_pct >= min_required_rise and min_time <= rise_time <= max_time:
                            patterns.append({
                                'type': 'buy',
                                'drop_pct': abs(drop_pct) * 100,
                                'drop_time': time_diff / 1000,
                                'rise_pct': rise_pct * 100,
                                'rise_time': rise_time / 1000,
                                'token': token,
                                'timestamp': current['timestamp']
                            })
                            break
                    break
    if not patterns and len(history) >= 20:
        for i in range(len(history) - 1, 19, -1):
            current = history[i]
            lookback_start = max(0, i - 10)
            total_drop = 0
            drop_count = 0
            for j in range(i - 1, lookback_start - 1, -1):
                drop_pct = (history[j]['price'] - history[j + 1]['price']) / history[j + 1]['price']
                if drop_pct > 0:
                    total_drop += drop_pct
                    drop_count += 1
            if drop_count > 0:
                avg_drop = total_drop / drop_count
                lookforward_end = min(len(history) - 1, i + 10)
                total_rise = 0
                rise_count = 0
                for j in range(i + 1, lookforward_end + 1):
                    rise_pct = (history[j]['price'] - history[j - 1]['price']) / history[j - 1]['price']
                    if rise_pct > 0:
                        total_rise += rise_pct
                        rise_count += 1
                if rise_count > 0:
                    avg_rise = total_rise / rise_count
                    time_diff = (history[lookforward_end]['timestamp'] - history[lookback_start]['timestamp']) / 1000
                    if avg_rise > avg_drop + (MIN_PROFITABILITY / 100):
                        patterns.append({
                            'type': 'buy',
                            'drop_pct': avg_drop * 100,
                            'drop_time': time_diff / 2,
                            'rise_pct': avg_rise * 100,
                            'rise_time': time_diff / 2,
                            'token': token,
                            'timestamp': current['timestamp']
                        })
    return patterns

def is_pattern_valid(pattern):
    if pattern['drop_pct'] > 1000 or pattern['rise_pct'] > 10000:
        return False
    if pattern['drop_pct'] < 0 or pattern['rise_pct'] < 0:
        return False
    if pattern['drop_time'] > 10000 or pattern['rise_time'] > 10000:
        return False
    if pattern['drop_time'] < 1 or pattern['rise_time'] < 1:
        return False
    return True

def backtest_pattern(pattern, history, backtest_period_ms):
    now = int(time.time() * 1000)
    start_time = now - backtest_period_ms
    total_trades = 0
    winning_trades = 0
    occurrences = 0
    total_profit = 0
    backtest_history = [h for h in history if h['timestamp'] >= start_time]
    if len(backtest_history) < 20:
        return {'occurrences': 0, 'total_trades': 0, 'winning_trades': 0, 'win_rate': 0, 'avg_profitability': 0, 'total_profit': 0}
    min_change = MIN_PRICE_CHANGE / 100
    trade_amount_eth = calculate_trade_amount()
    for i in range(10, len(backtest_history) - 10):
        current = backtest_history[i]
        pattern_matched = False
        if pattern['type'] == 'buy':
            for j in range(i - 1, max(0, i - 10) - 1, -1):
                prev = backtest_history[j]
                drop_pct = (current['price'] - prev['price']) / prev['price']
                time_diff = (current['timestamp'] - prev['timestamp']) / 1000
                if abs(drop_pct) >= pattern['drop_pct'] / 100 and (pattern['drop_time'] - 5 <= time_diff <= pattern['drop_time'] + 5):
                    for k in range(i + 1, min(len(backtest_history), i + 11)):
                        next_point = backtest_history[k]
                        rise_pct = (next_point['price'] - current['price']) / current['price']
                        rise_time = (next_point['timestamp'] - current['timestamp']) / 1000
                        if rise_pct >= pattern['rise_pct'] / 100 and (pattern['rise_time'] - 5 <= rise_time <= pattern['rise_time'] + 5):
                            pattern_matched = True
                            total_trades += 1
                            occurrences += 1
                            entry_price = current['price']
                            exit_price = next_point['price']
                            token_amount = trade_amount_eth / entry_price
                            exit_value = token_amount * exit_price
                            fee_percent = 0.0005
                            buy_fee = trade_amount_eth * fee_percent
                            sell_fee = exit_value * fee_percent
                            profit = exit_value - trade_amount_eth - buy_fee - sell_fee
                            if profit > 0:
                                winning_trades += 1
                            total_profit += profit
                            i = k
                            break
                    break
    avg_profitability = (total_profit / trade_amount_eth / total_trades * 100) if total_trades > 0 else 0
    return {
        'occurrences': occurrences,
        'total_trades': total_trades,
        'winning_trades': winning_trades,
        'win_rate': (winning_trades / total_trades * 100) if total_trades > 0 else 0,
        'avg_profitability': avg_profitability,
        'total_profit': total_profit
    }

def validate_patterns_with_backtesting(patterns):
    backtest_period_ms = BACKTEST_PERIOD * 60 * 60 * 1000
    for pattern_key, pattern in list(patterns.items()):
        history = state['price_history'].get(pattern['token'], [])
        if not history or len(history) < 20:
            del patterns[pattern_key]
            continue
        backtest_result = backtest_pattern(pattern, history, backtest_period_ms)
        if backtest_result['occurrences'] < MIN_OCCURRENCES:
            del patterns[pattern_key]
            continue
        if backtest_result['win_rate'] < MIN_WIN_RATE:
            del patterns[pattern_key]
            continue
        if backtest_result['avg_profitability'] < MIN_PROFITABILITY:
            del patterns[pattern_key]
            continue
        if pattern['rise_pct'] <= pattern['drop_pct']:
            del patterns[pattern_key]
            continue
        pattern['win_rate'] = backtest_result['win_rate']
        pattern['total_trades'] = backtest_result['total_trades']
        pattern['winning_trades'] = backtest_result['winning_trades']
        pattern['avg_profitability'] = backtest_result['avg_profitability']
        pattern['total_profit'] = backtest_result['total_profit']

def detect_all_patterns():
    tokens = list(state['observed_tokens'])
    new_active_patterns = {}
    for token in tokens:
        history = state['price_history'].get(token, [])
        if not history or len(history) < 10:
            continue
        patterns = detect_buy_patterns_for_token(history, token)
        for pattern in patterns:
            if not is_pattern_valid(pattern):
                continue
            if pattern['rise_pct'] <= pattern['drop_pct']:
                continue
            pattern_key = get_pattern_key(pattern)
            existing_pattern_key = f"{token}_{pattern_key}"
            if existing_pattern_key not in new_active_patterns:
                new_active_patterns[existing_pattern_key] = {
                    **pattern,
                    'occurrences': 1,
                    'first_seen': pattern['timestamp'],
                    'last_seen': pattern['timestamp'],
                    'win_rate': 0,
                    'total_trades': 0,
                    'winning_trades': 0,
                    'avg_profitability': 0,
                    'total_profit': 0
                }
            else:
                existing = new_active_patterns[existing_pattern_key]
                existing['occurrences'] += 1
                existing['last_seen'] = max(existing['last_seen'], pattern['timestamp'])
    validate_patterns_with_backtesting(new_active_patterns)
    state['active_patterns'] = new_active_patterns
    update_pattern_stats()

def update_pattern_stats():
    patterns_array = list(state['active_patterns'].values())
    state['pattern_stats']['total_patterns'] = len(patterns_array)
    state['pattern_stats']['buy_patterns'] = len([p for p in patterns_array if p['type'] == 'buy'])
    state['pattern_stats']['sell_patterns'] = len([p for p in patterns_array if p['type'] == 'sell'])
    state['pattern_stats']['tokens_with_patterns'] = len(set(p['token'] for p in patterns_array))

# ======================
# Trade Execution
# ======================
def create_trade_object(token, action, price, token_amount, amount_eth, pattern, status, reason=None, gas_used=0, gas_price=0, fee_amount=0, price_impact=0, slippage=0, pattern_obj=None):
    return {
        'id': f"trade_{int(time.time() * 1000)}_{random.randint(1000, 9999)}",
        'timestamp': datetime.utcnow().isoformat(),
        'token': token,
        'type': action,
        'price': price,
        'token_amount': token_amount,
        'amount_eth': amount_eth,
        'fee': fee_amount,
        'gas_used': gas_used,
        'gas_price': gas_price,
        'price_impact': price_impact,
        'slippage': slippage,
        'status': status,
        'reason': reason,
        'pnl': 0,
        'pattern': pattern,
        'pattern_obj': pattern_obj,
        'tx_hash': None,
        'network': state['current_network']
    }

async def simulate_realistic_trade(token, action, token_amount, current_price, pool_info, latency, gas_price_gwei):
    result = {
        'success': True,
        'token_amount': token_amount,
        'amount_eth': token_amount * current_price,
        'execution_price': current_price,
        'gas_used': 0,
        'gas_price': gas_price_gwei,
        'fee_amount': 0,
        'price_impact': 0,
        'slippage': 0,
        'reason': None
    }
    try:
        result['gas_price'] = gas_price_gwei or MAX_GAS_PRICE
        result['gas_used'] = estimate_swap_gas(action, token)
        fee_tier = pool_info.get('fee_tier', 3000)
        fee_percent = fee_tier / 1000000
        result['fee_amount'] = result['amount_eth'] * fee_percent
        result['price_impact'] = calculate_price_impact(token, token_amount, pool_info)
        base_slippage = result['price_impact']
        latency_slippage = (latency / 1000) * 0.01 if latency > 0 else 0
        result['slippage'] = base_slippage + latency_slippage
        if result['slippage'] > MAX_SLIPPAGE:
            result['success'] = False
            result['reason'] = f"Price moved too much during execution ({result['slippage']:.4f}% > {MAX_SLIPPAGE}% max)"
            return result
        if action == 'buy':
            result['execution_price'] = current_price * (1 + result['slippage'] / 100)
        else:
            result['execution_price'] = current_price * (1 - result['slippage'] / 100)
        result['amount_eth'] = token_amount * result['execution_price']
        result['token_amount'] = token_amount if action == 'sell' else (result['amount_eth'] / result['execution_price'])
        return result
    except Exception as e:
        result['success'] = False
        result['reason'] = str(e)
        return result

def estimate_swap_gas(action, token):
    base_gas = 120000
    if token in ['WBTC', 'ETH']:
        base_gas += 20000
    elif token in ['UNI', 'LINK']:
        base_gas += 8000
    else:
        base_gas += 5000
    if action == 'buy':
        base_gas += 10000
    base_gas += random.randint(0, 15000)
    return min(base_gas, GAS_LIMIT)

def calculate_price_impact(token, token_amount, pool_info):
    token_price = state['prices'].get(token, 0)
    token_value_eth = token_amount * token_price
    liquidity_eth = pool_info.get('liquidity', 100000)
    if liquidity_eth <= 0:
        return 0
    trade_size_ratio = token_value_eth / liquidity_eth
    return min(trade_size_ratio * 100, 2)

async def get_enhanced_pool_info(token):
    defaults = {
        'ETH': {'liquidity': 1000000, 'fee_tier': 500, 'token0': 'ETH', 'token1': 'WETH'},
        'WETH': {'liquidity': 1000000, 'fee_tier': 500, 'token0': 'ETH', 'token1': 'WETH'},
        'WBTC': {'liquidity': 50000, 'fee_tier': 3000, 'token0': 'WETH', 'token1': 'WBTC'},
        'UNI': {'liquidity': 100000, 'fee_tier': 3000, 'token0': 'WETH', 'token1': 'UNI'},
        'LINK': {'liquidity': 80000, 'fee_tier': 3000, 'token0': 'WETH', 'token1': 'LINK'},
        'ARB': {'liquidity': 150000, 'fee_tier': 3000, 'token0': 'WETH', 'token1': 'ARB'},
        'GMX': {'liquidity': 40000, 'fee_tier': 3000, 'token0': 'WETH', 'token1': 'GMX'}
    }
    return defaults.get(token, {'liquidity': 75000, 'fee_tier': 3000, 'token0': 'WETH', 'token1': token})

def update_portfolio_for_trade(trade, action, trade_result):
    token = trade['token']
    token_symbol = token
    gas_cost_eth = trade_result['gas_used'] * trade_result['gas_price'] / 1e9 / 1e9
    fee_cost_eth = trade_result['fee_amount']
    total_cost_eth = gas_cost_eth + fee_cost_eth
    if action == 'buy':
        eth_balance = state['portfolio']['balances'].get('ETH', 0)
        total_trade_cost = trade_result['amount_eth'] + total_cost_eth
        if eth_balance < total_trade_cost:
            trade['status'] = 'failed'
            trade['reason'] = 'Not enough ETH (including fees)'
            state['portfolio']['failed_trades'] += 1
            return
        state['portfolio']['balances']['ETH'] = eth_balance - total_trade_cost
        if token_symbol not in state['portfolio']['balances']:
            state['portfolio']['balances'][token_symbol] = 0
        state['portfolio']['balances'][token_symbol] += trade_result['token_amount']
        position = next((p for p in state['portfolio']['positions'] if p['token'] == token_symbol and p['status'] == 'open'), None)
        if not position:
            position = {
                'id': trade['id'],
                'token': token_symbol,
                'entry_price': trade_result['execution_price'],
                'amount': trade_result['token_amount'],
                'usd_value': trade_result['amount_eth'],
                'entry_time': int(time.time() * 1000),
                'gas_paid': gas_cost_eth,
                'fees_paid': fee_cost_eth,
                'status': 'open',
                'trade_id': trade['id'],
                'pattern': trade['pattern'],
                'pattern_obj': trade['pattern_obj']
            }
            state['portfolio']['positions'].append(position)
        else:
            position['amount'] += trade_result['token_amount']
            position['usd_value'] += trade_result['amount_eth']
            position['gas_paid'] += gas_cost_eth
            position['fees_paid'] += fee_cost_eth
        state['portfolio']['gas_spent'] += gas_cost_eth
        state['portfolio']['fees_paid'] += fee_cost_eth
        state['portfolio']['total_fees'] += total_cost_eth
    elif action == 'sell':
        open_positions = sorted([p for p in state['portfolio']['positions'] if p['token'] == token_symbol and p['status'] == 'open'], key=lambda x: x['entry_time'])
        if not open_positions:
            trade['status'] = 'failed'
            trade['reason'] = 'No open position to sell'
            state['portfolio']['failed_trades'] += 1
            return
        position = open_positions[0]
        amount_to_sell = min(trade_result['token_amount'], position['amount'])
        sell_value_eth = amount_to_sell * trade_result['execution_price']
        cost_basis = (amount_to_sell * position['entry_price']) + (amount_to_sell / position['amount']) * (position['fees_paid'] + position['gas_paid'])
        pnl = sell_value_eth - cost_basis - total_cost_eth
        position['amount'] -= amount_to_sell
        position['fees_paid'] += fee_cost_eth
        position['gas_paid'] += gas_cost_eth
        if position['amount'] <= 0.000001:
            position['status'] = 'closed'
            position['exit_price'] = trade_result['execution_price']
            position['exit_time'] = int(time.time() * 1000)
            position['pnl'] = pnl
            position['sell_trade_id'] = trade['id']
            state['portfolio']['realized_pnl'] += pnl
            if pnl > 0:
                state['portfolio']['winning_trades'] += 1
            elif pnl < 0:
                state['portfolio']['losing_trades'] += 1
        state['portfolio']['balances']['ETH'] = state['portfolio']['balances'].get('ETH', 0) + sell_value_eth - total_cost_eth
        trade['pnl'] = pnl
        trade['status'] = 'closed'
        trade['closed_at'] = datetime.utcnow().isoformat()
        if token_symbol in state['portfolio']['balances']:
            state['portfolio']['balances'][token_symbol] -= amount_to_sell
            if state['portfolio']['balances'][token_symbol] < 0.000001:
                del state['portfolio']['balances'][token_symbol]
        state['portfolio']['gas_spent'] += gas_cost_eth
        state['portfolio']['fees_paid'] += fee_cost_eth
        state['portfolio']['total_fees'] += total_cost_eth
        if position.get('pattern_obj'):
            pattern_key = get_pattern_key(position['pattern_obj'])
            pattern = state['active_patterns'].get(pattern_key)
            if pattern:
                pattern['total_trades'] += 1
                if pnl > 0:
                    pattern['winning_trades'] += 1
                pattern['win_rate'] = (pattern['winning_trades'] / pattern['total_trades'] * 100)
    update_portfolio_equity()

async def execute_trade(token, action, pattern_description='Manual', amount_eth=None, pattern=None):
    if not state['is_running']:
        return None
    if amount_eth is None:
        amount_eth = calculate_trade_amount()
    current_price = state['prices'].get(token)
    if current_price is None:
        return None
    if amount_eth <= 0:
        return None
    total_open_positions = len([p for p in state['portfolio']['positions'] if p['status'] == 'open'])
    if total_open_positions >= MAX_TRADES:
        return None
    last_trade_time = state['last_trade_times'].get(token)
    if last_trade_time and (time.time() - last_trade_time) < TRADE_COOLDOWN:
        return None
    token_symbol = token
    token_amount = amount_eth / current_price
    pool_info = await get_enhanced_pool_info(token_symbol)
    if not pool_info:
        return None
    current_gas_price = state['current_gas_price'] or MAX_GAS_PRICE
    if action == 'sell':
        token_balance = state['portfolio']['balances'].get(token_symbol, 0)
        if token_balance <= 0:
            return None
        sellable_amount = min(token_amount, token_balance)
        if sellable_amount <= 0:
            return None
    trade_result = await simulate_realistic_trade(token_symbol, action, token_amount, current_price, pool_info, 0, current_gas_price)
    if not trade_result['success']:
        failed_trade = create_trade_object(
            token_symbol, action, current_price, token_amount, amount_eth,
            pattern_description, 'failed', trade_result['reason'],
            trade_result['gas_used'], trade_result['gas_price'], trade_result['fee_amount'],
            trade_result['price_impact'], trade_result['slippage'], pattern
        )
        state['trades'].append(failed_trade)
        state['portfolio']['failed_trades'] += 1
        state['portfolio']['total_trades'] += 1
        return failed_trade
    if PREVENT_SEQUENTIAL_TRADES and state['last_traded_token'] == token_symbol:
        return None
    trade = create_trade_object(
        token_symbol, action, trade_result['execution_price'], trade_result['token_amount'],
        trade_result['amount_eth'], pattern_description, 'open', None, trade_result['gas_used'],
        trade_result['gas_price'], trade_result['fee_amount'], trade_result['price_impact'], trade_result['slippage'], pattern
    )
    update_portfolio_for_trade(trade, action, trade_result)
    state['trades'].append(trade)
    state['portfolio']['total_trades'] += 1
    state['last_traded_token'] = token_symbol
    state['last_trade_times'][token_symbol] = time.time()
    if action == 'sell':
        if token_symbol in state['open_buy_orders']:
            del state['open_buy_orders'][token_symbol]
    return trade

def check_patterns_for_token(token):
    if not state['is_running']:
        return
    history = state['price_history'].get(token, [])
    if not history or len(history) < 2:
        return
    current_price = state['prices'].get(token)
    if current_price is None:
        return
    open_position = next((p for p in state['portfolio']['positions'] if p['token'] == token and p['status'] == 'open'), None)
    token_patterns = [p for p in state['active_patterns'].values() if p['token'] == token]
    if not token_patterns:
        return
    if open_position:
        current_value = open_position['amount'] * current_price
        cost_basis = (open_position['amount'] * open_position['entry_price']) + open_position['fees_paid'] + open_position['gas_paid']
        profit_eth = current_value - cost_basis
        profit_percent = (profit_eth / cost_basis) * 100
        if profit_percent >= TARGET_PROFIT_PERCENT and profit_eth > 0:
            sell_amount_eth = open_position['amount'] * current_price
            execute_trade(token, 'sell', f"Profit target ({profit_percent:.2f}%) reached", sell_amount_eth, None)
            if token in state['open_buy_orders']:
                del state['open_buy_orders'][token]
            return
    if not open_position:
        buy_patterns = [p for p in token_patterns if p['type'] == 'buy']
        for pattern in buy_patterns:
            if check_pattern_match(token, pattern, 'buy'):
                if PREVENT_SEQUENTIAL_TRADES and state['last_traded_token'] == token:
                    continue
                if token in state['open_buy_orders']:
                    continue
                trade_amount = calculate_trade_amount()
                execute_trade(token, 'buy', get_pattern_description(pattern), trade_amount, pattern)
                state['open_buy_orders'][token] = {
                    'trade_id': None,
                    'pattern': pattern,
                    'entry_price': None,
                    'entry_time': time.time()
                }
    if open_position and MAX_POSITION_AGE > 0:
        position_age_seconds = (time.time() - open_position['entry_time']) / 1000
        current_value = open_position['amount'] * current_price
        cost_basis = (open_position['amount'] * open_position['entry_price']) + open_position['fees_paid'] + open_position['gas_paid']
        profit = current_value - cost_basis
        profit_percent = (profit / cost_basis) * 100
        if position_age_seconds > MAX_POSITION_AGE:
            if profit > 0:
                reason = f"Auto-sell after {position_age_seconds:.0f}s (made {profit_percent:.2f}% profit)"
                execute_trade(token, 'sell', reason)

def check_pattern_match(token, pattern, pattern_type):
    history = state['price_history'].get(token, [])
    if not history or len(history) < 2:
        return False
    current_price = state['prices'].get(token)
    if current_price is None:
        return False
    recent_history = history[-20:]
    for i in range(len(recent_history) - 1, -1, -1):
        current = recent_history[i]
        if pattern_type == 'buy':
            for j in range(i - 1, max(0, i - 10) - 1, -1):
                prev = recent_history[j]
                drop_pct = (current['price'] - prev['price']) / prev['price']
                time_diff = (current['timestamp'] - prev['timestamp']) / 1000
                if abs(drop_pct) >= pattern['drop_pct'] / 100 and (pattern['drop_time'] - 5 <= time_diff <= pattern['drop_time'] + 5):
                    price_diff = abs(current_price - current['price']) / current['price']
                    if price_diff < 0.01:
                        return True
    return False

def check_age_based_selling():
    if not MAX_POSITION_AGE or not state['is_running']:
        return
    now = time.time()
    for position in state['portfolio']['positions']:
        if position['status'] != 'open':
            continue
        position_age_seconds = (now - position['entry_time']) / 1000
        current_price = state['prices'].get(position['token'], position['entry_price'])
        current_value = position['amount'] * current_price
        cost_basis = (position['amount'] * position['entry_price']) + position['fees_paid'] + position['gas_paid']
        profit = current_value - cost_basis
        profit_percent = (profit / cost_basis) * 100
        if position_age_seconds > MAX_POSITION_AGE:
            if profit > 0:
                reason = f"Auto-sell after {position_age_seconds:.0f}s (made {profit_percent:.2f}% profit)"
                execute_trade(position['token'], 'sell', reason)

# ======================
# Flask Routes
# ======================
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/state', methods=['GET'])
def get_state():
    return jsonify({
        'is_running': state['is_running'],
        'current_network': state['current_network'],
        'prices': state['prices'],
        'portfolio': state['portfolio'],
        'pattern_stats': state['pattern_stats'],
        'last_price_update': state['last_price_update'],
        'current_gas_price': state['current_gas_price'],
        'start_time': state['start_time'],
        'uptime': (time.time() - state['start_time']) if state['start_time'] else 0,
        'trades': state['trades'][-10:] if state['trades'] else [],
        'active_patterns': list(state['active_patterns'].values()) if state['active_patterns'] else [],
        'observed_tokens': list(state['observed_tokens']),
        'trade_amount_eth': calculate_trade_amount(),
        'constants': {
            'BLOCKCHAIN_NETWORK': BLOCKCHAIN_NETWORK,
            'STARTING_ETH': STARTING_ETH,
            'TRADE_AMOUNT_PERCENT': TRADE_AMOUNT_PERCENT,
            'MIN_TRADE_AMOUNT_ETH': MIN_TRADE_AMOUNT_ETH,
            'MAX_TRADES': MAX_TRADES,
            'TRADE_COOLDOWN': TRADE_COOLDOWN,
            'MIN_PRICE_CHANGE': MIN_PRICE_CHANGE,
            'MIN_TIME_WINDOW': MIN_TIME_WINDOW,
            'MAX_TIME_WINDOW': MAX_TIME_WINDOW,
            'MIN_OCCURRENCES': MIN_OCCURRENCES,
            'MIN_WIN_RATE': MIN_WIN_RATE,
            'BACKTEST_PERIOD': BACKTEST_PERIOD,
            'TARGET_PROFIT_PERCENT': TARGET_PROFIT_PERCENT,
            'MIN_PROFITABILITY': MIN_PROFITABILITY,
            'MAX_PATTERNS_PER_TOKEN': MAX_PATTERNS_PER_TOKEN,
            'MAX_SLIPPAGE': MAX_SLIPPAGE,
            'MIN_PROFIT_PERCENT': MIN_PROFIT_PERCENT,
            'MAX_POSITION_AGE': MAX_POSITION_AGE,
            'MAX_GAS_PRICE': MAX_GAS_PRICE,
            'GAS_LIMIT': GAS_LIMIT,
            'PREVENT_SEQUENTIAL_TRADES': PREVENT_SEQUENTIAL_TRADES,
            'PRICE_HISTORY_DURATION': PRICE_HISTORY_DURATION,
            'MAX_PRICE_HISTORY': MAX_PRICE_HISTORY
        }
    })

@app.route('/api/start_bot', methods=['POST'])
def start_bot():
    if state['is_running']:
        return jsonify({'success': False, 'message': 'Trading is already running.'})
    state['is_running'] = True
    state['start_time'] = time.time()
    state['last_traded_token'] = None
    state['open_buy_orders'] = {}
    state['manually_stopped'] = False
    state['pattern_detection_active'] = True
    threading.Thread(target=start_pattern_detection_loop, daemon=True).start()
    threading.Thread(target=start_price_polling_loop, daemon=True).start()
    threading.Thread(target=check_age_based_selling_loop, daemon=True).start()
    return jsonify({'success': True, 'message': 'Trading started!'})

@app.route('/api/stop_bot', methods=['POST'])
def stop_bot():
    if not state['is_running']:
        return jsonify({'success': False, 'message': 'Trading is not running.'})
    state['is_running'] = False
    state['manually_stopped'] = True
    state['pattern_detection_active'] = False
    return jsonify({'success': True, 'message': 'Trading stopped!'})

@app.route('/api/toggle_live_mode', methods=['POST'])
def toggle_live_mode():
    state['live_mode'] = not state['live_mode']
    return jsonify({'success': True, 'live_mode': state['live_mode']})

@app.route('/api/switch_network', methods=['POST'])
def switch_network():
    network = request.json.get('network')
    if network in CHAINS:
        state['current_network'] = network
        return jsonify({'success': True, 'network': network})
    return jsonify({'success': False, 'message': 'Invalid network.'})

@app.route('/api/refresh_prices', methods=['POST'])
def refresh_prices():
    if not state['is_running']:
        return jsonify({'success': False, 'message': 'Start the bot first.'})
    threading.Thread(target=update_prices, daemon=True).start()
    return jsonify({'success': True, 'message': 'Prices refreshed!'})

@app.route('/api/clear_trade_history', methods=['POST'])
def clear_trade_history():
    state['trades'] = []
    state['portfolio']['positions'] = []
    state['portfolio']['realized_pnl'] = 0
    state['portfolio']['unrealized_pnl'] = 0
    state['portfolio']['total_trades'] = 0
    state['portfolio']['winning_trades'] = 0
    state['portfolio']['losing_trades'] = 0
    state['portfolio']['failed_trades'] = 0
    state['portfolio']['equity_history'] = [{'timestamp': int(time.time() * 1000), 'eth_value': state['portfolio']['starting_eth']}]
    state['portfolio']['current_eth'] = state['portfolio']['starting_eth']
    state['open_buy_orders'] = {}
    return jsonify({'success': True, 'message': 'Trade history cleared!'})

@app.route('/api/clear_patterns', methods=['POST'])
def clear_patterns():
    state['active_patterns'] = {}
    state['pattern_stats'] = {'total_patterns': 0, 'buy_patterns': 0, 'sell_patterns': 0, 'tokens_with_patterns': 0}
    return jsonify({'success': True, 'message': 'Patterns cleared!'})

@app.route('/api/export_trade_history', methods=['GET'])
def export_trade_history():
    trades = []
    for trade in state['trades']:
        trades.append({
            'Timestamp': trade['timestamp'],
            'Token': trade['token'],
            'Type': trade['type'],
            'Price (ETH)': trade['price'],
            'Amount (Token)': trade['token_amount'],
            'Amount (ETH)': trade['amount_eth'],
            'Fee (ETH)': trade['fee'],
            'Gas Used': trade['gas_used'],
            'Gas Price (gwei)': trade['gas_price'],
            'Price Impact (%)': trade['price_impact'],
            'Slippage (%)': trade['slippage'],
            'Status': trade['status'],
            'Reason': trade['reason'] or '',
            'PnL (ETH)': trade['pnl'],
            'Pattern': trade['pattern'] or '',
            'Network': trade['network'] or ''
        })
    return jsonify({'success': True, 'trades': trades})

@app.route('/api/export_patterns', methods=['GET'])
def export_patterns():
    patterns = []
    for pattern in state['active_patterns'].values():
        patterns.append({
            'Token': pattern['token'],
            'Type': pattern['type'],
            'Description': get_pattern_description(pattern),
            'Success Rate (%)': pattern['win_rate'],
            'Avg Profitability (%)': pattern['avg_profitability'],
            'Occurrences': pattern['occurrences'],
            'Total Trades': pattern['total_trades'],
            'Winning Trades': pattern['winning_trades'],
            'First Seen': datetime.fromtimestamp(pattern['first_seen'] / 1000).strftime('%Y-%m-%d %H:%M:%S'),
            'Last Seen': datetime.fromtimestamp(pattern['last_seen'] / 1000).strftime('%Y-%m-%d %H:%M:%S')
        })
    return jsonify({'success': True, 'patterns': patterns})

# ======================
# Background Loops
# ======================
def start_pattern_detection_loop():
    while state['is_running'] and state['pattern_detection_active']:
        detect_all_patterns()
        time.sleep(15)

def start_price_polling_loop():
    while state['is_running']:
        update_prices()
        time.sleep(10)

def check_age_based_selling_loop():
    while state['is_running']:
        check_age_based_selling()
        time.sleep(30)

def update_prices():
    if not state['is_running']:
        return
    tokens = list(state['observed_tokens'])
    for token in tokens:
        if token in state['prices']:
            price = state['prices'][token]
            update_price_history(token, price)
            check_patterns_for_token(token)
    state['last_price_update'] = datetime.utcnow().isoformat()

# ======================
# Initialization
# ======================
def init():
    initialize_known_tokens()
    state['portfolio']['balances'] = {'ETH': STARTING_ETH}
    state['portfolio']['current_eth'] = STARTING_ETH
    state['portfolio']['equity_history'] = [{'timestamp': int(time.time() * 1000), 'eth_value': STARTING_ETH}]

if __name__ == '__main__':
    init()
    app.run(debug=True, host='0.0.0.0', port=5050)