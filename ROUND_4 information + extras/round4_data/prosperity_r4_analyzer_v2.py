#!/usr/bin/env python3
"""
IMC Prosperity 4 – Comprehensive Round Analysis Tool
=====================================================
Analyses historical price & trade CSVs to produce:
  • Delta-1 overview + EMA mean-reversion thresholds
  • Volatility smile fitting (quadratic, per-tick)
  • Per-strike price deviation from smile fair value
  • VEV option return autocorrelations (scalping signals)
  • Delta surface across strikes / days
  • Mark trader flow heatmaps, timing, and forward-return signals
  • Spread & liquidity summary
  • Plain-English parameter report for the trader.py file

QUICK START
-----------
  pip install matplotlib numpy pandas scipy

  # Round 4 – three days of data:
  python prosperity_analyzer.py \\
      --prices prices_round_4_day_1.csv prices_round_4_day_2.csv prices_round_4_day_3.csv \\
      --trades trades_round_4_day_1.csv trades_round_4_day_2.csv trades_round_4_day_3.csv \\
      --round 4 --output ./r4_output

  # Round 5 (TTE 1 day):
  python prosperity_analyzer.py \\
      --prices prices_round_5_day_1.csv \\
      --trades trades_round_5_day_1.csv \\
      --round 5 --output ./r5_output

  # Prices only (skip mark analysis):
  python prosperity_analyzer.py \\
      --prices prices_round_4_day_1.csv \\
      --round 4 --no-marks --output ./r4_output

CSV FORMAT (IMC Prosperity 4)
------------------------------
  Prices:  day;timestamp;product;bid_price_1;bid_volume_1;...;mid_price;profit_and_loss
  Trades:  day;timestamp;buyer;seller;symbol;currency;price;quantity
  (Comma-separated files are also accepted automatically.)

CURRENCY: XIRECS (as per IMC Prosperity 4 competition)
"""

from __future__ import annotations

import argparse
import math
import os
import sys
import warnings
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
matplotlib.rcParams.update({
    "figure.dpi": 120,
    "font.size": 9,
    "axes.spines.top": False,
    "axes.spines.right": False,
})

# ════════════════════════════════════════════════════════════════════════════
#  CONSTANTS
# ════════════════════════════════════════════════════════════════════════════

CURRENCY = "XIRECS"          # IMC Prosperity 4 currency
PRODUCTS_DELTA1 = ["HYDROGEL_PACK", "VELVETFRUIT_EXTRACT"]
UNDERLYING = "VELVETFRUIT_EXTRACT"

STRIKES_MAP: dict[str, int] = {
    "VEV_4000": 4000, "VEV_4500": 4500, "VEV_5000": 5000,
    "VEV_5100": 5100, "VEV_5200": 5200, "VEV_5300": 5300,
    "VEV_5400": 5400, "VEV_5500": 5500, "VEV_6000": 6000,
    "VEV_6500": 6500,
}
TRADING_DAYS_PER_YEAR = 365

# Time-to-expiry (calendar days) per historical-data day, by round
TTE_PER_ROUND: dict[int, dict[int, int]] = {
    3: {0: 8, 1: 7, 2: 6},          # Round 3 historical days 0-2
    4: {1: 4, 2: 3, 3: 2},          # Round 4 historical days 1-3
    5: {1: 1, 2: 0},                 # Round 5 historical days 1-2
}

# ════════════════════════════════════════════════════════════════════════════
#  DATA LOADING
# ════════════════════════════════════════════════════════════════════════════

def _detect_sep(filepath: str) -> str:
    """Auto-detect CSV separator (semicolon or comma)."""
    with open(filepath) as f:
        first = f.readline()
    return "," if ("," in first and ";" not in first) else ";"


def load_prices(filepath: str, day: int | None = None) -> pd.DataFrame:
    """
    Load a Prosperity prices CSV.
    Required columns (after normalisation):
      day, timestamp, product, mid_price
    Optional: bid_price_1, ask_price_1 (for spread computation).
    """
    sep = _detect_sep(filepath)
    df = pd.read_csv(filepath, sep=sep)
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]

    if "timestamp" not in df.columns and "time" in df.columns:
        df = df.rename(columns={"time": "timestamp"})
    if "product" not in df.columns and "symbol" in df.columns:
        df = df.rename(columns={"symbol": "product"})

    if day is not None:
        df["day"] = day
    elif "day" not in df.columns:
        df["day"] = 1

    # Best-effort mid_price
    if "mid_price" not in df.columns:
        bp = next((c for c in df.columns if "bid" in c and "price" in c and "1" in c), None)
        ap = next((c for c in df.columns if "ask" in c and "price" in c and "1" in c), None)
        if bp and ap:
            df["mid_price"] = (df[bp] + df[ap]) / 2.0
        else:
            raise ValueError(f"Cannot find 'mid_price' column in {filepath}")

    df["product"] = df["product"].str.strip().str.upper()
    return df


def load_trades(filepath: str, day: int | None = None) -> pd.DataFrame:
    """
    Load a Prosperity trades CSV.
    Required columns: timestamp, buyer, seller, symbol (or product), price, quantity.
    """
    sep = _detect_sep(filepath)
    df = pd.read_csv(filepath, sep=sep)
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]

    if "symbol" not in df.columns and "product" in df.columns:
        df = df.rename(columns={"product": "symbol"})
    if "symbol" not in df.columns:
        raise ValueError(f"Cannot find 'symbol' or 'product' column in {filepath}")

    if day is not None:
        df["day"] = day
    elif "day" not in df.columns:
        df["day"] = 1

    for col in ("buyer", "seller"):
        if col in df.columns:
            df[col] = df[col].fillna("").astype(str).str.strip()
        else:
            df[col] = ""

    df["symbol"] = df["symbol"].str.strip().str.upper()
    return df


def load_many(filepaths: list[str], loader_fn, base_day: int = 1) -> pd.DataFrame:
    """Load and concatenate multiple CSV files."""
    frames = [loader_fn(fp, day=base_day + i) for i, fp in enumerate(filepaths)]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def mid_series(prices_df: pd.DataFrame, product: str) -> pd.DataFrame:
    """Return sorted (day, timestamp, mid_price) for one product."""
    mask = prices_df["product"] == product.upper()
    return (
        prices_df[mask][["day", "timestamp", "mid_price"]]
        .dropna(subset=["mid_price"])
        .sort_values(["day", "timestamp"])
        .reset_index(drop=True)
    )


def spread_series(prices_df: pd.DataFrame, product: str) -> pd.DataFrame:
    """Return bid-ask spread series for one product (requires bid/ask cols)."""
    mask = prices_df["product"] == product.upper()
    sub = prices_df[mask].copy()
    bp = next((c for c in sub.columns if "bid" in c and "price" in c and "1" in c), None)
    ap = next((c for c in sub.columns if "ask" in c and "price" in c and "1" in c), None)
    if bp and ap:
        sub["spread"] = sub[ap] - sub[bp]
        return sub[["day", "timestamp", "spread"]].dropna()
    return pd.DataFrame(columns=["day", "timestamp", "spread"])


