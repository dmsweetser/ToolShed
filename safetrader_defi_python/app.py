import asyncio
import json
import time
import threading
import os
import random
import math
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set, Tuple

# ========== CONFIGURATION ==========
@dataclass
class Config:
    # Network
    BLOCKCHAIN_NETWORK: str = 'arbitrum'
    UNISWAP_VERSION: str = 'v3'

    # Trading Budget
    STARTING_ETH: float = 0.0033
    TRADE_AMOUNT_PERCENT: float = 0.5
    MIN_TRADE_AMOUNT_ETH: float = 0.0003
    MAX_TRADES: int = 10
    TRADE_COOLDOWN: int = 60  # seconds

    # Pattern Detection
    MIN_PRICE_CHANGE: float = 0.1  # %
    MIN_TIME_WINDOW: int = 3       # seconds
    MAX_TIME_WINDOW: int = 600     # seconds
    MIN_OCCURRENCES: int = 2

    # Profit Targets (PROFIT-ONLY MODE)
    MIN_PROFIT_PERCENT: float = 2.0  # Sell only if profit >= 2%

    # Safety
    MAX_SLIPPAGE: float = 0.5  # %
    MAX_GAS_PRICE: int = 200    # gwei
    GAS_LIMIT: int = 200000
    PREVENT_SEQUENTIAL_TRADES: bool = True

    # Data
    PRICE_HISTORY_DURATION: int = 24  # hours
    MAX_PRICE_HISTORY: int = 5000

# ========== CONSTANTS ==========
POOL_FEES = {'LOW': 500, 'MEDIUM': 3000, 'HIGH': 10000}
PATTERN_TYPES = {'BUY': 'buy'}

# ========== STATE MANAGEMENT ==========
class State:
    def __init__(self, config: Config):
        self.config = config
        self.is_running = False
        self.current_network = config.BLOCKCHAIN_NETWORK
        self.prices: Dict[str, float] = {}
        self.price_history: Dict[str, List[Tuple[float, float]]] = {}  # {token: [(price, timestamp), ...]}
        self.trades: List[Dict] = []
        self.active_patterns: Dict[str, Dict] = {}  # {pattern_key: pattern_data}
        self.portfolio: Dict = {
            'balances': {'ETH': config.STARTING_ETH},
            'positions': [],
            'realized_pnl': 0,
            'unrealized_pnl': 0,
            'gas_spent': 0,
            'fees_paid': 0,
            'starting_eth': config.STARTING_ETH,
            'current_eth': config.STARTING_ETH,
            'equity_history': [{'timestamp': time.time(), 'eth_value': config.STARTING_ETH}],
            'total_trades': 0,
            'winning_trades': 0,
            'losing_trades': 0,
            'failed_trades': 0,
            'total_fees': 0
        }
        self.last_traded_token = None
        self.last_trade_times: Dict[str, float] = {}
        self.start_time = None
        self.last_price_update = None
        self.current_gas_price = 0.02
        self.manually_stopped = True
        self.observed_tokens: Set[str] = set()
        self.pattern_stats: Dict[str, int] = {'total_patterns': 0, 'tokens_with_patterns': 0}
        self.open_buy_orders: Dict[str, Dict] = {}
        self.pattern_detection_active = False

    def to_dict(self) -> Dict:
        """Convert state to a JSON-serializable dictionary."""
        return {
            'config': asdict(self.config),
            'is_running': self.is_running,
            'current_network': self.current_network,
            'prices': self.prices,
            'price_history': {k: [{'price': p, 'timestamp': t} for p, t in v] for k, v in self.price_history.items()},
            'trades': self.trades,
            'active_patterns': self.active_patterns,
            'portfolio': {
                **self.portfolio,
                'positions': [{k: v for k, v in pos.items() if not k.startswith('_')} for pos in self.portfolio['positions']]
            },
            'last_traded_token': self.last_traded_token,
            'last_trade_times': self.last_trade_times,
            'start_time': self.start_time,
            'last_price_update': self.last_price_update,
            'current_gas_price': self.current_gas_price,
            'observed_tokens': list(self.observed_tokens),
            'pattern_stats': self.pattern_stats,
            'open_buy_orders': self.open_buy_orders,
            'timestamp': datetime.now().isoformat()
        }

