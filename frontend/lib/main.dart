import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:math';
import 'package:flutter/material.dart';
import 'package:web_socket_channel/web_socket_channel.dart';
import 'package:candlesticks/candlesticks.dart';

void main() => runApp(const ATSApp());

class ATSApp extends StatelessWidget {
  const ATSApp({super.key});
  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Tradex AI',
      debugShowCheckedModeBanner: false,
      theme: ThemeData.dark().copyWith(
        scaffoldBackgroundColor: const Color(0xFF121212),
        primaryColor: const Color(0xFFFF9800),
        colorScheme: const ColorScheme.dark(primary: Color(0xFFFF9800)),
      ),
      home: const DashboardScreen(),
    );
  }
}

// ---------------------------------------------------------------------------
// Data Models
// ---------------------------------------------------------------------------

class WatchlistEntry {
  final String symbol;
  double price;
  double change;
  WatchlistEntry({required this.symbol, this.price = 0.0, this.change = 0.0});
}

class PositionData {
  final String symbol;
  final String side;
  final double quantity;
  final double entryPrice;
  double currentPrice;
  PositionData(
      {required this.symbol,
      required this.side,
      required this.quantity,
      required this.entryPrice,
      this.currentPrice = 0.0});
  double get pnl =>
      (currentPrice - entryPrice) * quantity * (side == 'BUY' ? 1 : -1);
}

class TradeRecord {
  final DateTime time;
  final String symbol;
  final String side;
  final double quantity;
  final double price;
  final String status;
  TradeRecord(
      {required this.time,
      required this.symbol,
      required this.side,
      required this.quantity,
      required this.price,
      required this.status});
}

// ---------------------------------------------------------------------------
// Dashboard
// ---------------------------------------------------------------------------

class DashboardScreen extends StatefulWidget {
  const DashboardScreen({super.key});
  @override
  State<DashboardScreen> createState() => _DashboardScreenState();
}

class _DashboardScreenState extends State<DashboardScreen> {
  // Indian equity watchlist + F&O + Crypto
  Map<String, WatchlistEntry> watchlist = {
    'RELIANCE': WatchlistEntry(symbol: 'RELIANCE', price: 2850.0),
    'TCS': WatchlistEntry(symbol: 'TCS', price: 3920.0),
    'HDFCBANK': WatchlistEntry(symbol: 'HDFCBANK', price: 1620.0),
    'INFY': WatchlistEntry(symbol: 'INFY', price: 1540.0),
    'ICICIBANK': WatchlistEntry(symbol: 'ICICIBANK', price: 1280.0),
    'SBIN': WatchlistEntry(symbol: 'SBIN', price: 820.0),
    'BHARTIARTL': WatchlistEntry(symbol: 'BHARTIARTL', price: 1680.0),
    'ITC': WatchlistEntry(symbol: 'ITC', price: 435.0),
    'HINDUNILVR': WatchlistEntry(symbol: 'HINDUNILVR', price: 2380.0),
    'KOTAKBANK': WatchlistEntry(symbol: 'KOTAKBANK', price: 1920.0),
    // F&O Indices
    'NIFTY': WatchlistEntry(symbol: 'NIFTY', price: 24200.0),
    'BANKNIFTY': WatchlistEntry(symbol: 'BANKNIFTY', price: 52100.0),
    'FINNIFTY': WatchlistEntry(symbol: 'FINNIFTY', price: 23800.0),
    // Crypto (USDT pairs)
    'BTCUSDT': WatchlistEntry(symbol: 'BTCUSDT', price: 104500.0),
    'ETHUSDT': WatchlistEntry(symbol: 'ETHUSDT', price: 2550.0),
    'SOLUSDT': WatchlistEntry(symbol: 'SOLUSDT', price: 172.0),
    'XRPUSDT': WatchlistEntry(symbol: 'XRPUSDT', price: 2.45),
    'BNBUSDT': WatchlistEntry(symbol: 'BNBUSDT', price: 655.0),
    'ADAUSDT': WatchlistEntry(symbol: 'ADAUSDT', price: 0.78),
    'DOGEUSDT': WatchlistEntry(symbol: 'DOGEUSDT', price: 0.225),
    'DOTUSDT': WatchlistEntry(symbol: 'DOTUSDT', price: 4.80),
    'MATICUSDT': WatchlistEntry(symbol: 'MATICUSDT', price: 0.42),
    'AVAXUSDT': WatchlistEntry(symbol: 'AVAXUSDT', price: 24.50),
  };

  String _selectedSymbol = 'RELIANCE';
  List<Candle> candles = [];

  // State
  bool _engineRunning = false;
  final String _tradingMode = 'PAPER';
  final String _brokerName = 'angel_one';
  final String _marketStatus = 'CLOSED';
  final double _totalCapital = 100000;
  final double _equityCapital = 70000;
  final double _fnoCapital = 30000;
  int _totalTrades = 0;

