import os
from flask import Flask, render_template, jsonify, request
from web3 import Web3
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

class Config:
    APP_VERSION = '4.1.0'
    BLOCKCHAIN_NETWORK = 'arbitrum'
    UNISWAP_VERSION = 'v3'
    STARTING_ETH = 0.0033
    TRADE_AMOUNT_PERCENT = 0.5
    MIN_TRADE_AMOUNT_ETH = 0.0003
    MAX_TRADES = 200
    TRADE_COOLDOWN = 60
    MIN_PRICE_CHANGE = 1.0
    MIN_TIME_WINDOW = 10
    MAX_TIME_WINDOW = 300
    MIN_OCCURRENCES = 2
    MIN_WIN_RATE = 60
    BACKTEST_PERIOD = 24
    TARGET_PROFIT_PERCENT = 1.0
    MIN_PROFITABILITY = 1.5
    MAX_PATTERNS_PER_TOKEN = 5
    MAX_SLIPPAGE = 0.5
    MIN_PROFIT_PERCENT = 0.5
    MAX_POSITION_AGE = 600
    MAX_GAS_PRICE = 200
    GAS_LIMIT = 200000
    PREVENT_SEQUENTIAL_TRADES = True
    PRICE_HISTORY_DURATION = 24
    MAX_PRICE_HISTORY = 10000
    RPC_URLS = {
        'arbitrum': 'https://arb1.arbitrum.io/rpc',
        'ethereum': 'https://eth.llamarpc.com',
        'base': 'https://mainnet.base.org',
        'optimism': 'https://mainnet.optimism.io',
        'polygon': 'https://polygon-rpc.com'
    }
    UNISWAP_V3_ROUTER = '0xE592427A0AEce92De3Edee1F18E0157C05861564'
    WETH_ADDRESSES = {
        'arbitrum': '0x82aF49447D8a07e3bd95BD0d56f35241523fBab1',
        'ethereum': '0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2',
        'base': '0x4200000000000000000000000000000000000006',
        'optimism': '0x4200000000000000000000000000000000000006',
        'polygon': '0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270'
    }

config = Config()
PRIVATE_KEY = os.getenv('PRIVATE_KEY', '')
LIVE_MODE = bool(PRIVATE_KEY)
current_network = config.BLOCKCHAIN_NETWORK
w3 = None

def init_web3():
    global w3
    if LIVE_MODE and PRIVATE_KEY:
        rpc = config.RPC_URLS.get(current_network, config.RPC_URLS['arbitrum'])
        w3 = Web3(Web3.HTTPProvider(rpc))
        return w3.is_connected()
    return False

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/status')
def get_status():
    return jsonify({
        'isRunning': False,
        'liveMode': LIVE_MODE,
        'network': current_network,
        'version': config.APP_VERSION
    })

@app.route('/api/config', methods=['GET', 'POST'])
def get_config():
    if request.method == 'POST':
        data = request.json
        global current_network
        current_network = data.get('network', current_network)
        return jsonify({'status': 'updated', 'network': current_network})
    return jsonify({k: v for k, v in config.__dict__.items() if not k.startswith('_')})

@app.route('/api/dashboard')
def get_dashboard():
    return jsonify({
        'prices': {},
        'patterns': [],
        'stats': {
            'totalPatterns': 0,
            'buyPatterns': 0,
            'tokensWithPatterns': 0,
            'gasSpent': 0,
            'dexFees': 0,
            'totalFees': 0
        }
    })

@app.route('/api/portfolio')
def get_portfolio():
    return jsonify({
        'startingEth': config.STARTING_ETH,
        'currentEth': config.STARTING_ETH,
        'realizedPnL': 0,
        'unrealizedPnL': 0,
        'balances': {},
        'positions': []
    })

@app.route('/api/trades')
def get_trades():
    return jsonify({'trades': []})

if __name__ == '__main__':
    init_web3()
    app.run(debug=True, host='0.0.0.0', port=5000)