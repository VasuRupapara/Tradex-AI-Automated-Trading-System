"""
Indian Mock Data Feed — Generates realistic NSE market data
when broker credentials are not yet configured.

Simulates realistic Indian stock price movements using
geometric Brownian motion with proper INR price ranges.
"""

from __future__ import annotations

import asyncio
import random
from datetime import datetime
from typing import Dict, List

from backend.common.events import EventType, MarketDataEvent
from backend.common.event_queue import EventQueue
from backend.common.logger import setup_logging
from backend.indian_market.models import (
    EQUITY_BASE_PRICES, INDEX_BASE_PRICES, MarketSchedule,
)

logger = setup_logging("indian-mock-feed")


class IndianMockDataFeed:
    """
    Generates realistic mock NSE market data.

    Uses geometric Brownian motion with typical Indian market
    volatility parameters. Generates ticks every 100ms.
    """

    def __init__(self, symbols: List[str]):
        self.symbols = symbols
        self._prices: Dict[str, float] = {}
        self._volumes: Dict[str, int] = {}

        # Initialize with realistic base prices
        all_prices = {**EQUITY_BASE_PRICES, **INDEX_BASE_PRICES}
        for sym in symbols:
            self._prices[sym] = all_prices.get(sym, 1000.0)
            self._volumes[sym] = random.randint(10000, 500000)

        # Volatility per symbol type
        self._volatility = {}
        for sym in symbols:
            if sym in INDEX_BASE_PRICES:
                self._volatility[sym] = 0.0003  # Lower vol for indices
            else:
                self._volatility[sym] = 0.0008  # Higher vol for stocks

    async def generate_ticks(self, event_queue: EventQueue):
        """
        Generate continuous market data ticks.

        Each tick updates the price using GBM and pushes
        a MarketDataEvent to the event queue.
        """
        logger.info("indian_mock_feed_started",
                   symbols=self.symbols,
                   market_status=MarketSchedule.market_status())

        tick_count = 0
        while True:
            for symbol in self.symbols:
                # Geometric Brownian Motion
                vol = self._volatility[symbol]
                drift = random.gauss(0, vol)
                self._prices[symbol] *= (1 + drift)

                # Round to tick size (₹0.05 for equity, ₹0.05 for index)
                self._prices[symbol] = round(self._prices[symbol] / 0.05) * 0.05

                # Simulate volume
                self._volumes[symbol] += random.randint(100, 5000)

                # Calculate OHLC (simplified)
                price = self._prices[symbol]
                noise = price * 0.001  # 0.1% range

                event = MarketDataEvent(
                    symbol=symbol,
                    price=price,
                    volume=float(self._volumes[symbol]),
                    open=round(price + random.uniform(-noise, noise), 2),
                    high=round(price + abs(random.gauss(0, noise)), 2),
                    low=round(price - abs(random.gauss(0, noise)), 2),
                    close=round(price, 2),
                    bid=round(price - 0.05, 2),
                    ask=round(price + 0.05, 2),
                )

                await event_queue.async_put(event)

            tick_count += 1
            if tick_count % 100 == 0:
                logger.debug("mock_ticks_generated", count=tick_count)

            # Tick interval: 2.0 seconds (for easier human observation)
            await asyncio.sleep(2.0)


class IndianMarketDataService:
    """
    Market data service for Indian markets.

    Can use either:
    1. Mock feed (no credentials needed)
    2. Real broker feed (via broker adapter WebSocket)
    """

    def __init__(self, event_queue: EventQueue, broker=None, symbols=None):
        self.event_queue = event_queue
        self.broker = broker
        self.symbols = symbols or []
        self._use_mock = broker is None

    async def start(self):
        """Start the market data feed."""
        if self._use_mock or not self.broker or not self.broker.authenticated:
            logger.info("using_mock_data_feed",
                       reason="No broker credentials or broker not authenticated")
            feed = IndianMockDataFeed(self.symbols)
            await feed.generate_ticks(self.event_queue)
        else:
            logger.info("using_live_broker_feed", broker=self.broker.name)
            await self._stream_from_broker()

    async def _stream_from_broker(self):
        """Stream real data from the broker adapter."""
        try:
            async for tick in self.broker.stream_market_data(self.symbols):
                symbol = tick.get("symbol", "")
                ltp = tick.get("ltp", 0)
                if symbol and ltp > 0:
                    event = MarketDataEvent(
                        symbol=symbol,
                        price=ltp,
                        volume=float(tick.get("volume", 0)),
                        open=float(tick.get("open", 0)),
                        high=float(tick.get("high", 0)),
                        low=float(tick.get("low", 0)),
                        close=float(tick.get("close", 0)),
                        bid=float(tick.get("bid", ltp - 0.05)),
                        ask=float(tick.get("ask", ltp + 0.05)),
                    )
                    await self.event_queue.async_put(event)
        except Exception as e:
            logger.error("broker_feed_error", error=str(e))
            logger.info("falling_back_to_mock_feed")
            feed = IndianMockDataFeed(self.symbols)
            await feed.generate_ticks(self.event_queue)
