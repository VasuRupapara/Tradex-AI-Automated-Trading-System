"""
Master Launcher — Indian Automated Trading System

Initializes all services in a single event loop:
  1. Broker adapter (auto-selected from .env)
  2. Market data feed (real or mock)
  3. Dual-engine strategies (Equity + F&O)
  4. Risk management with SEBI rules
  5. Execution handler (paper or live)
  6. Dashboard WebSocket bridge
  7. FastAPI gateway

Run: python start_trading.py
"""

import asyncio
import os
import sys
from datetime import datetime
from enum import Enum as _Enum

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from backend.common.event_queue import EventQueue
from backend.common.events import EventType
from backend.common.config import get_broker_selection, get_trading_config, get_risk_config
from backend.common.logger import setup_logging
from backend.brokers.registry import BrokerRegistry
from backend.indian_market.data_feed import IndianMarketDataService
from backend.indian_market.strategies import (
    IndianStrategyEngine,
    EquityMomentumStrategy,
    EquityMeanReversionStrategy,
    NiftyIntradayStrategy,
)
from backend.indian_market.smart_money_strategy import SmartMoneyStrategy
from backend.indian_market.models import MarketSchedule
from backend.risk_management.src.main import RiskManager
from backend.api_gateway.src.main import app, ws_manager

logger = setup_logging("ats-india", "INFO")