# ========== PATTERN DETECTION ==========
class PatternDetector:
    def __init__(self, state: State):
        self.state = state
        self.config = state.config

    def detect_all_patterns(self):
        """Detect buy patterns for all observed tokens."""
        tokens = list(self.state.observed_tokens)
        new_active_patterns = {}

        for token in tokens:
            history = self.state.price_history.get(token, [])
            if len(history) < 5:
                continue

            buy_patterns = self._detect_buy_patterns(history, token)
            for pattern in buy_patterns:
                if not self._is_valid_pattern(pattern):
                    continue

                pattern_key = self._get_pattern_key(pattern)
                existing_key = f"{token}_{pattern_key}"

                if existing_key not in new_active_patterns:
                    new_active_patterns[existing_key] = {
                        **pattern,
                        'token': token,
                        'occurrences': 1,
                        'first_seen': pattern['timestamp'],
                        'last_seen': pattern['timestamp']
                    }
                else:
                    existing = new_active_patterns[existing_key]
                    existing['occurrences'] += 1
                    existing['last_seen'] = max(existing['last_seen'], pattern['timestamp'])

        self._validate_patterns(new_active_patterns)
        self.state.active_patterns = new_active_patterns
        self._update_pattern_stats()
        self.state.last_price_update = time.time()

    def _detect_buy_patterns(self, history: List[Tuple[float, float]], token: str) -> List[Dict]:
        """Detect buy patterns (dips + rises) for a token."""
        patterns = []
        min_change = self.config.MIN_PRICE_CHANGE / 100
        min_time = self.config.MIN_TIME_WINDOW
        max_time = self.config.MAX_TIME_WINDOW

        for i in range(2, len(history) - 2):
            current = history[i]
            is_minima = (
                current[0] <= history[i-1][0] and
                current[0] <= history[i-2][0] and
                current[0] <= history[i+1][0] and
                current[0] <= history[i+2][0]
            )

            if is_minima:
                for j in range(i-1, max(0, i-5), -1):
                    prev = history[j]
                    drop_pct = (current[0] - prev[0]) / prev[0]
                    time_diff = (current[1] - prev[1])  # in seconds

                    if drop_pct <= -min_change and min_time <= time_diff <= max_time:
                        for k in range(i+1, min(len(history), i+6)):
                            next_point = history[k]
                            rise_pct = (next_point[0] - current[0]) / current[0]
                            rise_time = next_point[1] - current[1]

                            if (rise_pct >= (self.config.MIN_PROFIT_PERCENT / 100) and
                                min_time <= rise_time <= max_time):
                                patterns.append({
                                    'type': 'buy',
                                    'drop_pct': abs(drop_pct) * 100,
                                    'drop_time': time_diff,
                                    'rise_pct': rise_pct * 100,
                                    'rise_time': rise_time,
                                    'timestamp': current[1]
                                })
                                break
                        break
        return patterns

    def _is_valid_pattern(self, pattern: Dict) -> bool:
        """Check if a pattern meets validity criteria."""
        if pattern['drop_pct'] > 100 or pattern['rise_pct'] > 100:
            return False
        if pattern['drop_pct'] < 0 or pattern['rise_pct'] < 0:
            return False
        if pattern['drop_time'] > 100 or pattern['rise_time'] > 100:
            return False
        if pattern['drop_time'] < 1 or pattern['rise_time'] < 1:
            return False
        if pattern['rise_pct'] < self.config.MIN_PROFIT_PERCENT:
            return False
        return True

    def _get_pattern_key(self, pattern: Dict) -> str:
        """Generate a unique key for a pattern."""
        return (
            f"BUY_{round(pattern['drop_pct'] * 10) / 10}%"
            f"_{round(pattern['drop_time'])}s_"
            f"{round(pattern['rise_pct'] * 10) / 10}%"
            f"_{round(pattern['rise_time'])}s"
        )

    def _validate_patterns(self, patterns: Dict[str, Dict]):
        """Remove invalid patterns."""
        keys_to_delete = []
        for key, pattern in patterns.items():
            if pattern['drop_pct'] <= 0 or pattern['rise_pct'] <= 0:
                keys_to_delete.append(key)
            elif pattern['rise_pct'] < self.config.MIN_PROFIT_PERCENT:
                keys_to_delete.append(key)
        for key in keys_to_delete:
            del patterns[key]

    def _update_pattern_stats(self):
        """Update pattern statistics."""
        patterns_list = list(self.state.active_patterns.values())
        self.state.pattern_stats['total_patterns'] = len(patterns_list)
        self.state.pattern_stats['tokens_with_patterns'] = len({p['token'] for p in patterns_list})

