import os
import time
import json
import logging
import threading
from datetime import datetime
from flask import Flask, jsonify, render_template, request
from flask_socketio import SocketIO, emit
from web3 import Web3
from dotenv import load_dotenv

load_dotenv()

# Configure logging to file
logging.basicConfig(
    filename='bot.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

app = Flask(__name__, template_folder='.')
app.config['SECRET_KEY'] = 'safetrader_secret'
socketio = SocketIO(app, cors_allowed_origins="*")

# Global State Management
class AppState:
    def __init__(self):
        self.is_running = False
        self.current_chain_key = 'arbitrum'
        self.prices = {}
        self.price_history = {}
        self.trades = []
        self.active_patterns = {}
        self.portfolio = {
            'balances': {'ETH': 0.0033},
            'positions': [],
            'realizedPnL': 0.0,
            'unrealizedPnL': 0.0,
            'gasSpent': 0.0,
            'feesPaid': 0.0,
            'startingEth': 0.0033,
            'currentEth': 0.0033,
            'equityHistory': [{'timestamp': time.time(), 'ethValue': 0.0033}],
            'totalTrades': 0,
            'winningTrades': 0,
            'losingTrades': 0,
            'failedTrades': 0,
            'totalFees': 0.0
        }
        self.last_traded_token = None
        self.last_trade_times = {}
        self.start_time = None
        self.last_price_update = None
        self.current_gas_price = 0.02
        self.manually_stopped = True
        self.observed_tokens = set()
        self.pattern_stats = {'totalPatterns': 0, 'buyPatterns': 0, 'sellPatterns': 0, 'tokensWithPatterns': 0}
        self.open_buy_orders = {}
        self.pattern_detection_active = False
        self.session_serial = 0
        self.active_session = None
        self.wallet_connected = False
        self.live_mode = False
        self.provider = None
        self.signer = None
        self.active_session = None

        # Constants
        self.BLOCKCHAIN_NETWORK = 'arbitrum'
        self.STARTING_ETH = 0.0033
        self.TRADE_AMOUNT_PERCENT = 0.5
        self.MIN_TRADE_AMOUNT_ETH = 0.0003
        self.MAX_TRADES = 200
        self.TRADE_COOLDOWN = 60
        self.MIN_PRICE_CHANGE = 1.0
        self.MIN_TIME_WINDOW = 10
        self.MAX_TIME_WINDOW = 300
        self.MIN_OCCURRENCES = 3
        self.MIN_WIN_RATE = 60
        self.BACKTEST_PERIOD = 24
        self.TARGET_PROFIT_PERCENT = 1.0
        self.MIN_PROFITABILITY = 1.5
        self.MAX_PATTERNS_PER_TOKEN = 5
        self.MAX_SLIPPAGE = 0.5
        self.MIN_PROFIT_PERCENT = 0.5
        self.MAX_POSITION_AGE = 600
        self.MAX_GAS_PRICE = 200
        self.GAS_LIMIT = 200000
        self.PREVENT_SEQUENTIAL_TRADES = True
        self.PRICE_HISTORY_DURATION = 24
        self.MAX_PRICE_HISTORY = 10000
        self.POOL_FEES = {'LOW': 500, 'MEDIUM': 3000, 'HIGH': 10000}
        self.PATTERN_TYPES = {'BUY': 'buy', 'SELL': 'sell'}
        self.CHAINS = {
            'arbitrum': {'name': 'Arbitrum One', 'chainId': 42161, 'ws': 'wss://arbitrum-one-rpc.publicnode.com', 'factory': '0x1F98431c8aD98523631AE4a59f267346ea31F984', 'wrappedNative': '0x82aF49447D8a07e3bd95BD0d56f35241523fBab1', 'quoteMode': 'native', 'quoteLabel': 'ETH', 'stables': ['0xaf88d065e77c8cC2239327C5EDb3A432268e5831', '0xFd086bC7CD5C481DCC9C85ebE478A1C0b69FCbb9']},
            'ethereum': {'name': 'Ethereum Mainnet', 'chainId': 1, 'ws': 'wss://ethereum-rpc.publicnode.com', 'factory': '0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f', 'wrappedNative': '0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2', 'quoteMode': 'native', 'quoteLabel': 'ETH', 'stables': ['0xA0b86991c6218b36c1d19d4a2e9eb0ce3606eb48', '0xdAC17F958D2ee523a2206206994597C13D831ec7']},
            'base': {'name': 'Base', 'chainId': 8453, 'ws': 'wss://base-rpc.publicnode.com', 'factory': '0x33128a8fC17869897dcE68Ed026d694621f6FDfD', 'wrappedNative': '0x4200000000000000000000000000000000000006', 'quoteMode': 'native', 'quoteLabel': 'ETH', 'stables': ['0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913', '0x60a3e35cc302bfa44cb288bc5a4f316fdb1adb42']},
            'optimism': {'name': 'Optimism', 'chainId': 10, 'ws': 'wss://optimism-rpc.publicnode.com', 'factory': '0x1F98431c8aD98523631AE4a59f267346ea31F984', 'wrappedNative': '0x4200000000000000000000000000000000000006', 'quoteMode': 'native', 'quoteLabel': 'ETH', 'stables': ['0x0b2C639c533813f4AaA9D7837CAf62653d097Ff85', '0x7F5c764cBc14f9669B88837ca1490cCa17c31607']},
            'polygon': {'name': 'Polygon', 'chainId': 137, 'ws': 'wss://polygon-bor-rpc.publicnode.com', 'factory': '0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f', 'wrappedNative': '0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270', 'quoteMode': 'native', 'quoteLabel': 'WPOL', 'stables': ['0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174', '0xc2132D05D31c914a87C6611C10748AEb04B58e8F']}
        }
        self.KNOWN_TOKENS = {
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

state = AppState()

def initialize_known_tokens():
    network_tokens = {
        'arbitrum': {'WETH': '0x82aF49447D8a07e3bd95BD0d56f35241523fBab1', 'WBTC': '0x2f2a2543B76A416654947aaB75B4e35b52a17231', 'UNI': '0xfa7F8980b0f1E64A2062791cc3b0871572f1F7f0', 'LINK': '0xf97f4df75117a78c1A5a0DBb814Af92458539FB4', 'ARB': '0x912CE59144196C11c48067255325c5414506085A', 'GMX': '0xfc5A1A6EB076a2C7aD06eD22C5C769A78b3Fa3A1', 'USDC': '0xaf88d065e77c8cC2239327C5EDb3A432268e5831', 'USDT': '0xFd086bC7CD5C481DCC9C85ebE478A1C0b69FCbb9'},
        'ethereum': {'WETH': '0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2', 'WBTC': '0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599', 'UNI': '0x1f9840a85d5aF5bf1D1762F925BDADDd9702f158', 'LINK': '0x514910771AF9Ca656af840dff83E8264EcF986CA', 'USDC': '0xA0b86991c6218b36c1d19d4a2e9eb0ce3606eb48', 'USDT': '0xdAC17F958D2ee523a2206206994597C13D831ec7'},
        'base': {'WETH': '0x4200000000000000000000000000000000000006', 'WBTC': '0x6025518810202842D4E7b537291033197F2B498c', 'USDC': '0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913', 'USDT': '0x60a3e35cc302bfa44cb288bc5a4f316fdb1adb42'},
        'optimism': {'WETH': '0x4200000000000000000000000000000000000006', 'WBTC': '0x68f180fcCe6836688e9084f035309fC299A09C00', 'UNI': '0x6fd9d7AD17242c41f7131d257212c54A0e816691', 'LINK': '0x350a791Bfc2C21F9Ed5d10980Dad2e2638ffa7f6', 'USDC': '0x0b2C639c533813f4AaA9D7837CAf62653d097Ff85', 'USDT': '0x7F5c764cBc14f9669B88837ca1490cCa17c31607'},
        'polygon': {'WETH': '0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270', 'WBTC': '0x1BFD67037B42Cf73acF2047067bd4F2C47D9BfD6', 'UNI': '0xb33EaAd8d922B1083446DC23f610c2567fB5180', 'LINK': '0x53E0bca35eC356BD5ddDFebbD1Fc0fD03Fad3981', 'USDC': '0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174', 'USDT': '0xc2132D05D31c914a87C6611C10748AEb04B58e8F'}
    }
    network = state.CHAINS[state.current_chain_key]
    if network and network_tokens.get(state.current_chain_key):
        for symbol, address in network_tokens[state.current_chain_key].items():
            if symbol in state.KNOWN_TOKENS:
                state.KNOWN_TOKENS[symbol]['address'] = address

def calculate_trade_amount():
    gas_price = state.current_gas_price or state.MAX_GAS_PRICE
    gas_limit = state.GAS_LIMIT
    available_eth = state.portfolio['currentEth'] or state.STARTING_ETH
    gas_cost_per_trade = (gas_price * gas_limit * 2) / 1e9 / 1e9
    max_trades = state.MAX_TRADES
    total_gas_cost = gas_cost_per_trade * max_trades
    percent_based = available_eth * (state.TRADE_AMOUNT_PERCENT / 100)
    amount_after_fees = percent_based - (total_gas_cost / max_trades)
    trade_amount = min(percent_based, amount_after_fees)
    trade_amount = max(trade_amount, state.MIN_TRADE_AMOUNT_ETH)
    trade_amount = min(trade_amount, available_eth * 0.95)
    return trade_amount

def detect_buy_patterns_for_token(history, token):
    if not history or len(history) < 10:
        return []
    min_change = state.MIN_PRICE_CHANGE / 100
    min_time = state.MIN_TIME_WINDOW * 1000
    max_time = state.MAX_TIME_WINDOW * 1000
    patterns = []
    for i in range(5, len(history) - 5):
        current = history[i]
        is_minima = (current['price'] <= history[i-1]['price'] and current['price'] <= history[i-2]['price'] and
                     current['price'] <= history[i+1]['price'] and current['price'] <= history[i+2]['price'])
        if is_minima:
            for j in range(i-1, max(0, i-11), -1):
                prev = history[j]
                drop_pct = (current['price'] - prev['price']) / prev['price']
                time_diff = current['timestamp'] - prev['timestamp']
                if drop_pct <= -min_change and min_time <= time_diff <= max_time:
                    for k in range(i+1, min(len(history), i+11)):
                        next_p = history[k]
                        rise_pct = (next_p['price'] - current['price']) / current['price']
                        rise_time = next_p['timestamp'] - current['timestamp']
                        min_required_rise = abs(drop_pct) + (state.MIN_PROFITABILITY / 100)
                        if rise_pct >= min_required_rise and min_time <= rise_time <= max_time:
                            patterns.append({'type': 'buy', 'dropPct': abs(drop_pct)*100, 'dropTime': time_diff/1000,
                                             'risePct': rise_pct*100, 'riseTime': rise_time/1000, 'token': token, 'timestamp': current['timestamp']})
                            break
                    break
    return patterns

def get_pattern_key(pattern):
    if pattern['type'] == 'buy':
        return f"BUY_{round(pattern['dropPct']*10)/10}%_{round(pattern['dropTime'])}s_{round(pattern['risePct']*10)/10}%_{round(pattern['riseTime'])}s"
    return f"SELL_{round(pattern['risePct']*10)/10}%_{round(pattern['riseTime'])}s"

def validate_patterns_with_backtesting(patterns):
    backtest_period_ms = state.BACKTEST_PERIOD * 60 * 60 * 1000
    keys_to_remove = []
    for key, pattern in patterns.items():
        history = state.price_history.get(pattern['token'])
        if not history or len(history) < 20:
            keys_to_remove.append(key)
            continue
        backtest_history = [h for h in history if h['timestamp'] >= (datetime.now().timestamp() * 1000) - backtest_period_ms]
        if len(backtest_history) < 20:
            keys_to_remove.append(key)
            continue
        total_trades = 0
        winning_trades = 0
        occurrences = 0
        total_profit = 0
        trade_amount_eth = calculate_trade_amount()
        for i in range(10, len(backtest_history) - 10):
            current = backtest_history[i]
            if pattern['type'] == 'buy':
                for j in range(i-1, max(0, i-11), -1):
                    prev = backtest_history[j]
                    drop_pct = (current['price'] - prev['price']) / prev['price']
                    time_diff = (current['timestamp'] - prev['timestamp']) / 1000
                    if abs(drop_pct) >= pattern['dropPct']/100 and pattern['dropTime']-5 <= time_diff <= pattern['dropTime']+5:
                        for k in range(i+1, min(len(backtest_history), i+11)):
                            next_p = backtest_history[k]
                            rise_pct = (next_p['price'] - current['price']) / current['price']
                            rise_time = (next_p['timestamp'] - current['timestamp']) / 1000
                            if rise_pct >= pattern['risePct']/100 and pattern['riseTime']-5 <= rise_time <= pattern['riseTime']+5:
                                total_trades += 1
                                occurrences += 1
                                entry_price = current['price']
                                exit_price = next_p['price']
                                token_amount = trade_amount_eth / entry_price
                                exit_value = token_amount * exit_price
                                fee_percent = 0.0005
                                buy_fee = trade_amount_eth * fee_percent
                                sell_fee = exit_value * fee_percent
                                profit = exit_value - trade_amount_eth - buy_fee - sell_fee
                                if profit > 0: winning_trades += 1
                                total_profit += profit
                                i = k
                                break
                        break
        avg_profitability = (total_profit / trade_amount_eth / total_trades * 100) if total_trades > 0 else 0
        win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
        if occurrences < state.MIN_OCCURRENCES or win_rate < state.MIN_WIN_RATE or avg_profitability < state.MIN_PROFITABILITY or pattern['risePct'] <= pattern['dropPct']:
            keys_to_remove.append(key)
        else:
            pattern['winRate'] = win_rate
            pattern['totalTrades'] = total_trades
            pattern['winningTrades'] = winning_trades
            pattern['avgProfitability'] = avg_profitability
            pattern['totalProfit'] = total_profit
    for key in keys_to_remove:
        del patterns[key]

def update_portfolio_for_trade(trade, action, trade_result):
    token = trade['token']
    gas_cost_eth = trade_result['gasUsed'] * trade_result['gasPrice'] / 1e9 / 1e9
    fee_cost_eth = trade_result['feeAmount']
    total_cost_eth = gas_cost_eth + fee_cost_eth
    if action == 'buy':
        eth_balance = state.portfolio['balances'].get('ETH', 0)
        total_trade_cost = trade_result['amountETH'] + total_cost_eth
        if eth_balance < total_trade_cost:
            trade['status'] = 'failed'
            trade['reason'] = 'Not enough ETH'
            state.portfolio['failedTrades'] += 1
            return
        state.portfolio['balances']['ETH'] = eth_balance - total_trade_cost
        if token not in state.portfolio['balances']:
            state.portfolio['balances'][token] = 0
        state.portfolio['balances'][token] += trade_result['tokenAmount']
        position = next((p for p in state.portfolio['positions'] if p['token'] == token and p['status'] == 'open'), None)
        if not position:
            position = {'id': trade['id'], 'token': token, 'entryPrice': trade_result['executionPrice'], 'amount': trade_result['tokenAmount'],
                        'usdValue': trade_result['amountETH'], 'entryTime': time.time(), 'gasPaid': gas_cost_eth, 'feesPaid': fee_cost_eth,
                        'status': 'open', 'tradeId': trade['id'], 'pattern': trade['pattern']}
            state.portfolio['positions'].append(position)
        else:
            position['amount'] += trade_result['tokenAmount']
            position['usdValue'] += trade_result['amountETH']
            position['gasPaid'] += gas_cost_eth
            position['feesPaid'] += fee_cost_eth
        state.portfolio['gasSpent'] += gas_cost_eth
        state.portfolio['feesPaid'] += fee_cost_eth
        state.portfolio['totalFees'] += total_cost_eth
    elif action == 'sell':
        open_positions = sorted([p for p in state.portfolio['positions'] if p['token'] == token and p['status'] == 'open'], key=lambda x: x['entryTime'])
        if not open_positions:
            trade['status'] = 'failed'
            trade['reason'] = 'No open position'
            state.portfolio['failedTrades'] += 1
            return
        position = open_positions[0]
        amount_to_sell = min(trade_result['tokenAmount'], position['amount'])
        sell_value_eth = amount_to_sell * trade_result['executionPrice']
        cost_basis = (amount_to_sell * position['entryPrice']) + (amount_to_sell / position['amount']) * (position['feesPaid'] + position['gasPaid'])
        pnl = sell_value_eth - cost_basis - total_cost_eth
        position['amount'] -= amount_to_sell
        position['feesPaid'] += fee_cost_eth
        position['gasPaid'] += gas_cost_eth
        if position['amount'] <= 0.000001:
            position['status'] = 'closed'
            position['exitPrice'] = trade_result['executionPrice']
            position['exitTime'] = time.time()
            position['pnl'] = pnl
            state.portfolio['realizedPnL'] += pnl
            if pnl > 0: state.portfolio['winningTrades'] += 1
            elif pnl < 0: state.portfolio['losingTrades'] += 1
        state.portfolio['balances']['ETH'] = state.portfolio['balances'].get('ETH', 0) + sell_value_eth - total_cost_eth
        trade['pnl'] = pnl
        trade['status'] = 'closed'
        trade['closedAt'] = datetime.now().isoformat()
        if token in state.portfolio['balances']:
            state.portfolio['balances'][token] -= amount_to_sell
            if state.portfolio['balances'][token] < 0.000001:
                del state.portfolio['balances'][token]
        state.portfolio['gasSpent'] += gas_cost_eth
        state.portfolio['feesPaid'] += fee_cost_eth
        state.portfolio['totalFees'] += total_cost_eth
    update_portfolio_equity()

def update_portfolio_equity():
    total_eth = state.portfolio['balances'].get('ETH', 0)
    for token, amount in state.portfolio['balances'].items():
        if token == 'ETH': continue
        price = state.prices.get(token, 0)
        total_eth += amount * price
    for pos in state.portfolio['positions']:
        if pos['status'] == 'open':
            current_price = state.prices.get(pos['token'], pos['entryPrice'])
            current_value = pos['amount'] * current_price
            unrealized_pnl = current_value - (pos['amount'] * pos['entryPrice']) - pos['feesPaid'] - pos['gasPaid']
            total_eth += unrealized_pnl
    state.portfolio['currentEth'] = total_eth
    state.portfolio['unrealizedPnL'] = total_eth - state.portfolio['startingEth'] - state.portfolio['realizedPnL']
    state.portfolio['equityHistory'].append({'timestamp': time.time(), 'ethValue': state.portfolio['currentEth']})
    if len(state.portfolio['equityHistory']) > 1000:
        state.portfolio['equityHistory'].pop(0)

def update_pattern_stats():
    patterns_array = list(state.active_patterns.values())
    state.pattern_stats['totalPatterns'] = len(patterns_array)
    state.pattern_stats['buyPatterns'] = len([p for p in patterns_array if p['type'] == 'buy'])
    state.pattern_stats['sellPatterns'] = len([p for p in patterns_array if p['type'] == 'sell'])
    state.pattern_stats['tokensWithPatterns'] = len(set(p['token'] for p in patterns_array))

def update_prices_for_session():
    if not state.is_running or not state.active_session:
        return
    try:
        tokens_to_update = list(state.observed_tokens)
        for token in tokens_to_update:
            price = state.prices.get(token)
            if price is not None:
                ts = time.time() * 1000
                if token not in state.price_history:
                    state.price_history[token] = []
                state.price_history[token].append({'price': price, 'timestamp': ts})
                if len(state.price_history[token]) > state.MAX_PRICE_HISTORY:
                    state.price_history[token].pop(0)
                cutoff = ts - (state.PRICE_HISTORY_DURATION * 60 * 60 * 1000)
                while state.price_history[token] and state.price_history[token][0]['timestamp'] < cutoff:
                    state.price_history[token].pop(0)
        state.last_price_update = datetime.now()
        update_pattern_stats()
        socketio.emit('state_update', {
            'prices': state.prices,
            'portfolio': state.portfolio,
            'patterns': state.active_patterns,
            'stats': state.pattern_stats,
            'gasPrice': state.current_gas_price,
            'lastUpdate': state.last_price_update.isoformat()
        })
    except Exception as e:
        logger.error(f"Error updating prices: {e}")

def run_bot():
    logger.info("Bot started")
    state.is_running = True
    state.start_time = datetime.now()
    state.manually_stopped = False
    update_portfolio_equity()
    socketio.emit('state_update', {'isRunning': True, 'startTime': state.start_time.isoformat()})
    while state.is_running:
        try:
            update_prices_for_session()
            time.sleep(1)
        except Exception as e:
            logger.error(f"Bot loop error: {e}")
            time.sleep(1)
    logger.info("Bot stopped")

@app.route('/')
def index():
    return render_template('templates/index.html')

@app.route('/api/state')
def get_state():
    try:
        trade_amount = calculate_trade_amount()
    except Exception:
        trade_amount = 0
    return jsonify({
        'isRunning': state.is_running,
        'is_running': state.is_running,
        'prices': state.prices,
        'portfolio': state.portfolio,
        'patterns': state.active_patterns,
        'active_patterns': state.active_patterns,
        'stats': state.pattern_stats,
        'pattern_stats': {
            'total_patterns': state.pattern_stats.get('totalPatterns', 0),
            'buy_patterns': state.pattern_stats.get('buyPatterns', 0),
            'sell_patterns': state.pattern_stats.get('sellPatterns', 0),
            'tokens_with_patterns': state.pattern_stats.get('tokensWithPatterns', 0)
        },
        'gasPrice': state.current_gas_price,
        'current_gas_price': state.current_gas_price,
        'lastUpdate': state.last_price_update.isoformat() if state.last_price_update else None,
        'last_price_update': state.last_price_update.isoformat() if state.last_price_update else None,
        'walletConnected': state.wallet_connected,
        'liveMode': state.live_mode,
        'live_mode': state.live_mode,
        'current_network': state.current_chain_key,
        'observed_tokens': list(state.observed_tokens),
        'trades': state.trades,
        'constants': {
            'BLOCKCHAIN_NETWORK': state.BLOCKCHAIN_NETWORK,
            'STARTING_ETH': state.STARTING_ETH,
            'TRADE_AMOUNT_PERCENT': state.TRADE_AMOUNT_PERCENT,
            'MIN_TRADE_AMOUNT_ETH': state.MIN_TRADE_AMOUNT_ETH,
            'MAX_TRADES': state.MAX_TRADES,
            'TRADE_COOLDOWN': state.TRADE_COOLDOWN,
            'MIN_PRICE_CHANGE': state.MIN_PRICE_CHANGE,
            'MIN_TIME_WINDOW': state.MIN_TIME_WINDOW,
            'MAX_TIME_WINDOW': state.MAX_TIME_WINDOW,
            'MIN_OCCURRENCES': state.MIN_OCCURRENCES,
            'MIN_WIN_RATE': state.MIN_WIN_RATE,
            'BACKTEST_PERIOD': state.BACKTEST_PERIOD,
            'TARGET_PROFIT_PERCENT': state.TARGET_PROFIT_PERCENT,
            'MIN_PROFITABILITY': state.MIN_PROFITABILITY,
            'MAX_PATTERNS_PER_TOKEN': state.MAX_PATTERNS_PER_TOKEN,
            'MAX_SLIPPAGE': state.MAX_SLIPPAGE,
            'MIN_PROFIT_PERCENT': state.MIN_PROFIT_PERCENT,
            'MAX_POSITION_AGE': state.MAX_POSITION_AGE,
            'MAX_GAS_PRICE': state.MAX_GAS_PRICE,
            'GAS_LIMIT': state.GAS_LIMIT,
            'PREVENT_SEQUENTIAL_TRADES': state.PREVENT_SEQUENTIAL_TRADES,
            'PRICE_HISTORY_DURATION': state.PRICE_HISTORY_DURATION,
            'MAX_PRICE_HISTORY': state.MAX_PRICE_HISTORY
        },
        'start_time': state.start_time.timestamp() if state.start_time else None,
        'trade_amount_eth': trade_amount
    })

@app.route('/api/connect_wallet', methods=['POST'])
def connect_wallet():
    state.wallet_connected = True
    return jsonify({'status': 'connected'})

@app.route('/api/switch_network', methods=['POST'])
def switch_network():
    data = request.json
    network = data.get('network')
    if network in state.CHAINS:
        state.current_chain_key = network
        state.BLOCKCHAIN_NETWORK = network
        initialize_known_tokens()
        return jsonify({'status': 'network_switched', 'network': network})
    return jsonify({'status': 'invalid_network'}), 400

@app.route('/api/test_connection', methods=['POST'])
def test_connection():
    try:
        w3 = Web3(Web3.WebSocketProvider(state.CHAINS[state.current_chain_key]['ws']))
        if w3.is_connected():
            return jsonify({'status': 'connected'})
        return jsonify({'status': 'disconnected'}), 500
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/start_bot', methods=['POST'])
def start_bot():
    if state.is_running:
        return jsonify({'success': False, 'message': 'Already running'})
    threading.Thread(target=run_bot, daemon=True).start()
    return jsonify({'success': True, 'message': 'Started'})

@app.route('/api/stop_bot', methods=['POST'])
def stop_bot():
    if not state.is_running:
        return jsonify({'success': False, 'message': 'Not running'})
    state.is_running = False
    state.manually_stopped = True
    return jsonify({'success': True, 'message': 'Stopped'})

@app.route('/api/toggle_live_mode', methods=['POST'])
def toggle_live_mode():
    state.live_mode = not state.live_mode
    return jsonify({'success': True, 'live_mode': state.live_mode, 'message': 'Mode toggled'})

@app.route('/api/refresh_prices', methods=['POST'])
def refresh_prices():
    try:
        update_prices_for_session()
        return jsonify({'success': True, 'message': 'Prices refreshed'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/clear_trade_history', methods=['POST'])
def clear_trade_history():
    state.trades = []
    return jsonify({'success': True, 'message': 'History cleared'})

@app.route('/api/clear_patterns', methods=['POST'])
def clear_patterns():
    state.active_patterns = {}
    return jsonify({'success': True, 'message': 'Patterns cleared'})

@app.route('/api/export_trade_history')
def export_trade_history():
    return jsonify({'success': True, 'trades': state.trades})

@app.route('/api/export_patterns')
def export_patterns():
    return jsonify({'success': True, 'patterns': list(state.active_patterns.values())})

if __name__ == '__main__':
    initialize_known_tokens()
    socketio.run(app, host='0.0.0.0', port=5050, debug=True)