#!/usr/bin/env python3
"""
IMC Prosperity 4 – Round 5 Master Analyzer
===========================================
Built for the 50-product "Cherry Picking Winners" structure.
No options, no VEV, no counterparty data. Pure price/stat analysis.

Outputs (in --output dir):
  00_summary.txt              ← paste into Claude first
  00_parameter_report.txt     ← per-product strategy params
  01_group_prices.png         ← price time-series per group
  02_regime_acf.png           ← ACF + regime classification
  03_ema_deviation.png        ← EMA mean-reversion signals
  04_spread_summary.png       ← spread by product/group
  05_statarb_ratios.png       ← intra-group pair ratio stability
  06_statarb_zscores.png      ← pair spread z-scores over time
  07_volatility_ranking.png   ← vol ranking (MM candidates)
  08_strategy_heatmap.png     ← composite strategy score per product
  09_trade_volume.png         ← trade volume and frequency per product
  10_group_correlation.png    ← intra-group correlation matrices
  statarb_pairs.csv           ← pair ratio stats (best stat-arb targets)
  product_strategy_scores.csv ← full per-product scoring table

QUICK START:
  # Single folder:
  python prosperity4_r5_analyzer.py --data-dir ./my_csvs --output ./r5_output

  # Explicit files:
  python prosperity4_r5_analyzer.py \\
      --prices prices_round_5_day_2.csv prices_round_5_day_3.csv prices_round_5_day_4.csv \\
      --trades trades_round_5_day_2.csv trades_round_5_day_3.csv trades_round_5_day_4.csv \\
      --output ./r5_output

OPTIONS:
  --ema-window N    EMA window for MR analysis (default 20)
  --zwindow N       Rolling window for pair z-score (default 50)
  --quiet / -q      Suppress verbose output
"""

from __future__ import annotations

import argparse
import math
import os
import sys
import warnings
from collections import defaultdict
from itertools import combinations
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import numpy as np
import pandas as pd
from scipy import stats as sp_stats

warnings.filterwarnings("ignore")
matplotlib.use("Agg")
matplotlib.rcParams.update({
    "figure.dpi": 120,
    "font.size": 9,
    "axes.spines.top": False,
    "axes.spines.right": False,
})

# ════════════════════════════════════════════════════════════════════════════
#  CONSTANTS
# ════════════════════════════════════════════════════════════════════════════

CURRENCY      = "XIRECS"
TICKS_PER_DAY = 1_000_000
POSITION_LIMIT = 10   # All R5 products have limit 10

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

# Short label: last underscore-segment
def short(p: str) -> str:
    return p.split("_")[-1]

GROUP_COLORS = {
    "GALAXY_SOUNDS": "#4477AA",
    "SLEEP_POD":     "#EE6677",
    "MICROCHIP":     "#228833",
    "PEBBLES":       "#CCBB44",
    "ROBOT":         "#66CCEE",
    "UV_VISOR":      "#AA3377",
    "TRANSLATOR":    "#BBBBBB",
    "PANEL":         "#EE8833",
    "OXYGEN_SHAKE":  "#44BB99",
    "SNACKPACK":     "#9966CC",
}

DAY_PALETTE = ["#4477AA", "#EE6677", "#228833", "#CCBB44", "#66CCEE"]


def product_to_group(p: str) -> str:
    for g, prods in GROUPS.items():
        if p in prods:
            return g
    return "UNKNOWN"


# ════════════════════════════════════════════════════════════════════════════
#  DATA LOADING
# ════════════════════════════════════════════════════════════════════════════

def _detect_sep(filepath: str) -> str:
    with open(filepath) as f:
        first = f.readline()
    return "," if ("," in first and ";" not in first) else ";"


