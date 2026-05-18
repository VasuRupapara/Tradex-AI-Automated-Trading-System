"""Dhan HQ Broker Adapter. Requires: pip install dhanhq"""
from __future__ import annotations
import asyncio
from typing import AsyncGenerator, Dict, List
from backend.brokers.base import BrokerAdapter
from backend.common.config import get_dhan_config
from backend.common.events import FillEvent, FillStatus, OrderEvent, OrderSide, OrderType
from backend.common.logger import setup_logging
logger = setup_logging("broker-dhan")

class DhanAdapter(BrokerAdapter):
    def __init__(self):
        super().__init__("dhan")
        self._config = get_dhan_config()
        self._dhan = None

    async def authenticate(self) -> bool:
        try:
            from dhanhq import dhanhq
            self._dhan = dhanhq(self._config.DHAN_CLIENT_ID, self._config.DHAN_ACCESS_TOKEN)
            self.authenticated = True
            logger.info("dhan_authenticated")
            return True
        except Exception as e:
            logger.error("dhan_auth_error", error=str(e))
            return False

    async def refresh_token(self) -> bool:
        return await self.authenticate()

    async def get_ltp(self, symbols: List[str]) -> Dict[str, float]:
        if not self._dhan:
            return {}
        result = {}
        for sym in symbols:
            try:
                sec_id = self._get_security_id(sym)
                data = self._dhan.get_market_quote(sec_id, "NSE_EQ")
                result[sym] = float(data.get("data", {}).get("LTP", 0))
            except Exception:
                pass
        return result

    async def stream_market_data(self, symbols: List[str]) -> AsyncGenerator[Dict, None]:
        # Dhan uses DhanFeed for WebSocket — simplified polling fallback
        while True:
            prices = await self.get_ltp(symbols)
            for sym, price in prices.items():
                yield {"symbol": sym, "ltp": price, "volume": 0}
            await asyncio.sleep(1)

    async def get_historical_data(self, symbol, interval, from_date, to_date) -> List[Dict]:
        if not self._dhan:
            return []
        try:
            sec_id = self._get_security_id(symbol)
            data = self._dhan.historical_daily_data(sec_id, "NSE_EQ", from_date, to_date)
            return [{"timestamp": c["start_Time"], "open": c["open"], "high": c["high"], "low": c["low"], "close": c["close"], "volume": c["volume"]} for c in data.get("data", [])]
        except Exception:
            return []

    async def place_order(self, order: OrderEvent) -> FillEvent:
        if not self._dhan:
            return self._rej(order)
        try:
            from dhanhq import dhanhq
            side = dhanhq.BUY if order.side == OrderSide.BUY else dhanhq.SELL
            o_type = dhanhq.MARKET if order.order_type == OrderType.MARKET else dhanhq.LIMIT
            sec_id = self._get_security_id(order.symbol)
            result = self._dhan.place_order(
                security_id=sec_id, exchange_segment=dhanhq.NSE,
                transaction_type=side, quantity=int(order.quantity),
                order_type=o_type, product_type=dhanhq.CNC,
                price=order.limit_price or 0,
            )
            oid = result.get("data", {}).get("orderId", order.event_id)
            return FillEvent(order_id=str(oid), symbol=order.symbol, side=order.side, filled_quantity=order.quantity, fill_price=order.limit_price or 0, commission=20.0, slippage=0, status=FillStatus.FILLED, broker=self.name)
        except Exception as e:
            logger.error("dhan_order_error", error=str(e))
            return self._rej(order)

    async def cancel_order(self, order_id) -> bool:
        try:
            self._dhan.cancel_order(order_id)
            return True
        except Exception:
            return False

    async def get_positions(self) -> List[Dict]:
        try:
            return self._dhan.get_positions().get("data", [])
        except Exception:
            return []

    async def get_holdings(self) -> List[Dict]:
        try:
            return self._dhan.get_holdings().get("data", [])
        except Exception:
            return []

    async def get_order_book(self) -> List[Dict]:
        try:
            return self._dhan.get_order_list().get("data", [])
        except Exception:
            return []

    async def get_balance(self) -> Dict:
        try:
            data = self._dhan.get_fund_limits()
            return {
                "balance": float(data.get("data", {}).get("availabelBalance", 0)),
                "margin_available": float(data.get("data", {}).get("availabelBalance", 0)),
                "broker": self.name,
            }
        except Exception:
            return {"balance": 0, "broker": self.name}

    def _get_security_id(self, symbol: str) -> str:
        IDS = {"RELIANCE": "2885", "TCS": "11536", "HDFCBANK": "1333", "INFY": "1594", "ICICIBANK": "4963", "SBIN": "3045", "ITC": "1660", "BHARTIARTL": "10604", "HINDUNILVR": "1394", "KOTAKBANK": "1922"}
        return IDS.get(symbol, "")

    def _rej(self, order):
        return FillEvent(order_id=order.event_id, symbol=order.symbol, side=order.side, filled_quantity=0, fill_price=0, commission=0, slippage=0, status=FillStatus.REJECTED, broker=self.name)
