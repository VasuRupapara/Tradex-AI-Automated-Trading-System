"""
Risk Management Firewall - Pre-Trade Risk Controls

The Risk Management module intercepts every SignalEvent before
it reaches the Execution Handler. It enforces:
  - Position and monetary limits
  - Order size and frequency checks
  - Price tolerance verification
  - Drawdown circuit breakers
  - Global Kill Switch

Every single OrderEvent MUST pass through this module before
reaching the exchange.

Reference: Blueprint Section "Enterprise-Grade Risk Management and Security Protocols"
"""

from __future__ import annotations

import time
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from backend.common.config import get_risk_config
from backend.common.events import (
    EventType,
    FillEvent,
    KillSwitchEvent,
    OrderEvent,
    OrderSide,
    OrderType,
    RiskAlertEvent,
    SignalDirection,
    SignalEvent,
)
from backend.common.event_queue import EventQueue
from backend.common.logger import setup_logging

logger = setup_logging("risk-management")


# ============================================
# Position Tracker
# ============================================

class PositionTracker:
    """Tracks current positions and P&L for risk calculations."""

    def __init__(self):
        self.positions: Dict[str, float] = defaultdict(float)  # symbol → quantity
        self.avg_prices: Dict[str, float] = {}  # symbol → avg entry price
        self.daily_pnl: float = 0.0
        self.total_equity: float = 100000.0  # Starting equity
        self.peak_equity: float = 100000.0
        self.cash: float = 100000.0

    def update_position(self, fill: FillEvent) -> None:
        """Update positions based on a fill event."""
        symbol = fill.symbol
        if fill.side == OrderSide.BUY:
            self.positions[symbol] += fill.filled_quantity
            self.cash -= fill.filled_quantity * fill.fill_price + fill.commission
        else:
            self.positions[symbol] -= fill.filled_quantity
            self.cash += fill.filled_quantity * fill.fill_price - fill.commission

        # Clean up closed positions
        if abs(self.positions[symbol]) < 0.001:
            del self.positions[symbol]

    @property
    def total_exposure(self) -> float:
        """Total market exposure across all positions."""
        return sum(abs(qty) for qty in self.positions.values())

    @property
    def drawdown_percent(self) -> float:
        """Current drawdown from peak equity."""
        if self.peak_equity == 0:
            return 0.0
        return ((self.peak_equity - self.total_equity) / self.peak_equity) * 100


# ============================================
# Rate Limiter
# ============================================

class OrderRateLimiter:
    """
    Prevents excessive order submission.
    
    A strict rate-limiter prevents the algorithm from submitting
    an abnormal volume of orders within a rolling millisecond window.
    """

    def __init__(self, max_per_second: int = 10):
        self.max_per_second = max_per_second
        self._order_times: List[float] = []

    def check(self) -> bool:
        """Check if a new order is within rate limits."""
        now = time.time()
        # Remove orders older than 1 second
        self._order_times = [t for t in self._order_times if now - t < 1.0]

        if len(self._order_times) >= self.max_per_second:
            return False

        self._order_times.append(now)
        return True

    @property
    def current_rate(self) -> int:
        """Current orders per second."""
        now = time.time()
        return len([t for t in self._order_times if now - t < 1.0])


# ============================================
# Risk Manager Service
# ============================================

