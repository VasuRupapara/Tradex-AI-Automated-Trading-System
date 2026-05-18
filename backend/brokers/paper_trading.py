"""
Paper Trading Adapter — Wraps any real broker for data,
but simulates all orders locally with virtual capital.

This is the KEY to safe testing: real market prices, fake trades.
Switch to live by changing TRADING_MODE=live in .env
"""

from __future__ import annotations

import asyncio
import random
from datetime import datetime
from typing import AsyncGenerator, Dict, List

from backend.brokers.base import BrokerAdapter
from backend.common.config import get_trading_config
from backend.common.events import (
    FillEvent, FillStatus, OrderEvent, OrderSide, OrderType,
)
from backend.common.logger import setup_logging

logger = setup_logging("paper-trading")


class PaperTradingAdapter(BrokerAdapter):
    """
    Paper trading wrapper.

    - Market data: comes from the REAL broker (live NSE prices)
    - Orders: simulated locally (no real money)
    - Positions: tracked in-memory
    """

    def __init__(self, real_broker: BrokerAdapter):
        super().__init__(f"paper_{real_broker.name}")
        self.real_broker = real_broker
        self._config = get_trading_config()

        # Virtual portfolio
        self.virtual_cash = self._config.TOTAL_CAPITAL
        self.virtual_positions: Dict[str, Dict] = {}  # symbol -> {qty, avg_price, product}
        self.virtual_holdings: List[Dict] = []
        self.virtual_orders: List[Dict] = []
        self.trade_count = 0

    # ---- Auth: delegate to real broker ----

    async def authenticate(self) -> bool:
        result = await self.real_broker.authenticate()
        self.authenticated = result
        if result:
            logger.info("paper_mode_active",
                       broker=self.real_broker.name,
                       capital=f"₹{self.virtual_cash:,.0f}")
        return result

    async def refresh_token(self) -> bool:
        return await self.real_broker.refresh_token()

    # ---- Market Data: use REAL data ----

    async def get_ltp(self, symbols: List[str]) -> Dict[str, float]:
        return await self.real_broker.get_ltp(symbols)

    async def stream_market_data(
        self, symbols: List[str]
    ) -> AsyncGenerator[Dict, None]:
        async for tick in self.real_broker.stream_market_data(symbols):
            yield tick

    async def get_historical_data(
        self, symbol, interval, from_date, to_date
    ) -> List[Dict]:
        return await self.real_broker.get_historical_data(
            symbol, interval, from_date, to_date
        )

    async def get_option_chain(self, symbol, expiry) -> Dict:
        return await self.real_broker.get_option_chain(symbol, expiry)

    # ---- Orders: SIMULATED locally ----

    async def place_order(self, order: OrderEvent) -> FillEvent:
        """Simulate order execution with realistic slippage."""
        self.trade_count += 1

        # Simulate small slippage (0-10 bps)
        slippage_bps = random.uniform(0, 10) / 10000
        base_price = order.limit_price or 0

        if base_price == 0:
            # For market orders without a reference price, use a placeholder
            # In real usage, the strategy should attach the current LTP
            base_price = 100.0

        if order.side == OrderSide.BUY:
            fill_price = base_price * (1 + slippage_bps)
        else:
            fill_price = base_price * (1 - slippage_bps)

        fill_price = round(fill_price, 2)
        quantity = order.quantity
        cost = fill_price * quantity

        # Check virtual margin
        if order.side == OrderSide.BUY and cost > self.virtual_cash:
            logger.warning("paper_insufficient_funds",
                         required=f"₹{cost:,.0f}",
                         available=f"₹{self.virtual_cash:,.0f}")
            return FillEvent(
                order_id=f"PAPER-{self.trade_count}",
                symbol=order.symbol,
                side=order.side,
                filled_quantity=0,
                fill_price=0,
                commission=0,
                slippage=0,
                status=FillStatus.REJECTED,
                broker=self.name,
            )

        # Simulate commission (₹20 per order, typical discount broker)
        commission = 20.0

        # Update virtual portfolio
        if order.side == OrderSide.BUY:
            self.virtual_cash -= (cost + commission)
            pos = self.virtual_positions.get(order.symbol, {"qty": 0, "avg_price": 0})
            old_qty = pos["qty"]
            old_avg = pos["avg_price"]
            new_qty = old_qty + quantity
            new_avg = ((old_avg * old_qty) + (fill_price * quantity)) / new_qty if new_qty > 0 else 0
            self.virtual_positions[order.symbol] = {"qty": new_qty, "avg_price": round(new_avg, 2)}
        else:
            self.virtual_cash += (cost - commission)
            pos = self.virtual_positions.get(order.symbol, {"qty": 0, "avg_price": 0})
            pos["qty"] -= quantity
            if pos["qty"] <= 0:
                self.virtual_positions.pop(order.symbol, None)
            else:
                self.virtual_positions[order.symbol] = pos

        # Log the virtual trade
        trade_record = {
            "id": f"PAPER-{self.trade_count}",
            "time": datetime.now().isoformat(),
            "symbol": order.symbol,
            "side": order.side.value.upper(),
            "qty": quantity,
            "price": fill_price,
            "commission": commission,
            "status": "FILLED",
        }
        self.virtual_orders.append(trade_record)

        logger.info("paper_trade_executed",
                   symbol=order.symbol,
                   side=order.side.value,
                   qty=quantity,
                   price=f"₹{fill_price:,.2f}",
                   cash_remaining=f"₹{self.virtual_cash:,.0f}")

        return FillEvent(
            order_id=f"PAPER-{self.trade_count}",
            symbol=order.symbol,
            side=order.side,
            filled_quantity=quantity,
            fill_price=fill_price,
            commission=commission,
            slippage=round(abs(fill_price - base_price) * quantity, 2),
            status=FillStatus.FILLED,
            broker=self.name,
        )

    async def cancel_order(self, order_id: str) -> bool:
        logger.info("paper_order_cancelled", order_id=order_id)
        return True

    async def get_positions(self) -> List[Dict]:
        return [
            {"symbol": sym, "quantity": d["qty"], "avg_price": d["avg_price"]}
            for sym, d in self.virtual_positions.items()
        ]

    async def get_holdings(self) -> List[Dict]:
        return await self.get_positions()

    async def get_order_book(self) -> List[Dict]:
        return self.virtual_orders[-50:]  # Last 50 orders

    async def get_balance(self) -> Dict:
        total_invested = sum(
            d["qty"] * d["avg_price"]
            for d in self.virtual_positions.values()
        )
        return {
            "balance": round(self.virtual_cash, 2),
            "margin_available": round(self.virtual_cash, 2),
            "total_capital": self._config.TOTAL_CAPITAL,
            "invested": round(total_invested, 2),
            "open_positions": len(self.virtual_positions),
            "total_trades": self.trade_count,
            "broker": self.name,
        }