# ========== TRADING LOGIC ==========
class Trader:
    def __init__(self, state: State):
        self.state = state
        self.config = state.config
        self.detector = PatternDetector(state)

    def calculate_trade_amount(self) -> float:
        """Calculate the amount of ETH to trade based on config."""
        gas_price = self.state.current_gas_price or self.config.MAX_GAS_PRICE
        gas_limit = self.config.GAS_LIMIT
        available_eth = self.state.portfolio['current_eth'] or self.config.STARTING_ETH

        gas_cost_per_trade = (gas_price * gas_limit * 2) / 1e9  # Convert gwei to ETH
        max_trades = self.config.MAX_TRADES
        total_gas_cost = gas_cost_per_trade * max_trades

        percent_amount = available_eth * (self.config.TRADE_AMOUNT_PERCENT / 100)
        min_trade = self.config.MIN_TRADE_AMOUNT_ETH

        amount_after_fees = percent_amount - (total_gas_cost / max_trades)
        trade_amount = max(min(percent_amount, amount_after_fees), min_trade)
        trade_amount = min(trade_amount, available_eth * 0.95)  # Never trade more than 95% of ETH

        return trade_amount

    def simulate_trade(self, token: str, action: str, token_amount: float, current_price: float) -> Dict:
        """Simulate a trade (buy/sell) with realistic slippage, fees, and gas costs."""
        result = {
            'success': True,
            'token_amount': token_amount,
            'amount_eth': token_amount * current_price,
            'execution_price': current_price,
            'gas_used': self._estimate_gas(action, token),
            'gas_price': self.state.current_gas_price or self.config.MAX_GAS_PRICE,
            'fee_amount': 0,
            'price_impact': 0,
            'slippage': 0,
            'reason': None
        }

        # Calculate fees (0.3% for Uniswap V3)
        fee_tier = POOL_FEES['MEDIUM']
        fee_percent = fee_tier / 1e6
        result['fee_amount'] = result['amount_eth'] * fee_percent

        # Calculate price impact (simplified)
        result['price_impact'] = self._calculate_price_impact(token, token_amount)

        # Calculate slippage
        result['slippage'] = result['price_impact'] + random.uniform(0, 0.1)

        if result['slippage'] > self.config.MAX_SLIPPAGE:
            result['success'] = False
            result['reason'] = f"Slippage too high: {result['slippage']:.4f}% > {self.config.MAX_SLIPPAGE}%"
            return result

        # Adjust execution price based on slippage
        if action == 'buy':
            result['execution_price'] = current_price * (1 + result['slippage'] / 100)
        else:
            result['execution_price'] = current_price * (1 - result['slippage'] / 100)

        result['amount_eth'] = token_amount * result['execution_price']
        if action == 'buy':
            result['token_amount'] = result['amount_eth'] / result['execution_price']

        return result

    def _estimate_gas(self, action: str, token: str) -> int:
        """Estimate gas used for a swap."""
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
        return min(base_gas, self.config.GAS_LIMIT)

    def _calculate_price_impact(self, token: str, token_amount: float) -> float:
        """Calculate price impact based on token liquidity."""
        token_price = self.state.prices.get(token, 1.0)
        token_value_eth = token_amount * token_price
        liquidity_eth = 100000  # Simplified: assume $100k liquidity for all tokens
        return min((token_value_eth / liquidity_eth) * 100, 2.0)  # Max 2% impact

    def create_trade(self, token: str, action: str, price: float, token_amount: float, amount_eth: float,
                     pattern: str, status: str, reason: Optional[str] = None, **kwargs) -> Dict:
        """Create a trade object."""
        return {
            'id': f"trade_{int(time.time())}_{random.randint(1000, 9999)}",
            'timestamp': datetime.now().isoformat(),
            'token': token,
            'type': action,
            'price': price,
            'token_amount': token_amount,
            'amount_eth': amount_eth,
            'fee': kwargs.get('fee_amount', 0),
            'gas_used': kwargs.get('gas_used', 0),
            'gas_price': kwargs.get('gas_price', self.state.current_gas_price),
            'price_impact': kwargs.get('price_impact', 0),
            'slippage': kwargs.get('slippage', 0),
            'status': status,
            'reason': reason,
            'pnl': 0,
            'pattern': pattern,
            'network': self.state.current_network
        }

    def update_portfolio(self, trade: Dict, action: str, trade_result: Dict):
        """Update portfolio after a trade."""
        token = trade['token']
        gas_cost_eth = trade_result['gas_used'] * trade_result['gas_price'] / 1e9
        fee_cost_eth = trade_result['fee_amount']
        total_cost_eth = gas_cost_eth + fee_cost_eth

        if action == 'buy':
            eth_balance = self.state.portfolio['balances'].get('ETH', 0)
            total_trade_cost = trade_result['amount_eth'] + total_cost_eth

            if eth_balance < total_trade_cost:
                trade['status'] = 'failed'
                trade['reason'] = 'Insufficient ETH (including fees)'
                self.state.portfolio['failed_trades'] += 1
                self.state.trades.append(trade)
                return

            # Deduct ETH
            self.state.portfolio['balances']['ETH'] = eth_balance - total_trade_cost

            # Add token to portfolio
            if token not in self.state.portfolio['balances']:
                self.state.portfolio['balances'][token] = 0
            self.state.portfolio['balances'][token] += trade_result['token_amount']

            # Add or update position
            position = next((p for p in self.state.portfolio['positions'] if p['token'] == token and p['status'] == 'open'), None)
            if not position:
                position = {
                    'token': token,
                    'entry_price': trade_result['execution_price'],
                    'amount': trade_result['token_amount'],
                    'usd_value': trade_result['amount_eth'],
                    'entry_time': time.time(),
                    'gas_paid': gas_cost_eth,
                    'fees_paid': fee_cost_eth,
                    'status': 'open',
                    'trade_id': trade['id'],
                    'pattern': trade['pattern']
                }
                self.state.portfolio['positions'].append(position)
            else:
                position['amount'] += trade_result['token_amount']
                position['usd_value'] += trade_result['amount_eth']
                position['gas_paid'] += gas_cost_eth
                position['fees_paid'] += fee_cost_eth

            # Update fees
            self.state.portfolio['gas_spent'] += gas_cost_eth
            self.state.portfolio['fees_paid'] += fee_cost_eth
            self.state.portfolio['total_fees'] += total_cost_eth

        elif action == 'sell':
            # Find open position for this token
            open_positions = sorted(
                [p for p in self.state.portfolio['positions'] if p['token'] == token and p['status'] == 'open'],
                key=lambda x: x['entry_time']
            )

            if not open_positions:
                trade['status'] = 'failed'
                trade['reason'] = 'No open position to sell'
                self.state.portfolio['failed_trades'] += 1
                self.state.trades.append(trade)
                return

            position = open_positions[0]
            amount_to_sell = min(trade_result['token_amount'], position['amount'])
            sell_value_eth = amount_to_sell * trade_result['execution_price']

            # Calculate cost basis (FIFO)
            cost_basis = (amount_to_sell * position['entry_price']) + (
                (amount_to_sell / position['amount']) * (position['fees_paid'] + position['gas_paid'])
            )

            # Calculate PnL
            pnl = sell_value_eth - cost_basis - total_cost_eth
            trade['pnl'] = pnl

            # Update position
            position['amount'] -= amount_to_sell
            position['fees_paid'] += fee_cost_eth
            position['gas_paid'] += gas_cost_eth

            if position['amount'] <= 0.000001:
                position['status'] = 'closed'
                position['exit_price'] = trade_result['execution_price']
                position['exit_time'] = time.time()
                position['pnl'] = pnl
                position['sell_trade_id'] = trade['id']

                # Update portfolio stats
                self.state.portfolio['realized_pnl'] += pnl
                if pnl > 0:
                    self.state.portfolio['winning_trades'] += 1
                elif pnl < 0:
                    self.state.portfolio['losing_trades'] += 1

            # Add ETH from sale
            self.state.portfolio['balances']['ETH'] = self.state.portfolio['balances'].get('ETH', 0) + sell_value_eth - total_cost_eth

            # Update token balance
            if token in self.state.portfolio['balances']:
                self.state.portfolio['balances'][token] -= amount_to_sell
                if self.state.portfolio['balances'][token] < 0.000001:
                    del self.state.portfolio['balances'][token]

            # Update fees
            self.state.portfolio['gas_spent'] += gas_cost_eth
            self.state.portfolio['fees_paid'] += fee_cost_eth
            self.state.portfolio['total_fees'] += total_cost_eth

        # Update portfolio equity
        self._update_portfolio_equity()
        trade['status'] = 'closed' if action == 'sell' else 'open'
        self.state.trades.append(trade)

    def _update_portfolio_equity(self):
        """Recalculate portfolio equity (ETH + token values)."""
        total_eth = self.state.portfolio['balances'].get('ETH', 0)

        # Add value of all tokens
        for token, amount in self.state.portfolio['balances'].items():
            if token == 'ETH':
                continue
            price_in_eth = self.state.prices.get(token, 0)
            total_eth += amount * price_in_eth

        # Add unrealized PnL from open positions
        for position in self.state.portfolio['positions']:
            if position['status'] == 'open':
                current_price = self.state.prices.get(position['token'], position['entry_price'])
                current_value = position['amount'] * current_price
                unrealized_pnl = current_value - (position['amount'] * position['entry_price']) - position['fees_paid'] - position['gas_paid']
                total_eth += unrealized_pnl

        # Update portfolio
        self.state.portfolio['current_eth'] = total_eth
        self.state.portfolio['unrealized_pnl'] = total_eth - self.state.portfolio['starting_eth'] - self.state.portfolio['realized_pnl']

        # Add to equity history
        self.state.portfolio['equity_history'].append({
            'timestamp': time.time(),
            'eth_value': total_eth
        })

        # Trim history
        if len(self.state.portfolio['equity_history']) > 1000:
            self.state.portfolio['equity_history'] = self.state.portfolio['equity_history'][-1000:]

    async def execute_trade(self, token: str, action: str, pattern_desc: str = 'Manual', amount_eth: Optional[float] = None, pattern: Optional[Dict] = None) -> Optional[Dict]:
        """Execute a trade (buy/sell)."""
        if not self.state.is_running:
            return None

        if amount_eth is None:
            amount_eth = self.calculate_trade_amount()

        current_price = self.state.prices.get(token)
        if current_price is None:
            return None

        if amount_eth <= 0:
            return None

        # Check max trades
        open_positions = len([p for p in self.state.portfolio['positions'] if p['status'] == 'open'])
        if open_positions >= self.config.MAX_TRADES:
            print(f"Max trades ({self.config.MAX_TRADES}) reached")
            return None

        # Check cooldown
        last_trade_time = self.state.last_trade_times.get(token)
        if last_trade_time and (time.time() - last_trade_time) < self.config.TRADE_COOLDOWN:
            return None

        # Check gas price
        if self.state.current_gas_price > self.config.MAX_GAS_PRICE:
            print(f"Gas price too high: {self.state.current_gas_price:.2f} gwei > {self.config.MAX_GAS_PRICE} gwei")
            return None

        # Check token balance for sells
        if action == 'sell':
            token_balance = self.state.portfolio['balances'].get(token, 0)
            if token_balance <= 0:
                return None

        # Simulate trade
        token_amount = amount_eth / current_price
        trade_result = self.simulate_trade(token, action, token_amount, current_price)
        if not trade_result['success']:
            failed_trade = self.create_trade(
                token, action, current_price, token_amount, amount_eth,
                pattern_desc, 'failed', trade_result['reason'], **trade_result
            )
            self.state.trades.append(failed_trade)
            self.state.portfolio['failed_trades'] += 1
            self.state.portfolio['total_trades'] += 1
            print(f"Trade failed: {trade_result['reason']}")
            return failed_trade

        # Prevent sequential trades on the same token
        if self.config.PREVENT_SEQUENTIAL_TRADES and self.state.last_traded_token == token:
            return None

        # Create trade
        token_amount = trade_result['token_amount']
        trade = self.create_trade(
            token, action, trade_result['execution_price'], token_amount,
            trade_result['amount_eth'], pattern_desc, 'open', **trade_result
        )

        # Update portfolio
        self.update_portfolio(trade, action, trade_result)

        # Update state
        self.state.portfolio['total_trades'] += 1
        self.state.last_traded_token = token
        self.state.last_trade_times[token] = time.time()

        if action == 'buy':
            self.state.open_buy_orders[token] = {
                'trade_id': trade['id'],
                'pattern': pattern,
                'entry_price': trade_result['execution_price'],
                'entry_time': time.time()
            }
            print(f"Bought {trade_result['token_amount']:.6f} {token} at {trade_result['execution_price']:.8f} ETH")

        if action == 'sell':
            if token in self.state.open_buy_orders:
                del self.state.open_buy_orders[token]
            pnl_text = f"+{trade['pnl']:.8f}" if trade['pnl'] >= 0 else f"{trade['pnl']:.8f}"
            print(f"Sold {trade_result['token_amount']:.6f} {token} at {trade_result['execution_price']:.8f} ETH (PnL: {pnl_text} ETH)")

        return trade

    async def check_patterns_for_token(self, token: str):
        """Check for buy/sell opportunities for a token."""
        if not self.state.is_running:
            return

        history = self.state.price_history.get(token, [])
        if len(history) < 2:
            return

        current_price = self.state.prices.get(token)
        if current_price is None:
            return

        # Check for open position to sell at profit
        open_position = next((p for p in self.state.portfolio['positions'] if p['token'] == token and p['status'] == 'open'), None)
        if open_position:
            current_value = open_position['amount'] * current_price
            cost_basis = (open_position['amount'] * open_position['entry_price']) + open_position['fees_paid'] + open_position['gas_paid']
            profit_eth = current_value - cost_basis
            profit_pct = (profit_eth / cost_basis) * 100 if cost_basis > 0 else 0

            # Sell only if profit target is met
            if profit_pct >= self.config.MIN_PROFIT_PERCENT and profit_eth > 0:
                sell_amount_eth = open_position['amount'] * current_price
                await self.execute_trade(token, 'sell', f"Profit target ({profit_pct:.2f}%) reached", sell_amount_eth)
                return

        # Check for buy opportunities
        token_patterns = [p for p in self.state.active_patterns.values() if p['token'] == token]
        buy_patterns = [p for p in token_patterns if p['type'] == 'buy']

        for pattern in buy_patterns:
            if self._check_pattern_match(token, pattern):
                if self.config.PREVENT_SEQUENTIAL_TRADES and self.state.last_traded_token == token:
                    continue
                if token in self.state.open_buy_orders:
                    continue

                trade_amount = self.calculate_trade_amount()
                await self.execute_trade(
                    token, 'buy',
                    f"Buy dip: {pattern['drop_pct']:.2f}% drop, {pattern['rise_pct']:.2f}% target",
                    trade_amount, pattern
                )

    def _check_pattern_match(self, token: str, pattern: Dict) -> bool:
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
                drop_pct = (current[0] - prev[0]) / prev[0]
                time_diff = current[1] - prev[1]

                if (abs(drop_pct) >= pattern['drop_pct'] / 100 and
                    pattern['drop_time'] - 2 <= time_diff <= pattern['drop_time'] + 2):
                    price_diff = abs(current_price - current[0]) / current[0]
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
                time.sleep(3)  # Check every 3 seconds

        threading.Thread(target=loop, daemon=True).start()

    def stop_pattern_detection(self):
        """Stop the pattern detection loop."""
        self.state.pattern_detection_active = False

