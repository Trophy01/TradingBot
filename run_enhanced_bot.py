"""
Runner script for the Enhanced Gold Scalper Bot
Run this script to start the enhanced bot with better information display
"""

import sys
import os

# Add current directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    from enhanced_gold_scalper_bot import EnhancedGoldScalperBot
    
    print("🚀 Starting Enhanced Gold Scalper Bot...")
    print("Make sure MT5 is running and you're logged into your account!")
    print("Press Ctrl+C at any time to stop the bot safely.")
    print("-" * 60)
    
    # Create and run the bot
    bot = EnhancedGoldScalperBot()
    bot.run_enhanced_bot()
    
except ImportError as e:
    print(f"❌ Error importing bot: {e}")
    print("Make sure enhanced_gold_scalper_bot.py is in the same directory")
    
except Exception as e:
    print(f"❌ Error running bot: {e}")
    print("Check the error log for more details")
    
finally:
    print("\n✅ Bot session ended.")
    input("Press Enter to exit...")