def load_prices(filepath: str, day: int | None = None) -> pd.DataFrame:
    sep = _detect_sep(filepath)
    df  = pd.read_csv(filepath, sep=sep)
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
    if "timestamp" not in df.columns and "time" in df.columns:
        df = df.rename(columns={"time": "timestamp"})
    if "product" not in df.columns and "symbol" in df.columns:
        df = df.rename(columns={"symbol": "product"})
    if day is not None:
        df["day"] = day
    elif "day" not in df.columns:
        df["day"] = 1
    if "mid_price" not in df.columns:
        bp = next((c for c in df.columns if "bid" in c and "price" in c and "1" in c), None)
        ap = next((c for c in df.columns if "ask" in c and "price" in c and "1" in c), None)
        if bp and ap:
            df["mid_price"] = (df[bp] + df[ap]) / 2.0
        else:
            raise ValueError(f"Cannot find mid_price in {filepath}")
    df["product"]   = df["product"].str.strip().str.upper()
    df["global_ts"] = (df["day"] - 1) * TICKS_PER_DAY + df["timestamp"]
    for c in ["bid_price_1", "ask_price_1", "bid_volume_1", "ask_volume_1",
              "mid_price", "profit_and_loss"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    if "bid_price_1" in df.columns and "ask_price_1" in df.columns:
        df["spread"] = df["ask_price_1"] - df["bid_price_1"]
    return df


def load_trades(filepath: str, day: int | None = None) -> pd.DataFrame:
    sep = _detect_sep(filepath)
    df  = pd.read_csv(filepath, sep=sep)
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
    if "symbol" not in df.columns and "product" in df.columns:
        df = df.rename(columns={"product": "symbol"})
    if day is not None:
        df["day"] = day
    elif "day" not in df.columns:
        df["day"] = 1
    for col in ("buyer", "seller"):
        if col in df.columns:
            df[col] = df[col].fillna("").astype(str).str.strip()
        else:
            df[col] = ""
    df["symbol"]    = df["symbol"].str.strip().str.upper()
    df["price"]     = pd.to_numeric(df["price"],    errors="coerce")
    df["quantity"]  = pd.to_numeric(df["quantity"], errors="coerce")
    df["global_ts"] = (df["day"] - 1) * TICKS_PER_DAY + df["timestamp"]
    return df


def load_many(filepaths: list[str], loader_fn, base_day: int = 1) -> pd.DataFrame:
    frames = [loader_fn(fp, day=base_day + i) for i, fp in enumerate(filepaths)]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def discover_csvs(data_dir: str) -> tuple[list[str], list[str]]:
    price_files, trade_files = [], []
    for fname in sorted(os.listdir(data_dir)):
        path = os.path.join(data_dir, fname)
        if not fname.endswith(".csv"):
            continue
        if "price" in fname:
            price_files.append(path)
        elif "trade" in fname:
            trade_files.append(path)
    return price_files, trade_files


def mid_series(prices_df: pd.DataFrame, product: str) -> pd.DataFrame:
    mask = prices_df["product"] == product.upper()
    return (
        prices_df[mask][["day", "timestamp", "global_ts", "mid_price"]]
        .dropna(subset=["mid_price"])
        .sort_values(["day", "timestamp"])
        .reset_index(drop=True)
    )


def _out(out_dir: str, fname: str) -> str:
    return os.path.join(out_dir, fname)


def _save(fig, path: str, label: str):
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    print(f"  ✓ {label}")


# ════════════════════════════════════════════════════════════════════════════
#  PRODUCT STATISTICS
# ════════════════════════════════════════════════════════════════════════════

def compute_product_stats(prices_df: pd.DataFrame,
                           trades_df: pd.DataFrame,
                           ema_win: int = 20) -> pd.DataFrame:
    """
    Per-product: mean_mid, std_mid, mean_spread, lag1_acf, ema_thresh,
                 slope (trend), cv (coeff of variation), trade_count,
                 mean_trade_qty, group, regime.
    """
    rows = []
    for prod in ALL_PRODUCTS:
        mp = mid_series(prices_df, prod)
        if mp.empty or len(mp) < 10:
            continue

        vals = mp["mid_price"].values
        chg  = np.diff(vals)

        # ACF lag-1 of price changes
        if len(chg) > 2:
            lag1 = float(np.corrcoef(chg[:-1], chg[1:])[0, 1])
            if np.isnan(lag1):
                lag1 = 0.0
        else:
            lag1 = 0.0

        # EMA deviation threshold (p90 of |deviation|)
        ema = pd.Series(vals).ewm(span=ema_win, adjust=False).mean().values
        dev = vals - ema
        thresh = float(np.percentile(np.abs(dev), 90))

        # Trend: OLS slope per tick
        idx   = np.arange(len(vals))
        slope = float(np.polyfit(idx, vals, 1)[0])

        # Spread
        sp_sub = prices_df[prices_df["product"] == prod]["spread"].dropna()
        mean_spread = float(sp_sub.mean()) if not sp_sub.empty else float("nan")

        # Trade stats
        if not trades_df.empty:
            tr = trades_df[trades_df["symbol"] == prod]
            trade_count    = int(tr["quantity"].count())
            mean_trade_qty = float(tr["quantity"].mean()) if trade_count > 0 else 0.0
        else:
            trade_count, mean_trade_qty = 0, 0.0

        mean_mid = float(np.mean(vals))
        std_mid  = float(np.std(vals))
        cv       = std_mid / mean_mid if mean_mid > 0 else float("nan")
        std_chg  = float(np.std(chg)) if len(chg) > 1 else float("nan")

        # Regime classification
        if lag1 < -0.08:
            regime = "MEAN_REVERT"
        elif lag1 > 0.08:
            regime = "TRENDING"
        else:
            regime = "RANDOM_WALK"

        rows.append({
            "product":       prod,
            "group":         product_to_group(prod),
            "mean_mid":      mean_mid,
            "std_mid":       std_mid,
            "cv":            cv,
            "std_chg":       std_chg,
            "lag1_acf":      lag1,
            "ema_thresh":    thresh,
            "slope":         slope,
            "mean_spread":   mean_spread,
            "trade_count":   trade_count,
            "mean_trade_qty": mean_trade_qty,
            "regime":        regime,
        })

    df = pd.DataFrame(rows)

    # Strategy scoring (higher = better market-making / MR candidate)
    #   Score = -lag1_acf (negative ACF = MR = good) + low CV (stable = good)
    #         + low ema_thresh relative to spread (tight MR + capturable spread)
    if not df.empty:
        df["mr_score"]    = -df["lag1_acf"]    # higher = more mean-reverting
        df["stab_score"]  = 1.0 / (df["cv"] + 1e-6)  # higher = more stable price
        df["spread_score"] = df["mean_spread"] / (df["std_chg"] + 1e-6)  # spread > noise = MM viable
        # Normalize each 0–1
        for col in ["mr_score", "stab_score", "spread_score"]:
            mn, mx = df[col].min(), df[col].max()
            df[col + "_n"] = (df[col] - mn) / (mx - mn + 1e-9)
        df["composite_score"] = (
            0.40 * df["mr_score_n"] +
            0.35 * df["stab_score_n"] +
            0.25 * df["spread_score_n"]
        )

    return df.sort_values("composite_score", ascending=False).reset_index(drop=True)


# ════════════════════════════════════════════════════════════════════════════
#  PAIR STAT-ARB ANALYSIS
# ════════════════════════════════════════════════════════════════════════════

def compute_pair_stats(prices_df: pd.DataFrame, zwindow: int = 50) -> pd.DataFrame:
    """
    For every intra-group pair: compute ratio mean/std, ratio ADF stationarity,
    and rolling z-score reversal quality.
    Returns a sorted DataFrame of best stat-arb pairs.
    """
    # Build pivot: timestamp × product
    pivot = (
        prices_df
        .groupby(["global_ts", "product"])["mid_price"]
        .first()
        .unstack("product")
    )

    rows = []
    for gname, members in GROUPS.items():
        avail = [m for m in members if m in pivot.columns]
        if len(avail) < 2:
            continue
        sub = pivot[avail].dropna()
        if len(sub) < 100:
            continue

        for a, b in combinations(avail, 2):
            ratio = sub[a] / sub[b]
            r_mean = float(ratio.mean())
            r_std  = float(ratio.std())
            r_cv   = r_std / abs(r_mean) if r_mean != 0 else float("inf")

            # Augmented Dickey-Fuller on ratio (stationarity test)
            try:
                from statsmodels.tsa.stattools import adfuller
                adf_p = float(adfuller(ratio.dropna(), maxlags=10)[1])
            except Exception:
                adf_p = float("nan")

            # Rolling z-score of ratio, measure how often it crosses ±1 (mean reversion quality)
            z = (ratio - ratio.rolling(zwindow).mean()) / (ratio.rolling(zwindow).std() + 1e-9)
            z_valid = z.dropna()
            # Count sign changes (proxy for MR frequency)
            if len(z_valid) > 10:
                sign_changes = int(((np.diff(np.sign(z_valid.values)) != 0)).sum())
                z_extreme    = float((z_valid.abs() > 2).mean())   # fraction of time |z|>2
                z_acf1       = float(np.corrcoef(z_valid.values[:-1], z_valid.values[1:])[0, 1]) if len(z_valid) > 2 else 0.0
                if np.isnan(z_acf1):
                    z_acf1 = 0.0
            else:
                sign_changes = 0
                z_extreme    = float("nan")
                z_acf1       = float("nan")

            # Correlation of levels (high corr → ratio more predictable)
            corr = float(np.corrcoef(sub[a].values, sub[b].values)[0, 1])

            rows.append({
                "group":       gname,
                "product_a":   a,
                "product_b":   b,
                "ratio_mean":  r_mean,
                "ratio_std":   r_std,
                "ratio_cv":    r_cv,
                "adf_pval":    adf_p,
                "z_sign_changes": sign_changes,
                "z_extreme_frac": z_extreme,
                "z_acf1":      z_acf1,
                "level_corr":  corr,
            })

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    # Score: lower CV = tighter ratio = better; lower ADF p-val = more stationary = better
    df["statarb_score"] = (
        (1 - df["ratio_cv"].clip(0, 1)) * 0.5 +
        (1 - df["adf_pval"].clip(0, 1).fillna(0.5)) * 0.3 +
        (-df["z_acf1"].fillna(0)) * 0.2  # negative z_acf1 = ratio MR
    )
    return df.sort_values("statarb_score", ascending=False).reset_index(drop=True)


# ════════════════════════════════════════════════════════════════════════════
#  CHART 01 – Group price time-series
# ════════════════════════════════════════════════════════════════════════════

def plot_01_group_prices(prices_df: pd.DataFrame, out: str):
    gnames = list(GROUPS.keys())
    nrows, ncols = 5, 2
    fig, axes = plt.subplots(nrows, ncols, figsize=(18, 4 * nrows))
    fig.suptitle("Round 5 – Price Time-Series by Group", fontsize=14, fontweight="bold")
    axes = axes.flatten()

    for idx, gname in enumerate(gnames):
        ax  = axes[idx]
        col = GROUP_COLORS[gname]
        members = GROUPS[gname]
        alphas  = np.linspace(1.0, 0.35, len(members))
        for prod, alpha in zip(members, alphas):
            mp = mid_series(prices_df, prod)
            if mp.empty:
                continue
            ax.plot(mp["global_ts"], mp["mid_price"],
                    lw=0.6, alpha=alpha, label=short(prod))
        ax.set_title(gname, fontsize=10, fontweight="bold", color=col)
        ax.set_ylabel(f"Price ({CURRENCY})", fontsize=7)
        ax.legend(fontsize=6, ncol=3)
        ax.set_xlabel("Global Tick", fontsize=7)

    for i in range(len(gnames), len(axes)):
        axes[i].set_visible(False)
    _save(fig, _out(out, "01_group_prices.png"), "01_group_prices.png")


# ════════════════════════════════════════════════════════════════════════════
#  CHART 02 – Regime / ACF per product
# ════════════════════════════════════════════════════════════════════════════

def plot_02_regime_acf(stats_df: pd.DataFrame, out: str):
    if stats_df.empty:
        return
    fig, axes = plt.subplots(1, 2, figsize=(18, 9))
    fig.suptitle("Product Regime Classification – ACF(lag-1) of Price Changes",
                 fontsize=13, fontweight="bold")

    # Left: bar chart sorted by lag1_acf
    s = stats_df.sort_values("lag1_acf")
    colors = []
    for g in s["group"]:
        colors.append(GROUP_COLORS.get(g, "#999999"))
    ax = axes[0]
    ax.barh(range(len(s)), s["lag1_acf"].values, color=colors, alpha=0.85, height=0.7)
    ax.set_yticks(range(len(s)))
    ax.set_yticklabels([f"{p.split('_')[-2]}_{p.split('_')[-1]}" if '_' in p else p
                        for p in s["product"]], fontsize=6)
    ax.axvline(0, color="black", lw=0.8)
    ax.axvline(-0.08, color="red", ls="--", lw=1.0, label="MR threshold (−0.08)")
    ax.axvline( 0.08, color="green", ls="--", lw=1.0, label="Trend threshold (+0.08)")
    ax.set_xlabel("Lag-1 ACF  (negative = mean-reverting)")
    ax.set_title("All Products – Sorted by ACF")
    ax.legend(fontsize=7)

    # Add group legend
    from matplotlib.patches import Patch
    patches = [Patch(facecolor=c, label=g) for g, c in GROUP_COLORS.items()]
    ax.legend(handles=patches + [
        plt.Line2D([0], [0], color="red",   ls="--", label="MR threshold"),
        plt.Line2D([0], [0], color="green", ls="--", label="Trend threshold"),
    ], fontsize=6, loc="lower right")

    # Right: scatter volatility vs ACF
    ax2 = axes[1]
    for g, grp in stats_df.groupby("group"):
        ax2.scatter(grp["lag1_acf"], grp["std_chg"],
                    color=GROUP_COLORS.get(g, "#999999"),
                    s=55, alpha=0.85, label=g, zorder=5)
        for _, row in grp.iterrows():
            ax2.annotate(short(row["product"]),
                         (row["lag1_acf"], row["std_chg"]),
                         fontsize=5, ha="left", va="bottom")
    ax2.axvline(0, color="black", lw=0.7)
    ax2.axvline(-0.08, color="red",   ls="--", lw=0.8)
    ax2.axvline( 0.08, color="green", ls="--", lw=0.8)
    ax2.set_xlabel("Lag-1 ACF"); ax2.set_ylabel("Std of Price Changes")
    ax2.set_title("Volatility vs Mean-Reversion\n(bottom-left = best MM targets)")
    ax2.legend(fontsize=6, ncol=2)

    _save(fig, _out(out, "02_regime_acf.png"), "02_regime_acf.png")


# ════════════════════════════════════════════════════════════════════════════
#  CHART 03 – EMA deviation thresholds (top 20 MR products)
# ════════════════════════════════════════════════════════════════════════════

def plot_03_ema_deviation(prices_df: pd.DataFrame, stats_df: pd.DataFrame,
                           out: str, ema_win: int = 20, top_n: int = 20):
    if stats_df.empty:
        return
    # Pick the top_n most mean-reverting
    top = stats_df.nsmallest(top_n, "lag1_acf")["product"].tolist()
    ncols = 4
    nrows = math.ceil(len(top) / ncols)
    fig, axes = plt.subplots(nrows, ncols, figsize=(5 * ncols, 3.2 * nrows))
    axes = np.array(axes).flatten()
    fig.suptitle(f"EMA-{ema_win} Deviation – Top {top_n} Mean-Reverting Products",
                 fontsize=13, fontweight="bold")

    for idx, prod in enumerate(top):
        ax  = axes[idx]
        mp  = mid_series(prices_df, prod)
        if mp.empty:
            ax.set_title(prod, fontsize=7); continue
        vals = mp["mid_price"].values
        ema  = pd.Series(vals).ewm(span=ema_win, adjust=False).mean().values
        dev  = vals - ema
        ts   = mp["global_ts"].values
        p90  = float(np.percentile(np.abs(dev), 90))
        grp  = product_to_group(prod)
        col  = GROUP_COLORS.get(grp, "#4477AA")

        ax.fill_between(ts, dev, 0, where=(dev > 0), alpha=0.4, color="#EE6677")
        ax.fill_between(ts, dev, 0, where=(dev <= 0), alpha=0.4, color="#228833")
        ax.plot(ts, dev, lw=0.4, color="#334455")
        ax.axhline(0,     color="black", lw=0.6)
        ax.axhline( p90,  color="red",   ls="--", lw=1.0, label=f"p90={p90:.1f}")
        ax.axhline(-p90,  color="red",   ls="--", lw=1.0)
        g_row = stats_df[stats_df["product"] == prod]
        acf1  = g_row["lag1_acf"].values[0] if len(g_row) else float("nan")
        ax.set_title(f"{prod.replace(grp+'_','')}\n[{grp}] acf={acf1:.3f}", fontsize=7, color=col)
        ax.legend(fontsize=6)
        ax.set_ylabel("Dev", fontsize=6)

    for i in range(len(top), len(axes)):
        axes[i].set_visible(False)
    _save(fig, _out(out, "03_ema_deviation.png"), "03_ema_deviation.png")


# ════════════════════════════════════════════════════════════════════════════
#  CHART 04 – Spread summary
# ════════════════════════════════════════════════════════════════════════════

def plot_04_spread_summary(stats_df: pd.DataFrame, out: str):
    if stats_df.empty:
        return
    fig, axes = plt.subplots(2, 5, figsize=(20, 9))
    fig.suptitle("Mean Bid-Ask Spread by Group", fontsize=13, fontweight="bold")
    axes = axes.flatten()

    for idx, gname in enumerate(GROUPS.keys()):
        ax   = axes[idx]
        grp  = stats_df[stats_df["group"] == gname].sort_values("mean_spread")
        if grp.empty:
            ax.set_title(gname, fontsize=8); continue
        labels = [short(p) for p in grp["product"]]
        vals   = grp["mean_spread"].values
        cols   = [GROUP_COLORS.get(gname, "#4477AA")] * len(vals)
        bars = ax.bar(labels, vals, color=cols, alpha=0.85)
        # Overlay std_chg for reference
        ax2 = ax.twinx()
        ax2.plot(labels, grp["std_chg"].values, "k--o", ms=4, lw=1.0, alpha=0.6,
                 label="σ(Δprice)")
        ax2.set_ylabel("σ(Δprice)", fontsize=6)
        ax2.legend(fontsize=6)
        ax.set_title(gname, fontsize=8, fontweight="bold")
        ax.set_ylabel("Mean Spread", fontsize=7)
        ax.set_xticklabels(labels, rotation=30, ha="right", fontsize=7)
        # Annotate with spread/noise ratio
        for bar, row in zip(bars, grp.itertuples()):
            ratio = row.mean_spread / (row.std_chg + 1e-9)
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.1,
                    f"{ratio:.2f}x", ha="center", va="bottom", fontsize=6, color="navy")

    _save(fig, _out(out, "04_spread_summary.png"), "04_spread_summary.png")