# ========== PRICE SIMULATOR ==========
class PriceSimulator:
    """Simulates price movements for testing (replace with real data feeds for live use)."""
    def __init__(self, state: State):
        self.state = state
        self.tokens = ['ETH', 'WETH', 'WBTC', 'UNI', 'LINK', 'ARB', 'GMX', 'USDC', 'USDT']
        self.base_prices = {
            'ETH': 1.0, 'WETH': 1.0, 'WBTC': 20.0, 'UNI': 0.01, 'LINK': 0.005,
            'ARB': 0.001, 'GMX': 0.002, 'USDC': 0.0005, 'USDT': 0.0005
        }
        self.volatility = {
            'ETH': 0.02, 'WETH': 0.02, 'WBTC': 0.015, 'UNI': 0.05, 'LINK': 0.04,
            'ARB': 0.06, 'GMX': 0.07, 'USDC': 0.001, 'USDT': 0.001
        }
        self.last_prices = {}
        self.start_time = time.time()

    def generate_price(self, token: str) -> float:
        """Generate a realistic price for a token."""
        base = self.base_prices.get(token, 1.0)
        vol = self.volatility.get(token, 0.01)

        # Add trend (slow oscillation)
        time_factor = (time.time() - self.start_time) / 3600  # hours
        trend = math.sin(time_factor * 0.1) * 0.05

        # Add random walk
        if token in self.last_prices:
            last = self.last_prices[token]
            change = random.uniform(-vol, vol)
            new_price = last * (1 + change + trend * 0.01)
        else:
            new_price = base * (1 + random.uniform(-vol, vol))

        # Ensure price doesn't go negative
        new_price = max(new_price, base * 0.5)
        self.last_prices[token] = new_price
        return new_price

    def update_prices(self):
        """Update prices for all tokens."""
        for token in self.tokens:
            price = self.generate_price(token)
            self.state.prices[token] = price
            self._update_price_history(token, price)
            self.state.observed_tokens.add(token)
        self.state.last_price_update = time.time()

    def _update_price_history(self, token: str, price: float):
        """Update price history for a token."""
        if token not in self.state.price_history:
            self.state.price_history[token] = []

        self.state.price_history[token].append((price, time.time()))

        # Trim history by length
        if len(self.state.price_history[token]) > self.state.config.MAX_PRICE_HISTORY:
            self.state.price_history[token] = self.state.price_history[token][-self.state.config.MAX_PRICE_HISTORY:]

        # Trim history by time
        duration_sec = self.state.config.PRICE_HISTORY_DURATION * 3600
        cutoff = time.time() - duration_sec
        while (self.state.price_history[token] and
               self.state.price_history[token][0][1] < cutoff):
            self.state.price_history[token].pop(0)

