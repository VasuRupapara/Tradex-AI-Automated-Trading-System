"""
Centralized Configuration for Indian Automated Trading System.

Loads broker credentials, trading parameters, and risk limits
from environment variables / .env file.
"""

from __future__ import annotations

from functools import lru_cache
from typing import List, Optional

from pydantic_settings import BaseSettings


# ============================================
# Database Config
# ============================================

class DatabaseConfig(BaseSettings):
    """QuestDB connection configuration."""
    QUESTDB_HOST: str = "localhost"
    QUESTDB_PORT: int = 8812
    QUESTDB_HTTP_PORT: int = 9000
    QUESTDB_USER: str = "admin"
    QUESTDB_PASSWORD: str = "quest"

    @property
    def connection_string(self) -> str:
        return (
            f"postgresql://{self.QUESTDB_USER}:{self.QUESTDB_PASSWORD}"
            f"@{self.QUESTDB_HOST}:{self.QUESTDB_PORT}/qdb"
        )

    class Config:
        env_file = ".env"
        extra = "ignore"


# ============================================
# Broker Selection
# ============================================

class BrokerSelectionConfig(BaseSettings):
    """Which broker and trading mode to use."""
    BROKER_NAME: str = "angel_one"    # angel_one | zerodha | fyers | upstox | dhan | groww
    TRADING_MODE: str = "paper"       # paper | live

    class Config:
        env_file = ".env"
        extra = "ignore"


# ============================================
# Indian Broker Configs
# ============================================

class AngelOneConfig(BaseSettings):
    """Angel One SmartAPI credentials."""
    ANGEL_API_KEY: str = ""
    ANGEL_CLIENT_ID: str = ""
    ANGEL_PASSWORD: str = ""
    ANGEL_TOTP_SECRET: str = ""

    class Config:
        env_file = ".env"
        extra = "ignore"


class ZerodhaConfig(BaseSettings):
    """Zerodha Kite Connect credentials."""
    ZERODHA_API_KEY: str = ""
    ZERODHA_API_SECRET: str = ""
    ZERODHA_ACCESS_TOKEN: str = ""
    ZERODHA_USER_ID: str = ""

    class Config:
        env_file = ".env"
        extra = "ignore"


class FyersConfig(BaseSettings):
    """Fyers API v3 credentials."""
    FYERS_APP_ID: str = ""
    FYERS_SECRET_KEY: str = ""
    FYERS_ACCESS_TOKEN: str = ""
    FYERS_REDIRECT_URL: str = "http://localhost:8000/fyers/callback"

    class Config:
        env_file = ".env"
        extra = "ignore"


class UpstoxConfig(BaseSettings):
    """Upstox API v2 credentials."""
    UPSTOX_API_KEY: str = ""
    UPSTOX_API_SECRET: str = ""
    UPSTOX_ACCESS_TOKEN: str = ""
    UPSTOX_REDIRECT_URI: str = "http://localhost:8000/upstox/callback"

    class Config:
        env_file = ".env"
        extra = "ignore"


class DhanConfig(BaseSettings):
    """Dhan HQ credentials."""
    DHAN_CLIENT_ID: str = ""
    DHAN_ACCESS_TOKEN: str = ""

    class Config:
        env_file = ".env"
        extra = "ignore"


class GrowwConfig(BaseSettings):
    """Groww Trading API credentials."""
    GROWW_API_KEY: str = ""
    GROWW_API_SECRET: str = ""
    GROWW_ACCESS_TOKEN: str = ""

    class Config:
        env_file = ".env"
        extra = "ignore"


# ============================================
# Capital & Trading Config
# ============================================

class TradingConfig(BaseSettings):
    """Capital allocation and trading parameters."""
    TOTAL_CAPITAL: float = 100000.0
    EQUITY_CAPITAL_PERCENT: int = 70
    FNO_CAPITAL_PERCENT: int = 30
    EQUITY_SYMBOLS: str = "RELIANCE,TCS,HDFCBANK,INFY,ICICIBANK,SBIN,BHARTIARTL,ITC,HINDUNILVR,KOTAKBANK"
    FNO_SYMBOLS: str = "NIFTY,BANKNIFTY,FINNIFTY"
    CRYPTO_SYMBOLS: str = "BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT,BNBUSDT,ADAUSDT,DOGEUSDT,DOTUSDT,MATICUSDT,AVAXUSDT"

    @property
    def equity_capital(self) -> float:
        return self.TOTAL_CAPITAL * self.EQUITY_CAPITAL_PERCENT / 100

    @property
    def fno_capital(self) -> float:
        return self.TOTAL_CAPITAL * self.FNO_CAPITAL_PERCENT / 100

    @property
    def equity_symbols_list(self) -> List[str]:
        return [s.strip() for s in self.EQUITY_SYMBOLS.split(",") if s.strip()]

    @property
    def fno_symbols_list(self) -> List[str]:
        return [s.strip() for s in self.FNO_SYMBOLS.split(",") if s.strip()]

    @property
    def crypto_symbols_list(self) -> List[str]:
        return [s.strip() for s in self.CRYPTO_SYMBOLS.split(",") if s.strip()]

    class Config:
        env_file = ".env"
        extra = "ignore"


# ============================================
# Risk Config
# ============================================

class RiskConfig(BaseSettings):
    """Risk management configuration for Indian market."""
    MAX_POSITION_SIZE: float = 50000.0
    MAX_DRAWDOWN_PERCENT: float = 5.0
    MAX_DAILY_LOSS: float = 5000.0
    MAX_ORDER_FREQUENCY_PER_SECOND: int = 10
    KILL_SWITCH_ENABLED: bool = True
    INTRADAY_SQUARE_OFF_TIME: str = "15:15"

    class Config:
        env_file = ".env"
        extra = "ignore"


# ============================================
# App Config
# ============================================

class AppConfig(BaseSettings):
    """Main application configuration."""
    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"
    DEBUG: bool = True
    API_GATEWAY_HOST: str = "0.0.0.0"
    API_GATEWAY_PORT: int = 8000
    API_SECRET_KEY: str = "dev-secret-key-change-in-production"

    class Config:
        env_file = ".env"
        extra = "ignore"


# ============================================
# Cached Getters
# ============================================

@lru_cache()
def get_app_config() -> AppConfig:
    return AppConfig()

@lru_cache()
def get_database_config() -> DatabaseConfig:
    return DatabaseConfig()

@lru_cache()
def get_broker_selection() -> BrokerSelectionConfig:
    return BrokerSelectionConfig()

@lru_cache()
def get_angel_config() -> AngelOneConfig:
    return AngelOneConfig()

@lru_cache()
def get_zerodha_config() -> ZerodhaConfig:
    return ZerodhaConfig()

@lru_cache()
def get_fyers_config() -> FyersConfig:
    return FyersConfig()

@lru_cache()
def get_upstox_config() -> UpstoxConfig:
    return UpstoxConfig()

@lru_cache()
def get_dhan_config() -> DhanConfig:
    return DhanConfig()

@lru_cache()
def get_groww_config() -> GrowwConfig:
    return GrowwConfig()

@lru_cache()
def get_trading_config() -> TradingConfig:
    return TradingConfig()

@lru_cache()
def get_risk_config() -> RiskConfig:
    return RiskConfig()

# Keep backward compatibility alias
def get_broker_config():
    return get_broker_selection()
