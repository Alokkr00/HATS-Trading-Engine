// Global chart instances
let allocationChart = null;
let equityChart = null;

// Helper to format currency
function formatCurrency(value) {
    return new Intl.NumberFormat('en-US', {
        style: 'currency',
        currency: 'USD'
    }).format(value);
}

// Helper to format date
function formatDate(isoString) {
    if (!isoString) return '';
    try {
        const date = new Date(isoString);
        return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    } catch (e) {
        return isoString;
    }
}

// Helper to safely set innerHTML only when changed
function safeSetInnerHTML(elementId, newHtml) {
    const el = document.getElementById(elementId);
    if (el && el.innerHTML !== newHtml) {
        el.innerHTML = newHtml;
    }
}

// Helper to safely set textContent only when changed
function safeSetTextContent(elementId, newText) {
    const el = document.getElementById(elementId);
    if (el && el.textContent !== newText) {
        el.textContent = newText;
    }
}

// Update the KPI metrics
function updateKPIs(state) {
    const portfolio = state.portfolio || {};
    const cash = portfolio.cash || {};
    
    const netLiq = cash.net_liquidity || 100000.0;
    const cashBal = cash.cash_balance || 100000.0;
    
    const positions = portfolio.positions || {};
    const numPositions = Object.keys(positions).length;
    
    const orders = state.orders || {};
    const activeOrders = Object.values(orders).filter(
        o => ["PENDING_SUBMIT", "SUBMITTED", "PARTIALLY_FILLED"].includes(o.status)
    ).length;

    safeSetTextContent("val-net-liquidity", formatCurrency(netLiq));
    safeSetTextContent("val-cash-balance", formatCurrency(cashBal));
    safeSetTextContent("val-open-positions", numPositions);
    safeSetTextContent("val-pending-orders", activeOrders);
    safeSetTextContent("positions-count-badge", `${numPositions} Active`);

    // Update Engine Status (Regime, Heat, CB)
    const engine = state.engine_status || {};
    
    // 1. Regime state
    const regimeBadge = document.getElementById("regime-badge-val");
    if (regimeBadge) {
        const regimeStr = engine.regime_state || "UNKNOWN";
        regimeBadge.textContent = regimeStr;
        if (regimeStr === "RISK_OFF") {
            regimeBadge.style.color = "var(--color-danger)";
        } else if (regimeStr.startsWith("BEAR")) {
            regimeBadge.style.color = "var(--color-warning)";
        } else if (regimeStr.startsWith("BULL")) {
            regimeBadge.style.color = "var(--color-success)";
        } else {
            regimeBadge.style.color = "var(--accent-glow)";
        }
    }

    // 2. Risk Heat
    const heatBadge = document.getElementById("heat-badge-val");
    if (heatBadge) {
        const heatVal = engine.portfolio_heat !== undefined ? (engine.portfolio_heat * 100).toFixed(2) : "0.00";
        heatBadge.textContent = `${heatVal}% / 6.00%`;
        if (parseFloat(heatVal) >= 5.0) {
            heatBadge.style.color = "var(--color-danger)";
        } else if (parseFloat(heatVal) >= 3.0) {
            heatBadge.style.color = "var(--color-warning)";
        } else {
            heatBadge.style.color = "#ffffff";
        }
    }

    // 3. Circuit Breakers
    const cbBadge = document.getElementById("cb-badge-val");
    if (cbBadge) {
        const cb = engine.circuit_breaker || {};
        if (cb.halted) {
            cbBadge.textContent = "HALTED";
            cbBadge.style.color = "var(--color-danger)";
            cbBadge.title = cb.reason || "Circuit Breaker Active";
        } else {
            cbBadge.textContent = "CLEAR";
            cbBadge.style.color = "var(--color-success)";
            cbBadge.title = `Trades: ${cb.trades_today || 0} / ${cb.max_trades || 20}`;
        }
    }
}