# ════════════════════════════════════════════════════════════════════════════
#  BLACK-SCHOLES HELPERS
# ════════════════════════════════════════════════════════════════════════════

def _ncdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / 1.4142135623730951))


def bs_call(S: float, K: float, T: float, sigma: float) -> float:
    if T <= 1e-8 or sigma <= 1e-8:
        return max(0.0, S - K)
    sq = sigma * math.sqrt(T)
    d1 = (math.log(S / K) + 0.5 * sigma ** 2 * T) / sq
    return S * _ncdf(d1) - K * _ncdf(d1 - sq)


def bs_delta_call(S: float, K: float, T: float, sigma: float) -> float:
    if T <= 1e-8 or sigma <= 1e-8:
        return 1.0 if S > K else 0.0
    d1 = (math.log(S / K) + 0.5 * sigma ** 2 * T) / (sigma * math.sqrt(T))
    return _ncdf(d1)


def solve_iv(S: float, K: float, T: float, price: float,
             lo: float = 0.005, hi: float = 3.5, n: int = 80) -> float | None:
    """Binary-search for implied volatility. Returns None if no solution found."""
    intrinsic = max(0.0, S - K)
    if price < intrinsic + 0.05 or T <= 1e-8:
        return None
    for _ in range(n):
        mid = (lo + hi) * 0.5
        (lo if bs_call(S, K, T, mid) < price else hi).__class__  # dummy
        if bs_call(S, K, T, mid) < price:
            lo = mid
        else:
            hi = mid
    iv = (lo + hi) * 0.5
    return iv if 0.015 < iv < 3.0 else None


# ════════════════════════════════════════════════════════════════════════════
#  IV SURFACE BUILDER
# ════════════════════════════════════════════════════════════════════════════

def build_iv_surface(prices_df: pd.DataFrame, tte_map: dict[int, int]) -> pd.DataFrame:
    """
    For every (day, timestamp) with a valid VELVETFRUIT_EXTRACT mid-price,
    solve IV for each VEV strike and return a flat DataFrame with columns:
      day, timestamp, sym, K, S, T, iv, moneyness, market_mid
    """
    # Index the underlying mid by (day, timestamp)
    under = (
        prices_df[prices_df["product"] == UNDERLYING][["day", "timestamp", "mid_price"]]
        .rename(columns={"mid_price": "S"})
        .dropna()
    )

    rows: list[dict] = []
    for sym, K in STRIKES_MAP.items():
        opt = (
            prices_df[prices_df["product"] == sym][["day", "timestamp", "mid_price"]]
            .rename(columns={"mid_price": "market_mid"})
            .dropna()
        )
        merged = opt.merge(under, on=["day", "timestamp"], how="inner")

        for row in merged.itertuples(index=False):
            d = int(row.day)
            T = tte_map.get(d, 4) / TRADING_DAYS_PER_YEAR
            S, mkt = float(row.S), float(row.market_mid)
            if S <= 0 or mkt <= 0:
                continue
            iv = solve_iv(S, K, T, mkt)
            if iv is None:
                continue
            rows.append({
                "day": d,
                "timestamp": int(row.timestamp),
                "sym": sym,
                "K": K,
                "S": S,
                "T": T,
                "iv": iv,
                "moneyness": math.log(S / K),
                "market_mid": mkt,
            })

    return pd.DataFrame(rows)


def fit_smile_deviations(iv_df: pd.DataFrame) -> pd.DataFrame:
    """
    For each (day, timestamp), fit a quadratic smile IV = f(moneyness).
    Adds columns: fitted_iv, iv_deviation, smile_price, price_deviation.

    NOTE: Requires ≥3 strikes per tick for a valid fit.
    Ticks with fewer strikes are assigned NaN for fitted/deviation columns.
    """
    out_rows: list[dict] = []
    for (d, ts), grp in iv_df.groupby(["day", "timestamp"]):
        if len(grp) < 3:
            for row in grp.itertuples(index=False):
                out_rows.append({**row._asdict(),
                                  "fitted_iv": float("nan"),
                                  "iv_deviation": float("nan"),
                                  "smile_price": float("nan"),
                                  "price_deviation": float("nan")})
            continue

        m_arr = grp["moneyness"].values
        iv_arr = grp["iv"].values
        try:
            coeffs = np.polyfit(m_arr, iv_arr, 2)
        except np.linalg.LinAlgError:
            coeffs = np.array([0.0, 0.0, np.mean(iv_arr)])

        for row in grp.itertuples(index=False):
            fitted = float(np.polyval(coeffs, row.moneyness))
            fitted = max(0.01, fitted)
            sp = bs_call(row.S, row.K, row.T, fitted)
            out_rows.append({
                **row._asdict(),
                "fitted_iv": fitted,
                "iv_deviation": row.iv - fitted,
                "smile_price": sp,
                "price_deviation": row.market_mid - sp,
            })

    return pd.DataFrame(out_rows)


# ════════════════════════════════════════════════════════════════════════════
#  MARK SIGNAL ANALYSIS
# ════════════════════════════════════════════════════════════════════════════

def compute_mark_forward_returns(
    trades_df: pd.DataFrame,
    prices_df: pd.DataFrame,
    forward_ticks: int = 5,
    products: list[str] | None = None,
) -> pd.DataFrame:
    """
    For each Mark trade, look up the mid-price forward_ticks later and
    compute a signed forward return in basis points.

    Convention:
      If Mark BUYS and price goes UP  → positive return (Mark was informed)
      If Mark SELLS and price goes UP → negative return (Mark was informed selling)
      We negate sell-side returns so that positive t-stat always means
      "following this Mark is profitable."
    """
    if products is None:
        products = PRODUCTS_DELTA1

    all_rows: list[dict] = []

    for prod in products:
        mp = mid_series(prices_df, prod).reset_index(drop=True)
        # Build a fast timestamp → position-in-array lookup
        ts_index: dict[tuple[int, int], int] = {
            (int(r.day), int(r.timestamp)): i
            for i, r in mp.iterrows()
        }
        mid_arr = mp["mid_price"].values

        prod_trades = trades_df[trades_df["symbol"] == prod.upper()]
        for row in prod_trades.itertuples(index=False):
            key = (int(row.day), int(row.timestamp))
            idx = ts_index.get(key)
            if idx is None or idx + forward_ticks >= len(mid_arr):
                continue
            ref_price = float(row.price)
            fwd_mid = float(mid_arr[idx + forward_ticks])
            fwd_ret_bps = (fwd_mid - ref_price) / ref_price * 10_000

            for participant, side in [(row.buyer, "buy"), (row.seller, "sell")]:
                if not str(participant).startswith("Mark"):
                    continue
                # Seller profits when price goes DOWN, so flip sign for seller
                signed = fwd_ret_bps if side == "buy" else -fwd_ret_bps
                all_rows.append({
                    "product": prod,
                    "mark": participant,
                    "side": side,
                    "fwd_ret_bps": signed,
                    "price": ref_price,
                    "day": row.day,
                    "timestamp": row.timestamp,
                })

    if not all_rows:
        return pd.DataFrame()

    df = pd.DataFrame(all_rows)
    grouped = (
        df.groupby(["product", "mark", "side"])["fwd_ret_bps"]
        .agg(avg="mean", std="std", n="count")
        .reset_index()
    )
    grouped["t_stat"] = grouped.apply(
        lambda r: r["avg"] / (r["std"] / math.sqrt(max(r["n"], 1))) if r["std"] > 0 else 0.0,
        axis=1,
    )
    return grouped.sort_values("t_stat", key=abs, ascending=False)


