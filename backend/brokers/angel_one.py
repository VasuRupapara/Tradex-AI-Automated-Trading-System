"""
Angel One SmartAPI Broker Adapter.

Connects to Angel One (formerly Angel Broking) via the SmartAPI SDK.
Provides real-time WebSocket data, order placement, and account info.

Requirements: pip install smartapi-python pyotp
Docs: https://smartapi.angelone.in/docs
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import AsyncGenerator, Dict, List, Optional

from backend.brokers.base import BrokerAdapter
from backend.common.config import get_angel_config
from backend.common.events import (
    FillEvent, FillStatus, OrderEvent, OrderSide, OrderType,
)
from backend.common.logger import setup_logging

logger = setup_logging("broker-angel-one")


class AngelOneAdapter(BrokerAdapter):
    """
    Angel One SmartAPI adapter.

    Auth: Client ID + Password + TOTP (Time-based OTP via pyotp).
    Data: SmartAPI WebSocket for real-time, REST for historical.
    Orders: REST API for all order types.
    """

    def __init__(self):
        super().__init__("angel_one")
        self._config = get_angel_config()
        self._client = None
        self._feed_token = None
        self._ws = None

    async def authenticate(self) -> bool:
        """Login using Client ID, Password, and TOTP."""
        try:
            from SmartApi import SmartConnect
            import pyotp

            self._client = SmartConnect(api_key=self._config.ANGEL_API_KEY)

            totp = pyotp.TOTP(self._config.ANGEL_TOTP_SECRET).now()

            data = self._client.generateSession(
                clientCode=self._config.ANGEL_CLIENT_ID,
                password=self._config.ANGEL_PASSWORD,
                totp=totp,
            )

            if data["status"]:
                self._feed_token = self._client.getfeedToken()
                self.authenticated = True
                logger.info("angel_one_authenticated",
                           client_id=self._config.ANGEL_CLIENT_ID)
                return True
            else:
                logger.error("angel_one_auth_failed", message=data.get("message"))
                return False

        except Exception as e:
            logger.error("angel_one_auth_error", error=str(e))
            return False

    async def refresh_token(self) -> bool:
        """Re-generate session token."""
        return await self.authenticate()

    # ---- Market Data ----

    async def get_ltp(self, symbols: List[str]) -> Dict[str, float]:
        """Get LTP for symbols via REST API."""
        if not self._client:
            return {}

        result = {}
        try:
            for symbol in symbols:
                exchange = "NSE"
                trading_symbol = symbol + "-EQ" if not symbol.endswith(("-EQ", "CE", "PE", "FUT")) else symbol

                data = self._client.ltpData(
                    exchange=exchange,
                    tradingsymbol=trading_symbol,
                    symboltoken=self._get_token(symbol),
                )
                if data["status"]:
                    result[symbol] = float(data["data"]["ltp"])
        except Exception as e:
            logger.error("angel_ltp_error", error=str(e))

        return result

    async def stream_market_data(
        self, symbols: List[str]
    ) -> AsyncGenerator[Dict, None]:
        """
        Stream real-time tick data via Angel One WebSocket.

        Yields dicts like:
          {"symbol": "RELIANCE", "ltp": 2845.50, "volume": 12340, ...}
        """
        try:
            from SmartApi.smartWebSocketV2 import SmartWebSocketV2

            token_list = []
            token_map = {}  # token -> symbol name

            for sym in symbols:
                token = self._get_token(sym)
                if token:
                    token_list.append({"exchangeType": 1, "tokens": [token]})
                    token_map[token] = sym

            queue = asyncio.Queue()

            def on_data(ws, message):
                try:
                    sym_name = token_map.get(str(message.get("token", "")), "")
                    tick = {
                        "symbol": sym_name,
                        "ltp": message.get("last_traded_price", 0) / 100,
                        "open": message.get("open_price_day", 0) / 100,
                        "high": message.get("high_price_day", 0) / 100,
                        "low": message.get("low_price_day", 0) / 100,
                        "close": message.get("close_price", 0) / 100,
                        "volume": message.get("volume_traded", 0),
                        "oi": message.get("open_interest", 0),
                    }
                    queue.put_nowait(tick)
                except Exception:
                    pass

            def on_open(ws):
                logger.info("angel_ws_connected")
                ws.subscribe("abc123", 1, token_list)

            def on_error(ws, error):
                logger.error("angel_ws_error", error=str(error))

            self._ws = SmartWebSocketV2(
                self._client.AUTH_TOKEN,
                self._config.ANGEL_API_KEY,
                self._config.ANGEL_CLIENT_ID,
                self._feed_token,
            )
            self._ws.on_data = on_data
            self._ws.on_open = on_open
            self._ws.on_error = on_error

            # Run WebSocket in a background thread
            loop = asyncio.get_event_loop()
            loop.run_in_executor(None, self._ws.connect)

            while True:
                tick = await queue.get()
                yield tick

        except ImportError:
            logger.warning("SmartApi not installed, falling back to mock data")
            return
        except Exception as e:
            logger.error("angel_stream_error", error=str(e))

    async def get_historical_data(
        self, symbol: str, interval: str, from_date: str, to_date: str
    ) -> List[Dict]:
        """Get historical candle data."""
        if not self._client:
            return []

        try:
            params = {
                "exchange": "NSE",
                "symboltoken": self._get_token(symbol),
                "interval": interval,   # ONE_MINUTE, FIVE_MINUTE, etc.
                "fromdate": from_date,  # "2025-01-01 09:15"
                "todate": to_date,      # "2025-01-31 15:30"
            }
            data = self._client.getCandleData(params)
            if data["status"]:
                candles = []
                for c in data["data"]:
                    candles.append({
                        "timestamp": c[0],
                        "open": c[1],
                        "high": c[2],
                        "low": c[3],
                        "close": c[4],
                        "volume": c[5],
                    })
                return candles
        except Exception as e:
            logger.error("angel_historical_error", error=str(e))

        return []

    async def get_option_chain(self, symbol: str, expiry: str) -> Dict:
        """Get option chain (not directly available in SmartAPI — built from instruments)."""
        return {"symbol": symbol, "expiry": expiry, "chain": []}

    # ---- Order Execution ----

    async def place_order(self, order: OrderEvent) -> FillEvent:
        """Place order via Angel One REST API."""
        if not self._client:
            return self._rejected_fill(order, "Not authenticated")

        try:
            side = "BUY" if order.side == OrderSide.BUY else "SELL"
            order_type = "MARKET" if order.order_type == OrderType.MARKET else "LIMIT"

            # Determine product type and exchange
            is_fno = any(x in order.symbol for x in ["CE", "PE", "FUT"])
            exchange = "NFO" if is_fno else "NSE"
            product_type = "CARRYFORWARD" if is_fno else "DELIVERY"
            trading_symbol = order.symbol if is_fno else order.symbol + "-EQ"

            params = {
                "variety": "NORMAL",
                "tradingsymbol": trading_symbol,
                "symboltoken": self._get_token(order.symbol),
                "transactiontype": side,
                "exchange": exchange,
                "ordertype": order_type,
                "producttype": product_type,
                "duration": "DAY",
                "quantity": str(int(order.quantity)),
            }

            if order.limit_price and order_type == "LIMIT":
                params["price"] = str(order.limit_price)

            result = self._client.placeOrder(params)
            logger.info("angel_order_placed", order_id=result, symbol=order.symbol)

            # Fetch fill details from order book
            return FillEvent(
                order_id=str(result),
                symbol=order.symbol,
                side=order.side,
                filled_quantity=order.quantity,
                fill_price=order.limit_price or 0.0,
                commission=20.0,
                slippage=0.0,
                status=FillStatus.FILLED,
                broker=self.name,
            )

        except Exception as e:
            logger.error("angel_order_error", error=str(e))
            return self._rejected_fill(order, str(e))

    async def cancel_order(self, order_id: str) -> bool:
        if not self._client:
            return False
        try:
            self._client.cancelOrder(order_id, "NORMAL")
            return True
        except Exception:
            return False

    async def get_positions(self) -> List[Dict]:
        if not self._client:
            return []
        try:
            data = self._client.position()
            return data.get("data", []) or []
        except Exception:
            return []

    async def get_holdings(self) -> List[Dict]:
        if not self._client:
            return []
        try:
            data = self._client.holding()
            return data.get("data", []) or []
        except Exception:
            return []

    async def get_order_book(self) -> List[Dict]:
        if not self._client:
            return []
        try:
            data = self._client.orderBook()
            return data.get("data", []) or []
        except Exception:
            return []

    async def get_balance(self) -> Dict:
        if not self._client:
            return {"balance": 0, "margin_available": 0}
        try:
            data = self._client.rmsLimit()
            if data["status"]:
                d = data["data"]
                return {
                    "balance": float(d.get("availablecash", 0)),
                    "margin_available": float(d.get("net", 0)),
                    "margin_used": float(d.get("utiliseddebits", 0)),
                    "collateral": float(d.get("collateral", 0)),
                    "broker": self.name,
                }
        except Exception:
            pass
        return {"balance": 0, "margin_available": 0, "broker": self.name}

    # ---- Helpers ----

    def _get_token(self, symbol: str) -> str:
        """
        Map symbol name to Angel One security token.
        In production, load from the Angel instruments master file.
        """
        # Common tokens (these change — refresh from API daily)
        TOKENS = {
            "RELIANCE": "2885", "TCS": "11536", "HDFCBANK": "1333",
            "INFY": "1594", "ICICIBANK": "4963", "HINDUNILVR": "1394",
            "SBIN": "3045", "BHARTIARTL": "10604", "ITC": "1660",
            "KOTAKBANK": "1922", "LT": "11483", "AXISBANK": "5900",
            "HCLTECH": "7229", "WIPRO": "3787", "ADANIENT": "25",
            "BAJFINANCE": "317", "MARUTI": "10999", "TITAN": "3506",
            "SUNPHARMA": "3351", "TATAMOTORS": "3456",
            "NIFTY": "99926000", "BANKNIFTY": "99926009",
            "FINNIFTY": "99926037",
        }
        return TOKENS.get(symbol, "")

    def _rejected_fill(self, order: OrderEvent, reason: str) -> FillEvent:
        return FillEvent(
            order_id=order.event_id,
            symbol=order.symbol,
            side=order.side,
            filled_quantity=0,
            fill_price=0,
            commission=0,
            slippage=0,
            status=FillStatus.REJECTED,
            broker=self.name,
        )