# ════════════════════════════════════════════════════════════════════════════
#  CHART 05 – Stat-arb pair ratio stability
# ════════════════════════════════════════════════════════════════════════════

def plot_05_statarb_ratios(pair_df: pd.DataFrame, prices_df: pd.DataFrame, out: str,
                            top_n: int = 16):
    if pair_df.empty:
        print("  ⚠  No pair data – skipping statarb chart"); return
    top_pairs = pair_df.head(top_n)
    pivot = (
        prices_df
        .groupby(["global_ts", "product"])["mid_price"]
        .first()
        .unstack("product")
    )
    ncols = 4
    nrows = math.ceil(len(top_pairs) / ncols)
    fig, axes = plt.subplots(nrows, ncols, figsize=(5 * ncols, 3.2 * nrows))
    axes = np.array(axes).flatten()
    fig.suptitle(f"Top-{top_n} Stat-Arb Pair Ratios  (A/B over time)",
                 fontsize=13, fontweight="bold")

    for idx, row in top_pairs.iterrows():
        if idx >= len(axes):
            break
        ax = axes[idx]
        a, b = row["product_a"], row["product_b"]
        if a not in pivot.columns or b not in pivot.columns:
            ax.set_visible(False); continue
        sub = pivot[[a, b]].dropna()
        ratio = sub[a] / sub[b]
        ts    = sub.index.values

        ax.plot(ts, ratio, lw=0.5, color=GROUP_COLORS.get(row["group"], "#4477AA"), alpha=0.8)
        ax.axhline(ratio.mean(), color="red",   lw=1.2, ls="--", label=f"μ={ratio.mean():.4f}")
        ax.axhline(ratio.mean() + ratio.std(), color="orange", lw=0.8, ls=":")
        ax.axhline(ratio.mean() - ratio.std(), color="orange", lw=0.8, ls=":")
        ax.set_title(
            f"{short(a)}/{short(b)}  [{row['group']}]\n"
            f"CV={row['ratio_cv']:.3f}  ADF-p={row['adf_pval']:.3f}  score={row['statarb_score']:.3f}",
            fontsize=7
        )
        ax.legend(fontsize=6)
        ax.set_ylabel("Ratio", fontsize=6)

    for i in range(len(top_pairs), len(axes)):
        axes[i].set_visible(False)
    _save(fig, _out(out, "05_statarb_ratios.png"), "05_statarb_ratios.png")