  // Chart data per symbol
  final Map<String, List<Candle>> _symbolCandles = {};
  final Map<String, DateTime> _lastCandleTime = {};

  // Positions & Trade History
  List<PositionData> positions = [];
  List<TradeRecord> tradeHistory = [];

  // Event log
  List<String> eventLogs = [];

  WebSocketChannel? _channel;
  final String _wsUrl = 'ws://localhost:8000/ws/market-data';

  @override
  void initState() {
    super.initState();
    _generateFlatInitialData();
  }

  // -- WebSocket Connection ----

  void _connectWebSocket() {
    try {
      _channel = WebSocketChannel.connect(Uri.parse(_wsUrl));
      _addLog('Connected to ATS Engine');
      _channel!.stream.listen(
        _handleWsMessage,
        onError: (e) {
          _addLog('WS Error: $e');
          _reconnect();
        },
        onDone: () {
          _addLog('WS Disconnected');
          _reconnect();
        },
      );
    } catch (e) {
      _addLog('Connection failed: $e');
      _reconnect();
    }
  }

  void _reconnect() {
    if (_engineRunning) {
      Future.delayed(const Duration(seconds: 5), () {
        if (_engineRunning) _connectWebSocket();
      });
    }
  }

  void _handleWsMessage(dynamic message) {
    try {
      final data = jsonDecode(message);
      final type = data['type'] as String?;
      final payload = data['data'] as Map<String, dynamic>?;
      if (type == null) return;

      switch (type) {
        case 'MARKET_DATA':
          if (payload != null) {
            final symbol = payload['symbol']?.toString() ?? '';
            final price = _toDouble(payload['price']);
            if (symbol.isNotEmpty && price > 0) _onMarketTick(symbol, price);
          }
          break;
        case 'SIGNAL':
          final sym = payload?['symbol'] ?? '';
          final dir = payload?['direction'] ?? payload?['side'] ?? '';
          final str = _toDouble(payload?['strength']);
          final strat = payload?['strategy_name'] ?? '';
          _addLog('📊 SIGNAL $dir $sym str=${str.toStringAsFixed(2)} [$strat]');
          _addTrade(sym, dir.toString().toUpperCase(), 0, 0, 'SIGNAL');
          break;
        case 'ORDER':
          final sym = payload?['symbol'] ?? '';
          final side = payload?['side'] ?? '';
          final qty = _toDouble(payload?['quantity']);
          final price = _toDouble(payload?['limit_price'] ?? payload?['price']);
          _addLog('📝 ORDER $side $sym qty=${qty.toStringAsFixed(0)}');
          _addTrade(sym, side.toString().toUpperCase(), qty, price, 'ORDER');
          break;
        case 'FILL':
          final sym = payload?['symbol'] ?? '';
          final side = payload?['side'] ?? '';
          final price = _toDouble(payload?['fill_price'] ?? payload?['price']);
          final qty =
              _toDouble(payload?['filled_quantity'] ?? payload?['quantity']);
          _addLog('✅ FILL $side $sym @ ₹${price.toStringAsFixed(2)}');
          _addTrade(sym, side.toString().toUpperCase(), qty, price, 'FILLED');
          _onFill(sym, side.toString(), qty, price);
          break;
        default:
          _addLog('$type: ${jsonEncode(payload)}');
      }
    } catch (e) {/* ignore malformed */}
  }

  double _toDouble(dynamic v) {
    if (v is double) return v;
    if (v is int) return v.toDouble();
    if (v is String) return double.tryParse(v) ?? 0.0;
    return 0.0;
  }

  // -- Market Data Handlers ----

  void _onMarketTick(String symbol, double price) {
    setState(() {
      if (watchlist.containsKey(symbol)) {
        final w = watchlist[symbol]!;
        if (w.price > 0) {
          w.change = ((price - w.price) / w.price) * 100;
        }
        w.price = price;
      }
      _updateCandleForSymbol(symbol, price);
      if (symbol == _selectedSymbol) {
        candles = List.from(_symbolCandles[symbol] ?? []);
      }
      // Update position current prices
      for (var p in positions) {
        if (p.symbol == symbol) p.currentPrice = price;
      }
    });
  }

  void _updateCandleForSymbol(String symbol, double price) {
    final list = _symbolCandles.putIfAbsent(symbol, () => []);
    final now = DateTime.now();
    final minuteKey =
        DateTime(now.year, now.month, now.day, now.hour, now.minute);
    final lastTime = _lastCandleTime[symbol];

    if (lastTime == null || minuteKey.isAfter(lastTime)) {
      list.insert(
          0,
          Candle(
              date: minuteKey,
              open: price,
              high: price + (price * 0.0001),
              low: price - (price * 0.0001),
              close: price,
              volume: 1));
      _lastCandleTime[symbol] = minuteKey;
      if (list.length > 300) list.removeLast();
    } else {
      final c = list[0];
      list[0] = Candle(
          date: c.date,
          open: c.open,
          high: max(c.high, price),
          low: min(c.low, price),
          close: price,
          volume: c.volume + 1);
    }
  }

