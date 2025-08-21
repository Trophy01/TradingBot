import MetaTrader5 as mt5

print("Testing MT5 connection...")
if mt5.initialize():
    account_info = mt5.account_info()
    if account_info:
        print(f"SUCCESS: Connected to account {account_info.login}")
        print(f"Account type: {'DEMO' if account_info.trade_mode == 0 else 'LIVE'}")
        print(f"Balance: ${account_info.balance}")
        print(f"Equity: ${account_info.equity}")
        
        # Test XAUUSD access
        symbol_info = mt5.symbol_info("XAUUSD")
        if symbol_info:
            print(f"XAUUSD found: Current bid {symbol_info.bid}")
        else:
            print("XAUUSD not found - add it to Market Watch")
    else:
        print("ERROR: MT5 running but no account logged in")
    mt5.shutdown()
else:
    print("ERROR: Cannot connect to MT5")