# ════════════════════════════════════════════════════════════════════════════
#  CHART 06 – Stat-arb rolling z-scores
# ════════════════════════════════════════════════════════════════════════════

def plot_06_statarb_zscores(pair_df: pd.DataFrame, prices_df: pd.DataFrame,
                              out: str, zwindow: int = 50, top_n: int = 8):
    if pair_df.empty:
        return
    top_pairs = pair_df.head(top_n)
    pivot = (
        prices_df
        .groupby(["global_ts", "product"])["mid_price"]
        .first()
        .unstack("product")
    )
    ncols = 2
    nrows = math.ceil(len(top_pairs) / ncols)
    fig, axes = plt.subplots(nrows, ncols, figsize=(12, 3.5 * nrows))
    axes = np.array(axes).flatten()
    fig.suptitle(f"Top-{top_n} Pair Rolling Z-Scores  (window={zwindow})\n"
                 "(±2 = trade signal; |z|>2 and reverting = entry)",
                 fontsize=12, fontweight="bold")

    for idx, row in top_pairs.iterrows():
        if idx >= len(axes):
            break
        ax = axes[idx]
        a, b = row["product_a"], row["product_b"]
        if a not in pivot.columns or b not in pivot.columns:
            ax.set_visible(False); continue
        sub = pivot[[a, b]].dropna()
        ratio = sub[a] / sub[b]
        ts    = sub.index.values
        roll_mu  = ratio.rolling(zwindow).mean()
        roll_std = ratio.rolling(zwindow).std()
        z = (ratio - roll_mu) / (roll_std + 1e-9)

        ax.fill_between(ts, z, 0, where=(z > 0),  alpha=0.35, color="#EE6677")
        ax.fill_between(ts, z, 0, where=(z <= 0), alpha=0.35, color="#228833")
        ax.plot(ts, z, lw=0.4, color="#334455")
        ax.axhline( 2, color="red",   ls="--", lw=1.0, label="+2σ")
        ax.axhline(-2, color="green", ls="--", lw=1.0, label="−2σ")
        ax.axhline( 1, color="orange", ls=":", lw=0.7)
        ax.axhline(-1, color="orange", ls=":", lw=0.7)
        ax.axhline( 0, color="black", lw=0.6)
        ax.set_ylim(-5, 5)
        ax.set_title(f"{short(a)}/{short(b)}  [{row['group']}]  ADF-p={row['adf_pval']:.3f}",
                     fontsize=8)
        ax.legend(fontsize=6)
        ax.set_ylabel("Z-score", fontsize=6)

    for i in range(len(top_pairs), len(axes)):
        axes[i].set_visible(False)
    _save(fig, _out(out, "06_statarb_zscores.png"), "06_statarb_zscores.png")


