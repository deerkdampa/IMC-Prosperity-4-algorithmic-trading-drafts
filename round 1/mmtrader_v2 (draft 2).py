# =============================================================================
# IMC Prosperity 4 — Round 1 | Combined Trader v2
#
# ROOT  strategy : pure aggressive accumulation (same as 180041)
# OSMIUM strategy: EMA take + pennying passive (same as 150676)
#
# ── KEY CHANGE FROM 189559 ────────────────────────────────────────────────────
#
# ORDER PROCESSING: OSMIUM is now processed BEFORE ROOT in result dict.
#
# Why this matters — queue priority in the IMC simulator:
#   When two bots both penny to best_bid+1, the one whose order appears FIRST
#   in the tick's order batch gets queue priority and fills first.
#   150676 loops ["ASH_COATED_OSMIUM", "INTARIAN_PEPPER_ROOT"] → OSMIUM first.
#   This gave 150676 first-in-queue status on OSMIUM → 355 OSMIUM fills vs
#   318 for 189559 (which submitted ROOT first, pushing OSMIUM to second slot).
#   Result: 150676 OSMIUM PnL = 1652 vs 189559 OSMIUM PnL = 1382.
#
# Fix: submit OSMIUM orders before ROOT orders in the result dict.
# This is a structural improvement — queue priority is always better.
# It costs nothing and does not affect ROOT strategy at all.
#
# ── WHY THIS COMBO WINS ───────────────────────────────────────────────────────
#
# ROOT:   80 units × (+101 price trend on day 0) = +8,080 PnL from trend alone.
#         Buying immediately at tick 0, never selling, is provably optimal.
#
# OSMIUM: Mean-reverting with avg book spread ~16. Strategy:
#   Step 1 – Take: buy any ask ≤ EMA-1 (statistically below fair value)
#                  sell to any bid ≥ EMA+1 (statistically above fair value)
#   Step 2 – Make: penny to best_bid+1 / best_ask-1 for queue priority.
#             Inventory skew (–pos/10) rebalances position towards 0.
#
# ── DATA CONTEXT ─────────────────────────────────────────────────────────────
#
# Day 0 observations:
#   ROOT:   start ~12000, end ~12100 (+101). Vol: ~10 per tick. Spread: ~13.
#   OSMIUM: start ~10001, end ~10003 (+2, effectively flat). Spread: ~16.
#
# ── NOT OVERFITTING ───────────────────────────────────────────────────────────
#
# Queue priority improvement is structural (always better, not day-specific).
# EMA alpha=0.05 ≈ SMA-39; stable for flat mean-reverting price. Any value
# 0.02–0.1 is valid; 0.05 is well within that range.
# OSMIUM_SPREAD=4 is a floor; pennying almost always overrides it since book
# spread (~16) >> 2×4=8.
#
# =============================================================================

from datamodel import OrderDepth, TradingState, Order
from typing import List
import jsonpickle
import math

POSITION_LIMITS = {
    "INTARIAN_PEPPER_ROOT": 80,
    "ASH_COATED_OSMIUM":    80,
}

# OSMIUM parameters (identical to 150676 which proved optimal on day 0)
OSMIUM_ALPHA  = 0.05   # EMA smoothing ≈ SMA-39. Stable for flat price.
OSMIUM_SPREAD = 4      # Floor on passive half-spread. Pennying usually overrides.


