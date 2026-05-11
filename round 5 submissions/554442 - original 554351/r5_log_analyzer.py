#!/usr/bin/env python3
"""
╔═══════════════════════════════════════════════════════════════════════════╗
║       IMC Prosperity 4 — Round 5 Log Analyzer  (r5_log_analyzer)        ║
║                                                                           ║
║  Three modes in one file:                                                 ║
║                                                                           ║
║  1. LOG       — parse your .log, analyse all 50 products, produce        ║
║                 cherry-pick rankings, risk metrics & a Claude brief      ║
║                                                                           ║
║  2. RISK      — risk-dashboard mode: full Sharpe / Sortino / Calmar /    ║
║                 drawdown / correlation report (for your risk-focused      ║
║                 teammate)                                                 ║
║                                                                           ║
║  3. COMPARE   — diff two .log files side-by-side: which products         ║
║                 improved, which regressed, delta-PnL table               ║
║                                                                           ║
╠═══════════════════════════════════════════════════════════════════════════╣
║  QUICK START                                                              ║
║                                                                           ║
║    python r5_log_analyzer.py log    <result.log>                         ║
║    python r5_log_analyzer.py risk   <result.log>                         ║
║    python r5_log_analyzer.py compare <log_A.log> <log_B.log>            ║
║                                                                           ║
║  Options (all modes):                                                     ║
║    --out DIR        output folder (default: r5_charts/)                  ║
║    --top N          products to show in rankings  (default: 20)          ║
║    --horizon N      forward-return horizon in ticks (default: 5)         ║
║                                                                           ║
║  Dependencies:  pip install matplotlib numpy scipy                        ║
╚═══════════════════════════════════════════════════════════════════════════╝
"""

import sys, re, json, math, os, time, bisect, argparse
from collections import defaultdict
from statistics import mean, stdev, median

# ── Optional deps ──────────────────────────────────────────────────────────
try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.gridspec as gridspec
    import numpy as np
    HAS_MPL = True
except ImportError:
    HAS_MPL = False
    np = None
    print("[WARN] matplotlib/numpy not found — charts disabled.  pip install matplotlib numpy")

try:
    from scipy import stats as sp_stats
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False

# ═══════════════════════════════════════════════════════════════════════════
#  CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════

CURRENCY       = "XIRECS"
TICKS_PER_DAY  = 1_000_000
MY_ID          = "SUBMISSION"
POSITION_LIMIT = 10          # all R5 products share limit 10

GROUPS: dict[str, list[str]] = {
    "GALAXY_SOUNDS": [
        "GALAXY_SOUNDS_DARK_MATTER", "GALAXY_SOUNDS_BLACK_HOLES",
        "GALAXY_SOUNDS_PLANETARY_RINGS", "GALAXY_SOUNDS_SOLAR_WINDS",
        "GALAXY_SOUNDS_SOLAR_FLAMES",
    ],
    "SLEEP_POD": [
        "SLEEP_POD_SUEDE", "SLEEP_POD_LAMB_WOOL", "SLEEP_POD_POLYESTER",
        "SLEEP_POD_NYLON", "SLEEP_POD_COTTON",
    ],
    "MICROCHIP": [
        "MICROCHIP_CIRCLE", "MICROCHIP_OVAL", "MICROCHIP_SQUARE",
        "MICROCHIP_RECTANGLE", "MICROCHIP_TRIANGLE",
    ],
    "PEBBLES": [
        "PEBBLES_XS", "PEBBLES_S", "PEBBLES_M", "PEBBLES_L", "PEBBLES_XL",
    ],
    "ROBOT": [
        "ROBOT_VACUUMING", "ROBOT_MOPPING", "ROBOT_DISHES",
        "ROBOT_LAUNDRY", "ROBOT_IRONING",
    ],
    "UV_VISOR": [
        "UV_VISOR_YELLOW", "UV_VISOR_AMBER", "UV_VISOR_ORANGE",
        "UV_VISOR_RED", "UV_VISOR_MAGENTA",
    ],
    "TRANSLATOR": [
        "TRANSLATOR_SPACE_GRAY", "TRANSLATOR_ASTRO_BLACK",
        "TRANSLATOR_ECLIPSE_CHARCOAL", "TRANSLATOR_GRAPHITE_MIST",
        "TRANSLATOR_VOID_BLUE",
    ],
    "PANEL": [
        "PANEL_1X2", "PANEL_2X2", "PANEL_1X4", "PANEL_2X4", "PANEL_4X4",
    ],
    "OXYGEN_SHAKE": [
        "OXYGEN_SHAKE_MORNING_BREATH", "OXYGEN_SHAKE_EVENING_BREATH",
        "OXYGEN_SHAKE_MINT", "OXYGEN_SHAKE_CHOCOLATE", "OXYGEN_SHAKE_GARLIC",
    ],
    "SNACKPACK": [
        "SNACKPACK_CHOCOLATE", "SNACKPACK_VANILLA", "SNACKPACK_PISTACHIO",
        "SNACKPACK_STRAWBERRY", "SNACKPACK_RASPBERRY",
    ],
}
ALL_PRODUCTS = [p for prods in GROUPS.values() for p in prods]

GROUP_COLORS = {
    "GALAXY_SOUNDS": "#4477AA", "SLEEP_POD":    "#EE6677",
    "MICROCHIP":     "#228833", "PEBBLES":      "#CCBB44",
    "ROBOT":         "#66CCEE", "UV_VISOR":     "#AA3377",
    "TRANSLATOR":    "#888888", "PANEL":        "#EE8833",
    "OXYGEN_SHAKE":  "#44BB99", "SNACKPACK":    "#9966CC",
}

def product_group(p: str) -> str:
    for g, prods in GROUPS.items():
        if p in prods:
            return g
    return "OTHER"

def short(p: str) -> str:
    """Last 1-2 underscore segments — fits in chart labels."""
    parts = p.split("_")
    return "_".join(parts[-2:]) if len(parts) >= 3 else p


# ═══════════════════════════════════════════════════════════════════════════
#  LOG PARSING  — identical backbone to R4, updated for R5 fields
# ═══════════════════════════════════════════════════════════════════════════

def load_and_parse(filepath: str):
    print(f"\n>>> Loading: {filepath}")
    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        raw = f.read().strip()
    lines = [l for l in raw.splitlines() if l.strip()]
    print(f"  {len(raw):,} bytes  |  {len(lines):,} non-empty lines")

    if raw.startswith("{"):
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            obj = _regex_extract(raw)
        act_csv    = _get(obj, "activitiesLog", "activities_log")
        trades_raw = _get(obj, "tradesLog", "trades_log", "tradeHistory", "trade_history")
        sandbox    = _get(obj, "sandboxLog", "lambdaLog", "logs")
        if isinstance(sandbox, list):
            sandbox = "\n".join(str(e.get("lambdaLog") or e.get("sandboxLog") or e) for e in sandbox)
        activities = _parse_activities(act_csv)
        trades     = (_parse_trades_list(trades_raw) if isinstance(trades_raw, list)
                      else _parse_trades_csv(str(trades_raw)))
        return activities, trades, str(sandbox or "")

    if lines and lines[0].startswith("{"):
        activities, trades = [], []
        for line in lines:
            a, t = _parse_jsonl_line(line)
            activities.extend(a); trades.extend(t)
        return activities, trades, ""

    return _parse_section_text(raw), [], ""


def _get(obj, *keys):
    for k in keys:
        v = obj.get(k)
        if v is not None:
            return v
    return ""


def _regex_extract(raw: str) -> dict:
    obj = {}
    for field in ["activitiesLog", "tradesLog", "lambdaLog", "sandboxLog"]:
        m = re.search(rf'"{field}"\s*:\s*"((?:[^"\\]|\\.)*)"', raw)
        if m:
            obj[field] = m.group(1).replace("\\n", "\n").replace("\\t", "\t")
    return obj


def _parse_activities(csv_string: str) -> list:
    rows = []
    if not csv_string:
        return rows
    for line in str(csv_string).splitlines():
        line = line.strip()
        if not line or re.match(r'^day', line, re.I):
            continue
        parts = line.split(";")
        if len(parts) < 17:
            continue
        try:
            def flt(s):
                s = s.strip(); return float(s) if s else None
            rows.append({
                "day":       int(parts[0]),
                "timestamp": int(parts[1]),
                "product":   parts[2].strip().upper(),
                "bid1_p": flt(parts[3]),  "bid1_v": flt(parts[4]),
                "bid2_p": flt(parts[5]),  "bid2_v": flt(parts[6]),
                "bid3_p": flt(parts[7]),  "bid3_v": flt(parts[8]),
                "ask1_p": flt(parts[9]),  "ask1_v": flt(parts[10]),
                "ask2_p": flt(parts[11]), "ask2_v": flt(parts[12]),
                "ask3_p": flt(parts[13]), "ask3_v": flt(parts[14]),
                "mid_price": flt(parts[15]),
                "pnl":       flt(parts[16]),
            })
        except (ValueError, IndexError):
            continue
    return rows


def _parse_trades_csv(csv_string: str) -> list:
    trades = []
    if not csv_string:
        return trades
    for line in csv_string.splitlines():
        line = line.strip()
        if not line or re.match(r'^timestamp', line, re.I):
            continue
        parts = line.split(";")
        if len(parts) < 7:
            continue
        try:
            trades.append({
                "timestamp": int(parts[0]),
                "buyer":     parts[1].strip(),
                "seller":    parts[2].strip(),
                "symbol":    parts[3].strip().upper(),
                "price":     float(parts[5]),
                "quantity":  int(parts[6]),
            })
        except (ValueError, IndexError):
            continue
    return trades


def _parse_trades_list(trade_list: list) -> list:
    trades = []
    for e in (trade_list or []):
        if not isinstance(e, dict):
            continue
        try:
            trades.append({
                "timestamp": int(e.get("timestamp", 0)),
                "buyer":     str(e.get("buyer", "") or ""),
                "seller":    str(e.get("seller", "") or ""),
                "symbol":    str(e.get("symbol", "") or "").upper(),
                "price":     float(e["price"]),
                "quantity":  int(e["quantity"]),
            })
        except (KeyError, ValueError, TypeError):
            continue
    return trades


def _parse_jsonl_line(line: str):
    activities, trades = [], []
    try:
        obj   = json.loads(line)
        state = obj.get("state") or {}
        if isinstance(state, str):
            try: state = json.loads(state)
            except: state = {}
        ts  = state.get("timestamp", 0)
        day = ts // TICKS_PER_DAY
        for sym, depth in (state.get("order_depths") or {}).items():
            bids = sorted([int(p) for p in depth.get("buy_orders",  {})], reverse=True)
            asks = sorted([int(p) for p in depth.get("sell_orders", {})])
            mid  = (bids[0] + asks[0]) / 2.0 if bids and asks else None
            activities.append({
                "day": day, "timestamp": ts, "product": sym.upper(),
                "bid1_p": bids[0] if bids else None,
                "ask1_p": asks[0] if asks else None,
                "bid1_v": None, "ask1_v": None,
                "bid2_p": bids[1] if len(bids)>1 else None,
                "ask2_p": asks[1] if len(asks)>1 else None,
                "bid2_v": None, "ask2_v": None,
                "bid3_p": bids[2] if len(bids)>2 else None,
                "ask3_p": asks[2] if len(asks)>2 else None,
                "bid3_v": None, "ask3_v": None,
                "mid_price": mid, "pnl": None,
            })
        for sym, ts_trades in (state.get("market_trades") or {}).items():
            for t in (ts_trades or []):
                try:
                    trades.append({
                        "timestamp": ts,
                        "buyer":     str(t.get("buyer",  "") or ""),
                        "seller":    str(t.get("seller", "") or ""),
                        "symbol":    sym.upper(),
                        "price":     float(t["price"]),
                        "quantity":  int(t["quantity"]),
                    })
                except Exception:
                    pass
    except Exception:
        pass
    return activities, trades


def _parse_section_text(raw: str) -> list:
    activities = []
    in_activities = False
    for line in raw.splitlines():
        if re.search(r'Activities log|activitiesLog', line, re.I):
            in_activities = True; continue
        if in_activities and re.match(r'^\s*[A-Z]', line) and ";" not in line:
            in_activities = False
        if in_activities:
            activities.extend(_parse_activities(line))
    return activities