# ════════════════════════════════════════════════════════════════════════════
#  CHART 07 – Volatility ranking (MM viability)
# ════════════════════════════════════════════════════════════════════════════

def plot_07_volatility_ranking(stats_df: pd.DataFrame, out: str):
    if stats_df.empty:
        return
    fig, axes = plt.subplots(1, 2, figsize=(18, 10))
    fig.suptitle("Volatility Ranking – Market-Making Viability\n"
                 "(spread/noise ratio > 1 = profitable MM)",
                 fontsize=13, fontweight="bold")

    s = stats_df.copy()
    s["spread_noise_ratio"] = s["mean_spread"] / (s["std_chg"] + 1e-9)
    s = s.sort_values("spread_noise_ratio", ascending=False)

    colors = [GROUP_COLORS.get(g, "#999999") for g in s["group"]]
    short_labels = [f"{p.split('_')[-2]}_{p.split('_')[-1]}" if p.count('_') >= 2
                    else p for p in s["product"]]

    ax = axes[0]
    bars = ax.barh(range(len(s)), s["spread_noise_ratio"].values, color=colors, alpha=0.85)
    ax.axvline(1.0, color="red", ls="--", lw=1.2, label="Break-even (spread = noise)")
    ax.set_yticks(range(len(s)))
    ax.set_yticklabels(short_labels, fontsize=6)
    ax.set_xlabel("Spread / σ(ΔPrice)  [ratio]")
    ax.set_title("Spread-to-Noise Ratio\n(higher = better MM candidate)")
    ax.legend(fontsize=7)

    # Annotate spread value
    for bar, row in zip(bars, s.itertuples()):
        ax.text(bar.get_width() + 0.01, bar.get_y() + bar.get_height() / 2,
                f"spr={row.mean_spread:.1f}", va="center", fontsize=5.5, color="black")

    # Right: composite score
    s2 = stats_df.sort_values("composite_score", ascending=False)
    colors2 = [GROUP_COLORS.get(g, "#999999") for g in s2["group"]]
    short2  = [f"{p.split('_')[-2]}_{p.split('_')[-1]}" if p.count('_') >= 2
               else p for p in s2["product"]]
    ax2 = axes[1]
    ax2.barh(range(len(s2)), s2["composite_score"].values, color=colors2, alpha=0.85)
    ax2.set_yticks(range(len(s2)))
    ax2.set_yticklabels(short2, fontsize=6)
    ax2.set_xlabel("Composite Strategy Score  [0–1]")
    ax2.set_title("Overall Strategy Score\n(MR × stability × spread/noise)")

    # Group legend
    from matplotlib.patches import Patch
    patches = [Patch(facecolor=c, label=g) for g, c in GROUP_COLORS.items()]
    axes[0].legend(handles=patches + [
        plt.Line2D([0], [0], color="red", ls="--", label="Break-even")],
        fontsize=6, loc="lower right")

    _save(fig, _out(out, "07_volatility_ranking.png"), "07_volatility_ranking.png")


