"""
API Gateway - Main Application Entry Point

The API Gateway serves as the unified entry point for the entire
Automated Trading System. It handles:
  - REST API endpoints for client communication
  - WebSocket connections for real-time data streaming
  - Authentication and authorization
  - Request routing to backend microservices
  - Rate limiting and request validation

Reference: Blueprint Section "Inter-Service Communication"
"""

from __future__ import annotations

import asyncio
import os
import sys
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Dict, List

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import Counter, Histogram, generate_latest
from starlette.responses import Response

from backend.common.config import get_app_config
from backend.common.logger import setup_logging
from backend.common.models import (
    SystemHealthModel,
    PortfolioModel,
    OrderRequestModel,
    OrderResponseModel,
    StrategyConfigModel,
    RiskLimitsModel,
)

# ============================================
# Configuration & Logging
# ============================================

config = get_app_config()
logger = setup_logging("api-gateway", config.LOG_LEVEL)

# ============================================
# Prometheus Metrics
# ============================================

REQUEST_COUNT = Counter(
    "api_gateway_requests_total",
    "Total API requests",
    ["method", "endpoint", "status"],
)
REQUEST_LATENCY = Histogram(
    "api_gateway_request_duration_seconds",
    "Request latency in seconds",
    ["method", "endpoint"],
)
WEBSOCKET_CONNECTIONS = Counter(
    "api_gateway_websocket_connections_total",
    "Total WebSocket connections",
)

# ============================================
# WebSocket Connection Manager
# ============================================

class ConnectionManager:
    """Manages WebSocket connections for real-time data streaming."""

    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        WEBSOCKET_CONNECTIONS.inc()
        logger.info("websocket_connected",
                     total_connections=len(self.active_connections))

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)
        logger.info("websocket_disconnected",
                     total_connections=len(self.active_connections))

    async def broadcast(self, message: dict):
        """Broadcast message to all connected WebSocket clients."""
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                pass  # Connection will be cleaned up on next operation

    async def send_to(self, websocket: WebSocket, message: dict):
        """Send a message to a specific WebSocket client."""
        await websocket.send_json(message)


ws_manager = ConnectionManager()

# ============================================
# Application Lifecycle
# ============================================