// Update the portfolio positions table
function updatePositions(state) {
    const portfolio = state.portfolio || {};
    const positions = portfolio.positions || {};
    
    const posList = Object.values(positions);
    
    if (posList.length === 0) {
        safeSetInnerHTML("positions-tbody", `
            <tr>
                <td colspan="7" class="empty-state">No open positions. Ready for strategy triggers.</td>
            </tr>
        `);
        return;
    }
    
    const cash = portfolio.cash || {};
    const netLiq = cash.net_liquidity || 100000.0;

    const newHtml = posList.map(pos => {
        const symbol = pos.symbol || "UNKNOWN";
        const qty = parseFloat(pos.quantity || pos.qty || 0);
        const costPrice = parseFloat(pos.cost_price || pos.cost_basis || 0);
        const currentPrice = parseFloat(pos.current_price || costPrice);
        const marketValue = parseFloat(pos.market_value || (qty * currentPrice) || 0);
        const unrealizedPnl = parseFloat(pos.unrealized_pnl || 0.0);
        const unrealizedPnlPct = parseFloat(pos.unrealized_pnl_pct || 0.0);
        
        const allocation = netLiq > 0 ? ((marketValue / netLiq) * 100).toFixed(1) : "0.0";
        
        const pnlClass = unrealizedPnl >= 0 ? "pnl-positive" : "pnl-negative";
        const pnlSign = unrealizedPnl >= 0 ? "+" : "";
        const pnlText = `${pnlSign}${formatCurrency(unrealizedPnl)} (${pnlSign}${unrealizedPnlPct.toFixed(2)}%)`;
        
        return `
            <tr>
                <td class="tx-symbol">${symbol}</td>
                <td>${qty}</td>
                <td>${formatCurrency(costPrice)}</td>
                <td>${formatCurrency(currentPrice)}</td>
                <td>${formatCurrency(marketValue)}</td>
                <td class="${pnlClass}">${pnlText}</td>
                <td><span class="badge badge-info">${allocation}%</span></td>
            </tr>
        `;
    }).join("");
    
    safeSetInnerHTML("positions-tbody", newHtml);
}

// Update working orders table
function updateOrders(state) {
    const orders = state.orders || {};
    
    const activeOrders = Object.values(orders).filter(
        o => ["PENDING_SUBMIT", "SUBMITTED", "PARTIALLY_FILLED"].includes(o.status)
    );
    
    if (activeOrders.length === 0) {
        safeSetInnerHTML("orders-tbody", `
            <tr>
                <td colspan="6" class="empty-state">No active working orders.</td>
            </tr>
        `);
        return;
    }
    
    const newHtml = activeOrders.map(order => {
        const clientOrderId = order.client_order_id || "N/A";
        const symbol = order.symbol || "UNKNOWN";
        const side = order.side || "BUY";
        const sideClass = side === "BUY" ? "tx-side-buy" : "tx-side-sell";
        const qty = order.qty || 0;
        const price = order.price ? formatCurrency(order.price) : "MARKET";
        const status = order.status || "PENDING";
        
        return `
            <tr>
                <td class="text-muted" style="font-size:0.75rem;">${clientOrderId.substring(0, 15)}...</td>
                <td class="tx-symbol">${symbol}</td>
                <td><span class="${sideClass}">${side}</span></td>
                <td>${qty}</td>
                <td>${price}</td>
                <td><span class="badge badge-paper">${status}</span></td>
            </tr>
        `;
    }).join("");

    safeSetInnerHTML("orders-tbody", newHtml);
}

// Update the Strategy signals watchlist
function updateSignals(signals) {
    if (!signals || signals.length === 0) {
        safeSetInnerHTML("watchlist-tbody", `
            <tr>
                <td colspan="8" class="empty-state">No watchlist symbols configured.</td>
            </tr>
        `);
        return;
    }

    const getSignalHtml = (val) => {
        if (val === 1) return `<span class="signal-buy">BUY</span>`;
        if (val === -1) return `<span class="signal-sell">SELL</span>`;
        return `<span class="signal-hold">HOLD</span>`;
    };

    const newHtml = signals.map(sig => {
        const symbol = sig.symbol;
        const price = sig.close_price > 0 ? formatCurrency(sig.close_price) : "Loading...";
        return `
            <tr>
                <td class="tx-symbol">${symbol}</td>
                <td style="font-weight:500;">${price}</td>
                <td>${getSignalHtml(sig.MACrossover)}</td>
                <td>${getSignalHtml(sig.RSIMeanReversion)}</td>
                <td>${getSignalHtml(sig.BollingerSqueeze)}</td>
                <td>${getSignalHtml(sig.SectorMomentum)}</td>
                <td>${getSignalHtml(sig.OptionsIVRunup)}</td>
                <td>${getSignalHtml(sig.BreadthThrustReversion)}</td>
            </tr>
        `;
    }).join("");

    safeSetInnerHTML("watchlist-tbody", newHtml);
}