# ════════════════════════════════════════════════════════════════════════════
#  CHARTS
# ════════════════════════════════════════════════════════════════════════════

DAY_PALETTE = ["#4477AA", "#EE6677", "#228833", "#CCBB44", "#66CCEE"]


def _save(fig: plt.Figure, path: str, name: str):
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    print(f"  ✓ {name}")


# ── 01 Delta-1 overview ──────────────────────────────────────────────────────

def plot_01_delta1_overview(prices_df: pd.DataFrame, out: str):
    fig, axes = plt.subplots(2, 2, figsize=(16, 9))
    fig.suptitle("Round 4 – HYDROGEL_PACK & VELVETFRUIT_EXTRACT", fontsize=13, fontweight="bold")

    for col, prod in enumerate(PRODUCTS_DELTA1):
        mp = mid_series(prices_df, prod)
        sp = spread_series(prices_df, prod)
        color = "#4477AA" if col == 0 else "#228833"

        ax = axes[0, col]
        for d, g in mp.groupby("day"):
            ax.plot(g["timestamp"], g["mid_price"], lw=0.5,
                    color=DAY_PALETTE[d % len(DAY_PALETTE)], label=f"Day {d}")
        ax.set_title(f"{prod} – Mid Price")
        ax.set_xlabel("Timestamp"); ax.set_ylabel(f"Price ({CURRENCY})")
        ax.legend(fontsize=7)

        ax = axes[1, col]
        if not sp.empty:
            for d, g in sp.groupby("day"):
                ax.plot(g["timestamp"], g["spread"], lw=0.3, alpha=0.5,
                        color=DAY_PALETTE[d % len(DAY_PALETTE)])
            mn = sp["spread"].mean()
            ax.axhline(mn, color="red", ls="--", lw=1.4, label=f"Mean={mn:.2f}")
        ax.set_title(f"{prod} – Bid-Ask Spread"); ax.legend(fontsize=7)
        ax.set_xlabel("Timestamp"); ax.set_ylabel(f"Spread ({CURRENCY})")

        # ACF subplot inset (bottom row, manual)
        acf_ax = axes[1, col].inset_axes([0.65, 0.5, 0.33, 0.45])
        returns = mp["mid_price"].pct_change().dropna().values
        acf = [np.corrcoef(returns[:-lag], returns[lag:])[0, 1] if len(returns) > lag else 0
               for lag in range(1, 31)]
        acf_ax.bar(range(1, 31), acf, width=0.7, color=color, alpha=0.7)
        ci = 1.96 / math.sqrt(len(returns))
        acf_ax.axhline(ci, color="red", ls="--", lw=0.7)
        acf_ax.axhline(-ci, color="red", ls="--", lw=0.7)
        acf_ax.axhline(0, color="black", lw=0.5)
        acf_ax.set_title("Return ACF", fontsize=6)
        acf_ax.tick_params(labelsize=5)

    _save(fig, os.path.join(out, "01_delta1_overview.png"), "01_delta1_overview.png")


# ── 02 EMA deviation / mean-reversion signal ────────────────────────────────

def plot_02_ema_deviation(prices_df: pd.DataFrame, out: str, ema_win: int = 20) -> dict:
    fig, axes = plt.subplots(2, 2, figsize=(16, 9))
    fig.suptitle("EMA Deviation – Mean-Reversion Signal", fontsize=13, fontweight="bold")
    thresholds: dict[str, float] = {}

    for col, prod in enumerate(PRODUCTS_DELTA1):
        mp = mid_series(prices_df, prod)
        mp["ema20"]  = mp["mid_price"].ewm(span=20,  adjust=False).mean()
        mp["ema100"] = mp["mid_price"].ewm(span=100, adjust=False).mean()
        mp["dev20"]  = mp["mid_price"] - mp["ema20"]
        p90 = mp["dev20"].quantile(0.90)
        p10 = mp["dev20"].quantile(0.10)
        thresholds[prod] = abs(p90)

        ax = axes[0, col]
        for d, g in mp.groupby("day"):
            ax.plot(g["timestamp"], g["mid_price"], lw=0.4,
                    color=DAY_PALETTE[d % len(DAY_PALETTE)], alpha=0.7, label=f"Mid D{d}")
            ax.plot(g["timestamp"], g["ema20"],  lw=1.0, ls="-",  color="#EE6677", alpha=0.8)
            ax.plot(g["timestamp"], g["ema100"], lw=1.0, ls="--", color="#CCBB44", alpha=0.8)
        ax.set_title(f"{prod} – Price + EMAs (orange=EMA-20, yellow=EMA-100)")
        ax.set_ylabel(f"Price ({CURRENCY})")
        ax.legend(fontsize=6)

        ax = axes[1, col]
        for d, g in mp.groupby("day"):
            c = DAY_PALETTE[d % len(DAY_PALETTE)]
            ax.fill_between(g["timestamp"], g["dev20"], 0, alpha=0.35, color=c)
        ax.axhline(p90, color="red",   ls="--", lw=1.3, label=f"p90 = {p90:+.2f}")
        ax.axhline(p10, color="green", ls="--", lw=1.3, label=f"p10 = {p10:+.2f}")
        ax.axhline(0,   color="black", lw=0.7)
        ax.set_title(f"{prod} – Deviation from EMA-{ema_win}  →  MR threshold ≈ ±{abs(p90):.1f}")
        ax.set_ylabel(f"Deviation ({CURRENCY})"); ax.legend(fontsize=7)

    _save(fig, os.path.join(out, "02_delta1_ema_deviation.png"), "02_delta1_ema_deviation.png")
    return thresholds


# ── 03 Volatility smile ─────────────────────────────────────────────────────

