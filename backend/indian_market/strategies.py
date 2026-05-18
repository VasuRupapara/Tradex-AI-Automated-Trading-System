"""
Indian Market Strategies — Dual-Engine System

1. Equity Engine: Momentum + Mean Reversion on NSE stocks (wealth)
2. F&O Engine: Nifty/BankNifty option strategies (income)

All strategies produce SignalEvents consumed by the Risk Manager.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Optional

from backend.common.events import (
    EventType, MarketDataEvent, SignalDirection, SignalEvent,
)
from backend.common.event_queue import EventQueue
from backend.common.logger import setup_logging
from backend.indian_market.models import MarketSchedule

logger = setup_logging("indian-strategies")


# ============================================
# Base Strategy
# ============================================

class IndianStrategy:
    """Base class for Indian market strategies."""

    def __init__(self, name: str, symbols: List[str], params: Dict = None):
        self.name = name
        self.symbols = symbols
        self.parameters = params or {}
        self.enabled = True
        self._price_history: Dict[str, List[float]] = defaultdict(list)
        self._volume_history: Dict[str, List[float]] = defaultdict(list)

    def update_history(self, event: MarketDataEvent):
        self._price_history[event.symbol].append(event.price)
        self._volume_history[event.symbol].append(event.volume)
        if len(self._price_history[event.symbol]) > 500:
            self._price_history[event.symbol] = self._price_history[event.symbol][-500:]
            self._volume_history[event.symbol] = self._volume_history[event.symbol][-500:]

    def _sma(self, prices: List[float], period: int) -> Optional[float]:
        if len(prices) < period:
            return None
        return sum(prices[-period:]) / period

    def _rsi(self, prices: List[float], period: int = 14) -> Optional[float]:
        if len(prices) < period + 1:
            return None
        gains, losses = [], []
        for i in range(-period, 0):
            change = prices[i] - prices[i - 1]
            gains.append(max(0, change))
            losses.append(max(0, -change))
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def _ema(self, prices: List[float], period: int) -> Optional[float]:
        if len(prices) < period:
            return None
        mult = 2.0 / (period + 1)
        ema = sum(prices[:period]) / period
        for p in prices[period:]:
            ema = (p - ema) * mult + ema
        return ema

    def on_market_data(self, event: MarketDataEvent) -> Optional[SignalEvent]:
        raise NotImplementedError


# ============================================
# Equity Strategy: RSI + EMA Crossover
# ============================================

class EquityMomentumStrategy(IndianStrategy):
    """
    Equity Momentum Strategy for NSE stocks.

    BUY when:
      - RSI(14) crosses above 30 from oversold territory
      - EMA(9) > EMA(21) (short-term momentum up)
      - Volume is above 20-period average (confirmation)

    SELL when:
      - RSI(14) crosses above 70 (overbought)
      - EMA(9) < EMA(21) (momentum reversal)

    Designed for CNC (delivery) trades — holds for days/weeks.
    """

    def __init__(self, symbols: List[str], params: Dict = None):
        defaults = {"rsi_period": 14, "ema_short": 9, "ema_long": 21,
                    "rsi_oversold": 30, "rsi_overbought": 70, "vol_period": 20}
        if params:
            defaults.update(params)
        super().__init__("equity_momentum", symbols, defaults)

    def on_market_data(self, event: MarketDataEvent) -> Optional[SignalEvent]:
        if event.symbol not in self.symbols or not self.enabled:
            return None

        self.update_history(event)
        prices = self._price_history[event.symbol]
        volumes = self._volume_history[event.symbol]

        rsi = self._rsi(prices, self.parameters["rsi_period"])
        ema_short = self._ema(prices, self.parameters["ema_short"])
        ema_long = self._ema(prices, self.parameters["ema_long"])
        vol_avg = self._sma(volumes, self.parameters["vol_period"])

        if rsi is None or ema_short is None or ema_long is None:
            return None

        # Volume confirmation
        volume_ok = vol_avg is None or event.volume >= vol_avg * 0.8

        # BUY Signal: RSI recovering from oversold + bullish EMA crossover
        if rsi < self.parameters["rsi_oversold"] + 10 and ema_short > ema_long and volume_ok:
            strength = min(1.0, (self.parameters["rsi_oversold"] + 20 - rsi) / 30)
            return SignalEvent(
                symbol=event.symbol,
                direction=SignalDirection.LONG,
                strength=abs(strength),
                strategy_name=self.name,
                indicators={
                    "rsi": round(rsi, 2), "ema_short": round(ema_short, 2),
                    "ema_long": round(ema_long, 2), "price": event.price,
                    "product": "CNC",
                },
            )

        # SELL Signal: RSI overbought + bearish EMA crossover
        if rsi > self.parameters["rsi_overbought"] - 5 and ema_short < ema_long:
            strength = min(1.0, (rsi - self.parameters["rsi_overbought"] + 10) / 30)
            return SignalEvent(
                symbol=event.symbol,
                direction=SignalDirection.SHORT,
                strength=abs(strength),
                strategy_name=self.name,
                indicators={
                    "rsi": round(rsi, 2), "ema_short": round(ema_short, 2),
                    "ema_long": round(ema_long, 2), "price": event.price,
                    "product": "CNC",
                },
            )

        return None


# ============================================
# Equity Strategy: Mean Reversion (Bollinger)
# ============================================

class EquityMeanReversionStrategy(IndianStrategy):
    """
    Mean Reversion on NSE blue-chips using Bollinger Bands.

    BUY when price drops below lower Bollinger Band (oversold).
    SELL when price rises above upper Bollinger Band (overbought).
    """

    def __init__(self, symbols: List[str], params: Dict = None):
        defaults = {"window": 20, "num_std": 2.0}
        if params:
            defaults.update(params)
        super().__init__("equity_mean_reversion", symbols, defaults)

    def on_market_data(self, event: MarketDataEvent) -> Optional[SignalEvent]:
        if event.symbol not in self.symbols or not self.enabled:
            return None

        self.update_history(event)
        prices = self._price_history[event.symbol]
        window = self.parameters["window"]
        num_std = self.parameters["num_std"]

        if len(prices) < window:
            return None

        recent = prices[-window:]
        mean = sum(recent) / len(recent)
        variance = sum((p - mean) ** 2 for p in recent) / len(recent)
        std = variance ** 0.5
        if std == 0:
            return None

        upper = mean + num_std * std
        lower = mean - num_std * std
        z_score = (event.price - mean) / std

        if event.price < lower:
            return SignalEvent(
                symbol=event.symbol, direction=SignalDirection.LONG,
                strength=min(1.0, abs(z_score) / 3.0),
                strategy_name=self.name,
                indicators={"mean": round(mean, 2), "upper": round(upper, 2),
                            "lower": round(lower, 2), "z_score": round(z_score, 2),
                            "price": event.price, "product": "CNC"},
            )

        if event.price > upper:
            return SignalEvent(
                symbol=event.symbol, direction=SignalDirection.SHORT,
                strength=min(1.0, abs(z_score) / 3.0),
                strategy_name=self.name,
                indicators={"mean": round(mean, 2), "upper": round(upper, 2),
                            "lower": round(lower, 2), "z_score": round(z_score, 2),
                            "price": event.price, "product": "CNC"},
            )

        return None


# ============================================
# F&O Strategy: Nifty Intraday Breakout
# ============================================

class NiftyIntradayStrategy(IndianStrategy):
    """
    Intraday breakout strategy on NIFTY / BANKNIFTY.

    Trades the index directly (futures or ATM options).
    Uses 5-minute candle range breakout in the first 30 mins.
    All positions squared off by 3:15 PM.

    BUY when price breaks above the first 30-min high.
    SELL when price breaks below the first 30-min low.
    """

    def __init__(self, symbols: List[str], params: Dict = None):
        defaults = {"breakout_window": 30, "sl_percent": 0.5, "target_percent": 1.0}
        if params:
            defaults.update(params)
        super().__init__("nifty_intraday", symbols, defaults)
        self._range_high: Dict[str, float] = {}
        self._range_low: Dict[str, float] = {}
        self._range_set: Dict[str, bool] = {}
        self._tick_count: Dict[str, int] = defaultdict(int)

    def on_market_data(self, event: MarketDataEvent) -> Optional[SignalEvent]:
        if event.symbol not in self.symbols or not self.enabled:
            return None

        # Check market hours
        if MarketSchedule.is_intraday_cutoff():
            # Force exit signal near close
            if event.symbol in self._range_set and self._range_set[event.symbol]:
                return SignalEvent(
                    symbol=event.symbol, direction=SignalDirection.EXIT,
                    strength=1.0, strategy_name=self.name,
                    indicators={"price": event.price, "reason": "intraday_cutoff",
                                "product": "MIS"},
                )
            return None

        self.update_history(event)
        self._tick_count[event.symbol] += 1

        # Build opening range (first N ticks ≈ first 30 minutes)
        breakout_ticks = self.parameters["breakout_window"] * 6  # ~6 ticks/min
        if self._tick_count[event.symbol] <= breakout_ticks:
            if event.symbol not in self._range_high:
                self._range_high[event.symbol] = event.price
                self._range_low[event.symbol] = event.price
            else:
                self._range_high[event.symbol] = max(self._range_high[event.symbol], event.price)
                self._range_low[event.symbol] = min(self._range_low[event.symbol], event.price)

            if self._tick_count[event.symbol] == breakout_ticks:
                self._range_set[event.symbol] = True
                logger.info("opening_range_set",
                          symbol=event.symbol,
                          high=self._range_high[event.symbol],
                          low=self._range_low[event.symbol])
            return None

        if not self._range_set.get(event.symbol):
            return None

        # Breakout signals
        rng_high = self._range_high[event.symbol]
        rng_low = self._range_low[event.symbol]
        rng_size = rng_high - rng_low
        if rng_size == 0:
            return None

        if event.price > rng_high:
            strength = min(1.0, (event.price - rng_high) / rng_size)
            return SignalEvent(
                symbol=event.symbol, direction=SignalDirection.LONG,
                strength=strength, strategy_name=self.name,
                indicators={"range_high": rng_high, "range_low": rng_low,
                            "price": event.price, "product": "MIS"},
            )

        if event.price < rng_low:
            strength = min(1.0, (rng_low - event.price) / rng_size)
            return SignalEvent(
                symbol=event.symbol, direction=SignalDirection.SHORT,
                strength=strength, strategy_name=self.name,
                indicators={"range_high": rng_high, "range_low": rng_low,
                            "price": event.price, "product": "MIS"},
            )

        return None


# ============================================
# Strategy Engine (Indian)
# ============================================

class IndianStrategyEngine:
    """Runs all registered Indian strategies."""

    def __init__(self, event_queue: EventQueue):
        self.event_queue = event_queue
        self.strategies: List[IndianStrategy] = []
        self._signal_count = 0

    def register(self, strategy: IndianStrategy):
        self.strategies.append(strategy)
        logger.info("strategy_registered", name=strategy.name, symbols=strategy.symbols)

    def handle_market_data(self, event: MarketDataEvent):
        for strategy in self.strategies:
            if not strategy.enabled:
                continue
            try:
                signal = strategy.on_market_data(event)
                if signal:
                    self.event_queue.put(signal)
                    self._signal_count += 1
                    logger.info("signal_generated",
                              strategy=strategy.name, symbol=signal.symbol,
                              direction=signal.direction.value,
                              strength=round(signal.strength, 3))
            except Exception as e:
                logger.error("strategy_error", strategy=strategy.name, error=str(e))

    def start(self):
        self.event_queue.register_handler(EventType.MARKET_DATA, self.handle_market_data)
        logger.info("indian_strategy_engine_started", strategies=len(self.strategies))