# ═══════════════════════════════════════════════════════════════════════════
#  CORE RISK MATHS
# ═══════════════════════════════════════════════════════════════════════════

def _returns(pnl_series: list[float]) -> list[float]:
    """Tick-over-tick PnL increments (not percentage — absolute XIREC returns)."""
    return [pnl_series[i] - pnl_series[i-1] for i in range(1, len(pnl_series))]


def _sharpe(rets: list[float], annualise: bool = False) -> float:
    """Sharpe ratio of a return series.  Risk-free = 0."""
    if len(rets) < 2:
        return 0.0
    m = mean(rets)
    s = stdev(rets)
    if s == 0:
        return float("inf") if m > 0 else 0.0
    raw = m / s
    # Annualise to ~252 trading days × 10k ticks/day (approximate)
    return raw * math.sqrt(len(rets)) if annualise else raw * math.sqrt(len(rets))


def _sortino(rets: list[float]) -> float:
    """Sortino ratio: uses downside deviation only."""
    if len(rets) < 2:
        return 0.0
    m = mean(rets)
    neg = [r for r in rets if r < 0]
    if not neg:
        return float("inf")
    downside_std = math.sqrt(mean(r**2 for r in neg))
    return (m / downside_std) * math.sqrt(len(rets)) if downside_std > 0 else 0.0


def _max_drawdown(pnl_series: list[float]) -> float:
    """Maximum drawdown in XIREC absolute terms."""
    if not pnl_series:
        return 0.0
    peak = pnl_series[0]
    max_dd = 0.0
    for v in pnl_series:
        if v > peak:
            peak = v
        dd = peak - v
        if dd > max_dd:
            max_dd = dd
    return max_dd


def _calmar(net_pnl: float, max_dd: float) -> float:
    """Calmar ratio: total return / max drawdown. Higher = better."""
    return net_pnl / max_dd if max_dd > 0 else (float("inf") if net_pnl > 0 else 0.0)


def _win_rate(rets: list[float]) -> float:
    """Fraction of ticks with positive return."""
    if not rets:
        return 0.0
    return sum(1 for r in rets if r > 0) / len(rets)


def _profit_factor(rets: list[float]) -> float:
    """Gross profits / gross losses."""
    wins  = sum(r for r in rets if r > 0)
    loss  = sum(-r for r in rets if r < 0)
    return wins / loss if loss > 0 else (float("inf") if wins > 0 else 0.0)


def _skewness(rets: list[float]) -> float:
    if len(rets) < 3:
        return 0.0
    m, s = mean(rets), stdev(rets)
    if s == 0:
        return 0.0
    n = len(rets)
    return (n / ((n-1)*(n-2))) * sum(((r-m)/s)**3 for r in rets)


def _kurtosis(rets: list[float]) -> float:
    """Excess kurtosis (normal = 0)."""
    if len(rets) < 4:
        return 0.0
    m, s = mean(rets), stdev(rets)
    if s == 0:
        return 0.0
    n = len(rets)
    k = (n*(n+1)/((n-1)*(n-2)*(n-3))) * sum(((r-m)/s)**4 for r in rets)
    return k - 3*(n-1)**2 / ((n-2)*(n-3))


def _rolling_sharpe(rets: list[float], window: int = 200) -> list[float]:
    """Rolling Sharpe ratio (windowed)."""
    result = [float("nan")] * len(rets)
    for i in range(window, len(rets)):
        w = rets[i-window:i]
        m, s = mean(w), stdev(w) if len(w) > 1 else 0.0
        result[i] = (m / s) * math.sqrt(window) if s > 0 else 0.0
    return result