def plot_03_vol_smile(iv_df: pd.DataFrame, out: str):
    days = sorted(iv_df["day"].unique())
    fig, axes = plt.subplots(1, len(days), figsize=(6 * len(days), 5))
    if len(days) == 1:
        axes = [axes]
    fig.suptitle("Volatility Smile – IV vs ln(S/K) by Day", fontsize=13, fontweight="bold")

    for ax, d in zip(axes, days):
        g = iv_df[iv_df["day"] == d]
        ax.scatter(g["moneyness"], g["iv"], alpha=0.15, s=8, color="#4477AA", label="IV obs")
        m_rng = np.linspace(g["moneyness"].min(), g["moneyness"].max(), 300)
        try:
            c = np.polyfit(g["moneyness"].values, g["iv"].values, 2)
            fitted = np.polyval(c, g["moneyness"].values)
            r2 = 1 - np.sum((g["iv"].values - fitted) ** 2) / np.sum(
                (g["iv"].values - g["iv"].mean()) ** 2)
            ax.plot(m_rng, np.polyval(c, m_rng), "r-", lw=2, label=f"Parabola (R²={r2:.3f})")
        except Exception:
            pass
        T_val = g["T"].iloc[0] * TRADING_DAYS_PER_YEAR if not g.empty else "?"
        ax.set_title(f"Day {d}  TTE={T_val:.0f}d")
        ax.set_xlabel("ln(S/K)"); ax.set_ylabel("Implied Volatility")
        ax.legend(fontsize=8)

    _save(fig, os.path.join(out, "03_vol_smile.png"), "03_vol_smile.png")


# ── 04 Price deviation from smile fair ──────────────────────────────────────

def plot_04_iv_price_deviations(smile_df: pd.DataFrame, out: str):
    syms = sorted([s for s in smile_df["sym"].unique()], key=lambda s: STRIKES_MAP.get(s, 0))
    days = sorted(smile_df["day"].unique())
    nrows, ncols = len(syms), len(days)
    fig, axes = plt.subplots(nrows, ncols, figsize=(5 * ncols, 2.5 * nrows))
    if nrows == 1: axes = np.array([axes])
    if ncols == 1: axes = np.array([[r] for r in axes])
    fig.suptitle("Price Deviation from IV-Fair Value\n"
                 "(+= market ABOVE smile = overpriced;  −= underpriced)", fontsize=12, fontweight="bold")

    # Compute persistent bias per (sym, day) and print summary
    print("  Persistent price deviations from smile:")
    for ri, sym in enumerate(syms):
        for ci, d in enumerate(days):
            ax = axes[ri][ci]
            sub = smile_df[(smile_df["sym"] == sym) & (smile_df["day"] == d)].sort_values("timestamp")
            sub = sub.dropna(subset=["price_deviation"])
            if sub.empty:
                ax.set_visible(False); continue
            devs = sub["price_deviation"].values
            ts   = sub["timestamp"].values
            ax.fill_between(ts, devs, 0, where=(devs > 0), color="#EE6677", alpha=0.55)
            ax.fill_between(ts, devs, 0, where=(devs <= 0), color="#66CC99", alpha=0.55)
            ax.plot(ts, devs, lw=0.4, color="#334455")
            ax.axhline(0, color="black", lw=0.6)
            ax.set_title(f"{sym} D{d}", fontsize=7)
            if ci == 0: ax.set_ylabel("Dev", fontsize=6)
            if ri == 0 and ci == 0: pass
            mean_dev = np.mean(devs)
            bias = "OVER" if mean_dev > 0.5 else "UNDER" if mean_dev < -0.5 else "neutral"
            if bias != "neutral":
                print(f"    {sym} Day{d}: mean={mean_dev:+.2f} → {bias}PRICED")

    _save(fig, os.path.join(out, "04_iv_price_deviations.png"), "04_iv_price_deviations.png")


# ── 05 Option return ACF ─────────────────────────────────────────────────────

def plot_05_option_autocorr(smile_df: pd.DataFrame, out: str, max_lag: int = 20) -> dict:
    syms = sorted([s for s in smile_df["sym"].unique()], key=lambda s: STRIKES_MAP.get(s, 0))
    ncols, nrows = 5, math.ceil(len(syms) / 5)
    fig, axes = plt.subplots(nrows, ncols, figsize=(4 * ncols, 3.2 * nrows))
    axes = np.array(axes).flatten()
    fig.suptitle("VEV Option Return ACF\n(red bars = statistically significant mean reversion)",
                 fontsize=12, fontweight="bold")

    lag1_acfs: dict[str, float] = {}
    for idx, sym in enumerate(syms):
        ax = axes[idx]
        sub = smile_df[smile_df["sym"] == sym].sort_values(["day", "timestamp"])
        prices = sub["market_mid"].values
        if len(prices) < max_lag + 5:
            ax.set_title(sym); continue

        rets = np.diff(prices) / np.maximum(prices[:-1], 0.01)
        ci = 1.96 / math.sqrt(len(rets))
        acf = []
        for lag in range(1, max_lag + 1):
            if len(rets) > lag:
                c = np.corrcoef(rets[:-lag], rets[lag:])[0, 1]
                acf.append(0.0 if np.isnan(c) else c)
            else:
                acf.append(0.0)

        lag1 = acf[0] if acf else 0.0
        lag1_acfs[sym] = lag1
        colors = ["#CC3333" if v < -ci else "#4477AA" for v in acf]
        ax.bar(range(1, len(acf) + 1), acf, color=colors, width=0.7)
        ax.axhline(ci,  color="red", ls="--", lw=0.8)
        ax.axhline(-ci, color="red", ls="--", lw=0.8)
        ax.axhline(0,   color="black", lw=0.5)
        ax.set_title(f"{sym}\nlag-1={lag1:.3f}", fontsize=8)
        ax.set_ylim(-0.4, 0.2)

    for i in range(len(syms), len(axes)):
        axes[i].set_visible(False)

    _save(fig, os.path.join(out, "05_option_autocorr.png"), "05_option_autocorr.png")

    print("  Option lag-1 ACF (negative = mean-reverting = scalping opportunity):")
    for s, v in sorted(lag1_acfs.items(), key=lambda x: x[1]):
        note = " ← SCALP" if v < -0.15 else (" ← moderate" if v < -0.05 else "")
        print(f"    {s}: {v:+.4f}{note}")

    return lag1_acfs


# ── 06 Delta surface ────────────────────────────────────────────────────────

def plot_06_delta_surface(iv_df: pd.DataFrame, out: str):
    days = sorted(iv_df["day"].unique())
    fig, axes = plt.subplots(1, len(days), figsize=(6 * len(days), 5))
    if len(days) == 1: axes = [axes]
    fig.suptitle("VEV Option Deltas vs Time", fontsize=13, fontweight="bold")

    cmap = plt.cm.plasma(np.linspace(0.05, 0.95, len(STRIKES_MAP)))
    sym_order = sorted(STRIKES_MAP.keys(), key=lambda s: STRIKES_MAP[s])

    for ax, d in zip(axes, days):
        dg = iv_df[iv_df["day"] == d]
        for sym, col in zip(sym_order, cmap):
            sg = dg[dg["sym"] == sym].sort_values("timestamp")
            if sg.empty: continue
            deltas = [bs_delta_call(r.S, r.K, r.T, r.iv) for r in sg.itertuples()]
            ax.plot(sg["timestamp"].values, deltas, lw=0.8, color=col,
                    label=sym.replace("VEV_", ""))
        T_days = dg["T"].iloc[0] * TRADING_DAYS_PER_YEAR if not dg.empty else "?"
        ax.set_title(f"Day {d} – TTE={T_days:.0f}d")
        ax.axhline(0.5, color="black", ls="--", lw=0.8, alpha=0.5)
        ax.set_xlabel("Timestamp"); ax.set_ylabel("Delta")
        ax.legend(fontsize=6, ncol=2); ax.set_ylim(0, 1.05)

    _save(fig, os.path.join(out, "06_delta_surface.png"), "06_delta_surface.png")


