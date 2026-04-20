# =============================================================================
# IMC Prosperity 4 — Round 1  |  153649_improved.py
# =============================================================================
#
# ── WHY EACH PREVIOUS VERSION SCORED WHAT IT SCORED ─────────────────────────
#
#  Bot       Total   ROOT    OSMIUM  ROOT pos  OSMIUM pos
#  180041    7 286   5 847   1 439      80        ±20
#  150676      995   -657    1 652      17        ±40
#  153649    2 688   2 070     618      61        ±15
#
# ROOT earnings come almost entirely from TREND (price rises ~1 000/day):
#   PnL ≈ position_held × price_rise = position × 1 000
#
# OSMIUM earnings come from SPREAD (price is flat, collect bid-ask edge):
#   PnL ≈ round_trip_fills × avg_spread_earned
#
# ── CHANGE 1 — ROOT: market-take immediately, don't wait for passive fills ──
#
# Old code (153649): passive limit buy at mid-2 → fills slowly across the day
#   • 12 fills spread from ts=6400 to ts=99500
#   • avg buy price = 12 055  (bought LATE, price already risen)
#   • only reached position 61 by end of day
#
# 180041 code: takes ALL available ask-side volume at ts=0,100,200
#   • reaches position 80 by ts=200 (3rd tick!)
#   • avg buy price = 12 009  (bought at day-START, lowest price)
#   • holds full 80 for ~99 700 ticks while price rises 991 points
#
# MATHEMATICAL BASIS:
#   Every tick you wait to enter, you miss 0.1 points of trend on each unit.
#   Entering at ts=0 vs ts=50 000 (mid-day): 50 000 × 0.1 = 5 000 missed per unit.
#   Paying the ask spread (~17 ticks) ONCE is trivially cheap vs 5 000 missed trend.
#   Trend PnL 180041: 80 × (13000 − 12009) = 79 280
#   Trend PnL 153649: 61 × (13000 − 12056) = 57 584
#   Difference = 21 696 seashells — purely from slower entry and smaller position.
#
# FIX: On every tick scan all ask levels from cheapest to most expensive.
#      Take (buy) every unit available until we hit the 80-unit limit.
#      Never send a sell order on ROOT (price is going up, never sell).
#
# ── CHANGE 2 — OSMIUM: add an aggressive market-taking layer ─────────────────
#
# Old code (153649): pure passive quoting at SMA±2
#   • 162 fills, avg buy 9997.9, avg sell 10001.9
#   • spread earned per round-trip: 4.0 ticks
#   • total OSMIUM PnL: 618
#
# 150676 code: market-take when ask < EMA−1 or bid > EMA+1, THEN passive
#   • 186 buys at avg 9994.6, 169 sells at avg 10003.6
#   • spread earned per round-trip: 9.0 ticks (2.25× larger!)
#   • total OSMIUM PnL: 1 652
#
# WHY THE HYBRID WINS:
#   When another bot submits a cheap ask (ask ≤ EMA−1), that is a mispriced
#   order.  Taking it immediately locks in a guaranteed profit without queue
#   risk.  153649's passive-only approach misses these opportunities entirely.
#   avg buy price gap: 9997.9 − 9994.6 = 3.3 ticks better for 150676
#   Over 186 fills: 186 × 3.3 = 614 seashells of free money left on the table.
#
# FIX: Before passive quoting, scan asks for any price ≤ EMA−1 (buy them)
#      and scan bids for any price ≥ EMA+1 (sell to them).
#
# ── CHANGE 3 — OSMIUM: tighten passive spread from 2 → 1 ────────────────────
#
# Data-driven analysis (SMA-50 deviations across 3 days):
#   |mid − SMA| distribution:
#     mean = 1.41, stdev = 1.23, median = 1.10
#   Fill probability (fraction of ticks where |mid−SMA| ≥ spread):
#     spread=1 → 54.2% of ticks  (fills very frequently)
#     spread=2 → 23.6% of ticks
#     spread=3 → 10.0% of ticks
#   Simulated 3-day PnL (hybrid strategy, skew=0):
#     spread=1 → 13 197  ← best
#     spread=2 → 12 278
#     spread=3 →  9 781
#   Both spread=1 and spread=2 place quotes INSIDE the book 96–100% of ticks
#   (queue priority confirmed), so spread=1 is strictly better in simulation.
#
# ── CHANGE 4 — OSMIUM: replace SMA with slow EMA (alpha = 0.05) ─────────────
#
# SMA-50 ≡ EMA with α = 2/(50+1) = 0.039  (mathematically almost identical).
# EMA is computationally cheaper (no list needed) and equivalent in smoothness.
# We use alpha=0.05 (slightly more responsive than SMA-50) matching 150676's
# best-performing OSMIUM setup.  This also removes the osmium_prices list from
# traderData, reducing serialisation overhead.
#
# =============================================================================