# ════════════════════════════════════════════════════════════════════════════
#  CHART 08 – Strategy heatmap (group × metric)
# ════════════════════════════════════════════════════════════════════════════

def plot_08_strategy_heatmap(stats_df: pd.DataFrame, out: str):
    if stats_df.empty:
        return
    metrics = ["lag1_acf", "std_chg", "mean_spread", "composite_score"]
    metric_labels = ["ACF(1)\n(neg=MR)", "σ(ΔP)\n(noise)", "Spread", "Score"]

    fig, axes = plt.subplots(1, len(GROUPS), figsize=(22, 8))
    fig.suptitle("Per-Group Strategy Heatmap\n"
                 "(composite_score: higher = prioritise for trading)",
                 fontsize=13, fontweight="bold")

    for idx, (gname, members) in enumerate(GROUPS.items()):
        ax  = axes[idx]
        grp = stats_df[stats_df["group"] == gname].set_index("product")
        avail = [m for m in members if m in grp.index]
        if not avail:
            ax.set_visible(False); continue
        mat = grp.loc[avail, metrics].values.astype(float)
        # Normalise each column 0-1 for visual
        for c in range(mat.shape[1]):
            col = mat[:, c]
            mn, mx = np.nanmin(col), np.nanmax(col)
            if mx > mn:
                mat[:, c] = (col - mn) / (mx - mn)
        im = ax.imshow(mat, aspect="auto", cmap="RdYlGn", vmin=0, vmax=1)
        ax.set_xticks(range(len(metrics)))
        ax.set_xticklabels(metric_labels, fontsize=7, rotation=30, ha="right")
        ax.set_yticks(range(len(avail)))
        ax.set_yticklabels([short(p) for p in avail], fontsize=8)
        ax.set_title(gname, fontsize=8, fontweight="bold",
                     color=GROUP_COLORS.get(gname, "black"))
        plt.colorbar(im, ax=ax, fraction=0.04, pad=0.02)

    _save(fig, _out(out, "08_strategy_heatmap.png"), "08_strategy_heatmap.png")


# ════════════════════════════════════════════════════════════════════════════
#  CHART 09 – Trade volume per product
# ════════════════════════════════════════════════════════════════════════════

def plot_09_trade_volume(trades_df: pd.DataFrame, out: str):
    if trades_df.empty:
        print("  ⚠  No trade data – skipping trade volume chart"); return

    vol = (trades_df.groupby("symbol")["quantity"]
           .agg(["count", "sum", "mean"])
           .reset_index()
           .rename(columns={"symbol": "product", "count": "n_trades",
                            "sum": "total_vol", "mean": "avg_qty"}))
    vol["group"] = vol["product"].apply(product_to_group)
    vol = vol[vol["group"] != "UNKNOWN"]
    vol = vol.sort_values("total_vol", ascending=False)

    fig, axes = plt.subplots(1, 2, figsize=(18, 8))
    fig.suptitle("Trade Activity per Product", fontsize=13, fontweight="bold")

    colors = [GROUP_COLORS.get(g, "#999999") for g in vol["group"]]
    short_labels = [f"{p.split('_')[-2]}_{p.split('_')[-1]}" if p.count('_') >= 2
                    else p for p in vol["product"]]

    ax = axes[0]
    ax.barh(range(len(vol)), vol["total_vol"].values, color=colors, alpha=0.85)
    ax.set_yticks(range(len(vol)))
    ax.set_yticklabels(short_labels, fontsize=6)
    ax.set_xlabel("Total Volume Traded")
    ax.set_title("Total Trade Volume\n(proxy for liquidity)")

    ax2 = axes[1]
    ax2.barh(range(len(vol)), vol["n_trades"].values, color=colors, alpha=0.85)
    ax2.set_yticks(range(len(vol)))
    ax2.set_yticklabels(short_labels, fontsize=6)
    ax2.set_xlabel("Number of Trades")
    ax2.set_title("Trade Frequency\n(higher = more active market)")

    from matplotlib.patches import Patch
    patches = [Patch(facecolor=c, label=g) for g, c in GROUP_COLORS.items()]
    axes[0].legend(handles=patches, fontsize=6, loc="lower right")

    _save(fig, _out(out, "09_trade_volume.png"), "09_trade_volume.png")


# ════════════════════════════════════════════════════════════════════════════
#  CHART 10 – Intra-group correlation matrices
# ════════════════════════════════════════════════════════════════════════════

def plot_10_group_correlation(prices_df: pd.DataFrame, out: str):
    pivot = (
        prices_df
        .groupby(["global_ts", "product"])["mid_price"]
        .first()
        .unstack("product")
    )
    nrows, ncols = 2, 5
    fig, axes = plt.subplots(nrows, ncols, figsize=(20, 8))
    fig.suptitle("Intra-Group Price-Level Correlation Matrices",
                 fontsize=13, fontweight="bold")
    axes = axes.flatten()

    for idx, gname in enumerate(GROUPS.keys()):
        ax      = axes[idx]
        members = GROUPS[gname]
        avail   = [m for m in members if m in pivot.columns]
        if len(avail) < 2:
            ax.set_title(gname, fontsize=8); continue
        sub  = pivot[avail].dropna()
        corr = sub.corr()
        labels = [short(p) for p in avail]
        im = ax.imshow(corr.values, cmap="RdYlGn", vmin=-1, vmax=1, aspect="auto")
        ax.set_xticks(range(len(labels)))
        ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=7)
        ax.set_yticks(range(len(labels)))
        ax.set_yticklabels(labels, fontsize=7)
        for i in range(len(labels)):
            for j in range(len(labels)):
                ax.text(j, i, f"{corr.values[i,j]:.2f}",
                        ha="center", va="center", fontsize=6,
                        color="black" if abs(corr.values[i,j]) < 0.7 else "white")
        avg_corr = corr.values[np.triu_indices_from(corr.values, k=1)].mean()
        ax.set_title(f"{gname}\navg_corr={avg_corr:.3f}", fontsize=8,
                     fontweight="bold", color=GROUP_COLORS.get(gname, "black"))
        plt.colorbar(im, ax=ax, fraction=0.04, pad=0.02)

    _save(fig, _out(out, "10_group_correlation.png"), "10_group_correlation.png")


# ════════════════════════════════════════════════════════════════════════════
#  REPORTS
# ════════════════════════════════════════════════════════════════════════════