def _acf(rets: list[float], max_lag: int = 20) -> dict[int, float]:
    """Autocorrelation function up to max_lag."""
    n  = len(rets)
    mu = mean(rets)
    var = sum((r - mu)**2 for r in rets) / n
    if var < 1e-15:
        return {}
    result = {}
    for lag in range(1, min(max_lag + 1, n // 2)):
        cov = sum((rets[i] - mu) * (rets[i - lag] - mu)
                  for i in range(lag, n)) / n
        result[lag] = cov / var
    return result


# ═══════════════════════════════════════════════════════════════════════════
#  ANALYTICS
# ═══════════════════════════════════════════════════════════════════════════

def compute_pnl_metrics(activities: list) -> dict:
    """
    Per-product:
      net_pnl, final_pnl, peak_pnl, trough_pnl, max_drawdown,
      sharpe, sortino, calmar, win_rate, profit_factor,
      skewness, kurtosis, ticks, pnl_series, ret_series
    """
    by_prod: dict[str, list] = defaultdict(list)
    for r in activities:
        if r["pnl"] is not None:
            by_prod[r["product"]].append((r["timestamp"], r["pnl"]))

    metrics = {}
    for prod, ts_pnl in by_prod.items():
        ts_pnl.sort()
        pnls = [p for _, p in ts_pnl]
        if len(pnls) < 2:
            continue
        rets    = _returns(pnls)
        net_pnl = pnls[-1] - pnls[0]
        max_dd  = _max_drawdown(pnls)

        metrics[prod] = {
            "net_pnl":      net_pnl,
            "final_pnl":    pnls[-1],
            "initial_pnl":  pnls[0],
            "peak_pnl":     max(pnls),
            "trough_pnl":   min(pnls),
            "max_drawdown": max_dd,
            # ── Risk metrics ──────────────────────────────────────────────
            "sharpe":       _sharpe(rets),
            "sortino":      _sortino(rets),
            "calmar":       _calmar(net_pnl, max_dd),
            "win_rate":     _win_rate(rets),
            "profit_factor": _profit_factor(rets),
            "skewness":     _skewness(rets),
            "kurtosis":     _kurtosis(rets),
            # ── Series ────────────────────────────────────────────────────
            "pnl_series":   pnls,
            "ret_series":   rets,
            "ticks":        len(pnls),
        }
    return metrics


def compute_group_attribution(pnl_metrics: dict) -> dict:
    """Sum net_pnl and aggregate risk per group."""
    result = {}
    for gname, members in GROUPS.items():
        prods  = [m for m in members if m in pnl_metrics]
        if not prods:
            continue
        group_pnl = sum(pnl_metrics[p]["net_pnl"] for p in prods)
        # Pool all returns for group-level Sharpe
        pooled = []
        for p in prods:
            pooled.extend(pnl_metrics[p]["ret_series"])
        result[gname] = {
            "net_pnl":      group_pnl,
            "n_products":   len(prods),
            "sharpe":       _sharpe(pooled) if pooled else 0.0,
            "max_drawdown": max(pnl_metrics[p]["max_drawdown"] for p in prods),
            "best_product": max(prods, key=lambda p: pnl_metrics[p]["net_pnl"]),
            "worst_product": min(prods, key=lambda p: pnl_metrics[p]["net_pnl"]),
            "products":     prods,
        }
    return result


def compute_portfolio_risk(pnl_metrics: dict) -> dict:
    """
    Portfolio-level risk metrics treating each product as a position.
    Also computes per-product contribution to portfolio variance.
    """
    prods = [p for p in pnl_metrics if pnl_metrics[p]["ret_series"]]
    if not prods:
        return {}

    # Align series by length (use shortest for portfolio return)
    min_len = min(len(pnl_metrics[p]["ret_series"]) for p in prods)
    mat = [pnl_metrics[p]["ret_series"][:min_len] for p in prods]

    port_rets = [sum(col) for col in zip(*mat)]

    # Per-product marginal contribution to portfolio Sharpe
    port_sharpe = _sharpe(port_rets)
    port_sortino = _sortino(port_rets)

    if HAS_MPL and min_len > 1:
        arr = np.array(mat)  # shape (n_products, n_ticks)
        cov = np.cov(arr)    # (n_products, n_products)
        port_var = float(np.sum(cov))
        # Marginal contribution: cov_i_portfolio / port_std
        port_std = math.sqrt(max(port_var, 1e-15))
        marginal_contrib = {}
        for i, p in enumerate(prods):
            row_sum = float(np.sum(cov[i]))
            marginal_contrib[p] = row_sum / port_std if port_std > 0 else 0.0

        # FIX: Filter out zero-variance products before calculating correlation
        valid_indices = [i for i in range(len(prods)) if np.std(arr[i]) > 1e-9]
        valid_prods = [prods[i] for i in valid_indices]
        valid_arr = arr[valid_indices]

        pairs = []
        if len(valid_prods) > 1:
            corr = np.corrcoef(valid_arr)
            for i in range(len(valid_prods)):
                for j in range(i+1, len(valid_prods)):
                    pairs.append((valid_prods[i], valid_prods[j], float(corr[i, j])))
        pairs.sort(key=lambda x: abs(x[2]), reverse=True)
        
    else:
        # THE MISSING PART:
        marginal_contrib = {p: 0.0 for p in prods}
        pairs = []

    port_rets_series = port_rets
    return {
        "n_products":         len(prods),
        "portfolio_sharpe":   port_sharpe,
        "portfolio_sortino":  port_sortino,
        "portfolio_net_pnl":  sum(pnl_metrics[p]["net_pnl"] for p in prods),
        "portfolio_max_dd":   _max_drawdown([sum(col) for col in
                                             zip(*[pnl_metrics[p]["pnl_series"][:min_len]
                                                   for p in prods])]),
        "portfolio_calmar":   _calmar(
            sum(pnl_metrics[p]["net_pnl"] for p in prods),
            _max_drawdown([sum(col) for col in
                           zip(*[pnl_metrics[p]["pnl_series"][:min_len] for p in prods])])
        ),
        "portfolio_win_rate": _win_rate(port_rets),
        "portfolio_pf":       _profit_factor(port_rets),
        "marginal_contrib":   marginal_contrib,
        "top_correlations":   pairs[:10],
        "port_ret_series":    port_rets_series,
    }


def compute_spread_analysis(activities: list) -> dict:
    """Per-product: mean/median/min/max spread and spread-to-noise ratio."""
    by_prod: dict[str, list] = defaultdict(list)
    for r in activities:
        if r["bid1_p"] is not None and r["ask1_p"] is not None:
            spread = r["ask1_p"] - r["bid1_p"]
            if spread >= 0:
                by_prod[r["product"]].append(spread)
    result = {}
    for prod, spreads in by_prod.items():
        if not spreads:
            continue
        result[prod] = {
            "mean":   mean(spreads),
            "median": median(spreads),
            "min":    min(spreads),
            "max":    max(spreads),
            "std":    stdev(spreads) if len(spreads) > 1 else 0.0,
            "n":      len(spreads),
        }
    return result


def compute_execution_diagnosis(activities: list, trades: list,
                                 pnl_metrics: dict) -> dict:
    """
    Cross-reference the trade log against the activity PnL log to classify
    every product into one of four execution states:

      NEVER_ORDERED   — no own trades at all, PnL flat throughout.
                        Your algo is not generating orders for this product.
                        Fix: check ALL_SYMBOLS list, order generation logic,
                        or position-limit guard rejecting all orders.

      ORDERS_REJECTED — activity rows exist (market is live) but zero own
                        trades and PnL is truly zero.  Bot orders exist in the
                        book but your orders are being rejected before they
                        reach the matching engine.
                        Fix: check position-limit arithmetic — if you
                        initialise position incorrectly you reject your own
                        orders every tick.

      FILLED_FLAT     — own trades exist but net PnL ≈ 0.  You are trading
                        but capturing no edge.  Classic symptom of a spread
                        that is too wide to lift, or a fair value estimate
                        exactly at mid (buying ask, selling bid, zero net).
                        Fix: check fair value formula; tighten or shift quotes.

      ACTIVE          — both own trades and non-trivial PnL.  Normal state.
                        PnL sign tells you whether the strategy is working.

    Returns dict: product -> {
        state, own_trade_count, own_buy_qty, own_sell_qty,
        net_own_qty, pnl_nonzero_ticks, market_trade_count, diagnosis
    }
    """
    # Own trades: buyer or seller == MY_ID
    own_by_prod: dict[str, list] = defaultdict(list)
    mkt_by_prod: dict[str, int]  = defaultdict(int)
    for t in trades:
        sym = t.get("symbol", "")
        is_own = (t.get("buyer", "") == MY_ID or t.get("seller", "") == MY_ID)
        if is_own:
            own_by_prod[sym].append(t)
        else:
            mkt_by_prod[sym] += 1

    # PnL variation per product from activities
    pnl_nonzero: dict[str, int] = defaultdict(int)
    for r in activities:
        if r["pnl"] is not None and r["pnl"] != 0.0:
            pnl_nonzero[r["product"]] += 1

    # All products that appear in any source
    all_prods = (set(pnl_metrics.keys()) |
                 set(own_by_prod.keys())  |
                 {r["product"] for r in activities})

    result = {}
    for prod in sorted(all_prods):
        own_trades = own_by_prod.get(prod, [])
        n_own      = len(own_trades)
        own_buy_qty  = sum(t["quantity"] for t in own_trades
                           if t.get("buyer", "") == MY_ID)
        own_sell_qty = sum(t["quantity"] for t in own_trades
                           if t.get("seller", "") == MY_ID)
        net_own      = own_buy_qty - own_sell_qty
        n_mkt        = mkt_by_prod.get(prod, 0)
        n_pnl_nz     = pnl_nonzero.get(prod, 0)
        net_pnl      = pnl_metrics.get(prod, {}).get("net_pnl", 0.0)

        # ── Classify ──────────────────────────────────────────────────────
        if n_own == 0 and n_pnl_nz == 0 and n_mkt == 0:
            state = "NEVER_ORDERED"
            diagnosis = ("Algo generated zero orders. Check: (1) product in "
                         "ALL_SYMBOLS? (2) order-generation branch reached? "
                         "(3) position-limit guard blocking all orders from tick 0?")
        elif n_own == 0 and n_pnl_nz == 0 and n_mkt > 0:
            state = "ORDERS_REJECTED"
            diagnosis = (f"Market is live ({n_mkt} bot trades) but your orders "
                         "never filled. Most likely cause: position-limit "
                         "arithmetic error — algo thinks it is already at limit "
                         "and rejects every new order. Check position initialisation.")
        elif n_own > 0 and abs(net_pnl) < 5.0:
            state = "FILLED_FLAT"
            diagnosis = (f"{n_own} own trades executed (buy={own_buy_qty} "
                         f"sell={own_sell_qty}) but PnL ≈ 0. "
                         "Fair value estimate likely equals mid exactly — you are "
                         "buying the ask and selling the bid with zero edge. "
                         "Shift fair value by at least half the spread.")
        else:
            state = "ACTIVE"
            sign  = "profitable" if net_pnl >= 0 else "LOSING"
            diagnosis = (f"{n_own} own trades (buy={own_buy_qty} "
                         f"sell={own_sell_qty}), net_pnl={net_pnl:+,.0f} — {sign}.")

        result[prod] = {
            "state":             state,
            "own_trade_count":   n_own,
            "own_buy_qty":       own_buy_qty,
            "own_sell_qty":      own_sell_qty,
            "net_own_qty":       net_own,
            "market_trade_count": n_mkt,
            "pnl_nonzero_ticks": n_pnl_nz,
            "net_pnl":           net_pnl,
            "diagnosis":         diagnosis,
        }
    return result


def compute_acf_analysis(activities: list, max_lag: int = 20) -> dict:
    """Per-product return ACF. Negative ACF(1) = mean-reverting."""
    by_prod: dict[str, list] = defaultdict(list)
    for r in activities:
        if r["mid_price"] is not None:
            by_prod[r["product"]].append((r["timestamp"], r["mid_price"]))

    result = {}
    for prod, pts in by_prod.items():
        pts.sort()
        prices = [p[1] for p in pts]
        if len(prices) < 30:
            continue
        rets = [(prices[i] - prices[i-1]) / prices[i-1]
                for i in range(1, len(prices)) if prices[i-1] > 0]
        if len(rets) < 20:
            continue
        acf_vals = _acf(rets, max_lag)
        ci = 1.96 / math.sqrt(len(rets))
        acf1 = acf_vals.get(1, 0.0)
        result[prod] = {
            "acf":            acf_vals,
            "acf1":           acf1,
            "ci95":           ci,
            "n":              len(rets),
            "mean_reversion": acf1 < -ci,
            "trending":       acf1 > ci,
            "regime":         ("MEAN_REVERT" if acf1 < -ci
                               else "TRENDING" if acf1 > ci
                               else "RANDOM_WALK"),
        }
    return result


def compute_position_utilisation(activities: list) -> dict:
    """
    Estimate position from consecutive PnL / price-change ratios, then
    compute directional bias and explain WHY capped products are losing.

    Directional bias fields (new):
      long_frac       — fraction of time estimated position > 0 (net long)
      short_frac      — fraction of time estimated position < 0 (net short)
      dominant_side   — "LONG" | "SHORT" | "BALANCED"
      bias_pnl_corr   — correlation of position sign (+1 long, -1 short) with
                        the *next* tick's price move.
                        Negative → you are long when price falls (or short when
                        it rises) — your fair value estimate is systematically
                        wrong.
      cap_diagnosis   — plain-English root cause for CAPPED + losing products:
          "capped LONG while price trended DOWN → fair value estimate too HIGH;
           your buy threshold is too aggressive — reduce it or add a trend filter"
          "capped SHORT while price trended UP → fair value estimate too LOW;
           your sell threshold is too aggressive — raise it or add a trend filter"
          "capped but BALANCED direction → position flip-flopping at limit;
           spread is too tight — widen MM quotes to reduce fill frequency"
    """
    result = {}
    by_prod: dict[str, list] = defaultdict(list)
    for r in activities:
        by_prod[r["product"]].append(r)

    for prod, rows in by_prod.items():
        rows.sort(key=lambda x: x["timestamp"])

        positions  = []   # estimated signed position each tick
        mids       = []   # corresponding mid prices
        for i in range(1, len(rows)):
            prev, cur = rows[i-1], rows[i]
            if (prev["pnl"] is not None and cur["pnl"] is not None
                    and prev["mid_price"] and cur["mid_price"]):
                dp   = cur["mid_price"] - prev["mid_price"]
                dpnl = cur["pnl"] - prev["pnl"]
                if abs(dp) > 0.01:
                    pos = dpnl / dp
                    if abs(pos) <= POSITION_LIMIT * 1.2:
                        positions.append(pos)
                        mids.append(cur["mid_price"])

        if not positions:
            continue

        abs_pos = [abs(p) for p in positions]

        # ── Directional stats ─────────────────────────────────────────────
        n_long  = sum(1 for p in positions if p >  0.5)
        n_short = sum(1 for p in positions if p < -0.5)
        n_flat  = len(positions) - n_long - n_short
        n       = len(positions)

        long_frac  = n_long  / n
        short_frac = n_short / n

        if long_frac > 0.55:
            dominant = "LONG"
        elif short_frac > 0.55:
            dominant = "SHORT"
        else:
            dominant = "BALANCED"

        # Correlation: sign of position vs next tick's price move
        # pos_signs[i] correlated with mids[i+1] - mids[i]
        pos_signs  = [1 if p > 0 else (-1 if p < 0 else 0) for p in positions]
        price_moves = [mids[i] - mids[i-1] for i in range(1, len(mids))]
        bias_corr = 0.0
        if len(price_moves) > 5 and len(pos_signs) > 5:
            n_c = min(len(pos_signs) - 1, len(price_moves))
            ps  = pos_signs[:n_c]
            pm  = price_moves[:n_c]
            mu_ps = mean(ps) if ps else 0
            mu_pm = mean(pm) if pm else 0
            num = sum((ps[i]-mu_ps)*(pm[i]-mu_pm) for i in range(n_c))
            d_ps = math.sqrt(sum((x-mu_ps)**2 for x in ps) + 1e-15)
            d_pm = math.sqrt(sum((x-mu_pm)**2 for x in pm) + 1e-15)
            bias_corr = num / (d_ps * d_pm)

        # ── Cap diagnosis ─────────────────────────────────────────────────
        utilisation  = mean(abs_pos) / POSITION_LIMIT * 100
        pct_at_limit = (sum(1 for p in abs_pos if p > POSITION_LIMIT * 0.85)
                        / len(abs_pos) * 100)
        net_pnl_sign = sum(rows[-1]["pnl"] - rows[0]["pnl"]
                           for rows in [rows] if rows[-1]["pnl"] and rows[0]["pnl"])

        cap_diagnosis = ""
        if utilisation > 80:
            if dominant == "LONG" and bias_corr < -0.05:
                cap_diagnosis = (
                    "CAPPED LONG while price moved DOWN  →  fair value estimate too HIGH. "
                    "Your buy orders trigger too eagerly (you think price should be higher "
                    "than it is). Fix: lower your fair value by ~half the spread, or add a "
                    "downward momentum filter to suppress buys during falling markets."
                )
            elif dominant == "SHORT" and bias_corr > 0.05:
                cap_diagnosis = (
                    "CAPPED SHORT while price moved UP  →  fair value estimate too LOW. "
                    "Your sell orders trigger too eagerly. Fix: raise your fair value "
                    "estimate, or add an upward momentum filter to suppress sells."
                )
            elif dominant == "LONG" and bias_corr >= -0.05:
                cap_diagnosis = (
                    "CAPPED LONG but price direction mixed  →  position is stuck long but "
                    "not clearly from a trend bias. Most likely: your inventory skew / "
                    "mean-reversion exit is not working — once long you cannot get flat. "
                    "Fix: add a hard exit if position > 7 for N ticks; widen sell quotes."
                )
            elif dominant == "SHORT" and bias_corr <= 0.05:
                cap_diagnosis = (
                    "CAPPED SHORT but price direction mixed  →  stuck short without a clear "
                    "trend bias. Fix: add a hard exit if position < -7 for N ticks; "
                    "widen buy quotes to unwind faster."
                )
            else:
                cap_diagnosis = (
                    "CAPPED, BALANCED direction  →  position flipping at ±limit each way. "
                    "Spread is too tight relative to noise — you fill on both sides at "
                    "unfavourable prices. Fix: widen your MM half-spread by 1–2 ticks, "
                    "or add a minimum-edge filter before each order."
                )
        elif utilisation < 15:
            cap_diagnosis = (
                "UNDER-USED — algo is too conservative. Spread is too wide to ever "
                "lift bids/asks, or edge threshold is set too high. "
                "Check: is your fair value within 1 spread of the best bid/ask?"
            )

        result[prod] = {
            "limit":          POSITION_LIMIT,
            "est_avg_pos":    mean(abs_pos),
            "est_max_pos":    max(abs_pos),
            "utilisation":    utilisation,
            "pct_at_limit":   pct_at_limit,
            "n_samples":      n,
            # ── New directional fields ─────────────────────────────────────
            "long_frac":      long_frac,
            "short_frac":     short_frac,
            "dominant_side":  dominant,
            "bias_pnl_corr":  bias_corr,
            "cap_diagnosis":  cap_diagnosis,
        }
    return result


def compute_cherry_pick_score(pnl_metrics: dict, acf_data: dict,
                               spread_data: dict) -> list[dict]:
    """
    Score every traded product 0-100.
    High score → keep / increase attention.
    Low score  → drop or leave flat.

    Components:
      PnL sign & magnitude   40 %
      Sharpe ratio           25 %
      MR regime bonus        15 %
      Spread/noise ratio     10 %
      Win rate               10 %
    """
    if not pnl_metrics:
        return []

    all_pnls    = [abs(m["net_pnl"])    for m in pnl_metrics.values()]
    all_sharpes = [abs(m["sharpe"])     for m in pnl_metrics.values()]
    max_pnl     = max(all_pnls)    if all_pnls    else 1
    max_sharpe  = max(all_sharpes) if all_sharpes else 1

    rows = []
    for prod, m in pnl_metrics.items():
        pnl     = m["net_pnl"]
        sharpe  = m["sharpe"]
        wr      = m["win_rate"]
        acf_inf = acf_data.get(prod, {})
        spr_inf = spread_data.get(prod, {})

        # PnL score: positive pnl wins, negative penalised
        pnl_score = (pnl / max_pnl) * 40 if max_pnl > 0 else 0.0

        # Sharpe score (normalised, only positive contributes)
        sharpe_score = max(0, sharpe / max_sharpe) * 25 if max_sharpe > 0 else 0.0

        # MR regime bonus
        mr_bonus = 15 if acf_inf.get("mean_reversion") else 0

        # Spread/noise ratio
        spr  = spr_inf.get("mean", 0)
        mids = [r["mid_price"] for r in [] if r["mid_price"]]   # placeholder
        noise = m["ret_series"]
        noise_std = stdev(noise) if len(noise) > 1 else 1.0
        snr = min(spr / (noise_std + 1e-6), 3.0)
        spr_score = (snr / 3.0) * 10

        # Win rate
        wr_score = wr * 10

        total = pnl_score + sharpe_score + mr_bonus + spr_score + wr_score
        rows.append({
            "product":      prod,
            "group":        product_group(prod),
            "net_pnl":      pnl,
            "sharpe":       sharpe,
            "sortino":      m["sortino"],
            "calmar":       m["calmar"],
            "max_drawdown": m["max_drawdown"],
            "win_rate":     wr,
            "profit_factor": m["profit_factor"],
            "skewness":     m["skewness"],
            "kurtosis":     m["kurtosis"],
            "regime":       acf_inf.get("regime", "UNKNOWN"),
            "acf1":         acf_inf.get("acf1", float("nan")),
            "mean_spread":  spr_inf.get("mean", float("nan")),
            "pnl_score":    pnl_score,
            "sharpe_score": sharpe_score,
            "mr_bonus":     mr_bonus,
            "spr_score":    spr_score,
            "wr_score":     wr_score,
            "cherry_score": total,
            "verdict":      _cherry_verdict(pnl, sharpe, acf_inf.get("regime", "")),
        })
    rows.sort(key=lambda x: x["cherry_score"], reverse=True)
    return rows


def _cherry_verdict(pnl: float, sharpe: float, regime: str) -> str:
    if pnl > 0 and sharpe > 0.5 and regime == "MEAN_REVERT":
        return "🟢 KEEP — profitable MR scalp"
    if pnl > 0 and sharpe > 0.3:
        return "🟢 KEEP — profitable"
    if pnl > 0 and sharpe > 0:
        return "🟡 MONITOR — small edge"
    if pnl < 0 and sharpe < -0.3:
        return "🔴 DROP — consistently losing"
    if pnl < 0:
        return "🟠 REVIEW — negative PnL, check logic"
    return "⚪ FLAT — negligible edge"


def compute_rolling_sharpe_series(pnl_metrics: dict,
                                   window: int = 200) -> dict[str, list]:
    """Rolling Sharpe for each product (for time-series chart)."""
    result = {}
    for prod, m in pnl_metrics.items():
        rets = m["ret_series"]
        if len(rets) < window:
            continue
        result[prod] = _rolling_sharpe(rets, window)
    return result


# ═══════════════════════════════════════════════════════════════════════════
#  CHARTS
# ═══════════════════════════════════════════════════════════════════════════

OUTPUT_DIR = "r5_charts"

def _save(fig, fname: str):
    path = os.path.join(OUTPUT_DIR, fname)
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight", dpi=120)
    plt.close(fig)
    print(f"  ✓ {fname}")


def chart_pnl_curves(pnl_metrics: dict, activities: list):
    """PnL time-series per group, 2×5 grid."""
    if not pnl_metrics:
        return
    by_prod_ts: dict[str, list] = defaultdict(list)
    for r in activities:
        if r["pnl"] is not None:
            by_prod_ts[r["product"]].append((r["timestamp"], r["pnl"]))
    for prod in by_prod_ts:
        by_prod_ts[prod].sort()

    gnames = list(GROUPS.keys())
    nrows, ncols = 2, 5
    fig, axes = plt.subplots(nrows, ncols, figsize=(22, 8))
    fig.suptitle("PnL Curves by Group", fontsize=14, fontweight="bold")
    axes = axes.flatten()

    for idx, gname in enumerate(gnames):
        ax  = axes[idx]
        col = GROUP_COLORS[gname]
        any_data = False
        for prod in GROUPS[gname]:
            pts = by_prod_ts.get(prod, [])
            if not pts:
                continue
            ts_vals, pnl_vals = zip(*pts)
            ax.plot(ts_vals, pnl_vals, lw=0.8, label=short(prod), alpha=0.85)
            any_data = True
        ax.axhline(0, color="black", lw=0.6, ls="--")
        ax.set_title(gname, fontsize=9, fontweight="bold", color=col)
        ax.set_ylabel(CURRENCY, fontsize=7)
        ax.set_xlabel("Tick", fontsize=7)
        if any_data:
            ax.legend(fontsize=5, ncol=2)

    _save(fig, "01_pnl_curves.png")


def chart_risk_dashboard(cherry_rows: list, top_n: int = 25):
    """4-panel risk dashboard: Sharpe, Sortino, Max-DD, Calmar."""
    if not cherry_rows:
        return
    top = cherry_rows[:top_n]
    labels = [short(r["product"]) for r in top]
    colors = [GROUP_COLORS.get(r["group"], "#999999") for r in top]

    fig, axes = plt.subplots(2, 2, figsize=(20, 12))
    fig.suptitle(f"Risk Metrics Dashboard — Top {top_n} Products",
                 fontsize=14, fontweight="bold")

    # Sharpe
    ax = axes[0, 0]
    vals = [r["sharpe"] for r in top]
    bars = ax.barh(labels, vals, color=colors, alpha=0.85)
    ax.axvline(0, color="black", lw=0.8)
    ax.axvline(0.5,  color="green",  ls="--", lw=1.0, label="Sharpe=0.5 target")
    ax.axvline(-0.5, color="red",    ls="--", lw=1.0)
    ax.set_title("Sharpe Ratio  (higher = better risk-adj return)")
    ax.set_xlabel("Sharpe"); ax.legend(fontsize=7)
    for bar, r in zip(bars, top):
        ax.text(bar.get_width() + 0.01 * max(abs(v) for v in vals + [1]),
                bar.get_y() + bar.get_height()/2,
                f"{r['net_pnl']:+,.0f}", va="center", fontsize=5.5)

    # Sortino
    ax = axes[0, 1]
    vals = [min(r["sortino"], 10) for r in top]   # cap inf
    ax.barh(labels, vals, color=colors, alpha=0.85)
    ax.axvline(0, color="black", lw=0.8)
    ax.axvline(0.7, color="green", ls="--", lw=1.0, label="Sortino=0.7")
    ax.set_title("Sortino Ratio  (penalises downside only)")
    ax.set_xlabel("Sortino"); ax.legend(fontsize=7)

    # Max drawdown
    ax = axes[1, 0]
    vals = [r["max_drawdown"] for r in top]
    ax.barh(labels, vals, color=colors, alpha=0.85)
    ax.axvline(0, color="black", lw=0.8)
    ax.set_title(f"Max Drawdown ({CURRENCY})  (lower = more stable)")
    ax.set_xlabel(CURRENCY)

    # Win rate + profit factor
    ax = axes[1, 1]
    wr   = [r["win_rate"] * 100 for r in top]
    pf   = [min(r["profit_factor"], 5) for r in top]   # cap inf
    x    = range(len(top))
    ax2  = ax.twinx()
    ax.bar(x, wr, color=colors, alpha=0.6, label="Win rate %")
    ax2.plot(x, pf, "k--o", ms=4, lw=1.2, label="Profit Factor")
    ax.axhline(50, color="orange", ls=":", lw=1.0)
    ax.set_xticks(x); ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=6)
    ax.set_ylabel("Win Rate (%)"); ax2.set_ylabel("Profit Factor")
    ax.set_title("Win Rate & Profit Factor")
    ax.legend(fontsize=7, loc="upper left")
    ax2.legend(fontsize=7, loc="upper right")

    from matplotlib.patches import Patch
    patches = [Patch(facecolor=c, label=g) for g, c in GROUP_COLORS.items()]
    fig.legend(handles=patches, fontsize=6, loc="lower center",
               ncol=5, bbox_to_anchor=(0.5, -0.01))

    _save(fig, "02_risk_dashboard.png")


def chart_cherry_pick_ranking(cherry_rows: list):
    """Horizontal bar chart: cherry-pick score + PnL annotation."""
    if not cherry_rows:
        return
    rows   = cherry_rows[:40]
    labels = [short(r["product"]) for r in rows]
    scores = [r["cherry_score"] for r in rows]
    colors = [GROUP_COLORS.get(r["group"], "#999999") for r in rows]

    fig, ax = plt.subplots(figsize=(14, max(8, len(rows) * 0.38)))
    bars = ax.barh(labels, scores, color=colors, alpha=0.85)
    ax.axvline(50, color="green", ls="--", lw=1.2, label="Score 50 (good)")
    ax.axvline(25, color="orange", ls="--", lw=1.0, label="Score 25 (marginal)")
    ax.axvline(0,  color="black", lw=0.8)
    ax.set_xlabel("Cherry-Pick Score  (0–100)")
    ax.set_title("Product Cherry-Pick Ranking\n(PnL annotated on bars)",
                 fontsize=12, fontweight="bold")
    ax.legend(fontsize=8)

    for bar, r in zip(bars, rows):
        pnl_str = f"{r['net_pnl']:+,.0f}"
        regime  = r["regime"][:2] if r["regime"] else "?"
        ax.text(bar.get_width() + 0.3, bar.get_y() + bar.get_height()/2,
                f"{pnl_str}  [{regime}]", va="center", fontsize=6.5)

    from matplotlib.patches import Patch
    patches = [Patch(facecolor=c, label=g) for g, c in GROUP_COLORS.items()]
    ax.legend(handles=patches + [
        plt.Line2D([0],[0], color="green",  ls="--", label="Score 50"),
        plt.Line2D([0],[0], color="orange", ls="--", label="Score 25"),
    ], fontsize=6, loc="lower right")

    _save(fig, "03_cherry_pick_ranking.png")


def chart_group_attribution(group_attr: dict):
    """Group-level PnL waterfall + Sharpe."""
    if not group_attr:
        return
    groups = sorted(group_attr.keys(), key=lambda g: group_attr[g]["net_pnl"], reverse=True)
    pnls   = [group_attr[g]["net_pnl"]   for g in groups]
    sharps = [group_attr[g]["sharpe"]     for g in groups]
    colors = [GROUP_COLORS.get(g, "#999999") for g in groups]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 6))
    fig.suptitle("Group PnL Attribution & Sharpe", fontsize=13, fontweight="bold")

    x = range(len(groups))
    bar_colors = [("#43A047" if p >= 0 else "#E53935") for p in pnls]
    ax1.bar(x, pnls, color=bar_colors, alpha=0.85)
    ax1.axhline(0, color="black", lw=0.8)
    ax1.set_xticks(x)
    ax1.set_xticklabels(groups, rotation=30, ha="right", fontsize=8)
    ax1.set_ylabel(f"Net PnL ({CURRENCY})")
    ax1.set_title("Net PnL by Group")
    for i, (g, p) in enumerate(zip(groups, pnls)):
        ax1.text(i, p + (max(pnls)*0.01 if p >= 0 else min(pnls)*0.01),
                 f"{p:+,.0f}", ha="center", fontsize=7)

    bar_colors2 = [("#43A047" if s >= 0 else "#E53935") for s in sharps]
    ax2.bar(x, sharps, color=bar_colors2, alpha=0.85)
    ax2.axhline(0,   color="black", lw=0.8)
    ax2.axhline(0.5, color="green",  ls="--", lw=1.0, label="Sharpe=0.5")
    ax2.set_xticks(x)
    ax2.set_xticklabels(groups, rotation=30, ha="right", fontsize=8)
    ax2.set_ylabel("Group Sharpe Ratio")
    ax2.set_title("Group-Level Sharpe")
    ax2.legend(fontsize=8)

    _save(fig, "04_group_attribution.png")