from datamodel import OrderDepth, TradingState, Order
from typing import List
import jsonpickle
import math

# =============================================================================
# POSITION LIMITS
# =============================================================================
POSITION_LIMITS = {
    "INTARIAN_PEPPER_ROOT": 80,
    "ASH_COATED_OSMIUM":    80,
}

# =============================================================================
# INTARIAN_PEPPER_ROOT — pure long accumulation via market taking
#
# No parameters to tune: just take every ask until position = +80.
# We never sell. Every unit held earns ~0.1 ticks/tick of trend.
# =============================================================================

# =============================================================================
# ASH_COATED_OSMIUM — hybrid: aggressive takes + tight passive quoting
#
# OSMIUM_EMA_ALPHA = 0.05
#   Controls how fast the EMA tracks price changes.
#   Lower  = smoother, slower to react (better for stable prices).
#   Higher = more reactive (tracks noise, leads to worse fair value).
#   0.05 ≈ SMA-39, which is close to SMA-50 used before.
#   Range to experiment: 0.02–0.10.
#
# OSMIUM_TAKE_EDGE = 1
#   Take (buy/sell aggressively) when mispricing ≥ this many ticks from EMA.
#   ask ≤ EMA − TAKE_EDGE  → buy (cheap ask, guaranteed profit)
#   bid ≥ EMA + TAKE_EDGE  → sell (expensive bid, guaranteed profit)
#   Lower = more aggressive (more takes, lower avg buy price).
#   Minimum sensible value = 1 (any ask below EMA is statistically cheap).
#
# OSMIUM_PASSIVE_SPREAD = 1
#   Half-spread for passive limit orders after taking is done.
#   Analytically optimal from the fill-probability analysis above.
#   spread=1 fills 54% of ticks; spread=2 fills 24%.
#   Expected PnL per tick: spread × fill_prob: 1×0.54=0.54 > 2×0.24=0.48
#
# OSMIUM_SKEW_FACTOR = 0.04
#   Ticks of quote shift per unit of inventory.
#   max skew at ±80: 80 × 0.04 = 3.2 ticks — enough to nudge without
#   significantly narrowing the effective spread.
# =============================================================================
OSMIUM_EMA_ALPHA     = 0.05
OSMIUM_TAKE_EDGE     = 1
OSMIUM_PASSIVE_SPREAD = 1
OSMIUM_SKEW_FACTOR   = 0.04


