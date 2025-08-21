"""
Demo script showing the Enhanced Gold Scalper Bot's superior information display
Run this to see how the enhanced messages look without needing MT5 connection
"""

import time
import random
from datetime import datetime
from colorama import Fore, Style, init

# Initialize colorama for colored output
init(autoreset=True)

class EnhancedDisplayDemo:
    def __init__(self):
        self.session_stats = {
            'trades_opened': 0,
            'trades_closed': 0,
            'total_profit': 0.0,
            'winning_trades': 0,
            'losing_trades': 0,
            'session_start': datetime.now(),
            'largest_win': 0.0,
            'largest_loss': 0.0
        }
    
    def display_startup_banner(self):
        """Display startup banner"""
        banner = f"""
{Fore.YELLOW}{'='*80}
{Fore.CYAN}     🏆 ENHANCED GOLD SCALPER BOT v2.0 - DEMO MODE 🏆
{Fore.YELLOW}{'='*80}
{Fore.GREEN}Symbol: XAUUSD | Risk per Trade: 3.0%
{Fore.GREEN}RSI Period: 14 | Stochastic: 14/3
{Fore.GREEN}Stop Loss: 300 pts | Take Profit: Dynamic ATR-based
{Fore.GREEN}Max Concurrent Trades: 3
{Fore.YELLOW}{'='*80}{Style.RESET_ALL}
        """
        print(banner)
        print(f"{Fore.CYAN}🚀 This is a DEMO showing the enhanced display features{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}No actual trading will occur - just visual demonstration{Style.RESET_ALL}")
        print()

    def format_rsi_status(self, rsi):
        """Format RSI with color coding"""
        if rsi > 70:
            return f"{Fore.RED}{rsi:.1f} (OVERBOUGHT){Style.RESET_ALL}"
        elif rsi < 30:
            return f"{Fore.GREEN}{rsi:.1f} (OVERSOLD){Style.RESET_ALL}"
        else:
            return f"{Fore.WHITE}{rsi:.1f} (NEUTRAL){Style.RESET_ALL}"

    def format_stochastic_status(self, k, d):
        """Format Stochastic with signal indication"""
        if k > d and k < 30:
            signal = f"{Fore.GREEN}BUY SIGNAL{Style.RESET_ALL}"
        elif k < d and k > 70:
            signal = f"{Fore.RED}SELL SIGNAL{Style.RESET_ALL}"
        else:
            signal = f"{Fore.WHITE}NEUTRAL{Style.RESET_ALL}"
        
        return f"%K:{k:.1f} %D:{d:.1f} ({signal})"

    def print_market_status(self, current_price, rsi, stoch_k, stoch_d, atr, ma_value, spread, positions_count):
        """Print beautifully formatted market status"""
        trend = "BULLISH (UP)" if current_price > ma_value else "BEARISH (DOWN)"
        trend_color = Fore.GREEN if current_price > ma_value else Fore.RED
        
        spread_status = "GOOD" if spread <= 2.5 else "CAUTION" if spread <= 4 else "TOO HIGH!"
        spread_color = Fore.GREEN if spread <= 2.5 else Fore.YELLOW if spread <= 4 else Fore.RED
        
        pos_status = "READY" if positions_count == 0 else f"ACTIVE ({positions_count}/3)"
        pos_color = Fore.WHITE if positions_count == 0 else Fore.YELLOW
        
        status = f"""
{Fore.CYAN}📊 MARKET STATUS UPDATE {Fore.YELLOW}[{datetime.now().strftime('%H:%M:%S')}]{Style.RESET_ALL}
{Fore.WHITE}├─ 💰 XAUUSD Price: {Fore.YELLOW}${current_price:.2f}{Style.RESET_ALL}
{Fore.WHITE}├─ 📈 RSI (14): {self.format_rsi_status(rsi)}
{Fore.WHITE}├─ 🔄 Stochastic: {self.format_stochastic_status(stoch_k, stoch_d)}
{Fore.WHITE}├─ 📏 ATR (20): {Fore.CYAN}{atr:.3f}{Style.RESET_ALL}
{Fore.WHITE}├─ 📊 MA (200): {Fore.CYAN}${ma_value:.2f}{Style.RESET_ALL} - {trend_color}{trend}{Style.RESET_ALL}
{Fore.WHITE}├─ 💸 Spread: {spread_color}{spread:.1f} pts ({spread_status}){Style.RESET_ALL}
{Fore.WHITE}└─ 🎯 Open Positions: {pos_color}{pos_status}{Style.RESET_ALL}
        """
        print(status)

    def print_trade_signal(self, signal_type, reasoning, entry_price, sl, tp, lot_size):
        """Print detailed trade signal information"""
        signal_color = Fore.GREEN if signal_type == "BUY" else Fore.RED
        sl_pts = abs((entry_price-sl)*100)
        tp_pts = abs((tp-entry_price)*100)
        risk_reward = tp_pts / sl_pts if sl_pts > 0 else 0
        
        trade_info = f"""
{signal_color}🎯 {signal_type} TRADE SIGNAL DETECTED! {Style.RESET_ALL}
{Fore.WHITE}┌─ 📋 TRADE REASONING:{Style.RESET_ALL}
{Fore.WHITE}│  {reasoning}{Style.RESET_ALL}
{Fore.WHITE}├─ 💼 TRADE DETAILS:{Style.RESET_ALL}
{Fore.WHITE}│  Entry Price: {Fore.YELLOW}${entry_price:.2f}{Style.RESET_ALL}
{Fore.WHITE}│  Stop Loss:   {Fore.RED}${sl:.2f} (-{sl_pts:.0f} pts){Style.RESET_ALL}
{Fore.WHITE}│  Take Profit: {Fore.GREEN}${tp:.2f} (+{tp_pts:.0f} pts){Style.RESET_ALL}
{Fore.WHITE}│  Lot Size:    {Fore.CYAN}{lot_size:.2f} lots{Style.RESET_ALL}
{Fore.WHITE}└─ 🎲 Risk:Reward = 1:{risk_reward:.2f}{Style.RESET_ALL}
        """
        print(trade_info)

    def print_trade_result(self, ticket, profit, reason):
        """Print trade result"""
        result_color = Fore.GREEN if profit > 0 else Fore.RED
        profit_symbol = "💰" if profit > 0 else "💸"
        result_type = "WIN" if profit > 0 else "LOSS"
        
        # Update stats
        self.session_stats['trades_closed'] += 1
        self.session_stats['total_profit'] += profit
        
        if profit > 0:
            self.session_stats['winning_trades'] += 1
            if profit > self.session_stats['largest_win']:
                self.session_stats['largest_win'] = profit
        else:
            self.session_stats['losing_trades'] += 1
            if profit < self.session_stats['largest_loss']:
                self.session_stats['largest_loss'] = profit
        
        pnl_color = Fore.GREEN if self.session_stats['total_profit'] > 0 else Fore.RED
        session_pnl = f"{pnl_color}${self.session_stats['total_profit']:.2f}{Style.RESET_ALL}"
        
        result_info = f"""
{result_color}{profit_symbol} TRADE CLOSED - {result_type}{Style.RESET_ALL}
{Fore.WHITE}├─ Ticket: {Fore.CYAN}#{ticket}{Style.RESET_ALL}
{Fore.WHITE}├─ P&L: {result_color}${profit:.2f}{Style.RESET_ALL}
{Fore.WHITE}├─ Reason: {Fore.YELLOW}{reason}{Style.RESET_ALL}
{Fore.WHITE}└─ Session P&L: {session_pnl}{Style.RESET_ALL}
        """
        print(result_info)

    def print_session_summary(self):
        """Print session summary"""
        stats = self.session_stats
        runtime = datetime.now() - stats['session_start']
        win_rate = (stats['winning_trades'] / max(stats['trades_closed'], 1)) * 100
        
        win_rate_color = Fore.GREEN if win_rate >= 70 else Fore.YELLOW if win_rate >= 50 else Fore.RED
        win_rate_desc = "EXCELLENT" if win_rate >= 70 else "GOOD" if win_rate >= 50 else "NEEDS IMPROVEMENT"
        
        summary = f"""
{Fore.YELLOW}{'='*60}{Style.RESET_ALL}
{Fore.CYAN}📊 TRADING SESSION SUMMARY{Style.RESET_ALL}
{Fore.YELLOW}{'='*60}{Style.RESET_ALL}
{Fore.WHITE}Session Runtime: {Fore.CYAN}{str(runtime).split('.')[0]}{Style.RESET_ALL}
{Fore.WHITE}Trades Opened:   {Fore.YELLOW}{stats['trades_opened']}{Style.RESET_ALL}
{Fore.WHITE}Trades Closed:   {Fore.YELLOW}{stats['trades_closed']}{Style.RESET_ALL}
{Fore.WHITE}Win Rate:        {win_rate_color}{win_rate:.1f}% ({win_rate_desc}){Style.RESET_ALL}
{Fore.WHITE}Total P&L:       {Fore.GREEN if stats['total_profit'] > 0 else Fore.RED}${stats['total_profit']:.2f}{Style.RESET_ALL}
{Fore.WHITE}Largest Win:     {Fore.GREEN}+${stats['largest_win']:.2f}{Style.RESET_ALL}
{Fore.WHITE}Largest Loss:    {Fore.RED}${stats['largest_loss']:.2f}{Style.RESET_ALL}
{Fore.YELLOW}{'='*60}{Style.RESET_ALL}
        """
        print(summary)

    def print_waiting_message(self, message):
        """Print waiting message"""
        print(f"{Fore.BLUE}⏳ {message}{Style.RESET_ALL}")

    def run_demo(self):
        """Run the demonstration"""
        self.display_startup_banner()
        
        print(f"{Fore.GREEN}🎬 Starting enhanced display demonstration...{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}Watch how clear and informative the messages are!{Style.RESET_ALL}")
        print()
        
        try:
            # Simulate market data
            base_price = 2650.0
            base_ma = 2648.0
            
            for i in range(20):  # 20 demo iterations
                # Generate realistic market data
                current_price = base_price + random.uniform(-5, 5)
                rsi = random.uniform(20, 80)
                stoch_k = random.uniform(15, 85)
                stoch_d = stoch_k + random.uniform(-5, 5)
                atr = random.uniform(12, 18)
                ma_value = base_ma + random.uniform(-2, 2)
                spread = random.uniform(1.5, 6.0)
                positions = random.randint(0, 3)
                
                # Show market status every few iterations
                if i % 3 == 0:
                    self.print_market_status(current_price, rsi, stoch_k, stoch_d, atr, ma_value, spread, positions)
                
                # Simulate trade signals
                if i % 7 == 0:
                    signal_type = "BUY" if rsi < 35 else "SELL"
                    if signal_type == "BUY":
                        reasoning = f"RSI oversold ({rsi:.1f}) + Stochastic bullish crossover + Price above MA trend"
                        sl = current_price - 3.0
                        tp = current_price + 10.0
                    else:
                        reasoning = f"RSI overbought ({rsi:.1f}) + Stochastic bearish crossover + Price below MA trend"
                        sl = current_price + 3.0
                        tp = current_price - 10.0
                    
                    self.print_trade_signal(signal_type, reasoning, current_price, sl, tp, 0.05)
                    self.session_stats['trades_opened'] += 1
                
                # Simulate trade results
                if i % 9 == 0 and self.session_stats['trades_opened'] > self.session_stats['trades_closed']:
                    profit = random.choice([15.50, -8.75, 22.30, -12.40, 31.20, -15.80])
                    reason = "Take Profit Hit" if profit > 0 else "Stop Loss Hit"
                    self.print_trade_result(12000 + i, profit, reason)
                
                # Show waiting messages occasionally
                if i % 5 == 0:
                    messages = [
                        "Analyzing market conditions...",
                        "Monitoring for entry signals...",
                        "Waiting for optimal spread conditions...",
                        "Checking risk parameters...",
                        "Scanning for trend confirmation..."
                    ]
                    self.print_waiting_message(random.choice(messages))
                
                # Show session summary periodically
                if i == 15:
                    self.print_session_summary()
                
                time.sleep(2)  # 2 second delay for demo
        
        except KeyboardInterrupt:
            print(f"\n{Fore.YELLOW}🛑 Demo interrupted by user{Style.RESET_ALL}")
        
        print(f"\n{Fore.GREEN}🎬 Demo complete!{Style.RESET_ALL}")
        self.print_session_summary()
        
        print(f"\n{Fore.CYAN}As you can see, the enhanced bot provides:{Style.RESET_ALL}")
        print(f"{Fore.WHITE}✅ Clear, color-coded status updates{Style.RESET_ALL}")
        print(f"{Fore.WHITE}✅ Detailed trade reasoning{Style.RESET_ALL}")
        print(f"{Fore.WHITE}✅ Real-time performance tracking{Style.RESET_ALL}")
        print(f"{Fore.WHITE}✅ User-friendly progress indicators{Style.RESET_ALL}")
        print(f"{Fore.WHITE}✅ Professional presentation{Style.RESET_ALL}")

if __name__ == "__main__":
    demo = EnhancedDisplayDemo()
    demo.run_demo()