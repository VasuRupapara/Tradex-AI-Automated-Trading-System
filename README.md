# 🚀 Automated Trading System (ATS)

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)](https://python.org)
[![Flutter](https://img.shields.io/badge/Flutter-3.x-02569B?logo=flutter&logoColor=white)](https://flutter.dev)
[![QuestDB](https://img.shields.io/badge/QuestDB-TimeSeries-D14671?logo=questdb)](https://questdb.io)
[![Docker](https://img.shields.io/badge/Docker-Containerized-2496ED?logo=docker&logoColor=white)](https://docker.com)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

> **Institutional-grade, cross-platform automated trading system** built on microservices architecture with event-driven execution, real-time risk management, and GPU-accelerated charting.

---

## 📐 Architecture

```
Frontend (Flutter) ←── WebSockets ──→ API Gateway ←── gRPC ──→ Microservices
                                           │
                    ┌──────────────────────┼──────────────────────┐
                    │                      │                      │
              Market Data            Strategy Engine        Execution Handler
              Ingestion              (Event-Driven)         (Broker Adapter)
                    │                      │                      │
                    ▼                      ▼                      ▼
               QuestDB              Risk Firewall           Broker APIs
              (Time-Series)         (Pre-Trade Checks)    (Alpaca/IBKR)
```

## 🧩 Core Microservices

| Service | Language | Responsibility |
|---------|----------|---------------|
| `api-gateway` | Python | Unified entry point, auth, routing |
| `market-data` | Python | Real-time tick/bar ingestion from feeds |
| `strategy-engine` | Python | Quantitative strategies, signal generation |
| `risk-management` | Python | Pre-trade limits, drawdown controls, kill switch |
| `execution-handler` | Python | Order routing, broker adapters |

## 🗄️ Tech Stack

- **Backend**: Python 3.11+, gRPC, Protobuf, asyncio
- **Frontend**: Dart/Flutter, BLoC pattern, Cristalyse charting
- **Database**: QuestDB (time-series), Redis (caching)
- **Infrastructure**: Docker, Kubernetes, Prometheus, Grafana
- **Security**: OAuth 2.0, HashiCorp Vault, zero-trust architecture
- **Communication**: gRPC (internal), WebSockets (client-facing)

## 📂 Project Structure

```
Automated-Trading-System/
├── backend/                    # Backend Microservices
│   ├── api-gateway/            # Unified entry point
│   ├── market-data/            # Data ingestion engine
│   ├── strategy-engine/        # Quantitative logic & event loop
│   ├── risk-management/        # Risk firewall
│   ├── execution-handler/      # Order routing & broker adapters
│   ├── common/                 # Shared utilities, events, models
│   └── proto/                  # Protobuf service definitions
├── frontend/                   # Flutter cross-platform app
├── infrastructure/             # DevOps & observability
│   ├── docker/                 # Dockerfiles per service
│   ├── k8s/                    # Kubernetes manifests
│   ├── prometheus/             # Metrics scraping config
│   └── grafana/                # Dashboard definitions
├── database/                   # QuestDB schemas & migrations
├── scripts/                    # Automation & research
├── tests/                      # Integration & E2E tests
├── docs/                       # Architecture documentation
└── BluePrint/                  # Original design documents
```

## 🚀 Quick Start

### Prerequisites
- Python 3.11+
- Docker & Docker Compose
- Flutter SDK 3.x (for frontend)

### 1. Clone & Setup
```bash
git clone <repo-url>
cd Automated-Trading-System
python -m venv venv
venv\Scripts\activate          # Windows
pip install -r requirements.txt
```

### 2. Start Infrastructure
```bash
docker-compose up -d           # QuestDB, Prometheus, Grafana
```

### 3. Run Backend Services
```bash
python -m backend.api_gateway.src.main
python -m backend.market_data.src.main
python -m backend.strategy_engine.src.main
python -m backend.risk_management.src.main
python -m backend.execution_handler.src.main
```

### 4. Run Frontend
```bash
cd frontend
flutter pub get
flutter run -d windows         # or -d chrome, -d android
```

## 📊 Event Flow

```
MarketDataEvent → Strategy Engine → SignalEvent → Risk Manager → OrderEvent → Execution → FillEvent → Portfolio
```

## 📄 License

This project is licensed under the MIT License - see [LICENSE](LICENSE) file.
