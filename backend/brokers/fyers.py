"""Fyers API v3 Broker Adapter. Requires: pip install fyers-apiv3"""
from __future__ import annotations
import asyncio
from typing import AsyncGenerator, Dict, List
from backend.brokers.base import BrokerAdapter
from backend.common.config import get_fyers_config
from backend.common.events import FillEvent, FillStatus, OrderEvent, OrderSide, OrderType
from backend.common.logger import setup_logging
logger = setup_logging("broker-fyers")

class FyersAdapter(BrokerAdapter):
    def __init__(self):
        super().__init__("fyers")
        self._config = get_fyers_config()
        self._fyers = None
    async def authenticate(self) -> bool:
        try:
            from fyers_apiv3 import fyersModel
            self._fyers = fyersModel.FyersModel(client_id=self._config.FYERS_APP_ID, is_async=False, token=self._config.FYERS_ACCESS_TOKEN, log_path="")
            profile = self._fyers.get_profile()
            if profile.get("s") == "ok":
                self.authenticated = True
                logger.info("fyers_authenticated", name=profile.get("data", {}).get("name"))
                return True
            logger.error("fyers_auth_failed", response=profile); return False
        except Exception as e:
            logger.error("fyers_auth_error", error=str(e)); return False
    async def refresh_token(self) -> bool: return await self.authenticate()
    async def get_ltp(self, symbols: List[str]) -> Dict[str, float]:
        if not self._fyers: return {}
        try:
            syms = ",".join(f"NSE:{s}-EQ" for s in symbols)
            data = self._fyers.quotes({"symbols": syms})
            result = {}
            for q in data.get("d", []):
                sym = q["n"].split(":")[1].replace("-EQ", "")
                result[sym] = q["v"]["lp"]
            return result
        except Exception as e: logger.error("fyers_ltp_error", error=str(e)); return {}
    async def stream_market_data(self, symbols: List[str]) -> AsyncGenerator[Dict, None]:
        try:
            from fyers_apiv3.FyersWebsocket import data_ws
            queue = asyncio.Queue()
            sym_list = [f"NSE:{s}-EQ" for s in symbols]
            def on_msg(message):
                if isinstance(message, dict) and "symbol" in message:
                    sym = message["symbol"].split(":")[1].replace("-EQ", "")
                    queue.put_nowait({"symbol": sym, "ltp": message.get("ltp", 0), "volume": message.get("vol_traded_today", 0), "open": message.get("open_price", 0), "high": message.get("high_price", 0), "low": message.get("low_price", 0), "close": message.get("prev_close_price", 0)})
            ws = data_ws.FyersDataSocket(access_token=f"{self._config.FYERS_APP_ID}:{self._config.FYERS_ACCESS_TOKEN}", log_path="", litemode=False, write_to_file=False, reconnect=True, on_message=on_msg)
            ws.subscribe(symbols=sym_list, data_type="SymbolUpdate")
            loop = asyncio.get_event_loop()
            loop.run_in_executor(None, ws.keep_running)
            while True: yield await queue.get()
        except ImportError: logger.warning("fyers_apiv3 not installed"); return
    async def get_historical_data(self, symbol, interval, from_date, to_date) -> List[Dict]:
        if not self._fyers: return []
        try:
            INTERVALS = {"1m": "1", "5m": "5", "15m": "15", "1h": "60", "1d": "1D"}
            data = self._fyers.history({"symbol": f"NSE:{symbol}-EQ", "resolution": INTERVALS.get(interval, "5"), "date_format": "1", "range_from": from_date, "range_to": to_date, "cont_flag": "1"})
            return [{"timestamp": c[0], "open": c[1], "high": c[2], "low": c[3], "close": c[4], "volume": c[5]} for c in data.get("candles", [])]
        except Exception: return []
    async def place_order(self, order: OrderEvent) -> FillEvent:
        if not self._fyers: return self._rejected_fill(order)
        try:
            data = {"symbol": f"NSE:{order.symbol}-EQ", "qty": int(order.quantity), "type": 2 if order.order_type == OrderType.MARKET else 1, "side": 1 if order.side == OrderSide.BUY else -1, "productType": "CNC", "limitPrice": order.limit_price or 0, "stopPrice": 0, "validity": "DAY", "disclosedQty": 0, "offlineOrder": False}
            result = self._fyers.place_order(data)
            oid = result.get("id", order.event_id)
            return FillEvent(order_id=str(oid), symbol=order.symbol, side=order.side, filled_quantity=order.quantity, fill_price=order.limit_price or 0, commission=20.0, slippage=0, status=FillStatus.FILLED, broker=self.name)
        except Exception as e: logger.error("fyers_order_error", error=str(e)); return self._rejected_fill(order)
    async def cancel_order(self, order_id) -> bool:
        try: self._fyers.cancel_order({"id": order_id}); return True
        except: return False
    async def get_positions(self) -> List[Dict]:
        try: return self._fyers.positions().get("netPositions", [])
        except: return []
    async def get_holdings(self) -> List[Dict]:
        try: return self._fyers.holdings().get("holdings", [])
        except: return []
    async def get_order_book(self) -> List[Dict]:
        try: return self._fyers.orderbook().get("orderBook", [])
        except: return []
    async def get_balance(self) -> Dict:
        try:
            data = self._fyers.funds()
            funds = {f["title"]: f["equityAmount"] for f in data.get("fund_limit", [])}
            return {"balance": float(funds.get("Total Balance", 0)), "margin_available": float(funds.get("Available Balance", 0)), "broker": self.name}
        except: return {"balance": 0, "broker": self.name}
    def _rejected_fill(self, order):
        return FillEvent(order_id=order.event_id, symbol=order.symbol, side=order.side, filled_quantity=0, fill_price=0, commission=0, slippage=0, status=FillStatus.REJECTED, broker=self.name)