  void _onFill(String symbol, String side, double qty, double price) {
    setState(() {
      positions.add(PositionData(
          symbol: symbol,
          side: side,
          quantity: qty,
          entryPrice: price,
          currentPrice: price));
      _totalTrades++;
    });
  }

  void _addTrade(
      String symbol, String side, double qty, double price, String status) {
    setState(() {
      tradeHistory.insert(
          0,
          TradeRecord(
              time: DateTime.now(),
              symbol: symbol,
              side: side,
              quantity: qty,
              price: price,
              status: status));
      if (tradeHistory.length > 200) tradeHistory.removeLast();
    });
  }

  void _addLog(String msg) {
    setState(() {
      eventLogs.insert(0, '> $msg');
      if (eventLogs.length > 100) eventLogs.removeLast();
    });
  }


  // -- Clean Flat Candles to prevent rendering crashes ----

  List<Candle> _buildFlatCandles(double price) {
    final list = <Candle>[];
    final now = DateTime.now();
    for (int i = 0; i < 100; i++) {
      list.add(Candle(
        date: now.subtract(Duration(minutes: i)),
        open: price,
        high: price + (price * 0.0001), // Slight offset to prevent division by zero
        low: price - (price * 0.0001),
        close: price,
        volume: 100,
      ));
    }
    return list;
  }

  void _generateFlatInitialData() {
    final basePrices = {
      'RELIANCE': 2850.0,
      'TCS': 3920.0,
      'HDFCBANK': 1620.0,
      'INFY': 1540.0,
      'ICICIBANK': 1280.0,
      'SBIN': 820.0,
      'BHARTIARTL': 1680.0,
      'ITC': 435.0,
      'HINDUNILVR': 2380.0,
      'KOTAKBANK': 1920.0,
      'NIFTY': 24200.0,
      'BANKNIFTY': 52100.0,
      'FINNIFTY': 23800.0,
      'BTCUSDT': 104500.0,
      'ETHUSDT': 2550.0,
      'SOLUSDT': 172.0,
      'XRPUSDT': 2.45,
      'BNBUSDT': 655.0,
      'ADAUSDT': 0.78,
      'DOGEUSDT': 0.225,
      'DOTUSDT': 4.80,
      'MATICUSDT': 0.42,
      'AVAXUSDT': 24.50,
    };
    for (var sym in watchlist.keys) {
      _symbolCandles[sym] = _buildFlatCandles(basePrices[sym] ?? 1000.0);
    }
    candles = List.from(_symbolCandles[_selectedSymbol] ?? []);
  }

  @override
  void dispose() {
    _channel?.sink.close();
    super.dispose();
  }

