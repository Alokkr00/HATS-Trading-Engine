"""Place a real test order on Alpaca paper trading and verify it went through."""
import sys, os
sys.stdout.reconfigure(encoding='utf-8')
os.chdir('d:/stocks')
from dotenv import load_dotenv
load_dotenv()
from src.execution.alpaca_client import AlpacaClient
import time

c = AlpacaClient()

print("=== PLACING TEST MARKET ORDER: BUY 1 SPY ===")
result = c.place_order(
    account_id="test",
    symbol="SPY",
    side="BUY",
    qty=1,
    price=None,        # Market order
    stop_price=None,
    client_order_id="hats_test_001"
)
print(f"Order submitted: {result}")

# Wait a moment for fill
time.sleep(3)

# Check order status
order_status = c.get_order(result['order_id'])
print(f"Order status:   {order_status}")

# Check positions updated
data = c.get_positions('test')
print(f"\nCash remaining: ${data['cash']['cash_balance']:,.2f}")
print(f"Net equity:     ${data['cash']['net_liquidity']:,.2f}")
print(f"Open positions: {len(data['positions'])}")
for p in data['positions']:
    print(f"  {p['symbol']:6s}  qty={p['qty']}  avg_entry=${p['cost_price']:.2f}  market_val=${p['market_value']:.2f}")

print("\n=== TEST COMPLETE - NOW SELLING BACK ===")
sell_result = c.place_order(
    account_id="test",
    symbol="SPY",
    side="SELL",
    qty=1,
    price=None,
    stop_price=None,
    client_order_id="hats_test_002"
)
print(f"Sell order: {sell_result}")
print("Done. Orders are real and hitting Alpaca paper trading.")