def chart_return_acf(acf_data: dict, top_n: int = 20):
    """ACF bar charts for top N products by |ACF(1)|."""
    if not HAS_MPL or not acf_data:
        return
    # Sort by |ACF(1)|
    sorted_prods = sorted(acf_data.keys(),
                          key=lambda p: abs(acf_data[p]["acf1"]), reverse=True)
    prods = sorted_prods[:top_n]
    ncols = 4
    nrows = math.ceil(len(prods) / ncols)
    fig, axes = plt.subplots(nrows, ncols, figsize=(5*ncols, 3.2*nrows), squeeze=False)
    axes = axes.flatten()
    fig.suptitle(f"Return ACF — Top {len(prods)} by |ACF(1)|\n"
                 "(red = significant; negative lag-1 = mean-reversion)",
                 fontsize=12, fontweight="bold")

    for i, prod in enumerate(prods):
        ax   = axes[i]
        data = acf_data[prod]
        lags = sorted(data["acf"].keys())
        vals = [data["acf"][l] for l in lags]
        ci   = data["ci95"]
        color = "#E53935" if data["mean_reversion"] else (
                "#43A047" if data["trending"] else "steelblue")
        ax.bar(lags, vals, color=color, alpha=0.8)
        ax.axhline( ci, color="orange", ls="--", lw=0.8)
        ax.axhline(-ci, color="orange", ls="--", lw=0.8)
        ax.axhline(0,   color="grey",   lw=0.5)
        mr_tag = "◄MR" if data["mean_reversion"] else ("▲TR" if data["trending"] else "")
        ax.set_title(f"{short(prod)}\nACF1={data['acf1']:+.3f}  {mr_tag}",
                     fontsize=7, color=color)
        ax.set_xlabel("Lag", fontsize=6)
        ax.set_ylim(-0.6, 0.6)

    for j in range(len(prods), len(axes)):
        axes[j].set_visible(False)

    _save(fig, "05_return_acf.png")


