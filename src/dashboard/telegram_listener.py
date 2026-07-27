"""Interactive Telegram Assistant Bot listener for read-only H.A.T.S trading suite auditing."""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import time
import urllib.request
import urllib.parse
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
EXECUTION_DIR = PROJECT_ROOT / "data" / "execution"


class TelegramListener:
    """Listens to incoming Telegram commands and queries H.A.T.S systems to reply."""

    def __init__(self, token: str | None = None, chat_id: str | None = None) -> None:
        """Initialize listener credentials."""
        load_dotenv()
        self.token = token or os.getenv("TELEGRAM_BOT_TOKEN")
        self.chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID")
        self.offset = 0
        self.running = False
        
        if not self.token or not self.chat_id:
            raise ValueError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set in the environment.")

    def send_message(self, text: str) -> None:
        """Utility to send a message back to the verified chat ID."""
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "Markdown"
        }
        try:
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=5) as response:
                response.read()
        except Exception as e:
            logger.error(f"TelegramListener failed to send reply message: {e}")

    def handle_command(self, text: str) -> None:
        """Parse incoming text commands and execute corresponding read actions."""
        cmd_parts = text.split(maxsplit=1)
        if not cmd_parts:
            return
            
        command = cmd_parts[0].lower()
        args = cmd_parts[1].strip() if len(cmd_parts) > 1 else ""
        
        logger.info(f"Processing command: {command} with args: '{args}'")
        
        if command in ("/start", "/help"):
            self.send_help()
        elif command == "/status":
            self.send_status()
        elif command == "/trades":
            self.send_trades()
        elif command == "/news":
            self.send_news(args)
        elif command == "/report":
            self.send_report()
        else:
            self.send_message(f"❌ Unknown command: `{command}`. Type `/help` to see available options.")

    def send_help(self) -> None:
        """Reply with available options."""
        help_text = (
            "🤖 **H.A.T.S Operational Assistant**\n\n"
            "You can control and query your system using these commands:\n"
            "• `/status` - Check current bot state, cash balance, and open positions.\n"
            "• `/trades` - View fills and transactions executed today.\n"
            "• `/news <symbol>` - Get recent market news and headlines from Yahoo Finance.\n"
            "• `/report` - Trigger and compile a Weekly Audit Report immediately.\n"
            "• `/help` - View this instruction list."
        )
        self.send_message(help_text)

    def send_status(self) -> None:
        """Reply with system status, active positions, and cash balance."""
        # 1. Check if bot is running
        flag_file = EXECUTION_DIR / "bot_running.flag"
        bot_active = flag_file.exists()
        bot_state_str = "🟢 **ACTIVE (Trading Enabled)**" if bot_active else "🔴 **PAUSED (Execution Suspended)**"
        
        # 2. Check OMS state
        state_file = EXECUTION_DIR / "oms_state.json"
        cash = 100000.0
        positions = []
        
        if state_file.exists():
            try:
                with open(state_file, "r", encoding="utf-8") as f:
                    state = json.load(f)
                portfolio = state.get("portfolio", {})
                cash_val = portfolio.get("cash", 100000.0)
                if isinstance(cash_val, dict):
                    cash = float(cash_val.get("cash_balance") or cash_val.get("net_liquidity") or 100000.0)
                else:
                    cash = float(cash_val)
                pos_dict = portfolio.get("positions", {})
                
                for sym, info in pos_dict.items():
                    qty = info.get("quantity") or info.get("qty") or 0
                    price = info.get("avg_price") or info.get("entry_price") or 0.0
                    positions.append(f"• `{sym}`: {qty} shares @ ${price:.2f}")
            except Exception as e:
                logger.error(f"Status command failed to parse OMS state: {e}")
                
        positions_str = "\n".join(positions) if positions else "• *No open positions held.*"
        
        # 3. Read engine status
        engine_file = EXECUTION_DIR / "engine_status.json"
        heat_str = "N/A"
        stress_str = "N/A"
        if engine_file.exists():
            try:
                with open(engine_file, "r", encoding="utf-8") as f:
                    estatus = json.load(f)
                heat_str = f"{estatus.get('portfolio_heat', 0.0) * 100.0:.2f}%"
            except Exception:
                pass

        status_msg = (
            f"💻 **H.A.T.S System Status**\n\n"
            f"• **Execution State**: {bot_state_str}\n"
            f"• **Available Cash**: ${cash:,.2f}\n"
            f"• **Portfolio Heat**: `{heat_str}`\n\n"
            f"📦 **Open Positions**:\n{positions_str}"
        )
        self.send_message(status_msg)

    def send_trades(self) -> None:
        """Reply with trades executed today."""
        from src.execution.db_manager import DatabaseManager
        db_path = PROJECT_ROOT / "data" / "execution" / "trading_bot.db"
        
        if not db_path.exists():
            self.send_message("❌ No execution database found.")
            return
            
        try:
            db = DatabaseManager(str(db_path))
            today_iso = dt.date.today().isoformat()
            
            rows = db.execute_query(
                "SELECT symbol, side, qty, price, timestamp FROM transactions WHERE timestamp >= :today ORDER BY timestamp DESC;",
                {"today": today_iso}
            ).fetchall()
            
            if not rows:
                self.send_message("ℹ️ No transactions executed today.")
                return
                
            trade_lines = []
            for r in rows:
                sym, side, qty, price, ts = r[0], r[1], r[2], r[3], r[4]
                try:
                    time_part = dt.datetime.fromisoformat(ts).strftime("%H:%M:%S")
                except Exception:
                    time_part = ts
                emoji = "🟢" if side == "BUY" else "🔴"
                trade_lines.append(f"{emoji} `{time_part}`: {side} {qty} `{sym}` @ ${float(price):.2f}")
                
            msg = "📈 **Transactions Executed Today**:\n\n" + "\n".join(trade_lines)
            self.send_message(msg)
        except Exception as e:
            logger.error(f"Failed to query today's trades: {e}")
            self.send_message(f"❌ Database error: {e}")

    def send_news(self, symbol: str) -> None:
        """Reply with latest 3 news headlines for a stock ticker from Yahoo Finance."""
        if not symbol:
            self.send_message("⚠️ Please specify a stock ticker. Example: `/news AAPL`")
            return
            
        ticker = symbol.upper().strip()
        try:
            import yfinance as yf
            stock = yf.Ticker(ticker)
            news = stock.news
            
            if not news:
                self.send_message(f"ℹ️ No recent headlines found for ticker `{ticker}`.")
                return
                
            news_lines = []
            for item in news[:3]:
                title = item.get("title", "Headline")
                link = item.get("link", "")
                publisher = item.get("publisher", "Yahoo Finance")
                news_lines.append(f"• **{publisher}**: [{title}]({link})")
                
            msg = f"📰 **Latest News for `{ticker}`**:\n\n" + "\n".join(news_lines)
            self.send_message(msg)
        except Exception as e:
            logger.error(f"Failed to retrieve news for {ticker}: {e}")
            self.send_message(f"❌ Failed to retrieve news: {e}")

    def send_report(self) -> None:
        """Trigger weekly performance report compilation and send it."""
        self.send_message("⏳ Compiling Weekly Operational Report...")
        try:
            from src.dashboard.report_generator import WeeklyReportGenerator
            generator = WeeklyReportGenerator()
            report_md, _ = generator.generate_weekly_report()
            generator.send_report_summary(report_md)
        except Exception as e:
            logger.error(f"Failed to compile report from Telegram command: {e}")
            self.send_message(f"❌ Failed to compile report: {e}")

    def start_polling(self) -> None:
        """Start the long-polling listener loop to receive updates."""
        self.running = True
        logger.info("Starting Telegram Bot listener daemon (long polling)...")
        
        # 1. Clear backlog on startup to avoid re-processing old events
        try:
            logger.info("Clearing Telegram update backlog on startup...")
            # Query the single last update with offset=-1 and a short timeout
            url = f"https://api.telegram.org/bot{self.token}/getUpdates?offset=-1&limit=1&timeout=0"
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=5) as response:
                res_data = json.loads(response.read().decode("utf-8"))
                if res_data.get("ok"):
                    results = res_data.get("result", [])
                    if results:
                        last_update_id = results[0].get("update_id", 0)
                        self.offset = last_update_id + 1
                        logger.info(f"Backlog cleared. Resuming updates starting from offset {self.offset}.")
                    else:
                        logger.info("No updates backlog to clear.")
        except Exception as e:
            logger.warning(f"Could not clear Telegram backlog on startup: {e}")

        while self.running:
            url = f"https://api.telegram.org/bot{self.token}/getUpdates?offset={self.offset}&timeout=30"
            try:
                req = urllib.request.Request(url, method="GET")
                with urllib.request.urlopen(req, timeout=35) as response:
                    res_data = json.loads(response.read().decode("utf-8"))
                    
                if not res_data.get("ok"):
                    logger.error(f"Telegram API getUpdates returned error: {res_data}")
                    time.sleep(5)
                    continue
                    
                updates = res_data.get("result", [])
                for update in updates:
                    update_id = update.get("update_id", 0)
                    self.offset = max(self.offset, update_id + 1)
                    
                    message = update.get("message", {})
                    chat = message.get("chat", {})
                    chat_id = chat.get("id")
                    text = message.get("text", "").strip()
                    
                    if not chat_id or not text:
                        continue
                        
                    # Security gate: verify correct user Chat ID
                    if str(chat_id) != str(self.chat_id):
                        logger.warning(f"Unauthorized message access attempt from Chat ID: {chat_id} (Text: '{text}'). Ignoring.")
                        continue
                        
                    self.handle_command(text)
            except (TimeoutError, urllib.error.URLError) as ue:
                # Expected timeout or temporary dropout during long-polling
                logger.debug(f"Telegram polling connection timeout/dropout: {ue}")
                time.sleep(2)
            except Exception as e:
                logger.error(f"Error inside Telegram polling loop: {e}", exc_info=True)
                time.sleep(5)

    def stop_polling(self) -> None:
        """Stop the polling loop."""
        self.running = False
        logger.info("Stopping Telegram Bot listener daemon...")
