"""Upstox API v2 Broker Adapter. Requires: pip install aiohttp"""
from __future__ import annotations
import asyncio, json
from typing import AsyncGenerator, Dict, List
from backend.brokers.base import BrokerAdapter
from backend.common.config import get_upstox_config
from backend.common.events import FillEvent, FillStatus, OrderEvent, OrderSide, OrderType
from backend.common.logger import setup_logging
logger = setup_logging("broker-upstox")

class UpstoxAdapter(BrokerAdapter):
    def __init__(self):
        super().__init__("upstox")
        self._config = get_upstox_config()
        self._headers = {}

    async def authenticate(self) -> bool:
        if self._config.UPSTOX_ACCESS_TOKEN:
            self._headers = {
                "Authorization": f"Bearer {self._config.UPSTOX_ACCESS_TOKEN}",
                "Content-Type": "application/json", "Accept": "application/json",
            }
            self.authenticated = True
            logger.info("upstox_authenticated")
            return True
        logger.error("upstox_no_token")
        return False

    async def refresh_token(self) -> bool:
        return await self.authenticate()

    async def _api_get(self, url):
        import aiohttp
        async with aiohttp.ClientSession() as s:
            async with s.get(url, headers=self._headers) as r:
                return await r.json()

    async def get_ltp(self, symbols: List[str]) -> Dict[str, float]:
        syms = ",".join(f"NSE_EQ|{s}" for s in symbols)
        data = await self._api_get(f"https://api.upstox.com/v2/market-quote/ltp?instrument_key={syms}")
        return {k.split("|")[1]: v["last_price"] for k, v in data.get("data", {}).items()}

    async def stream_market_data(self, symbols: List[str]) -> AsyncGenerator[Dict, None]:
        import aiohttp
        auth = await self._api_get("https://api.upstox.com/v2/feed/market-data-feed/authorize")
        ws_url = auth["data"]["authorizedRedirectUri"]
        async with aiohttp.ClientSession() as s:
            async with s.ws_connect(ws_url) as ws:
                sub = json.dumps({"guid": "ats", "method": "sub", "data": {"mode": "full", "instrumentKeys": [f"NSE_EQ|{s}" for s in symbols]}})
                await ws.send_str(sub)
                async for msg in ws:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        feeds = json.loads(msg.data).get("feeds", {})
                        for key, feed in feeds.items():
                            sym = key.split("|")[1] if "|" in key else key
                            ltpc = feed.get("ff", {}).get("marketFF", {}).get("ltpc", {})
                            yield {"symbol": sym, "ltp": ltpc.get("ltp", 0), "close": ltpc.get("cp", 0)}

    async def get_historical_data(self, symbol, interval, from_date, to_date) -> List[Dict]:
        data = await self._api_get(f"https://api.upstox.com/v2/historical-candle/NSE_EQ|{symbol}/{interval}/{to_date}/{from_date}")
        return [{"timestamp": c[0], "open": c[1], "high": c[2], "low": c[3], "close": c[4], "volume": c[5]} for c in data.get("data", {}).get("candles", [])]

    async def place_order(self, order: OrderEvent) -> FillEvent:
        import aiohttp
        body = {"quantity": int(order.quantity), "product": "D", "validity": "DAY", "price": order.limit_price or 0, "instrument_token": f"NSE_EQ|{order.symbol}", "order_type": "MARKET" if order.order_type == OrderType.MARKET else "LIMIT", "transaction_type": "BUY" if order.side == OrderSide.BUY else "SELL", "disclosed_quantity": 0, "trigger_price": 0, "is_amo": False}
        async with aiohttp.ClientSession() as s:
            async with s.post("https://api.upstox.com/v2/order/place", headers=self._headers, json=body) as r:
                data = await r.json()
                oid = data.get("data", {}).get("order_id", order.event_id)
                return FillEvent(order_id=str(oid), symbol=order.symbol, side=order.side, filled_quantity=order.quantity, fill_price=order.limit_price or 0, commission=20.0, slippage=0, status=FillStatus.FILLED, broker=self.name)

    async def cancel_order(self, order_id) -> bool:
        import aiohttp
        async with aiohttp.ClientSession() as s:
            async with s.delete(f"https://api.upstox.com/v2/order/cancel?order_id={order_id}", headers=self._headers) as r:
                return r.status == 200

    async def get_positions(self) -> List[Dict]:
        return (await self._api_get("https://api.upstox.com/v2/portfolio/short-term-positions")).get("data", [])

    async def get_holdings(self) -> List[Dict]:
        return (await self._api_get("https://api.upstox.com/v2/portfolio/long-term-holdings")).get("data", [])

    async def get_order_book(self) -> List[Dict]:
        return (await self._api_get("https://api.upstox.com/v2/order/retrieve-all")).get("data", [])

    async def get_balance(self) -> Dict:
        data = await self._api_get("https://api.upstox.com/v2/user/get-funds-and-margin")
        eq = data.get("data", {}).get("equity", {})
        return {"balance": float(eq.get("available_margin", 0)), "margin_available": float(eq.get("available_margin", 0)), "broker": self.name}