# ── 07 Fair vs market ───────────────────────────────────────────────────────

def plot_07_fair_vs_market(smile_df: pd.DataFrame, out: str):
    # Focus on the most tradeable strikes (tight spread, some extrinsic)
    focus = [s for s in ["VEV_5000", "VEV_5200", "VEV_5400", "VEV_5500", "VEV_6000"]
             if s in smile_df["sym"].unique()]
    days  = sorted(smile_df["day"].unique())
    nrows, ncols = len(focus), len(days)
    fig, axes = plt.subplots(nrows, ncols, figsize=(5 * ncols, 2.8 * nrows))
    if nrows == 1: axes = np.array([axes])
    if ncols == 1: axes = np.array([[r] for r in axes])
    fig.suptitle("VEV – BS Fair (smile) vs Market Mid", fontsize=13, fontweight="bold")

    for ri, sym in enumerate(focus):
        for ci, d in enumerate(days):
            ax = axes[ri][ci]
            sub = smile_df[(smile_df["sym"] == sym) & (smile_df["day"] == d)].sort_values("timestamp")
            sub = sub.dropna(subset=["smile_price"])
            if sub.empty: ax.set_visible(False); continue
            ax.plot(sub["timestamp"], sub["market_mid"], lw=0.7, color="#4477AA", label="Market")
            ax.plot(sub["timestamp"], sub["smile_price"], lw=0.7, ls="--",
                    color="#EE6677", label="BS Fair")
            ax.fill_between(sub["timestamp"], sub["market_mid"], sub["smile_price"],
                            alpha=0.2, color="#AA44BB")
            ax.set_title(f"{sym} D{d}", fontsize=8)
            if ci == 0: ax.set_ylabel(f"Price ({CURRENCY})", fontsize=7)
            if ri == 0 and ci == 0: ax.legend(fontsize=6)

    _save(fig, os.path.join(out, "07_fair_vs_market.png"), "07_fair_vs_market.png")


# ── 08 IV level trends ───────────────────────────────────────────────────────

def plot_08_iv_level_trends(iv_df: pd.DataFrame, out: str):
    syms = sorted(STRIKES_MAP.keys(), key=lambda s: STRIKES_MAP[s])
    ncols, nrows = 5, math.ceil(len(syms) / 5)
    fig, axes = plt.subplots(nrows, ncols, figsize=(4.2 * ncols, 3.5 * nrows))
    axes = np.array(axes).flatten()
    fig.suptitle("IV Level Over Time per Strike (D1=blue, D2=orange, D3=green)",
                 fontsize=12, fontweight="bold")

    day_colors = {1: "#4477AA", 2: "#EE6677", 3: "#228833", 4: "#CCBB44"}
    for idx, sym in enumerate(syms):
        ax = axes[idx]
        for d, col in day_colors.items():
            sg = iv_df[(iv_df["sym"] == sym) & (iv_df["day"] == d)].sort_values("timestamp")
            if sg.empty: continue
            ax.plot(sg["timestamp"], sg["iv"], lw=0.7, color=col, alpha=0.85, label=f"D{d}")
        ax.set_title(sym, fontsize=9)
        ax.set_xlabel("Timestamp", fontsize=7); ax.set_ylabel("IV", fontsize=7)
        ax.legend(fontsize=6)

    for i in range(len(syms), len(axes)):
        axes[i].set_visible(False)
    _save(fig, os.path.join(out, "08_iv_level_trends.png"), "08_iv_level_trends.png")


# ── 09 Mark volume heatmap ───────────────────────────────────────────────────

def plot_09_mark_heatmap(trades_df: pd.DataFrame, out: str):
    from matplotlib.colors import TwoSlopeNorm

    all_prods = PRODUCTS_DELTA1 + sorted(STRIKES_MAP.keys(), key=lambda s: STRIKES_MAP[s])
    all_marks = sorted({
        m for col in ("buyer", "seller")
        for m in trades_df[col].unique()
        if str(m).startswith("Mark")
    })
    if not all_marks:
        print("  ⚠  No Mark traders found – skipping heatmap"); return

    buy_vol = {m: {p: 0.0 for p in all_prods} for m in all_marks}
    sell_vol = {m: {p: 0.0 for p in all_prods} for m in all_marks}

    for row in trades_df.itertuples():
        sym = str(row.symbol).upper()
        prod = next((p for p in all_prods if p.upper() == sym), None)
        if prod is None: continue
        qty = abs(float(row.quantity))
        if str(row.buyer).startswith("Mark"):
            buy_vol[row.buyer][prod] += qty
        if str(row.seller).startswith("Mark"):
            sell_vol[row.seller][prod] += qty

    # Keep only active marks
    active = [m for m in all_marks if
              sum(buy_vol[m][p] + sell_vol[m][p] for p in all_prods) > 0]
    active_prods = [p for p in all_prods if
                    any(buy_vol[m][p] + sell_vol[m][p] > 0 for m in active)]

    buy_arr  = np.array([[buy_vol[m][p]  for p in active_prods] for m in active])
    sell_arr = np.array([[sell_vol[m][p] for p in active_prods] for m in active])
    net_arr  = buy_arr - sell_arr

    fig, axes = plt.subplots(1, 3, figsize=(20, max(4, len(active) * 0.55 + 2)))
    fig.suptitle("Mark Activity – Volume Heatmaps", fontsize=13, fontweight="bold")

    for ax, data, title, cmap in zip(
        axes, [buy_arr, sell_arr, net_arr], ["Buy", "Sell", "Net"], ["Blues", "Reds", "RdYlGn"]
    ):
        if cmap == "RdYlGn":
            vmax = max(abs(net_arr).max(), 1)
            norm = TwoSlopeNorm(vmin=-vmax, vcenter=0, vmax=vmax)
            im = ax.imshow(data, aspect="auto", cmap=cmap, norm=norm)
        else:
            im = ax.imshow(data, aspect="auto", cmap=cmap)
        ax.set_xticks(range(len(active_prods)))
        ax.set_xticklabels([p.replace("VELVETFRUIT_EXTRACT", "VEV_EXT").replace("HYDROGEL_PACK", "HYDRO")
                            for p in active_prods], rotation=45, ha="right", fontsize=7)
        ax.set_yticks(range(len(active)))
        ax.set_yticklabels(active, fontsize=7)
        ax.set_title(title)
        plt.colorbar(im, ax=ax, fraction=0.02, pad=0.02)

    _save(fig, os.path.join(out, "09_mark_volume_heatmap.png"), "09_mark_volume_heatmap.png")


