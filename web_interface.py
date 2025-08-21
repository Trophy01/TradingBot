#!/usr/bin/env python3
"""
GoldTick5 Bot Web Interface Monitor
Monitors the goldtick5.py bot's log file and MT5 data to provide real-time web dashboard
"""

import sys
import os
import re
import json
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
import logging

# Check for required dependencies
try:
    from flask import Flask, jsonify, request
    from flask_socketio import SocketIO, emit
    import MetaTrader5 as mt5
except ImportError as e:
    print(f"Import failed: {e}")
    print("Please install: pip install flask flask-socketio MetaTrader5")
    sys.exit(1)

# Initialize Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = 'goldtick5-monitor-secret'
socketio = SocketIO(app, cors_allowed_origins="*")

class GoldTick5Monitor:
    """Monitor for GoldTick5 trading bot"""
    
    def __init__(self):
        self.bot_log_file = "gold_scalper_bot.log"
        self.config_file = "goldtick5_config.json"
        self.data_dir = Path("web_data")
        self.data_dir.mkdir(exist_ok=True)
        
        # Data storage
        self.trades_data = []
        self.terminal_messages = []
        self.current_state = {}
        self.performance_metrics = {}
        self.bot_config = {}
        
        # Monitoring state
        self.last_log_position = 0
        self.last_update_time = datetime.now()
        self.mt5_connected = False
        
        # Load initial config
        self.load_bot_config()
        
        # Start monitoring
        self.start_monitoring()
        
    def load_bot_config(self):
        """Load bot configuration"""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r') as f:
                    self.bot_config = json.load(f)
            else:
                # Default config based on goldtick5.py constants
                self.bot_config = {
                    "RISK_PERCENT_PER_TRADE": 0.03,
                    "MAX_SPREAD_POINTS": 25,
                    "RSI_OVERSOLD": 30,
                    "RSI_OVERBOUGHT": 70,
                    "SL_POINTS": 300,
                    "TP_POINTS": 1000,
                    "MAX_HOLD_TIME_SECONDS": 180,
                    "NUM_CONCURRENT_TRADES": 3,
                    "BREAK_EVEN_PROFIT_POINTS": 75,
                    "ATR_MULTIPLIER": 1.5,
                    "COOLDOWN_AFTER_TRADE_SECONDS": 300
                }
                self.save_bot_config()
        except Exception as e:
            print(f"Error loading config: {e}")
            
    def save_bot_config(self):
        """Save bot configuration"""
        try:
            with open(self.config_file, 'w') as f:
                json.dump(self.bot_config, f, indent=2)
            return True
        except Exception as e:
            print(f"Error saving config: {e}")
            return False
            
    def connect_mt5(self):
        """Connect to MT5 for real-time data"""
        try:
            if not mt5.initialize():
                print(f"MT5 initialization failed: {mt5.last_error()}")
                return False
                
            account_info = mt5.account_info()
            if not account_info:
                print("No MT5 account detected")
                return False
                
            self.mt5_connected = True
            print(f"Connected to MT5 account: {account_info.login}")
            return True
            
        except Exception as e:
            print(f"MT5 connection error: {e}")
            return False
            
    def parse_log_file(self):
        """Parse the bot's log file for new entries"""
        if not os.path.exists(self.bot_log_file):
            return
            
        try:
            with open(self.bot_log_file, 'r', encoding='utf-8') as f:
                f.seek(self.last_log_position)
                new_lines = f.readlines()
                self.last_log_position = f.tell()
                
            for line in new_lines:
                self.process_log_line(line.strip())
                
        except Exception as e:
            print(f"Error parsing log file: {e}")
            
    def process_log_line(self, line):
        """Process a single log line and extract relevant information"""
        if not line:
            return
            
        # Add to terminal messages
        self.add_terminal_message(line)
        
        # Parse trade entries
        if "TRADE ENTRY" in line:
            self.parse_trade_entry(line)
            
        # Parse trade closures
        elif "TRADE CLOSED" in line:
            self.parse_trade_closure(line)
            
        # Parse trade modifications
        elif "TRADE MODIFICATION" in line:
            self.parse_trade_modification(line)
            
        # Parse current state information
        elif any(keyword in line for keyword in ["Current Bar:", "RSI:", "Stoch:", "Live Prices:"]):
            self.parse_current_state(line)
            
    def add_terminal_message(self, line):
        """Add a message to terminal history"""
        # Parse timestamp and level from log line
        timestamp_match = re.search(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', line)
        level_match = re.search(r'- (INFO|WARNING|ERROR|DEBUG|CRITICAL) -', line)
        
        timestamp = timestamp_match.group(1) if timestamp_match else datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        level = level_match.group(1) if level_match else 'INFO'
        
        # Extract message content
        message = line
        if level_match:
            message = line[level_match.end():].strip()
            
        terminal_msg = {
            'timestamp': timestamp,
            'level': level,
            'message': message
        }
        
        self.terminal_messages.append(terminal_msg)
        
        # Keep only last 100 messages
        if len(self.terminal_messages) > 100:
            self.terminal_messages = self.terminal_messages[-100:]
            
    def parse_trade_entry(self, line):
        """Parse trade entry from log line"""
        try:
            # Example: "TRADE ENTRY - Ticket: 123456, Type: 0, Volume: 0.10, Price: 2025.50, SL: 2022.50, TP: 2035.50"
            patterns = {
                'ticket': r'Ticket: (\d+)',
                'type': r'Type: (\d+)',
                'volume': r'Volume: ([\d.]+)',
                'price': r'Price: ([\d.]+)',
                'sl': r'SL: ([\d.]+)',
                'tp': r'TP: ([\d.]+)'
            }
            
            trade_data = {'action': 'ENTRY', 'timestamp': datetime.now().isoformat()}
            
            for key, pattern in patterns.items():
                match = re.search(pattern, line)
                if match:
                    value = match.group(1)
                    if key in ['volume', 'price', 'sl', 'tp']:
                        trade_data[key] = float(value)
                    elif key == 'type':
                        trade_data['trade_type'] = 'BUY' if value == '0' else 'SELL'
                    else:
                        trade_data[key] = value
                        
            # Extract comment/reason
            comment_match = re.search(r'Comment: ([^.]+)', line)
            if comment_match:
                trade_data['reason'] = comment_match.group(1)
                
            self.trades_data.append(trade_data)
            
        except Exception as e:
            print(f"Error parsing trade entry: {e}")
            
    def parse_trade_closure(self, line):
        """Parse trade closure from log line"""
        try:
            # Example: "TRADE CLOSED - Ticket: 123456, P/L (USD): 15.50, P/L (Points): 25.00, Close Reason: TP_HIT"
            patterns = {
                'ticket': r'Ticket: (\d+)',
                'profit_usd': r'P/L \(USD\): ([-\d.]+)',
                'profit_points': r'P/L \(Points\): ([-\d.]+)',
                'reason': r'Close Reason: ([^.]+)'
            }
            
            trade_data = {'action': 'EXIT', 'timestamp': datetime.now().isoformat()}
            
            for key, pattern in patterns.items():
                match = re.search(pattern, line)
                if match:
                    value = match.group(1)
                    if key in ['profit_usd', 'profit_points']:
                        trade_data[key] = float(value)
                    else:
                        trade_data[key] = value
                        
            self.trades_data.append(trade_data)
            
            # Update performance metrics
            self.update_performance_metrics()
            
        except Exception as e:
            print(f"Error parsing trade closure: {e}")
            
    def parse_trade_modification(self, line):
        """Parse trade modification from log line"""
        try:
            # Example: "TRADE MODIFICATION - Ticket: 123456, Old SL: 2022.50, New SL: 2025.00"
            ticket_match = re.search(r'Ticket: (\d+)', line)
            if ticket_match:
                mod_data = {
                    'action': 'MODIFY',
                    'timestamp': datetime.now().isoformat(),
                    'ticket': ticket_match.group(1),
                    'message': line
                }
                self.trades_data.append(mod_data)
                
        except Exception as e:
            print(f"Error parsing trade modification: {e}")
            
    def parse_current_state(self, line):
        """Parse current state information from log line"""
        try:
            # Extract RSI, Stochastic, prices, etc.
            rsi_match = re.search(r'RSI: ([\d.]+)', line)
            if rsi_match:
                self.current_state['rsi'] = float(rsi_match.group(1))
                
            stoch_k_match = re.search(r'%K ([\d.]+)', line)
            if stoch_k_match:
                self.current_state['stoch_k'] = float(stoch_k_match.group(1))
                
            stoch_d_match = re.search(r'%D ([\d.]+)', line)
            if stoch_d_match:
                self.current_state['stoch_d'] = float(stoch_d_match.group(1))
                
            bid_match = re.search(r'Bid ([\d.]+)', line)
            if bid_match:
                self.current_state['bid'] = float(bid_match.group(1))
                
            ask_match = re.search(r'Ask ([\d.]+)', line)
            if ask_match:
                self.current_state['ask'] = float(ask_match.group(1))
                
            spread_match = re.search(r'Spread ([\d.]+)', line)
            if spread_match:
                self.current_state['spread'] = float(spread_match.group(1))
                
            positions_match = re.search(r'Open Positions: (\d+)', line)
            if positions_match:
                self.current_state['open_positions_count'] = int(positions_match.group(1))
                
        except Exception as e:
            print(f"Error parsing current state: {e}")
            
    def get_mt5_data(self):
        """Get real-time data from MT5"""
        if not self.mt5_connected:
            return
            
        try:
            # Get account info
            account_info = mt5.account_info()
            if account_info:
                self.current_state.update({
                    'account_balance': account_info.balance,
                    'account_equity': account_info.equity,
                    'account_margin': account_info.margin,
                    'account_margin_free': account_info.margin_free
                })
                
            # Get positions
            positions = mt5.positions_get(symbol="XAUUSD")
            if positions:
                self.current_state['open_positions_count'] = len(positions)
                self.current_state['positions'] = [
                    {
                        'ticket': pos.ticket,
                        'type': 'BUY' if pos.type == 0 else 'SELL',
                        'volume': pos.volume,
                        'price_open': pos.price_open,
                        'sl': pos.sl,
                        'tp': pos.tp,
                        'profit': pos.profit
                    } for pos in positions
                ]
            else:
                self.current_state['open_positions_count'] = 0
                self.current_state['positions'] = []
                
            # Get current symbol info
            symbol_info = mt5.symbol_info_tick("XAUUSD")
            if symbol_info:
                self.current_state.update({
                    'bid': symbol_info.bid,
                    'ask': symbol_info.ask,
                    'spread': (symbol_info.ask - symbol_info.bid) / 0.01,  # points
                    'symbol': 'XAUUSD'
                })
                
        except Exception as e:
            print(f"Error getting MT5 data: {e}")
            
    def update_performance_metrics(self):
        """Calculate performance metrics from trades data"""
        try:
            exit_trades = [t for t in self.trades_data if t.get('action') == 'EXIT' and 'profit_usd' in t]
            
            if not exit_trades:
                self.performance_metrics = {
                    'total_trades': 0,
                    'total_profit': 0.0,
                    'win_rate': 0.0,
                    'winning_trades': 0,
                    'losing_trades': 0,
                    'avg_win': 0.0,
                    'avg_loss': 0.0,
                    'profit_factor': 0.0
                }
                return
                
            total_profit = sum(t['profit_usd'] for t in exit_trades)
            winning_trades = [t for t in exit_trades if t['profit_usd'] > 0]
            losing_trades = [t for t in exit_trades if t['profit_usd'] < 0]
            
            win_rate = (len(winning_trades) / len(exit_trades)) * 100 if exit_trades else 0
            avg_win = sum(t['profit_usd'] for t in winning_trades) / len(winning_trades) if winning_trades else 0
            avg_loss = sum(t['profit_usd'] for t in losing_trades) / len(losing_trades) if losing_trades else 0
            
            gross_profit = sum(t['profit_usd'] for t in winning_trades)
            gross_loss = abs(sum(t['profit_usd'] for t in losing_trades))
            profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0
            
            self.performance_metrics = {
                'total_trades': len(exit_trades),
                'total_profit': total_profit,
                'win_rate': win_rate,
                'winning_trades': len(winning_trades),
                'losing_trades': len(losing_trades),
                'avg_win': avg_win,
                'avg_loss': avg_loss,
                'profit_factor': profit_factor,
                'gross_profit': gross_profit,
                'gross_loss': gross_loss
            }
            
        except Exception as e:
            print(f"Error updating performance metrics: {e}")
            
    def get_dashboard_data(self):
        """Get complete dashboard data"""
        self.current_state['bot_status'] = 'Running' if self.is_bot_running() else 'Stopped'
        self.current_state['last_update'] = datetime.now().isoformat()
        
        return {
            'current_state': self.current_state,
            'recent_trades': self.trades_data[-20:],  # Last 20 trades
            'terminal_messages': self.terminal_messages[-50:],  # Last 50 messages
            'performance_metrics': self.performance_metrics,
            'bot_config': self.bot_config,
            **self.performance_metrics  # Include metrics at top level for compatibility
        }
        
    def is_bot_running(self):
        """Check if bot is running based on recent log activity"""
        if not os.path.exists(self.bot_log_file):
            return False
            
        try:
            # Check if log file was modified in last 60 seconds
            last_modified = os.path.getmtime(self.bot_log_file)
            return (time.time() - last_modified) < 60
        except:
            return False
            
    def start_monitoring(self):
        """Start monitoring threads"""
        def monitor_loop():
            while True:
                try:
                    # Parse new log entries
                    self.parse_log_file()
                    
                    # Get MT5 data if connected
                    if self.mt5_connected:
                        self.get_mt5_data()
                    elif time.time() % 30 < 1:  # Try to reconnect every 30 seconds
                        self.connect_mt5()
                        
                    # Update performance metrics
                    self.update_performance_metrics()
                    
                    # Emit update to connected clients
                    dashboard_data = self.get_dashboard_data()
                    socketio.emit('dashboard_update', dashboard_data)
                    
                    time.sleep(2)  # Update every 2 seconds
                    
                except Exception as e:
                    print(f"Monitor loop error: {e}")
                    time.sleep(5)
                    
        # Start monitoring thread
        monitor_thread = threading.Thread(target=monitor_loop, daemon=True)
        monitor_thread.start()
        
        # Try initial MT5 connection
        self.connect_mt5()
        
        print("GoldTick5 monitor started")

# Initialize monitor
monitor = GoldTick5Monitor()

# Web Dashboard HTML
DASHBOARD_HTML = '''<!DOCTYPE html>
<html>
<head>
    <title>GoldTick5 Bot Monitor</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.0.1/socket.io.js"></script>
    <style>
        .status-indicator { width: 12px; height: 12px; border-radius: 50%; display: inline-block; margin-right: 8px; }
        .status-running { background-color: #28a745; animation: pulse 2s infinite; }
        .status-stopped { background-color: #dc3545; }
        .profit-positive { color: #28a745; font-weight: bold; }
        .profit-negative { color: #dc3545; font-weight: bold; }
        .metric-card { transition: transform 0.2s; border-left: 4px solid; }
        .metric-card:hover { transform: translateY(-2px); }
        .metric-card.profit { border-left-color: #28a745; }
        .metric-card.trades { border-left-color: #007bff; }
        .metric-card.winrate { border-left-color: #17a2b8; }
        @keyframes pulse { 0% { opacity: 1; } 50% { opacity: 0.5; } 100% { opacity: 1; } }
        .terminal-container {
            background-color: #1a1a1a; border-radius: 4px; font-family: 'Courier New', monospace;
            font-size: 11px; max-height: 400px; overflow: hidden;
        }
        .terminal-header {
            background-color: #2d2d2d; padding: 8px 12px; border-bottom: 1px solid #444;
            display: flex; justify-content: between; align-items: center;
        }
        .terminal-title { color: #fff; font-weight: bold; font-size: 11px; }
        .terminal-content { padding: 8px; height: 350px; overflow-y: auto; background-color: #1a1a1a; }
        .terminal-line { color: #e0e0e0; margin-bottom: 2px; font-size: 10px; line-height: 1.2; }
        .terminal-timestamp { color: #888; margin-right: 8px; }
        .terminal-level { margin-right: 8px; padding: 1px 4px; border-radius: 2px; font-weight: bold; font-size: 9px; }
        .terminal-level.INFO { background-color: #17a2b8; color: white; }
        .terminal-level.WARNING { background-color: #ffc107; color: black; }
        .terminal-level.ERROR { background-color: #dc3545; color: white; }
        .terminal-level.DEBUG { background-color: #6c757d; color: white; }
        .terminal-level.CRITICAL { background-color: #dc3545; color: white; animation: blink 1s infinite; }
        .terminal-message { color: #fff; }
        @keyframes blink { 0% { opacity: 1; } 50% { opacity: 0.5; } 100% { opacity: 1; } }
        .config-section { background-color: #f8f9fa; border-radius: 8px; padding: 15px; margin-bottom: 15px; }
    </style>
</head>
<body>
    <nav class="navbar navbar-expand-lg navbar-dark bg-dark">
        <div class="container-fluid">
            <span class="navbar-brand">
                <i class="fas fa-chart-line me-2"></i>GoldTick5 Bot Monitor
                <span class="badge bg-warning ms-2">LIVE</span>
            </span>
            <div class="navbar-nav ms-auto">
                <span class="nav-link">
                    <span id="connection-status" class="badge bg-secondary">Connecting...</span>
                </span>
            </div>
        </div>
    </nav>
    
    <div class="container-fluid mt-3">
        <!-- Bot Configuration Panel -->
        <div class="row mb-3">
            <div class="col-12">
                <div class="card">
                    <div class="card-header">
                        <h6 class="mb-0"><i class="fas fa-cogs me-2"></i>Bot Configuration</h6>
                    </div>
                    <div class="card-body">
                        <div class="row">
                            <div class="col-md-6">
                                <div class="config-section">
                                    <h6>Risk Management</h6>
                                    <div class="row">
                                        <div class="col-md-6">
                                            <label class="form-label small">Risk per Trade (%)</label>
                                            <input type="range" class="form-range" id="risk-slider" min="1" max="10" step="0.5" value="3"
                                                   oninput="updateDisplay('risk', this.value)">
                                            <small class="text-muted"><span id="risk-display">3.0</span>%</small>
                                        </div>
                                        <div class="col-md-6">
                                            <label class="form-label small">Stop Loss (points)</label>
                                            <input type="range" class="form-range" id="sl-slider" min="100" max="500" value="300"
                                                   oninput="updateDisplay('sl', this.value)">
                                            <small class="text-muted"><span id="sl-display">300</span> pts</small>
                                        </div>
                                    </div>
                                </div>
                                <div class="config-section">
                                    <h6>Entry Conditions</h6>
                                    <div class="row">
                                        <div class="col-md-4">
                                            <label class="form-label small">RSI Oversold</label>
                                            <input type="range" class="form-range" id="rsi-oversold-slider" min="20" max="40" value="30"
                                                   oninput="updateDisplay('rsi-oversold', this.value)">
                                            <small class="text-muted"><span id="rsi-oversold-display">30</span></small>
                                        </div>
                                        <div class="col-md-4">
                                            <label class="form-label small">RSI Overbought</label>
                                            <input type="range" class="form-range" id="rsi-overbought-slider" min="60" max="80" value="70"
                                                   oninput="updateDisplay('rsi-overbought', this.value)">
                                            <small class="text-muted"><span id="rsi-overbought-display">70</span></small>
                                        </div>
                                        <div class="col-md-4">
                                            <label class="form-label small">Max Spread (pts)</label>
                                            <input type="range" class="form-range" id="spread-slider" min="5" max="50" value="25"
                                                   oninput="updateDisplay('spread', this.value)">
                                            <small class="text-muted"><span id="spread-display">25</span> pts</small>
                                        </div>
                                    </div>
                                </div>
                            </div>
                            <div class="col-md-6">
                                <div class="config-section">
                                    <h6>Position Management</h6>
                                    <div class="row">
                                        <div class="col-md-6">
                                            <label class="form-label small">Max Positions</label>
                                            <input type="range" class="form-range" id="max-positions-slider" min="1" max="5" value="3"
                                                   oninput="updateDisplay('max-positions', this.value)">
                                            <small class="text-muted"><span id="max-positions-display">3</span> positions</small>
                                        </div>
                                        <div class="col-md-6">
                                            <label class="form-label small">Max Hold Time (min)</label>
                                            <input type="range" class="form-range" id="hold-time-slider" min="1" max="10" value="3"
                                                   oninput="updateDisplay('hold-time', this.value)">
                                            <small class="text-muted"><span id="hold-time-display">3</span> min</small>
                                        </div>
                                    </div>
                                </div>
                                <div class="config-section">
                                    <h6>Actions</h6>
                                    <div class="d-grid gap-2 d-md-flex">
                                        <button class="btn btn-success" onclick="applyConfig()">
                                            <i class="fas fa-save me-1"></i>Apply Config
                                        </button>
                                        <button class="btn btn-warning" onclick="loadCurrentConfig()">
                                            <i class="fas fa-download me-1"></i>Load Current
                                        </button>
                                        <button class="btn btn-info" onclick="resetToDefaults()">
                                            <i class="fas fa-undo me-1"></i>Reset
                                        </button>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
        
        <!-- Status and Quick Stats -->
        <div class="row mb-3">
            <div class="col-md-8">
                <div class="card">
                    <div class="card-header d-flex justify-content-between align-items-center">
                        <h5 class="mb-0">
                            <span id="status-indicator" class="status-indicator status-stopped"></span>
                            Bot Status: <span id="bot-status">Unknown</span>
                        </h5>
                        <div>
                            <small class="text-muted">Last Update: <span id="last-update">Never</span></small>
                        </div>
                    </div>
                    <div class="card-body">
                        <div class="row">
                            <div class="col-md-2">
                                <strong>Balance:</strong><br>$<span id="account-balance">0.00</span>
                            </div>
                            <div class="col-md-2">
                                <strong>Equity:</strong><br>$<span id="account-equity">0.00</span>
                            </div>
                            <div class="col-md-2">
                                <strong>Positions:</strong><br><span id="open-positions">0</span>
                            </div>
                            <div class="col-md-2">
                                <strong>Spread:</strong><br><span id="current-spread">0.0</span> pts
                            </div>
                            <div class="col-md-2">
                                <strong>RSI:</strong><br><span id="current-rsi">-</span>
                            </div>
                            <div class="col-md-2">
                                <strong>Price:</strong><br>$<span id="current-price">0.00</span>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
            <div class="col-md-4">
                <div class="card">
                    <div class="card-header">
                        <h6 class="mb-0">Quick Actions</h6>
                    </div>
                    <div class="card-body">
                        <div class="d-grid gap-2">
                            <button class="btn btn-primary btn-sm" onclick="refreshData()">
                                <i class="fas fa-sync-alt me-1"></i>Refresh Data
                            </button>
                            <button class="btn btn-secondary btn-sm" onclick="clearLogs()">
                                <i class="fas fa-broom me-1"></i>Clear Logs
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- Performance Metrics -->
        <div class="row mb-3">
            <div class="col-md-3">
                <div class="card metric-card profit">
                    <div class="card-body text-center">
                        <h4 id="total-profit" class="profit-positive">$0.00</h4>
                        <p class="text-muted mb-0">Total Profit</p>
                        <small class="text-muted">PF: <span id="profit-factor">0.00</span></small>
                    </div>
                </div>
            </div>
            <div class="col-md-3">
                <div class="card metric-card trades">
                    <div class="card-body text-center">
                        <h4 id="total-trades">0</h4>
                        <p class="text-muted mb-0">Total Trades</p>
                        <small class="text-muted"><span id="winning-trades">0</span>W / <span id="losing-trades">0</span>L</small>
                    </div>
                </div>
            </div>
            <div class="col-md-3">
                <div class="card metric-card winrate">
                    <div class="card-body text-center">
                        <h4 id="win-rate">0%</h4>
                        <p class="text-muted mb-0">Win Rate</p>
                        <small class="text-muted">Avg Win: $<span id="avg-win">0.00</span></small>
                    </div>
                </div>
            </div>
            <div class="col-md-3">
                <div class="card metric-card">
                    <div class="card-body text-center">
                        <h4 id="avg-loss" class="profit-negative">$0.00</h4>
                        <p class="text-muted mb-0">Avg Loss</p>
                        <small class="text-muted">Risk Ratio</small>
                    </div>
                </div>
            </div>
        </div>

        <!-- Main Content -->
        <div class="row">
            <!-- Recent Trades -->
            <div class="col-md-8">
                <div class="card">
                    <div class="card-header">
                        <h6 class="mb-0"><i class="fas fa-list me-2"></i>Recent Trades</h6>
                    </div>
                    <div class="card-body">
                        <div class="table-responsive">
                            <table class="table table-sm">
                                <thead>
                                    <tr>
                                        <th>Time</th>
                                        <th>Action</th>
                                        <th>Type</th>
                                        <th>Volume</th>
                                        <th>Price</th>
                                        <th>P/L</th>
                                        <th>Reason</th>
                                    </tr>
                                </thead>
                                <tbody id="trades-tbody">
                                    <tr><td colspan="7" class="text-center">No trades yet</td></tr>
                                </tbody>
                            </table>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Terminal -->
            <div class="col-md-4">
                <div class="card">
                    <div class="card-header">
                        <h6 class="mb-0"><i class="fas fa-terminal me-2"></i>Bot Terminal</h6>
                    </div>
                    <div class="card-body p-0">
                        <div class="terminal-container">
                            <div class="terminal-header">
                                <span class="terminal-title">GoldTick5 Bot Console</span>
                            </div>
                            <div class="terminal-content" id="terminal-content">
                                <div class="terminal-line">
                                    <span class="terminal-timestamp">[Loading...]</span>
                                    <span class="terminal-level INFO">INFO</span>
                                    <span class="terminal-message">Connecting to bot...</span>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <script>
        const socket = io();
        let lastConfigUpdate = 0;

        socket.on('connect', function() {
            console.log('Connected to GoldTick5 monitor');
            document.getElementById('connection-status').textContent = 'Connected';
            document.getElementById('connection-status').className = 'badge bg-success';
        });

        socket.on('dashboard_update', function(data) {
            updateDashboard(data);
        });

        function updateDisplay(type, value) {
            document.getElementById(type + '-display').textContent = 
                type === 'risk' ? parseFloat(value).toFixed(1) : 
                type === 'hold-time' ? value : value;
        }

        function updateDashboard(data) {
            const state = data.current_state || {};
            const metrics = data.performance_metrics || {};
            
            // Update bot status
            const botRunning = state.bot_status === 'Running';
            document.getElementById('bot-status').textContent = state.bot_status || 'Unknown';
            document.getElementById('status-indicator').className = 
                'status-indicator ' + (botRunning ? 'status-running' : 'status-stopped');
            
            // Update account info
            document.getElementById('account-balance').textContent = (state.account_balance || 0).toFixed(2);
            document.getElementById('account-equity').textContent = (state.account_equity || 0).toFixed(2);
            document.getElementById('open-positions').textContent = state.open_positions_count || 0;
            document.getElementById('current-spread').textContent = (state.spread || 0).toFixed(1);
            document.getElementById('current-rsi').textContent = state.rsi ? state.rsi.toFixed(1) : '-';
            document.getElementById('current-price').textContent = (state.bid || 0).toFixed(2);
            
            // Update performance metrics
            const totalProfit = metrics.total_profit || 0;
            document.getElementById('total-profit').textContent = '$' + totalProfit.toFixed(2);
            document.getElementById('total-profit').className = totalProfit >= 0 ? 'profit-positive' : 'profit-negative';
            
            document.getElementById('total-trades').textContent = metrics.total_trades || 0;
            document.getElementById('winning-trades').textContent = metrics.winning_trades || 0;
            document.getElementById('losing-trades').textContent = metrics.losing_trades || 0;
            document.getElementById('win-rate').textContent = (metrics.win_rate || 0).toFixed(1) + '%';
            document.getElementById('profit-factor').textContent = (metrics.profit_factor || 0).toFixed(2);
            document.getElementById('avg-win').textContent = (metrics.avg_win || 0).toFixed(2);
            document.getElementById('avg-loss').textContent = '$' + Math.abs(metrics.avg_loss || 0).toFixed(2);
            
            // Update last update time
            if (state.last_update) {
                const updateTime = new Date(state.last_update).toLocaleTimeString();
                document.getElementById('last-update').textContent = updateTime;
            }
            
            // Update trades table
            updateTradesTable(data.recent_trades || []);
            
            // Update terminal
            updateTerminal(data.terminal_messages || []);
        }

        function updateTradesTable(trades) {
            const tbody = document.getElementById('trades-tbody');
            
            if (trades.length === 0) {
                tbody.innerHTML = '<tr><td colspan="7" class="text-center">No trades yet</td></tr>';
                return;
            }
            
            tbody.innerHTML = trades.slice(-10).reverse().map(trade => {
                const time = new Date(trade.timestamp).toLocaleTimeString();
                const profit = parseFloat(trade.profit_usd || 0);
                const profitClass = profit >= 0 ? 'text-success' : 'text-danger';
                
                return `
                    <tr>
                        <td>${time}</td>
                        <td><span class="badge bg-${trade.action === 'ENTRY' ? 'primary' : 'secondary'}">${trade.action}</span></td>
                        <td><span class="badge bg-${trade.trade_type === 'BUY' ? 'success' : 'danger'}">${trade.trade_type || '-'}</span></td>
                        <td>${trade.volume || '-'}</td>
                        <td>${(trade.price || 0).toFixed(2)}</td>
                        <td class="${profitClass}">$${profit.toFixed(2)}</td>
                        <td><small>${trade.reason || '-'}</small></td>
                    </tr>
                `;
            }).join('');
        }

        function updateTerminal(messages) {
            const terminalContent = document.getElementById('terminal-content');
            
            if (messages.length === 0) {
                terminalContent.innerHTML = `
                    <div class="terminal-line">
                        <span class="terminal-timestamp">[${new Date().toLocaleTimeString()}]</span>
                        <span class="terminal-level INFO">INFO</span>
                        <span class="terminal-message">Waiting for bot messages...</span>
                    </div>
                `;
                return;
            }
            
            const recentMessages = messages.slice(-30);
            
            terminalContent.innerHTML = recentMessages.map(msg => {
                const time = new Date(msg.timestamp).toLocaleTimeString();
                const level = (msg.level || 'INFO').toUpperCase();
                
                return `
                    <div class="terminal-line">
                        <span class="terminal-timestamp">[${time}]</span>
                        <span class="terminal-level ${level}">${level}</span>
                        <span class="terminal-message">${msg.message}</span>
                    </div>
                `;
            }).join('');
            
            terminalContent.scrollTop = terminalContent.scrollHeight;
        }

        function loadCurrentConfig() {
            fetch('/api/config')
                .then(r => r.json())
                .then(config => {
                    document.getElementById('risk-slider').value = (config.RISK_PERCENT_PER_TRADE || 0.03) * 100;
                    document.getElementById('sl-slider').value = config.SL_POINTS || 300;
                    document.getElementById('rsi-oversold-slider').value = config.RSI_OVERSOLD || 30;
                    document.getElementById('rsi-overbought-slider').value = config.RSI_OVERBOUGHT || 70;
                    document.getElementById('spread-slider').value = config.MAX_SPREAD_POINTS || 25;
                    document.getElementById('max-positions-slider').value = config.NUM_CONCURRENT_TRADES || 3;
                    document.getElementById('hold-time-slider').value = (config.MAX_HOLD_TIME_SECONDS || 180) / 60;
                    
                    // Update displays
                    updateDisplay('risk', document.getElementById('risk-slider').value);
                    updateDisplay('sl', document.getElementById('sl-slider').value);
                    updateDisplay('rsi-oversold', document.getElementById('rsi-oversold-slider').value);
                    updateDisplay('rsi-overbought', document.getElementById('rsi-overbought-slider').value);
                    updateDisplay('spread', document.getElementById('spread-slider').value);
                    updateDisplay('max-positions', document.getElementById('max-positions-slider').value);
                    updateDisplay('hold-time', document.getElementById('hold-time-slider').value);
                    
                    showAlert('Current configuration loaded', 'success');
                })
                .catch(e => showAlert('Error loading config: ' + e.message, 'danger'));
        }

        function applyConfig() {
            const config = {
                RISK_PERCENT_PER_TRADE: parseFloat(document.getElementById('risk-slider').value) / 100,
                SL_POINTS: parseInt(document.getElementById('sl-slider').value),
                RSI_OVERSOLD: parseInt(document.getElementById('rsi-oversold-slider').value),
                RSI_OVERBOUGHT: parseInt(document.getElementById('rsi-overbought-slider').value),
                MAX_SPREAD_POINTS: parseInt(document.getElementById('spread-slider').value),
                NUM_CONCURRENT_TRADES: parseInt(document.getElementById('max-positions-slider').value),
                MAX_HOLD_TIME_SECONDS: parseInt(document.getElementById('hold-time-slider').value) * 60
            };

            fetch('/api/config', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(config)
            })
            .then(r => r.json())
            .then(data => {
                if (data.status === 'success') {
                    showAlert('Configuration applied successfully!', 'success');
                } else {
                    showAlert('Error applying configuration', 'danger');
                }
            })
            .catch(e => showAlert('Error: ' + e.message, 'danger'));
        }

        function resetToDefaults() {
            document.getElementById('risk-slider').value = 3;
            document.getElementById('sl-slider').value = 300;
            document.getElementById('rsi-oversold-slider').value = 30;
            document.getElementById('rsi-overbought-slider').value = 70;
            document.getElementById('spread-slider').value = 25;
            document.getElementById('max-positions-slider').value = 3;
            document.getElementById('hold-time-slider').value = 3;
            
            updateDisplay('risk', 3);
            updateDisplay('sl', 300);
            updateDisplay('rsi-oversold', 30);
            updateDisplay('rsi-overbought', 70);
            updateDisplay('spread', 25);
            updateDisplay('max-positions', 3);
            updateDisplay('hold-time', 3);
            
            showAlert('Reset to default values', 'info');
        }

        function refreshData() {
            fetch('/api/dashboard').then(r => r.json()).then(updateDashboard).catch(console.error);
        }

        function clearLogs() {
            if (confirm('Clear terminal logs?')) {
                const terminalContent = document.getElementById('terminal-content');
                terminalContent.innerHTML = `
                    <div class="terminal-line">
                        <span class="terminal-timestamp">[${new Date().toLocaleTimeString()}]</span>
                        <span class="terminal-level INFO">INFO</span>
                        <span class="terminal-message">Logs cleared by user</span>
                    </div>
                `;
                showAlert('Logs cleared', 'info');
            }
        }

        function showAlert(message, type) {
            const alertDiv = document.createElement('div');
            alertDiv.className = `alert alert-${type} alert-dismissible fade show position-fixed`;
            alertDiv.style.cssText = 'top: 20px; right: 20px; z-index: 9999; min-width: 300px;';
            alertDiv.innerHTML = `
                ${message}
                <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
            `;
            document.body.appendChild(alertDiv);
            
            setTimeout(() => {
                if (alertDiv.parentNode) alertDiv.parentNode.removeChild(alertDiv);
            }, 5000);
        }

        // Initial load
        loadCurrentConfig();
        refreshData();
        
        // Auto-refresh every 10 seconds
        setInterval(refreshData, 10000);
    </script>
</body>
</html>'''

# Routes
@app.route('/')
def dashboard():
    return DASHBOARD_HTML

@app.route('/api/dashboard')
def api_dashboard():
    try:
        return jsonify(monitor.get_dashboard_data())
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/config', methods=['GET', 'POST'])
def api_config():
    try:
        if request.method == 'GET':
            return jsonify(monitor.bot_config)
        else:
            new_config = request.json
            monitor.bot_config.update(new_config)
            if monitor.save_bot_config():
                return jsonify({'status': 'success'})
            else:
                return jsonify({'status': 'error'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Socket.IO events
@socketio.on('connect')
def handle_connect():
    print('Client connected to GoldTick5 monitor')
    try:
        data = monitor.get_dashboard_data()
        emit('dashboard_update', data)
    except Exception as e:
        print(f"Error sending initial data: {e}")

if __name__ == '__main__':
    print("\n" + "="*70)
    print("GoldTick5 Bot Web Interface Monitor")
    print("="*70)
    print(f"Monitoring log file: {monitor.bot_log_file}")
    print(f"Configuration file: {monitor.config_file}")
    print(f"MT5 Connection: {'Active' if monitor.mt5_connected else 'Inactive'}")
    print("="*70)
    print("Dashboard: http://localhost:5000")
    print("This interface monitors your live GoldTick5 bot")
    print("="*70)
    
    try:
        socketio.run(app, host='0.0.0.0', port=5000, debug=False, allow_unsafe_werkzeug=True)
    except Exception as e:
        print(f"Error starting web interface: {e}")
    finally:
        if monitor.mt5_connected:
            mt5.shutdown()