# ========== STATE PERSISTENCE ==========
class StateManager:
    """Saves and loads state to/from JSON files."""
    def __init__(self, state: State):
        self.state = state
        self.data_dir = "data"
        os.makedirs(self.data_dir, exist_ok=True)

    def save_state(self):
        """Save all state to JSON files."""
        try:
            # Full state
            with open(os.path.join(self.data_dir, "full_state.json"), 'w') as f:
                json.dump(self.state.to_dict(), f, indent=2)

            # Open positions
            with open(os.path.join(self.data_dir, "open_positions.json"), 'w') as f:
                json.dump(
                    [p for p in self.state.portfolio['positions'] if p['status'] == 'open'],
                    f, indent=2
                )

            # Prices
            with open(os.path.join(self.data_dir, "prices.json"), 'w') as f:
                json.dump(self.state.prices, f, indent=2)

            # Price history
            history_for_save = {
                k: [{'price': p, 'timestamp': t} for p, t in v]
                for k, v in self.state.price_history.items()
            }
            with open(os.path.join(self.data_dir, "price_history.json"), 'w') as f:
                json.dump(history_for_save, f, indent=2)

            # Trades
            with open(os.path.join(self.data_dir, "trades.json"), 'w') as f:
                json.dump(self.state.trades, f, indent=2)

            # Portfolio
            portfolio_summary = {
                'current_eth': self.state.portfolio['current_eth'],
                'starting_eth': self.state.portfolio['starting_eth'],
                'realized_pnl': self.state.portfolio['realized_pnl'],
                'unrealized_pnl': self.state.portfolio['unrealized_pnl'],
                'total_trades': self.state.portfolio['total_trades'],
                'winning_trades': self.state.portfolio['winning_trades'],
                'losing_trades': self.state.portfolio['losing_trades'],
                'failed_trades': self.state.portfolio['failed_trades'],
                'gas_spent': self.state.portfolio['gas_spent'],
                'fees_paid': self.state.portfolio['fees_paid'],
                'total_fees': self.state.portfolio['total_fees'],
                'balances': self.state.portfolio['balances']
            }
            with open(os.path.join(self.data_dir, "portfolio.json"), 'w') as f:
                json.dump(portfolio_summary, f, indent=2)

            # Patterns
            with open(os.path.join(self.data_dir, "patterns.json"), 'w') as f:
                json.dump(list(self.state.active_patterns.values()), f, indent=2)

            # Metrics
            uptime = str(timedelta(seconds=int(time.time() - self.state.start_time))) if self.state.start_time else "00:00:00"
            last_update = datetime.fromtimestamp(self.state.last_price_update).strftime('%Y-%m-%d %H:%M:%S') if self.state.last_price_update else "Never"
            metrics = {
                'uptime': uptime,
                'last_price_update': last_update,
                'current_gas_price': f"{self.state.current_gas_price:.2f} gwei",
                'tracked_tokens': len(self.state.observed_tokens),
                'active_patterns': self.state.pattern_stats['total_patterns']
            }
            with open(os.path.join(self.data_dir, "metrics.json"), 'w') as f:
                json.dump(metrics, f, indent=2)

        except Exception as e:
            print(f"Error saving state: {e}")

    def load_state(self) -> bool:
        """Load state from JSON files."""
        try:
            full_state_path = os.path.join(self.data_dir, "full_state.json")
            if not os.path.exists(full_state_path):
                return False

            with open(full_state_path, 'r') as f:
                state_dict = json.load(f)

            # Reconstruct state
            self.state.config = Config(**state_dict['config'])
            self.state.is_running = state_dict['is_running']
            self.state.current_network = state_dict['current_network']
            self.state.prices = state_dict['prices']
            self.state.price_history = {
                k: [(p['price'], p['timestamp']) for p in v]
                for k, v in state_dict['price_history'].items()
            }
            self.state.trades = state_dict['trades']
            self.state.active_patterns = {p['key']: p for p in state_dict['active_patterns']}
            self.state.portfolio = state_dict['portfolio']
            self.state.last_traded_token = state_dict['last_traded_token']
            self.state.last_trade_times = state_dict['last_trade_times']
            self.state.start_time = state_dict['start_time']
            self.state.last_price_update = state_dict['last_price_update']
            self.state.current_gas_price = state_dict['current_gas_price']
            self.state.observed_tokens = set(state_dict['observed_tokens'])
            self.state.pattern_stats = state_dict['pattern_stats']
            self.state.open_buy_orders = state_dict['open_buy_orders']

            print("State loaded successfully!")
            return True

        except Exception as e:
            print(f"Error loading state: {e}")
            return False