# ── 10 Mark timing ───────────────────────────────────────────────────────────

def plot_10_mark_timing(trades_df: pd.DataFrame, out: str, nbins: int = 20):
    days = sorted(trades_df["day"].unique())
    all_marks = sorted({
        m for col in ("buyer", "seller")
        for m in trades_df[col].unique()
        if str(m).startswith("Mark")
    })
    # Sort marks by total volume and take top 7
    mark_vol = {m: len(trades_df[(trades_df["buyer"] == m) | (trades_df["seller"] == m)])
                for m in all_marks}
    top_marks = sorted(all_marks, key=mark_vol.get, reverse=True)[:7]

    fig, axes = plt.subplots(1, len(days), figsize=(6 * len(days), 4.5))
    if len(days) == 1: axes = [axes]
    fig.suptitle("Mark Trade Timestamp Distribution", fontsize=13, fontweight="bold")
    colors = plt.cm.tab10(np.linspace(0, 1, len(top_marks)))

    for ax, d in zip(axes, days):
        sub = trades_df[trades_df["day"] == d]
        ts_min, ts_max = sub["timestamp"].min(), sub["timestamp"].max()
        edges = np.linspace(ts_min, ts_max, nbins + 1)
        bottoms = np.zeros(nbins)
        for mark, col in zip(top_marks, colors):
            mt = sub[(sub["buyer"] == mark) | (sub["seller"] == mark)]
            counts, _ = np.histogram(mt["timestamp"], bins=edges)
            ax.bar((edges[:-1] + edges[1:]) / 2, counts,
                   width=(ts_max - ts_min) / nbins * 0.85,
                   bottom=bottoms, color=col, alpha=0.8, label=mark)
            bottoms += counts
        ax.set_title(f"Day {d}")
        ax.set_xlabel("Timestamp"); ax.set_ylabel("# Trades")
        ax.legend(fontsize=7, ncol=2)

    _save(fig, os.path.join(out, "10_mark_timing.png"), "10_mark_timing.png")


# ── 11 Mark forward-return signals ──────────────────────────────────────────

def plot_11_mark_signals(signals_df: pd.DataFrame, out: str):
    if signals_df.empty:
        print("  ⚠  signals_df empty – skipping mark signals chart"); return

    fig, axes = plt.subplots(1, 2, figsize=(14, 6))
    fig.suptitle("Mark Signals – 5-tick forward return", fontsize=13, fontweight="bold")

    for ax, prod in zip(axes, PRODUCTS_DELTA1):
        sub = signals_df[(signals_df["product"] == prod) & (signals_df["n"] >= 5)].copy()
        if sub.empty: ax.set_title(prod); continue
        sub = sub.sort_values("t_stat")
        labels = sub.apply(lambda r: f"{r['mark']} / {r['side']}", axis=1).values
        vals   = sub["avg"].values
        colors = ["#228833" if v > 0 else "#CC3333" for v in vals]
        bars = ax.barh(range(len(sub)), vals, color=colors, alpha=0.85, edgecolor="white")
        ax.set_yticks(range(len(sub)))
        ax.set_yticklabels(labels, fontsize=8)
        for i, row in enumerate(sub.itertuples()):
            ax.text(0.005, i, f"t={row.t_stat:.1f}  n={int(row.n)}",
                    va="center", ha="left", fontsize=7, color="black",
                    transform=ax.get_yaxis_transform())
        ax.axvline(0, color="black", lw=0.9)
        ax.set_xlabel("Avg fwd return (bps)")
        ax.set_title(prod.replace("_", " "))

    _save(fig, os.path.join(out, "11_mark_signals.png"), "11_mark_signals.png")


# ── 12 Mark overlay on individual products ───────────────────────────────────

def plot_12_mark_overlay(trades_df: pd.DataFrame, prices_df: pd.DataFrame,
                          product: str, out: str, fname: str, n_marks: int = 6):
    mp = mid_series(prices_df, product)
    prod_trades = trades_df[trades_df["symbol"] == product.upper()]
    all_marks = sorted({
        m for col in ("buyer", "seller")
        for m in prod_trades[col].unique()
        if str(m).startswith("Mark")
    })
    mark_vol = {m: len(prod_trades[(prod_trades["buyer"] == m) | (prod_trades["seller"] == m)])
                for m in all_marks}
    top_marks = sorted(all_marks, key=mark_vol.get, reverse=True)[:n_marks]

    ncols = 2
    nrows = math.ceil(len(top_marks) / ncols)
    fig, axes = plt.subplots(nrows, ncols, figsize=(10, 4 * nrows))
    axes = np.array(axes).flatten()
    fig.suptitle(f"{product.replace('_', ' ')} – Top-{len(top_marks)} Mark Overlay",
                 fontsize=13, fontweight="bold")

    for idx, mark in enumerate(top_marks):
        ax = axes[idx]
        for d, g in mp.groupby("day"):
            ax.plot(g["timestamp"], g["mid_price"], lw=0.35, color="#AAAAAA", alpha=0.8)
        mt = prod_trades[(prod_trades["buyer"] == mark) | (prod_trades["seller"] == mark)]
        buys  = mt[mt["buyer"]  == mark]
        sells = mt[mt["seller"] == mark]
        if not buys.empty:
            ax.scatter(buys["timestamp"],  buys["price"],  marker="^", s=18,
                       color="#228833", zorder=5, label=f"Buy({len(buys)})")
        if not sells.empty:
            ax.scatter(sells["timestamp"], sells["price"], marker="v", s=18,
                       color="#CC3333", zorder=5, label=f"Sell({len(sells)})")
        ax.set_title(mark, fontsize=9)
        ax.legend(fontsize=7)
        ax.set_xlabel("Timestamp"); ax.set_ylabel(f"Price ({CURRENCY})")

    for i in range(len(top_marks), len(axes)):
        axes[i].set_visible(False)
    _save(fig, os.path.join(out, f"{fname}.png"), f"{fname}.png")


# ── 13 Spread summary ───────────────────────────────────────────────────────