start_time = datetime.utcnow()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown lifecycle."""
    logger.info("api_gateway_starting",
                 host=config.API_GATEWAY_HOST,
                 port=config.API_GATEWAY_PORT)
    yield
    logger.info("api_gateway_shutting_down")


# ============================================
# FastAPI Application
# ============================================

app = FastAPI(
    title="Automated Trading System - API Gateway",
    description="Unified entry point for the institutional-grade ATS",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================
# Health & Metrics Endpoints
# ============================================

@app.get("/health", response_model=SystemHealthModel, tags=["System"])
async def health_check():
    """System health check endpoint."""
    uptime = (datetime.utcnow() - start_time).total_seconds()
    return SystemHealthModel(
        status="healthy",
        services={
            "api-gateway": "running",
            "market-data": "pending",
            "strategy-engine": "pending",
            "risk-management": "pending",
            "execution-handler": "pending",
        },
        uptime_seconds=uptime,
        active_connections=len(ws_manager.active_connections),
    )


@app.get("/metrics", tags=["System"])
async def prometheus_metrics():
    """Prometheus metrics endpoint for scraping."""
    return Response(
        content=generate_latest(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


@app.post("/api/v1/system/restart", tags=["System"])
async def restart_system():
    """
    Restart the entire trading engine (Hot Reload).
    Useful after saving configuration changes via the UI.
    """
    logger.warning("System restart requested via API. Rebooting engine...")
    
    # Broadcast to all websocket clients that we are restarting
    await ws_manager.broadcast({
        "type": "SYSTEM_MESSAGE", 
        "data": "Rebooting Trading Engine with new settings..."
    })
    
    def _restart():
        # Exit the process. The outer batch file/process manager will restart it.
        os._exit(0)
        
    # Schedule restart slightly in the future to allow the HTTP response to return to Flutter
    asyncio.get_event_loop().call_later(0.5, _restart)
    
    return {"status": "success", "message": "Engine is restarting..."}


# ============================================
# Portfolio Endpoints
# ============================================

@app.get("/api/v1/portfolio", response_model=PortfolioModel, tags=["Portfolio"])
async def get_portfolio():
    """Get current portfolio state and positions."""
    # TODO: Connect to portfolio service via gRPC
    return PortfolioModel(
        total_equity=100000.0,
        cash=100000.0,
        positions=[],
    )


# ============================================
# Order Endpoints
# ============================================

@app.post("/api/v1/orders", response_model=OrderResponseModel, tags=["Orders"])
async def submit_order(order: OrderRequestModel):
    """
    Submit a trading order.
    
    The order flows through: Risk Manager → Execution Handler → Broker
    """
    logger.info("order_submitted",
                 symbol=order.symbol,
                 side=order.side,
                 quantity=order.quantity)

    # TODO: Forward to risk management service via gRPC
    # TODO: Forward to execution handler via gRPC

    return OrderResponseModel(
        order_id="placeholder",
        symbol=order.symbol,
        side=order.side,
        order_type=order.order_type,
        quantity=order.quantity,
        status="submitted",
        message="Order submitted to risk management pipeline",
    )


# ============================================
# Strategy Endpoints
# ============================================

@app.get("/api/v1/strategies", tags=["Strategies"])
async def list_strategies():
    """List all available trading strategies and their status."""
    # TODO: Connect to strategy engine service via gRPC
    return {"strategies": [], "engine_running": False}


@app.post("/api/v1/strategies/toggle", tags=["Strategies"])
async def toggle_strategy(config: StrategyConfigModel):
    """Enable or disable a specific trading strategy."""
    logger.info("strategy_toggled",
                 strategy=config.strategy_name,
                 enabled=config.enabled)
    # TODO: Forward to strategy engine via gRPC
    return {"message": f"Strategy '{config.strategy_name}' toggled", "config": config}


# ============================================
# Risk Management Endpoints
# ============================================

@app.get("/api/v1/risk/limits", response_model=RiskLimitsModel, tags=["Risk"])
async def get_risk_limits():
    """Get current risk management limits."""
    # TODO: Connect to risk management service via gRPC
    return RiskLimitsModel()


@app.post("/api/v1/risk/kill-switch", tags=["Risk"])
async def activate_kill_switch(activate: bool = True, reason: str = "manual"):
    """
    Activate or deactivate the Global Kill Switch.
    
    This is the ultimate-priority gRPC command that flattens ALL positions
    immediately and halts all trading activity.
    """
    logger.critical("kill_switch_activated" if activate else "kill_switch_deactivated",
                     reason=reason)
    # TODO: Forward to all services via gRPC
    return {
        "active": activate,
        "reason": reason,
        "message": "Kill switch activated - all positions will be flattened"
        if activate else "Kill switch deactivated",
    }


# ============================================
# WebSocket Endpoints
# ============================================

@app.websocket("/ws/market-data")
async def websocket_market_data(websocket: WebSocket):
    """
    WebSocket endpoint for real-time market data streaming.
    
    Maintains a persistent, full-duplex TCP connection allowing
    the server to push real-time data to the client.
    """
    await ws_manager.connect(websocket)
    try:
        while True:
            # Receive subscription messages from client
            data = await websocket.receive_json()
            logger.debug("ws_message_received", data=data)

            # TODO: Subscribe to market data service and stream updates
            await ws_manager.send_to(websocket, {
                "type": "ack",
                "message": "Subscribed to market data",
                "symbols": data.get("symbols", []),
            })
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)


@app.websocket("/ws/portfolio")
async def websocket_portfolio(websocket: WebSocket):
    """WebSocket endpoint for real-time portfolio P&L streaming."""
    await ws_manager.connect(websocket)
    try:
        while True:
            await asyncio.sleep(1)
            # TODO: Stream portfolio updates from portfolio service
            await ws_manager.send_to(websocket, {
                "type": "portfolio_update",
                "timestamp": datetime.utcnow().isoformat(),
            })
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)


# ============================================
# Entry Point
# ============================================

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "backend.api_gateway.src.main:app",
        host=config.API_GATEWAY_HOST,
        port=config.API_GATEWAY_PORT,
        reload=config.DEBUG,
        log_level=config.LOG_LEVEL.lower(),
    )