// Dictionary mapping common symbols to their friendly names
const SYMBOL_NAMES = {
    "AAPL": "Apple Inc.",
    "MSFT": "Microsoft Corp.",
    "SPY": "S&P 500 ETF",
    "QQQ": "Nasdaq 100 ETF",
    "TSLA": "Tesla Inc.",
    "GOOGL": "Alphabet Inc.",
    "AMZN": "Amazon Inc.",
    "NVDA": "NVIDIA Corp.",
    "META": "Meta Platforms",
    "JPM": "JPMorgan Chase",
    "PLTR": "Palantir Tech",
    "XLK": "Tech Sector ETF",
    "XLF": "Financials ETF",
    "XLV": "Healthcare ETF",
    "XLY": "Consumer Discr ETF",
    "XLP": "Staples ETF",
    "XLI": "Industrials ETF",
    "XLB": "Materials ETF",
    "XLE": "Energy ETF",
    "XLRE": "Real Estate ETF",
    "XLU": "Utilities ETF",
    "XLC": "Communications ETF",
    "^VIX": "CBOE VIX Index"
};

// Update the executed transactions list
function updateTransactions(txs) {
    const container = document.getElementById("transactions-list");
    if (!txs || txs.length === 0) {
        container.innerHTML = `<div class="empty-state">No executed trades logged.</div>`;
        return;
    }

    container.innerHTML = txs.map(tx => {
        const symbol = tx.symbol || "UNKNOWN";
        const name = SYMBOL_NAMES[symbol] || "";
        const side = tx.side || "BUY";
        const sideClass = side === "BUY" ? "tx-side-buy" : "tx-side-sell";
        const qty = tx.qty || tx.filled_qty || 0;
        const price = tx.avg_price || tx.price || 0;
        const notional = qty * price;
        const timeStr = formatDate(tx.timestamp);
        
        return `
            <div class="tx-item">
                <div class="tx-left">
                    <div>
                        <span class="tx-symbol">${symbol}</span>
                        ${name ? `<span class="text-secondary" style="font-size: var(--font-xs); margin-left: var(--space-xs); opacity: 0.85;">— ${name}</span>` : ''}
                        <span class="${sideClass}" style="margin-left:0.5rem; font-weight:600;">${side}</span>
                    </div>
                    <span class="tx-date">${timeStr}</span>
                </div>
                <div class="tx-right">
                    <span style="font-weight:600;">${qty} @ ${formatCurrency(price)}</span>
                    <span class="text-muted" style="font-size:0.75rem;">Total: ${formatCurrency(notional)}</span>
                </div>
            </div>
        `;
    }).join("");
}

// Update the systematic decision logs table
function updateDecisions(logs) {
    const tbody = document.getElementById("decisions-tbody");
    const countBadge = document.getElementById("decisions-count-badge");
    
    if (!logs || logs.length === 0) {
        tbody.innerHTML = `<tr><td colspan="10" class="empty-state">No decisions logged.</td></tr>`;
        if (countBadge) countBadge.textContent = "0 Logs";
        return;
    }
    
    if (countBadge) {
        countBadge.textContent = `${logs.length} Logs`;
    }

    tbody.innerHTML = logs.map(log => {
        const timeStr = formatDate(log.timestamp);
        const cycleId = log.cycle_id ? log.cycle_id.substring(0, 8) + "..." : "—";
        const symbol = log.symbol || "—";
        const hurst = typeof log.regime_hurst === 'number' ? log.regime_hurst.toFixed(3) : "—";
        
        // Strategy signals formatting
        let sigs = "—";
        if (log.strategy_signals && typeof log.strategy_signals === 'object') {
            sigs = Object.entries(log.strategy_signals)
                .map(([k, v]) => `${k}: ${v > 0 ? '+' + v : v}`)
                .join(", ");
        }
        
        const equity = formatCurrency(log.portfolio_equity || 0);
        const heat = typeof log.portfolio_heat === 'number' ? (log.portfolio_heat * 100).toFixed(2) + "%" : "0.00%";
        const stress = typeof log.tims_stress_pct === 'number' ? (log.tims_stress_pct * 100).toFixed(2) + "%" : "0.00%";
        
        const riskPassed = log.risk_passed 
            ? `<span class="badge badge-success">PASSED</span>` 
            : `<span class="badge badge-danger" title="${log.risk_reason || ''}">FAILED</span>`;
            
        const action = log.action_taken || "NO_ACTION";
        let actionClass = "text-muted";
        if (action.includes("PLACED")) actionClass = "text-success font-weight-bold";
        if (action.includes("REJECTED")) actionClass = "text-danger";

        return `
            <tr>
                <td>${timeStr}</td>
                <td title="${log.cycle_id || ''}">${cycleId}</td>
                <td><span class="tx-symbol">${symbol}</span></td>
                <td>${hurst}</td>
                <td><code style="font-size:0.75rem;">${sigs}</code></td>
                <td>${equity}</td>
                <td>${heat}</td>
                <td class="${log.tims_stress_pct > 0.15 ? 'text-danger' : ''}">${stress}</td>
                <td>${riskPassed}</td>
                <td class="${actionClass}">${action}</td>
            </tr>
        `;
    }).join("");
}

