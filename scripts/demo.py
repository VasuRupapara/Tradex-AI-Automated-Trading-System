"""
Full System Demo - Automated Trading System

Runs the complete event-driven execution loop with mock data
to demonstrate the end-to-end flow:

    Market Data → Strategy Engine → Risk Manager → Execution → Portfolio

No real money or broker connections required.
"""

import asyncio
import time
from datetime import datetime

from backend.common.events import EventType, MarketDataEvent, TickType
from backend.common.event_queue import EventQueue
from backend.strategy_engine.src.main import (
    SMACrossoverStrategy,
    MeanReversionStrategy,
    StrategyEngineService,
)
from backend.risk_management.src.main import RiskManager
from backend.execution_handler.src.main import ExecutionHandlerService
from backend.common.logger import setup_logging

logger = setup_logging("demo", "INFO")


def run_demo():
    """Run a demonstration of the complete trading system."""
    print("=" * 60)
    print("  AUTOMATED TRADING SYSTEM - FULL DEMO")
    print("  Event-Driven Execution Loop")
    print("=" * 60)
    print()

    # Initialize the central event queue
    event_queue = EventQueue()

    # Initialize services
    symbols = ["AAPL", "GOOGL", "MSFT"]

    # 1. Strategy Engine
    strategy_engine = StrategyEngineService(event_queue)
    strategy_engine.register_strategy(SMACrossoverStrategy(
        symbols=symbols,
        parameters={"short_window": 5, "long_window": 10},
    ))
    strategy_engine.register_strategy(MeanReversionStrategy(
        symbols=symbols,
        parameters={"window": 10, "num_std": 1.5},
    ))
    strategy_engine.start()

    # 2. Risk Manager
    risk_manager = RiskManager(event_queue)
    risk_manager.start()

    # 3. Execution Handler
    execution_handler = ExecutionHandlerService(
        event_queue=event_queue,
        default_broker="mock",
    )
    execution_handler.start()

    # 4. Register fill handler for portfolio updates
    fill_count = [0]
    def on_fill(event):
        fill_count[0] += 1
        print(f"  📊 FILL #{fill_count[0]}: {event.symbol} "
              f"{event.side.value} {event.filled_quantity:.0f} @ ${event.fill_price:.2f} "
              f"(commission: ${event.commission:.4f})")

    event_queue.register_handler(EventType.FILL, on_fill)

    print("✅ All services initialized")
    print(f"📈 Tracking symbols: {symbols}")
    print(f"🧠 Active strategies: {len(strategy_engine.strategies)}")
    print()
    print("-" * 60)
    print("  Simulating 200 market data ticks...")
    print("-" * 60)
    print()

    # Simulate market data feed
    import random
    prices = {s: random.uniform(100, 300) for s in symbols}

    for i in range(200):
        for symbol in symbols:
            # Random walk
            prices[symbol] += random.gauss(0, 1.0)
            prices[symbol] = max(10.0, prices[symbol])

            # Create market data event
            event = MarketDataEvent(
                symbol=symbol,
                price=round(prices[symbol], 2),
                volume=float(random.randint(100, 5000)),
                tick_type=TickType.TRADE,
            )

            # Push to event queue (triggers the chain)
            event_queue.put(event)

        # Process all events in queue
        while event_queue.process_next():
            pass

    # Print summary
    print()
    print("=" * 60)
    print("  DEMO RESULTS")
    print("=" * 60)
    print()
    print(f"  📊 Strategy Engine: {strategy_engine.status}")
    print(f"  🛡️  Risk Manager:   {risk_manager.status}")
    print(f"  ⚡ Execution:      {execution_handler.status}")
    print(f"  📈 Total Fills:    {fill_count[0]}")
    print()
    print("✅ Demo complete! The event-driven loop is working correctly.")
    print()


if __name__ == "__main__":
    run_demo()
