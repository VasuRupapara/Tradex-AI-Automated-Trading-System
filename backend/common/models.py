"""
Data Models for the Automated Trading System.

Pydantic models for API request/response validation and 
internal data transfer objects (DTOs).
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ============================================
# Portfolio Models
# ============================================

class PositionModel(BaseModel):
    """Represents a single position in the portfolio."""
    symbol: str
    quantity: float
    avg_entry_price: float
    current_price: float = 0.0
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    market_value: float = 0.0
    side: str = "long"  # "long" or "short"
    opened_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def total_pnl(self) -> float:
        """Total P&L including both realized and unrealized."""
        return self.unrealized_pnl + self.realized_pnl


class PortfolioModel(BaseModel):
    """Complete portfolio state snapshot."""
    total_equity: float = 0.0
    cash: float = 0.0
    total_unrealized_pnl: float = 0.0
    total_realized_pnl: float = 0.0
    daily_pnl: float = 0.0
    drawdown_percent: float = 0.0
    peak_equity: float = 0.0
    positions: List[PositionModel] = []
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# ============================================
# Market Data Models
# ============================================

class TickModel(BaseModel):
    """Single market tick data point."""
    symbol: str
    price: float
    volume: float
    tick_type: str = "trade"  # "trade", "bid", "ask"
    exchange: str = ""
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class BarModel(BaseModel):
    """OHLCV bar data (candlestick)."""
    symbol: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    timeframe: str = "1m"  # "1m", "5m", "1h", "1d"
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# ============================================
# Strategy Models
# ============================================

class StrategyStatus(str, Enum):
    """Strategy operational status."""
    ACTIVE = "active"
    PAUSED = "paused"
    ERROR = "error"
    BACKTESTING = "backtesting"


class StrategyConfigModel(BaseModel):
    """Configuration for a trading strategy."""
    strategy_name: str
    enabled: bool = False
    status: StrategyStatus = StrategyStatus.PAUSED
    parameters: Dict[str, Any] = {}
    symbols: List[str] = []
    description: str = ""
    version: str = "1.0.0"


class StrategyPerformance(BaseModel):
    """Performance metrics for a strategy."""
    strategy_name: str
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    total_pnl: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    avg_trade_pnl: float = 0.0


# ============================================
# Risk Models
# ============================================

class RiskLimitsModel(BaseModel):
    """Risk management limits configuration."""
    max_position_size: float = 10000.0
    max_drawdown_percent: float = 5.0
    max_daily_loss: float = 1000.0
    max_order_frequency_per_second: int = 10
    max_single_order_value: float = 5000.0
    max_portfolio_leverage: float = 1.0
    kill_switch_enabled: bool = True


class RiskCheckResult(BaseModel):
    """Result of a pre-trade risk check."""
    approved: bool
    reason: str = ""
    adjusted_quantity: Optional[float] = None
    risk_score: float = 0.0  # 0.0 (safe) to 1.0 (critical)


# ============================================
# Order & Execution Models
# ============================================

class OrderRequestModel(BaseModel):
    """API request to place an order."""
    symbol: str
    side: str  # "buy" or "sell"
    order_type: str = "market"  # "market", "limit", "stop", "stop_limit"
    quantity: float
    limit_price: Optional[float] = None
    stop_price: Optional[float] = None
    broker: str = "mock"  # "alpaca", "ibkr", "mock"
    strategy_name: str = "manual"


class OrderResponseModel(BaseModel):
    """API response after order submission."""
    order_id: str
    symbol: str
    side: str
    order_type: str
    quantity: float
    status: str  # "submitted", "filled", "rejected"
    fill_price: Optional[float] = None
    commission: float = 0.0
    message: str = ""
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# ============================================
# System Models
# ============================================

class SystemHealthModel(BaseModel):
    """System health status report."""
    status: str = "healthy"  # "healthy", "degraded", "critical"
    services: Dict[str, str] = {}
    uptime_seconds: float = 0.0
    cpu_usage_percent: float = 0.0
    memory_usage_percent: float = 0.0
    active_connections: int = 0
    kill_switch_active: bool = False
    timestamp: datetime = Field(default_factory=datetime.utcnow)
