"""
Base Broker Adapter — Abstract interface for all Indian brokers.

Every broker (Angel One, Zerodha, Fyers, Upstox, Dhan) implements
this interface so the trading engine is broker-agnostic.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import AsyncGenerator, Dict, List, Optional

from backend.common.events import FillEvent, OrderEvent


class BrokerAdapter(ABC):
    """
    Abstract base for Indian stock broker adapters.

    Provides three capabilities:
      1. Authentication (login, token refresh)
      2. Market Data (real-time stream, LTP, historical, option chain)
      3. Order Execution (place, cancel, positions, holdings)
    """

    def __init__(self, name: str):
        self.name = name
        self.connected = False
        self.authenticated = False

    # ---- Authentication ----

    @abstractmethod
    async def authenticate(self) -> bool:
        """Login to the broker API. Returns True on success."""
        ...

    @abstractmethod
    async def refresh_token(self) -> bool:
        """Refresh the access token if it expires."""
        ...

    # ---- Market Data ----

    @abstractmethod
    async def get_ltp(self, symbols: List[str]) -> Dict[str, float]:
        """Get Last Traded Price for a list of symbols."""
        ...

    @abstractmethod
    async def stream_market_data(
        self, symbols: List[str]
    ) -> AsyncGenerator[Dict, None]:
        """
        Yield real-time tick data as dicts:
        {"symbol": "RELIANCE", "ltp": 2845.50, "volume": 12000, ...}
        """
        ...

    @abstractmethod
    async def get_historical_data(
        self,
        symbol: str,
        interval: str,
        from_date: str,
        to_date: str,
    ) -> List[Dict]:
        """Get historical OHLCV candle data."""
        ...

    async def get_option_chain(
        self, symbol: str, expiry: str
    ) -> Dict:
        """Get option chain for an index/stock. Override if supported."""
        return {}

    # ---- Order Execution ----

    @abstractmethod
    async def place_order(self, order: OrderEvent) -> FillEvent:
        """Place an order and return fill result."""
        ...

    @abstractmethod
    async def cancel_order(self, order_id: str) -> bool:
        """Cancel a pending order."""
        ...

    @abstractmethod
    async def get_positions(self) -> List[Dict]:
        """Get current open positions."""
        ...

    @abstractmethod
    async def get_holdings(self) -> List[Dict]:
        """Get delivery holdings (CNC)."""
        ...

    @abstractmethod
    async def get_order_book(self) -> List[Dict]:
        """Get today's order book."""
        ...

    # ---- Account ----

    @abstractmethod
    async def get_balance(self) -> Dict:
        """Get account balance and margin info."""
        ...

    async def get_margins(self) -> Dict:
        """Get detailed margin breakdown. Default: same as balance."""
        return await self.get_balance()

    # ---- Lifecycle ----

    async def connect(self) -> None:
        """Connect and authenticate."""
        self.authenticated = await self.authenticate()
        self.connected = self.authenticated

    async def disconnect(self) -> None:
        """Clean disconnect."""
        self.connected = False
        self.authenticated = False