def chart_rolling_sharpe(rolling: dict, top_n: int = 12):
    """Rolling Sharpe time-series for top N products."""
    if not HAS_MPL or not rolling:
        return
    prods = list(rolling.keys())[:top_n]
    ncols = 3
    nrows = math.ceil(len(prods) / ncols)
    fig, axes = plt.subplots(nrows, ncols, figsize=(6*ncols, 3.5*nrows), squeeze=False)
    axes = axes.flatten()
    fig.suptitle(f"Rolling Sharpe (window=200 ticks) — Top {len(prods)} Products",
                 fontsize=12, fontweight="bold")

    for i, prod in enumerate(prods):
        ax   = axes[i]
        vals = rolling[prod]
        ts   = range(len(vals))
        col  = GROUP_COLORS.get(product_group(prod), "steelblue")
        ax.plot(ts, vals, lw=0.7, color=col, alpha=0.85)
        ax.axhline(0,   color="black",  lw=0.8, ls="--")
        ax.axhline(0.5, color="green",  lw=0.8, ls=":",  label="0.5")
        ax.axhline(-0.5,color="red",    lw=0.8, ls=":",  label="-0.5")
        ax.fill_between(ts, vals, 0,
                        where=[v >= 0 for v in vals], alpha=0.25, color="green")
        ax.fill_between(ts, vals, 0,
                        where=[v < 0 for v in vals],  alpha=0.25, color="red")
        ax.set_title(f"{short(prod)}\n[{product_group(prod)}]", fontsize=7, color=col)
        ax.legend(fontsize=5); ax.set_xlabel("Tick", fontsize=6)
        ax.set_ylabel("Sharpe", fontsize=6)

    for j in range(len(prods), len(axes)):
        axes[j].set_visible(False)

    _save(fig, "06_rolling_sharpe.png")


def chart_drawdown_curves(pnl_metrics: dict, top_n: int = 15):
    """Drawdown time-series for worst-drawdown products."""
    if not HAS_MPL or not pnl_metrics:
        return
    # Sort by max drawdown descending
    sorted_prods = sorted(pnl_metrics.keys(),
                          key=lambda p: pnl_metrics[p]["max_drawdown"], reverse=True)
    prods = sorted_prods[:top_n]
    ncols = 3
    nrows = math.ceil(len(prods) / ncols)
    fig, axes = plt.subplots(nrows, ncols, figsize=(6*ncols, 3.5*nrows), squeeze=False)
    axes = axes.flatten()
    fig.suptitle(f"Drawdown Curves — Top {len(prods)} Worst Drawdowns",
                 fontsize=12, fontweight="bold")

    for i, prod in enumerate(prods):
        ax   = axes[i]
        pnls = pnl_metrics[prod]["pnl_series"]
        ts   = range(len(pnls))
        # Compute drawdown curve
        peak = pnls[0]
        dd_curve = []
        for p in pnls:
            if p > peak: peak = p
            dd_curve.append(-(peak - p))
        col = GROUP_COLORS.get(product_group(prod), "steelblue")
        ax.fill_between(ts, dd_curve, 0, alpha=0.5, color="#E53935")
        ax.plot(ts, dd_curve, lw=0.6, color="#B71C1C")
        ax.set_title(f"{short(prod)}\nMaxDD={pnl_metrics[prod]['max_drawdown']:,.0f}",
                     fontsize=7, color=col)
        ax.set_ylabel(CURRENCY, fontsize=6); ax.set_xlabel("Tick", fontsize=6)

    for j in range(len(prods), len(axes)):
        axes[j].set_visible(False)

    _save(fig, "07_drawdown_curves.png")


def chart_execution_diagnosis(exec_diag: dict):
    """
    4-quadrant summary of execution states across all 50 products.
    Left: stacked bar count by state per group.
    Right: own-trade volume heatmap (buy vs sell qty per product).
    """
    if not HAS_MPL or not exec_diag:
        return

    STATE_COLORS = {
        "NEVER_ORDERED":   "#BBBBBB",
        "ORDERS_REJECTED": "#FF8C00",
        "FILLED_FLAT":     "#4477AA",
        "ACTIVE":          "#228833",
    }
    STATES = ["NEVER_ORDERED", "ORDERS_REJECTED", "FILLED_FLAT", "ACTIVE"]

    # Group counts
    group_counts: dict[str, dict] = {g: {s: 0 for s in STATES} for g in GROUPS}
    for prod, d in exec_diag.items():
        g = product_group(prod)
        if g in group_counts:
            group_counts[g][d["state"]] += 1

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(20, 7))
    fig.suptitle("Execution Diagnosis — What Is Your Algorithm Actually Doing?",
                 fontsize=13, fontweight="bold")

    # ── Left: stacked bar by group ────────────────────────────────────────
    gnames = list(GROUPS.keys())
    bottoms = [0] * len(gnames)
    x = range(len(gnames))
    for state in STATES:
        vals = [group_counts[g][state] for g in gnames]
        ax1.bar(x, vals, bottom=bottoms, color=STATE_COLORS[state],
                label=state, alpha=0.9)
        bottoms = [b + v for b, v in zip(bottoms, vals)]
    ax1.set_xticks(x)
    ax1.set_xticklabels(gnames, rotation=30, ha="right", fontsize=8)
    ax1.set_ylabel("Number of Products")
    ax1.set_title("Execution State by Group\n"
                  "Grey=never ordered  Orange=orders rejected  "
                  "Blue=filled flat  Green=active")
    ax1.legend(fontsize=7, loc="upper right")
    ax1.axhline(5, color="black", lw=0.5, ls=":")  # max 5 per group

    # ── Right: own buy/sell qty scatter ──────────────────────────────────
    active = [(p, d) for p, d in exec_diag.items() if d["own_buy_qty"] + d["own_sell_qty"] > 0]
    if active:
        prods_a  = [short(p) for p, _ in active]
        buy_qtys = [d["own_buy_qty"]  for _, d in active]
        sel_qtys = [d["own_sell_qty"] for _, d in active]
        cols_a   = [GROUP_COLORS.get(product_group(p), "#999") for p, _ in active]
        y = range(len(active))
        ax2.barh(y, buy_qtys, color="#228833", alpha=0.7, label="Own Buy Qty")
        ax2.barh(y, [-s for s in sel_qtys], color="#E53935", alpha=0.7, label="Own Sell Qty")
        ax2.axvline(0, color="black", lw=0.8)
        ax2.set_yticks(y)
        ax2.set_yticklabels(prods_a, fontsize=6)
        ax2.set_xlabel("Own Buy (green, right) / Own Sell (red, left) Quantity")
        ax2.set_title("Own Trade Volume per Active Product\n"
                      "(imbalance = directional bias in your fills)")
        ax2.legend(fontsize=7)
    else:
        ax2.text(0.5, 0.5, "No own trades found in log.\nCheck MY_ID = 'SUBMISSION'",
                 ha="center", va="center", fontsize=10, color="red",
                 transform=ax2.transAxes)
        ax2.set_title("Own Trade Volume — NO OWN TRADES DETECTED")

    _save(fig, "13_execution_diagnosis.png")


def chart_directional_bias(util: dict, pnl_metrics: dict):
    """
    For each CAPPED product: long/short split bar + bias_pnl_corr scatter.
    Tells you which direction you are stuck in and whether it correlates
    with price moving against you.
    """
    if not HAS_MPL or not util:
        return

    capped = {p: u for p, u in util.items() if u["utilisation"] > 80}
    if not capped:
        return

    prods  = sorted(capped.keys(), key=lambda p: capped[p]["utilisation"], reverse=True)
    n      = len(prods)
    ncols  = 2
    nrows  = math.ceil(n / ncols)
    fig, axes = plt.subplots(nrows, ncols,
                              figsize=(12, max(5, nrows * 2.8)), squeeze=False)
    axes = axes.flatten()
    fig.suptitle("Directional Bias on CAPPED Products\n"
                 "(bias_corr < 0 = long when price falls / short when it rises → wrong-way bias)",
                 fontsize=12, fontweight="bold")

    for i, prod in enumerate(prods):
        ax  = axes[i]
        u   = capped[prod]
        col = GROUP_COLORS.get(product_group(prod), "steelblue")

        lf   = u["long_frac"]   * 100
        sf   = u["short_frac"]  * 100
        flat = max(0, 100 - lf - sf)
        corr = u["bias_pnl_corr"]
        dom  = u["dominant_side"]
        net_pnl = pnl_metrics.get(prod, {}).get("net_pnl", 0)

        # Stacked horizontal: long | flat | short
        ax.barh(0, lf,        left=0,         height=0.4, color="#228833", alpha=0.85, label=f"Long {lf:.0f}%")
        ax.barh(0, flat,      left=lf,        height=0.4, color="#CCCCCC", alpha=0.7,  label=f"Flat {flat:.0f}%")
        ax.barh(0, sf,        left=lf+flat,   height=0.4, color="#E53935", alpha=0.85, label=f"Short {sf:.0f}%")

        # Bias correlation bar below
        corr_color = "#E53935" if corr < 0 else "#228833"
        ax.barh(-0.6, corr * 50, height=0.35, color=corr_color, alpha=0.8,
                label=f"Bias corr={corr:+.3f}")
        ax.axvline(0, color="black", lw=0.5)
        ax.axvline(50, color="grey", lw=0.4, ls=":")  # midpoint

        ax.set_xlim(-55, 105)
        ax.set_yticks([0, -0.6])
        ax.set_yticklabels(["Position\nSplit %", "Bias\nCorr×50"], fontsize=6)
        ax.set_xlabel("← Short bias    Long bias →", fontsize=6)

        # Annotate with diagnosis snippet
        diag_short = u["cap_diagnosis"][:70] + "…" if len(u["cap_diagnosis"]) > 70 else u["cap_diagnosis"]
        ax.set_title(
            f"{short(prod)}  [{dom}]  util={u['utilisation']:.0f}%  "
            f"PnL={net_pnl:+,.0f}\n{diag_short}",
            fontsize=6.5, color=col, loc="left"
        )
        ax.legend(fontsize=5, ncol=2, loc="upper right")

    for j in range(n, len(axes)):
        axes[j].set_visible(False)

    _save(fig, "14_directional_bias.png")