class IndianTradingEngine:
    """
    Unified Indian ATS Engine.

    Reads BROKER_NAME and TRADING_MODE from .env,
    auto-configures everything, and runs the full pipeline.
    """

    def __init__(self):
        self.event_queue = EventQueue()
        self._broker_config = get_broker_selection()
        self._trading_config = get_trading_config()
        self._risk_config = get_risk_config()

        # Symbols from .env
        self.equity_symbols = self._trading_config.equity_symbols_list
        self.fno_symbols = self._trading_config.fno_symbols_list
        self.crypto_symbols = self._trading_config.crypto_symbols_list
        self.all_symbols = self.equity_symbols + self.fno_symbols + self.crypto_symbols

        # 1. Create broker (auto-wraps in PaperTrading if TRADING_MODE=paper)
        self.broker = BrokerRegistry.create()

        # 2. Market data service
        self.market_data = IndianMarketDataService(
            event_queue=self.event_queue,
            broker=self.broker if self.broker.authenticated else None,
            symbols=self.all_symbols,
        )

        # 3. Strategy engine with dual strategies
        self.strategy_engine = IndianStrategyEngine(self.event_queue)

        # Equity strategies (on equity symbols)
        self.strategy_engine.register(EquityMomentumStrategy(
            symbols=self.equity_symbols,
            params={"rsi_period": 14, "ema_short": 9, "ema_long": 21},
        ))
        self.strategy_engine.register(EquityMeanReversionStrategy(
            symbols=self.equity_symbols,
            params={"window": 15, "num_std": 1.5},
        ))

        # F&O strategy (on index symbols)
        self.strategy_engine.register(NiftyIntradayStrategy(
            symbols=self.fno_symbols,
            params={"breakout_window": 30},
        ))

        # Smart Money Concepts strategy (on equity symbols)
        self.strategy_engine.register(SmartMoneyStrategy(
            symbols=self.equity_symbols,
            params={"swing_length": 50, "internal_length": 5, "min_signal_strength": 0.3},
        ))

        # 4. Risk manager
        self.risk_manager = RiskManager(self.event_queue)

        # 5. Execution handler (uses the broker adapter directly)
        self.execution_broker = self.broker

    async def broadcast_to_dashboard(self, event):
        """Bridge events to the Flutter WebSocket dashboard."""
        def _serialize(obj):
            if isinstance(obj, _Enum):
                return obj.value if hasattr(obj, 'value') else obj.name
            if isinstance(obj, datetime):
                return obj.isoformat()
            if isinstance(obj, dict):
                return {k: _serialize(v) for k, v in obj.items()}
            if isinstance(obj, (list, tuple)):
                return [_serialize(v) for v in obj]
            return obj

        raw = vars(event) if hasattr(event, "____dict__") else {}
        if not raw and hasattr(event, "__dict__"):
            raw = event.__dict__
        safe = _serialize(raw)

        msg = {
            "type": event.event_type.name,
            "timestamp": datetime.now().isoformat(),
            "data": safe,
        }
        await ws_manager.broadcast(msg)

    async def handle_order_via_broker(self, event):
        """Execute orders through the broker adapter."""
        try:
            fill = await self.execution_broker.place_order(event)
            self.event_queue.put(fill)
            logger.info("order_executed",
                       symbol=event.symbol,
                       side=event.side.value,
                       qty=event.quantity,
                       fill_status=fill.status.value)
        except Exception as e:
            logger.error("order_execution_failed", error=str(e))

    async def start(self):
        """Start the full Indian ATS pipeline."""
        mode = self._broker_config.TRADING_MODE.upper()
        broker_name = self._broker_config.BROKER_NAME

        logger.info("=" * 60)
        logger.info("🤖 TRADEX AI - AUTOMATED TRADING SYSTEM")
        logger.info("=" * 60)
        logger.info(f"Broker:        {broker_name}")
        logger.info(f"Mode:          {mode} {'🟡' if mode == 'PAPER' else '🔴 LIVE'}")
        logger.info(f"Capital:       ₹{self._trading_config.TOTAL_CAPITAL:,.0f}")
        logger.info(f"  Equity (CNC):  ₹{self._trading_config.equity_capital:,.0f} ({self._trading_config.EQUITY_CAPITAL_PERCENT}%)")
        logger.info(f"  F&O (MIS):     ₹{self._trading_config.fno_capital:,.0f} ({self._trading_config.FNO_CAPITAL_PERCENT}%)")
        logger.info(f"Equity Stocks: {self.equity_symbols}")
        logger.info(f"F&O Indices:   {self.fno_symbols}")
        logger.info(f"Crypto Watch:  {self.crypto_symbols}")
        logger.info(f"Market Status: {MarketSchedule.market_status()}")
        logger.info("=" * 60)

        # Try to authenticate broker (for real data)
        try:
            await self.broker.connect()
        except Exception as e:
            logger.warning(f"Broker auth failed ({e}), using mock data feed")

        # Register dashboard broadcast for all event types
        for et in [EventType.MARKET_DATA, EventType.SIGNAL,
                    EventType.ORDER, EventType.FILL]:
            self.event_queue.register_handler(et, self.broadcast_to_dashboard)

        # Register order handler
        self.event_queue.register_handler(EventType.ORDER, self.handle_order_via_broker)

        # Start strategy engine & risk manager
        self.strategy_engine.start()
        self.risk_manager.start()

        logger.info("All services started. Launching event loop...")

        # Run market data + event loop + API gateway concurrently
        await asyncio.gather(
            self.market_data.start(),
            self.event_queue.async_run_loop(),
            self._start_api_gateway(),
            self._run_monthly_report_scheduler(),
        )

    async def _start_api_gateway(self):
        """Run FastAPI inside the same event loop."""
        import uvicorn
        config = uvicorn.Config(app, host="0.0.0.0", port=8000, log_level="warning")
        server = uvicorn.Server(config)
        await server.serve()

    async def _run_monthly_report_scheduler(self):
        """
        Background task that checks daily if it's the last day of the month,
        and sends the PDF report email at 23:50.
        """
        from backend.common.monthly_report import execute_monthly_report
        import calendar
        
        logger.info("Monthly report scheduler started.")
        while True:
            now = datetime.now()
            # Find the last day of the current month
            _, last_day = calendar.monthrange(now.year, now.month)
            
            # If today is the last day and time is 23:50 (11:50 PM)
            if now.day == last_day and now.hour == 23 and now.minute == 50:
                logger.info("Month end detected. Generating and sending PDF report...")
                # Run synchronously in another thread or just block since it's end of day
                try:
                    execute_monthly_report()
                except Exception as e:
                    logger.error(f"Failed to execute monthly report: {e}")
                
                # Sleep for 61 seconds to avoid triggering multiple times in the same minute
                await asyncio.sleep(61)
            else:
                # Check again in 30 seconds
                await asyncio.sleep(30)


if __name__ == "__main__":
    engine = IndianTradingEngine()
    try:
        asyncio.run(engine.start())
    except KeyboardInterrupt:
        logger.info("System shutdown requested. Goodbye!")
