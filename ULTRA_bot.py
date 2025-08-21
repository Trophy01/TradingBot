import MetaTrader5 as mt5
import pandas as pd
import time
import json
from datetime import datetime, timedelta
import os
import pytz
import numpy as np
import logging
from pathlib import Path

# Setup logging
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s',
                    handlers=[
                        logging.FileHandler("gold_scalper_bot.log"),
                        logging.StreamHandler()
                    ])

class GoldScalperBot:
    """
    Fixed Gold Trading Bot using the Enhanced Algorithm
    Uses M1 timeframe with clean RSI + Stochastic + Trend Filter logic
    """

    def __init__(self):
        # Enhanced Configuration - Much More Conservative
        self.SYMBOL = "XAUUSD"
        self.RSI_PERIOD = 14
        self.RSI_OVERBOUGHT = 70  # Conservative levels
        self.RSI_OVERSOLD = 30
        
        # Stochastic Settings
        self.K_PERIOD = 14
        self.D_PERIOD = 3
        self.STOCHASTIC_OVERBOUGHT = 80
        self.STOCHASTIC_OVERSOLD = 20
        
        # MUCH MORE CONSERVATIVE Risk Management
        self.SL_POINTS = 300      # Same SL
        self.TP_POINTS = 600      # Better 2:1 RR ratio
        self.MAGIC_NUMBER = 12345
        self.RISK_PERCENT_PER_TRADE = 0.01  # 1% risk instead of 3%
        self.MAX_SPREAD_POINTS = 30  # Tighter spread control
        self.NUM_CONCURRENT_TRADES = 1    # Only 1 position at a time
        self.TRADE_ENTRY_COOLDOWN_SECONDS = 60  # 1 minute between trades
        
        # ATR Settings for dynamic TP
        self.ATR_PERIOD = 20
        self.USE_DYNAMIC_TP = True
        self.ATR_TP_MULTIPLIER = 2.0
        self.MIN_DYNAMIC_TP_POINTS = 400  # Larger minimum TP
        self.MAX_DYNAMIC_TP_POINTS = 1000
        
        # Trend Filter Settings (Simplified)
        self.TREND_MA_PERIOD = 50  # Shorter MA for responsiveness
        self.USE_TREND_FILTER = True
        
        # Cooldown Configuration
        self.COOLDOWN_AFTER_TRADE_SECONDS = 300
        self.COOLDOWN_LOSS_THRESHOLD_USD = 0.01
        
        # MT5 Path
        self.MT5_PATH = r"C:\Program Files\MetaTrader 5\terminal64.exe"
        
        # Web interface integration
        self.web_data_dir = Path("web_data")
        self.web_data_dir.mkdir(exist_ok=True)
        
        # Initialize tracking variables
        self.symbol_info = None
        self.point_value = 0.0
        self.last_trade_time = 0
        self.last_trade_closed_timestamp = 0
        self.trades_data = []
        self.tracked_positions = {}
        self.timezone = pytz.timezone("Etc/UTC")
        
        # Load configuration
        self.load_configuration()
        self.load_existing_data()
        
        logging.info("Enhanced Algorithm Gold Trading Bot initialized")
        
    def load_configuration(self):
        """Load configuration from web interface"""
        try:
            config_file = self.web_data_dir / "config.json"
            if config_file.exists():
                with open(config_file, 'r') as f:
                    config = json.load(f)
                    
                # Update settings from web interface (with safety caps)
                if 'RISK_PERCENT_PER_TRADE' in config:
                    self.RISK_PERCENT_PER_TRADE = min(config['RISK_PERCENT_PER_TRADE'], 0.015)  # Cap at 1.5%
                if 'MAX_SPREAD_POINTS' in config:
                    self.MAX_SPREAD_POINTS = config['MAX_SPREAD_POINTS']
                if 'RSI_OVERSOLD' in config:
                    self.RSI_OVERSOLD = max(config['RSI_OVERSOLD'], 25)  # Minimum 25
                if 'RSI_OVERBOUGHT' in config:
                    self.RSI_OVERBOUGHT = min(config['RSI_OVERBOUGHT'], 75)  # Maximum 75
                    
                self.send_terminal_message('INFO', f'Config loaded: Risk {self.RISK_PERCENT_PER_TRADE*100:.1f}%, RSI {self.RSI_OVERSOLD}-{self.RSI_OVERBOUGHT}')
        except Exception as e:
            logging.error(f"Error loading config: {e}")
    
    def load_existing_data(self):
        """Load existing trade data"""
        try:
            trades_file = self.web_data_dir / "trades.json"
            if trades_file.exists():
                with open(trades_file, 'r') as f:
                    self.trades_data = json.load(f)
        except Exception as e:
            logging.error(f"Error loading data: {e}")
    
    def send_terminal_message(self, level: str, message: str):
        """Send message to web terminal"""
        try:
            terminal_file = self.web_data_dir / "terminal_messages.json"
            
            # Load existing messages
            messages = []
            if terminal_file.exists():
                with open(terminal_file, 'r') as f:
                    messages = json.load(f)
            
            # Add new message
            new_message = {
                'timestamp': datetime.now().isoformat(),
                'level': level,
                'message': message
            }
            messages.append(new_message)
            
            # Keep only last 100 messages
            if len(messages) > 100:
                messages = messages[-100:]
            
            # Save messages
            with open(terminal_file, 'w') as f:
                json.dump(messages, f, indent=2)
                
            # Also log to console
            logging.info(f"{level}: {message}")
            
        except Exception as e:
            logging.error(f"Terminal message error: {e}")
    
    def save_trade_data(self, trade_data):
        """Save trade data for web interface"""
        try:
            self.trades_data.append(trade_data)
            
            # Keep only last 100 trades
            if len(self.trades_data) > 100:
                self.trades_data = self.trades_data[-100:]
            
            with open(self.web_data_dir / "trades.json", 'w') as f:
                json.dump(self.trades_data, f, indent=2)
                
            # Update performance data after each trade
            self.update_performance_data()
                
        except Exception as e:
            logging.error(f"Error saving trade data: {e}")
    
    def update_performance_data(self):
        """Update performance metrics for web interface"""
        try:
            # Calculate performance from trades data
            exit_trades = [t for t in self.trades_data if t.get('action') == 'EXIT']
            
            total_profit = sum(float(t.get('profit_usd', 0)) for t in exit_trades)
            total_loss = sum(float(t.get('profit_usd', 0)) for t in exit_trades if float(t.get('profit_usd', 0)) < 0)
            winning_trades = [t for t in exit_trades if float(t.get('profit_usd', 0)) > 0]
            losing_trades = [t for t in exit_trades if float(t.get('profit_usd', 0)) < 0]
            
            win_rate = (len(winning_trades) / max(1, len(exit_trades))) * 100 if exit_trades else 0
            
            # Calculate additional metrics
            avg_win = np.mean([float(t.get('profit_usd', 0)) for t in winning_trades]) if winning_trades else 0
            avg_loss = np.mean([float(t.get('profit_usd', 0)) for t in losing_trades]) if losing_trades else 0
            
            performance_data = {
                'total_trades': len(exit_trades),
                'winning_trades': len(winning_trades),
                'losing_trades': len(losing_trades),
                'total_profit': total_profit,
                'total_loss': abs(total_loss),
                'net_profit': total_profit,
                'win_rate': win_rate,
                'avg_win': avg_win,
                'avg_loss': avg_loss,
                'profit_factor': abs(avg_win / avg_loss) if avg_loss != 0 else 0,
                'last_updated': datetime.now().isoformat()
            }
            
            with open(self.web_data_dir / "performance.json", 'w') as f:
                json.dump(performance_data, f, indent=2)
                
        except Exception as e:
            logging.error(f"Error updating performance data: {e}")
    
    def update_current_state(self):
        """Update current state for web interface"""
        try:
            account_info = mt5.account_info()
            symbol_tick = mt5.symbol_info_tick(self.SYMBOL)
            positions = mt5.positions_get(symbol=self.SYMBOL)
            
            state = {
                "bot_status": "RUNNING",
                "symbol": self.SYMBOL,
                "account_balance": account_info.balance if account_info else 0,
                "account_equity": account_info.equity if account_info else 0,
                "open_positions_count": len(positions) if positions else 0,
                "current_bid": symbol_tick.bid if symbol_tick else 0,
                "current_ask": symbol_tick.ask if symbol_tick else 0,
                "current_spread": (symbol_tick.ask - symbol_tick.bid) / self.point_value if symbol_tick and self.point_value else 0,
                "last_updated": datetime.now().isoformat()
            }
            
            with open(self.web_data_dir / "current_state.json", 'w') as f:
                json.dump(state, f, indent=2)
                
        except Exception as e:
            logging.error(f"Error updating state: {e}")

    def connect_mt5(self):
        """Establishes connection to MetaTrader 5 terminal."""
        logging.info(f"Attempting to connect to MT5 at path: {self.MT5_PATH}")
        if not os.path.exists(self.MT5_PATH):
            logging.error(f"Error: MT5 executable not found at '{self.MT5_PATH}'. Please verify the path.")
            return False

        if not mt5.initialize(path=self.MT5_PATH):
            logging.error(f"Failed to initialize MT5. Last error: {mt5.last_error()}")
            return False
        logging.info("MT5 initialized successfully.")

        account_info = mt5.account_info()
        if not account_info:
            logging.error("Error: No account detected as logged into MT5 terminal.")
            mt5.shutdown()
            return False

        logging.info(f"Successfully connected to MT5. Account: {account_info.login}, Balance: {account_info.balance:.2f}")
        return True

    def disconnect_mt5(self):
        """Disconnects from MetaTrader 5 terminal."""
        mt5.shutdown()
        logging.info("MT5 disconnected.")

    # ENHANCED ALGORITHM - Clean and Simple
    def calculate_rsi(self, prices, period=14):
        """Calculate RSI using the enhanced algorithm"""
        if len(prices) < period + 1:
            return None
            
        deltas = np.diff(prices)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        
        avg_gain = np.mean(gains[:period])
        avg_loss = np.mean(losses[:period])
        
        if avg_loss == 0:
            return 100
            
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return rsi
    
    def calculate_stochastic(self, highs, lows, closes, k_period=14, d_period=3):
        """Calculate Stochastic Oscillator using enhanced algorithm"""
        if len(closes) < k_period + d_period:
            return None, None
            
        # Calculate %K
        lowest_lows = []
        highest_highs = []
        
        for i in range(k_period - 1, len(closes)):
            period_low = min(lows[i - k_period + 1:i + 1])
            period_high = max(highs[i - k_period + 1:i + 1])
            lowest_lows.append(period_low)
            highest_highs.append(period_high)
        
        if not lowest_lows or not highest_highs:
            return None, None
            
        k_values = []
        for i, close in enumerate(closes[k_period - 1:]):
            if highest_highs[i] == lowest_lows[i]:
                k_values.append(50)
            else:
                k = 100 * (close - lowest_lows[i]) / (highest_highs[i] - lowest_lows[i])
                k_values.append(k)
        
        if len(k_values) < d_period:
            return k_values[-1] if k_values else None, None
            
        # Calculate %D (SMA of %K)
        d_value = np.mean(k_values[-d_period:])
        
        return k_values[-1], d_value
    
    def calculate_atr(self, highs, lows, closes, period=20):
        """Calculate Average True Range"""
        if len(closes) < period + 1:
            return None
            
        true_ranges = []
        for i in range(1, len(closes)):
            high_low = highs[i] - lows[i]
            high_prev_close = abs(highs[i] - closes[i-1])
            low_prev_close = abs(lows[i] - closes[i-1])
            true_range = max(high_low, high_prev_close, low_prev_close)
            true_ranges.append(true_range)
            
        if len(true_ranges) >= period:
            return np.mean(true_ranges[-period:])
        return None
    
    def calculate_moving_average(self, prices, period):
        """Calculate Simple Moving Average"""
        if len(prices) < period:
            return None
        return np.mean(prices[-period:])
    
    def get_market_data(self):
        """Get market data using M1 timeframe (enhanced algorithm)"""
        try:
            # Get M1 bars instead of complex tick analysis
            required_bars = max(self.RSI_PERIOD, self.K_PERIOD, self.ATR_PERIOD, self.TREND_MA_PERIOD) + 10
            rates = mt5.copy_rates_from_pos(self.SYMBOL, mt5.TIMEFRAME_M1, 0, required_bars)
            
            if rates is None or len(rates) < required_bars:
                return None
            
            df = pd.DataFrame(rates)
            
            # Extract price arrays
            closes = df['close'].values
            highs = df['high'].values
            lows = df['low'].values
            
            # Calculate indicators
            current_price = closes[-1]
            rsi = self.calculate_rsi(closes, self.RSI_PERIOD)
            stoch_k, stoch_d = self.calculate_stochastic(highs, lows, closes, self.K_PERIOD, self.D_PERIOD)
            atr = self.calculate_atr(highs, lows, closes, self.ATR_PERIOD)
            ma = self.calculate_moving_average(closes, self.TREND_MA_PERIOD)
            
            # Get current spread
            tick = mt5.symbol_info_tick(self.SYMBOL)
            spread = (tick.ask - tick.bid) / self.point_value if tick else 0
            
            return {
                'price': current_price,
                'rsi': rsi,
                'stoch_k': stoch_k,
                'stoch_d': stoch_d,
                'atr': atr,
                'ma': ma,
                'spread': spread,
                'tick': tick
            }
            
        except Exception as e:
            logging.error(f"Error getting market data: {e}")
            return None
    
    def calculate_safe_lot_size(self):
        """Calculate very conservative position size"""
        try:
            account_info = mt5.account_info()
            if not account_info:
                return 0.01
            
            # Much more conservative approach
            free_margin = account_info.margin_free
            equity = account_info.equity
            
            # Calculate risk amount (very conservative)
            risk_amount = min(equity * self.RISK_PERCENT_PER_TRADE, free_margin * 0.05)  # Max 5% of free margin
            
            # Calculate lot size based on SL points
            point_value_usd = self.symbol_info.trade_contract_size * self.point_value
            risk_per_lot = self.SL_POINTS * point_value_usd
            
            if risk_per_lot <= 0:
                return 0.01
            
            lot_size = risk_amount / risk_per_lot
            
            # Apply strict safety limits
            min_lot = max(self.symbol_info.volume_min, 0.01)
            max_lot = min(self.symbol_info.volume_max, 0.05)  # Cap at 0.05 lots
            lot_step = self.symbol_info.volume_step
            
            lot_size = max(min_lot, round(lot_size / lot_step) * lot_step)
            lot_size = min(max_lot, lot_size)
            
            # Final safety check
            required_margin = lot_size * self.symbol_info.margin_required
            if required_margin > free_margin * 0.3:  # Use max 30% of free margin
                lot_size = (free_margin * 0.3) / self.symbol_info.margin_required
                lot_size = max(min_lot, round(lot_size / lot_step) * lot_step)
            
            return lot_size
            
        except Exception as e:
            logging.error(f"Error calculating lot size: {e}")
            return 0.01
    
    def check_trade_conditions(self, market_data):
        """ENHANCED ALGORITHM - Clean trade condition checking"""
        if not market_data or any(v is None for v in [market_data['rsi'], market_data['stoch_k'], market_data['stoch_d']]):
            return None, None
        
        price = market_data['price']
        rsi = market_data['rsi']
        stoch_k = market_data['stoch_k']
        stoch_d = market_data['stoch_d']
        ma = market_data['ma']
        
        # Check spread
        if market_data['spread'] > self.MAX_SPREAD_POINTS:
            return None, f"Spread too wide: {market_data['spread']:.1f} > {self.MAX_SPREAD_POINTS}"
        
        # Check cooldown
        if time.time() - self.last_trade_time < self.TRADE_ENTRY_COOLDOWN_SECONDS:
            return None, "Trade cooldown active"
            
        # Check loss cooldown
        if (time.time() - self.last_trade_closed_timestamp) < self.COOLDOWN_AFTER_TRADE_SECONDS:
            return None, "Loss cooldown active"
        
        # CLEAN BUY CONDITIONS (Enhanced Algorithm)
        buy_conditions = [
            rsi < self.RSI_OVERSOLD,
            stoch_k < self.STOCHASTIC_OVERSOLD,
            stoch_k > stoch_d  # Stochastic starting to turn up
        ]
        
        # Add trend filter if enabled
        if self.USE_TREND_FILTER and ma is not None:
            buy_conditions.append(price > ma * 0.999)  # Allow small deviation below MA
        
        # CLEAN SELL CONDITIONS (Enhanced Algorithm)
        sell_conditions = [
            rsi > self.RSI_OVERBOUGHT,
            stoch_k > self.STOCHASTIC_OVERBOUGHT,
            stoch_k < stoch_d  # Stochastic starting to turn down
        ]
        
        # Add trend filter if enabled
        if self.USE_TREND_FILTER and ma is not None:
            sell_conditions.append(price < ma * 1.001)  # Allow small deviation above MA
        
        # Check BUY signal
        if all(buy_conditions):
            reason = f"RSI oversold ({rsi:.1f}), Stochastic oversold ({stoch_k:.1f}>{stoch_d:.1f})"
            if self.USE_TREND_FILTER:
                reason += f", Price above MA ({price:.2f}>{ma:.2f})"
            return "BUY", reason
        
        # Check SELL signal
        if all(sell_conditions):
            reason = f"RSI overbought ({rsi:.1f}), Stochastic overbought ({stoch_k:.1f}<{stoch_d:.1f})"
            if self.USE_TREND_FILTER:
                reason += f", Price below MA ({price:.2f}<{ma:.2f})"
            return "SELL", reason
        
        return None, f"No signal: RSI {rsi:.1f}, Stoch {stoch_k:.1f}/{stoch_d:.1f}"
    
    def calculate_dynamic_tp(self, atr):
        """Calculate dynamic take profit based on ATR"""
        if not self.USE_DYNAMIC_TP or atr is None:
            return self.TP_POINTS
        
        # Calculate TP in points based on ATR
        atr_points = atr / self.point_value
        dynamic_tp = atr_points * self.ATR_TP_MULTIPLIER
        
        # Apply limits
        dynamic_tp = max(self.MIN_DYNAMIC_TP_POINTS, min(self.MAX_DYNAMIC_TP_POINTS, dynamic_tp))
        
        return int(dynamic_tp)
    
    def send_order(self, order_type, price, volume, sl, tp, comment):
        """Send trade order with enhanced error handling"""
        try:
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": self.SYMBOL,
                "volume": volume,
                "type": order_type,
                "price": price,
                "sl": sl,
                "tp": tp,
                "deviation": 20,
                "magic": self.MAGIC_NUMBER,
                "comment": comment,
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            }
            
            result = mt5.order_send(request)
            
            if result.retcode == mt5.TRADE_RETCODE_DONE:
                trade_type = "BUY" if order_type == mt5.ORDER_TYPE_BUY else "SELL"
                self.send_terminal_message('SUCCESS', 
                    f'{trade_type} ORDER: {volume} lots at {price:.2f} | SL: {sl:.2f} | TP: {tp:.2f} | {comment}')
                
                # Save trade data
                trade_data = {
                    "timestamp": datetime.now().isoformat(),
                    "trade_id": result.order,
                    "action": "ENTRY",
                    "trade_type": trade_type,
                    "volume": volume,
                    "entry_price": price,
                    "sl": sl,
                    "tp": tp,
                    "reason": comment
                }
                self.save_trade_data(trade_data)
                self.last_trade_time = time.time()
                
                return True
            else:
                error_msg = f'ORDER FAILED: {result.comment} (Code: {result.retcode})'
                if result.retcode == 10019:
                    error_msg += f' | Insufficient margin'
                self.send_terminal_message('ERROR', error_msg)
                return False
                
        except Exception as e:
            self.send_terminal_message('ERROR', f'ORDER ERROR: {e}')
            return False
    
    def monitor_positions(self):
        """Monitor and track position closures"""
        try:
            # Get current positions
            positions = mt5.positions_get(symbol=self.SYMBOL)
            current_tickets = {pos.ticket for pos in positions} if positions else set()
            
            # Check for closed positions
            for ticket in list(self.tracked_positions.keys()):
                if ticket not in current_tickets:
                    # Position was closed
                    position_data = self.tracked_positions.pop(ticket)
                    
                    # Get deal history to find closure details
                    to_time = datetime.now()
                    from_time = to_time - timedelta(minutes=5)
                    deals = mt5.history_deals_get(from_time, to_time)
                    
                    if deals:
                        for deal in deals:
                            if (deal.position_id == ticket and 
                                deal.entry == mt5.DEAL_ENTRY_OUT):
                                
                                profit_points = deal.profit / (self.symbol_info.trade_contract_size * self.point_value)
                                
                                self.send_terminal_message(
                                    'SUCCESS' if deal.profit > 0 else 'WARNING',
                                    f'POSITION CLOSED: #{ticket} | P&L: ${deal.profit:.2f} ({profit_points:.1f} pts)'
                                )
                                
                                # Check if loss triggers cooldown
                                if deal.profit < -self.COOLDOWN_LOSS_THRESHOLD_USD:
                                    self.last_trade_closed_timestamp = time.time()
                                    self.send_terminal_message('WARNING', 'Loss cooldown activated')
                                
                                # Save exit trade data
                                trade_data = {
                                    "timestamp": datetime.now().isoformat(),
                                    "trade_id": ticket,
                                    "action": "EXIT",
                                    "trade_type": position_data.get('type', 'UNKNOWN'),
                                    "volume": deal.volume,
                                    "exit_price": deal.price,
                                    "profit_usd": deal.profit,
                                    "profit_points": profit_points,
                                    "reason": "TP/SL Hit"
                                }
                                self.save_trade_data(trade_data)
                                break
            
            # Track new positions
            if positions:
                for pos in positions:
                    if pos.ticket not in self.tracked_positions:
                        self.tracked_positions[pos.ticket] = {
                            'type': 'BUY' if pos.type == mt5.POSITION_TYPE_BUY else 'SELL',
                            'open_time': datetime.now(),
                            'volume': pos.volume
                        }
                        
        except Exception as e:
            logging.error(f"Error monitoring positions: {e}")

    def run_scalping_bot(self):
        """Main trading loop using enhanced algorithm"""
        if not self.connect_mt5():
            logging.critical("Failed to connect to MT5. Exiting bot.")
            return

        if not mt5.symbol_select(self.SYMBOL, True):
            logging.error(f"Error: {self.SYMBOL} not found in Market Watch.")
            self.disconnect_mt5()
            return

        self.symbol_info = mt5.symbol_info(self.SYMBOL)
        if self.symbol_info is None:
            logging.critical(f"Error: Could not get symbol info for {self.SYMBOL}.")
            self.disconnect_mt5()
            return

        self.point_value = self.symbol_info.point
        
        self.send_terminal_message('SUCCESS', 'Enhanced Algorithm Trading Bot Started')
        self.send_terminal_message('INFO', 
            f'Settings: Risk {self.RISK_PERCENT_PER_TRADE*100:.1f}%, RSI {self.RSI_OVERSOLD}-{self.RSI_OVERBOUGHT}, Max Pos: {self.NUM_CONCURRENT_TRADES}')
        
        # Check account
        account_info = mt5.account_info()
        if account_info:
            self.send_terminal_message('SUCCESS', 
                f'Account {account_info.login} | Balance: ${account_info.balance:.2f}')

        iteration_count = 0
        
        try:
            while True:
                iteration_count += 1
                
                # Reload configuration every 60 iterations
                if iteration_count % 60 == 0:
                    self.load_configuration()
                
                # Get market data using M1 timeframe (enhanced algorithm)
                market_data = self.get_market_data()
                
                if not market_data:
                    self.send_terminal_message('WARNING', 'Failed to get market data')
                    time.sleep(5)
                    continue
                
                # Update web interface every 10 iterations
                if iteration_count % 10 == 0:
                    self.update_current_state()
                
                # Get current positions
                positions = mt5.positions_get(symbol=self.SYMBOL)
                num_positions = len(positions) if positions else 0
                
                # Monitor position closures
                self.monitor_positions()
                
                # Log status every 30 seconds
                if iteration_count % 30 == 1:
                    self.send_terminal_message('INFO', 
                        f'Market: ${market_data["price"]:.2f} | RSI: {market_data["rsi"]:.1f} | ' +
                        f'Stoch: {market_data["stoch_k"]:.1f}/{market_data["stoch_d"]:.1f} | ' +
                        f'Spread: {market_data["spread"]:.1f}pts | Pos: {num_positions}')
                
                # Check if we can trade
                if num_positions >= self.NUM_CONCURRENT_TRADES:
                    if iteration_count % 60 == 1:
                        self.send_terminal_message('INFO', f'Max positions reached: {num_positions}')
                    time.sleep(2)
                    continue
                
                # Check trade conditions using enhanced algorithm
                signal, reason = self.check_trade_conditions(market_data)
                
                if signal == "BUY":
                    tick = market_data['tick']
                    price = tick.ask
                    lot_size = self.calculate_safe_lot_size()
                    
                    if lot_size >= self.symbol_info.volume_min:
                        sl_price = price - (self.SL_POINTS * self.point_value)
                        tp_points = self.calculate_dynamic_tp(market_data['atr'])
                        tp_price = price + (tp_points * self.point_value)
                        
                        self.send_terminal_message('INFO', f'BUY SIGNAL: {reason}')
                        if self.send_order(mt5.ORDER_TYPE_BUY, price, lot_size, sl_price, tp_price, f"Enhanced_BUY_{market_data['rsi']:.1f}"):
                            self.send_terminal_message('SUCCESS', 'BUY order placed successfully')
                
                elif signal == "SELL":
                    tick = market_data['tick']
                    price = tick.bid
                    lot_size = self.calculate_safe_lot_size()
                    
                    if lot_size >= self.symbol_info.volume_min:
                        sl_price = price + (self.SL_POINTS * self.point_value)
                        tp_points = self.calculate_dynamic_tp(market_data['atr'])
                        tp_price = price - (tp_points * self.point_value)
                        
                        self.send_terminal_message('INFO', f'SELL SIGNAL: {reason}')
                        if self.send_order(mt5.ORDER_TYPE_SELL, price, lot_size, sl_price, tp_price, f"Enhanced_SELL_{market_data['rsi']:.1f}"):
                            self.send_terminal_message('SUCCESS', 'SELL order placed successfully')
                
                else:
                    # Log why no signal every 2 minutes
                    if iteration_count % 120 == 1:
                        self.send_terminal_message('DEBUG', f'No signal: {reason}')
                
                time.sleep(1)  # Check every second
                
        except KeyboardInterrupt:
            self.send_terminal_message('WARNING', 'Trading bot stopped by user')
        except Exception as e:
            self.send_terminal_message('ERROR', f'Trading bot error: {e}')
            logging.exception(f"Unexpected error: {e}")
        finally:
            self.disconnect_mt5()

# Run the bot
if __name__ == "__main__":
    bot = GoldScalperBot()
    bot.run_scalping_bot()