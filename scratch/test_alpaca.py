import sys, os
sys.stdout.reconfigure(encoding='utf-8')
os.chdir('d:/stocks')
from dotenv import load_dotenv
load_dotenv()
from src.execution.alpaca_client import AlpacaClient

c = AlpacaClient()
data = c.get_positions('test')
cash = data['cash']
positions = data['positions']

print("=== ALPACA PAPER ACCOUNT ===")
print(f"Cash Balance:  ${cash['cash_balance']:,.2f}")
print(f"Net Equity:    ${cash['net_liquidity']:,.2f}")
print(f"Open Positions: {len(positions)}")
for p in positions:
    print(f"  {p['symbol']:6s}  qty={p['qty']}  avg_entry=${p['cost_price']:.2f}  P&L=${p['unrealized_pl']:.2f}")
print("=== CONNECTION SUCCESSFUL ===")
