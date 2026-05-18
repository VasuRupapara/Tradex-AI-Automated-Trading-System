"""
Indian Market Event Models & Instruments.

Extends the base event system with NSE/BSE-specific fields:
exchanges, instrument types, lot sizes, open interest, and option greeks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, date
from enum import Enum, auto
from typing import Dict, List, Optional
import pytz

IST = pytz.timezone("Asia/Kolkata")


# ============================================
# Indian Market Enums
# ============================================

class Exchange(Enum):
    NSE = "NSE"
    BSE = "BSE"
    NFO = "NFO"     # NSE Futures & Options
    BFO = "BFO"     # BSE F&O
    MCX = "MCX"     # Commodities
    CDS = "CDS"     # Currency Derivatives


class InstrumentType(Enum):
    EQUITY = "EQ"
    FUTURES = "FUT"
    CALL_OPTION = "CE"
    PUT_OPTION = "PE"
    INDEX = "INDEX"
    ETF = "ETF"


class ProductType(Enum):
    """Indian broker product types."""
    CNC = "CNC"           # Cash & Carry (delivery)
    MIS = "MIS"           # Margin Intraday Square-off
    NRML = "NRML"         # Normal (F&O carry forward)
    INTRADAY = "INTRADAY" # Alias for MIS


# ============================================
# Instrument Definition
# ============================================

@dataclass
class Instrument:
    """Represents a tradeable instrument on Indian exchanges."""
    symbol: str                           # "RELIANCE", "NIFTY25MAY24000CE"
    exchange: Exchange = Exchange.NSE
    instrument_type: InstrumentType = InstrumentType.EQUITY
    lot_size: int = 1                     # 1 for equity, 25/50 for F&O
    tick_size: float = 0.05               # Min price movement
    expiry: Optional[str] = None          # "2025-05-29" for F&O
    strike: Optional[float] = None        # 24000.0 for options
    token: str = ""                       # Exchange token / security ID
    isin: Optional[str] = None            # INE002A01018
    name: str = ""                        # "Reliance Industries Ltd"


# ============================================
# Market Schedule
# ============================================

class MarketSchedule:
    """NSE/BSE trading hours (IST)."""
    PRE_OPEN_START = time(9, 0)
    PRE_OPEN_END = time(9, 8)
    MARKET_OPEN = time(9, 15)
    MARKET_CLOSE = time(15, 30)
    INTRADAY_CUTOFF = time(15, 15)    # Square off MIS by 3:15 PM
    AFTER_HOURS_END = time(16, 0)

    # NSE Holidays 2025 (partial list — update annually)
    HOLIDAYS = [
        date(2025, 1, 26),   # Republic Day
        date(2025, 2, 26),   # Maha Shivaratri
        date(2025, 3, 14),   # Holi
        date(2025, 3, 31),   # Id-Ul-Fitr
        date(2025, 4, 10),   # Shri Ram Navami
        date(2025, 4, 14),   # Dr. Ambedkar Jayanti
        date(2025, 4, 18),   # Good Friday
        date(2025, 5, 1),    # Maharashtra Day
        date(2025, 8, 15),   # Independence Day
        date(2025, 8, 27),   # Ganesh Chaturthi
        date(2025, 10, 2),   # Mahatma Gandhi Jayanti
        date(2025, 10, 21),  # Diwali (Laxmi Puja)
        date(2025, 10, 22),  # Diwali Balipratipada
        date(2025, 11, 5),   # Guru Nanak Jayanti
        date(2025, 12, 25),  # Christmas
    ]

    @classmethod
    def is_market_open(cls) -> bool:
        now = datetime.now(IST)
        today = now.date()
        if today.weekday() >= 5:
            return False
        if today in cls.HOLIDAYS:
            return False
        return cls.MARKET_OPEN <= now.time() <= cls.MARKET_CLOSE

    @classmethod
    def is_intraday_cutoff(cls) -> bool:
        now = datetime.now(IST)
        return now.time() >= cls.INTRADAY_CUTOFF

    @classmethod
    def seconds_to_close(cls) -> int:
        now = datetime.now(IST)
        close_dt = now.replace(
            hour=cls.MARKET_CLOSE.hour,
            minute=cls.MARKET_CLOSE.minute,
            second=0
        )
        return max(0, int((close_dt - now).total_seconds()))

    @classmethod
    def market_status(cls) -> str:
        if cls.is_market_open():
            return "OPEN"
        now = datetime.now(IST)
        if now.time() < cls.MARKET_OPEN:
            return "PRE_MARKET"
        return "CLOSED"


# ============================================
# Indian Brokerage Calculator
# ============================================

class BrokerageCalculator:
    """
    Calculates brokerage, STT, stamp duty, GST, and SEBI charges.
    Based on standard Indian discount broker rates.
    """

    # Equity Delivery
    EQUITY_DELIVERY_BROKERAGE = 0.0     # ₹0 on most discount brokers
    EQUITY_DELIVERY_STT = 0.001         # 0.1% on buy + sell

    # Equity Intraday
    EQUITY_INTRADAY_BROKERAGE = 20.0    # ₹20 per order (flat)
    EQUITY_INTRADAY_STT = 0.00025       # 0.025% on sell side

    # F&O Futures
    FUTURES_BROKERAGE = 20.0            # ₹20 per order
    FUTURES_STT = 0.0001                # 0.01% on sell side

    # F&O Options
    OPTIONS_BROKERAGE = 20.0            # ₹20 per order
    OPTIONS_STT = 0.0005                # 0.05% on sell (premium)

    # Common charges
    EXCHANGE_TXN_CHARGE = 0.0000345     # NSE transaction charge
    GST_RATE = 0.18                      # 18% GST on brokerage
    SEBI_CHARGE = 0.000001               # ₹10 per crore
    STAMP_DUTY = 0.00003                 # ₹300 per crore (buy side)

    @classmethod
    def calculate(
        cls,
        instrument_type: InstrumentType,
        product_type: ProductType,
        side: str,
        quantity: float,
        price: float,
    ) -> Dict[str, float]:
        """Calculate all charges for a trade."""
        turnover = quantity * price

        if instrument_type == InstrumentType.EQUITY:
            if product_type == ProductType.CNC:
                brokerage = cls.EQUITY_DELIVERY_BROKERAGE
                stt = turnover * cls.EQUITY_DELIVERY_STT
            else:
                brokerage = min(cls.EQUITY_INTRADAY_BROKERAGE, turnover * 0.0003)
                stt = turnover * cls.EQUITY_INTRADAY_STT if side == "SELL" else 0
        elif instrument_type == InstrumentType.FUTURES:
            brokerage = cls.FUTURES_BROKERAGE
            stt = turnover * cls.FUTURES_STT if side == "SELL" else 0
        elif instrument_type in (InstrumentType.CALL_OPTION, InstrumentType.PUT_OPTION):
            brokerage = cls.OPTIONS_BROKERAGE
            stt = turnover * cls.OPTIONS_STT if side == "SELL" else 0
        else:
            brokerage = 0
            stt = 0

        exchange_txn = turnover * cls.EXCHANGE_TXN_CHARGE
        gst = (brokerage + exchange_txn) * cls.GST_RATE
        sebi = turnover * cls.SEBI_CHARGE
        stamp = turnover * cls.STAMP_DUTY if side == "BUY" else 0

        total = brokerage + stt + exchange_txn + gst + sebi + stamp

        return {
            "brokerage": round(brokerage, 2),
            "stt": round(stt, 2),
            "exchange_txn": round(exchange_txn, 2),
            "gst": round(gst, 2),
            "sebi": round(sebi, 2),
            "stamp_duty": round(stamp, 2),
            "total_charges": round(total, 2),
        }


# ============================================
# Default Watchlists
# ============================================

NIFTY_50_TOP = [
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK",
    "HINDUNILVR", "SBIN", "BHARTIARTL", "ITC", "KOTAKBANK",
    "LT", "AXISBANK", "HCLTECH", "WIPRO", "ADANIENT",
    "BAJFINANCE", "MARUTI", "TITAN", "SUNPHARMA", "TATAMOTORS",
]

FNO_INDICES = ["NIFTY", "BANKNIFTY", "FINNIFTY"]

EQUITY_BASE_PRICES = {
    "RELIANCE": 2850.0, "TCS": 3920.0, "HDFCBANK": 1620.0,
    "INFY": 1540.0, "ICICIBANK": 1280.0, "HINDUNILVR": 2380.0,
    "SBIN": 820.0, "BHARTIARTL": 1680.0, "ITC": 435.0,
    "KOTAKBANK": 1920.0, "LT": 3450.0, "AXISBANK": 1150.0,
    "HCLTECH": 1680.0, "WIPRO": 460.0, "ADANIENT": 2950.0,
    "BAJFINANCE": 8200.0, "MARUTI": 12500.0, "TITAN": 3350.0,
    "SUNPHARMA": 1780.0, "TATAMOTORS": 720.0,
}

INDEX_BASE_PRICES = {
    "NIFTY": 24200.0,
    "BANKNIFTY": 52100.0,
    "FINNIFTY": 23800.0,
}

# ============================================
# Crypto Watchlist & Base Prices (USDT pairs)
# ============================================

CRYPTO_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT",
    "ADAUSDT", "DOGEUSDT", "DOTUSDT", "MATICUSDT", "AVAXUSDT",
]

CRYPTO_BASE_PRICES = {
    "BTCUSDT": 104500.0,
    "ETHUSDT": 2550.0,
    "SOLUSDT": 172.0,
    "XRPUSDT": 2.45,
    "BNBUSDT": 655.0,
    "ADAUSDT": 0.78,
    "DOGEUSDT": 0.225,
    "DOTUSDT": 4.80,
    "MATICUSDT": 0.42,
    "AVAXUSDT": 24.50,
}