def plot_13_spread_summary(prices_df: pd.DataFrame, out: str):
    all_prods = PRODUCTS_DELTA1 + sorted(STRIKES_MAP.keys(), key=lambda s: STRIKES_MAP[s])
    means, mins_, maxs_, labels = [], [], [], []

    for prod in all_prods:
        sp = spread_series(prices_df, prod)
        if sp.empty or sp["spread"].isna().all():
            means.append(0); mins_.append(0); maxs_.append(0)
        else:
            s = sp["spread"].dropna()
            means.append(s.mean()); mins_.append(s.min()); maxs_.append(s.max())
        labels.append(prod.replace("VELVETFRUIT_EXTRACT", "VEV_EXT").replace("HYDROGEL_PACK", "HYDRO"))

    fig, axes = plt.subplots(1, 2, figsize=(16, 5))
    fig.suptitle("Spread & Liquidity", fontsize=13, fontweight="bold")

    d1_idx  = [i for i, p in enumerate(all_prods) if p in PRODUCTS_DELTA1]
    vev_idx = [i for i, p in enumerate(all_prods) if p in STRIKES_MAP]

    ax = axes[0]; ax.set_title("Delta-1 – Mean Spread")
    for i, idx in enumerate(d1_idx):
        c = ["#4477AA", "#228833"][i]
        ax.bar(labels[idx], means[idx], color=c)
        if maxs_[idx] > 0:
            ax.errorbar(labels[idx], means[idx],
                        yerr=[[means[idx] - mins_[idx]], [maxs_[idx] - means[idx]]],
                        fmt="none", color="black", capsize=5)
    ax.set_ylabel(f"Spread (ticks)")

    ax = axes[1]; ax.set_title("VEV Options – Mean Spread")
    xs = [labels[i] for i in vev_idx]
    ys = [means[i] for i in vev_idx]
    ax.bar(xs, ys, color="#6699CC", alpha=0.85)
    for i, (x, y, lo, hi) in enumerate(zip(xs, ys,
                                            [means[i] - mins_[i] for i in vev_idx],
                                            [maxs_[i] - means[i] for i in vev_idx])):
        if hi > 0:
            ax.errorbar(i, y, yerr=[[lo], [hi]], fmt="none", color="black", capsize=4)
    ax.set_xticks(range(len(xs))); ax.set_xticklabels(xs, rotation=45, ha="right", fontsize=8)
    ax.set_ylabel("Spread (ticks)")

    _save(fig, os.path.join(out, "13_spread_summary.png"), "13_spread_summary.png")


# ════════════════════════════════════════════════════════════════════════════
#  PARAMETER REPORT
# ════════════════════════════════════════════════════════════════════════════

def write_parameter_report(
    prices_df: pd.DataFrame,
    iv_df: pd.DataFrame,
    smile_df: pd.DataFrame,
    signals_df: pd.DataFrame,
    ema_thresholds: dict,
    lag1_acfs: dict,
    out: str,
    round_num: int,
):
    lines = [
        "=" * 70,
        f"IMC Prosperity 4 – Round {round_num} Parameter Report  (currency: {CURRENCY})",
        "=" * 70,
        "",
    ]

    # ── Delta-1 ──
    lines.append("── DELTA-1 PARAMETERS ──")
    for prod in PRODUCTS_DELTA1:
        mp  = mid_series(prices_df, prod)
        sp  = spread_series(prices_df, prod)
        acf1 = mp["mid_price"].pct_change().dropna().autocorr(lag=1)
        thresh = ema_thresholds.get(prod, 5.0)
        mean_sp = sp["spread"].mean() if not sp.empty else float("nan")
        lines += [
            f"  {prod}",
            f"    Mean price:         {mp['mid_price'].mean():.2f} {CURRENCY}",
            f"    Price std:          {mp['mid_price'].std():.4f}",
            f"    Return ACF(1):      {acf1:.4f}  {'◄ MEAN-REVERT' if acf1 < -0.05 else ''}",
            f"    Mean spread:        {mean_sp:.2f} ticks",
            f"    EMA-20 MR threshold (p90): ±{thresh:.2f}",
            f"    → Recommended take_edge:   {max(1, round(thresh * 0.40))} {CURRENCY}",
            f"    → Recommended halfspread:  {max(2, round(mean_sp * 0.55))} {CURRENCY}",
            "",
        ]

    # ── VEV IV summary ──
    if not iv_df.empty:
        lines.append("── VEV IV SUMMARY (per-strike) ──")
        for sym in sorted(STRIKES_MAP.keys(), key=lambda s: STRIKES_MAP[s]):
            sub = iv_df[iv_df["sym"] == sym]["iv"].dropna()
            if sub.empty: continue
            lines.append(
                f"  {sym}: mean={sub.mean():.3f}  std={sub.std():.3f}"
                f"  range=[{sub.min():.3f}, {sub.max():.3f}]"
            )
        lines.append("")

    # ── Smile deviation bias ──
    if not smile_df.empty:
        lines.append("── PRICE DEVIATION FROM SMILE  (+= overpriced, sell bias; −= buy bias) ──")
        for sym in sorted(STRIKES_MAP.keys(), key=lambda s: STRIKES_MAP[s]):
            sub = smile_df[smile_df["sym"] == sym]["price_deviation"].dropna()
            if sub.empty: continue
            mn, sd = sub.mean(), sub.std()
            bias = "→ SELL BIAS" if mn > 0.5 else ("→ BUY BIAS" if mn < -0.5 else "→ NEUTRAL")
            lines.append(f"  {sym}: mean_dev={mn:+.3f}  std={sd:.3f}  {bias}")
        lines.append("")

        # Recommended IV threshold
        dev_abs = smile_df["iv_deviation"].dropna().abs()
        if not dev_abs.empty:
            p70 = dev_abs.quantile(0.70)
            p85 = dev_abs.quantile(0.85)
            lines += [
                "── SMILE TRADING THRESHOLDS ──",
                f"  Medium signal (p70):  IV_DEV_THRESHOLD = {p70:.4f}",
                f"  High   signal (p85):  IV_DEV_THRESHOLD = {p85:.4f}",
                f"  Recommended:          IV_DEV_THRESHOLD = {p70:.4f}  (use p70 to trade more)",
                f"  MIN_EDGE:             1.0 {CURRENCY}",
                "",
            ]

    # ── ACF scalping ──
    if lag1_acfs:
        lines.append("── OPTION ACF SCALPING SIGNALS (lag-1, negative = mean-reverting) ──")
        for sym, v in sorted(lag1_acfs.items(), key=lambda x: x[1]):
            note = " ← STRONG SCALP" if v < -0.15 else (" ← moderate" if v < -0.05 else "")
            lines.append(f"  {sym}: lag-1 ACF = {v:+.4f}{note}")
        lines.append("")

    # ── Mark signals ──
    if not signals_df.empty:
        lines.append("── TOP MARK SIGNALS (|t| ≥ 2.0, min 5 trades) ──")
        top = (
            signals_df[(signals_df["t_stat"].abs() >= 2.0) & (signals_df["n"] >= 5)]
            .sort_values("t_stat", key=abs, ascending=False)
        )
        for _, r in top.iterrows():
            lines.append(
                f"  {r['product']}: {r['mark']} {r['side'].upper():4s}  "
                f"avg={r['avg']:+.1f}bps  t={r['t_stat']:.2f}  n={int(r['n'])}"
            )
        lines.append("")
        lines += [
            "  INTERPRETATION:",
            "    avg > 0 and t > 2.0 → following this Mark/side is profitable",
            "    avg < 0 and t < −2.0 → FADE this Mark/side (take opposite side)",
            "    |t| < 2.0 → not statistically significant, ignore",
        ]

    lines += ["", "=" * 70]
    text = "\n".join(lines)
    path = os.path.join(out, "00_parameter_report.txt")
    with open(path, "w") as f:
        f.write(text)
    print("\n" + text)
    print(f"\n  ✓ 00_parameter_report.txt  (copy paste into your pre-round notes)")


