import os
import json
import time
import math
import random
import threading
from datetime import datetime
from flask import Flask, render_template, jsonify, request, send_from_directory
from flask_socketio import SocketIO, emit
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = 'safetrader_secret'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# Global State
state = {
    'isRunning': False,
    'liveMode': False,
    'network': 'arbitrum',
    'startTime': None,
    'startingEth': 0.0033,
    'currentEth': 0.0033,
    'realizedPnL': 0.0,
    'unrealizedPnL': 0.0,
    'gasSpent': 0.0,
    'dexFees': 0.0,
    'totalFees': 0.0,
    'trackedTokensCount': 0,
    'totalPatterns': 0,
    'buyPatterns': 0,
    'tokensWithPatterns': 0,
    'prices': {},
    'equityHistory': [{'timestamp': time.time(), 'ethValue': 0.0033}],
    'balances': {'ETH': 0.0033},
    'positions': [],
    'trades': [],
    'activePatterns': [],
    'patternStats': {'totalPatterns': 0, 'buyPatterns': 0, 'sellPatterns': 0, 'tokensWithPatterns': 0}
}

# Configuration Constants
CONFIG = {
    'tradeAmountPercent': 10, 'minTradeAmountEth': 0.00001, 'maxTrades': 3,
    'tradeCooldown': 60, 'minPriceChange': 1.0, 'minTimeWindow': 10,
    'maxTimeWindow': 300, 'minOccurrences': 2, 'minWinRate': 60,
    'backtestPeriod': 24, 'targetProfitPercent': 1.0, 'minProfitability': 1.5,
    'maxPatternsPerToken': 5, 'maxSlippage': 0.5, 'minProfitPercent': 0.5,
    'maxPositionAge': 600, 'maxGasPrice': 200, 'gasLimit': 200000,
    'preventSequentialTrades': True, 'priceHistoryDuration': 24, 'maxPriceHistory': 10000
}

# Uniswap Chain Configs
CHAINS = {
    'arbitrum': {'ws': 'wss://arbitrum-one-rpc.publicnode.com', 'chainId': 42161, 'wrappedNative': '0x82aF49447D8a07e3bd95BD0d56f35241523fBab1'},
    'ethereum': {'ws': 'wss://ethereum-rpc.publicnode.com', 'chainId': 1, 'wrappedNative': '0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2'},
    'base': {'ws': 'wss://base-rpc.publicnode.com', 'chainId': 8453, 'wrappedNative': '0x4200000000000000000000000000000000000006'},
    'optimism': {'ws': 'wss://optimism-rpc.publicnode.com', 'chainId': 10, 'wrappedNative': '0x4200000000000000000000000000000000000006'},
    'polygon': {'ws': 'wss://polygon-bor-rpc.publicnode.com', 'chainId': 137, 'wrappedNative': '0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270'}
}

price_poller = None

def update_state():
    totalEth = state['balances'].get('ETH', 0)
    for token, amount in state['balances'].items():
        if token != 'ETH' and token in state['prices']:
            totalEth += amount * state['prices'][token]
    state['currentEth'] = totalEth
    state['unrealizedPnL'] = state['currentEth'] - state['startingEth'] - state['realizedPnL']
    state['equityHistory'].append({'timestamp': time.time(), 'ethValue': state['currentEth']})
    if len(state['equityHistory']) > 1000:
        state['equityHistory'].pop(0)

def emit_state():
    update_state()
    socketio.emit('state_update', {
        'type': 'state_update',
        'state': {
            'isRunning': state['isRunning'],
            'liveMode': state['liveMode'],
            'network': state['network'],
            'startingEth': state['startingEth'],
            'currentEth': state['currentEth'],
            'realizedPnL': state['realizedPnL'],
            'unrealizedPnL': state['unrealizedPnL'],
            'gasSpent': state['gasSpent'],
            'dexFees': state['dexFees'],
            'totalFees': state['totalFees'],
            'trackedTokensCount': len(state['prices']),
            'totalPatterns': state['totalPatterns'],
            'buyPatterns': state['buyPatterns'],
            'tokensWithPatterns': state['tokensWithPatterns'],
            'prices': {k: v for k, v in list(state['prices'].items())[:20]},
            'equityHistory': state['equityHistory'][-100:],
            'balances': {k: v for k, v in state['balances'].items() if v > 0},
            'positions': state['positions'][-20:],
            'activePatterns': state['activePatterns'][-20:],
            **CONFIG
        }
    })

