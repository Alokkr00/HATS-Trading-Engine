"""Main execution entrypoint for the algorithmic trading bot.

This script loads configuration settings, fetches latest daily market data,
cleans it, runs strategy rule pipelines, sizes trades according to risk limits,
and executes them via the Order Management System (OMS).
"""

from __future__ import annotations

import datetime as dt
import logging
import os
import sys
import json
from pathlib import Path
import concurrent.futures
import pandas as pd

import math
from src.config_loader import get_settings, load_env, get_risk_settings
from src.data.cleaner import DataCleaner
from src.data.fetcher import DataFetcher
from src.data.store import DataStore
from src.execution.oms import OrderManager
from src.execution.alpaca_client import AlpacaClient
from src.strategy.portfolio import PositionSizer
from src.strategy.strategies import (
    MACrossoverStrategy,
    RSIMeanReversionStrategy,
    BollingerSqueezeStrategy,
    IchimokuCloudStrategy,
    PivotPointReversionStrategy,
    SectorMomentumStrategy,
    OptionsIVRunupStrategy,
    BreadthThrustReversionStrategy,
    MACDHistogramStrategy,
    DonchianChannelBreakoutStrategy,
    StochasticOscillatorStrategy,
    ZScoreMeanReversionStrategy,
    LinearRegressionChannelStrategy,
    PairsTradingStrategy,
)
from src.strategy.regime import MarketRegimeClassifier
from src.risk.circuit_breaker import CircuitBreaker
from src.risk.heat_tracker import PortfolioHeatTracker
from src.execution.sector_resolver import SectorResolver
from src.utils.logger import get_logger
from src.utils.notifier import send_telegram_alert

# Configure structured logging
logger = get_logger(__name__)


