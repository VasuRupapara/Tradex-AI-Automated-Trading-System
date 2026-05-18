"""Zerodha Kite Connect Broker Adapter. Requires: pip install kiteconnect"""
from __future__ import annotations
import asyncio
from typing import AsyncGenerator, Dict, List
from backend.brokers.base import BrokerAdapter
from backend.common.config import get_zerodha_config
from backend.common.events import FillEvent, FillStatus, OrderEvent, OrderSide, OrderType
from backend.common.logger import setup_logging
logger = setup_logging("broker-zerodha")

class ZerodhaAdapter(BrokerAdapter):
    def __init__(self):
        super().__init__("zerodha")
        self._config = get_zerodha_config()
        self._kite = None
    async def authenticate(self) -> bool:
        try:
            from kiteconnect import KiteConnect
            self._kite = KiteConnect(api_key=self._config.ZERODHA_API_KEY)
            if self._config.ZERODHA_ACCESS_TOKEN:
                self._kite.set_access_token(self._config.ZERODHA_ACCESS_TOKEN)
                self.authenticated = True
                logger.info("zerodha_authenticated")
                return True
            logger.warning("zerodha_no_access_token", hint="Generate via kite.trade/connect/login")
            return False
        except Exception as e:
            logger.error("zerodha_auth_error", error=str(e))
            return False
    async def refresh_token(self) -> bool:
        return await self.authenticate()
    async def get_ltp(self, symbols: List[str]) -> Dict[str, float]:
        if not self._kite: return {}
        try:
            instruments = [f"NSE:{s}" for s in symbols]
            data = self._kite.ltp(instruments)
            return {k.split(":")[1]: v["last_price"] for k, v in data.items()}
        except Exception as e:
            logger.error("zerodha_ltp_error", error=str(e)); return {}
    async def stream_market_data(self, symbols: List[str]) -> AsyncGenerator[Dict, None]:
        try:
            from kiteconnect import KiteTicker
            queue = asyncio.Queue()
            tokens = [self._get_instrument_token(s) for s in symbols]
            token_map = dict(zip(tokens, symbols))
            def on_ticks(ws, ticks):
                for t in ticks:
                    queue.put_nowait({
                        "symbol": token_map.get(t["instrument_token"], ""),
                        "ltp": t.get("last_price", 0), "volume": t.get("volume_traded", 0),
                        "open": t.get("ohlc", {}).get("open", 0), "high": t.get("ohlc", {}).get("high", 0),
                        "low": t.get("ohlc", {}).get("low", 0), "close": t.get("ohlc", {}).get("close", 0),
                        "oi": t.get("oi", 0),
                    })
            def on_connect(ws, response):
                ws.subscribe(tokens); ws.set_mode(ws.MODE_FULL, tokens)
            kws = KiteTicker(self._config.ZERODHA_API_KEY, self._config.ZERODHA_ACCESS_TOKEN)
            kws.on_ticks = on_ticks; kws.on_connect = on_connect
            loop = asyncio.get_event_loop()
            loop.run_in_executor(None, kws.connect, True)
            while True: yield await queue.get()
        except ImportError:
            logger.warning("kiteconnect not installed"); return
    async def get_historical_data(self, symbol, interval, from_date, to_date) -> List[Dict]:
        if not self._kite: return []
        try:
            token = self._get_instrument_token(symbol)
            data = self._kite.historical_data(token, from_date, to_date, interval)
            return [{"timestamp": str(c["date"]), "open": c["open"], "high": c["high"], "low": c["low"], "close": c["close"], "volume": c["volume"]} for c in data]
        except Exception: return []
    async def place_order(self, order: OrderEvent) -> FillEvent:
        if not self._kite: return self._rejected_fill(order)
        try:
            from kiteconnect import KiteConnect
            params = {
                "tradingsymbol": order.symbol, "exchange": "NSE",
                "transaction_type": self._kite.TRANSACTION_TYPE_BUY if order.side == OrderSide.BUY else self._kite.TRANSACTION_TYPE_SELL,
                "quantity": int(order.quantity),
                "order_type": self._kite.ORDER_TYPE_MARKET if order.order_type == OrderType.MARKET else self._kite.ORDER_TYPE_LIMIT,
                "product": self._kite.PRODUCT_CNC,
            }
            if order.limit_price: params["price"] = order.limit_price
            oid = self._kite.place_order(variety=self._kite.VARIETY_REGULAR, **params)
            return FillEvent(order_id=str(oid), symbol=order.symbol, side=order.side, filled_quantity=order.quantity, fill_price=order.limit_price or 0, commission=20.0, slippage=0, status=FillStatus.FILLED, broker=self.name)
        except Exception as e:
            logger.error("zerodha_order_error", error=str(e)); return self._rejected_fill(order)
    async def cancel_order(self, order_id) -> bool:
        try: self._kite.cancel_order(self._kite.VARIETY_REGULAR, order_id); return True
        except: return False
    async def get_positions(self) -> List[Dict]:
        try: return self._kite.positions().get("net", [])
        except: return []
    async def get_holdings(self) -> List[Dict]:
        try: return self._kite.holdings()
        except: return []
    async def get_order_book(self) -> List[Dict]:
        try: return self._kite.orders()
        except: return []
    async def get_balance(self) -> Dict:
        try:
            m = self._kite.margins("equity")
            return {"balance": float(m.get("available", {}).get("cash", 0)), "margin_available": float(m.get("net", 0)), "broker": self.name}
        except: return {"balance": 0, "broker": self.name}
    def _get_instrument_token(self, symbol: str) -> int:
        TOKENS = {"RELIANCE": 738561, "TCS": 2953217, "HDFCBANK": 341249, "INFY": 408065, "ICICIBANK": 1270529, "SBIN": 779521, "ITC": 424961, "BHARTIARTL": 2714625, "HINDUNILVR": 356865, "KOTAKBANK": 492033, "NIFTY": 256265, "BANKNIFTY": 260105}
        return TOKENS.get(symbol, 0)
    def _rejected_fill(self, order):
        return FillEvent(order_id=order.event_id, symbol=order.symbol, side=order.side, filled_quantity=0, fill_price=0, commission=0, slippage=0, status=FillStatus.REJECTED, broker=self.name)