// Update asset allocation chart
function updateAllocationChart(state) {
    const portfolio = state.portfolio || {};
    const positions = portfolio.positions || {};
    const cash = portfolio.cash || {};
    const cashBal = parseFloat(cash.cash_balance || 100000.0);
    
    const labels = ["Cash"];
    const series = [cashBal];
    
    Object.values(positions).forEach(pos => {
        const symbol = pos.symbol;
        const qty = parseFloat(pos.quantity || pos.qty || 0);
        const costPrice = parseFloat(pos.cost_price || pos.cost_basis || 0);
        const marketValue = parseFloat(pos.market_value || (qty * costPrice) || 0);
        
        labels.push(symbol);
        series.push(marketValue);
    });

    const options = {
        series: series,
        labels: labels,
        chart: {
            type: 'donut',
            height: 250,
            foreColor: '#94a3b8',
            fontFamily: 'Inter, sans-serif'
        },
        theme: { monochrome: { enabled: false } },
        colors: ["#334155", "#8b5cf6", "#10b981", "#ef4444", "#3b82f6", "#f59e0b"], // Premium desaturated palette
        plotOptions: {
            pie: {
                donut: {
                    size: '72%',
                    labels: {
                        show: true,
                        name: { show: true, fontSize: '12px', fontWeight: 600 },
                        value: {
                            show: true,
                            fontSize: '14px',
                            fontWeight: 700,
                            formatter: (val) => '$' + parseFloat(val).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})
                        },
                        total: {
                            show: true,
                            label: 'Net Liquidity',
                            fontSize: '11px',
                            fontWeight: 600,
                            formatter: (w) => {
                                const total = w.globals.seriesTotals.reduce((a, b) => a + b, 0);
                                return '$' + total.toLocaleString(undefined, {maximumFractionDigits: 0});
                            }
                        }
                    }
                }
            }
        },
        stroke: {
            show: true,
            colors: ['rgba(255, 255, 255, 0.08)'],
            width: 1
        },
        dataLabels: { enabled: false },
        legend: { show: false }
    };

    const container = document.querySelector("#allocation-pie-chart");
    if (!container) return;
    container.innerHTML = "";
    allocationChart = new ApexCharts(container, options);
    allocationChart.render();
}

// Update the historical performance chart and stats panel
function updatePerformanceChart(dates, equity, stats) {
    document.getElementById("stat-sharpe").textContent = parseFloat(stats.sharpe_ratio || 0.0).toFixed(2);
    document.getElementById("stat-win-rate").textContent = `${parseFloat(stats.win_rate || 0.0).toFixed(1)}%`;
    document.getElementById("stat-profit-factor").textContent = parseFloat(stats.profit_factor || 0.0).toFixed(2);
    
    const maxDd = parseFloat(stats.max_drawdown || 0.0);
    document.getElementById("stat-drawdown").textContent = `-${maxDd.toFixed(2)}%`;

    const options = {
        series: [{
            name: 'Net Liquidity',
            data: equity
        }],
        chart: {
            type: 'area',
            height: 250,
            zoom: { enabled: true },
            toolbar: { show: false },
            foreColor: '#64748b',
            fontFamily: 'Inter, sans-serif'
        },
        colors: ['#8b5cf6'],
        fill: {
            type: 'gradient',
            gradient: {
                shadeIntensity: 0.5,
                opacityFrom: 0.12,
                opacityTo: 0.01,
                stops: [0, 95, 100]
            }
        },
        dataLabels: { enabled: false },
        stroke: { curve: 'smooth', width: 1.5 },
        xaxis: {
            categories: dates,
            labels: { show: true, hideOverlappingLabels: true, maxTicksLimit: 6 },
            axisBorder: { show: false },
            axisTicks: { show: false }
        },
        yaxis: {
            labels: {
                formatter: (val) => '$' + (val / 1000).toFixed(0) + 'k'
            }
        },
        grid: {
            borderColor: 'rgba(255, 255, 255, 0.04)',
            strokeDashArray: 4
        },
        tooltip: {
            theme: 'dark',
            x: { format: 'dd MMM yyyy' },
            y: {
                formatter: (val) => '$' + val.toLocaleString(undefined, {minimumFractionDigits: 2})
            }
        }
    };

    const container = document.querySelector("#equity-line-chart");
    if (!container) return;
    container.innerHTML = "";
    equityChart = new ApexCharts(container, options);
    equityChart.render();
}

