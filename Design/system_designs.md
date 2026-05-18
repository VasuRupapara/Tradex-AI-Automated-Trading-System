# Automated Trading System: Diagrams & Designs

Based on the **Comprehensive Blueprint**, the following diagrams illustrate the architectural and operational design of the system.

## 1. High-Level System Architecture
This diagram shows the microservices-based topology, communication protocols, and data flow.

```mermaid
graph TD
    subgraph "Frontend (Flutter App)"
        UI[User Interface]
        State[BLoC/Provider State]
        Chart[Cristalyse Charting]
    end

    subgraph "Backend (Microservices - Kubernetes/Docker)"
        ING[Market Data Ingestion]
        STRAT[Quantitative Strategy Engine]
        RISK[Risk Management Firewall]
        EXEC[Execution Routing Handler]
        TELE[Telemetry Stack - Prometheus/Grafana]
    end

    subgraph "Data Layer"
        QDB[(QuestDB - Time Series)]
        VAULT[Secret Vault - HashiCorp/AWS]
    end

    subgraph "External Entities"
        BROKER[Brokerage APIs - Alpaca/IBKR]
        FEED[Market Data Feeds]
        FCM[Firebase Cloud Messaging]
    end

    %% Communications
    FEED -->|TCP/WS| ING
    ING -->|gRPC| QDB
    ING -->|gRPC| STRAT
    STRAT -->|gRPC| RISK
    RISK -->|gRPC| EXEC
    EXEC -->|REST/FIX| BROKER
    
    ING -.->|WebSockets| State
    EXEC -.->|WebSockets| State
    State --> UI
    UI --> Chart

    STRAT -.->|Alerts| FCM
    FCM -.->|Push Notifications| UI

    ING -.->|Metrics| TELE
    STRAT -.->|Metrics| TELE
    EXEC -.->|Metrics| TELE
```

---

## 2. Event-Driven Execution Loop
The core simulation and live execution sequence using the event-driven paradigm.

```mermaid
sequenceDiagram
    participant DH as Data Handler
    participant Q as Event Queue
    participant SE as Strategy Engine
    participant RM as Risk Manager
    participant EH as Execution Handler
    participant Port as Portfolio/Accounting

    Note over DH, Port: Event Loop (While True)

    DH->>Q: MarketDataEvent (Tick/Bar)
    Q->>SE: Pop MarketDataEvent
    SE->>Q: SignalEvent (Long/Short)
    
    Q->>RM: Pop SignalEvent
    RM->>RM: Pre-Trade Risk Checks
    RM->>Q: OrderEvent (Quantity/Price)
    
    Q->>EH: Pop OrderEvent
    EH->>EH: Broker Adapter Translation
    EH->>EH: Live/Mock Execution
    EH->>Q: FillEvent (Execution Details)
    
    Q->>Port: Pop FillEvent
    Port->>Port: Update Holdings & P&L
```

---

## 3. Infrastructure Topology
Deployment strategy for low-latency execution and high availability.

```mermaid
graph LR
    subgraph "Local Development"
        Dev[Docker Desktop]
    end

    subgraph "Production (Low Latency)"
        subgraph "Equinix NY4 / AWS Local Zone"
            direction TB
            K8S[Kubernetes Cluster]
            VPS[Dedicated VPS]
            QDB_P[(QuestDB)]
        end
    end

    subgraph "Connectivity"
        Backbone[Fiber Optics / Direct Connect]
    end

    subgraph "Exchanges"
        NYSE[NYSE/NASDAQ Matching Engines]
        CME[CME Matching Engines]
    end

    K8S --- Backbone
    VPS --- Backbone
    Backbone --- NYSE
    Backbone --- CME
```

---

## 4. UI Design Concept (Dashboard)
A conceptual design for the Flutter-based command center.

> [!TIP]
> The UI leverages **GPU-accelerated charting** and **BLoC pattern** for 60fps performance during high-volatility events.

| Component | Functionality |
| :--- | :--- |
| **Global Kill Switch** | Ultimate-priority gRPC command to flatten all positions. |
| **Real-time P&L** | WebSocket-driven live equity curve and drawdown monitoring. |
| **Strategy Toggle** | Individual control for various algorithmic modules. |
| **Tick-Level Charts** | Multi-axis visualization using the Cristalyse library. |
| **Composite Alerts** | Correlated event notifications (e.g., Volatility + Rejection Rate). |

---

### Next Steps
1. **Implementation:** Start building the `Market Data Ingestion` microservice.
2. **Setup:** Initialize the QuestDB instance and Prometheus/Grafana stack.
3. **Frontend:** Scaffold the Flutter application with the BLoC pattern.