class Trader:

    def run(self, state: TradingState):

        # ── Restore persisted state ───────────────────────────────────────────
        if state.traderData and state.traderData not in ("", "SAMPLE"):
            trader_state = jsonpickle.decode(state.traderData)
        else:
            trader_state = {"osmium_ema": None}

        result = {}

        # =====================================================================
        # INTARIAN_PEPPER_ROOT — take all available asks immediately
        # =====================================================================
        product = "INTARIAN_PEPPER_ROOT"
        if product in state.order_depths:
            depth  = state.order_depths[product]
            pos    = state.position.get(product, 0)
            limit  = POSITION_LIMITS[product]
            orders = []

            # Scan asks from cheapest to most expensive.
            # Take every unit we can until the position limit is full.
            # We never send a sell order — ROOT is going up, holding = earning.
            if pos < limit and depth.sell_orders:
                asks_sorted = sorted(depth.sell_orders.items())   # ascending price
                current_pos = pos
                for price, vol in asks_sorted:
                    # vol in sell_orders is negative in IMC's datamodel
                    available = abs(vol)
                    buy_amount = min(available, limit - current_pos)
                    if buy_amount > 0:
                        orders.append(Order(product, price, buy_amount))
                        current_pos += buy_amount
                    if current_pos >= limit:
                        break   # full — no point scanning further

            result[product] = orders

        # =====================================================================
        # ASH_COATED_OSMIUM — hybrid aggressive + passive market making
        # =====================================================================
        product = "ASH_COATED_OSMIUM"
        if product in state.order_depths:
            depth  = state.order_depths[product]
            pos    = state.position.get(product, 0)
            limit  = POSITION_LIMITS[product]
            orders = []

            if not depth.sell_orders or not depth.buy_orders:
                result[product] = orders
            else:
                best_ask = min(depth.sell_orders.keys())
                best_bid = max(depth.buy_orders.keys())
                mid = (best_ask + best_bid) / 2

                # ── Update EMA ────────────────────────────────────────────────
                if trader_state["osmium_ema"] is None:
                    trader_state["osmium_ema"] = mid
                else:
                    trader_state["osmium_ema"] = (
                        OSMIUM_EMA_ALPHA * mid
                        + (1 - OSMIUM_EMA_ALPHA) * trader_state["osmium_ema"]
                    )
                ema = trader_state["osmium_ema"]

                # ── LAYER 1: Aggressive market taking ─────────────────────────
                # Buy any ask that is underpriced (ask ≤ EMA − TAKE_EDGE).
                # These are orders from other bots posted at a bad price.
                # Taking them locks in profit with no queue risk.
                current_pos = pos
                asks_sorted = sorted(depth.sell_orders.items())       # cheapest first
                for price, vol in asks_sorted:
                    if price <= ema - OSMIUM_TAKE_EDGE and current_pos < limit:
                        buy_amount = min(abs(vol), limit - current_pos)
                        orders.append(Order(product, price, buy_amount))
                        current_pos += buy_amount
                    else:
                        break   # asks are sorted ascending; once price > threshold, stop

                # Sell to any bid that is overpriced (bid ≥ EMA + TAKE_EDGE).
                bids_sorted = sorted(depth.buy_orders.items(), reverse=True)  # most expensive first
                for price, vol in bids_sorted:
                    if price >= ema + OSMIUM_TAKE_EDGE and current_pos > -limit:
                        sell_amount = min(abs(vol), limit + current_pos)
                        orders.append(Order(product, price, -sell_amount))
                        current_pos -= sell_amount
                    else:
                        break

                # ── LAYER 2: Passive limit orders ─────────────────────────────
                # Quote symmetrically around EMA with a tight spread of 1 tick.
                # Inventory skew leans the quotes to push position back toward 0.
                skew = -int(round(current_pos * OSMIUM_SKEW_FACTOR))

                passive_buy  = round(ema) - OSMIUM_PASSIVE_SPREAD + skew
                passive_sell = round(ema) + OSMIUM_PASSIVE_SPREAD + skew

                # Guard: never cross the spread (passive orders only, not market orders)
                passive_buy  = min(passive_buy,  best_ask - 1)
                passive_sell = max(passive_sell, best_bid + 1)

                # Guard: if skew pushed prices to cross each other, fix it
                if passive_buy >= passive_sell:
                    passive_buy  = passive_sell - 1

                buy_capacity  = limit - current_pos
                sell_capacity = limit + current_pos

                if buy_capacity > 0:
                    orders.append(Order(product, int(passive_buy),  buy_capacity))
                if sell_capacity > 0:
                    orders.append(Order(product, int(passive_sell), -sell_capacity))

                result[product] = orders

        # ── Persist state for next tick ───────────────────────────────────────
        traderData = jsonpickle.encode(trader_state)
        conversions = 0
        return result, conversions, traderData