# ========== MAIN BOT CLASS ==========
class Bot:
    def __init__(self, config: Optional[Config] = None):
        self.config = config or Config()
        self.state = State(self.config)
        self.trader = Trader(self.state)
        self.simulator = PriceSimulator(self.state)
        self.state_manager = StateManager(self.state)
        self.running = False

    def start(self):
        """Start the bot."""
        if self.running:
            print("Bot is already running")
            return

        print("Starting Uniswap Quick Swap Trader (Profit-Only Mode)...")
        self.running = True
        self.state.is_running = True
        self.state.start_time = time.time()
        self.state.last_traded_token = None
        self.state.open_buy_orders = {}

        # Start price updates
        def price_updater():
            while self.running:
                self.simulator.update_prices()
                time.sleep(5)  # Update every 5 seconds

        threading.Thread(target=price_updater, daemon=True).start()

        # Start pattern detection
        self.trader.start_pattern_detection()

        # Start state saving
        def state_saver():
            while self.running:
                self.state_manager.save_state()
                time.sleep(30)  # Save every 30 seconds

        threading.Thread(target=state_saver, daemon=True).start()

        # Start pattern checking
        async def pattern_checker():
            while self.running:
                for token in list(self.state.observed_tokens):
                    await self.trader.check_patterns_for_token(token)
                time.sleep(1)  # Check every second

        threading.Thread(
            target=lambda: asyncio.run(pattern_checker()), 
            daemon=True
        ).start()

        print("Bot started! Press Ctrl+C to stop.")
        print("Type 'status' to see current state, 'prices' to see prices, or 'stop' to stop.")

        # Start interactive loop
        self._interactive_loop()

    def stop(self):
        """Stop the bot."""
        if not self.running:
            print("Bot is not running")
            return

        print("Stopping bot...")
        self.running = False
        self.state.is_running = False
        self.state.manually_stopped = True
        self.trader.stop_pattern_detection()
        self.state_manager.save_state()
        print("Bot stopped!")

    def _interactive_loop(self):
        """Interactive console loop."""
        try:
            while self.running:
                cmd = input("> ").strip().lower()
                if cmd == 'stop':
                    self.stop()
                elif cmd == 'status':
                    self.print_status()
                elif cmd == 'prices':
                    self.print_prices()
                elif cmd == 'reset':
                    self.reset()
                elif cmd == 'help':
                    print("Commands: status, prices, stop, reset, help")
                elif cmd:
                    print("Unknown command. Type 'help' for options.")
        except KeyboardInterrupt:
            self.stop()

    def print_status(self):
        """Print current bot status."""
        status = self._get_status()
        print("\n=== Uniswap Quick Swap Trader v7.0.0 - Profit-Only Mode ===")
        print(f"Status: {'Running' if status['is_running'] else 'Stopped'}")
        print(f"Uptime: {status['uptime']}")
        print(f"\n--- Portfolio ---")
        print(f"Current Value: {status['current_eth']:.12f} ETH")
        print(f"Starting Budget: {self.state.portfolio['starting_eth']:.12f} ETH")
        print(f"Realized PnL: {status['realized_pnl']:.12f} ETH")
        print(f"Unrealized PnL: {status['unrealized_pnl']:.12f} ETH")
        print(f"Total Profit: {status['net_pnl']:.12f} ETH")
        print(f"Return: {status['portfolio_return']:.2f}%")
        print(f"\n--- Trading Stats ---")
        print(f"Total Trades: {status['total_trades']}")
        print(f"Winning Trades: {status['winning_trades']}")
        print(f"Losing Trades: {status['losing_trades']}")
        print(f"Failed Trades: {status['failed_trades']}")
        print(f"Win Rate: {status['win_rate']:.2f}%")
        print(f"\n--- Market ---")
        print(f"Tracked Tokens: {status['tracked_tokens']}")
        print(f"Active Patterns: {status['active_patterns']}")
        print(f"Open Positions: {status['open_positions']}")
        print(f"Last Price Update: {status['last_price_update']}")
        print(f"Gas Price: {status['current_gas_price']}")

        # Print open positions
        open_positions = [p for p in self.state.portfolio['positions'] if p['status'] == 'open']
        if open_positions:
            print("\n--- Open Positions ---")
            for pos in open_positions:
                current_price = self.state.prices.get(pos['token'], pos['entry_price'])
                current_value = pos['amount'] * current_price
                unrealized_pnl = current_value - (pos['amount'] * pos['entry_price']) - pos['fees_paid'] - pos['gas_paid']
                cost_basis = (pos['amount'] * pos['entry_price']) + pos['fees_paid'] + pos['gas_paid']
                return_pct = (unrealized_pnl / cost_basis) * 100 if cost_basis > 0 else 0
                age = int(time.time() - pos['entry_time'])
                print(
                    f"{pos['token']}: Bought at {pos['entry_price']:.8f}, "
                    f"Amount: {pos['amount']:.8f}, Value: {current_value:.8f} ETH, "
                    f"PnL: {unrealized_pnl:+.8f} ETH ({return_pct:+.2f}%), "
                    f"Age: {age}s, Pattern: {pos.get('pattern', 'Manual')}"
                )

        # Print recent trades
        if self.state.trades:
            print("\n--- Recent Trades ---")
            for trade in self.state.trades[-5:]:  # Last 5 trades
                pnl_str = f"+{trade['pnl']:.8f}" if trade['pnl'] >= 0 else f"{trade['pnl']:.8f}"
                print(
                    f"{trade['timestamp'][:19]} | {trade['token']} | {trade['type'].upper()} | "
                    f"Price: {trade['price']:.8f} | Amount: {trade['token_amount']:.8f} | "
                    f"PnL: {pnl_str} | Pattern: {trade.get('pattern', 'Manual')}"
                )

    def print_prices(self):
        """Print current prices for all tokens."""
        print("\n--- Current Prices ---")
        for token, price in sorted(self.state.prices.items()):
            history = self.state.price_history.get(token, [])
            change_pct = 0
            if len(history) >= 2:
                oldest = history[0]
                newest = history[-1]
                if newest[1] > oldest[1]:
                    change_pct = ((newest[0] - oldest[0]) / oldest[0]) * 100
            change_symbol = '↑' if change_pct > 0 else '↓' if change_pct < 0 else ' '
            print(f"{token}: {price:.8f} ETH ({change_symbol}{abs(change_pct):.2f}%)")

    def reset(self):
        """Reset the bot state."""
        if self.running:
            print("Cannot reset while bot is running. Stop the bot first.")
            return

        if input("Are you sure you want to reset? This will clear all data. (y/n): ").lower() == 'y':
            self.state = State(self.config)
            self.trader = Trader(self.state)
            self.simulator = PriceSimulator(self.state)
            os.makedirs("data", exist_ok=True)
            for f in os.listdir("data"):
                os.remove(os.path.join("data", f))
            print("Bot reset!")

    def _get_status(self) -> Dict:
        """Get current status as a dictionary."""
        net_pnl = self.state.portfolio['realized_pnl'] + self.state.portfolio['unrealized_pnl']
        successful_trades = self.state.portfolio['winning_trades'] + self.state.portfolio['losing_trades']
        win_rate = (self.state.portfolio['winning_trades'] / successful_trades * 100) if successful_trades > 0 else 0

        return {
            'is_running': self.state.is_running,
            'uptime': str(timedelta(seconds=int(time.time() - self.state.start_time))) if self.state.start_time else "00:00:00",
            'current_eth': self.state.portfolio['current_eth'],
            'realized_pnl': self.state.portfolio['realized_pnl'],
            'unrealized_pnl': self.state.portfolio['unrealized_pnl'],
            'net_pnl': net_pnl,
            'portfolio_return': (net_pnl / self.state.portfolio['starting_eth'] * 100) if self.state.portfolio['starting_eth'] > 0 else 0,
            'total_trades': self.state.portfolio['total_trades'],
            'winning_trades': self.state.portfolio['winning_trades'],
            'losing_trades': self.state.portfolio['losing_trades'],
            'failed_trades': self.state.portfolio['failed_trades'],
            'win_rate': win_rate,
            'open_positions': len([p for p in self.state.portfolio['positions'] if p['status'] == 'open']),
            'tracked_tokens': len(self.state.observed_tokens),
            'active_patterns': self.state.pattern_stats['total_patterns'],
            'last_price_update': datetime.fromtimestamp(self.state.last_price_update).strftime('%Y-%m-%d %H:%M:%S') if self.state.last_price_update else "Never",
            'current_gas_price': f"{self.state.current_gas_price:.2f} gwei"
        }

# ========== MAIN ==========
def main():
    print("Uniswap Quick Swap Trader v7.0.0 - Python Console Version")
    print("Profit-Only Mode: Buys dips and sells ONLY at profit\n")

    bot = Bot()
    bot.state_manager.load_state()  # Load previous state if available

    print("Commands:")
    print("  start   - Start the bot")
    print("  stop    - Stop the bot")
    print("  status  - Show current status")
    print("  prices  - Show current prices")
    print("  reset   - Reset all data")
    print("  help    - Show this help\n")

    while True:
        cmd = input("> ").strip().lower()
        if cmd == 'start':
            if not bot.running:
                bot.start()
            else:
                print("Bot is already running")
        elif cmd == 'stop':
            if bot.running:
                bot.stop()
            else:
                print("Bot is not running")
        elif cmd == 'status':
            bot.print_status()
        elif cmd == 'prices':
            bot.print_prices()
        elif cmd == 'reset':
            bot.reset()
        elif cmd == 'help':
            print("Commands: start, stop, status, prices, reset, help")
        elif cmd:
            print("Unknown command. Type 'help' for options.")

if __name__ == "__main__":
    main()