# ════════════════════════════════════════════════════════════════════════════
#  MAIN
# ════════════════════════════════════════════════════════════════════════════

def main():
    ap = argparse.ArgumentParser(
        description="IMC Prosperity 4 – Comprehensive Round Analysis Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("--prices", nargs="+", required=True,
                    help="Price CSV file(s). Pass one per day in order.")
    ap.add_argument("--trades", nargs="+", default=[],
                    help="Trade CSV file(s). One per day in order (optional).")
    ap.add_argument("--round", type=int, default=4, dest="round_num",
                    help="Competition round number (3, 4, or 5). Default: 4")
    ap.add_argument("--start-day", type=int, default=1,
                    help="Day label for the first file (default: 1).")
    ap.add_argument("--ema-window", type=int, default=20,
                    help="EMA window for Delta-1 mean-reversion analysis (default: 20).")
    ap.add_argument("--forward-ticks", type=int, default=5,
                    help="Forward tick horizon for Mark signal computation (default: 5).")
    ap.add_argument("--output", default="./analysis_output",
                    help="Directory for output files (created if absent). Default: ./analysis_output")
    ap.add_argument("--no-marks",   action="store_true", help="Skip all Mark trader analysis.")
    ap.add_argument("--no-options", action="store_true", help="Skip options / smile analysis.")
    ap.add_argument("--quiet", "-q", action="store_true",
                    help="Print only warnings and the final report.")
    args = ap.parse_args()

    os.makedirs(args.output, exist_ok=True)

    # ── TTE map ──
    tte_raw = TTE_PER_ROUND.get(args.round_num, {1: 4, 2: 3, 3: 2})
    # Re-key by actual start_day if user shifted
    keys = sorted(tte_raw.keys())
    tte_map = {args.start_day + (k - keys[0]): tte_raw[k] for k in keys}

    print(f"\n{'─'*60}")
    print(f"  IMC Prosperity 4 – Analysis Tool  |  Round {args.round_num}")
    print(f"  Output directory: {os.path.abspath(args.output)}")
    print(f"  Currency: {CURRENCY}")
    print(f"{'─'*60}\n")

    # ── Load prices ──
    print("▶ Loading price CSVs...")
    prices_df = load_many(args.prices, load_prices, base_day=args.start_day)
    if prices_df.empty:
        sys.exit("ERROR: No price data loaded – check file paths and separator.")
    n_days = prices_df["day"].nunique()
    print(f"  {len(prices_df):,} rows | {n_days} day(s) | "
          f"{prices_df['product'].nunique()} products\n")

    # ── Load trades ──
    trades_df = pd.DataFrame()
    if args.trades and not args.no_marks:
        print("▶ Loading trade CSVs...")
        trades_df = load_many(args.trades, load_trades, base_day=args.start_day)
        print(f"  {len(trades_df):,} trades loaded\n")

    # ── 01 Delta-1 overview ──
    print("▶ [01/13] Delta-1 overview...")
    plot_01_delta1_overview(prices_df, args.output)

    # ── 02 EMA deviation / thresholds ──
    print("▶ [02/13] EMA mean-reversion thresholds...")
    ema_thresholds = plot_02_ema_deviation(prices_df, args.output, ema_win=args.ema_window)

    # ── Options pipeline ──
    iv_df, smile_df = pd.DataFrame(), pd.DataFrame()
    lag1_acfs: dict[str, float] = {}

    if not args.no_options:
        print(f"\n▶ [03/13] Building IV surface "
              f"(may take 30–120 s for large files)...")
        iv_df = build_iv_surface(prices_df, tte_map)
        if iv_df.empty:
            print("  ⚠  IV surface is empty. Check that VELVETFRUIT_EXTRACT "
                  "and at least one VEV_XXXX product exist in the prices file.")
        else:
            print(f"  {len(iv_df):,} IV observations across "
                  f"{iv_df['sym'].nunique()} strikes\n")

            print("▶ [04/13] Fitting smile deviations...")
            smile_df = fit_smile_deviations(iv_df)
            fitted_count = smile_df["fitted_iv"].notna().sum()
            print(f"  {fitted_count:,} ticks with valid smile fit\n")

            print("▶ [05/13] Volatility smile plot...")
            plot_03_vol_smile(iv_df, args.output)

            print("▶ [06/13] IV price deviation plots...")
            plot_04_iv_price_deviations(smile_df, args.output)

            print("▶ [07/13] Option return ACF...")
            lag1_acfs = plot_05_option_autocorr(smile_df, args.output)

            print("\n▶ [08/13] Delta surface...")
            plot_06_delta_surface(iv_df, args.output)

            print("▶ [09/13] Fair vs market...")
            plot_07_fair_vs_market(smile_df, args.output)

            print("▶ [10/13] IV level trends...")
            plot_08_iv_level_trends(iv_df, args.output)
    else:
        print("  (Options analysis skipped via --no-options)\n")

    # ── Mark analysis ──
    signals_df = pd.DataFrame()
    if not trades_df.empty and not args.no_marks:
        print("\n▶ [11/13] Mark volume heatmap...")
        plot_09_mark_heatmap(trades_df, args.output)

        print("▶ [12/13] Mark timing + signals...")
        plot_10_mark_timing(trades_df, args.output)
        signals_df = compute_mark_forward_returns(
            trades_df, prices_df, forward_ticks=args.forward_ticks
        )
        if not signals_df.empty:
            signals_df.to_csv(
                os.path.join(args.output, "mark_signal_strength.csv"), index=False)
            print("  ✓ mark_signal_strength.csv")
        plot_11_mark_signals(signals_df, args.output)

        for prod, fname in [("HYDROGEL_PACK", "12_mark_hydro"),
                             ("VELVETFRUIT_EXTRACT", "12_mark_velv")]:
            plot_12_mark_overlay(trades_df, prices_df, prod, args.output, fname)
    else:
        print("  (Mark analysis skipped)\n")

    # ── Spread summary ──
    print("▶ [13/13] Spread & liquidity summary...")
    plot_13_spread_summary(prices_df, args.output)

    # ── Parameter report ──
    print("\n▶ Writing parameter report...\n")
    write_parameter_report(
        prices_df, iv_df, smile_df, signals_df,
        ema_thresholds, lag1_acfs, args.output, args.round_num,
    )

    print(f"\n{'─'*60}")
    print(f"  ✓  All outputs saved to: {os.path.abspath(args.output)}/")
    print(f"{'─'*60}\n")


if __name__ == "__main__":
    main()
