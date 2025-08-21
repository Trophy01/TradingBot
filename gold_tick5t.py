import MetaTrader5 as mt5
import pandas as pd
import time
from datetime import datetime, timedelta
import os
import pytz
import numpy as np
import logging # Import the logging module
import json # Added for config file loading

# --- Logging Configuration ---
# Configure logging to output to console and a file
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s',
                    handlers=[
                        logging.FileHandler("gold_scalper_bot.log"),
                        logging.StreamHandler()
                    ])

class GoldScalperBot:
    """
    A class-based implementation of a Gold (XAUUSD) scalping bot for MetaTrader 5.
    This bot uses custom 5-second tick bars, RSI and Stochastic for entry signals,
    and advanced position management including dynamic lot sizing, break-even,
    ATR trailing stop, aggressive loss limiter, spread filter, time-based exit,
    DYNAMIC TAKE PROFIT, and PARTIAL PROFIT TAKING.
    """

    # --- Configuration ---
    SYMBOL = "XAUUSD" # Gold symbol
    RSI_PERIOD = 14 # Period for RSI calculation (applied to custom 5-second bars)
    RSI_OVERBOUGHT = 65 # RSI overbought threshold
    RSI_OVERSOLD = 35 # RSI oversold threshold

    # Initial SL/TP points - TP_POINTS now acts as a fallback for dynamic TP
    SL_POINTS = 150 # Initial Stop Loss in points (e.g., $5.00 for XAUUSD)
    TP_POINTS = 500 # Take Profit in points (e.g., $10.00 for XAUUSD) - Fallback for dynamic TP

    MAGIC_NUMBER = 678910 # Unique identifier for your trades

    # --- Stochastic Oscillator Configuration ---
    K_PERIOD = 14 # Period for %K line calculation
    D_PERIOD = 3 # Period for %D line (SMA of %K)
    STOCHASTIC_OVERBOUGHT = 75 # Stochastic overbought threshold
    STOCHASTIC_OVERSOLD = 25 # Stochastic oversold threshold

    # Dynamic Aggressive Loss Limiter Configuration
    AGGRESSIVE_SL_PERCENT_TRIGGER = 0.20 # 10% of initial SL_POINTS
    AGGRESSIVE_SL_FIXED_BUFFER_FOR_TRIGGER = 5 # Additional points for the trigger threshold
    AGGRESSIVE_SL_MIN_DISTANCE_FROM_CURRENT = 5 # Points (e.g., $0.25 for XAUUSD). This is the minimum buffer from current price.

    # S/R Lookback for Aggressive SL
    SR_LOOKBACK_BARS = 30 # Number of previous custom 5-second bars to find recent High/Low for S/R
    SR_BREACH_BUFFER_POINTS = 3 # Small buffer (in points) when placing SL just beyond breached S/R

    # Absolute Maximum Adverse Excursion to Close Trade
    # If a trade moves this many points against entry, it will be closed immediately.
    # This acts as an emergency exit, overriding other SL logic if breached.
    MAX_ADVERSE_EXCURSION_CLOSE_POINTS = 200 # e.g., Close trade if it's 150 points ($1.50) in adverse excursion from entry.

    # ATR Trailing Stop Configuration
    ATR_PERIOD = 14 # Period for ATR calculation (common periods are 14 or 20)
    ATR_MULTIPLIER = 1.0 # Multiplier for ATR to determine trailing stop distance (e.g., 1.0 for tighter)

    # Cooldown Configuration
    COOLDOWN_AFTER_TRADE_SECONDS = 60 # Wait X seconds after a trade closes in a LOSS before opening a new one (e.g., 300 seconds = 5 minutes)
    COOLDOWN_LOSS_THRESHOLD_USD = 0.01 # Monetary loss threshold (in USD) to activate cooldown. Set to 0.01 for any loss > $0.01.
    COOLDOWN_POINTS_THRESHOLD = 5 # Price-based loss threshold (in points) to activate cooldown. E.g., 5 points.

    # --- Trade Filters ---
    MAX_SPREAD_POINTS = 35 # Maximum allowed spread in points for entering a trade (e.g., $0.25 for XAUUSD)
    MAX_HOLD_TIME_SECONDS = 120 # Maximum time in seconds a trade can be held before being closed if not profitable (e.g., 3 minutes)
    NUM_CONCURRENT_TRADES = 50 # NEW: Maximum number of trades to hold at one time
    TRADE_ENTRY_COOLDOWN_SECONDS = 10 # NEW: Cooldown after any trade entry of the same type (buy/sell)

    # --- Dynamic Take Profit Configuration ---
    DYNAMIC_TP_ATR_MULTIPLIER = 2.0 # Take Profit Target = Current ATR * Multiplier (e.g., 3 * ATR)
    MIN_DYNAMIC_TP_POINTS = 50 # Minimum dynamic TP in points (e.g., $0.50)
    MAX_DYNAMIC_TP_POINTS = 1000 # Maximum dynamic TP in points (e.g., $20.00)

    # --- Partial Profit Taking Configuration ---
    PARTIAL_PROFIT_TRIGGER_POINTS = 150 # Profit in points to trigger partial close (e.g., $2.50)
    PARTIAL_PROFIT_PERCENTAGE = 0.50 # Percentage of position to close (e.g., 0.50 for 50%)

    # --- Trend Filter Configuration ---
    TREND_MA_PERIOD = 100 # Period for the trend-following moving average
    TREND_MA_TIMEFRAME = mt5.TIMEFRAME_M5 # Timeframe for the trend filter (e.g., M5, M15)
    MA_SLOPE_LOOKBACK_BARS = 2 # Number of M5 bars to check for MA slope direction

    # --- Reversal Confirmation Configuration (NEW) ---
    REVERSAL_CONFIRMATION_BARS = 1 # Number of consecutive bars closing beyond MA to confirm reversal

    # --- MT5 Path Configuration ---
    MT5_PATH = r"C:\Program Files\MetaTrader 5\terminal64.exe"

    # --- Profitability & Risk Management Enhancements ---
    RISK_PERCENT_PER_TRADE = 0.03 # Risk 3% of account equity per trade (0.03 for 3%)
    BREAK_EVEN_PROFIT_POINTS = 75 # Profit in points to move SL to break-even (e.g., $0.75 for XAUUSD)
    BREAK_EVEN_BUFFER_POINTS = 22 # Small buffer for break-even (e.g., $0.22 for XAUUSD)

    # Custom Tick Bar Configuration
    TICK_BAR_INTERVAL_SECONDS = 5 # Build custom bars every 5 seconds
    # HISTORY_BARS_NEEDED now accounts for Stochastic, ATR, SR, and ensures enough for MA slope
    HISTORY_BARS_NEEDED = max(RSI_PERIOD, ATR_PERIOD, SR_LOOKBACK_BARS, K_PERIOD + D_PERIOD) * 2 + 5 + MA_SLOPE_LOOKBACK_BARS
    TICK_DATA_FETCH_HISTORY_MINUTES = max(30, int(HISTORY_BARS_NEEDED * TICK_BAR_INTERVAL_SECONDS / 60) + 5)

    def __init__(self):
        """Initializes the bot's state and global variables."""
        self.tracked_positions = {}
        self.last_tick_time = 0
        self.all_custom_bars = pd.DataFrame()
        self.last_processed_bar_time = datetime.min

        self.symbol_info = None
        self.trade_stop_level_points = 0
        self.point_value = 0.0
        self.trade_contract_size = 0.0

        self.last_trade_closed_timestamp = 0
        self.timezone = pytz.timezone("Etc/UTC")
        self.m5_ma = None # Initialize trend MA
        self.m5_ma_slope = "UNKNOWN" # NEW: To store the slope direction of the M5 MA

        # --- New Reversal Tracking Variables ---
        self.sl_hit_active = False # True if the last trade was an SL hit and we are monitoring for reversal
        self.sl_hit_direction = None # Stores the type of the trade that was SL'd (mt5.ORDER_TYPE_BUY or mt5.ORDER_TYPE_SELL)
        self.sl_hit_confirmation_count = 0 # Counter for consecutive bars confirming the reversal
        self.sl_hit_ma_level = None # The M5 MA level at the time of the SL hit
        
        # --- NEW: Cooldown timers for consecutive entries of the same type ---
        self.last_buy_entry_timestamp = 0
        self.last_sell_entry_timestamp = 0

        # Load config from file on startup
        self.load_config_from_file()

    def load_config_from_file(self):
        """Load configuration from JSON file if it exists"""
        config_file = "goldtick5_config.json"
        if os.path.exists(config_file):
            try:
                with open(config_file, 'r') as f:
                    config = json.load(f)
                    
                # Update class constants
                self.MAX_SPREAD_POINTS = config.get('MAX_SPREAD_POINTS', self.MAX_SPREAD_POINTS)
                self.RSI_OVERSOLD = config.get('RSI_OVERSOLD', self.RSI_OVERSOLD)
                self.RSI_OVERBOUGHT = config.get('RSI_OVERBOUGHT', self.RSI_OVERBOUGHT)
                self.RISK_PERCENT_PER_TRADE = config.get('RISK_PERCENT_PER_TRADE', self.RISK_PERCENT_PER_TRADE)
                self.SL_POINTS = config.get('SL_POINTS', self.SL_POINTS)
                self.TP_POINTS = config.get('TP_POINTS', self.TP_POINTS)
                self.MAX_HOLD_TIME_SECONDS = config.get('MAX_HOLD_TIME_SECONDS', self.MAX_HOLD_TIME_SECONDS)
                self.NUM_CONCURRENT_TRADES = config.get('NUM_CONCURRENT_TRADES', self.NUM_CONCURRENT_TRADES)
                self.BREAK_EVEN_PROFIT_POINTS = config.get('BREAK_EVEN_PROFIT_POINTS', self.BREAK_EVEN_PROFIT_POINTS)
                self.ATR_MULTIPLIER = config.get('ATR_MULTIPLIER', self.ATR_MULTIPLIER)
                self.COOLDOWN_AFTER_TRADE_SECONDS = config.get('COOLDOWN_AFTER_TRADE_SECONDS', self.COOLDOWN_AFTER_TRADE_SECONDS)
                
                logging.info(f"Config updated from file: Spread limit = {self.MAX_SPREAD_POINTS}, RSI = {self.RSI_OVERSOLD}-{self.RSI_OVERBOUGHT}, Risk = {self.RISK_PERCENT_PER_TRADE*100:.1f}%")
                return True
            except Exception as e:
                logging.error(f"Error loading config: {e}")
        return False

    def connect_mt5(self):
        """Establishes connection to MetaTrader 5 terminal."""
        logging.info(f"Attempting to connect to MT5 at path: {self.MT5_PATH}")
        if not os.path.exists(self.MT5_PATH):
            logging.error(f"Error: MT5 executable not found at '{self.MT5_PATH}'. Please verify the path.")
            return False

        if not mt5.initialize(path=self.MT5_PATH):
            logging.error(f"Failed to initialize MT5. Last error: {mt5.last_error()}")
            logging.error("Please ensure MT5 terminal is running, logged into an.account, and 'Allow algorithmic trading' is enabled.")
            return False
        logging.info("MT5 initialized successfully.")

        account_info = mt5.account_info()
        if not account_info:
            logging.error("Error: No account detected as logged into MT5 terminal. Please log in manually.")
            mt5.shutdown()
            return False

        logging.info(f"Successfully connected to MT5. Current account: {account_info.login}, Balance: {account_info.balance:.2f}")
        return True

    def disconnect_mt5(self):
        """Disconnects from MetaTrader 5 terminal."""
        mt5.shutdown()
        logging.info("MT5 disconnected.")

    def get_custom_bars_from_ticks(self, symbol, interval_seconds):
        """
        Retrieves tick data and builds custom OHLCV bars based on a specified time interval.
        It fetches ticks starting from the last known tick time to get new data efficiently.
        Uses mt5.copy_ticks_from for continuous fetching.
        """

        # Determine the start time for fetching ticks
        if self.last_tick_time == 0: # Initial startup, fetch broad history
            from_ts = int((datetime.now(self.timezone) - timedelta(minutes=self.TICK_DATA_FETCH_HISTORY_MINUTES)).timestamp())
            logging.info(f"Initial tick fetch: Requesting history from {self.TICK_DATA_FETCH_HISTORY_MINUTES} minutes ago (Unix timestamp: {from_ts}).")
        else:
            from_ts = int((self.last_tick_time + timedelta(microseconds=1)).timestamp())
            logging.debug(f"Subsequent tick fetch: Requesting ticks from last known tick at {self.last_tick_time.strftime('%Y-%m-%d %H:%M:%S.%f %Z')} (Unix timestamp: {from_ts}).")

        max_ticks_to_fetch = 1000000

        logging.debug(f"Calling mt5.copy_ticks_from({symbol}, {from_ts}, {max_ticks_to_fetch}, mt5.COPY_TICKS_ALL)")

        try:
            ticks = mt5.copy_ticks_from(symbol, from_ts, max_ticks_to_fetch, mt5.COPY_TICKS_ALL)
        except Exception as e:
            logging.error(f"Error fetching ticks with mt5.copy_ticks_from: {e}, MT5 error: {mt5.last_error()}")
            return pd.DataFrame()

        if ticks is None or len(ticks) == 0:
            logging.info(f"mt5.copy_ticks_from returned empty list (no ticks from {datetime.fromtimestamp(from_ts, self.timezone).strftime('%Y-%m-%d %H:%M:%S.%f %Z')}). MT5 error: {mt5.last_error()}. This indicates no new ticks were available or a data connection issue.")
            return pd.DataFrame()

        df_ticks = pd.DataFrame(ticks)
        df_ticks['time'] = pd.to_datetime(df_ticks['time_msc'], unit='ms').dt.tz_localize('UTC')

        logging.debug(f"Fetched {len(df_ticks)} raw ticks from copy_ticks_from.")

        if not df_ticks.empty:
            self.last_tick_time = df_ticks['time'].max()

        df_ticks['bid_ask_avg'] = (df_ticks['bid'] + df_ticks['ask']) / 2

        df_ticks['bar_time'] = pd.to_datetime((df_ticks['time'].astype('int64') // (interval_seconds * 10**9)) * (interval_seconds * 10**9))

        ohlcv = df_ticks.groupby('bar_time').agg(
            open=('bid_ask_avg', 'first'),
            high=('bid_ask_avg', 'max'),
            low=('bid_ask_avg', 'min'),
            close=('bid_ask_avg', 'last')
        )

        ohlcv['real_volume'] = df_ticks.groupby('bar_time')['volume_real'].sum()
        ohlcv.index.name = 'time'

        logging.debug(f"Built {len(ohlcv)} custom {interval_seconds}-second bars.")

        return ohlcv

    def calculate_rsi(self, data, period):
        """Calculates the Relative Strength Index (RSI)."""
        if len(data) < period + 1:
            logging.debug(f"Not enough data ({len(data)} bars) for RSI calculation with period {period}.")
            return None

        delta = data['close'].diff()
        gain = (delta.where(delta > 0, 0)).fillna(0)
        loss = (-delta.where(delta < 0, 0)).fillna(0)

        avg_gain = gain.ewm(com=period - 1, min_periods=period, adjust=False).mean()
        avg_loss = loss.ewm(com=period - 1, min_periods=period, adjust=False).mean()

        with pd.option_context('mode.chained_assignment', None):
            rs = avg_gain / avg_loss

            rsi = 100 - (100 / (1 + rs))

            rsi = rsi.replace([np.inf], 100).replace([-np.inf], 0)
            rsi = rsi.fillna(0)
            rsi = rsi.clip(0, 100)

        return rsi

    def calculate_stochastic(self, data, k_period, d_period):
        """Calculates the Stochastic Oscillator (%K and %D)."""
        if len(data) < k_period + d_period:
            logging.debug(f"Not enough data ({len(data)} bars) for Stochastic calculation with K={k_period}, D={d_period}.")
            return None, None

        # Calculate %K
        low_min = data['low'].rolling(window=k_period).min()
        high_max = data['high'].rolling(window=k_period).max()

        # Avoid division by zero by adding a small epsilon or handling cases where high_max == low_min
        with pd.option_context('mode.chained_assignment', None):
            denominator = (high_max - low_min)
            percent_k = 100 * ((data['close'] - low_min) / np.where(denominator != 0, denominator, np.nan))
            # Fix: Use .ffill() directly as .fillna(method='ffill') is deprecated
            percent_k = percent_k.ffill().fillna(50)
            percent_k = percent_k.clip(0, 100)

        # Calculate %D (SMA of %K)
        percent_d = percent_k.rolling(window=d_period).mean()

        return percent_k, percent_d

    def calculate_atr(self, data, period):
        """Calculates the Average True Range (ATR)."""
        if len(data) < period:
            logging.debug(f"Not enough data ({len(data)} bars) for ATR calculation with period {period}.")
            return None

        high_low = data['high'] - data['low']
        high_prev_close = abs(data['high'] - data['close'].shift(1))
        low_prev_close = abs(data['low'] - data['close'].shift(1))

        true_range = pd.DataFrame({'hl': high_low, 'hpc': high_prev_close, 'lpc': low_prev_close}).max(axis=1)

        atr = true_range.ewm(com=period - 1, min_periods=period, adjust=False).mean()

        return atr

    def calculate_dynamic_lot_size(self, risk_percent, stop_loss_points):
        """
        Calculates the dynamic lot size based on account equity, risk percentage,
        and the stop-loss distance in points.
        Uses stored symbol_info and point_value.
        """
        account_info = mt5.account_info()
        if not account_info:
            logging.warning("Could not get account info for lot size calculation. Using minimum lot.")
            return self.symbol_info.volume_min if self.symbol_info else 0.01

        account_equity = account_info.equity

        if not self.symbol_info:
            logging.warning(f"Could not get symbol info. Using minimum lot.")
            return 0.01

        monetary_value_per_point_per_standard_lot = self.symbol_info.trade_contract_size * self.point_value

        risk_per_standard_lot_usd = stop_loss_points * monetary_value_per_point_per_standard_lot

        if risk_per_standard_lot_usd <= 0:
            logging.warning("Calculated risk per standard lot is zero or negative. Using minimum lot.")
            return self.symbol_info.volume_min

        max_risk_amount_usd = account_equity * risk_percent

        calculated_lot_size = max_risk_amount_usd / risk_per_standard_lot_usd

        min_volume = self.symbol_info.volume_min
        max_volume = self.symbol_info.volume_max
        volume_step = self.symbol_info.volume_step

        adjusted_lot_size = max(min_volume, (calculated_lot_size // volume_step) * volume_step)
        adjusted_lot_size = min(max_volume, adjusted_lot_size)

        logging.info(f"Calculated dynamic lot size: {adjusted_lot_size:.2f} (Equity: {account_equity:.2f}, Risk%: {risk_percent*100}%, SL Points: {stop_loss_points})")

        return adjusted_lot_size

    def send_order(self, order_type, price, volume, sl, tp, comment):
        """Sends a trade order to MT5 and tracks the position."""
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

        try:
            result = mt5.order_send(request)
            if result.retcode != mt5.TRADE_RETCODE_DONE:
                if result.retcode == mt5.TRADE_RETCODE_NO_MONEY:
                    account_info = mt5.account_info()
                    logging.error(f"Order failed: INSUFFICIENT FREE MARGIN. Retcode: {result.retcode}, Current Free Margin: {account_info.margin_free:.2f}.")
                else:
                    logging.error(f"Order failed. Retcode: {result.retcode}, Error: {mt5.last_error()}. Result: {result}")
                return None
            else:
                logging.info(f"TRADE ENTRY - Ticket: {result.order}, Type: {order_type}, Volume: {volume:.2f}, Price: {price:.5f}, SL: {sl:.5f}, TP: {tp:.5f}, Comment: {comment}. MT5 Result: {result.comment}")
                if result.order:
                    self.tracked_positions[result.order] = {
                        'entry_price': price,
                        'current_sl': sl,
                        'type': order_type,
                        'tp': tp,
                        'open_time': time.time(),
                        'partial_profit_taken': False
                    }
                # Update last entry timestamp for specific trade type
                if order_type == mt5.ORDER_TYPE_BUY:
                    self.last_buy_entry_timestamp = time.time()
                elif order_type == mt5.ORDER_TYPE_SELL:
                    self.last_sell_entry_timestamp = time.time()

                # Reset reversal flags after a new trade is successfully opened
                self.sl_hit_active = False
                self.sl_hit_direction = None
                self.sl_hit_confirmation_count = 0
                self.sl_hit_ma_level = None
            return result
        except Exception as e:
            logging.exception(f"Exception while sending order: {e}")
            return None

    def modify_position_sl_tp(self, ticket, new_sl, new_tp):
        """Modifies the stop loss and/or take profit of an open position."""
        position_data = mt5.positions_get(ticket=ticket)
        if not position_data:
            logging.warning(f"Position {ticket} not found for modification.")
            if ticket in self.tracked_positions:
                del self.tracked_positions[ticket]
            return False

        position = position_data[0]

        if (position.sl is not None and abs(position.sl - new_sl) < 1e-9) and \
           (position.tp is not None and abs(position.tp - new_tp) < 1e-9):
            logging.debug(f"SL/TP for position {ticket} already at desired levels. No modification needed.")
            return True

        request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "position": ticket,
            "symbol": position.symbol,
            "volume": position.volume,
            "type": position.type,
            "price": position.price_open,
            "sl": new_sl,
            "tp": new_tp,
            "deviation": 20,
            "magic": self.MAGIC_NUMBER,
            "comment": "SL/TP Modified",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        try:
            result = mt5.order_send(request)
            if result.retcode != mt5.TRADE_RETCODE_DONE:
                logging.error(f"Failed to modify SL/TP for position {ticket}. Retcode: {result.retcode}, Error: {mt5.last_error()}. Result: {result}")
                return False
            else:
                # Log the modification details
                old_sl = position.sl if position.sl is not None else "N/A"
                old_tp = position.tp if position.tp is not None else "N/A"
                logging.info(f"TRADE MODIFICATION - Ticket: {ticket}, Old SL: {old_sl:.5f}, New SL: {new_sl:.5f}, Old TP: {old_tp:.5f}, New TP: {new_tp:.5f}. Reason: {'Break-Even' if new_sl == position.price_open + self.BREAK_EVEN_BUFFER_POINTS * self.point_value or new_sl == position.price_open - self.BREAK_EVEN_BUFFER_POINTS * self.point_value else 'Trailing Stop/Aggressive SL'}")
                if ticket in self.tracked_positions:
                    self.tracked_positions[ticket]['current_sl'] = new_sl
                    self.tracked_positions[ticket]['tp'] = new_tp
                return True
        except Exception as e:
            logging.exception(f"Exception while modifying SL/TP for position {ticket}: {e}")
            return False

    def close_position(self, ticket, volume_to_close=None, reason="Manual/Internal"):
        """
        Closes an open position, optionally partially.
        If volume_to_close is None, closes the full position.
        """
        position_data = mt5.positions_get(ticket=ticket)
        if not position_data:
            logging.warning(f"Position {ticket} not found for closing.")
            if ticket in self.tracked_positions:
                del self.tracked_positions[ticket]
            return None

        position = position_data[0]
        symbol = position.symbol
        volume = volume_to_close if volume_to_close is not None else position.volume

        if volume <= 0:
            logging.warning(f"Attempted to close zero or negative volume for position {ticket}. Skipping close.")
            return None

        order_type = mt5.ORDER_TYPE_SELL if position.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY

        symbol_info_tick = mt5.symbol_info_tick(symbol)
        if symbol_info_tick is None:
            logging.error(f"Failed to get tick info for {symbol} when closing position {ticket}: {mt5.last_error()}")
            return None

        price = symbol_info_tick.bid if order_type == mt5.ORDER_TYPE_BUY else symbol_info_tick.ask

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "position": ticket,
            "symbol": symbol,
            "volume": volume,
            "type": order_type,
            "price": price,
            "deviation": 20,
            "magic": self.MAGIC_NUMBER,
            "comment": f"Close Position: {reason}", # Include reason in comment
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        try:
            result = mt5.order_send(request)
            if result.retcode != mt5.TRADE_RETCODE_DONE:
                logging.error(f"Failed to close position {ticket} (Volume: {volume}). Retcode: {result.retcode}, Error: {mt5.last_error()}")
            else:
                # Log the closure details
                logging.info(f"TRADE CLOSURE REQUEST - Ticket: {ticket}, Volume: {volume:.2f}, Close Price: {price:.5f}, Reason: {reason}. MT5 Result: {result.comment}. Remaining volume: {position.volume - volume:.2f}")
                if position.volume - volume <= self.symbol_info.volume_min / 2: # Fully closed
                    if ticket in self.tracked_positions:
                        del self.tracked_positions[ticket]
            return result
        except Exception as e:
            logging.exception(f"Exception while closing position {ticket}: {e}")
            return None

    def get_current_open_positions(self): # Removed current_tick_time_msc parameter as it's not used here directly
        """
        Retrieves all open positions and updates tracked_positions.
        Also updates last_trade_closed_timestamp if a position was just closed
        at a significant loss.
        """
        mt5_positions = mt5.positions_get(symbol=self.SYMBOL)

        active_mt5_tickets = {pos.ticket for pos in mt5_positions}

        tickets_to_remove = [t for t in self.tracked_positions if t not in active_mt5_tickets]

        for ticket_to_remove in tickets_to_remove:
            logging.info(f"Checking closure status for position {ticket_to_remove} (no longer in MT5 open positions).")

            original_trade_info = self.tracked_positions.get(ticket_to_remove)

            from_time = datetime.now(self.timezone) - timedelta(minutes=15)
            to_time = datetime.now(self.timezone)
            # Fetch deals that include the position's ticket and occurred recently
            deals = mt5.history_deals_get(from_time, to_time)
            if deals:
                deals = [d for d in deals if d.position_id == ticket_to_remove]
            
            position_closed_profit_usd = 0.0
            closing_deal_price = None
            closing_deal_price_time_msc = 0
            closure_type = "UNKNOWN" # NEW: Determine closure type

            if deals and original_trade_info:
                # Sort deals by time_msc to find the latest closing deal
                relevant_deals = sorted([d for d in deals if d.position_id == ticket_to_remove], key=lambda x: x.time_msc)
                
                if relevant_deals:
                    for deal in relevant_deals:
                        position_closed_profit_usd += deal.profit
                        # Identify the actual closing deal (DEAL_ENTRY_OUT for full close, DEAL_ENTRY_OUT_BY for partial)
                        if deal.entry == mt5.DEAL_ENTRY_OUT or deal.entry == mt5.DEAL_ENTRY_OUT_BY:
                            closing_deal_price = deal.price
                            closing_deal_price_time_msc = deal.time_msc

                        # Infer closure type based on deal properties and stored trade info
                        if deal.entry == mt5.DEAL_ENTRY_OUT: # Full closure
                            # Check if the profit matches TP (allowing for small deviation)
                            # This is a more robust check for TP/SL hit
                            if original_trade_info['tp'] is not None and original_trade_info['current_sl'] is not None: # Use current_sl from tracked_positions
                                if original_trade_info['type'] == mt5.ORDER_TYPE_BUY:
                                    if abs(deal.price - original_trade_info['tp']) < self.point_value * 5: # Within 5 points of TP
                                        closure_type = "TP_HIT"
                                    elif abs(deal.price - original_trade_info['current_sl']) < self.point_value * 5: # Within 5 points of SL
                                        closure_type = "SL_HIT"
                                    else:
                                        closure_type = "MANUAL/OTHER" # Could be time-based, aggressive SL, manual
                                elif original_trade_info['type'] == mt5.ORDER_TYPE_SELL:
                                    if abs(deal.price - original_trade_info['tp']) < self.point_value * 5:
                                        closure_type = "TP_HIT"
                                    elif abs(deal.price - original_trade_info['current_sl']) < self.point_value * 5:
                                        closure_type = "SL_HIT"
                                    else:
                                        closure_type = "MANUAL/OTHER"
                            else: # If SL/TP not set, it's definitely manual/other
                                closure_type = "MANUAL/OTHER"
                        elif deal.entry == mt5.DEAL_ENTRY_OUT_BY: # Partial closure
                            closure_type = "PARTIAL_PROFIT_TAKE"
                else:
                    logging.debug(f"No recent deals found for closed position {ticket_to_remove}.")

            price_based_loss_occurred = False
            price_difference_points = 0.0
            if original_trade_info and closing_deal_price is not None and self.point_value != 0:
                entry_price = original_trade_info['entry_price']
                position_type = original_trade_info['type']

                if position_type == mt5.ORDER_TYPE_BUY:
                    price_difference_points = (closing_deal_price - entry_price) / self.point_value
                    if price_difference_points < -self.COOLDOWN_POINTS_THRESHOLD:
                        price_based_loss_occurred = True
                elif position_type == mt5.ORDER_TYPE_SELL:
                    price_difference_points = (entry_price - closing_deal_price) / self.point_value
                    if price_difference_points < -self.COOLDOWN_POINTS_THRESHOLD:
                        price_based_loss_occurred = True
                logging.info(f"Price-based P/L for {ticket_to_remove}: {price_difference_points:.2f} points. Cooldown threshold: {-self.COOLDOWN_POINTS_THRESHOLD:.2f} points.")
            else:
                logging.debug(f"Cannot calculate price-based P/L for {ticket_to_remove}. Missing info or zero point_value.")

            # Log actual trade closure details
            logging.info(f"TRADE CLOSED - Ticket: {ticket_to_remove}, P/L (USD): {position_closed_profit_usd:.2f}, P/L (Points): {price_difference_points:.2f}, Close Reason: {closure_type}. Cooldown Active: {'YES' if (position_closed_profit_usd < -self.COOLDOWN_LOSS_THRESHOLD_USD) or price_based_loss_occurred else 'NO'}")

            if (position_closed_profit_usd < -self.COOLDOWN_LOSS_THRESHOLD_USD) or price_based_loss_occurred:
                logging.warning(f"Position {ticket_to_remove} closed in LOSS (monetary or price-based). Activating cooldown.")
                self.last_trade_closed_timestamp = time.time()

                # --- NEW: Set reversal monitoring flags ---
                if closure_type == "SL_HIT":
                    self.sl_hit_active = True
                    self.sl_hit_direction = original_trade_info['type'] # Type of the trade that was stopped out
                    self.sl_hit_confirmation_count = 0 # Reset counter
                    self.sl_hit_ma_level = self.m5_ma # Record MA level at time of SL hit
                    logging.info(f"SL HIT DETECTED. Entering REVERSAL WATCH MODE for direction {'BUY' if self.sl_hit_direction == mt5.ORDER_TYPE_SELL else 'SELL'} at MA {self.sl_hit_ma_level:.5f}.")
            else:
                logging.info(f"Position {ticket_to_remove} closed in PROFIT/BREAK-EVEN (no significant loss). No cooldown.")
                # If a profitable trade closes, reset reversal flags too, as a new trend might be confirmed.
                self.sl_hit_active = False
                self.sl_hit_direction = None
                self.sl_hit_confirmation_count = 0
                self.sl_hit_ma_level = None


            del self.tracked_positions[ticket_to_remove]

        for pos in mt5_positions:
            if pos.ticket not in self.tracked_positions:
                logging.info(f"Adding new position {pos.ticket} to internal tracker. Entry: {pos.price_open:.5f}, SL: {pos.sl:.5f}, TP: {pos.tp:.5f}, Type: {pos.type}")
                self.tracked_positions[pos.ticket] = {
                    'entry_price': pos.price_open,
                    'current_sl': pos.sl,
                    'type': pos.type,
                    'tp': pos.tp,
                    'open_time': time.time(),
                    'partial_profit_taken': False
                }
            else:
                # Only log if SL/TP actually changed
                if self.tracked_positions[pos.ticket]['current_sl'] != pos.sl:
                    logging.debug(f"Updating tracked SL for position {pos.ticket} from {self.tracked_positions[pos.ticket]['current_sl']:.5f} to {pos.sl:.5f}")
                    self.tracked_positions[pos.ticket]['current_sl'] = pos.sl
                if self.tracked_positions[pos.ticket]['tp'] != pos.tp:
                    logging.debug(f"Updating tracked TP for position {pos.ticket} from {self.tracked_positions[ticket]['tp']:.5f} to {pos.tp:.5f}")
                    self.tracked_positions[ticket]['tp'] = pos.tp

        return mt5_positions

    def manage_positions(self, open_positions_list):
        """Manages open positions by applying break-even, trailing stop, and aggressive loss limiter logic."""

        if self.symbol_info is None:
            logging.error(f"Symbol info is None. Cannot manage positions.")
            return

        current_atr = None
        previous_high_in_period = -np.inf
        previous_low_in_period = np.inf

        min_bars_for_indicators = max(self.RSI_PERIOD, self.ATR_PERIOD, self.SR_LOOKBACK_BARS, self.K_PERIOD + self.D_PERIOD) * 2 + 5
        if self.all_custom_bars.empty or len(self.all_custom_bars) < min_bars_for_indicators:
            logging.warning(f"Not enough complete custom tick bars ({len(self.all_custom_bars)} of {min_bars_for_indicators} needed) to calculate ATR or perform S/R lookback for trailing stop/aggressive SL.")
        else:
            atr_series = self.calculate_atr(self.all_custom_bars, self.ATR_PERIOD)
            if atr_series is not None and not atr_series.empty:
                current_atr = atr_series.iloc[-1]
                if pd.isna(current_atr):
                    current_atr = None

            logging.debug(f"Current ATR ({self.ATR_PERIOD} period): {current_atr:.5f}" if current_atr is not None else "ATR could not be calculated (None/NaN).")

            if len(self.all_custom_bars) >= self.SR_LOOKBACK_BARS:
                recent_bars_for_sr = self.all_custom_bars.iloc[-self.SR_LOOKBACK_BARS:]
                previous_high_in_period = recent_bars_for_sr['high'].max()
                previous_low_in_period = recent_bars_for_sr['low'].min()
                logging.debug(f"S/R Lookback ({self.SR_LOOKBACK_BARS} bars): Prev High: {previous_high_in_period:.5f}, Prev Low: {previous_low_in_period:.5f}")
            else:
                logging.debug(f"Not enough bars ({len(self.all_custom_bars)}) for S/R lookback ({self.SR_LOOKBACK_BARS} needed).")

        dynamic_aggressive_trigger_points = (self.SL_POINTS * self.AGGRESSIVE_SL_PERCENT_TRIGGER) + self.AGGRESSIVE_SL_FIXED_BUFFER_FOR_TRIGGER

        for position in open_positions_list:
            ticket = position.ticket
            entry_price = position.price_open
            current_sl = position.sl
            current_tp = position.tp
            position_type = position.type
            current_volume = position.volume

            tracked_pos_info = self.tracked_positions.get(ticket, {})
            open_time = tracked_pos_info.get('open_time')
            partial_profit_taken = tracked_pos_info.get('partial_profit_taken', False)

            if entry_price is None or current_sl is None or position_type is None:
                logging.warning(f"Warning: Missing data for fetched position {ticket}. Skipping management.")
                continue

            symbol_info_tick = mt5.symbol_info_tick(self.SYMBOL)
            if symbol_info_tick is None:
                logging.error(f"Failed to get live tick info for {self.SYMBOL}. Skipping position management for ticket {ticket}.")
                continue

            current_bid = symbol_info_tick.bid
            current_ask = symbol_info_tick.ask

            profit_points = 0
            current_adverse_excursion_points = 0

            if position_type == mt5.ORDER_TYPE_BUY:
                profit_points = (current_bid - entry_price) / self.point_value
                current_adverse_excursion_points = (entry_price - current_bid) / self.point_value
            elif position_type == mt5.ORDER_TYPE_SELL:
                profit_points = (entry_price - current_ask) / self.point_value
                current_adverse_excursion_points = (current_ask - entry_price) / self.point_value

            logging.info(f"\n--- Position {ticket} Management ---")
            logging.info(f"  Entry Price: {entry_price:.5f}")
            logging.info(f"  Current Bid: {current_bid:.5f}, Current Ask: {current_ask:.5f}")
            logging.info(f"  Current Volume: {current_volume:.2f} lots")
            logging.info(f"  Profit/Loss (points): {profit_points:.2f}")
            logging.info(f"  Adverse Excursion (points): {current_adverse_excursion_points:.2f} (Dynamic Threshold: {dynamic_aggressive_trigger_points:.2f})")
            logging.info(f"  Current Stop Loss: {current_sl:.5f}")
            logging.info(f"  Current Take Profit: {current_tp:.5f}")
            logging.info(f"-----------------------------------\n")

            # --- Partial Profit Taking Logic ---
            if not partial_profit_taken and \
               profit_points >= self.PARTIAL_PROFIT_TRIGGER_POINTS and \
               current_volume > self.symbol_info.volume_min:

                volume_to_close = current_volume * self.PARTIAL_PROFIT_PERCENTAGE
                volume_to_close = (volume_to_close // self.symbol_info.volume_step) * self.symbol_info.volume_step
                volume_to_close = max(volume_to_close, self.symbol_info.volume_min)

                if current_volume - volume_to_close >= self.symbol_info.volume_min or (current_volume - volume_to_close < self.symbol_info.volume_min and current_volume - volume_to_close < self.symbol_info.volume_step / 2):
                    logging.info(f"Position {ticket}: PARTIAL PROFIT TRIGGER HIT! Profit: {profit_points:.2f} pts. Closing {volume_to_close:.2f} lots ({self.PARTIAL_PROFIT_PERCENTAGE*100:.0f}%).")

                    close_result = self.close_position(ticket, volume_to_close, reason="PARTIAL PROFIT")
                    if close_result and close_result.retcode == mt5.TRADE_RETCODE_DONE:
                        self.tracked_positions[ticket]['partial_profit_taken'] = True
                        new_sl_after_partial = entry_price
                        if position_type == mt5.ORDER_TYPE_BUY:
                            new_sl_after_partial += (self.BREAK_EVEN_BUFFER_POINTS * self.point_value)
                            if current_sl is None or new_sl_after_partial > current_sl:
                                self.modify_position_sl_tp(ticket, new_sl_after_partial, current_tp)
                        elif position_type == mt5.ORDER_TYPE_SELL:
                            new_sl_after_partial -= (self.BREAK_EVEN_BUFFER_POINTS * self.point_value)
                            if current_sl is None or new_sl_after_partial < current_sl:
                                self.modify_position_sl_tp(ticket, new_sl_after_partial, current_tp)
                    else:
                        logging.error(f"Failed to execute partial close for {ticket}.")
                else:
                    logging.info(f"Position {ticket}: Partial profit condition met, but calculated partial close volume ({volume_to_close:.2f}) would result in invalid remaining volume ({current_volume - volume_to_close:.2f}). Skipping partial close.")

            # --- Time-Based Exit for Stagnant Trades ---
            if open_time is not None and (time.time() - open_time) > self.MAX_HOLD_TIME_SECONDS:
                if profit_points <= 0:
                    logging.warning(f"Position {ticket}: Time-based exit activated. Held for {(time.time() - open_time):.1f}s (>{self.MAX_HOLD_TIME_SECONDS}s) with P/L of {profit_points:.2f} points. Closing trade.")
                    self.close_position(ticket, reason="TIME-BASED EXIT (UNPROFITABLE)")
                    continue

            if current_adverse_excursion_points >= self.MAX_ADVERSE_EXCURSION_CLOSE_POINTS:
                logging.critical(f"Position {ticket}: EMERGENCY CLOSE! Adverse Excursion ({current_adverse_excursion_points:.2f} pts) hit MAX_ADVERSE_EXCURSION_CLOSE_POINTS ({self.MAX_ADVERSE_EXCURSION_CLOSE_POINTS} pts). Closing trade immediately.")
                self.close_position(ticket, reason="MAX ADVERSE EXCURSION")
                continue

            aggressive_trigger_price_level = 0.0
            if position_type == mt5.ORDER_TYPE_BUY:
                aggressive_trigger_price_level = entry_price - (dynamic_aggressive_trigger_points * self.point_value)
            elif position_type == mt5.ORDER_TYPE_SELL:
                aggressive_trigger_price_level = entry_price + (dynamic_aggressive_trigger_points * self.point_value)

            if profit_points < 0 and current_adverse_excursion_points >= dynamic_aggressive_trigger_points:

                momentum_confirmed = False

                if not self.all_custom_bars.empty:
                    current_bar_close = self.all_custom_bars['close'].iloc[-1]
                else:
                    current_bar_close = None

                if current_bar_close is not None:
                    if position_type == mt5.ORDER_TYPE_BUY:
                        if current_bar_close < aggressive_trigger_price_level:
                            momentum_confirmed = True
                    elif position_type == mt5.ORDER_TYPE_SELL:
                        if current_bar_close > aggressive_trigger_price_level:
                            momentum_confirmed = True

                if momentum_confirmed:
                    actual_aggressive_buffer_points = max(self.AGGRESSIVE_SL_MIN_DISTANCE_FROM_CURRENT, self.trade_stop_level_points + 5)
                    new_aggressive_sl_candidate = 0.0

                    if position_type == mt5.ORDER_TYPE_BUY:
                        sl_from_current_price = current_bid - (actual_aggressive_buffer_points * self.point_value)
                        new_aggressive_sl_candidate = sl_from_current_price

                        if current_bid < previous_low_in_period and previous_low_in_period != np.inf:
                            sl_from_sr_breach = previous_low_in_period - (self.SR_BREACH_BUFFER_POINTS * self.point_value)
                            new_aggressive_sl_candidate = max(sl_from_current_price, sl_from_sr_breach)
                            logging.debug(f"Position {ticket} (BUY): S/R (Prev Low: {previous_low_in_period:.5f}) breached. Aggressive SL candidate considered from S/R: {sl_from_sr_breach:.5f}.")

                        if current_sl is None or new_aggressive_sl_candidate < current_sl:
                            logging.warning(f"Position {ticket}: AGGRESSIVE LOSS LIMITER ACTIVATED (BUY - Momentum Confirmed). Moving SL to {new_aggressive_sl_candidate:.5f}. Adverse Excursion: {current_adverse_excursion_points:.2f} points. Targeting SL based on current price and/or breached S/R.")
                            self.modify_position_sl_tp(ticket, new_aggressive_sl_candidate, current_tp)
                        else:
                            logging.debug(f"Position {ticket} (BUY): Aggressive SL not moved as candidate ({new_aggressive_sl_candidate:.5f}) is not tighter (lower) than current ({current_sl:.5f}).")

                    elif position_type == mt5.ORDER_TYPE_SELL:
                        sl_from_current_price = current_ask + (actual_aggressive_buffer_points * self.point_value)
                        new_aggressive_sl_candidate = sl_from_current_price

                        if current_ask > previous_high_in_period and previous_high_in_period != -np.inf:
                            sl_from_sr_breach = previous_high_in_period + (self.SR_BREACH_BUFFER_POINTS * self.point_value)
                            new_aggressive_sl_candidate = min(sl_from_current_price, sl_from_sr_breach)
                            logging.debug(f"Position {ticket} (SELL): S/R (Prev High: {previous_high_in_period:.5f}) breached. Aggressive SL candidate considered from S/R: {sl_from_sr_breach:.5f}.")

                        if current_sl is None or new_aggressive_sl_candidate > current_sl:
                            logging.warning(f"Position {ticket}: AGGRESSIVE LOSS LIMITER ACTIVATED (SELL - Momentum Confirmed). Moving SL to {new_aggressive_sl_candidate:.5f}. Adverse Excursion: {current_adverse_excursion_points:.2f} points. Targeting SL based on current price and/or breached S/R.")
                            self.modify_position_sl_tp(ticket, new_aggressive_sl_candidate, current_tp)
                        else:
                            logging.debug(f"Position {ticket} (SELL): Aggressive SL not moved as candidate ({new_aggressive_sl_candidate:.5f}) is not tighter (higher) than current ({current_sl:.5f}).")
                else:
                    logging.debug(f"Position {ticket}: Aggressive SL trigger hit ({current_adverse_excursion_points:.2f} pts), but momentum not confirmed by current bar close ({current_bar_close if current_bar_close is not None else 'N/A' :.5f} vs trigger {aggressive_trigger_price_level:.5f}). Waiting for stronger confirmation.")
            elif profit_points >= self.BREAK_EVEN_PROFIT_POINTS:
                new_be_sl = 0.0
                if position_type == mt5.ORDER_TYPE_BUY:
                    new_be_sl = entry_price + (self.BREAK_EVEN_BUFFER_POINTS * self.point_value)
                    if current_sl is None or new_be_sl > current_sl:
                        logging.info(f"Position {ticket}: Moving SL to Break-Even ({new_be_sl:.5f}). Profit: {profit_points:.2f} points.")
                        self.modify_position_sl_tp(ticket, new_be_sl, current_tp)
                    else:
                        logging.debug(f"Position {ticket} (BUY): Break-Even SL not moved as candidate ({new_be_sl:.5f}) is not better (higher) than current ({current_sl:.5f}).")

                elif position_type == mt5.ORDER_TYPE_SELL:
                    new_be_sl = entry_price - (self.BREAK_EVEN_BUFFER_POINTS * self.point_value)
                    if current_sl is None or new_be_sl < current_sl:
                        logging.info(f"Position {ticket}: Moving SL to Break-Even ({new_be_sl:.5f}). Profit: {profit_points:.2f} points.")
                        self.modify_position_sl_tp(ticket, new_be_sl, current_tp)
                    else:
                        logging.debug(f"Position {ticket} (SELL): Break-Even SL not moved as candidate ({new_be_sl:.5f}) is not better (lower) than current ({current_sl:.5f}).")


            if profit_points > self.BREAK_EVEN_PROFIT_POINTS and current_atr is not None:
                atr_trailing_distance_points = current_atr * self.ATR_MULTIPLIER

                new_ts_sl = 0.0
                if position_type == mt5.ORDER_TYPE_BUY:
                    new_ts_sl = current_bid - (atr_trailing_distance_points * self.point_value)
                    be_level = entry_price + (self.BREAK_EVEN_BUFFER_POINTS * self.point_value)
                    if new_ts_sl > current_sl and new_ts_sl > be_level:
                        logging.info(f"Position {ticket}: ATR Trailing SL to {new_ts_sl:.5f}. Current Profit: {profit_points:.2f} points. ATR Distance: {atr_trailing_distance_points:.2f} points.")
                        self.modify_position_sl_tp(ticket, new_ts_sl, current_tp)
                    else:
                        logging.debug(f"Position {ticket} (BUY): ATR Trailing SL not moved as candidate ({new_ts_sl:.5f}) is not higher than current ({current_sl:.5f}) or not above Break-Even level ({be_level:.5f}).")

                elif position_type == mt5.ORDER_TYPE_SELL:
                    new_ts_sl = current_ask + (atr_trailing_distance_points * self.point_value)
                    be_level = entry_price - (self.BREAK_EVEN_BUFFER_POINTS * self.point_value)
                    if new_ts_sl < current_sl and new_ts_sl < be_level:
                        logging.info(f"Position {ticket}: ATR Trailing SL to {new_ts_sl:.5f}. Current Profit: {profit_points:.2f} points. ATR Distance: {atr_trailing_distance_points:.2f} points.")
                        self.modify_position_sl_tp(ticket, new_ts_sl, current_tp)
                    else:
                        logging.debug(f"Position {ticket} (SELL): ATR Trailing SL not moved as candidate ({new_ts_sl:.5f}) is not lower than current ({current_sl:.5f}) or not below Break-Even level ({be_level:.5f}).")

    def run_scalping_bot(self):
        """Main loop for the scalping bot."""

        if not self.connect_mt5():
            logging.critical("Failed to connect to MT5. Exiting bot.")
            return

        if not mt5.symbol_select(self.SYMBOL, True):
            logging.error(f"Error: {self.SYMBOL} not found in Market Watch. Please add it manually in MT5.")
            self.disconnect_mt5()
            return

        self.symbol_info = mt5.symbol_info(self.SYMBOL)
        if self.symbol_info is None:
            logging.critical(f"Error: Could not get symbol info for {self.SYMBOL}. Exiting bot.")
            self.disconnect_mt5()
            return

        self.trade_stop_level_points = self.symbol_info.trade_stops_level
        self.point_value = self.symbol_info.point
        self.trade_contract_size = self.symbol_info.trade_contract_size

        logging.info(f"Broker's minimum stop level for {self.SYMBOL}: {self.trade_stop_level_points} points.")
        logging.info(f"Symbol Point Value: {self.point_value}")
        logging.info(f"Symbol Volume Min: {self.symbol_info.volume_min:.5f} lots")
        logging.info(f"Symbol Volume Max: {self.symbol_info.volume_max:.5f} lots")
        logging.info(f"Symbol Volume Step: {self.symbol_info.volume_step:.5f} lots")
        logging.info(f"Symbol Contract Size: {self.trade_contract_size} (e.g., 100 for standard Gold lot)")


        if self.SL_POINTS < self.trade_stop_level_points:
            logging.warning(f"Configured SL_POINTS ({self.SL_POINTS}) is less than broker's minimum stop level ({self.trade_stop_level_points}). This could lead to 'Invalid stops' errors. Consider increasing SL_POINTS.")

        if self.TP_POINTS < self.trade_stop_level_points:
            logging.warning(f"Configured TP_POINTS ({self.TP_POINTS}) is less than broker's minimum stop level ({self.TP_POINTS}). This could lead to 'Invalid stops' errors. Consider increasing TP_POINTS.")

        # --- Initial M5 MA Calculation and Slope Determination ---
        # Fetch enough bars for initial MA and slope calculation
        m5_bars = mt5.copy_rates_from_pos(self.SYMBOL, self.TREND_MA_TIMEFRAME, 0, self.TREND_MA_PERIOD + self.MA_SLOPE_LOOKBACK_BARS + 5) # +5 for buffer
        if m5_bars is None or len(m5_bars) < self.TREND_MA_PERIOD + self.MA_SLOPE_LOOKBACK_BARS:
            logging.error(f"Not enough {self.TREND_MA_TIMEFRAME} history to calculate MA and slope. Got {len(m5_bars) if m5_bars is not None else 0} bars, need {self.TREND_MA_PERIOD + self.MA_SLOPE_LOOKBACK_BARS}. Running without trend filter.")
            self.m5_ma = None
            self.m5_ma_slope = "UNKNOWN"
        else:
            m5_bars_df = pd.DataFrame(m5_bars)
            m5_bars_df['time'] = pd.to_datetime(m5_bars_df['time'], unit='s')
            m5_ma_series = m5_bars_df['close'].rolling(window=self.TREND_MA_PERIOD).mean()
            self.m5_ma = m5_ma_series.iloc[-1]

            # Determine M5 MA slope
            if len(m5_ma_series) >= self.MA_SLOPE_LOOKBACK_BARS + 1:
                # Compare the last MA value to the MA value from MA_SLOPE_LOOKBACK_BARS ago
                ma_start_of_period = m5_ma_series.iloc[- (self.MA_SLOPE_LOOKBACK_BARS + 1)]
                ma_end_of_period = m5_ma_series.iloc[-1]
                if ma_end_of_period > ma_start_of_period:
                    self.m5_ma_slope = "UP"
                elif ma_end_of_period < ma_start_of_period:
                    self.m5_ma_slope = "DOWN"
                else:
                    self.m5_ma_slope = "FLAT"
            else:
                self.m5_ma_slope = "UNKNOWN" # Not enough data for slope

            logging.info(f"Initial {self.TREND_MA_TIMEFRAME} trend MA calculated: {self.m5_ma:.5f}, Slope: {self.m5_ma_slope}")


        logging.info(f"Starting {self.SYMBOL} scalping bot on 5-second timeframe using tick data...")

        # Track time for periodic config reload
        last_config_check_time = time.time()

        while True:
            try:
                # Check for config file updates every 30 seconds
                current_time = time.time()
                if current_time - last_config_check_time >= 30:
                    self.load_config_from_file()
                    last_config_check_time = current_time

                # Get custom bars from ticks using the improved fetching method
                new_bars = self.get_custom_bars_from_ticks(self.SYMBOL, self.TICK_BAR_INTERVAL_SECONDS)

                if not new_bars.empty:
                    if new_bars.index.tz is None:
                        new_bars.index = new_bars.index.tz_localize('UTC')

                    # Ensure last_processed_bar_time is timezone-aware for comparison
                    if self.last_processed_bar_time == datetime.min: # Initial setup
                        last_processed_ts = pd.Timestamp(self.last_processed_bar_time, tz='UTC')
                    else: # Subsequent runs, ensure it's timezone-aware
                        if self.last_processed_bar_time.tzinfo is None:
                            last_processed_ts = pd.Timestamp(self.last_processed_bar_time, tz='UTC')
                        else:
                            last_processed_ts = pd.Timestamp(self.last_processed_bar_time)

                    # Filter out bars older than the last processed bar
                    new_bars = new_bars[new_bars.index > last_processed_ts]

                    if not new_bars.empty:
                        self.all_custom_bars = pd.concat([self.all_custom_bars, new_bars]).drop_duplicates().sort_index().copy()
                        self.last_processed_bar_time = self.all_custom_bars.index.max().to_pydatetime()

                        # Keep only the necessary number of bars to prevent excessive memory usage
                        bars_needed = max(self.RSI_PERIOD, self.ATR_PERIOD, self.SR_LOOKBACK_BARS, self.K_PERIOD + self.D_PERIOD) * 2 + 5 + self.MA_SLOPE_LOOKBACK_BARS # Increased bars needed
                        if len(self.all_custom_bars) > bars_needed:
                            self.all_custom_bars = self.all_custom_bars.iloc[-bars_needed:].copy()

                        logging.debug(f"Total custom bars in history: {len(self.all_custom_bars)}")
                    else:
                        logging.debug("No new bars generated from fetched ticks after filtering by last_processed_bar_time. This might mean only old ticks were retrieved.")
                else:
                    logging.info("No custom bars could be built from the fetched ticks in this iteration. This often means no new ticks were available.")

                # Initialize log variables to 'N/A' defaults
                current_rsi, current_percent_k, current_percent_d = "N/A", "N/A", "N/A"
                prev_bar_open, prev_bar_high, prev_bar_low, prev_bar_close = "N/A", "N/A", "N/A", "N/A"
                current_bar_open, current_bar_high, current_bar_low, current_bar_close = "N/A", "N/A", "N/A", "N/A"
                ma_log_val = "N/A"
                atr_log_val = "N/A"

                # Check if there's enough data for all indicators
                min_bars_for_indicators = max(self.RSI_PERIOD, self.ATR_PERIOD, self.SR_LOOKBACK_BARS, self.K_PERIOD + self.D_PERIOD) + 2
                if self.all_custom_bars.empty or len(self.all_custom_bars) < min_bars_for_indicators:
                    logging.info(f"Not enough complete custom tick bars ({len(self.all_custom_bars)} of {min_bars_for_indicators} needed) to calculate indicators. Waiting for more data...")
                    time.sleep(1)
                    continue

                # --- Update M5 MA and Slope ---
                # Fetch enough bars for MA and slope calculation
                m5_bars = mt5.copy_rates_from_pos(self.SYMBOL, self.TREND_MA_TIMEFRAME, 0, self.TREND_MA_PERIOD + self.MA_SLOPE_LOOKBACK_BARS + 5)
                if m5_bars is not None and len(m5_bars) > self.TREND_MA_PERIOD + self.MA_SLOPE_LOOKBACK_BARS:
                    m5_bars_df = pd.DataFrame(m5_bars)
                    m5_bars_df['time'] = pd.to_datetime(m5_bars_df['time'], unit='s')
                    m5_ma_series = m5_bars_df['close'].rolling(window=self.TREND_MA_PERIOD).mean()
                    self.m5_ma = m5_ma_series.iloc[-1]
                    ma_log_val = f"{self.m5_ma:.5f}" # Set for log here

                    if len(m5_ma_series) >= self.MA_SLOPE_LOOKBACK_BARS + 1:
                        ma_start_of_period = m5_ma_series.iloc[- (self.MA_SLOPE_LOOKBACK_BARS + 1)]
                        ma_end_of_period = m5_ma_series.iloc[-1]
                        if ma_end_of_period > ma_start_of_period:
                            self.m5_ma_slope = "UP"
                        elif ma_end_of_period < ma_start_of_period:
                            self.m5_ma_slope = "DOWN"
                        else:
                            self.m5_ma_slope = "FLAT"
                    else:
                        self.m5_ma_slope = "UNKNOWN"

                    logging.debug(f"Updated {self.TREND_MA_TIMEFRAME} trend MA: {self.m5_ma:.5f}, Slope: {self.m5_ma_slope}")
                else:
                    self.m5_ma = None
                    self.m5_ma_slope = "UNKNOWN"
                    logging.warning(f"Not enough {self.TREND_MA_TIMEFRAME} bars to update MA and slope, running without trend filter for now.")

                # Calculate RSI
                self.all_custom_bars['rsi'] = self.calculate_rsi(self.all_custom_bars, self.RSI_PERIOD)

                # Calculate Stochastic
                percent_k, percent_d = self.calculate_stochastic(self.all_custom_bars, self.K_PERIOD, self.D_PERIOD)

                if percent_k is not None:
                    self.all_custom_bars['%k'] = percent_k
                    self.all_custom_bars['%d'] = percent_d
                else:
                    logging.warning("Stochastic calculation returned None. Not enough data or issue in calculation. Waiting...")
                    time.sleep(1)
                    continue

                current_rsi = self.all_custom_bars['rsi'].iloc[-1]
                current_percent_k = self.all_custom_bars['%k'].iloc[-1]
                current_percent_d = self.all_custom_bars['%d'].iloc[-1]

                # Get data for previous custom bar for dip/rally confirmation
                # Ensure there are enough bars to safely access previous elements
                if len(self.all_custom_bars) < 2:
                    logging.info("Not enough custom bars for previous bar data. Waiting...")
                    time.sleep(1)
                    continue

                prev_bar_open = self.all_custom_bars['open'].iloc[-2]
                prev_bar_high = self.all_custom_bars['high'].iloc[-2]
                prev_bar_low = self.all_custom_bars['low'].iloc[-2]
                prev_bar_close = self.all_custom_bars['close'].iloc[-2]
                current_bar_open = self.all_custom_bars['open'].iloc[-1]
                current_bar_high = self.all_custom_bars['high'].iloc[-1]
                current_bar_low = self.all_custom_bars['low'].iloc[-1]
                current_bar_close = self.all_custom_bars['close'].iloc[-1] # Get current bar close

                # Re-assign for logging if calculations were successful
                # Note: These 'if' statements ensure that the log variables are only updated
                # if the calculations actually produce valid numbers.
                if current_rsi is None or pd.isna(current_rsi) or \
                   current_percent_k is None or pd.isna(current_percent_k) or \
                   current_percent_d is None or pd.isna(current_percent_d):
                    logging.warning("Latest indicator calculation returned None or NaN. Not enough data or issue in calculation. Waiting...")
                    # Do not set current_rsi, current_percent_k, current_percent_d to N/A here, as
                    # they might have been set in the previous iteration and we want them for the log.
                    # The log formatter already handles 'N/A' if the values are None/NaN from calculation.
                    time.sleep(1)
                    continue

                # Calculate current_atr for dynamic TP calculation
                current_atr = None
                atr_series = self.calculate_atr(self.all_custom_bars, self.ATR_PERIOD)
                if atr_series is not None and not atr_series.empty:
                    current_atr = atr_series.iloc[-1]
                    if pd.isna(current_atr):
                        current_atr = None
                
                atr_log_val = f"{current_atr:.5f}" if current_atr is not None else "N/A" # Format for log

                symbol_info_tick = mt5.symbol_info_tick(self.SYMBOL)
                if symbol_info_tick is None:
                    logging.error(f"Failed to get live tick info for {self.SYMBOL}: {mt5.last_error()}")
                    time.sleep(1)
                    continue

                live_bid_price = symbol_info_tick.bid
                live_ask_price = symbol_info_tick.ask
                live_spread_points = (live_ask_price - live_bid_price) / self.point_value
                live_mid_price = (live_bid_price + live_ask_price) / 2 # Mid price for MA comparison
                
                # --- FIX: Fetch open positions BEFORE using it in the log or trade logic ---
                open_positions = self.get_current_open_positions() # Fetch here!
                num_open_positions = len(open_positions)
                
                reversal_status_log = ""
                if self.sl_hit_active:
                    reversal_status_log = f"REVERSAL_WATCH ({'BUY' if self.sl_hit_direction == mt5.ORDER_TYPE_SELL else 'SELL'} side, count {self.sl_hit_confirmation_count}/{self.REVERSAL_CONFIRMATION_BARS})"
                else:
                    reversal_status_log = "NOT_ACTIVE"

                # Updated comprehensive log message for each iteration
                logging.info(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
                             f"Current Bar: O{current_bar_open:.5f} H{current_bar_high:.5f} L{current_bar_low:.5f} C{current_bar_close:.5f} | "
                             f"Prev Bar: O{prev_bar_open:.5f} H{prev_bar_high:.5f} L{prev_bar_low:.5f} C{prev_bar_close:.5f} | "
                             f"RSI: {current_rsi:.2f} | Stoch: %K {current_percent_k:.2f} %D {current_percent_d:.2f} | "
                             f"Live Prices: Bid {live_bid_price:.5f} Ask {live_ask_price:.5f} Spread {live_spread_points:.2f} | "
                             f"M5 MA: {ma_log_val} (Slope: {self.m5_ma_slope}) | ATR: {atr_log_val} | "
                             f"Open Positions: {num_open_positions}/{self.NUM_CONCURRENT_TRADES} | Reversal Status: {reversal_status_log}")


                # --- Reversal Confirmation Logic ---
                if self.sl_hit_active and self.m5_ma is not None:
                    # Logic is for "reversal TO" the opposite direction of the SL'd trade
                    if self.sl_hit_direction == mt5.ORDER_TYPE_BUY: # Previous trade was a BUY, stopped out going down. Look for SELL reversal.
                        # Check if current bar closes below the MA (confirming downtrend)
                        if current_bar_close < self.m5_ma:
                            self.sl_hit_confirmation_count += 1
                            logging.debug(f"Reversal confirmation for BUY SL hit (looking for SELL): Count {self.sl_hit_confirmation_count}/{self.REVERSAL_CONFIRMATION_BARS}. Current Close ({current_bar_close:.5f}) < MA ({self.m5_ma:.5f}).")
                        else:
                            # If a bar closes on the wrong side, reset count and deactivate
                            logging.debug(f"Reversal confirmation for BUY SL hit RESET. Current Close ({current_bar_close:.5f}) >= MA ({self.m5_ma:.5f}). Deactivating reversal watch.")
                            self.sl_hit_active = False # Deactivate as pattern broken
                            self.sl_hit_confirmation_count = 0
                    elif self.sl_hit_direction == mt5.ORDER_TYPE_SELL: # Previous trade was a SELL, stopped out going up. Look for BUY reversal.
                        # Check if current bar closes above the MA (confirming uptrend)
                        if current_bar_close > self.m5_ma:
                            self.sl_hit_confirmation_count += 1
                            logging.debug(f"Reversal confirmation for SELL SL hit (looking for BUY): Count {self.sl_hit_confirmation_count}/{self.REVERSAL_CONFIRMATION_BARS}. Current Close ({current_bar_close:.5f}) > MA ({self.m5_ma:.5f}).")
                        else:
                            # If a bar closes on the wrong side, reset count and deactivate
                            logging.debug(f"Reversal confirmation for SELL SL hit RESET. Current Close ({current_bar_close:.5f}) <= MA ({self.m5_ma:.5f}). Deactivating reversal watch.")
                            self.sl_hit_active = False # Deactivate as pattern broken
                            self.sl_hit_confirmation_count = 0

                    if self.sl_hit_active and self.sl_hit_confirmation_count >= self.REVERSAL_CONFIRMATION_BARS:
                        # Reversal is confirmed, bypass cooldown and reset flags
                        logging.info(f"REVERSAL CONFIRMED after SL hit! Bypassing cooldown for new entry in {'SELL' if self.sl_hit_direction == mt5.ORDER_TYPE_BUY else 'BUY'} direction. Old trade SL hit on {self.sl_hit_ma_level:.5f} MA.")
                        self.last_trade_closed_timestamp = 0 # This effectively allows new entries
                        self.sl_hit_active = False # Clear all reversal flags
                        self.sl_hit_direction = None
                        self.sl_hit_confirmation_count = 0
                        self.sl_hit_ma_level = None
                # --- End Reversal Confirmation Logic ---


                if (time.time() - self.last_trade_closed_timestamp) < self.COOLDOWN_AFTER_TRADE_SECONDS:
                    remaining_cooldown = self.COOLDOWN_AFTER_TRADE_SECONDS - (time.time() - self.last_trade_closed_timestamp)
                    logging.info(f"Cooldown active (after loss). Waiting {remaining_cooldown:.1f} seconds before new entries.")
                    time.sleep(1)
                    continue

                if live_spread_points > self.MAX_SPREAD_POINTS:
                    logging.info(f"Spread ({live_spread_points:.2f} pts) is too wide (>{self.MAX_SPREAD_POINTS} pts). Skipping new trade entry.")
                    time.sleep(1)
                    continue

                # Calculate dynamic TP for new entries
                dynamic_tp_points = self.TP_POINTS
                if current_atr is not None and not pd.isna(current_atr):
                    calculated_tp = current_atr * self.DYNAMIC_TP_ATR_MULTIPLIER
                    dynamic_tp_points = max(self.MIN_DYNAMIC_TP_POINTS, min(self.MAX_DYNAMIC_TP_POINTS, calculated_tp))
                    logging.debug(f"Calculated dynamic TP: {calculated_tp:.2f} points. Adjusted to: {dynamic_tp_points:.2f} points.")
                else:
                    logging.warning("ATR not available or NaN, using fixed TP_POINTS for new entries.")


                # --- Buy Logic (RSI + Stochastic Crossover + Buy the Dip from MA - Trend Aligned) ---
                # Buy on dip if:
                # 1. M5 MA is available AND trending UP
                # 2. Current price is generally above the M5 MA
                # 3. RSI is oversold
                # 4. Stochastic %K crosses above %D in oversold territory
                # 5. Previous bar's low tested/went below MA, and previous bar's close bounced above MA
                # 6. Number of concurrent trades is below the limit
                if self.m5_ma is not None and \
                   self.m5_ma_slope == "UP" and \
                   live_mid_price > self.m5_ma and \
                   current_rsi < self.RSI_OVERSOLD and \
                   current_percent_k > current_percent_d and \
                   self.all_custom_bars['%k'].iloc[-2] <= self.all_custom_bars['%d'].iloc[-2] and \
                   current_percent_k < self.STOCHASTIC_OVERSOLD + 5 and \
                   prev_bar_low <= self.m5_ma and \
                   prev_bar_close > self.m5_ma and \
                   num_open_positions < self.NUM_CONCURRENT_TRADES and \
                   (time.time() - self.last_buy_entry_timestamp) > self.TRADE_ENTRY_COOLDOWN_SECONDS: # NEW: Buy entry cooldown
                   
                    buy_price = symbol_info_tick.ask
                    dynamic_lot_size = self.calculate_dynamic_lot_size(self.RISK_PERCENT_PER_TRADE, self.SL_POINTS)
                    if dynamic_lot_size <= 0:
                        logging.warning("Calculated lot size is zero or less. Not placing buy order.")
                        time.sleep(1)
                        continue

                    sl = buy_price - self.SL_POINTS * self.point_value
                    tp = buy_price + dynamic_tp_points * self.point_value

                    logging.info(f"RSI {current_rsi:.2f} < {self.RSI_OVERSOLD}, Stochastic BUY Signal (%K: {current_percent_k:.2f}, %D: {current_percent_d:.2f}), AND BUY THE DIP (Prev Low: {prev_bar_low:.5f} <= MA: {self.m5_ma:.5f}, Prev Close: {prev_bar_close:.5f} > MA: {self.m5_ma:.5f}) IN UPTREND (MA Slope: {self.m5_ma_slope}, Price > MA). Sending BUY order with {dynamic_lot_size:.2f} lots (Dynamic TP: {dynamic_tp_points:.2f} pts)...")
                    self.send_order(mt5.ORDER_TYPE_BUY, buy_price, dynamic_lot_size, sl, tp, "RSI+Stoch+MA_DipBuy_TrendGOLD")

                # --- NEW BUY Logic: Trend Continuation After Minor Pullback ---
                # This aims to catch trades when the price is trending strongly,
                # doesn't necessarily dip all the way to the 200 MA, but shows
                # a brief pullback and then a strong bullish reversal candle.
                elif self.m5_ma is not None and \
                     self.m5_ma_slope == "UP" and \
                     live_mid_price > self.m5_ma and \
                     current_rsi < 60 and \
                     current_rsi > 40 and \
                     current_percent_k > current_percent_d and \
                     self.all_custom_bars['%k'].iloc[-2] <= self.all_custom_bars['%d'].iloc[-2] and \
                     prev_bar_close < prev_bar_open and \
                     current_bar_close > current_bar_open and \
                     current_bar_close > prev_bar_high and \
                     num_open_positions < self.NUM_CONCURRENT_TRADES and \
                     (time.time() - self.last_buy_entry_timestamp) > self.TRADE_ENTRY_COOLDOWN_SECONDS: # NEW: Buy entry cooldown

                    buy_price = symbol_info_tick.ask
                    dynamic_lot_size = self.calculate_dynamic_lot_size(self.RISK_PERCENT_PER_TRADE, self.SL_POINTS)
                    if dynamic_lot_size <= 0:
                        logging.warning("Calculated lot size is zero or less. Not placing buy order (Trend Continuation).")
                        time.sleep(1)
                        continue

                    sl = buy_price - self.SL_POINTS * self.point_value
                    tp = buy_price + dynamic_tp_points * self.point_value

                    logging.info(f"RSI {current_rsi:.2f} (40-60 range), Stochastic BUY Signal (%K: {current_percent_k:.2f}, %D: {current_percent_d:.2f}), AND TREND CONTINUATION (Prev bar bearish, Current bar bullish & above Prev High) IN UPTREND. Sending BUY order with {dynamic_lot_size:.2f} lots (Dynamic TP: {dynamic_tp_points:.2f} pts)...")
                    self.send_order(mt5.ORDER_TYPE_BUY, buy_price, dynamic_lot_size, sl, tp, "Trend_Continuation_Buy_GOLD")


                # --- Sell Logic (RSI + Stochastic Crossover + Sell the Rally from MA - Trend Aligned) ---
                # Sell on rally if:
                # 1. M5 MA is available AND trending DOWN
                # 2. Current price is generally below the M5 MA
                # 3. RSI is overbought
                # 4. Stochastic %K crosses below %D in overbought territory
                # 5. Previous bar's high tested/went above MA, and previous bar's close bounced below MA
                # 6. Number of concurrent trades is below the limit
                elif self.m5_ma is not None and \
                     self.m5_ma_slope == "DOWN" and \
                     live_mid_price < self.m5_ma and \
                     current_rsi > self.RSI_OVERBOUGHT and \
                     current_percent_k < current_percent_d and \
                     self.all_custom_bars['%k'].iloc[-2] >= self.all_custom_bars['%d'].iloc[-2] and \
                     current_percent_k > self.STOCHASTIC_OVERBOUGHT - 5 and \
                     prev_bar_high >= self.m5_ma and \
                     prev_bar_close < self.m5_ma and \
                     num_open_positions < self.NUM_CONCURRENT_TRADES and \
                     (time.time() - self.last_sell_entry_timestamp) > self.TRADE_ENTRY_COOLDOWN_SECONDS: # NEW: Sell entry cooldown

                    sell_price = symbol_info_tick.bid
                    dynamic_lot_size = self.calculate_dynamic_lot_size(self.RISK_PERCENT_PER_TRADE, self.SL_POINTS)
                    if dynamic_lot_size <= 0:
                        logging.warning("Calculated lot size is zero or less. Not placing sell order.")
                        time.sleep(1)
                        continue

                    sl = sell_price + self.SL_POINTS * self.point_value
                    tp = sell_price - dynamic_tp_points * self.point_value

                    logging.info(f"RSI {current_rsi:.2f} > {self.RSI_OVERBOUGHT}, Stochastic SELL Signal (%K: {current_percent_k:.2f}, %D: {current_percent_d:.2f}), AND SELL THE RALLY (Prev High: {prev_bar_high:.5f} >= MA: {self.m5_ma:.5f}, Prev Close: {prev_bar_close:.5f} < MA: {self.m5_ma:.5f}) IN DOWNTREND (MA Slope: {self.m5_ma_slope}, Price < MA). Sending SELL order with {dynamic_lot_size:.2f} lots (Dynamic TP: {dynamic_tp_points:.2f} pts)...")
                    self.send_order(mt5.ORDER_TYPE_SELL, sell_price, dynamic_lot_size, sl, tp, "RSI+Stoch+MA_SellRally_TrendGOLD")

                # --- NEW SELL Logic: Trend Continuation After Minor Rally ---
                # Similar to the buy logic, but for downtrends.
                elif self.m5_ma is not None and \
                     self.m5_ma_slope == "DOWN" and \
                     live_mid_price < self.m5_ma and \
                     current_rsi < 60 and \
                     current_rsi > 40 and \
                     current_percent_k < current_percent_d and \
                     self.all_custom_bars['%k'].iloc[-2] >= self.all_custom_bars['%d'].iloc[-2] and \
                     prev_bar_close > prev_bar_open and \
                     current_bar_close < current_bar_open and \
                     current_bar_close < prev_bar_low and \
                     num_open_positions < self.NUM_CONCURRENT_TRADES and \
                     (time.time() - self.last_sell_entry_timestamp) > self.TRADE_ENTRY_COOLDOWN_SECONDS: # NEW: Sell entry cooldown

                    sell_price = symbol_info_tick.bid
                    dynamic_lot_size = self.calculate_dynamic_lot_size(self.RISK_PERCENT_PER_TRADE, self.SL_POINTS)
                    if dynamic_lot_size <= 0:
                        logging.warning("Calculated lot size is zero or less. Not placing sell order (Trend Continuation).")
                        time.sleep(1)
                        continue

                    sl = sell_price + self.SL_POINTS * self.point_value
                    tp = sell_price - dynamic_tp_points * self.point_value

                    logging.info(f"RSI {current_rsi:.2f} (40-60 range), Stochastic SELL Signal (%K: {current_percent_k:.2f}, %D: {current_percent_d:.2f}), AND TREND CONTINUATION (Prev bar bullish, Current bar bearish & below Prev Low) IN DOWNTREND. Sending SELL order with {dynamic_lot_size:.2f} lots (Dynamic TP: {dynamic_tp_points:.2f} pts)...")
                    self.send_order(mt5.ORDER_TYPE_SELL, sell_price, dynamic_lot_size, sl, tp, "Trend_Continuation_Sell_GOLD")

                # --- Manage existing positions ---
                if open_positions:
                    self.manage_positions(open_positions)

            except Exception as e:
                logging.exception(f"An unexpected error occurred in main loop: {e}")

            time.sleep(1)

        self.disconnect_mt5()

# --- Run the bot ---
if __name__ == "__main__":
    bot = GoldScalperBot()
    bot.run_scalping_bot()