  // -- UI Build ----

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: _buildAppBar(),
      body: Row(
        children: [
          _buildWatchlistSidebar(),
          Expanded(
            child: Column(
              children: [
                // Chart
                Expanded(flex: 3, child: _buildChartPanel()),
                // Bottom panels
                Expanded(flex: 2, child: _buildBottomSection()),
              ],
            ),
          ),
        ],
      ),
    );
  }

  PreferredSizeWidget _buildAppBar() {
    final modeColor = _tradingMode == 'PAPER' ? Colors.amber : Colors.redAccent;
    return AppBar(
      title: Row(
        children: [
          const Text('🤖 ', style: TextStyle(fontSize: 20)),
          const Text('Tradex AI Terminal',
              style: TextStyle(fontWeight: FontWeight.bold, fontSize: 16)),
          const SizedBox(width: 12),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
            decoration: BoxDecoration(
              color: modeColor.withOpacity(0.2),
              borderRadius: BorderRadius.circular(4),
              border: Border.all(color: modeColor, width: 1),
            ),
            child: Text(_tradingMode,
                style: TextStyle(
                    fontSize: 10,
                    fontWeight: FontWeight.bold,
                    color: modeColor,
                    letterSpacing: 1)),
          ),
          const SizedBox(width: 8),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 3),
            decoration: BoxDecoration(
                color: Colors.white.withOpacity(0.08),
                borderRadius: BorderRadius.circular(4)),
            child: Text(_brokerName.toUpperCase(),
                style: const TextStyle(
                    fontSize: 9, color: Colors.white54, letterSpacing: 0.5)),
          ),
        ],
      ),
      backgroundColor: const Color(0xFF1E1E1E),
      elevation: 0,
      actions: [
        // Market status
        Padding(
          padding: const EdgeInsets.only(right: 8),
          child: Center(
            child: Row(
              children: [
                Icon(Icons.circle,
                    size: 8,
                    color: _marketStatus == 'OPEN'
                        ? Colors.greenAccent
                        : Colors.grey),
                const SizedBox(width: 4),
                Text('NSE $_marketStatus',
                    style: const TextStyle(fontSize: 10, color: Colors.grey)),
              ],
            ),
          ),
        ),
        // Capital display
        Padding(
          padding: const EdgeInsets.only(right: 12),
          child: Center(
            child: Text('₹${_totalCapital.toStringAsFixed(0)}',
                style: const TextStyle(
                    fontSize: 12,
                    color: Colors.white70,
                    fontFamily: 'monospace')),
          ),
        ),
        // Live connection toggle
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 8),
          child: Row(
            children: [
              const Text('Engine: ',
                  style: TextStyle(color: Colors.grey, fontSize: 11)),
              Switch(
                value: _engineRunning,
                onChanged: (val) {
                  setState(() {
                    _engineRunning = val;
                    if (_engineRunning) {
                      _connectWebSocket();
                    } else {
                      _channel?.sink.close();
                    }
                  });
                },
                activeThumbColor: Colors.greenAccent,
              ),
            ],
          ),
        ),
        IconButton(
          icon: const Icon(Icons.settings, color: Colors.grey, size: 20),
          onPressed: () {
            Navigator.push(context, MaterialPageRoute(builder: (ctx) => const SettingsScreen()));
          },
        ),
      ],
    );
  }

  // Crypto symbol names
  static const _cryptoSymbols = [
    'BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'XRPUSDT', 'BNBUSDT',
    'ADAUSDT', 'DOGEUSDT', 'DOTUSDT', 'MATICUSDT', 'AVAXUSDT',
  ];
  static const _indexSymbols = ['NIFTY', 'BANKNIFTY', 'FINNIFTY'];

  bool _isCrypto(String symbol) => _cryptoSymbols.contains(symbol);
  bool _isIndex(String symbol) => _indexSymbols.contains(symbol);

  Widget _buildWatchlistSidebar() {
    // Separate equity, index, and crypto
    final equitySyms = watchlist.values
        .where((w) => !_isIndex(w.symbol) && !_isCrypto(w.symbol))
        .toList();
    final indexSyms = watchlist.values
        .where((w) => _isIndex(w.symbol))
        .toList();
    final cryptoSyms = watchlist.values
        .where((w) => _isCrypto(w.symbol))
        .toList();

    return Container(
      width: 220,
      decoration: const BoxDecoration(
        color: Color(0xFF1A1A1A),
        border: Border(right: BorderSide(color: Color(0xFF333333))),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Padding(
            padding: EdgeInsets.fromLTRB(12, 12, 12, 4),
            child: Text('EQUITY',
                style: TextStyle(
                    letterSpacing: 1.5,
                    fontSize: 10,
                    color: Colors.grey,
                    fontWeight: FontWeight.bold)),
          ),
          Expanded(
            flex: 5,
            child: ListView(
              children: equitySyms.map((w) => _watchlistTile(w)).toList(),
            ),
          ),
          Container(height: 1, color: const Color(0xFF333333)),
          const Padding(
            padding: EdgeInsets.fromLTRB(12, 8, 12, 4),
            child: Text('F&O INDICES',
                style: TextStyle(
                    letterSpacing: 1.5,
                    fontSize: 10,
                    color: Color(0xFFFF9800),
                    fontWeight: FontWeight.bold)),
          ),
          Expanded(
            flex: 2,
            child: ListView(
              children: indexSyms.map((w) => _watchlistTile(w)).toList(),
            ),
          ),
          Container(height: 1, color: const Color(0xFF333333)),
          Padding(
            padding: const EdgeInsets.fromLTRB(12, 8, 12, 4),
            child: Row(
              children: [
                const Text('💰 ',
                    style: TextStyle(fontSize: 10)),
                const Text('CRYPTO',
                    style: TextStyle(
                        letterSpacing: 1.5,
                        fontSize: 10,
                        color: Color(0xFF00E5FF),
                        fontWeight: FontWeight.bold)),
                const Spacer(),
                Text('${cryptoSyms.length}',
                    style: const TextStyle(
                        fontSize: 9, color: Colors.white38)),
              ],
            ),
          ),
          Expanded(
            flex: 4,
            child: ListView(
              children: cryptoSyms.map((w) => _watchlistTile(w)).toList(),
            ),
          ),
        ],
      ),
    );
  }

  Widget _watchlistTile(WatchlistEntry w) {
    final isSelected = w.symbol == _selectedSymbol;
    final changeColor = w.change >= 0 ? Colors.greenAccent : Colors.redAccent;
    final isIndex = _isIndex(w.symbol);
    final isCrypto = _isCrypto(w.symbol);

    // Use $ for crypto, ₹ for Indian stocks
    final currencySymbol = isCrypto ? '\$' : '₹';
    // Crypto with small prices show more decimals
    final priceStr = w.price < 1
        ? '$currencySymbol${w.price.toStringAsFixed(4)}'
        : '$currencySymbol${w.price.toStringAsFixed(2)}';

    // Color coding: orange for indices, cyan for crypto, white for equity
    final symbolColor = isCrypto
        ? const Color(0xFF00E5FF)
        : isIndex
            ? const Color(0xFFFF9800)
            : Colors.white;

    return InkWell(
      onTap: () {
        setState(() {
          _selectedSymbol = w.symbol;
          candles = List.from(_symbolCandles[w.symbol] ?? []);
        });
      },
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        color: isSelected ? Colors.white.withOpacity(0.06) : Colors.transparent,
        child: Row(
          children: [
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                      isCrypto ? w.symbol.replaceAll('USDT', '') : w.symbol,
                      style: TextStyle(
                          fontSize: 12,
                          fontWeight: FontWeight.bold,
                          color: symbolColor)),
                  Text(priceStr,
                      style:
                          const TextStyle(fontSize: 10, color: Colors.white54)),
                ],
              ),
            ),
            Flexible(
              child: Text(
                  '${w.change >= 0 ? '+' : ''}${w.change.toStringAsFixed(2)}%',
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(
                      fontSize: 11,
                      color: changeColor,
                      fontWeight: FontWeight.bold)),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildChartPanel() {
    return Container(
      color: const Color(0xFF0D0D0D),
      child: Stack(
        children: [
          Candlesticks(candles: candles, onLoadMoreCandles: () async {}),
          Positioned(
            top: 8,
            left: 12,
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
              decoration: BoxDecoration(
                  color: Colors.black54,
                  borderRadius: BorderRadius.circular(4)),
              child: Text(_selectedSymbol,
                  style: const TextStyle(
                      color: Colors.white70,
                      fontSize: 13,
                      fontWeight: FontWeight.bold)),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildBottomSection() {
    return Container(
      decoration: const BoxDecoration(
        color: Color(0xFF1A1A1A),
        border: Border(top: BorderSide(color: Color(0xFF333333))),
      ),
      child: Column(
        children: [
          // Trade History Table
          Expanded(flex: 3, child: _buildTradeHistoryTable()),
          // Bottom row: Event Log + Positions
          Expanded(
            flex: 2,
            child: Row(
              children: [
                _buildPanel('EVENT LOG', [
                  Expanded(
                    child: ListView.builder(
                      itemCount: eventLogs.length,
                      itemBuilder: (ctx, i) => Padding(
                        padding: const EdgeInsets.only(bottom: 2),
                        child: Text(eventLogs[i],
                            style: const TextStyle(
                                fontFamily: 'monospace',
                                fontSize: 10,
                                color: Colors.white54)),
                      ),
                    ),
                  ),
                ]),
                _buildPanel('POSITIONS (${positions.length})', [
                  Expanded(
                    child: positions.isEmpty
                        ? const Center(
                            child: Text('No open positions',
                                style: TextStyle(
                                    color: Colors.grey, fontSize: 11)))
                        : ListView.builder(
                            itemCount: positions.length,
                            itemBuilder: (ctx, i) {
                              final p = positions[i];
                              final pnl = p.pnl;
                              final clr = pnl >= 0
                                  ? Colors.greenAccent
                                  : Colors.redAccent;
                              return Padding(
                                padding: const EdgeInsets.only(bottom: 3),
                                child: Row(
                                  children: [
                                    Text('${p.side} ${p.symbol}',
                                        style: const TextStyle(
                                            fontFamily: 'monospace',
                                            fontSize: 10,
                                            color: Colors.white70)),
                                    const Spacer(),
                                    Text('₹${pnl.toStringAsFixed(2)}',
                                        style: TextStyle(
                                            fontFamily: 'monospace',
                                            fontSize: 10,
                                            color: clr)),
                                  ],
                                ),
                              );
                            },
                          ),
                  ),
                ]),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildTradeHistoryTable() {
    return Container(
      decoration: const BoxDecoration(
          border: Border(bottom: BorderSide(color: Color(0xFF333333)))),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
            child: Row(
              children: [
                const Text('TRADE HISTORY',
                    style: TextStyle(
                        fontSize: 10,
                        fontWeight: FontWeight.bold,
                        color: Colors.grey,
                        letterSpacing: 1.5)),
                const SizedBox(width: 12),
                Text('${tradeHistory.length} trades',
                    style: const TextStyle(fontSize: 10, color: Colors.grey)),
              ],
            ),
          ),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 3),
            color: const Color(0xFF222222),
            child: const Row(
              children: [
                SizedBox(
                    width: 60,
                    child: Text('TIME',
                        style: TextStyle(
                            fontSize: 9,
                            color: Colors.grey,
                            fontWeight: FontWeight.bold))),
                SizedBox(
                    width: 85,
                    child: Text('SYMBOL',
                        style: TextStyle(
                            fontSize: 9,
                            color: Colors.grey,
                            fontWeight: FontWeight.bold))),
                SizedBox(
                    width: 50,
                    child: Text('SIDE',
                        style: TextStyle(
                            fontSize: 9,
                            color: Colors.grey,
                            fontWeight: FontWeight.bold))),
                SizedBox(
                    width: 45,
                    child: Text('QTY',
                        style: TextStyle(
                            fontSize: 9,
                            color: Colors.grey,
                            fontWeight: FontWeight.bold))),
                SizedBox(
                    width: 80,
                    child: Text('PRICE',
                        style: TextStyle(
                            fontSize: 9,
                            color: Colors.grey,
                            fontWeight: FontWeight.bold))),
                Expanded(
                    child: Text('STATUS',
                        style: TextStyle(
                            fontSize: 9,
                            color: Colors.grey,
                            fontWeight: FontWeight.bold))),
              ],
            ),
          ),
          Expanded(
            child: tradeHistory.isEmpty
                ? const Center(
                    child: Text('No trades yet — turn on Engine',
                        style: TextStyle(color: Colors.grey, fontSize: 11)))
                : ListView.builder(
                    itemCount: tradeHistory.length,
                    itemBuilder: (ctx, i) {
                      final t = tradeHistory[i];
                      final isBuy =
                          t.side.contains('BUY') || t.side.contains('LONG');
                      final sideClr =
                          isBuy ? Colors.greenAccent : Colors.redAccent;
                      final statusClr = t.status == 'FILLED'
                          ? Colors.greenAccent
                          : t.status == 'ORDER'
                              ? Colors.orangeAccent
                              : Colors.blueAccent;
                      final timeStr =
                          '${t.time.hour.toString().padLeft(2, '0')}:${t.time.minute.toString().padLeft(2, '0')}:${t.time.second.toString().padLeft(2, '0')}';
                      return Container(
                        padding: const EdgeInsets.symmetric(
                            horizontal: 12, vertical: 2),
                        decoration: BoxDecoration(
                          color: i.isEven
                              ? Colors.transparent
                              : Colors.white.withOpacity(0.015),
                          border: const Border(
                              bottom: BorderSide(
                                  color: Color(0xFF2A2A2A), width: 0.5)),
                        ),
                        child: Row(
                          children: [
                            SizedBox(
                                width: 60,
                                child: Text(timeStr,
                                    style: const TextStyle(
                                        fontFamily: 'monospace',
                                        fontSize: 9,
                                        color: Colors.white54))),
                            SizedBox(
                                width: 85,
                                child: Text(t.symbol,
                                    style: const TextStyle(
                                        fontFamily: 'monospace',
                                        fontSize: 9,
                                        color: Colors.white,
                                        fontWeight: FontWeight.bold))),
                            SizedBox(
                                width: 50,
                                child: Text(t.side,
                                    style: TextStyle(
                                        fontFamily: 'monospace',
                                        fontSize: 9,
                                        color: sideClr,
                                        fontWeight: FontWeight.bold))),
                            SizedBox(
                                width: 45,
                                child: Text(
                                    t.quantity > 0
                                        ? t.quantity.toStringAsFixed(0)
                                        : '--',
                                    style: const TextStyle(
                                        fontFamily: 'monospace',
                                        fontSize: 9,
                                        color: Colors.white70))),
                            SizedBox(
                                width: 80,
                                child: Text(
                                    t.price > 0
                                        ? '₹${t.price.toStringAsFixed(2)}'
                                        : '--',
                                    style: const TextStyle(
                                        fontFamily: 'monospace',
                                        fontSize: 9,
                                        color: Colors.white70))),
                            Expanded(
                              child: Container(
                                padding: const EdgeInsets.symmetric(
                                    horizontal: 5, vertical: 1),
                                decoration: BoxDecoration(
                                    color: statusClr.withOpacity(0.15),
                                    borderRadius: BorderRadius.circular(3)),
                                child: Text(t.status,
                                    style: TextStyle(
                                        fontFamily: 'monospace',
                                        fontSize: 8,
                                        color: statusClr,
                                        fontWeight: FontWeight.bold)),
                              ),
                            ),
                          ],
                        ),
                      );
                    },
                  ),
          ),
        ],
      ),
    );
  }

  Widget _buildPanel(String title, List<Widget> children) {
    return Expanded(
      child: Container(
        padding: const EdgeInsets.all(10),
        decoration: BoxDecoration(
            border: Border.all(color: const Color(0xFF333333), width: 0.5)),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(title,
                style: const TextStyle(
                    fontSize: 10,
                    fontWeight: FontWeight.bold,
                    color: Colors.grey,
                    letterSpacing: 1.2)),
            const SizedBox(height: 6),
            ...children,
          ],
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Settings Screen
// ---------------------------------------------------------------------------

class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key});
  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  final Map<String, TextEditingController> _controllers = {};
  List<String> _envLines = [];

  @override
  void initState() {
    super.initState();
    _loadEnv();
  }

  void _loadEnv() {
    try {
      final file = File('../.env');
      if (file.existsSync()) {
        _envLines = file.readAsLinesSync();
        for (var line in _envLines) {
          line = line.trim();
          if (line.isNotEmpty && !line.startsWith('#') && line.contains('=')) {
            final idx = line.indexOf('=');
            final key = line.substring(0, idx).trim();
            final value = line.substring(idx + 1).trim();
            _controllers[key] = TextEditingController(text: value);
          }
        }
        setState(() {});
      }
    } catch (e) {
      debugPrint('Error loading .env: $e');
    }
  }

  void _saveEnv() {
    try {
      final file = File('../.env');
      List<String> newLines = [];
      for (var line in _envLines) {
        final trimmed = line.trim();
        if (trimmed.isNotEmpty && !trimmed.startsWith('#') && trimmed.contains('=')) {
          final idx = trimmed.indexOf('=');
          final key = trimmed.substring(0, idx).trim();
          if (_controllers.containsKey(key)) {
            newLines.add('$key=${_controllers[key]!.text}');
            continue;
          }
        }
        newLines.add(line);
      }
      file.writeAsStringSync(newLines.join('\n'));
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Settings saved successfully! Restart backend to apply.', style: TextStyle(color: Colors.white))),
      );
      Navigator.pop(context);
    } catch (e) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Error saving: $e', style: const TextStyle(color: Colors.redAccent))),
      );
    }
  }

  @override
  void dispose() {
    for (var controller in _controllers.values) {
      controller.dispose();
    }
    super.dispose();
  }

  Widget _buildTextField(String key) {
    if (!_controllers.containsKey(key)) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.only(bottom: 12.0),
      child: TextField(
        controller: _controllers[key],
        style: const TextStyle(fontSize: 13, fontFamily: 'monospace'),
        decoration: InputDecoration(
          labelText: key,
          labelStyle: const TextStyle(color: Colors.grey, fontSize: 12),
          border: OutlineInputBorder(
            borderRadius: BorderRadius.circular(4),
            borderSide: const BorderSide(color: Color(0xFF333333)),
          ),
          enabledBorder: OutlineInputBorder(
            borderRadius: BorderRadius.circular(4),
            borderSide: const BorderSide(color: Color(0xFF333333)),
          ),
          focusedBorder: OutlineInputBorder(
            borderRadius: BorderRadius.circular(4),
            borderSide: const BorderSide(color: Colors.orange),
          ),
          filled: true,
          fillColor: const Color(0xFF1A1A1A),
          isDense: true,
        ),
      ),
    );
  }

  Widget _buildDropdownField(String key, List<String> options) {
    if (!_controllers.containsKey(key)) return const SizedBox.shrink();
    String currentValue = _controllers[key]!.text.trim();
    if (!options.contains(currentValue)) {
      if (options.isNotEmpty) currentValue = options.first;
    }
    
    return Padding(
      padding: const EdgeInsets.only(bottom: 12.0),
      child: DropdownButtonFormField<String>(
        value: currentValue,
        dropdownColor: const Color(0xFF1A1A1A),
        style: const TextStyle(fontSize: 13, fontFamily: 'monospace', color: Colors.white),
        decoration: InputDecoration(
          labelText: key,
          labelStyle: const TextStyle(color: Colors.grey, fontSize: 12),
          border: OutlineInputBorder(
            borderRadius: BorderRadius.circular(4),
            borderSide: const BorderSide(color: Color(0xFF333333)),
          ),
          enabledBorder: OutlineInputBorder(
            borderRadius: BorderRadius.circular(4),
            borderSide: const BorderSide(color: Color(0xFF333333)),
          ),
          focusedBorder: OutlineInputBorder(
            borderRadius: BorderRadius.circular(4),
            borderSide: const BorderSide(color: Colors.orange),
          ),
          filled: true,
          fillColor: const Color(0xFF1A1A1A),
          isDense: true,
        ),
        items: options.map((e) => DropdownMenuItem(value: e, child: Text(e))).toList(),
        onChanged: (val) {
          if (val != null) {
            _controllers[key]!.text = val;
            setState(() {});
          }
        },
      ),
    );
  }

  Widget _buildSection(String title, List<Widget> children) {
    // If all children are SizedBox.shrink, don't show the card
    bool hasContent = children.any((widget) => widget is! SizedBox);
    if (!hasContent) return const SizedBox.shrink();

    return Card(
      color: const Color(0xFF121212),
      margin: const EdgeInsets.only(bottom: 20.0),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(8),
        side: const BorderSide(color: Color(0xFF333333), width: 1),
      ),
      elevation: 4,
      child: Padding(
        padding: const EdgeInsets.all(16.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                const Icon(Icons.tune, size: 16, color: Colors.orangeAccent),
                const SizedBox(width: 8),
                Text(
                  title.toUpperCase(),
                  style: const TextStyle(
                    color: Colors.orangeAccent,
                    fontWeight: FontWeight.bold,
                    letterSpacing: 1.2,
                    fontSize: 14,
                  ),
                ),
              ],
            ),
            const Divider(color: Color(0xFF333333), height: 24),
            ...children,
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Tradex AI Configuration', style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold)),
        backgroundColor: const Color(0xFF1E1E1E),
        elevation: 0,
        actions: [
          ElevatedButton.icon(
            icon: const Icon(Icons.save, color: Colors.white, size: 16),
            label: const Text('Save Settings'),
            style: ElevatedButton.styleFrom(
              backgroundColor: Colors.green,
              foregroundColor: Colors.white,
              padding: const EdgeInsets.symmetric(horizontal: 16),
            ),
            onPressed: _saveEnv,
          ),
          const SizedBox(width: 16),
        ],
      ),
      body: _controllers.isEmpty
          ? const Center(child: Text('No settings found in .env', style: TextStyle(color: Colors.grey)))
          : ListView(
              padding: const EdgeInsets.all(24),
              children: [
                _buildSection('Broker Selection', [
                  _buildDropdownField('BROKER_NAME', ['angel_one', 'zerodha', 'fyers', 'upstox', 'dhan', 'groww']),
                  _buildDropdownField('TRADING_MODE', ['paper', 'live']),
                ]),
                _buildSection('Angel One API', [
                  _buildTextField('ANGEL_API_KEY'),
                  _buildTextField('ANGEL_CLIENT_ID'),
                  _buildTextField('ANGEL_PASSWORD'),
                  _buildTextField('ANGEL_TOTP_SECRET'),
                ]),
                _buildSection('Zerodha Kite Connect', [
                  _buildTextField('ZERODHA_API_KEY'),
                  _buildTextField('ZERODHA_API_SECRET'),
                  _buildTextField('ZERODHA_ACCESS_TOKEN'),
                  _buildTextField('ZERODHA_USER_ID'),
                ]),
                _buildSection('Fyers API v3', [
                  _buildTextField('FYERS_APP_ID'),
                  _buildTextField('FYERS_SECRET_KEY'),
                  _buildTextField('FYERS_ACCESS_TOKEN'),
                  _buildTextField('FYERS_REDIRECT_URL'),
                ]),
                _buildSection('Upstox API v2', [
                  _buildTextField('UPSTOX_API_KEY'),
                  _buildTextField('UPSTOX_API_SECRET'),
                  _buildTextField('UPSTOX_ACCESS_TOKEN'),
                  _buildTextField('UPSTOX_REDIRECT_URI'),
                ]),
                _buildSection('Dhan HQ', [
                  _buildTextField('DHAN_CLIENT_ID'),
                  _buildTextField('DHAN_ACCESS_TOKEN'),
                ]),
                _buildSection('Groww Trading API', [
                  _buildTextField('GROWW_API_KEY'),
                  _buildTextField('GROWW_API_SECRET'),
                  _buildTextField('GROWW_ACCESS_TOKEN'),
                ]),
                _buildSection('Trading Capital Allocation', [
                  _buildTextField('TOTAL_CAPITAL'),
                  _buildTextField('EQUITY_CAPITAL_PERCENT'),
                  _buildTextField('FNO_CAPITAL_PERCENT'),
                  _buildTextField('CRYPTO_CAPITAL_PERCENT'),
                ]),
                _buildSection('Monthly Report Email Settings', [
                  _buildTextField('SENDER_EMAIL'),
                  _buildTextField('SENDER_PASSWORD'),
                  _buildTextField('RECEIVER_EMAIL'),
                ]),
                _buildSection('Risk Management', [
                  _buildTextField('MAX_POSITION_SIZE'),
                  _buildTextField('MAX_DRAWDOWN_PERCENT'),
                  _buildTextField('MAX_DAILY_LOSS'),
                  _buildTextField('MAX_ORDER_FREQUENCY_PER_SECOND'),
                  _buildDropdownField('KILL_SWITCH_ENABLED', ['true', 'false']),
                  _buildTextField('INTRADAY_SQUARE_OFF_TIME'),
                ]),
                _buildSection('Watchlist', [
                  _buildTextField('EQUITY_SYMBOLS'),
                  _buildTextField('FNO_SYMBOLS'),
                  _buildTextField('CRYPTO_SYMBOLS'),
                ]),
                _buildSection('Redis', [
                  _buildTextField('REDIS_HOST'),
                  _buildTextField('REDIS_PORT'),
                  _buildTextField('REDIS_DB'),
                ]),
                _buildSection('System & Infrastructure', [
                  _buildDropdownField('ENVIRONMENT', ['production', 'development']),
                  _buildDropdownField('LOG_LEVEL', ['DEBUG', 'INFO', 'WARNING', 'ERROR']),
                  _buildDropdownField('DEBUG', ['true', 'false']),
                  _buildTextField('API_GATEWAY_HOST'),
                  _buildTextField('API_GATEWAY_PORT'),
                  _buildTextField('API_SECRET_KEY'),
                  _buildTextField('QUESTDB_HOST'),
                  _buildTextField('QUESTDB_PORT'),
                  _buildTextField('QUESTDB_HTTP_PORT'),
                  _buildTextField('QUESTDB_USER'),
                  _buildTextField('QUESTDB_PASSWORD'),
                ]),
              ],
            ),
    );
  }
}