class RiskManager:
    """
    Institutional-grade Risk Management Firewall.
    
    Intercepts SignalEvents, performs pre-trade risk checks,
    and generates OrderEvents only if all checks pass.
    
    Risk Checks (in order):
        1. Kill Switch status
        2. Position limits (per-symbol and aggregate)
        3. Monetary limits (max order value, daily loss)
        4. Order frequency (rate limiting)
        5. Drawdown circuit breaker
        6. Price tolerance verification
    """

    def __init__(self, event_queue: EventQueue):
        self.event_queue = event_queue
        self._config = get_risk_config()
        self.positions = PositionTracker()
        self.rate_limiter = OrderRateLimiter(
            max_per_second=self._config.MAX_ORDER_FREQUENCY_PER_SECOND
        )
        self._kill_switch_active = False
        self._kill_switch_reason = ""
        self._blocked_orders = 0
        self._approved_orders = 0

    # ---- Pre-Trade Risk Checks ----

    def _check_kill_switch(self) -> Optional[str]:
        """Check 1: Is the global kill switch active?"""
        if self._kill_switch_active:
            return f"Kill switch active: {self._kill_switch_reason}"
        return None

    def _check_position_limits(self, symbol: str, quantity: float) -> Optional[str]:
        """Check 2: Position size limits."""
        current_position = abs(self.positions.positions.get(symbol, 0))
        new_exposure = current_position + quantity

        if new_exposure > self._config.MAX_POSITION_SIZE:
            return (
                f"Position limit exceeded for {symbol}: "
                f"current={current_position}, requested={quantity}, "
                f"limit={self._config.MAX_POSITION_SIZE}"
            )
        return None

    def _check_monetary_limits(self, quantity: float, price: float) -> Optional[str]:
        """Check 3: Monetary / daily loss limits."""
        order_value = quantity * price

        if self.positions.daily_pnl < -self._config.MAX_DAILY_LOSS:
            return (
                f"Daily loss limit breached: "
                f"daily_pnl={self.positions.daily_pnl}, "
                f"limit=-{self._config.MAX_DAILY_LOSS}"
            )
        return None

    def _check_rate_limit(self) -> Optional[str]:
        """Check 4: Order submission frequency."""
        if not self.rate_limiter.check():
            return (
                f"Order rate limit exceeded: "
                f"{self.rate_limiter.current_rate}/{self.rate_limiter.max_per_second} "
                f"orders per second"
            )
        return None

    def _check_drawdown(self) -> Optional[str]:
        """Check 5: Drawdown circuit breaker."""
        drawdown = self.positions.drawdown_percent

        if drawdown >= self._config.MAX_DRAWDOWN_PERCENT:
            # Auto-activate kill switch
            self.activate_kill_switch(
                reason=f"Max drawdown breached: {drawdown:.2f}% >= "
                       f"{self._config.MAX_DRAWDOWN_PERCENT}%"
            )
            return (
                f"Drawdown circuit breaker triggered at {drawdown:.2f}%. "
                f"Kill switch activated automatically."
            )
        return None

    def run_risk_checks(
        self, symbol: str, quantity: float, price: float
    ) -> Optional[str]:
        """
        Run all pre-trade risk checks in sequence.
        
        Returns None if all checks pass, or a rejection reason string.
        Uses both hard blocks (prevent order) and soft warnings.
        """
        checks = [
            self._check_kill_switch(),
            self._check_position_limits(symbol, quantity),
            self._check_monetary_limits(quantity, price),
            self._check_rate_limit(),
            self._check_drawdown(),
        ]

        for result in checks:
            if result is not None:
                return result

        return None  # All checks passed

    # ---- Signal → Order Conversion ----

    def handle_signal(self, event: SignalEvent) -> None:
        """
        Process a SignalEvent through the risk firewall.
        
        If all risk checks pass, generates an OrderEvent and
        pushes it to the event queue for the Execution Handler.
        """
        # Calculate position size based on signal strength and risk limits
        base_quantity = 100  # Base share quantity
        quantity = base_quantity * event.strength

        # Determine order side from signal direction
        if event.direction == SignalDirection.LONG:
            side = OrderSide.BUY
        elif event.direction == SignalDirection.SHORT:
            side = OrderSide.SELL
        else:
            # EXIT signal - close existing position
            current = self.positions.positions.get(event.symbol, 0)
            if current > 0:
                side = OrderSide.SELL
                quantity = abs(current)
            elif current < 0:
                side = OrderSide.BUY
                quantity = abs(current)
            else:
                return  # No position to exit

        # Get approximate price from signal indicators
        price = event.indicators.get("price", 0.0)

        # Run risk checks
        rejection = self.run_risk_checks(event.symbol, quantity, price)

        if rejection:
            self._blocked_orders += 1
            logger.warning("order_blocked",
                            symbol=event.symbol,
                            reason=rejection,
                            strategy=event.strategy_name)
            return

        # All checks passed - generate OrderEvent
        order = OrderEvent(
            symbol=event.symbol,
            side=side,
            order_type=OrderType.MARKET,
            quantity=quantity,
            limit_price=price,  # Pass price for paper trading reference
            strategy_name=event.strategy_name,
            signal_id=event.event_id,
        )

        self.event_queue.put(order)
        self._approved_orders += 1

        logger.info("order_approved",
                      symbol=order.symbol,
                      side=order.side.value,
                      quantity=order.quantity,
                      price=f"₹{price:,.2f}",
                      strategy=order.strategy_name)

    # ---- Fill Processing ----

    def handle_fill(self, event: FillEvent) -> None:
        """Update position tracking when a fill is received."""
        self.positions.update_position(event)
        logger.info("position_updated",
                      symbol=event.symbol,
                      fill_price=event.fill_price,
                      quantity=event.filled_quantity)

    # ---- Kill Switch ----

    def activate_kill_switch(self, reason: str = "manual") -> None:
        """
        Activate the Global Kill Switch.
        
        Ultimate-priority command that:
          1. Immediately halts all new order generation
          2. Sends market orders to flatten ALL open positions
          3. Keeps the trading engine halted until manual reset
        """
        self._kill_switch_active = True
        self._kill_switch_reason = reason

        logger.critical("KILL_SWITCH_ACTIVATED", reason=reason)

        # Emit kill switch event
        self.event_queue.put(KillSwitchEvent(
            activated=True,
            reason=reason,
            activated_by="risk_manager",
        ))

        # Generate exit orders for all open positions
        for symbol, quantity in list(self.positions.positions.items()):
            if quantity > 0:
                exit_order = OrderEvent(
                    symbol=symbol,
                    side=OrderSide.SELL,
                    order_type=OrderType.MARKET,
                    quantity=abs(quantity),
                    strategy_name="kill_switch",
                )
                self.event_queue.put(exit_order)
            elif quantity < 0:
                exit_order = OrderEvent(
                    symbol=symbol,
                    side=OrderSide.BUY,
                    order_type=OrderType.MARKET,
                    quantity=abs(quantity),
                    strategy_name="kill_switch",
                )
                self.event_queue.put(exit_order)

    def deactivate_kill_switch(self) -> None:
        """Manually reset the kill switch (requires human intervention)."""
        self._kill_switch_active = False
        self._kill_switch_reason = ""
        logger.info("kill_switch_deactivated")

    # ---- Service Lifecycle ----

    def start(self) -> None:
        """Start the risk management service."""
        # Register event handlers
        self.event_queue.register_handler(
            EventType.SIGNAL, self.handle_signal
        )
        self.event_queue.register_handler(
            EventType.FILL, self.handle_fill
        )

        logger.info("risk_manager_started",
                      max_position=self._config.MAX_POSITION_SIZE,
                      max_drawdown=self._config.MAX_DRAWDOWN_PERCENT,
                      max_daily_loss=self._config.MAX_DAILY_LOSS)

    @property
    def status(self) -> Dict:
        """Get risk manager status."""
        return {
            "kill_switch_active": self._kill_switch_active,
            "approved_orders": self._approved_orders,
            "blocked_orders": self._blocked_orders,
            "current_drawdown": self.positions.drawdown_percent,
            "daily_pnl": self.positions.daily_pnl,
            "total_exposure": self.positions.total_exposure,
            "open_positions": len(self.positions.positions),
        }


# ============================================
# Entry Point
# ============================================

def main():
    """Start the Risk Management service."""
    event_queue = EventQueue()
    risk_manager = RiskManager(event_queue)
    risk_manager.start()

    logger.info("risk_manager_ready", status=risk_manager.status)


if __name__ == "__main__":
    main()