def chart_position_utilisation(util: dict):
    """Position utilisation bar chart."""
    if not HAS_MPL or not util:
        return
    prods = sorted(util.keys(), key=lambda p: util[p]["utilisation"], reverse=True)
    avgs  = [util[p]["utilisation"]  for p in prods]
    at_lim= [util[p]["pct_at_limit"] for p in prods]
    colors= [GROUP_COLORS.get(product_group(p), "#999") for p in prods]

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(max(14, len(prods)*0.5), 10))
    fig.suptitle(f"Position Utilisation  (limit={POSITION_LIMIT} per product)",
                 fontsize=13, fontweight="bold")

    x = range(len(prods))
    ax1.bar(x, avgs, color=colors, alpha=0.85)
    ax1.axhline(80, color="red",   ls="--", lw=1.2, label="80% — near cap")
    ax1.axhline(20, color="green", ls="--", lw=1.0, label="20% — under-utilised")
    ax1.set_xticks(x); ax1.set_xticklabels([short(p) for p in prods],
                                            rotation=45, ha="right", fontsize=7)
    ax1.set_ylabel("Avg utilisation (% of limit=10)")
    ax1.set_title("Average Position / Limit (%)")
    ax1.legend(fontsize=8)

    ax2.bar(x, at_lim, color="orange", alpha=0.85)
    ax2.axhline(25, color="red", ls="--", lw=1.2, label="25% threshold")
    ax2.set_xticks(x); ax2.set_xticklabels([short(p) for p in prods],
                                            rotation=45, ha="right", fontsize=7)
    ax2.set_ylabel("% time >85% of limit")
    ax2.set_title("% of Time Capped  (high = you're leaving trades on table)")
    ax2.legend(fontsize=8)

    _save(fig, "08_position_utilisation.png")


def chart_return_distribution(pnl_metrics: dict, top_n: int = 12):
    """Return distribution histograms with skewness/kurtosis annotations."""
    if not HAS_MPL or not pnl_metrics:
        return
    # Pick products with most data
    sorted_prods = sorted(pnl_metrics.keys(),
                          key=lambda p: pnl_metrics[p]["ticks"], reverse=True)
    prods = sorted_prods[:top_n]
    ncols = 4
    nrows = math.ceil(len(prods) / ncols)
    fig, axes = plt.subplots(nrows, ncols, figsize=(5*ncols, 3.5*nrows), squeeze=False)
    axes = axes.flatten()
    fig.suptitle("Return Distribution per Product\n(skew > 0 = fat right tail; kurt > 0 = leptokurtic)",
                 fontsize=12, fontweight="bold")

    for i, prod in enumerate(prods):
        ax   = axes[i]
        rets = pnl_metrics[prod]["ret_series"]
        col  = GROUP_COLORS.get(product_group(prod), "steelblue")
        
        if HAS_MPL and len(rets) > 5:
            arr = np.array(rets)
            ax.hist(arr, bins=40, color=col, alpha=0.75, edgecolor="white", lw=0.3)
            ax.axvline(0, color="black", lw=0.9, ls="--")
            mu = float(np.mean(arr)); sig = float(np.std(arr))
            
            # FIX 2: Only overlay normal distribution if there is actual variance
            if sig > 1e-9:
                x_range = np.linspace(mu - 4*sig, mu + 4*sig, 200)
                n_scale = len(rets) * (x_range[1] - x_range[0])
                import scipy.stats as ss
                ax.plot(x_range, ss.norm.pdf(x_range, mu, sig) * n_scale,
                        color="red", lw=1.0, ls="--", label="Normal fit")
        
        # This formatting needs to stay outside the if block!
        skew = pnl_metrics[prod]["skewness"]
        kurt = pnl_metrics[prod]["kurtosis"]
        ax.set_title(
            f"{short(prod)}\nskew={skew:+.2f}  kurt={kurt:+.2f}",
            fontsize=7, color=col
        )
        if ax.get_legend_handles_labels()[0]:
            ax.legend(fontsize=5)
        ax.set_xlabel("Δ PnL per tick", fontsize=6)

    for j in range(len(prods), len(axes)):
        axes[j].set_visible(False)

    _save(fig, "09_return_distributions.png")


def chart_portfolio_risk(port: dict, pnl_metrics: dict):
    """Portfolio-level cumulative PnL + rolling Sharpe."""
    if not HAS_MPL or not port or not port.get("port_ret_series"):
        return
    rets = port["port_ret_series"]
    cum  = [sum(rets[:i+1]) for i in range(len(rets))]
    roll = _rolling_sharpe(rets, window=min(200, len(rets)//4 or 50))

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 8), sharex=True)
    fig.suptitle(
        f"Portfolio Summary\n"
        f"Sharpe={port['portfolio_sharpe']:.3f}  "
        f"Sortino={port['portfolio_sortino']:.3f}  "
        f"Calmar={port['portfolio_calmar']:.3f}  "
        f"PnL={port['portfolio_net_pnl']:+,.0f}",
        fontsize=12, fontweight="bold"
    )

    ax1.plot(cum, lw=0.8, color="steelblue")
    ax1.fill_between(range(len(cum)), cum, 0,
                     where=[c >= 0 for c in cum], alpha=0.25, color="green")
    ax1.fill_between(range(len(cum)), cum, 0,
                     where=[c < 0 for c in cum],  alpha=0.25, color="red")
    ax1.axhline(0, color="black", lw=0.8, ls="--")
    ax1.set_ylabel(f"Cumulative PnL ({CURRENCY})")
    ax1.set_title("Portfolio Cumulative PnL (all products summed)")

    ax2.plot(roll, lw=0.7, color="purple", alpha=0.85)
    ax2.fill_between(range(len(roll)), roll, 0,
                     where=[v >= 0 for v in roll], alpha=0.2, color="green")
    ax2.fill_between(range(len(roll)), roll, 0,
                     where=[v < 0 for v in roll],  alpha=0.2, color="red")
    ax2.axhline(0,   color="black", lw=0.8, ls="--")
    ax2.axhline(0.5, color="green", lw=0.8, ls=":")
    ax2.set_ylabel("Rolling Sharpe"); ax2.set_xlabel("Tick")
    ax2.set_title("Portfolio Rolling Sharpe (window=200 ticks)")

    _save(fig, "10_portfolio_risk.png")


def chart_spread_analysis(spread_data: dict):
    """Spread bar chart grouped by product group."""
    if not HAS_MPL or not spread_data:
        return
    # Sort by group then spread
    prods  = sorted(spread_data.keys(),
                    key=lambda p: (product_group(p), spread_data[p]["mean"]))
    means  = [spread_data[p]["mean"] for p in prods]
    colors = [GROUP_COLORS.get(product_group(p), "#999") for p in prods]

    fig, ax = plt.subplots(figsize=(max(14, len(prods)*0.45), 7))
    ax.bar(range(len(prods)), means, color=colors, alpha=0.85)
    ax.set_xticks(range(len(prods)))
    ax.set_xticklabels([short(p) for p in prods],
                       rotation=45, ha="right", fontsize=6.5)
    ax.set_ylabel("Mean Bid-Ask Spread (XIRECS)")
    ax.set_title("Spread by Product (grouped by category)\n"
                 "Lower spread = cheaper to trade = better for MM/scalp",
                 fontsize=11, fontweight="bold")

    from matplotlib.patches import Patch
    patches = [Patch(facecolor=c, label=g) for g, c in GROUP_COLORS.items()
               if any(product_group(p) == g for p in prods)]
    ax.legend(handles=patches, fontsize=7, ncol=5)

    _save(fig, "11_spread_analysis.png")


def chart_correlation_heatmap(port: dict):
    """Pairwise product correlation heatmap."""
    if not HAS_MPL or not port.get("top_correlations"):
        return
    # Extract unique products from top pairs
    seen = set()
    for a, b, _ in port["top_correlations"]:
        seen.add(a); seen.add(b)
    prods = sorted(seen)
    if len(prods) < 3:
        return

    fig, ax = plt.subplots(figsize=(max(8, len(prods)*0.5), max(7, len(prods)*0.5)))
    fig.suptitle("Pairwise Return Correlation\n(high positive = diversification benefit lost)",
                 fontsize=11, fontweight="bold")

    corr_dict = {(a, b): c for a, b, c in port["top_correlations"]}
    mat = np.zeros((len(prods), len(prods)))
    for i, p in enumerate(prods):
        mat[i, i] = 1.0
        for j, q in enumerate(prods):
            if i != j:
                mat[i, j] = corr_dict.get((p, q), corr_dict.get((q, p), 0.0))

    im = ax.imshow(mat, cmap="RdYlGn", vmin=-1, vmax=1, aspect="auto")
    ax.set_xticks(range(len(prods)))
    ax.set_xticklabels([short(p) for p in prods], rotation=45, ha="right", fontsize=7)
    ax.set_yticks(range(len(prods)))
    ax.set_yticklabels([short(p) for p in prods], fontsize=7)
    for i in range(len(prods)):
        for j in range(len(prods)):
            ax.text(j, i, f"{mat[i,j]:.2f}", ha="center", va="center", fontsize=6,
                    color="black" if abs(mat[i,j]) < 0.6 else "white")
    plt.colorbar(im, ax=ax, fraction=0.03)

    _save(fig, "12_correlation_heatmap.png")


# ═══════════════════════════════════════════════════════════════════════════
#  PRINT REPORTS
# ═══════════════════════════════════════════════════════════════════════════

def print_log_report(activities, trades, pnl_m, spread_a,
                     acf_data, util, cherry_rows, group_attr, port,
                     exec_diag: dict):
    SEP = "═" * 72
    print(f"\n{SEP}")
    print(f"  IMC Prosperity 4 — Round 5 Log Report  ({CURRENCY})")
    print(SEP)
    print(f"  Activity rows : {len(activities):,}")
    print(f"  Trade rows    : {len(trades):,}")
    print(f"  Products found: {len(pnl_m)}")
    print()

    # Portfolio summary
    print("── PORTFOLIO SUMMARY ────────────────────────────────────────────────")
    if port:
        print(f"  Total PnL      : {port['portfolio_net_pnl']:>+12,.0f}  {CURRENCY}")
        print(f"  Portfolio Sharpe: {port['portfolio_sharpe']:>+10.4f}")
        print(f"  Portfolio Sortino:{port['portfolio_sortino']:>+10.4f}")
        print(f"  Portfolio Calmar: {port['portfolio_calmar']:>+10.4f}")
        print(f"  Portfolio MaxDD : {port['portfolio_max_dd']:>12,.0f}  {CURRENCY}")
        print(f"  Portfolio WinRate:{port['portfolio_win_rate']*100:>10.1f} %")
        print(f"  # Products      : {port['n_products']}")
    print()

    # Group attribution
    print("── GROUP ATTRIBUTION ────────────────────────────────────────────────")
    sorted_g = sorted(group_attr.items(), key=lambda x: x[1]["net_pnl"], reverse=True)
    for gname, g in sorted_g:
        bar = ("▓" * min(40, max(0, int(g["net_pnl"]/500)))) if g["net_pnl"] > 0 else \
              ("░" * min(40, max(0, int(-g["net_pnl"]/500))))
        print(f"  {gname:<18}  {g['net_pnl']:>+10,.0f}  Sharpe={g['sharpe']:+.3f}  "
              f"best={short(g['best_product'])}  {bar}")
    print()

    # Cherry-pick table
    print("── CHERRY-PICK RANKING (top 20) ─────────────────────────────────────")
    print(f"  {'Product':<42} {'Score':>6} {'PnL':>10} {'Sharpe':>8} "
          f"{'Sortino':>8} {'WinRate':>8}  Verdict")
    print("  " + "─" * 105)
    for r in cherry_rows[:20]:
        print(f"  {r['product']:<42} {r['cherry_score']:>6.1f} "
              f"{r['net_pnl']:>+10,.0f} {r['sharpe']:>+8.3f} "
              f"{r['sortino']:>+8.3f} {r['win_rate']*100:>7.1f}%  "
              f"{r['verdict']}")
    print()

    # Regime breakdown
    for regime in ["MEAN_REVERT", "TRENDING", "RANDOM_WALK", "UNKNOWN"]:
        prods = [r["product"] for r in cherry_rows if r["regime"] == regime]
        if prods:
            print(f"  {regime}: {', '.join(short(p) for p in prods)}")
    print()

    # ── Execution diagnosis (new) ──────────────────────────────────────────
    print("── EXECUTION DIAGNOSIS ──────────────────────────────────────────────")
    state_counts = defaultdict(int)
    for d in exec_diag.values():
        state_counts[d["state"]] += 1
    print(f"  NEVER_ORDERED  : {state_counts['NEVER_ORDERED']:>3}  "
          "(algo never sent an order — check ALL_SYMBOLS / order logic)")
    print(f"  ORDERS_REJECTED: {state_counts['ORDERS_REJECTED']:>3}  "
          "(market active but your orders rejected — check position-limit arithmetic)")
    print(f"  FILLED_FLAT    : {state_counts['FILLED_FLAT']:>3}  "
          "(orders filled but zero edge — check fair value vs spread)")
    print(f"  ACTIVE         : {state_counts['ACTIVE']:>3}  "
          "(trading and generating non-zero PnL)")
    print()
    for state in ["ORDERS_REJECTED", "FILLED_FLAT"]:
        prods_in_state = [(p, d) for p, d in exec_diag.items() if d["state"] == state]
        if prods_in_state:
            print(f"  {state} products:")
            for prod, d in sorted(prods_in_state):
                print(f"    {prod:<42}  {d['diagnosis']}")
            print()

    # ── Directional bias (new) — only capped + losing products ────────────
    capped_losing = [
        (p, u) for p, u in util.items()
        if u["utilisation"] > 80 and pnl_m.get(p, {}).get("net_pnl", 0) < 0
        and u.get("cap_diagnosis")
    ]
    if capped_losing:
        print("── DIRECTIONAL BIAS (capped + losing) ───────────────────────────────")
        print(f"  {'Product':<42} {'Util%':>6} {'Dom':>8} {'BiasCrr':>8}  Root Cause")
        print("  " + "─" * 110)
        for prod, u in sorted(capped_losing,
                               key=lambda x: x[1]["utilisation"], reverse=True):
            diag_short = u["cap_diagnosis"][:65] + "…" if len(u["cap_diagnosis"]) > 65 else u["cap_diagnosis"]
            print(f"  {prod:<42} {u['utilisation']:>5.0f}% {u['dominant_side']:>8} "
                  f"{u['bias_pnl_corr']:>+8.3f}  {diag_short}")
        print()