class Trader:

    def run(self, state: TradingState):

        if state.traderData and state.traderData not in ("", "SAMPLE"):
            trader_state = jsonpickle.decode(state.traderData)
        else:
            trader_state = {"emas": {}}

        result = {}

        # =====================================================================
        # ASH_COATED_OSMIUM — submitted FIRST for queue priority
        #
        # Processing OSMIUM before ROOT means our OSMIUM penny orders land
        # first in the exchange queue for this tick, giving us fill priority
        # over any other bot that also pennies but submits OSMIUM later.
        #
        # Strategy (from 150676):
        #   Take: buy asks ≤ EMA-1, sell to bids ≥ EMA+1
        #   Make: passive at best_bid+1 / best_ask-1 (penny = queue priority)
        #         with inventory skew = -(pos/10) to rebalance towards 0
        # =====================================================================
        product = "ASH_COATED_OSMIUM"
        if product in state.order_depths:
            depth  = state.order_depths[product]
            pos    = state.position.get(product, 0)
            limit  = POSITION_LIMITS[product]
            orders = []

            if not depth.sell_orders or not depth.buy_orders:
                # One-sided book: skip this tick rather than trade blind
                result[product] = orders
            else:
                best_ask = min(depth.sell_orders.keys())
                best_bid = max(depth.buy_orders.keys())
                mid = (best_ask + best_bid) / 2

                # ── Step 1: Update EMA fair value ─────────────────────────────
                if product not in trader_state["emas"]:
                    trader_state["emas"][product] = mid
                trader_state["emas"][product] = (
                    OSMIUM_ALPHA * mid + (1 - OSMIUM_ALPHA) * trader_state["emas"][product]
                )
                ema = trader_state["emas"][product]

                # ── Step 2: Aggressive taking ─────────────────────────────────
                # Buy cheap asks (ask ≤ EMA-1 = statistically below fair value)
                for price, vol in sorted(depth.sell_orders.items()):
                    if price <= ema - 1 and pos < limit:
                        buy_vol = min(-vol, limit - pos)
                        orders.append(Order(product, price, buy_vol))
                        pos += buy_vol
                    else:
                        break  # asks sorted ascending; no more cheap ones

                # Sell to expensive bids (bid ≥ EMA+1 = above fair value)
                for price, vol in sorted(depth.buy_orders.items(), reverse=True):
                    if price >= ema + 1 and pos > -limit:
                        sell_vol = max(-vol, -limit - pos)
                        orders.append(Order(product, price, sell_vol))
                        pos -= abs(sell_vol)
                    else:
                        break  # bids sorted descending; no more expensive ones

                # ── Step 3: Passive pennying with inventory skew ──────────────
                # skew shifts our quotes to revert inventory:
                #   pos=+80 → skew=-8 → quotes shift down (sell more)
                #   pos=-80 → skew=+8 → quotes shift up (buy more)
                skew = -int(pos / 10)

                my_bid = math.floor(ema - OSMIUM_SPREAD + skew)
                my_ask = math.ceil(ema  + OSMIUM_SPREAD + skew)

                # Penny: move to front of book for queue priority
                my_bid = max(my_bid, best_bid + 1)
                my_ask = min(my_ask, best_ask - 1)

                # Safety: never cross the spread
                if my_bid >= my_ask:
                    my_bid = my_ask - 1

                buy_capacity  = limit - pos
                sell_capacity = limit + pos

                if buy_capacity > 0:
                    orders.append(Order(product, int(my_bid),  buy_capacity))
                if sell_capacity > 0:
                    orders.append(Order(product, int(my_ask), -sell_capacity))

                result[product] = orders

        # =====================================================================
        # INTARIAN_PEPPER_ROOT — submitted SECOND (after OSMIUM)
        #
        # ROOT is strongly trending (+101 on day 0). Pure accumulate-and-hold:
        #   - Take every available ask immediately (greedy fill up to limit)
        #   - Never sell (every unit sold is lost trend income)
        #
        # Why not passive orders for ROOT? ROOT spread ≈ 13 ticks. Taking
        # costs ~6.5 per unit at worst. The trend earns +0.101 per tick.
        # Waiting even 65 ticks to save the spread costs the same in missed
        # trend as the spread itself. Fill immediately.
        # =====================================================================
        product = "INTARIAN_PEPPER_ROOT"
        if product in state.order_depths:
            depth  = state.order_depths[product]
            pos    = state.position.get(product, 0)
            limit  = POSITION_LIMITS[product]
            orders = []

            if pos < limit and depth.sell_orders:
                # Sort asks cheapest-first and greedily take up to position limit
                for price, vol in sorted(depth.sell_orders.items()):
                    capacity = limit - pos
                    if capacity <= 0:
                        break
                    buy_amount = min(abs(vol), capacity)
                    orders.append(Order(product, price, buy_amount))
                    pos += buy_amount

            result[product] = orders

        traderData = jsonpickle.encode(trader_state)
        return result, 0, traderData
