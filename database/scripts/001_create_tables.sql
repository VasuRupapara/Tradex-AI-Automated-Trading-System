-- ============================================
-- QuestDB Schema Definitions
-- Automated Trading System
-- ============================================
-- QuestDB uses a specialized SQL syntax optimized for
-- time-series data. Key feature: LATEST ON for 1.56ms
-- most-recent-tick lookups.

-- ============================================
-- Tick Data Table
-- Stores raw tick-level market data
-- Designed for maximum ingestion velocity (11M+ rows/sec)
-- ============================================
CREATE TABLE IF NOT EXISTS ticks (
    symbol        SYMBOL        CAPACITY 256,
    price         DOUBLE,
    volume        DOUBLE,
    tick_type     SYMBOL        CAPACITY 8,     -- 'trade', 'bid', 'ask'
    exchange      SYMBOL        CAPACITY 32,
    bid           DOUBLE,
    ask           DOUBLE,
    spread        DOUBLE,
    timestamp     TIMESTAMP
) TIMESTAMP(timestamp)
PARTITION BY DAY
WAL
DEDUP UPSERT KEYS(symbol, timestamp);

-- ============================================
-- Bar Data Table (OHLCV Candlesticks)
-- Aggregated price data at various timeframes
-- ============================================
CREATE TABLE IF NOT EXISTS bars (
    symbol        SYMBOL        CAPACITY 256,
    timeframe     SYMBOL        CAPACITY 16,    -- '1m', '5m', '15m', '1h', '4h', '1d'
    open          DOUBLE,
    high          DOUBLE,
    low           DOUBLE,
    close         DOUBLE,
    volume        DOUBLE,
    num_trades    INT,
    vwap          DOUBLE,                       -- Volume Weighted Average Price
    timestamp     TIMESTAMP
) TIMESTAMP(timestamp)
PARTITION BY MONTH
WAL;

-- ============================================
-- Orders Table
-- Tracks all order submissions
-- ============================================
CREATE TABLE IF NOT EXISTS orders (
    order_id      STRING,
    symbol        SYMBOL        CAPACITY 256,
    side          SYMBOL        CAPACITY 4,     -- 'buy', 'sell'
    order_type    SYMBOL        CAPACITY 16,    -- 'market', 'limit', 'stop', 'stop_limit'
    quantity      DOUBLE,
    limit_price   DOUBLE,
    stop_price    DOUBLE,
    strategy      SYMBOL        CAPACITY 64,
    status        SYMBOL        CAPACITY 16,    -- 'submitted', 'filled', 'rejected', 'cancelled'
    timestamp     TIMESTAMP
) TIMESTAMP(timestamp)
PARTITION BY MONTH
WAL;

-- ============================================
-- Fills Table
-- Records all order executions
-- ============================================
CREATE TABLE IF NOT EXISTS fills (
    fill_id       STRING,
    order_id      STRING,
    symbol        SYMBOL        CAPACITY 256,
    side          SYMBOL        CAPACITY 4,
    filled_qty    DOUBLE,
    fill_price    DOUBLE,
    commission    DOUBLE,
    slippage      DOUBLE,
    broker        SYMBOL        CAPACITY 32,
    status        SYMBOL        CAPACITY 16,
    timestamp     TIMESTAMP
) TIMESTAMP(timestamp)
PARTITION BY MONTH
WAL;

-- ============================================
-- Portfolio Snapshots
-- Periodic snapshots of portfolio state
-- ============================================
CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    total_equity      DOUBLE,
    cash              DOUBLE,
    unrealized_pnl    DOUBLE,
    realized_pnl      DOUBLE,
    daily_pnl         DOUBLE,
    drawdown_pct      DOUBLE,
    num_positions     INT,
    timestamp         TIMESTAMP
) TIMESTAMP(timestamp)
PARTITION BY MONTH
WAL;

-- ============================================
-- System Metrics
-- Application-level telemetry data
-- ============================================
CREATE TABLE IF NOT EXISTS system_metrics (
    service       SYMBOL        CAPACITY 32,
    metric_name   SYMBOL        CAPACITY 128,
    metric_value  DOUBLE,
    timestamp     TIMESTAMP
) TIMESTAMP(timestamp)
PARTITION BY DAY
WAL;


-- ============================================
-- Example Queries Using QuestDB LATEST ON
-- ============================================

-- Get the most recent tick for each symbol (1.56ms!)
-- SELECT * FROM ticks LATEST ON timestamp PARTITION BY symbol;

-- Get latest tick for a specific symbol
-- SELECT * FROM ticks
-- WHERE symbol = 'AAPL'
-- LATEST ON timestamp PARTITION BY symbol;

-- Get 1-minute OHLCV bars from tick data
-- SELECT
--     symbol,
--     first(price) AS open,
--     max(price) AS high,
--     min(price) AS low,
--     last(price) AS close,
--     sum(volume) AS volume,
--     timestamp
-- FROM ticks
-- WHERE symbol = 'AAPL'
--     AND timestamp > dateadd('d', -1, now())
-- SAMPLE BY 1m
-- ALIGN TO CALENDAR;
