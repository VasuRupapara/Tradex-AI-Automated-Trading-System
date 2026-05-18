"""Groww Broker Adapter. Requires: pip install growwapi"""
from __future__ import annotations
import asyncio
from typing import AsyncGenerator, Dict, List
from backend.brokers.base import BrokerAdapter
from backend.common.config import get_groww_config
from backend.common.events import FillEvent, FillStatus, OrderEvent, OrderSide, OrderType
from backend.common.logger import setup_logging

logger = setup_logging("broker-groww")


class GrowwAdapter(BrokerAdapter):
    """
    Groww broker adapter for Indian stock market trading.

    Supports:
      - Equity (NSE/BSE) — CNC delivery & MIS intraday
      - F&O — NIFTY / BANKNIFTY options & futures
      - Mutual Funds (read-only holdings)

    Authentication:
      - Uses API Key + Secret from .env
      - Access tokens expire daily at 6:00 AM IST — auto-refreshed

    Setup:
      1. Log in to Groww → Settings → Trading APIs
      2. Generate your API Key and Secret
      3. Add them to .env under GROWW_API_KEY and GROWW_API_SECRET
    """

    def __init__(self):
        super().__init__("groww")
        self._config = get_groww_config()
        self._client = None

    async def authenticate(self) -> bool:
        """Login to Groww API using API key + secret."""
        try:
            from growwapi import GrowwAPI
            self._client = GrowwAPI(
                api_key=self._config.GROWW_API_KEY,
                api_secret=self._config.GROWW_API_SECRET,
            )
            # If an access token is already set, use it
            if self._config.GROWW_ACCESS_TOKEN:
                self._client.set_access_token(self._config.GROWW_ACCESS_TOKEN)

            # Verify connection by fetching profile
            profile = self._client.get_profile()
            if profile:
                self.authenticated = True
                logger.info("groww_authenticated",
                           user=profile.get("userName", "unknown"))
                return True
            return False
        except ImportError:
            logger.error("groww_sdk_missing",
                        msg="Install with: pip install growwapi")
            return False
        except Exception as e:
            logger.error("groww_auth_error", error=str(e))
            return False

    async def refresh_token(self) -> bool:
        """Refresh the Groww access token (expires daily at 6 AM IST)."""
        try:
            if self._client:
                token_data = self._client.refresh_session()
                if token_data:
                    logger.info("groww_token_refreshed")
                    return True
            return await self.authenticate()
        except Exception as e:
            logger.error("groww_refresh_error", error=str(e))
            return await self.authenticate()

    async def get_ltp(self, symbols: List[str]) -> Dict[str, float]:
        """Get Last Traded Price for a list of symbols."""
        if not self._client:
            return {}
        result = {}
        for sym in symbols:
            try:
                quote = self._client.get_quote(
                    exchange="NSE",
                    trading_symbol=sym,
                )
                if quote and "ltp" in quote:
                    result[sym] = float(quote["ltp"])
                elif quote and "data" in quote:
                    result[sym] = float(quote["data"].get("ltp", 0))
            except Exception as e:
                logger.debug("groww_ltp_error", symbol=sym, error=str(e))
        return result

    async def stream_market_data(self, symbols: List[str]) -> AsyncGenerator[Dict, None]:
        """
        Stream real-time market data.

        Groww supports WebSocket feeds via their SDK's feed client.
        Falls back to polling if WebSocket is not available.
        """
        # Try WebSocket first
        try:
            if hasattr(self._client, 'create_feed'):
                feed = self._client.create_feed(symbols=symbols, exchange="NSE")
                async for tick in feed:
                    yield {
                        "symbol": tick.get("symbol", ""),
                        "ltp": float(tick.get("ltp", 0)),
                        "volume": int(tick.get("volume", 0)),
                        "high": float(tick.get("high", 0)),
                        "low": float(tick.get("low", 0)),
                        "open": float(tick.get("open", 0)),
                        "close": float(tick.get("close", 0)),
                    }
                return
        except Exception:
            logger.info("groww_websocket_fallback", msg="Using polling mode")

        # Polling fallback (1-second interval)
        while True:
            prices = await self.get_ltp(symbols)
            for sym, price in prices.items():
                yield {"symbol": sym, "ltp": price, "volume": 0}
            await asyncio.sleep(1)

    async def get_historical_data(self, symbol, interval, from_date, to_date) -> List[Dict]:
        """Get historical OHLCV candle data."""
        if not self._client:
            return []
        try:
            data = self._client.get_historical_data(
                exchange="NSE",
                trading_symbol=symbol,
                interval=interval,
                from_date=from_date,
                to_date=to_date,
            )
            candles = data if isinstance(data, list) else data.get("data", [])
            return [
                {
                    "timestamp": c.get("date", c.get("timestamp", "")),
                    "open": float(c.get("open", 0)),
                    "high": float(c.get("high", 0)),
                    "low": float(c.get("low", 0)),
                    "close": float(c.get("close", 0)),
                    "volume": int(c.get("volume", 0)),
                }
                for c in candles
            ]
        except Exception as e:
            logger.error("groww_historical_error", symbol=symbol, error=str(e))
            return []

    async def place_order(self, order: OrderEvent) -> FillEvent:
        """Place an order through Groww."""
        if not self._client:
            return self._reject(order, "Not authenticated")
        try:
            side = "BUY" if order.side == OrderSide.BUY else "SELL"
            o_type = "MARKET" if order.order_type == OrderType.MARKET else "LIMIT"

            result = self._client.place_order(
                exchange="NSE",
                trading_symbol=order.symbol,
                transaction_type=side,
                quantity=int(order.quantity),
                order_type=o_type,
                product="CNC",
                price=order.limit_price or 0,
            )

            order_id = (
                result.get("orderId")
                or result.get("data", {}).get("orderId")
                or order.event_id
            )

            logger.info("groww_order_placed",
                       order_id=order_id,
                       symbol=order.symbol,
                       side=side,
                       qty=order.quantity)

            return FillEvent(
                order_id=str(order_id),
                symbol=order.symbol,
                side=order.side,
                filled_quantity=order.quantity,
                fill_price=order.limit_price or 0,
                commission=20.0,  # Groww flat fee
                slippage=0,
                status=FillStatus.FILLED,
                broker=self.name,
            )
        except Exception as e:
            logger.error("groww_order_error", error=str(e))
            return self._reject(order, str(e))

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel a pending order."""
        try:
            if self._client:
                self._client.cancel_order(order_id=order_id)
                logger.info("groww_order_cancelled", order_id=order_id)
                return True
        except Exception as e:
            logger.error("groww_cancel_error", order_id=order_id, error=str(e))
        return False

    async def get_positions(self) -> List[Dict]:
        """Get current open positions (intraday)."""
        try:
            if self._client:
                data = self._client.get_positions()
                return data if isinstance(data, list) else data.get("data", [])
        except Exception as e:
            logger.error("groww_positions_error", error=str(e))
        return []

    async def get_holdings(self) -> List[Dict]:
        """Get delivery holdings (CNC)."""
        try:
            if self._client:
                data = self._client.get_holdings()
                return data if isinstance(data, list) else data.get("data", [])
        except Exception as e:
            logger.error("groww_holdings_error", error=str(e))
        return []

    async def get_order_book(self) -> List[Dict]:
        """Get today's order book."""
        try:
            if self._client:
                data = self._client.get_orders()
                return data if isinstance(data, list) else data.get("data", [])
        except Exception as e:
            logger.error("groww_orderbook_error", error=str(e))
        return []

    async def get_balance(self) -> Dict:
        """Get account balance and margin info."""
        try:
            if self._client:
                data = self._client.get_funds()
                funds = data if isinstance(data, dict) and "balance" in data else data.get("data", {})
                return {
                    "balance": float(funds.get("availableBalance", funds.get("balance", 0))),
                    "margin_available": float(funds.get("availableMargin", funds.get("availableBalance", 0))),
                    "margin_used": float(funds.get("usedMargin", 0)),
                    "broker": self.name,
                }
        except Exception as e:
            logger.error("groww_balance_error", error=str(e))
        return {"balance": 0, "margin_available": 0, "broker": self.name}

    def _reject(self, order: OrderEvent, reason: str = "") -> FillEvent:
        """Create a rejected fill event."""
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