def write_reports(stats_df: pd.DataFrame, pair_df: pd.DataFrame,
                   prices_df: pd.DataFrame, out: str):
    SEP = "=" * 72

    # ── 00_summary.txt ────────────────────────────────────────────────────
    L = [
        SEP,
        "IMC Prosperity 4 – Round 5 Analysis Summary",
        f"Products: 50 across 10 groups  |  Position limit: {POSITION_LIMIT} each",
        SEP, "",
    ]

    L.append("── REGIME CLASSIFICATION ──")
    for regime in ["MEAN_REVERT", "RANDOM_WALK", "TRENDING"]:
        prods = stats_df[stats_df["regime"] == regime]["product"].tolist()
        L.append(f"  {regime:15s} ({len(prods):2d} products): {', '.join(short(p) for p in prods)}")
    L.append("")

    L.append("── TOP 15 STRATEGY TARGETS (composite score) ──")
    top15 = stats_df.head(15)
    for _, r in top15.iterrows():
        L.append(
            f"  {r['product']:<42s}  "
            f"acf={r['lag1_acf']:+.3f}  "
            f"spr={r['mean_spread']:.1f}  "
            f"σΔ={r['std_chg']:.1f}  "
            f"score={r['composite_score']:.3f}  "
            f"[{r['regime']}]"
        )
    L.append("")

    L.append("── PER-GROUP SUMMARY ──")
    for gname in GROUPS.keys():
        grp  = stats_df[stats_df["group"] == gname]
        if grp.empty:
            continue
        best = grp.iloc[0]
        avg_acf  = grp["lag1_acf"].mean()
        avg_spr  = grp["mean_spread"].mean()
        avg_std  = grp["std_chg"].mean()
        L.append(f"\n  {gname}")
        L.append(f"    avg_acf={avg_acf:+.3f}  avg_spread={avg_spr:.1f}  avg_σΔ={avg_std:.1f}")
        L.append(f"    best_product: {best['product']}  (score={best['composite_score']:.3f})")
        for _, r in grp.iterrows():
            L.append(
                f"      {short(r['product']):<20s}"
                f"  acf={r['lag1_acf']:+.4f}"
                f"  spr/σ={r['mean_spread']/(r['std_chg']+1e-9):.2f}"
                f"  score={r['composite_score']:.3f}"
                f"  {r['regime']}"
            )
    L.append("")

    L.append("── TOP 20 STAT-ARB PAIRS ──")
    if not pair_df.empty:
        for _, r in pair_df.head(20).iterrows():
            L.append(
                f"  {r['product_a']:<40s} / {r['product_b']:<40s}"
                f"  [{r['group']}]"
                f"  CV={r['ratio_cv']:.4f}"
                f"  ADF-p={r['adf_pval']:.3f}"
                f"  score={r['statarb_score']:.3f}"
            )
    else:
        L.append("  (No pair data available)")
    L.append("")

    L += [
        "── NOTES ──",
        "  • Position limit = 10 for ALL products.",
        "  • With limit 10, MM PnL per product is small – prioritise best scorers.",
        "  • Stat-arb: long cheap / short expensive within group. Ratio CV < 5% = tightest.",
        "  • MEAN_REVERT products: use EMA deviation entry with tight exits.",
        "  • RANDOM_WALK products: pure MM with symmetric spreads.",
        "  • TRENDING products: skew inventory or skip entirely.",
        "",
        "── FILES GENERATED ──",
        *[f"  {f}" for f in sorted(os.listdir(out))],
        "",
        "── NEXT STEP ──",
        "Upload all PNGs + 00_summary.txt to Claude.",
        "Ask: 'Here are my Round 5 analysis results – build the cherry-picking trader.py'",
        "",
        SEP,
    ]
    text = "\n".join(L)
    with open(_out(out, "00_summary.txt"), "w") as f:
        f.write(text)
    print("\n" + text)
    print("  ✓ 00_summary.txt")

    # ── 00_parameter_report.txt ────────────────────────────────────────────
    P = [
        SEP,
        "IMC Prosperity 4 – Round 5 Parameter Report",
        "Per-product recommended trading parameters",
        SEP, "",
        "COLUMN GUIDE:",
        "  ema_thresh  : trade when mid deviates > thresh from EMA (MR entry)",
        "  take_edge   : aggressive take limit (≈40% of thresh)",
        "  mm_halfspread: post limit orders at ±mm_halfspread from mid",
        "  strategy    : recommended approach",
        "",
    ]

    # Group-by-group parameter recommendations
    for gname in GROUPS.keys():
        grp = stats_df[stats_df["group"] == gname].sort_values("composite_score", ascending=False)
        if grp.empty:
            continue
        P.append(f"── {gname} ──")
        for _, r in grp.iterrows():
            spr   = r["mean_spread"]
            thresh = r["ema_thresh"]
            take  = max(1, round(thresh * 0.40))
            mm_hs = max(1, round(spr * 0.55))
            if r["regime"] == "MEAN_REVERT":
                strat = "MR_SCALP"
            elif r["std_chg"] < spr * 0.8:
                strat = "MARKET_MAKE"
            else:
                strat = "SKIP_OR_WIDE_MM"
            P.append(
                f"  {r['product']:<42s}"
                f"  ema_thresh={thresh:6.1f}"
                f"  take_edge={take:4d}"
                f"  mm_halfspread={mm_hs:4d}"
                f"  score={r['composite_score']:.3f}"
                f"  → {strat}"
            )
        P.append("")

    if not pair_df.empty:
        P.append("── STAT-ARB PAIRS (top 10, threshold = 1.5σ entry / 0.5σ exit) ──")
        for _, r in pair_df.head(10).iterrows():
            ratio_entry_hi = r["ratio_mean"] + 1.5 * r["ratio_std"]
            ratio_entry_lo = r["ratio_mean"] - 1.5 * r["ratio_std"]
            P.append(
                f"  {r['product_a']:<38s} / {r['product_b']:<38s}"
                f"  ratio_mean={r['ratio_mean']:.4f}"
                f"  ±1.5σ=[{ratio_entry_lo:.4f}, {ratio_entry_hi:.4f}]"
                f"  ADF-p={r['adf_pval']:.3f}"
            )
        P.append("")

    P += [
        "── POSITION MANAGEMENT NOTES ──",
        f"  Position limit: {POSITION_LIMIT} per product (hard enforced by exchange).",
        "  With limit 10, do NOT mix aggressive MR + stat-arb on same product.",
        "  Recommend: pick top 10–15 products, trade each with dedicated logic.",
        "  Stat-arb pairs: hedge ratio 1:1 when ratio_cv < 5%.",
        "  Risk: if pattern breaks (new regime), close positions immediately.",
        "",
        SEP,
    ]
    with open(_out(out, "00_parameter_report.txt"), "w") as f:
        f.write("\n".join(P))
    print("  ✓ 00_parameter_report.txt")