def print_risk_report(cherry_rows: list, port: dict, pnl_m: dict):
    """Teammate-facing risk report: all Sharpe/risk metrics."""
    SEP = "═" * 72
    print(f"\n{SEP}")
    print("  IMC Prosperity 4 — Round 5 Risk Report  (for risk-focused teammate)")
    print(SEP)
    print()

    if port:
        print("── PORTFOLIO RISK METRICS ───────────────────────────────────────────")
        print(f"  Sharpe Ratio       : {port['portfolio_sharpe']:+.4f}")
        print(f"    Interpretation   : {'Good (> 0.5)' if port['portfolio_sharpe'] > 0.5 else 'Caution (0–0.5)' if port['portfolio_sharpe'] > 0 else 'Negative — strategy losing on risk-adj basis'}")
        print(f"  Sortino Ratio      : {port['portfolio_sortino']:+.4f}")
        print(f"    Interpretation   : {'Good (> 0.7)' if port['portfolio_sortino'] > 0.7 else 'Acceptable (0–0.7)' if port['portfolio_sortino'] > 0 else 'Negative downside risk outweighs returns'}")
        print(f"  Calmar Ratio       : {port['portfolio_calmar']:+.4f}")
        print(f"    Interpretation   : {'Good (> 1)' if port['portfolio_calmar'] > 1 else 'Marginal (0–1)' if port['portfolio_calmar'] > 0 else 'Loss exceeds max drawdown recovery'}")
        print(f"  Max Drawdown       : {port['portfolio_max_dd']:>12,.0f} {CURRENCY}")
        print(f"  Win Rate           : {port['portfolio_win_rate']*100:.1f}%  "
              f"({'above random' if port['portfolio_win_rate'] > 0.5 else 'below 50% — check strategy'})")
        print(f"  Profit Factor      : {port['portfolio_pf']:.3f}  "
              f"({'good (>1.5)' if port['portfolio_pf'] > 1.5 else 'marginal' if port['portfolio_pf'] > 1 else 'LOSING — gross losses > gross gains'})")
        print()

    print("── PER-PRODUCT RISK TABLE ───────────────────────────────────────────")
    print(f"  {'Product':<42} {'Sharpe':>8} {'Sortino':>8} {'Calmar':>8} "
          f"{'MaxDD':>10} {'WinRate':>8} {'PF':>6} {'Skew':>7} {'Kurt':>7}")
    print("  " + "─" * 115)
    for r in cherry_rows:
        calmar_str = f"{min(r['calmar'], 99):>8.3f}" if r["calmar"] != float("inf") else "    ∞   "
        pf_str     = f"{min(r['profit_factor'], 99):>6.3f}" if r["profit_factor"] != float("inf") else "   ∞  "
        print(f"  {r['product']:<42} "
              f"{r['sharpe']:>+8.3f} "
              f"{min(r['sortino'], 99):>+8.3f} "
              f"{calmar_str} "
              f"{r['max_drawdown']:>10,.0f} "
              f"{r['win_rate']*100:>7.1f}% "
              f"{pf_str} "
              f"{r['skewness']:>+7.3f} "
              f"{r['kurtosis']:>+7.3f}")
    print()

    if port and port.get("top_correlations"):
        print("── TOP CORRELATED PAIRS (diversification risk) ─────────────────────")
        print(f"  {'Product A':<38} {'Product B':<38} {'Corr':>8}")
        print("  " + "─" * 90)
        for a, b, c in port["top_correlations"][:10]:
            flag = "  ⚠️  high" if abs(c) > 0.7 else ""
            print(f"  {a:<38} {b:<38} {c:>+8.3f}{flag}")
        print()

    print("── RISK WARNINGS ────────────────────────────────────────────────────")
    warns = 0
    for r in cherry_rows:
        if r["sharpe"] < -0.3:
            print(f"  ❌ {r['product']}: Sharpe={r['sharpe']:+.3f} — consistently losing on risk-adj basis → DROP")
            warns += 1
        if r["max_drawdown"] > abs(r["net_pnl"]) * 3 and r["max_drawdown"] > 100:
            print(f"  ⚠️  {r['product']}: MaxDD={r['max_drawdown']:,.0f} >> PnL={r['net_pnl']:+,.0f} — erratic, high risk")
            warns += 1
        if r["win_rate"] < 0.35 and r["net_pnl"] < 0:
            print(f"  ⚠️  {r['product']}: WinRate={r['win_rate']*100:.0f}% + negative PnL — strategy wrong side")
            warns += 1
    if warns == 0:
        print("  ✅ No major risk flags detected.")
    print()


# ═══════════════════════════════════════════════════════════════════════════
#  CLAUDE STRATEGY BRIEF
# ═══════════════════════════════════════════════════════════════════════════

def write_claude_brief(pnl_m, acf_data, spread_data, cherry_rows,
                       group_attr, port, util, exec_diag: dict,
                       output_path: str):
    H = "═" * 72
    L  = [H, "  CLAUDE STRATEGY BRIEF — IMC Prosperity 4 Round 5", H,
          "  Paste this file into Claude along with the PNG charts.",
          "  Claude: read this first, then use charts for confirmation.", ""]

    # 1. Portfolio snapshot
    L += ["── 1. PORTFOLIO SNAPSHOT ─────────────────────────────────────────────"]
    if port:
        L += [
            f"  Total PnL       : {port['portfolio_net_pnl']:+,.0f} {CURRENCY}",
            f"  Sharpe Ratio    : {port['portfolio_sharpe']:+.4f}",
            f"  Sortino Ratio   : {port['portfolio_sortino']:+.4f}",
            f"  Calmar Ratio    : {port['portfolio_calmar']:+.4f}",
            f"  Max Drawdown    : {port['portfolio_max_dd']:,.0f} {CURRENCY}",
            f"  Win Rate        : {port['portfolio_win_rate']*100:.1f}%",
            f"  # Products      : {port['n_products']}",
        ]
    L.append("")

    # 2. Group attribution
    L += ["── 2. GROUP ATTRIBUTION (sorted best → worst) ────────────────────────"]
    sorted_g = sorted(group_attr.items(), key=lambda x: x[1]["net_pnl"], reverse=True)
    for gname, g in sorted_g:
        verdict = "✅ KEEP" if g["net_pnl"] > 0 else "❌ REVIEW"
        L.append(f"  {gname:<18}  PnL={g['net_pnl']:>+10,.0f}  "
                 f"Sharpe={g['sharpe']:+.3f}  {verdict}")
    L.append("")

    # 3. Cherry-pick verdict table
    L += ["── 3. CHERRY-PICK TABLE (all traded products) ────────────────────────"]
    L.append(f"  {'Product':<42} {'PnL':>10} {'Sharpe':>8} {'WR%':>6} "
             f"{'Regime':>12}  Verdict")
    L.append("  " + "─" * 95)
    for r in cherry_rows:
        L.append(f"  {r['product']:<42} {r['net_pnl']:>+10,.0f} "
                 f"{r['sharpe']:>+8.3f} {r['win_rate']*100:>5.1f}% "
                 f"{r['regime']:>12}  {r['verdict']}")
    L.append("")

    # 4. Drop list
    drops = [r["product"] for r in cherry_rows if "DROP" in r["verdict"]]
    if drops:
        L += ["── 4. PRODUCTS TO DROP (losing on risk-adj basis) ────────────────────",
              *[f"  - {p}" for p in drops], ""]

    # 5. Keep & expand list
    keeps = [r["product"] for r in cherry_rows if "🟢" in r["verdict"]]
    if keeps:
        L += ["── 5. PRODUCTS TO KEEP / EXPAND ─────────────────────────────────────",
              *[f"  + {p}" for p in keeps], ""]

    # 6. Execution diagnosis
    L += ["── 6. EXECUTION DIAGNOSIS ───────────────────────────────────────────"]
    state_counts = defaultdict(int)
    for d in exec_diag.values():
        state_counts[d["state"]] += 1
    L += [
        f"  NEVER_ORDERED  : {state_counts['NEVER_ORDERED']:>3}  products — algo not generating orders",
        f"  ORDERS_REJECTED: {state_counts['ORDERS_REJECTED']:>3}  products — orders sent but never fill",
        f"  FILLED_FLAT    : {state_counts['FILLED_FLAT']:>3}  products — fills but zero edge",
        f"  ACTIVE         : {state_counts['ACTIVE']:>3}  products — trading normally",
        "",
    ]
    for state in ["ORDERS_REJECTED", "FILLED_FLAT"]:
        prods_in = [(p, d) for p, d in exec_diag.items() if d["state"] == state]
        if prods_in:
            L.append(f"  {state}:")
            for prod, d in sorted(prods_in):
                L.append(f"    {prod:<42}  {d['diagnosis']}")
            L.append("")

    # 6b. Directional bias
    capped_losing = [
        (p, u) for p, u in util.items()
        if u["utilisation"] > 80 and pnl_m.get(p, {}).get("net_pnl", 0) < 0
        and u.get("cap_diagnosis")
    ]
    if capped_losing:
        L += ["── 6b. DIRECTIONAL BIAS (capped + losing) ────────────────────────────"]
        L.append(f"  {'Product':<42} {'Dom':>8} {'BiasCrr':>8}  Root Cause")
        L.append("  " + "─" * 100)
        for prod, u in sorted(capped_losing,
                               key=lambda x: x[1]["utilisation"], reverse=True):
            L.append(f"  {prod:<42} {u['dominant_side']:>8} "
                     f"{u['bias_pnl_corr']:>+8.3f}  {u['cap_diagnosis']}")
        L.append("")

    # 7. Regime breakdown
    L += ["── 7. REGIME BREAKDOWN ──────────────────────────────────────────────"]
    for regime in ["MEAN_REVERT", "TRENDING", "RANDOM_WALK"]:
        prods = [r["product"] for r in cherry_rows if r["regime"] == regime]
        if prods:
            L.append(f"  {regime:15s} ({len(prods):2d}): {', '.join(short(p) for p in prods)}")
    L.append("")

    # 8. ACF signals (top mean-reverting)
    L += ["── 8. TOP MEAN-REVERSION SIGNALS ────────────────────────────────────"]
    L.append(f"  {'Product':<42} {'ACF1':>8} {'CI95':>8}  Regime")
    mr_prods = [(p, d) for p, d in acf_data.items() if d["mean_reversion"]]
    mr_prods.sort(key=lambda x: x[1]["acf1"])
    for prod, d in mr_prods[:10]:
        L.append(f"  {prod:<42} {d['acf1']:>+8.4f} {d['ci95']:>8.4f}  MEAN_REVERT ← scalp this")
    L.append("")

    # 9. Code change recommendations
    L += ["── 9. RECOMMENDED CODE CHANGES ──────────────────────────────────────"]
    L.append("  Based on this report, tell Claude:")
    for r in cherry_rows:
        if "DROP" in r["verdict"]:
            L.append(f"  • Remove {r['product']} from ALL_SYMBOLS in trader.py")
        elif "🟢" in r["verdict"] and r["regime"] == "MEAN_REVERT":
            thresh_guess = 2.0  # placeholder; analyzer gives exact via EMA analysis
            L.append(f"  • {r['product']}: EMA mean-reversion entry threshold ≈ look at chart 05")
        elif "🟢" in r["verdict"]:
            L.append(f"  • {r['product']}: Keep MM logic, score={r['cherry_score']:.1f}")
    L.append("")

    # 10. Files
    L += ["── 10. FILES IN THIS REPORT ─────────────────────────────────────────",
          *[f"  {f}" for f in sorted(os.listdir(OUTPUT_DIR))], "", H]

    text = "\n".join(L)
    with open(output_path, "w") as f:
        f.write(text)
    print(f"\n  ✓ CLAUDE_STRATEGY_BRIEF.txt")
    print(text)


