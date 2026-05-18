"""
Smart Money Concepts Strategy — Python Port of LuxAlgo Pine Script

Translates the TradingView "Smart Money Concepts" indicator logic into
a live trading strategy that produces SignalEvents.

Concepts implemented:
  1. Market Structure (BOS / CHoCH) — trend direction detection
  2. Order Blocks — institutional footprint zones
  3. Fair Value Gaps (FVG) — price imbalance pockets
  4. Equal Highs / Lows — liquidity grab zones
  5. Premium / Discount Zones — value area classification

Each concept can independently fire buy/sell signals.
All signals are consumed by the Risk Manager before execution.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from backend.common.events import (
    EventType, MarketDataEvent, SignalDirection, SignalEvent,
)
from backend.common.event_queue import EventQueue
from backend.common.logger import setup_logging
from backend.indian_market.strategies import IndianStrategy

logger = setup_logging("smart-money")


# ============================================
# Data Structures (mirrors Pine Script UDTs)
# ============================================

@dataclass
class PivotPoint:
    """Tracks a swing high or low price level."""
    current_level: float = 0.0
    last_level: float = 0.0
    crossed: bool = False
    bar_index: int = 0
    bar_time: float = 0.0


@dataclass
class OrderBlock:
    """A zone where large institutional orders were placed."""
    high: float = 0.0
    low: float = 0.0
    bar_index: int = 0
    bias: int = 0          # +1 = bullish, -1 = bearish
    active: bool = True


@dataclass
class FairValueGap:
    """A price gap left by rapid movement (imbalance)."""
    top: float = 0.0
    bottom: float = 0.0
    bias: int = 0           # +1 = bullish, -1 = bearish
    bar_index: int = 0
    active: bool = True


@dataclass
class TrendState:
    """Tracks current trend direction."""
    bias: int = 0           # +1 = bullish, -1 = bearish


BULLISH = 1
BEARISH = -1


# ============================================
# Smart Money Concepts Strategy
# ============================================

class SmartMoneyStrategy(IndianStrategy):
    """
    Smart Money Concepts strategy ported from Pine Script.

    Generates BUY signals when:
      - Bullish CHoCH detected (trend reversal to upside)
      - Price enters a bullish Order Block zone
      - Bullish Fair Value Gap gets filled
      - Price is in the Discount zone

    Generates SELL signals when:
      - Bearish CHoCH detected (trend reversal to downside)
      - Price enters a bearish Order Block zone
      - Bearish Fair Value Gap gets filled
      - Price is in the Premium zone

    Each condition adds to signal strength (0-1 scale).
    """

    def __init__(self, symbols: List[str], params: Dict = None):
        defaults = {
            "swing_length": 50,         # bars for swing structure detection
            "internal_length": 5,       # bars for internal structure
            "ob_max_count": 10,         # max order blocks to track
            "fvg_enabled": True,        # detect fair value gaps
            "eq_hl_threshold": 0.1,     # equal highs/lows sensitivity (ATR multiplier)
            "eq_hl_length": 3,          # bars to confirm equal H/L
            "min_signal_strength": 0.3, # minimum strength to emit signal
        }
        if params:
            defaults.update(params)
        super().__init__("smart_money_concepts", symbols, defaults)

        # Per-symbol tracking
        self._bars: Dict[str, List[Dict]] = defaultdict(list)

        # Structure pivots
        self._swing_high: Dict[str, PivotPoint] = {}
        self._swing_low: Dict[str, PivotPoint] = {}
        self._internal_high: Dict[str, PivotPoint] = {}
        self._internal_low: Dict[str, PivotPoint] = {}

        # Trend state
        self._swing_trend: Dict[str, TrendState] = {}
        self._internal_trend: Dict[str, TrendState] = {}

        # Order blocks
        self._bullish_obs: Dict[str, List[OrderBlock]] = defaultdict(list)
        self._bearish_obs: Dict[str, List[OrderBlock]] = defaultdict(list)

        # Fair value gaps
        self._fvgs: Dict[str, List[FairValueGap]] = defaultdict(list)

        # Trailing extremes for premium/discount zones
        self._trailing_high: Dict[str, float] = {}
        self._trailing_low: Dict[str, float] = {}

        # ATR for volatility measurement
        self._true_ranges: Dict[str, List[float]] = defaultdict(list)

    # ---- Initialization helpers ----

    def _ensure_init(self, symbol: str):
        """Initialize tracking structures for a new symbol."""
        if symbol not in self._swing_high:
            self._swing_high[symbol] = PivotPoint()
            self._swing_low[symbol] = PivotPoint()
            self._internal_high[symbol] = PivotPoint()
            self._internal_low[symbol] = PivotPoint()
            self._swing_trend[symbol] = TrendState()
            self._internal_trend[symbol] = TrendState()
            self._trailing_high[symbol] = 0.0
            self._trailing_low[symbol] = float('inf')

    # ---- Core Calculations ----

    def _atr(self, symbol: str, period: int = 14) -> Optional[float]:
        """Average True Range — measures volatility."""
        trs = self._true_ranges[symbol]
        if len(trs) < period:
            return None
        return sum(trs[-period:]) / period

    def _detect_leg(self, bars: List[Dict], size: int) -> Optional[int]:
        """
        Detect swing leg direction (mirrors Pine `leg()` function).
        Returns 1 for bullish leg, 0 for bearish leg, or None.
        """
        if len(bars) <= size:
            return None

        ref_bar = bars[-(size + 1)]
        recent_bars = bars[-size:]

        highest = max(b["high"] for b in recent_bars)
        lowest = min(b["low"] for b in recent_bars)

        if ref_bar["high"] > highest:
            return 0  # bearish leg
        elif ref_bar["low"] < lowest:
            return 1  # bullish leg
        return None

    def _detect_pivot(self, bars: List[Dict], size: int, symbol: str,
                      high_pivot: PivotPoint, low_pivot: PivotPoint,
                      is_internal: bool = False) -> Optional[str]:
        """
        Detect new swing pivots. Returns 'high' or 'low' if a new pivot formed.
        Mirrors Pine `getCurrentStructure()`.
        """
        if len(bars) <= size + 1:
            return None

        current_leg = self._detect_leg(bars, size)
        if current_leg is None:
            return None

        # Check if leg direction changed
        prev_leg = self._detect_leg(bars[:-1], size)
        if prev_leg is None or current_leg == prev_leg:
            return None

        ref_bar = bars[-(size + 1)]

        if current_leg == 1:  # new bullish leg → low pivot formed
            low_pivot.last_level = low_pivot.current_level
            low_pivot.current_level = ref_bar["low"]
            low_pivot.crossed = False
            low_pivot.bar_index = len(bars) - size - 1
            return "low"
        else:  # new bearish leg → high pivot formed
            high_pivot.last_level = high_pivot.current_level
            high_pivot.current_level = ref_bar["high"]
            high_pivot.crossed = False
            high_pivot.bar_index = len(bars) - size - 1
            return "high"

    def _detect_structure_break(self, bars: List[Dict], symbol: str,
                                 high_pivot: PivotPoint, low_pivot: PivotPoint,
                                 trend: TrendState,
                                 is_internal: bool = False) -> Optional[Dict]:
        """
        Detect BOS (Break of Structure) and CHoCH (Change of Character).
        Mirrors Pine `displayStructure()`.

        Returns dict with 'type' ('BOS'/'CHoCH'), 'direction' ('bullish'/'bearish'),
        and 'level' (price) if a structure break is detected.
        """
        if not bars:
            return None

        current_close = bars[-1]["close"]

        # Check bullish break (close crosses above swing high)
        if (high_pivot.current_level > 0 and
                current_close > high_pivot.current_level and
                not high_pivot.crossed):
            tag = "CHoCH" if trend.bias == BEARISH else "BOS"
            high_pivot.crossed = True
            trend.bias = BULLISH

            # Store bullish order block (the candle that caused the break)
            self._store_order_block(bars, symbol, high_pivot, BULLISH, is_internal)

            return {"type": tag, "direction": "bullish", "level": high_pivot.current_level}

        # Check bearish break (close crosses below swing low)
        if (low_pivot.current_level > 0 and
                current_close < low_pivot.current_level and
                not low_pivot.crossed):
            tag = "CHoCH" if trend.bias == BULLISH else "BOS"
            low_pivot.crossed = True
            trend.bias = BEARISH

            # Store bearish order block
            self._store_order_block(bars, symbol, low_pivot, BEARISH, is_internal)

            return {"type": tag, "direction": "bearish", "level": low_pivot.current_level}

        return None

    def _store_order_block(self, bars: List[Dict], symbol: str,
                           pivot: PivotPoint, bias: int, is_internal: bool):
        """
        Find and store the order block candle between the pivot and current bar.
        Mirrors Pine `storeOrdeBlock()`.
        """
        max_obs = self.parameters["ob_max_count"]
        start = max(0, pivot.bar_index)
        end = len(bars) - 1

        if start >= end or start >= len(bars):
            return

        segment = bars[start:end]
        if not segment:
            return

        if bias == BEARISH:
            # Find the bar with the highest parsed high
            ob_bar = max(segment, key=lambda b: b["high"])
        else:
            # Find the bar with the lowest parsed low
            ob_bar = min(segment, key=lambda b: b["low"])

        ob = OrderBlock(
            high=ob_bar["high"],
            low=ob_bar["low"],
            bar_index=start + segment.index(ob_bar),
            bias=bias,
            active=True,
        )

        obs_list = self._bullish_obs[symbol] if bias == BULLISH else self._bearish_obs[symbol]
        obs_list.insert(0, ob)

        # Keep only the most recent N order blocks
        while len(obs_list) > max_obs:
            obs_list.pop()

    def _check_order_block_mitigation(self, symbol: str, current_bar: Dict) -> List[Dict]:
        """
        Check if price has broken through any active order blocks.
        Mirrors Pine `deleteOrderBlocks()`.
        Returns list of mitigated OBs with their bias.
        """
        mitigated = []

        # Check bearish OBs: mitigated when price goes above their high
        for ob in self._bearish_obs[symbol]:
            if ob.active and current_bar["high"] > ob.high:
                ob.active = False
                mitigated.append({"bias": BEARISH, "ob": ob})

        # Check bullish OBs: mitigated when price goes below their low
        for ob in self._bullish_obs[symbol]:
            if ob.active and current_bar["low"] < ob.low:
                ob.active = False
                mitigated.append({"bias": BULLISH, "ob": ob})

        # Clean up inactive OBs
        self._bearish_obs[symbol] = [ob for ob in self._bearish_obs[symbol] if ob.active]
        self._bullish_obs[symbol] = [ob for ob in self._bullish_obs[symbol] if ob.active]

        return mitigated

    def _detect_fair_value_gap(self, bars: List[Dict], symbol: str) -> Optional[Dict]:
        """
        Detect fair value gaps (price imbalances).
        Mirrors Pine `drawFairValueGaps()`.

        A bullish FVG: current low > 2-bars-ago high (gap up)
        A bearish FVG: current high < 2-bars-ago low (gap down)
        """
        if not self.parameters["fvg_enabled"] or len(bars) < 3:
            return None

        current = bars[-1]
        last = bars[-2]
        two_ago = bars[-3]

        # Bullish FVG: gap up
        if current["low"] > two_ago["high"] and last["close"] > two_ago["high"]:
            fvg = FairValueGap(
                top=current["low"],
                bottom=two_ago["high"],
                bias=BULLISH,
                bar_index=len(bars) - 1,
                active=True,
            )
            self._fvgs[symbol].insert(0, fvg)
            return {"bias": BULLISH, "top": fvg.top, "bottom": fvg.bottom}

        # Bearish FVG: gap down
        if current["high"] < two_ago["low"] and last["close"] < two_ago["low"]:
            fvg = FairValueGap(
                top=two_ago["low"],
                bottom=current["high"],
                bias=BEARISH,
                bar_index=len(bars) - 1,
                active=True,
            )
            self._fvgs[symbol].insert(0, fvg)
            return {"bias": BEARISH, "top": fvg.top, "bottom": fvg.bottom}

        return None

    def _check_fvg_fill(self, symbol: str, current_bar: Dict) -> List[Dict]:
        """Check if price has filled any active FVGs."""
        filled = []
        for fvg in self._fvgs[symbol]:
            if not fvg.active:
                continue
            if fvg.bias == BULLISH and current_bar["low"] < fvg.bottom:
                fvg.active = False
                filled.append({"bias": BULLISH, "fvg": fvg})
            elif fvg.bias == BEARISH and current_bar["high"] > fvg.top:
                fvg.active = False
                filled.append({"bias": BEARISH, "fvg": fvg})

        self._fvgs[symbol] = [f for f in self._fvgs[symbol] if f.active]
        return filled

    def _detect_equal_highs_lows(self, bars: List[Dict], symbol: str) -> Optional[Dict]:
        """
        Detect equal highs (EQH) and equal lows (EQL).
        These are liquidity zones where price touches the same level multiple times.
        """
        eq_len = self.parameters["eq_hl_length"]
        threshold = self.parameters["eq_hl_threshold"]
        atr = self._atr(symbol)

        if atr is None or len(bars) < eq_len * 2 + 1:
            return None

        # Check recent swing highs
        recent_highs = [b["high"] for b in bars[-(eq_len * 2):]]
        recent_lows = [b["low"] for b in bars[-(eq_len * 2):]]

        max_high = max(recent_highs)
        min_low = min(recent_lows)

        # Count how many bars touch the same high level (within threshold)
        high_touches = sum(1 for h in recent_highs if abs(h - max_high) < threshold * atr)
        low_touches = sum(1 for l in recent_lows if abs(l - min_low) < threshold * atr)

        if high_touches >= eq_len:
            return {"type": "EQH", "level": max_high}
        if low_touches >= eq_len:
            return {"type": "EQL", "level": min_low}

        return None

    def _get_premium_discount_zone(self, symbol: str, price: float) -> Optional[str]:
        """
        Determine if current price is in Premium, Discount, or Equilibrium zone.
        Mirrors Pine `drawPremiumDiscountZones()`.
        """
        high = self._trailing_high.get(symbol, 0)
        low = self._trailing_low.get(symbol, float('inf'))

        if high <= low or high == 0:
            return None

        range_size = high - low
        premium_threshold = high - 0.05 * range_size    # top 5%
        discount_threshold = low + 0.05 * range_size    # bottom 5%
        eq_upper = high - 0.475 * range_size            # middle band
        eq_lower = low + 0.475 * range_size

        if price >= premium_threshold:
            return "premium"
        elif price <= discount_threshold:
            return "discount"
        elif eq_lower <= price <= eq_upper:
            return "equilibrium"
        return None

    # ---- Price in OB zone check ----

    def _price_in_active_ob(self, symbol: str, price: float) -> Optional[int]:
        """Check if price is sitting inside an active order block zone."""
        for ob in self._bullish_obs[symbol]:
            if ob.active and ob.low <= price <= ob.high:
                return BULLISH
        for ob in self._bearish_obs[symbol]:
            if ob.active and ob.low <= price <= ob.high:
                return BEARISH
        return None

    # ============================================
    # Main Entry Point
    # ============================================

    def on_market_data(self, event: MarketDataEvent) -> Optional[SignalEvent]:
        """
        Process each incoming tick/bar and check all Smart Money conditions.
        Combines multiple confluence signals into a single strength score.
        """
        if event.symbol not in self.symbols or not self.enabled:
            return None

        symbol = event.symbol
        self._ensure_init(symbol)
        self.update_history(event)

        # Build bar from event
        bar = {
            "open": event.open if event.open else event.price,
            "high": event.high if event.high else event.price,
            "low": event.low if event.low else event.price,
            "close": event.close if event.close else event.price,
            "volume": event.volume,
        }
        self._bars[symbol].append(bar)

        # Keep last 500 bars
        if len(self._bars[symbol]) > 500:
            self._bars[symbol] = self._bars[symbol][-500:]

        bars = self._bars[symbol]

        # Update True Range for ATR
        if len(bars) >= 2:
            prev = bars[-2]
            tr = max(
                bar["high"] - bar["low"],
                abs(bar["high"] - prev["close"]),
                abs(bar["low"] - prev["close"]),
            )
            self._true_ranges[symbol].append(tr)
            if len(self._true_ranges[symbol]) > 200:
                self._true_ranges[symbol] = self._true_ranges[symbol][-200:]

        # Update trailing extremes
        self._trailing_high[symbol] = max(self._trailing_high[symbol], bar["high"])
        self._trailing_low[symbol] = min(self._trailing_low[symbol], bar["low"])

        # Need enough bars for analysis
        if len(bars) < self.parameters["swing_length"] + 2:
            return None

        # ---- Run all detections ----
        signals = []  # list of (direction, strength, reason)

        # 1. Swing structure detection
        swing_len = self.parameters["swing_length"]
        internal_len = self.parameters["internal_length"]

        self._detect_pivot(bars, swing_len, symbol,
                           self._swing_high[symbol], self._swing_low[symbol])
        self._detect_pivot(bars, internal_len, symbol,
                           self._internal_high[symbol], self._internal_low[symbol],
                           is_internal=True)

        # 2. Structure breaks (BOS / CHoCH)
        swing_break = self._detect_structure_break(
            bars, symbol,
            self._swing_high[symbol], self._swing_low[symbol],
            self._swing_trend[symbol],
        )
        internal_break = self._detect_structure_break(
            bars, symbol,
            self._internal_high[symbol], self._internal_low[symbol],
            self._internal_trend[symbol],
            is_internal=True,
        )

        if swing_break:
            if swing_break["type"] == "CHoCH":
                # CHoCH = trend reversal → strong signal
                direction = SignalDirection.LONG if swing_break["direction"] == "bullish" else SignalDirection.SHORT
                signals.append((direction, 0.4, f"swing_{swing_break['type']}_{swing_break['direction']}"))
            else:
                # BOS = trend continuation → moderate signal
                direction = SignalDirection.LONG if swing_break["direction"] == "bullish" else SignalDirection.SHORT
                signals.append((direction, 0.25, f"swing_{swing_break['type']}_{swing_break['direction']}"))

        if internal_break:
            if internal_break["type"] == "CHoCH":
                direction = SignalDirection.LONG if internal_break["direction"] == "bullish" else SignalDirection.SHORT
                signals.append((direction, 0.2, f"internal_{internal_break['type']}_{internal_break['direction']}"))

        # 3. Order block checks
        ob_zone = self._price_in_active_ob(symbol, event.price)
        if ob_zone == BULLISH:
            signals.append((SignalDirection.LONG, 0.2, "price_in_bullish_OB"))
        elif ob_zone == BEARISH:
            signals.append((SignalDirection.SHORT, 0.2, "price_in_bearish_OB"))

        # Order block mitigation
        mitigated = self._check_order_block_mitigation(symbol, bar)
        for m in mitigated:
            if m["bias"] == BEARISH:
                signals.append((SignalDirection.LONG, 0.15, "bearish_OB_mitigated"))
            else:
                signals.append((SignalDirection.SHORT, 0.15, "bullish_OB_mitigated"))

        # 4. Fair value gaps
        new_fvg = self._detect_fair_value_gap(bars, symbol)
        fvg_fills = self._check_fvg_fill(symbol, bar)
        for fill in fvg_fills:
            if fill["bias"] == BULLISH:
                signals.append((SignalDirection.LONG, 0.15, "bullish_FVG_filled"))
            else:
                signals.append((SignalDirection.SHORT, 0.15, "bearish_FVG_filled"))

        # 5. Premium / Discount zones
        zone = self._get_premium_discount_zone(symbol, event.price)
        if zone == "discount":
            signals.append((SignalDirection.LONG, 0.1, "discount_zone"))
        elif zone == "premium":
            signals.append((SignalDirection.SHORT, 0.1, "premium_zone"))

        # 6. Equal Highs / Lows
        eq_hl = self._detect_equal_highs_lows(bars, symbol)
        if eq_hl:
            if eq_hl["type"] == "EQL":
                signals.append((SignalDirection.LONG, 0.1, "equal_lows_liquidity"))
            elif eq_hl["type"] == "EQH":
                signals.append((SignalDirection.SHORT, 0.1, "equal_highs_liquidity"))

        # ---- Combine confluence signals ----
        if not signals:
            return None

        # Separate long and short signals
        long_strength = sum(s[1] for s in signals if s[0] == SignalDirection.LONG)
        short_strength = sum(s[1] for s in signals if s[0] == SignalDirection.SHORT)
        long_reasons = [s[2] for s in signals if s[0] == SignalDirection.LONG]
        short_reasons = [s[2] for s in signals if s[0] == SignalDirection.SHORT]

        min_strength = self.parameters["min_signal_strength"]

        # Whichever side has more confluence wins
        if long_strength > short_strength and long_strength >= min_strength:
            final_strength = min(1.0, long_strength)
            atr = self._atr(symbol) or 0
            return SignalEvent(
                symbol=symbol,
                direction=SignalDirection.LONG,
                strength=final_strength,
                strategy_name=self.name,
                indicators={
                    "price": event.price,
                    "confluence_reasons": ", ".join(long_reasons),
                    "confluence_count": len(long_reasons),
                    "swing_trend": self._swing_trend[symbol].bias,
                    "internal_trend": self._internal_trend[symbol].bias,
                    "zone": zone or "neutral",
                    "active_bull_OBs": len(self._bullish_obs[symbol]),
                    "active_bear_OBs": len(self._bearish_obs[symbol]),
                    "active_FVGs": len(self._fvgs[symbol]),
                    "atr": round(atr, 2),
                    "product": "CNC",
                },
            )

        elif short_strength > long_strength and short_strength >= min_strength:
            final_strength = min(1.0, short_strength)
            atr = self._atr(symbol) or 0
            return SignalEvent(
                symbol=symbol,
                direction=SignalDirection.SHORT,
                strength=final_strength,
                strategy_name=self.name,
                indicators={
                    "price": event.price,
                    "confluence_reasons": ", ".join(short_reasons),
                    "confluence_count": len(short_reasons),
                    "swing_trend": self._swing_trend[symbol].bias,
                    "internal_trend": self._internal_trend[symbol].bias,
                    "zone": zone or "neutral",
                    "active_bull_OBs": len(self._bullish_obs[symbol]),
                    "active_bear_OBs": len(self._bearish_obs[symbol]),
                    "active_FVGs": len(self._fvgs[symbol]),
                    "atr": round(atr, 2),
                    "product": "CNC",
                },
            )

        return None