// Parse raw log entries into clean color-coded HTML tokens
function formatLogLine(line) {
    if (!line || typeof line !== 'string') return '';
    
    // Split log lines formatted like: "YYYY-MM-DD HH:MM:SS | module | LEVEL | Message"
    const parts = line.split(" | ");
    if (parts.length >= 4) {
        const timestamp = parts[0].trim();
        const module = parts[1].trim();
        const level = parts[2].trim();
        const message = parts.slice(3).join(" | ").trim();
        
        let levelClass = "level-info";
        if (level.includes("WARN")) levelClass = "level-warn";
        else if (level.includes("ERROR") || level.includes("CRITICAL")) levelClass = "level-error";
        else if (level.includes("DEBUG")) levelClass = "level-debug";
        
        return `<div class="log-line">
            <span class="log-time">${timestamp}</span>
            <span class="log-module">${module}</span>
            <span class="log-level ${levelClass}">${level}</span>
            <span class="log-msg">${message}</span>
        </div>`;
    }
    
    // Formatting tracebacks or stack traces
    if (line.includes("Traceback") || line.startsWith("  File ") || line.includes("Error:") || line.startsWith("    ")) {
        return `<div class="log-line log-traceback">${line}</div>`;
    }
    return `<div class="log-line">${line}</div>`;
}

// Update logs console
function updateHealth(health) {
    document.getElementById("health-badge").textContent = health.status || "HEALTHY";
    document.getElementById("env-badge").textContent = health.environment || "Dry Run";
    
    const badge = document.getElementById("env-badge");
    if (health.environment === "Dry Run") {
        badge.className = "badge badge-paper";
    } else {
        badge.className = "badge badge-success";
    }

    const consoleDiv = document.getElementById("logs-console");
    const logs = health.log_entries || [];
    
    if (logs.length === 0) {
        consoleDiv.innerHTML = `<div class="log-line text-muted">No log entries found. System executing cleanly.</div>`;
        return;
    }

    consoleDiv.innerHTML = logs.map(formatLogLine).join("");
    
    // Auto-scroll to bottom of logs
    consoleDiv.scrollTop = consoleDiv.scrollHeight;
}

// Core Sync call to reload all APIs
async function syncAll() {
    console.log("Synchronizing dashboard data streams...");
    const refreshBtn = document.getElementById("refresh-btn");
    if (refreshBtn) {
        refreshBtn.disabled = true;
        refreshBtn.textContent = "Syncing...";
        refreshBtn.style.opacity = "0.6";
    }

    try {
        const [stateRes, txRes, sigRes, healthRes, perfRes, decRes] = await Promise.all([
            fetch("/api/state"),
            fetch("/api/transactions"),
            fetch("/api/signals"),
            fetch("/api/health"),
            fetch("/api/performance"),
            fetch("/api/decisions")
        ]);

        if (stateRes.ok) {
            const state = await stateRes.json();
            updateKPIs(state);
            updatePositions(state);
            updateOrders(state);
            updateAllocationChart(state);

            // Update bot status switch and label dynamically
            const toggle = document.getElementById("bot-toggle");
            const label = document.getElementById("bot-status-label");
            if (toggle && label) {
                toggle.checked = state.bot_active;
                if (state.bot_active) {
                    label.textContent = "ACTIVE";
                    label.className = "bot-status-active";
                } else {
                    label.textContent = "PAUSED";
                    label.className = "bot-status-inactive";
                }
            }
        }
        
        if (txRes.ok) {
            const txs = await txRes.json();
            updateTransactions(txs);
        }
        
        if (sigRes.ok) {
            const signals = await sigRes.json();
            updateSignals(signals);
        }
        
        if (healthRes.ok) {
            const health = await healthRes.json();
            updateHealth(health);
        }

        if (perfRes.ok) {
            const perf = await perfRes.json();
            updatePerformanceChart(perf.dates, perf.equity, perf.stats);
        }

        if (decRes.ok) {
            const decisions = await decRes.json();
            updateDecisions(decisions);
        }
    } catch (e) {
        console.error("Dashboard synchronization error:", e);
    } finally {
        if (refreshBtn) {
            refreshBtn.disabled = false;
            refreshBtn.textContent = "Sync Now";
            refreshBtn.style.opacity = "1";
        }
    }
}

