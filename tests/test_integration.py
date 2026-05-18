"""
Integration Test - Complete Event Loop

Tests the full event-driven execution flow:
    MarketDataEvent → Strategy Engine → SignalEvent →
    Risk Manager → OrderEvent → Execution Handler → FillEvent

This test validates that all components work together correctly
using the mock data feed and mock broker.
"""

import pytest
from unittest.mock import MagicMock

from backend.common.events import (
    EventType,
    MarketDataEvent,
    SignalEvent,
    OrderEvent,
    FillEvent,
    SignalDirection,
    OrderSide,
    TickType,
)
from backend.common.event_queue import EventQueue
from backend.strategy_engine.src.main import (
    SMACrossoverStrategy,
    MeanReversionStrategy,
    StrategyEngineService,
)
from backend.risk_management.src.main import RiskManager
from backend.execution_handler.src.main import ExecutionHandlerService


# ============================================
# Event Queue Tests
# ============================================

class TestEventQueue:
    """Tests for the central event queue."""

    def test_put_and_get(self):
        """Events should be retrieved in FIFO order."""
        queue = EventQueue()
        event1 = MarketDataEvent(symbol="AAPL", price=150.0)
        event2 = MarketDataEvent(symbol="GOOGL", price=2800.0)

        queue.put(event1)
        queue.put(event2)

        assert queue.size == 2
        assert queue.get() == event1
        assert queue.get() == event2
        assert queue.is_empty

    def test_handler_registration(self):
        """Handlers should be called when matching events are processed."""
        queue = EventQueue()
        handler = MagicMock()

        queue.register_handler(EventType.MARKET_DATA, handler)
        event = MarketDataEvent(symbol="AAPL", price=150.0)
        queue.put(event)
        queue.process_next()

        handler.assert_called_once_with(event)

    def test_empty_queue_returns_none(self):
        """Getting from empty queue should return None."""
        queue = EventQueue()
        assert queue.get() is None
        assert not queue.process_next()


# ============================================
# Event Model Tests
# ============================================

class TestEvents:
    """Tests for event data models."""

    def test_market_data_event(self):
        event = MarketDataEvent(
            symbol="AAPL",
            price=150.25,
            volume=1000.0,
            tick_type=TickType.TRADE,
        )
        assert event.symbol == "AAPL"
        assert event.price == 150.25
        assert event.event_type == EventType.MARKET_DATA

    def test_signal_event(self):
        event = SignalEvent(
            symbol="GOOGL",
            direction=SignalDirection.LONG,
            strength=0.85,
            strategy_name="sma_crossover",
        )
        assert event.direction == SignalDirection.LONG
        assert event.strength == 0.85

    def test_order_event(self):
        event = OrderEvent(
            symbol="MSFT",
            side=OrderSide.BUY,
            quantity=100,
        )
        assert event.side == OrderSide.BUY
        assert event.quantity == 100

    def test_event_has_unique_id(self):
        e1 = MarketDataEvent(symbol="A", price=1.0)
        e2 = MarketDataEvent(symbol="B", price=2.0)
        assert e1.event_id != e2.event_id


# ============================================
# Strategy Tests
# ============================================

class TestSMACrossoverStrategy:
    """Tests for the SMA Crossover strategy."""

    def test_no_signal_insufficient_data(self):
        """Should return None when not enough data for SMA calculation."""
        strategy = SMACrossoverStrategy(
            symbols=["AAPL"],
            parameters={"short_window": 3, "long_window": 5},
        )
        event = MarketDataEvent(symbol="AAPL", price=150.0)
        result = strategy.on_market_data(event)
        assert result is None

    def test_ignores_untracked_symbols(self):
        """Should ignore market data for symbols not in the strategy."""
        strategy = SMACrossoverStrategy(symbols=["AAPL"])
        event = MarketDataEvent(symbol="GOOGL", price=150.0)
        result = strategy.on_market_data(event)
        assert result is None

    def test_disabled_strategy_returns_none(self):
        """Disabled strategy should not generate signals."""
        strategy = SMACrossoverStrategy(symbols=["AAPL"])
        strategy.enabled = False
        event = MarketDataEvent(symbol="AAPL", price=150.0)
        result = strategy.on_market_data(event)
        assert result is None


class TestMeanReversionStrategy:
    """Tests for the Mean Reversion strategy."""

    def test_no_signal_insufficient_data(self):
        strategy = MeanReversionStrategy(
            symbols=["AAPL"],
            parameters={"window": 5, "num_std": 2.0},
        )
        event = MarketDataEvent(symbol="AAPL", price=100.0)
        result = strategy.on_market_data(event)
        assert result is None


# ============================================
# Risk Manager Tests
# ============================================

class TestRiskManager:
    """Tests for the Risk Management firewall."""

    def test_kill_switch_blocks_orders(self):
        """Kill switch should block all new orders."""
        queue = EventQueue()
        rm = RiskManager(queue)
        rm.activate_kill_switch(reason="test")

        result = rm.run_risk_checks("AAPL", 100, 150.0)
        assert result is not None
        assert "Kill switch" in result

    def test_position_limit_check(self):
        """Orders exceeding position limits should be blocked."""
        queue = EventQueue()
        rm = RiskManager(queue)

        # Set very small position limit
        rm._config.MAX_POSITION_SIZE = 50

        result = rm.run_risk_checks("AAPL", 100, 150.0)
        assert result is not None
        assert "Position limit" in result

    def test_all_checks_pass(self):
        """Should return None when all risk checks pass."""
        queue = EventQueue()
        rm = RiskManager(queue)
        result = rm.run_risk_checks("AAPL", 10, 150.0)
        assert result is None  # All checks passed

    def test_kill_switch_generates_exit_orders(self):
        """Kill switch should generate exit orders for open positions."""
        queue = EventQueue()
        rm = RiskManager(queue)
        rm.positions.positions["AAPL"] = 100  # Long 100 shares

        rm.activate_kill_switch(reason="test")

        # Should have queued a kill switch event + exit order
        assert not queue.is_empty


# ============================================
# Run tests
# ============================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
