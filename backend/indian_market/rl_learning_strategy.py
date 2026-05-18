"""
Reinforcement Learning (Q-Learning) Adaptive Strategy

This strategy implements an adaptive learning engine that "learns" from the market
on every tick/bar. It uses a Q-learning approach where the state is defined by 
technical indicators (RSI, EMA crossover, Bollinger Bands), and the actions are 
LONG, SHORT, or HOLD.

Rewards are given based on the subsequent price movement after taking a LONG or SHORT action.
Over time, the Q-table converges to the most profitable actions for each market state, 
making the system more efficient and self-optimizing.
"""

from __future__ import annotations

import random
import os
import json
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from backend.common.events import (
    EventType, MarketDataEvent, SignalDirection, SignalEvent,
)
from backend.common.logger import setup_logging
from backend.indian_market.strategies import IndianStrategy

logger = setup_logging("rl-learning-strategy")

# Actions
ACTION_HOLD = 0
ACTION_LONG = 1
ACTION_SHORT = 2


class ReinforcementLearningStrategy(IndianStrategy):
    """
    Q-Learning based adaptive strategy.
    
    States:
    - RSI State: Oversold (0), Neutral (1), Overbought (2)
    - Trend State: Bearish (0), Bullish (1)
    - BB State: Below Lower (0), Inside (1), Above Upper (2)
    Total States = 3 * 2 * 3 = 18 possible market states.
    
    The agent updates its Q-values using the Bellman equation.
    """

    def __init__(self, symbols: List[str], params: Dict = None):
        defaults = {
            "rsi_period": 14,
            "ema_short": 9,
            "ema_long": 21,
            "bb_window": 20,
            "bb_std": 2.0,
            "learning_rate": 0.1,    # Alpha
            "discount_factor": 0.9,  # Gamma
            "exploration_rate": 0.1, # Epsilon
            "min_signal_strength": 0.5,
            "save_file": "q_table_weights.json"
        }
        if params:
            defaults.update(params)
        super().__init__("rl_adaptive_learner", symbols, defaults)
        
        # Q-table: Dict[symbol, Dict[state_str, List[float]]]
        # List holds Q-values for [HOLD, LONG, SHORT]
        self._q_table: Dict[str, Dict[str, List[float]]] = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0, 0.0]))
        
        # Track last state and action to compute reward on next tick
        self._last_state: Dict[str, str] = {}
        self._last_action: Dict[str, int] = {}
        self._last_price: Dict[str, float] = {}

        self._load_weights()

    def _load_weights(self):
        """Loads learned Q-table weights from disk if they exist."""
        save_file = self.parameters["save_file"]
        if os.path.exists(save_file):
            try:
                with open(save_file, "r") as f:
                    data = json.load(f)
                    for sym, states in data.items():
                        for state, q_vals in states.items():
                            self._q_table[sym][state] = q_vals
                logger.info("rl_weights_loaded", file=save_file)
            except Exception as e:
                logger.error("rl_load_failed", error=str(e))

    def _save_weights(self):
        """Periodically save Q-table weights."""
        save_file = self.parameters["save_file"]
        try:
            with open(save_file, "w") as f:
                json.dump(self._q_table, f)
        except Exception as e:
            logger.error("rl_save_failed", error=str(e))

    def _get_state(self, prices: List[float], symbol: str) -> Optional[str]:
        """Discretize the current market state."""
        # Need enough data
        if len(prices) < max(self.parameters["rsi_period"], self.parameters["ema_long"], self.parameters["bb_window"]):
            return None

        # 1. RSI State
        rsi = self._rsi(prices, self.parameters["rsi_period"])
        if rsi is None: return None
        rsi_state = 0 if rsi < 30 else 2 if rsi > 70 else 1

        # 2. Trend State (EMA Crossover)
        ema_s = self._ema(prices, self.parameters["ema_short"])
        ema_l = self._ema(prices, self.parameters["ema_long"])
        if ema_s is None or ema_l is None: return None
        trend_state = 1 if ema_s > ema_l else 0

        # 3. Bollinger Band State
        window = self.parameters["bb_window"]
        recent = prices[-window:]
        mean = sum(recent) / len(recent)
        variance = sum((p - mean) ** 2 for p in recent) / len(recent)
        std = variance ** 0.5
        
        current_price = prices[-1]
        if current_price < mean - self.parameters["bb_std"] * std:
            bb_state = 0
        elif current_price > mean + self.parameters["bb_std"] * std:
            bb_state = 2
        else:
            bb_state = 1

        return f"{rsi_state}_{trend_state}_{bb_state}"

    def _calculate_reward(self, current_price: float, last_price: float, last_action: int) -> float:
        """Calculate reward based on price movement and previous action."""
        pct_change = (current_price - last_price) / last_price
        
        if last_action == ACTION_LONG:
            return pct_change * 100.0  # Reward is positive if price went up
        elif last_action == ACTION_SHORT:
            return -pct_change * 100.0 # Reward is positive if price went down
        else:
            # Small penalty for holding to encourage finding trades, or 0
            return 0.0

    def on_market_data(self, event: MarketDataEvent) -> Optional[SignalEvent]:
        """
        Processes new market data, updates Q-table based on previous action's reward,
        and selects the next optimal action based on the learned policy.
        """
        if event.symbol not in self.symbols or not self.enabled:
            return None

        self.update_history(event)
        prices = self._price_history[event.symbol]
        current_state = self._get_state(prices, event.symbol)

        if current_state is None:
            return None

        alpha = self.parameters["learning_rate"]
        gamma = self.parameters["discount_factor"]
        epsilon = self.parameters["exploration_rate"]

        # 1. Update Q-Table (Learn from previous step)
        if event.symbol in self._last_state:
            last_s = self._last_state[event.symbol]
            last_a = self._last_action[event.symbol]
            last_p = self._last_price[event.symbol]

            reward = self._calculate_reward(event.price, last_p, last_a)
            
            # Bellman Equation Update:
            # Q(s,a) = Q(s,a) + alpha * (reward + gamma * max(Q(s')) - Q(s,a))
            old_q = self._q_table[event.symbol][last_s][last_a]
            next_max_q = max(self._q_table[event.symbol][current_state])
            new_q = old_q + alpha * (reward + gamma * next_max_q - old_q)
            self._q_table[event.symbol][last_s][last_a] = new_q

        # 2. Choose Next Action (Epsilon-Greedy Policy)
        if random.random() < epsilon:
            # Explore: Random action
            action = random.choice([ACTION_HOLD, ACTION_LONG, ACTION_SHORT])
            is_exploration = True
        else:
            # Exploit: Choose action with max Q-value for current state
            q_values = self._q_table[event.symbol][current_state]
            max_q = max(q_values)
            # Find all actions with max Q (to handle ties randomly)
            best_actions = [a for a, q in enumerate(q_values) if q == max_q]
            action = random.choice(best_actions)
            is_exploration = False

        # 3. Save state for next tick
        self._last_state[event.symbol] = current_state
        self._last_action[event.symbol] = action
        self._last_price[event.symbol] = event.price
        
        # Periodically save weights (e.g. 1% chance per tick to avoid I/O blocking)
        if random.random() < 0.01:
            self._save_weights()

        # 4. Generate Trade Signal if confident
        if action == ACTION_LONG:
            confidence = max(0.1, min(1.0, self._q_table[event.symbol][current_state][ACTION_LONG]))
            if confidence >= self.parameters["min_signal_strength"] or is_exploration:
                return SignalEvent(
                    symbol=event.symbol,
                    direction=SignalDirection.LONG,
                    strength=confidence,
                    strategy_name=self.name,
                    indicators={
                        "price": event.price,
                        "rl_state": current_state,
                        "q_value": round(self._q_table[event.symbol][current_state][ACTION_LONG], 4),
                        "exploration": is_exploration,
                        "product": "CNC"
                    }
                )
        elif action == ACTION_SHORT:
            confidence = max(0.1, min(1.0, self._q_table[event.symbol][current_state][ACTION_SHORT]))
            if confidence >= self.parameters["min_signal_strength"] or is_exploration:
                return SignalEvent(
                    symbol=event.symbol,
                    direction=SignalDirection.SHORT,
                    strength=confidence,
                    strategy_name=self.name,
                    indicators={
                        "price": event.price,
                        "rl_state": current_state,
                        "q_value": round(self._q_table[event.symbol][current_state][ACTION_SHORT], 4),
                        "exploration": is_exploration,
                        "product": "CNC"
                    }
                )

        return None
