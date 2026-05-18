"""
Broker Registry — Auto-discovers and loads the correct broker
adapter based on BROKER_NAME and TRADING_MODE in .env

Usage:
    broker = BrokerRegistry.create()
    # Returns PaperTradingAdapter(AngelOneAdapter()) in paper mode
    # Returns AngelOneAdapter() directly in live mode
"""

from __future__ import annotations
from backend.common.config import get_broker_selection
from backend.common.logger import setup_logging

logger = setup_logging("broker-registry")


class BrokerRegistry:
    """Factory that builds the correct broker adapter."""

    @classmethod
    def create(cls):
        """
        Create a broker adapter based on .env settings.

        BROKER_NAME selects the real broker.
        TRADING_MODE wraps it in PaperTradingAdapter if 'paper'.
        """
        config = get_broker_selection()
        broker_name = config.BROKER_NAME.lower().strip()
        trading_mode = config.TRADING_MODE.lower().strip()

        # Import adapters lazily to avoid import errors for uninstalled SDKs
        real_broker = cls._create_real_broker(broker_name)

        if trading_mode == "paper":
            from backend.brokers.paper_trading import PaperTradingAdapter
            broker = PaperTradingAdapter(real_broker)
            logger.info("broker_created",
                       mode="PAPER",
                       underlying=broker_name,
                       name=broker.name)
        else:
            broker = real_broker
            logger.info("broker_created",
                       mode="LIVE ⚠️",
                       name=broker.name)

        return broker

    @classmethod
    def _create_real_broker(cls, broker_name: str):
        if broker_name == "angel_one":
            from backend.brokers.angel_one import AngelOneAdapter
            return AngelOneAdapter()
        elif broker_name == "zerodha":
            from backend.brokers.zerodha import ZerodhaAdapter
            return ZerodhaAdapter()
        elif broker_name == "fyers":
            from backend.brokers.fyers import FyersAdapter
            return FyersAdapter()
        elif broker_name == "upstox":
            from backend.brokers.upstox import UpstoxAdapter
            return UpstoxAdapter()
        elif broker_name == "dhan":
            from backend.brokers.dhan import DhanAdapter
            return DhanAdapter()
        elif broker_name == "groww":
            from backend.brokers.groww import GrowwAdapter
            return GrowwAdapter()
        else:
            raise ValueError(
                f"Unknown broker: '{broker_name}'. "
                f"Valid options: angel_one, zerodha, fyers, upstox, dhan, groww"
            )

    @classmethod
    def available_brokers(cls):
        return ["angel_one", "zerodha", "fyers", "upstox", "dhan", "groww"]