// Check user authorization level on startup and restrict UI if read-only
async function enforceRolePermissions() {
    try {
        const res = await fetch("/api/auth/role");
        if (res.ok) {
            const data = await res.json();
            if (data.role === "readonly") {
                console.warn("🔐 Operational Cockpit initialized in READ-ONLY mode. Disabling execution controls.");
                
                // 1. Disable Bot Toggle
                const toggle = document.getElementById("bot-toggle");
                if (toggle) {
                    toggle.disabled = true;
                    toggle.title = "Action disabled: Admin access required.";
                    const wrapper = toggle.closest(".switch-container");
                    if (wrapper) {
                        wrapper.classList.add("switch-disabled-locked");
                        const statusItem = wrapper.closest(".status-item");
                        if (statusItem && !statusItem.querySelector(".lock-indicator")) {
                            const lockSpan = document.createElement("span");
                            lockSpan.className = "lock-indicator";
                            lockSpan.innerHTML = "🔒";
                            lockSpan.style.marginLeft = "4px";
                            statusItem.appendChild(lockSpan);
                        }
                    }
                }
                
                // 2. Disable Emergency Liquidate button instead of hiding
                const liquidateBtn = document.getElementById("liquidate-btn");
                if (liquidateBtn) {
                    liquidateBtn.disabled = true;
                    liquidateBtn.classList.add("btn-disabled-locked");
                    liquidateBtn.innerHTML = "🔒 Emergency Flat (Locked)";
                    liquidateBtn.title = "Action disabled: Admin access required.";
                }
                
                // 3. Disable Backtesting tab trigger instead of hiding
                const tabBacktest = document.getElementById("tab-backtest");
                if (tabBacktest) {
                    tabBacktest.classList.add("tab-disabled-locked");
                    tabBacktest.innerHTML = "Backtesting Portal 🔒";
                    tabBacktest.title = "Access disabled: Admin access required.";
                    tabBacktest.style.pointerEvents = "none";
                }
            }
        }
    } catch (e) {
        console.error("Failed to fetch user auth role:", e);
    }
}