def run_trading_cycle(interval: str = "1d", use_options: bool = False, force_run: bool = False) -> None:
    """Run a single systematic trading cycle for the given interval timeframe."""
    logger.info(f"Starting systematic trading cycle for interval: {interval} (Options Mode: {use_options})...")

    # 0. Market Hours Check
    from src.utils.helpers import is_market_open
    if not force_run and not is_market_open():
        logger.info("Market is closed. Skipping trading cycle.")
        send_telegram_alert("ℹ️ H.A.T.S cycle skipped — market is closed.")
        return

    # 1. Load configuration and credentials
    load_env()
    settings = get_settings()
    watchlist = list(settings.get("watchlist", ["AAPL", "MSFT", "SPY", "QQQ", "TSLA"]))
    
    # Append Sector ETFs, Inverse ETFs, and VIX to watchlist
    sector_etfs = settings.get("sector_etfs", [])
    for etf in sector_etfs:
        if etf not in watchlist:
            watchlist.append(etf)
            
    inverse_map = settings.get("inverse_map", {})
    for inv in inverse_map.values():
        if inv not in watchlist:
            watchlist.append(inv)
            
    if "^VIX" not in watchlist:
        watchlist.append("^VIX")
        
    data_settings = settings.get("data", {})
    raw_dir = data_settings.get("raw_dir", "data/raw")
    
    # Intraday limits: yfinance allows a maximum of 30-60 days of 15m or 1h data
    if interval == "1d":
        history_days = data_settings.get("default_history_days", 730)
    else:
        history_days = 30
        logger.info(f"Applying intraday data length cap of {history_days} days to comply with API retrieval limits.")

    # Initialize dynamic sector resolver
    resolver = SectorResolver(Path(raw_dir).parent / "execution" / "sector_cache.json")

    # Calculate date ranges
    end_date = dt.datetime.now()
    start_date = end_date - dt.timedelta(days=history_days)
    
    start_str = start_date.strftime("%Y-%m-%d")
    end_str = end_date.strftime("%Y-%m-%d")

    # 2. Ingest, clean, and cache market data
    logger.info(f"Ingesting historical data from {start_str} to {end_str} for {len(watchlist)} tickers...")
    fetcher = DataFetcher()
    cleaner = DataCleaner()
    store = DataStore(raw_dir=raw_dir)

    def download_and_clean(sym: str) -> None:
        try:
            symbol_start_str = start_str
            if store.has_symbol(sym):
                date_range = store.get_date_range(sym)
                if date_range is not None:
                    min_date, max_date = date_range
                    today = pd.Timestamp.now().normalize()
                    target_start_dt = pd.Timestamp(start_str)
                    
                    # If local cache starts too late (e.g. we only have 2 years but want 10 years), full fetch
                    if min_date > target_start_dt + pd.Timedelta(days=5):
                        logger.info(f"[{sym}] Cache range insufficient ({min_date.strftime('%Y-%m-%d')} > target {start_str}). Performing full fetch...")
                    # If max_date is older than yesterday, fetch only the missing window
                    elif max_date < today - pd.Timedelta(days=1):
                        symbol_start_str = (max_date + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
                        logger.info(f"[{sym}] Performing incremental fetch from {symbol_start_str} to {end_str}...")
                    else:
                        logger.info(f"[{sym}] Cache is up to date (last bar: {max_date.strftime('%Y-%m-%d')}). Skipping fetch.")
                        return

            raw_df = fetcher.fetch(sym, start=symbol_start_str, end=end_str, interval=interval)
            clean_df, report = cleaner.clean(raw_df, symbol=sym)
            store.save(sym, clean_df)
            logger.info(f"Successfully cached and cleaned {sym} ({len(clean_df)} bars) [Parallel]")
        except Exception as e:
            logger.error(f"Failed to fetch/clean data for {sym}: {e}")

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        executor.map(download_and_clean, watchlist)

    # 3. Initialize Alpaca Client and Order Management System (OMS)
    client = AlpacaClient()
    account_id = os.getenv("APCA_API_KEY_ID", "alpaca_paper")
    oms = OrderManager(client, account_id=account_id)

    # Sync portfolio state with broker
    portfolio_state = oms.sync_portfolio()
    cash_data = portfolio_state.get("cash", {})
    net_equity = cash_data.get("net_liquidity", 100000.0)
    cash_bal = cash_data.get("cash_balance", 100000.0)
    current_positions = list(portfolio_state.get("positions", {}).values())

    # Fetch symbols with pending/open orders from broker to prevent duplicates
    pending_order_symbols: set[str] = set()
    try:
        open_orders = client.get_open_orders(account_id)
        pending_order_symbols = {o["symbol"] for o in open_orders}
        if pending_order_symbols:
            logger.info(f"Pending orders detected for: {sorted(pending_order_symbols)} — will skip re-entry.")
    except Exception as e:
        logger.warning(f"Could not fetch open orders for deduplication check: {e}")

    logger.info(f"Portfolio synced. Net Equity: {net_equity:.2f}, Cash: {cash_bal:.2f}, Active Positions: {len(current_positions)}, Pending Orders: {len(pending_order_symbols)}")

    # 4. Initialize Risk Controls and Circuit Breaker
    risk_settings = get_risk_settings()
    cb = CircuitBreaker(risk_settings)
    heat_tracker = PortfolioHeatTracker(risk_settings.get("portfolio", {}).get("max_portfolio_heat_pct", 0.06))

    # Calculate trades today count from transactions db table
    today_start = dt.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    try:
        res = oms.db.execute_query(
            "SELECT COUNT(*) FROM transactions WHERE timestamp >= :ts;", {"ts": today_start}
        ).fetchone()
        trades_today = res[0] if res else 0
    except Exception:
        trades_today = 0

    allowed, reason = cb.check(net_liquidity=net_equity, trades_today=trades_today)
    if not allowed:
        logger.critical(f"Trading cycle blocked by Circuit Breaker: {reason}")
        send_telegram_alert(f"⚠️ **H.A.T.S Circuit Breaker Active**: {reason}. Cycle skipped.")
        return

    # Load 60-day price history of watchlist to compute correlations
    price_data = {}
    for sym in watchlist:
        try:
            p_df = store.load(sym, tz="US/Eastern")
            if p_df is not None and not p_df.empty:
                price_data[sym] = p_df
        except Exception:
            pass

    # 4B. Market Regime Classification
    vix_val = None
    try:
        vix_df = store.load("^VIX", tz="US/Eastern")
        if vix_df is not None and not vix_df.empty:
            vix_val = float(vix_df["close"].iloc[-1])
    except Exception:
        pass

    regime_cfg = settings.get("regime", {})
    regime_classifier = MarketRegimeClassifier(
        vix_ticker=regime_cfg.get("vix_ticker", "^VIX"),
        market_proxy=regime_cfg.get("market_proxy", "SPY"),
        low_vol_threshold=regime_cfg.get("low_vol_threshold", 16.0),
        high_vol_threshold=regime_cfg.get("high_vol_threshold", 25.0),
        crisis_vol_threshold=regime_cfg.get("crisis_vol_threshold", 35.0),
    )
    spy_df = price_data.get("SPY", pd.DataFrame())
    regime_info = regime_classifier.classify(spy_df, vix_val)
    regime_state = regime_info["state"]
    size_multiplier = regime_info["size_multiplier"]
    allowed_actions = regime_info["allowed_actions"]

    logger.info(f"Current Market Regime: {regime_state.name} (Multiplier: {size_multiplier:.2f}, Allowed Actions: {allowed_actions})")

    # RISK_OFF emergency action: Liquidation
    if regime_state.name == "RISK_OFF":
        logger.critical("RISK-OFF regime! Flattening all positions and halting new trades.")
        for pos in current_positions:
            sym = pos.get("symbol")
            qty = int(pos.get("quantity") or pos.get("qty") or 0)
            if qty > 0:
                logger.warning(f"RISK_OFF: Liquidating position in {sym}")
                oms.place_trade(symbol=sym, side="SELL", qty=qty)
            elif qty < 0:
                logger.warning(f"RISK_OFF: Covering short position in {sym}")
                oms.place_trade(symbol=sym, side="BUY", qty=abs(qty))
        send_telegram_alert("⚠️ **H.A.T.S RISK-OFF ACTIVATED**: Halted all trading and flattened positions.")
        return

    # 4C. Instantiate Active Strategies
    active_names = settings.get("active_strategies", ["SectorMomentum", "OptionsIVRunup", "BreadthThrustReversion", "MACDHistogram", "DonchianBreakout", "StochasticOscillator", "ZScoreReversion", "LinearRegressionChannel", "PairsTrading"])
    strategies = []
    for name in active_names:
        if name == "SectorMomentum":
            strategies.append(SectorMomentumStrategy("SectorMomentum", config={"check_look_ahead": False}))
        elif name == "OptionsIVRunup":
            strategies.append(OptionsIVRunupStrategy("OptionsIVRunup", config={"check_look_ahead": False}))
        elif name == "BreadthThrustReversion":
            strategies.append(BreadthThrustReversionStrategy("BreadthThrustReversion", config={"check_look_ahead": False}))
        elif name == "MACDHistogram":
            strategies.append(MACDHistogramStrategy("MACDHistogram", config={"check_look_ahead": False}))
        elif name == "DonchianBreakout":
            strategies.append(DonchianChannelBreakoutStrategy("DonchianBreakout", config={"check_look_ahead": False}))
        elif name == "StochasticOscillator":
            strategies.append(StochasticOscillatorStrategy("StochasticOscillator", config={"check_look_ahead": False}))
        elif name == "ZScoreReversion":
            strategies.append(ZScoreMeanReversionStrategy("ZScoreReversion", config={"check_look_ahead": False}))
        elif name == "LinearRegressionChannel":
            strategies.append(LinearRegressionChannelStrategy("LinearRegressionChannel", config={"check_look_ahead": False}))
        elif name == "PairsTrading":
            strategies.append(PairsTradingStrategy("PairsTrading", config={"check_look_ahead": False}))

    # Fallback to defaults if none defined
    if not strategies:
        strategies = [
            SectorMomentumStrategy("SectorMomentum", config={"check_look_ahead": False}),
            OptionsIVRunupStrategy("OptionsIVRunup", config={"check_look_ahead": False}),
            BreadthThrustReversionStrategy("BreadthThrustReversion", config={"check_look_ahead": False}),
            MACDHistogramStrategy("MACDHistogram", config={"check_look_ahead": False}),
            DonchianChannelBreakoutStrategy("DonchianBreakout", config={"check_look_ahead": False}),
            StochasticOscillatorStrategy("StochasticOscillator", config={"check_look_ahead": False}),
            ZScoreMeanReversionStrategy("ZScoreReversion", config={"check_look_ahead": False}),
            LinearRegressionChannelStrategy("LinearRegressionChannel", config={"check_look_ahead": False}),
            PairsTradingStrategy("PairsTrading", config={"check_look_ahead": False}),
        ]
    sizer = PositionSizer()

    # 5. Evaluate Signals (Concurrently)
    signals_to_execute = []

    def evaluate_symbol_signals(sym: str) -> list[dict[str, Any]]:
        sym_signals = []
        try:
            # Skip VIX and inverse ETFs from strategy rule evaluation
            if sym == "^VIX" or sym in inverse_map.values():
                return sym_signals

            df = store.load(sym, tz="US/Eastern")
            if df is None or df.empty:
                return sym_signals

            last_close = float(df["close"].iloc[-1])
            last_atr = float(df["atr_14"].iloc[-1]) if "atr_14" in df.columns else 1.0

            for strat in strategies:
                sig_df = strat.generate_signals(df)
                if sig_df.empty or "signal" not in sig_df.columns:
                    continue

                signal = int(sig_df["signal"].iloc[-1])
                if signal != 0:
                    sym_signals.append({
                        "symbol": sym,
                        "strategy": strat,
                        "signal": signal,
                        "last_close": last_close,
                        "last_atr": last_atr,
                        "df": sig_df
                    })
        except Exception as e:
            logger.error(f"Error executing strategy rules for {sym}: {e}")
        return sym_signals

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        results = executor.map(evaluate_symbol_signals, watchlist)
        for res_list in results:
            signals_to_execute.extend(res_list)

    # Available cash tracking buffer
    available_cash = cash_bal

    # 6. Execute Fills Sequentially (Guarantees Thread-Safety on current_positions)
    import uuid
    cycle_id = str(uuid.uuid4())

    for item in signals_to_execute:
        symbol = item["symbol"]
        strat = item["strategy"]
        signal = item["signal"]
        last_close = item["last_close"]
        last_atr = item["last_atr"]
        df = item["df"]

        def log_decision(action: str, passed: bool, reason: str | None = None, stress_pct: float = 0.0) -> None:
            try:
                from src.strategy.indicators_math import calculate_hurst_exponent
                hurst_val = float(calculate_hurst_exponent(df["close"]))
                current_heat = float(heat_tracker.calculate_heat(current_positions, net_equity))
                
                oms.db.save_decision_log({
                    "cycle_id": cycle_id,
                    "symbol": symbol,
                    "regime_hurst": hurst_val,
                    "strategy_signals": {strat.name: signal},
                    "portfolio_equity": float(net_equity),
                    "portfolio_heat": current_heat,
                    "risk_passed": passed,
                    "risk_reason": reason,
                    "tims_stress_pct": stress_pct,
                    "action_taken": action
                })
            except Exception as le:
                logger.error(f"Failed to log decision for {symbol}: {le}")

        try:
            logger.info(f"Strategy {strat.name} generated {signal} signal for {symbol} at price {last_close:.2f}")

            # Send Telegram alert for the strategy signal generated (market entry tip)
            try:
                from src.strategy.indicators_math import calculate_hurst_exponent
                hurst_val = float(calculate_hurst_exponent(df["close"]))
            except Exception:
                hurst_val = 0.5
                
            action_text = "BUY 🟢" if signal == 1 else "SELL 🔴"
            send_telegram_alert(
                f"🎯 **H.A.T.S Strategy Signal (Market Entry Tip)**:\n"
                f"• **Symbol**: {symbol}\n"
                f"• **Strategy**: {strat.name}\n"
                f"• **Action**: {action_text}\n"
                f"• **Signal Price**: ${last_close:.2f}\n"
                f"• **Hurst Exponent**: {hurst_val:.3f}"
            )

            # Check action side allowed by current regime
            action_side = "BUY" if signal == 1 else "SELL"
            
            # Map SELL signal to BUY inverse ETF in bear regime
            trade_symbol = symbol
            if signal == -1 and "INVERSE" in allowed_actions:
                # If we hold a long position in this symbol, exit it first
                held_long = next((pos for pos in current_positions if pos.get("symbol") == symbol), None)
                if held_long:
                    # Let the normal sell flow handle it
                    pass
                else:
                    # Map to inverse ETF buy
                    inverse_symbol = inverse_map.get(symbol)
                    if inverse_symbol:
                        trade_symbol = inverse_symbol
                        signal = 1
                        logger.info(f"Bearish regime: Mapping sell/short for {symbol} to BUY inverse ETF {trade_symbol}")

            # If BUY signal, close any held inverse ETF first
            if signal == 1:
                inverse_symbol = inverse_map.get(symbol)
                if inverse_symbol:
                    held_inverse = next((pos for pos in current_positions if pos.get("symbol") == inverse_symbol), None)
                    if held_inverse:
                        qty = int(held_inverse.get("quantity") or held_inverse.get("qty") or 0)
                        if qty > 0:
                            logger.info(f"BUY signal for {symbol}: Closing inverse ETF position in {inverse_symbol}.")
                            oms.place_trade(symbol=inverse_symbol, side="SELL", qty=qty)
                            current_positions = [pos for pos in current_positions if pos.get("symbol") != inverse_symbol]

            # Determine if we already hold a position in this symbol
            if use_options:
                held_position = next((pos for pos in current_positions if pos.get("symbol", "").startswith(trade_symbol)), None)
            else:
                held_position = next((pos for pos in current_positions if pos.get("symbol") == trade_symbol), None)

            if signal == 1:  # BUY
                if held_position:
                    logger.debug(f"Buy signal ignored for {trade_symbol}: Position already held.")
                    log_decision("REJECTED_ALREADY_HELD", False, "Position already held")
                    continue

                # Skip if there's already a pending/open order for this symbol on the broker
                if trade_symbol in pending_order_symbols:
                    logger.info(f"Buy signal ignored for {trade_symbol}: Open order already pending on broker.")
                    log_decision("REJECTED_ALREADY_HELD", False, "Pending order already exists on broker")
                    continue

                # Check portfolio limits
                sector = resolver.resolve(trade_symbol)
                if not sizer.check_portfolio_limits(current_positions, sector, account_equity=net_equity):
                    logger.warning(f"Buy signal for {trade_symbol} rejected by portfolio limits.")
                    log_decision("REJECTED_PORTFOLIO_LIMITS", False, "Portfolio limits (max positions or sector cap) exceeded")
                    continue

                # Check correlation limit
                correlation_threshold = risk_settings.get("portfolio", {}).get("correlation_threshold", 0.70)
                max_correlated = risk_settings.get("portfolio", {}).get("max_correlated_positions", 3)
                if not sizer.check_correlation(trade_symbol, current_positions, price_data, correlation_threshold, max_correlated):
                    logger.warning(f"Buy signal for {trade_symbol} rejected by correlation limits.")
                    log_decision("REJECTED_CORRELATION_LIMIT", False, "Correlation limit exceeded")
                    continue

                # Apply sizing multiplier based on regime
                sizing_equity = net_equity * size_multiplier

                if use_options:
                    from src.strategy.option_selector import select_option
                    opt_contract = select_option(trade_symbol, "BUY", last_close)
                    if not opt_contract:
                        logger.warning(f"Could not resolve option contract for {trade_symbol}. Skipping trade.")
                        log_decision("REJECTED_OPTION_MISSING", False, "Could not resolve ATM option contracts")
                        continue
                    
                    option_symbol = opt_contract["contract_symbol"]
                    option_premium = opt_contract["last_price"]
                    opt_stop_price = option_premium * 0.5
                    
                    # Calculate option Delta using Black-Scholes model
                    from src.strategy.black_scholes import parse_option_symbol, calculate_option_price_and_delta
                    try:
                        returns = df["close"].pct_change().dropna()
                        sigma = float(returns.tail(30).std() * math.sqrt(252.0))
                        if pd.isna(sigma) or sigma <= 0.0:
                            sigma = 0.3
                    except Exception:
                        sigma = 0.3

                    und, opt_type, strike, T = parse_option_symbol(option_symbol)
                    _, delta = calculate_option_price_and_delta(
                        S=last_close,
                        K=strike,
                        T=T,
                        r=0.05,
                        sigma=sigma,
                        option_type=opt_type
                    )
                    
                    sizing = sizer.calculate_size(
                        account_equity=sizing_equity,
                        entry_price=option_premium,
                        stop_price=opt_stop_price,
                        slippage_bps=5.0,
                        is_option=True,
                        delta=delta
                    )
                    contracts = sizing.get("shares", 0)
                    
                    # Cap by available cash
                    max_contracts = int(available_cash / (option_premium * 100.0))
                    contracts = min(contracts, max_contracts)

                    if contracts <= 0:
                        logger.warning(f"Option contract sizer returned 0 contracts for {option_symbol}. Skipping.")
                        log_decision("REJECTED_ZERO_SIZE", False, "Sizer returned 0 contracts")
                        continue
                        
                    # Check Portfolio Heat Limit
                    new_trade_risk_pct = sizing.get("risk_pct", 0.0) * (contracts / max(1, sizing.get("shares", 1)))
                    current_heat = heat_tracker.calculate_heat(current_positions, net_equity)
                    if not heat_tracker.can_add_trade(new_trade_risk_pct, current_heat):
                        logger.warning(f"Option order for {option_symbol} rejected by portfolio heat limits.")
                        log_decision("REJECTED_HEAT_LIMIT", False, f"Portfolio heat exceeds limit (trade risk: {new_trade_risk_pct:.2%})")
                        continue

                    # Calculate TIMS stress margin before ordering
                    from src.risk.margin import PortfolioMarginSimulator
                    temp_pos = current_positions + [{"symbol": option_symbol, "quantity": contracts, "avg_price": option_premium}]
                    sim = PortfolioMarginSimulator()
                    stress_res = sim.stress_test(temp_pos, net_equity)
                    stress_pct = stress_res["worst_case_pct"]

                    if not stress_res["passed"]:
                        logger.warning(
                            f"Option order for {option_symbol} rejected by TIMS stress limits. "
                            f"Projected worst-case loss: {stress_pct:.2%}, Limit: {sim.max_stress_loss_pct:.2%}"
                        )
                        log_decision("REJECTED_MARGIN_STRESS", False, "Worst-case stress loss exceeds limit", stress_pct)
                        continue

                    logger.info(f"Enqueuing option order: BUY {contracts} contracts of {option_symbol} (Premium: {option_premium:.2f}, Stop: {opt_stop_price:.2f}, Delta: {delta:.4f})")
                    oms.place_trade(
                        symbol=option_symbol,
                        side="BUY",
                        qty=contracts,
                        price=option_premium,
                        stop_price=opt_stop_price,
                    )
                    available_cash -= contracts * option_premium * 100.0
                    current_positions.append({"symbol": option_symbol, "quantity": contracts, "avg_price": option_premium, "stop_price": opt_stop_price})
                    log_decision("BUY_ORDER_PLACED", True, None, stress_pct)
                else:
                    stop_price = strat.get_initial_stop_price(df, len(df) - 1, last_close)
                    sizing = sizer.calculate_size(sizing_equity, last_close, stop_price, last_atr, slippage_bps=5.0)
                    shares = sizing.get("shares", 0)
                    
                    # Cap by available cash
                    max_shares = int(available_cash / last_close)
                    shares = min(shares, max_shares)

                    if shares <= 0:
                        logger.warning(f"Size calculation for {trade_symbol} returned 0 shares. Risk rules check failed.")
                        log_decision("REJECTED_ZERO_SIZE", False, "Sizer returned 0 shares")
                        continue

                    # Check Portfolio Heat Limit
                    new_trade_risk_pct = sizing.get("risk_pct", 0.0) * (shares / max(1, sizing.get("shares", 1)))
                    current_heat = heat_tracker.calculate_heat(current_positions, net_equity)
                    if not heat_tracker.can_add_trade(new_trade_risk_pct, current_heat):
                        logger.warning(f"Trade order for {trade_symbol} rejected by portfolio heat limits.")
                        log_decision("REJECTED_HEAT_LIMIT", False, f"Portfolio heat exceeds limit (trade risk: {new_trade_risk_pct:.2%})")
                        continue

                    # Calculate TIMS stress margin before ordering
                    from src.risk.margin import PortfolioMarginSimulator
                    temp_pos = current_positions + [{"symbol": trade_symbol, "quantity": shares, "avg_price": last_close}]
                    sim = PortfolioMarginSimulator()
                    stress_res = sim.stress_test(temp_pos, net_equity)
                    stress_pct = stress_res["worst_case_pct"]

                    if not stress_res["passed"]:
                        logger.warning(
                            f"Trade order for {trade_symbol} rejected by TIMS stress limits. "
                            f"Projected worst-case loss: {stress_pct:.2%}, Limit: {sim.max_stress_loss_pct:.2%}"
                        )
                        log_decision("REJECTED_MARGIN_STRESS", False, "Worst-case stress loss exceeds limit", stress_pct)
                        continue

                    logger.info(f"Enqueuing trade order: BUY {shares} shares of {trade_symbol} (Limit: {last_close:.2f}, Stop: {stop_price:.2f})")
                    oms.place_trade(
                        symbol=trade_symbol,
                        side="BUY",
                        qty=shares,
                        price=last_close,
                        stop_price=stop_price,
                    )
                    available_cash -= shares * last_close
                    current_positions.append({"symbol": trade_symbol, "quantity": shares, "avg_price": last_close, "stop_price": stop_price})
                    log_decision("BUY_ORDER_PLACED", True, None, stress_pct)

            elif signal == -1:  # SELL
                if not held_position:
                    logger.debug(f"Sell signal ignored for {trade_symbol}: No position held.")
                    log_decision("REJECTED_NO_POSITION", False, "No position held to sell")
                    continue

                qty = int(held_position.get("quantity") or held_position.get("qty") or 0)
                if qty <= 0:
                    continue

                held_symbol = held_position.get("symbol")
                exit_price = None if use_options else last_close
                logger.info(f"Enqueuing trade order: SELL {qty} shares/contracts of {held_symbol}")
                oms.place_trade(
                    symbol=held_symbol,
                    side="SELL",
                    qty=qty,
                    price=exit_price,
                )
                available_cash += qty * (exit_price if exit_price else held_position.get("avg_price", 0.0))
                current_positions = [pos for pos in current_positions if pos.get("symbol") != held_symbol]
                log_decision("SELL_ORDER_PLACED", True, None)
        except Exception as e:
            logger.error(f"Error executing strategy order generation for {symbol}: {e}", exc_info=True)

    # 5B. Write engine status to persistent file for dashboard alignment
    try:
        status_file = Path("data/execution/engine_status.json")
        status_file.parent.mkdir(parents=True, exist_ok=True)
        status_data = {
            "regime_state": regime_state.name,
            "size_multiplier": size_multiplier,
            "allowed_actions": allowed_actions,
            "circuit_breaker": {
                "halted": cb.state["halted"],
                "reason": cb.state["halt_reason"],
                "trades_today": trades_today,
                "max_trades": cb.max_trades_per_day
            },
            "portfolio_heat": float(heat_tracker.calculate_heat(current_positions, net_equity)),
            "updated_at": dt.datetime.now().isoformat()
        }
        with open(status_file, "w") as sf:
            json.dump(status_data, sf, indent=4)
        logger.info(f"Engine status successfully saved to {status_file}.")
    except Exception as ese:
        logger.error(f"Failed to write engine status file: {ese}")

    # 6. Reconcile working orders
    logger.info("Synchronizing active order states with Alpaca...")
    oms.sync_orders()
    msg = f"✅ H.A.T.S Systematic trading cycle ({interval}) completed successfully."
    logger.info(msg)
    send_telegram_alert(msg)

    # 7. Check if Friday EOD to compile the weekly report
    try:
        if dt.datetime.now().weekday() == 4: # Friday
            logger.info("Friday EOD detected. Compiling weekly operational report...")
            from src.dashboard.report_generator import WeeklyReportGenerator
            generator = WeeklyReportGenerator(db_manager=oms.db)
            report_md, _ = generator.generate_weekly_report()
            generator.send_report_summary(report_md)
    except Exception as wre:
        logger.error(f"Failed to generate weekly report: {wre}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Run H.A.T.S Systematic Trading Cycle.")
    parser.add_argument("--interval", "-i", type=str, default="1d", help="Candle interval timeframe (e.g. 1d, 1h, 15m).")
    parser.add_argument("--options", "-o", action="store_true", help="Enable equity options trading mode instead of stocks.")
    parser.add_argument("--force", "-f", action="store_true", help="Force cycle execution during off-market hours.")
    parser.add_argument("--report", "-r", action="store_true", help="Compile and transmit the weekly performance report manually.")
    parser.add_argument("--listener", "-l", action="store_true", help="Start the interactive Telegram Bot listener daemon.")
    args = parser.parse_args()

    # Setup standard console logging if run directly
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    
    if args.report:
        try:
            logger.info("Manual weekly report trigger initiated...")
            from src.dashboard.report_generator import WeeklyReportGenerator
            generator = WeeklyReportGenerator()
            report_md, report_file = generator.generate_weekly_report()
            generator.send_report_summary(report_md)
            logger.info(f"Weekly report compilation complete. Saved to: {report_file}")
            sys.exit(0)
        except Exception as e:
            logger.critical(f"Failed to generate manual weekly report: {e}", exc_info=True)
            sys.exit(1)

    if args.listener:
        try:
            logger.info("Starting H.A.T.S Telegram listener daemon...")
            from src.dashboard.telegram_listener import TelegramListener
            listener = TelegramListener()
            listener.start_polling()
        except Exception as e:
            logger.critical(f"Telegram listener crashed: {e}", exc_info=True)
            sys.exit(1)

    try:
        run_trading_cycle(interval=args.interval, use_options=args.options, force_run=args.force)
    except Exception as e:
        logger.critical(f"Unhandled systematic trading engine crash: {e}", exc_info=True)
        send_telegram_alert(f"⚠️ **H.A.T.S CRITICAL ERROR**: Trading engine crashed with error:\n`{e}`")
        sys.exit(1)
