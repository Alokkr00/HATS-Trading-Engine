"""Cancel all pending orders on Alpaca paper account."""
import os, sys
sys.stdout.reconfigure(encoding='utf-8')
os.chdir('d:/stocks')
from dotenv import load_dotenv
load_dotenv()
from src.execution.alpaca_client import AlpacaClient

c = AlpacaClient()

# Get all open orders
orders = c.get_open_orders('all')
print(f"Found {len(orders)} open orders. Cancelling all...")

from alpaca.trading.client import TradingClient
tc = TradingClient(os.getenv('APCA_API_KEY_ID'), os.getenv('APCA_API_SECRET_KEY'), paper=True)
cancel_responses = tc.cancel_orders()
print(f"Cancelled {len(cancel_responses)} orders.")

# Confirm
remaining = c.get_open_orders('all')
print(f"Remaining open orders: {len(remaining)}")
print("Order book is now clean.")