# ════════════════════════════════════════════════════════════════════════════
#  MAIN
# ════════════════════════════════════════════════════════════════════════════

def main():
    ap = argparse.ArgumentParser(
        description="IMC Prosperity 4 – Round 5 Master Analyzer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("--data-dir",   default=None,
                    help="Folder with price/trade CSVs.")
    ap.add_argument("--prices",     nargs="+", default=[],
                    help="Price CSV file(s) in day order.")
    ap.add_argument("--trades",     nargs="+", default=[],
                    help="Trade CSV file(s) in day order.")
    ap.add_argument("--start-day",  type=int, default=2,
                    help="Day label for first file (default: 2 for R5 data).")
    ap.add_argument("--ema-window", type=int, default=20,
                    help="EMA window for MR analysis (default 20).")
    ap.add_argument("--zwindow",    type=int, default=50,
                    help="Rolling window for z-score stat-arb (default 50).")
    ap.add_argument("--output",     default="./r5_output",
                    help="Output directory. Default: ./r5_output")
    ap.add_argument("--quiet", "-q", action="store_true")
    args = ap.parse_args()

    os.makedirs(args.output, exist_ok=True)

    print(f"\n{'─'*64}")
    print(f"  IMC Prosperity 4 – Round 5 Analyzer")
    print(f"  Products: 50 across 10 groups  |  Pos limit: {POSITION_LIMIT}")
    print(f"  Output:   {os.path.abspath(args.output)}")
    print(f"{'─'*64}\n")

    # ── Resolve files ──
    price_files = list(args.prices)
    trade_files = list(args.trades)
    if args.data_dir:
        pf, tf = discover_csvs(args.data_dir)
        if not price_files: price_files = pf
        if not trade_files: trade_files = tf
        print(f"  Auto-discovered in {args.data_dir}:")
        print(f"    prices: {price_files}")
        print(f"    trades: {trade_files}\n")

    if not price_files:
        sys.exit("ERROR: No price files found. Use --prices or --data-dir.")

    # ── Load ──
    print("▶ Loading price CSVs …")
    prices_df = load_many(price_files, load_prices, base_day=args.start_day)
    if prices_df.empty:
        sys.exit("ERROR: No price data loaded.")
    n_prods = prices_df["product"].nunique()
    print(f"  {len(prices_df):,} rows | {prices_df['day'].nunique()} day(s) | {n_prods} products\n")

    trades_df = pd.DataFrame()
    if trade_files:
        print("▶ Loading trade CSVs …")
        trades_df = load_many(trade_files, load_trades, base_day=args.start_day)
        print(f"  {len(trades_df):,} trades\n")

    # ── Product stats ──
    print("▶ Computing per-product statistics …")
    stats_df = compute_product_stats(prices_df, trades_df, ema_win=args.ema_window)
    stats_df.to_csv(_out(args.output, "product_strategy_scores.csv"), index=False)
    print("  ✓ product_strategy_scores.csv\n")

    # ── Pair stats ──
    print("▶ Computing stat-arb pair statistics …")
    try:
        import statsmodels  # noqa: F401
        pair_df = compute_pair_stats(prices_df, zwindow=args.zwindow)
    except ImportError:
        print("  ⚠  statsmodels not installed – ADF test skipped (pip install statsmodels)")
        pair_df = compute_pair_stats.__wrapped__(prices_df, zwindow=args.zwindow) \
            if hasattr(compute_pair_stats, '__wrapped__') else pd.DataFrame()
        # Re-run without ADF
        pair_df = compute_pair_stats(prices_df, zwindow=args.zwindow)
    if not pair_df.empty:
        pair_df.to_csv(_out(args.output, "statarb_pairs.csv"), index=False)
        print(f"  ✓ statarb_pairs.csv  ({len(pair_df)} pairs across {pair_df['group'].nunique()} groups)\n")

    # ── Charts ──
    print("▶ [01/10] Group price time-series …")
    plot_01_group_prices(prices_df, args.output)

    print("▶ [02/10] Regime / ACF …")
    plot_02_regime_acf(stats_df, args.output)

    print("▶ [03/10] EMA deviation thresholds …")
    plot_03_ema_deviation(prices_df, stats_df, args.output, ema_win=args.ema_window)

    print("▶ [04/10] Spread summary …")
    plot_04_spread_summary(stats_df, args.output)

    print("▶ [05/10] Stat-arb pair ratios …")
    plot_05_statarb_ratios(pair_df, prices_df, args.output)

    print("▶ [06/10] Stat-arb z-scores …")
    plot_06_statarb_zscores(pair_df, prices_df, args.output, zwindow=args.zwindow)

    print("▶ [07/10] Volatility ranking …")
    plot_07_volatility_ranking(stats_df, args.output)

    print("▶ [08/10] Strategy heatmap …")
    plot_08_strategy_heatmap(stats_df, args.output)

    print("▶ [09/10] Trade volume …")
    plot_09_trade_volume(trades_df, args.output)

    print("▶ [10/10] Group correlation matrices …")
    plot_10_group_correlation(prices_df, args.output)

    # ── Reports ──
    print("\n▶ Writing reports …\n")
    write_reports(stats_df, pair_df, prices_df, args.output)

    print(f"\n{'─'*64}")
    print(f"  ✓  All outputs in: {os.path.abspath(args.output)}/")
    print(f"{'─'*64}\n")
    print("✅  Done. Upload all PNGs + 00_summary.txt to Claude.")
    print("    Suggested prompt: 'Build me a cherry-picking Round 5 trader.py based on these results'")


if __name__ == "__main__":
    main()