def start_price_polling():
    global price_poller
    while state['isRunning']:
        try:
            if not state['prices']:
                state['prices'] = {'WETH': 0.0033, 'USDC': 3000.0, 'WBTC': 45000.0, 'ARB': 1.2, 'GMX': 50.0}
                state['trackedTokensCount'] = len(state['prices'])
            
            for token in list(state['prices'].keys()):
                state['prices'][token] *= (1 + (0.0005 * (random.random() - 0.5)))
            
            state['prices']['WETH'] = 0.0033
            update_state()
            socketio.emit('state_update', {'type': 'state_update', 'state': {'prices': state['prices'], 'trackedTokensCount': len(state['prices'])}})
        except Exception as e:
            print(f"Polling error: {e}")
        time.sleep(1)

@app.route('/')
def index():
    return send_from_directory(os.path.dirname(__file__), 'index.html')

@app.route('/api/config')
def get_config():
    return jsonify({'liveMode': state['liveMode'], 'network': state['network']})

@app.route('/api/dashboard')
def get_dashboard():
    return jsonify({
        'prices': state['prices'],
        'stats': {
            'totalPatterns': state['totalPatterns'],
            'buyPatterns': state['buyPatterns'],
            'tokensWithPatterns': state['tokensWithPatterns'],
            'gasSpent': state['gasSpent'],
            'dexFees': state['dexFees'],
            'totalFees': state['totalFees']
        }
    })

@app.route('/api/trades')
def get_trades():
    return jsonify({'trades': state['trades']})

@app.route('/api/portfolio')
def get_portfolio():
    return jsonify({
        'balances': state['balances'],
        'positions': state['positions'],
        'realizedPnL': state['realizedPnL'],
        'unrealizedPnL': state['unrealizedPnL'],
        'currentEth': state['currentEth'],
        'startingEth': state['startingEth']
    })

@socketio.on('connect')
def handle_connect():
    print('Client connected')
    emit_state()

@socketio.on('disconnect')
def handle_disconnect():
    print('Client disconnected')

@socketio.on('start_bot')
def handle_start_bot():
    if not state['isRunning']:
        state['isRunning'] = True
        state['startTime'] = time.time()
        threading.Thread(target=start_price_polling, daemon=True).start()
        print("Bot started")
        emit_state()

@socketio.on('stop_bot')
def handle_stop_bot():
    if state['isRunning']:
        state['isRunning'] = False
        print("Bot stopped")
        emit_state()

@socketio.on('toggle_live_mode')
def handle_toggle_live_mode():
    state['liveMode'] = not state['liveMode']
    print(f"Live mode: {state['liveMode']}")
    emit_state()

@socketio.on('switch_network')
def handle_switch_network(data):
    state['network'] = data.get('network', 'arbitrum')
    print(f"Switched to {state['network']}")
    emit_state()

@socketio.on('refresh_prices')
def handle_refresh_prices():
    print("Refreshing prices...")
    emit_state()

@socketio.on('clear_trade_history')
def handle_clear_trade_history():
    state['trades'] = []
    state['positions'] = []
    state['realizedPnL'] = 0
    state['equityHistory'] = [{'timestamp': time.time(), 'ethValue': state['startingEth']}]
    print("Trade history cleared")
    emit_state()

@socketio.on('clear_patterns')
def handle_clear_patterns():
    state['activePatterns'] = []
    state['totalPatterns'] = 0
    state['buyPatterns'] = 0
    state['tokensWithPatterns'] = 0
    print("Patterns cleared")
    emit_state()

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)