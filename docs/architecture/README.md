# Architecture Documentation

This directory contains detailed architecture documentation for the Automated Trading System.

## Documents

| Document | Description |
|----------|-------------|
| [System Designs](../../Design/system_designs.md) | Mermaid diagrams: architecture, event loop, infrastructure |
| [System Structure](../../Design/System%20Structure.txt) | Folder structure and technology mapping |

## Key Architecture Decisions

### 1. Microservices over Monolith
- **Decision**: Distributed microservices architecture
- **Rationale**: Fault isolation, independent deployment, targeted scaling
- **Trade-off**: Higher engineering complexity, eventual consistency

### 2. Event-Driven Execution
- **Decision**: Event queue with sequential processing
- **Rationale**: Eliminates look-ahead bias, identical backtest/live path
- **Trade-off**: Slower than vectorized backtesting

### 3. QuestDB over PostgreSQL/InfluxDB
- **Decision**: QuestDB as primary time-series database
- **Rationale**: 11M+ rows/sec ingestion, 1.56ms LATEST ON queries
- **Trade-off**: Less mature ecosystem than PostgreSQL

### 4. gRPC + WebSockets
- **Decision**: gRPC for inter-service, WebSockets for client
- **Rationale**: 10x faster than REST for dense data; full-duplex for UI
- **Trade-off**: gRPC lacks native browser support

### 5. Flutter for Frontend
- **Decision**: Single codebase cross-platform UI
- **Rationale**: 60fps GPU-accelerated rendering, desktop + mobile
- **Trade-off**: Dart is less common than JS/TS