# ═══════════════════════════════════════════════════════════════════════════
#  COMPARE MODE
# ═══════════════════════════════════════════════════════════════════════════

def run_compare_mode(path_a: str, path_b: str, top_n: int = 30):
    """Diff two log files: show per-product PnL delta, Sharpe delta."""
    print("\n── COMPARE MODE ──────────────────────────────────────────────────────")
    acts_a, _, _ = load_and_parse(path_a)
    acts_b, _, _ = load_and_parse(path_b)

    pnl_a = compute_pnl_metrics(acts_a)
    pnl_b = compute_pnl_metrics(acts_b)

    all_prods = sorted(set(pnl_a.keys()) | set(pnl_b.keys()))

    rows = []
    for prod in all_prods:
        ma = pnl_a.get(prod, {})
        mb = pnl_b.get(prod, {})
        pa  = ma.get("net_pnl", 0)
        pb  = mb.get("net_pnl", 0)
        sa  = ma.get("sharpe",  0)
        sb  = mb.get("sharpe",  0)
        rows.append({
            "product":   prod,
            "pnl_a":     pa,
            "pnl_b":     pb,
            "delta_pnl": pb - pa,
            "sharpe_a":  sa,
            "sharpe_b":  sb,
            "delta_sharpe": sb - sa,
        })
    rows.sort(key=lambda x: x["delta_pnl"], reverse=True)

    total_a = sum(r["pnl_a"] for r in rows)
    total_b = sum(r["pnl_b"] for r in rows)
    SEP = "═" * 72
    print(f"\n{SEP}")
    print("  COMPARISON: A (baseline) vs B (new)")
    print(f"  A total PnL: {total_a:>+12,.0f}  {CURRENCY}")
    print(f"  B total PnL: {total_b:>+12,.0f}  {CURRENCY}")
    print(f"  Δ PnL      : {total_b-total_a:>+12,.0f}  {CURRENCY}  "
          f"({'IMPROVED' if total_b > total_a else 'REGRESSED'})")
    print(SEP)
    print(f"\n  {'Product':<42} {'PnL A':>10} {'PnL B':>10} {'Δ PnL':>10} "
          f"{'Sharpe A':>9} {'Sharpe B':>9} {'Δ Sharpe':>9}  Verdict")
    print("  " + "─" * 112)
    for r in rows[:top_n]:
        dpnl  = r["delta_pnl"]
        dshar = r["delta_sharpe"]
        if dpnl > 0 and dshar > 0:
            verdict = "🟢 both improved"
        elif dpnl > 0 and dshar <= 0:
            verdict = "🟡 PnL up, Sharpe down (more risk?)"
        elif dpnl <= 0 and dshar > 0:
            verdict = "🟡 Sharpe up, PnL down"
        else:
            verdict = "🔴 both worsened"
        print(f"  {r['product']:<42} {r['pnl_a']:>+10,.0f} {r['pnl_b']:>+10,.0f} "
              f"{dpnl:>+10,.0f} {r['sharpe_a']:>+9.3f} {r['sharpe_b']:>+9.3f} "
              f"{dshar:>+9.3f}  {verdict}")

    # Chart comparison
    if HAS_MPL:
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        delta_pnls = [r["delta_pnl"]   for r in rows[:top_n]]
        labels     = [short(r["product"]) for r in rows[:top_n]]
        colors     = [("#43A047" if d >= 0 else "#E53935") for d in delta_pnls]
        fig, ax = plt.subplots(figsize=(14, max(7, len(rows[:top_n])*0.38)))
        ax.barh(labels, delta_pnls, color=colors, alpha=0.85)
        ax.axvline(0, color="black", lw=0.8)
        ax.set_xlabel(f"Δ PnL  ({CURRENCY})  [B - A]")
        ax.set_title("PnL Delta: New vs Baseline\n(green = improved)", fontweight="bold")
        _save(fig, "compare_pnl_delta.png")
        print(f"\n  Chart → {OUTPUT_DIR}/compare_pnl_delta.png")


# ═══════════════════════════════════════════════════════════════════════════
#  MAIN ENTRY POINTS
# ═══════════════════════════════════════════════════════════════════════════

def run_log_mode(filepath: str, top_n: int = 20):
    t0 = time.time()
    activities, trades, sandbox = load_and_parse(filepath)

    products_found = sorted({r["product"] for r in activities})
    print(f"  Activity rows : {len(activities):,}")
    print(f"  Trade rows    : {len(trades):,}")
    print(f"  Products      : {len(products_found)}")

    if not activities:
        print("\n⚠️  No activity data found — check log format.")
        sys.exit(1)

    print("\nComputing analytics …")
    pnl_m      = compute_pnl_metrics(activities)
    spread_a   = compute_spread_analysis(activities)
    exec_diag  = compute_execution_diagnosis(activities, trades, pnl_m)
    acf_data   = compute_acf_analysis(activities)
    util       = compute_position_utilisation(activities)
    cherry     = compute_cherry_pick_score(pnl_m, acf_data, spread_a)
    group_attr = compute_group_attribution(pnl_m)
    port       = compute_portfolio_risk(pnl_m)
    rolling_sh = compute_rolling_sharpe_series(pnl_m)

    print_log_report(activities, trades, pnl_m, spread_a,
                     acf_data, util, cherry, group_attr, port, exec_diag)

    if HAS_MPL:
        print(f"\nGenerating charts → ./{OUTPUT_DIR}/")
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        chart_pnl_curves(pnl_m, activities)
        chart_risk_dashboard(cherry, top_n=min(top_n, len(cherry)))
        chart_cherry_pick_ranking(cherry)
        chart_group_attribution(group_attr)
        chart_return_acf(acf_data, top_n=top_n)
        chart_rolling_sharpe(rolling_sh, top_n=min(top_n, len(rolling_sh)))
        chart_drawdown_curves(pnl_m, top_n=min(15, len(pnl_m)))
        chart_position_utilisation(util)
        chart_return_distribution(pnl_m, top_n=12)
        chart_portfolio_risk(port, pnl_m)
        chart_spread_analysis(spread_a)
        chart_correlation_heatmap(port)
        chart_execution_diagnosis(exec_diag)
        chart_directional_bias(util, pnl_m)
        print(f"  All charts saved in ./{OUTPUT_DIR}/")
    else:
        print("\n[SKIP] pip install matplotlib numpy to generate charts")

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # JSON summary
    summary = {
        "products":        products_found,
        "portfolio_sharpe": port.get("portfolio_sharpe", 0) if port else 0,
        "portfolio_pnl":   port.get("portfolio_net_pnl", 0) if port else 0,
        "cherry_ranking":  [
            {k: ("Infinity" if v == float("inf") else "-Infinity" if v == float("-inf") else v) 
             for k, v in r.items()
             if k not in ("pnl_series", "ret_series")}
            for r in cherry
        ],
        "group_attribution": {
            g: {k: ("Infinity" if v == float("inf") else "-Infinity" if v == float("-inf") else v) 
                for k, v in d.items() if k != "products"}
            for g, d in group_attr.items()
        },
    }
    jp = os.path.join(OUTPUT_DIR, "r5_summary.json")
    with open(jp, "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"\n  ✓ r5_summary.json")

    brief_path = os.path.join(OUTPUT_DIR, "CLAUDE_STRATEGY_BRIEF.txt")
    write_claude_brief(pnl_m, acf_data, spread_a, cherry,
                       group_attr, port, util, exec_diag, brief_path)

    print(f"\n  Elapsed: {time.time()-t0:.1f}s")


def run_risk_mode(filepath: str, top_n: int = 20):
    """Risk-dashboard mode: focused on all Sharpe/Sortino/Calmar metrics."""
    t0 = time.time()
    activities, trades, _ = load_and_parse(filepath)

    if not activities:
        print("\n⚠️  No activity data found.")
        sys.exit(1)

    print("\nComputing risk metrics …")
    pnl_m    = compute_pnl_metrics(activities)
    spread_a = compute_spread_analysis(activities)
    acf_data = compute_acf_analysis(activities)
    cherry   = compute_cherry_pick_score(pnl_m, acf_data, spread_a)
    port     = compute_portfolio_risk(pnl_m)
    rolling  = compute_rolling_sharpe_series(pnl_m)

    print_risk_report(cherry, port, pnl_m)

    if HAS_MPL:
        print(f"\nGenerating risk charts → ./{OUTPUT_DIR}/")
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        chart_risk_dashboard(cherry, top_n=min(top_n, len(cherry)))
        chart_rolling_sharpe(rolling, top_n=min(top_n, len(rolling)))
        chart_drawdown_curves(pnl_m)
        chart_portfolio_risk(port, pnl_m)
        chart_return_distribution(pnl_m)
        chart_correlation_heatmap(port)

    print(f"\n  Elapsed: {time.time()-t0:.1f}s")


# ═══════════════════════════════════════════════════════════════════════════
#  CLI
# ═══════════════════════════════════════════════════════════════════════════

def usage():
    print(__doc__)
    print("Usage:")
    print("  python r5_log_analyzer.py  log    <result.log>  [--out DIR] [--top N]")
    print("  python r5_log_analyzer.py  risk   <result.log>  [--out DIR] [--top N]")
    print("  python r5_log_analyzer.py  compare <log_A> <log_B>  [--out DIR]")


def main():
    if len(sys.argv) < 2:
        usage(); sys.exit(0)

    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("mode",    nargs="?", default="")
    ap.add_argument("files",   nargs="*")
    ap.add_argument("--out",   default="r5_charts")
    ap.add_argument("--top",   type=int, default=20)
    ap.add_argument("--horizon", type=int, default=5)
    args = ap.parse_args()

    global OUTPUT_DIR
    OUTPUT_DIR = args.out

    mode = args.mode.lower()

    if mode == "log":
        if not args.files:
            print("⚠️  Provide a log file:  python r5_log_analyzer.py log <file.log>")
            sys.exit(1)
        run_log_mode(args.files[0], top_n=args.top)

    elif mode == "risk":
        if not args.files:
            print("⚠️  Provide a log file:  python r5_log_analyzer.py risk <file.log>")
            sys.exit(1)
        run_risk_mode(args.files[0], top_n=args.top)

    elif mode == "compare":
        if len(args.files) < 2:
            print("⚠️  Provide two log files:  python r5_log_analyzer.py compare A.log B.log")
            sys.exit(1)
        run_compare_mode(args.files[0], args.files[1], top_n=args.top)

    else:
        usage(); sys.exit(1)


if __name__ == "__main__":
    main()