// Event Listeners on initialization
document.addEventListener("DOMContentLoaded", () => {
    // Check role and disable admin buttons
    enforceRolePermissions();

    // Initial fetch
    syncAll();
    
    // Refresh button event listener
    document.getElementById("refresh-btn").addEventListener("click", () => {
        syncAll();
    });

    // Bot engine status toggle event listener
    const botToggle = document.getElementById("bot-toggle");
    if (botToggle) {
        botToggle.addEventListener("change", async (e) => {
            const active = e.target.checked;
            try {
                const res = await fetch(`/api/action/toggle?active=${active}`, {
                    method: "POST"
                });
                if (res.ok) {
                    const data = await res.json();
                    console.log("Bot engine state updated:", data.message);
                    syncAll();
                } else {
                    console.error("Failed to update bot engine state.");
                    e.target.checked = !active; // revert state on fail
                }
            } catch (err) {
                console.error("Failed to toggle bot engine:", err);
                e.target.checked = !active; // revert state on fail
            }
        });
    }

    // Emergency flat/liquidate button event listener
    const liquidateBtn = document.getElementById("liquidate-btn");
    if (liquidateBtn) {
        liquidateBtn.addEventListener("click", async () => {
            if (confirm("⚠️ WARNING: Are you sure you want to trigger EMERGENCY FLATTEN? This will liquidate all open positions immediately!")) {
                liquidateBtn.disabled = true;
                liquidateBtn.textContent = "Liquidating...";
                try {
                    const res = await fetch("/api/action/liquidate", {
                        method: "POST"
                    });
                    if (res.ok) {
                        const data = await res.json();
                        alert("✅ " + data.message);
                        syncAll();
                    } else {
                        const err = await res.json();
                        alert("❌ Failed to liquidate: " + err.detail);
                    }
                } catch (err) {
                    console.error("Liquidation error:", err);
                    alert("❌ Network error performing liquidation.");
                } finally {
                    liquidateBtn.disabled = false;
                    liquidateBtn.textContent = "Emergency Flat";
                }
            }
        });
    }
    
    // Toast alert builder
    function showToast(title, body, type = "info") {
        const container = document.getElementById("toast-container");
        if (!container) return;
        
        const toast = document.createElement("div");
        toast.className = `toast toast-${type}`;
        
        toast.innerHTML = `
            <div class="toast-header">
                <span>${title}</span>
                <span style="cursor:pointer; opacity: 0.6;" onclick="this.parentElement.parentElement.remove()">×</span>
            </div>
            <div class="toast-body">${body}</div>
        `;
        
        container.appendChild(toast);
        
        setTimeout(() => {
            toast.style.animation = "slideIn 0.3s ease reverse forwards";
            setTimeout(() => toast.remove(), 300);
        }, 6000);
    }

    // Setup live WebSocket stream with ticket validation
    async function setupWebSocket() {
        try {
            const tokenRes = await fetch("/api/auth/token");
            if (!tokenRes.ok) {
                console.error("Failed to fetch WebSocket handshake token. HTTP status:", tokenRes.status);
                const wsBadge = document.getElementById("ws-badge");
                if (wsBadge) {
                    wsBadge.className = "badge pulsing-badge pulsing-red";
                    wsBadge.textContent = "RECONNECTING";
                }
                setTimeout(setupWebSocket, 5000);
                return;
            }
            const tokenData = await tokenRes.json();
            const token = tokenData.token;

            const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
            const wsUrl = `${protocol}//${window.location.host}/ws/live?token=${token}`;
            const socket = new WebSocket(wsUrl);

            socket.onopen = () => {
                console.log("WebSocket connected to H.A.T.S live event stream.");
                const wsBadge = document.getElementById("ws-badge");
                if (wsBadge) {
                    wsBadge.className = "badge pulsing-badge pulsing-green";
                    wsBadge.textContent = "CONNECTED";
                }
            };

            socket.onmessage = (event) => {
                try {
                    const msg = JSON.parse(event.data);
                    console.log("Received live broadcast event:", msg.type);
                    if (["positions_updated", "transaction_logged", "signals_updated", "bot_active_updated"].includes(msg.type)) {
                        syncAll();
                        
                        // Push Toast Alert notifications
                        if (msg.type === "transaction_logged") {
                            const tx = msg.data || {};
                            showToast(
                                `📈 Trade Execution Filled`,
                                `• ${tx.side} ${tx.qty} shares/contracts of ${tx.symbol}<br>• Average Price: $${parseFloat(tx.price).toFixed(2)}`,
                                "success"
                            );
                        } else if (msg.type === "bot_active_updated") {
                            const active = msg.data?.active;
                            showToast(
                                `🤖 Bot State Changed`,
                                `System state is now: ${active ? "ACTIVE" : "PAUSED"}`,
                                active ? "success" : "info"
                            );
                        }
                    }
                } catch (e) {
                    console.error("Error parsing WebSocket event:", e);
                }
            };

            socket.onclose = () => {
                console.warn("WebSocket disconnected. Attempting reconnection in 5 seconds...");
                const wsBadge = document.getElementById("ws-badge");
                if (wsBadge) {
                    wsBadge.className = "badge pulsing-badge pulsing-red";
                    wsBadge.textContent = "RECONNECTING";
                }
                setTimeout(setupWebSocket, 5000);
            };

            socket.onerror = (err) => {
                console.error("WebSocket connection error:", err);
                socket.close();
            };
        } catch (err) {
            console.error("Error in WebSocket setup flow:", err);
            const wsBadge = document.getElementById("ws-badge");
            if (wsBadge) {
                wsBadge.className = "badge pulsing-badge pulsing-red";
                wsBadge.textContent = "RECONNECTING";
            }
            setTimeout(setupWebSocket, 5000);
        }
    }

    // Connect to WebSocket stream
    setupWebSocket();

    // Tabs Navigation setup
    const tabLive = document.getElementById("tab-live");
    const tabBacktest = document.getElementById("tab-backtest");
    const contentLive = document.getElementById("content-live");
    const contentBacktest = document.getElementById("content-backtest");

    if (tabLive && tabBacktest) {
        tabLive.addEventListener("click", () => {
            tabLive.classList.add("active");
            tabBacktest.classList.remove("active");
            contentLive.classList.remove("hidden");
            contentBacktest.classList.add("hidden");
            window.dispatchEvent(new Event('resize'));
        });

        tabBacktest.addEventListener("click", () => {
            tabBacktest.classList.add("active");
            tabLive.classList.remove("active");
            contentBacktest.classList.remove("hidden");
            contentLive.classList.add("hidden");
            window.dispatchEvent(new Event('resize'));
        });
    }

    // Backtest Form submission
    const btForm = document.getElementById("backtest-form");
    let backtestChart = null;

    if (btForm) {
        btForm.addEventListener("submit", async (e) => {
            e.preventDefault();
            
            const runBtn = document.getElementById("run-backtest-btn");
            runBtn.disabled = true;
            runBtn.textContent = "Running Simulation...";
            
            const symbol = document.getElementById("backtest-symbol").value;
            const strategy = document.getElementById("backtest-strategy").value;
            const capital = parseFloat(document.getElementById("backtest-capital").value);
            
            try {
                const res = await fetch("/api/backtest/run", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ symbol, strategy, capital })
                });
                
                if (!res.ok) {
                    const errText = await res.text();
                    showToast("❌ Backtest Failed", `Server returned error: ${errText}`, "danger");
                    return;
                }
                
                const data = await res.json();
                if (data.status === "success") {
                    showToast("📈 Backtest Completed", `Simulation finished for ${symbol} using ${strategy}.`, "success");
                    
                    // Display results wrapper
                    document.getElementById("backtest-results-panel").classList.remove("hidden");
                    
                    // Populate metrics
                    const m = data.metrics;
                    document.getElementById("bt-cagr").textContent = (m.cagr * 100).toFixed(2) + "%";
                    document.getElementById("bt-sharpe").textContent = m.sharpe.toFixed(2);
                    document.getElementById("bt-sortino").textContent = m.sortino.toFixed(2);
                    document.getElementById("bt-drawdown").textContent = (m.max_drawdown * 100).toFixed(2) + "%";
                    document.getElementById("bt-win-rate").textContent = (m.win_rate * 100).toFixed(1) + "%";
                    document.getElementById("bt-profit-factor").textContent = m.profit_factor === "inf" ? "inf" : parseFloat(m.profit_factor).toFixed(2);
                    document.getElementById("bt-total-trades").textContent = m.total_trades;
                    
                    // Render Backtest Equity Chart
                    const dates = data.equity_curve.map(d => d.date);
                    const values = data.equity_curve.map(d => d.value);
                    
                    const chartOpts = {
                        series: [{
                            name: 'Simulated Equity',
                            data: values
                        }],
                        chart: {
                            type: 'area',
                            height: 400,
                            foreColor: '#94a3b8',
                            fontFamily: 'Inter, sans-serif'
                        },
                        colors: ['#a855f7'],
                        fill: {
                            type: 'gradient',
                            gradient: {
                                shadeIntensity: 1,
                                opacityFrom: 0.3,
                                opacityTo: 0.05,
                                stops: [0, 90, 100]
                            }
                        },
                        dataLabels: { enabled: false },
                        markers: { size: 0 },
                        stroke: { curve: 'smooth', width: 2 },
                        xaxis: {
                            categories: dates,
                            labels: {
                                show: true,
                                rotate: -45,
                                rotateAlways: false,
                                hideOverlappingLabels: true,
                                maxTicksLimit: 12,
                                style: { fontSize: '10px' }
                            },
                            axisBorder: { show: false },
                            axisTicks: { show: false }
                        },
                        yaxis: {
                            labels: {
                                formatter: (val) => '$' + val.toLocaleString(undefined, { maximumFractionDigits: 0 })
                            }
                        },
                        grid: {
                            borderColor: 'rgba(255, 255, 255, 0.02)'
                        },
                        tooltip: {
                            theme: 'dark',
                            y: {
                                formatter: (val) => '$' + val.toLocaleString(undefined, {minimumFractionDigits: 2})
                            }
                        }
                    };
                    
                    const btContainer = document.querySelector("#backtest-chart");
                    btContainer.innerHTML = "";
                    backtestChart = new ApexCharts(btContainer, chartOpts);
                    backtestChart.render();
                }
            } catch (err) {
                console.error("Backtest request error:", err);
                showToast("❌ Network Error", "Failed to contact backtest execution server.", "danger");
            } finally {
                runBtn.disabled = false;
                runBtn.textContent = "Execute Simulation";
            }
        });
    }

    // Periodic synchronization loop fallback (every 30 seconds)
    setInterval(syncAll, 30000);
});
