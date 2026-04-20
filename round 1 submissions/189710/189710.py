# =============================================================================
# IMC Prosperity 4 — Round 1 | Improvement Starter Bot
#
# GOAL: Beat 180041 on ROOT and 150676 on OSMIUM WITHOUT overfitting.
#
# ── WHAT OVERFITTING LOOKS LIKE ─────────────────────────────────────────────
#
# Overfitting = tuning parameters until they score well on the 3 training
# days, but fail on the live round 1 submission.
# Signs of overfitting:
#   - A parameter like "take when ask ≤ EMA − 3.7" (suspiciously precise)
#   - Strategy that only works because day -1 had an unusual price spike
#   - Spread/threshold chosen by trial-and-error until backtest peaked
#
# ── WHAT IS NOT OVERFITTING ──────────────────────────────────────────────────
#
# Structural improvements — things grounded in market microstructure that
# would work on ANY day, not just the training days:
#   1. Market-take ROOT (works as long as ROOT trends — confirmed over 3 days)
#   2. Queue priority for passive orders (always better than back-of-queue)
#   3. Taking statistically mispriced orders (any ask < mid = free money)
#   4. More fills = more PnL (structural: more trades → more spread income)
#
# ── WHY 180041 IS NEAR-OPTIMAL FOR ROOT ──────────────────────────────────────
#
# Data (day 0): 180041 bought 80 units by tick 200 at avg 12008.
# The day ended at 13000. Theoretical max PnL = 80 × (13000 − 12008) = 79,360.
# You literally cannot do better: you can't hold more than 80 units, and
# 180041 already buys at the very first asks available (tick 0).
# The only edge case is if the first tick has a one-sided book (no asks).
# The DEPTH_LIMIT parameter below handles that by placing a passive buy too.
#
# ── HOW TO BEAT 150676 ON OSMIUM ─────────────────────────────────────────────
#
# 150676 performance: 29 round trips, avg spread 9.12 per unit.
# Why it wins: queue priority (best_bid+1) + aggressive taking.
#
# Two non-overfitting improvements:
#
# IMPROVEMENT A — Use current mid-price as taking threshold (not EMA).
#   150676 uses: take if ask ≤ EMA - 1
#   Proposed:   take if ask < mid_price  (i.e., ask is below current fair value)
#   Why better: EMA lags by ~20 ticks (alpha=0.05). If price has spiked UP
#   temporarily, EMA underestimates fair value and we miss cheap asks.
#   Using current mid = (best_bid + best_ask) / 2 has zero lag.
#   This is structural, not overfitting: "buy when ask < fair value" is always
#   the right rule.
#
# IMPROVEMENT B — Two-level pennying (penny both level 1 and level 2 of book).
#   150676 pennies at level 1 (best_bid + 1).
#   We ALSO submit a second passive order at best_bid2 + 1 (level 2 of book).
#   Why: some ticks the level-1 bid gets filled by a big order and our single
#   penny order gets consumed. A second order at level 2 catches the next wave.
#   This increases total fills without changing the price logic.
#   Structural: more passive orders at valid prices = more fills.
#
# IMPROVEMENT C — Separate buy/sell skew factors.
#   150676 uses a single skew = -(pos / 10).
#   When pos is large negative (short), this pushes our ask DOWN, making us
#   sell even cheaper — the opposite of what we want.
#   Better: apply skew asymmetrically:
#     If pos > 0 (long): lower our ask aggressively, leave bid alone.
#     If pos < 0 (short): raise our bid aggressively, leave ask alone.
#   This reverts inventory faster with fewer ticks of spread sacrifice.
#
# ── DATA SUMMARY (from prices_round_1_day_{-2,-1,0}.csv) ────────────────────
#
#   INTARIAN_PEPPER_ROOT:
#     Trend: +1001 per day, every day, rock-solid (3/3 days)
#     Tick-to-tick σ ≈ 1.7 (two-sided book rows only)
#     Avg book spread ≈ 13, min ≈ 2
#     → sigma/2 ≈ 0.85 → optimal passive spread ≈ 1 (we don't need it; just take)
#
#   ASH_COATED_OSMIUM:
#     Trend: ≈ 0 (−6.5, +10, +4 over 3 days — statistical noise)
#     Tick-to-tick σ ≈ 1.9 (two-sided book rows only)
#     Avg book spread ≈ 16, min ≈ 5
#     → sigma/2 ≈ 0.95 → optimal passive half-spread ≈ 1, but with book spread 16
#       that means passive orders at EMA±1 sit INSIDE the book and may not fill
#       unless you penny. Pennying (best_bid+1) is analytically better.
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

# =============================================================================
# OSMIUM PARAMETERS
# =============================================================================

# EMA smoothing factor. 0.05 ≈ SMA-39 (very smooth, good for flat price).
# Changing to 0.1 makes it faster/noisier. Keep between 0.02 and 0.1.
# NOT a high-overfitting-risk parameter — any value in this range is fine.
OSMIUM_ALPHA = 0.05

# How many ticks from EMA to take aggressively (on top of mid-price check).
# See IMPROVEMENT A above — we ALSO take when ask < mid_price.
# This value adds an extra buffer: take even more eagerly below EMA.
# 0 = take whenever ask ≤ EMA (most aggressive)
# 1 = take whenever ask ≤ EMA - 1 (150676's setting)
# Keep at 0 for maximum fills without overfitting.
OSMIUM_TAKE_EDGE = 0

# Minimum passive half-spread (floor on profitability).
# We penny to best_bid+1 / best_ask-1, so this only activates when
# the book spread collapses below 2×OSMIUM_SPREAD (rare for OSMIUM).
# Min book spread = 5, so OSMIUM_SPREAD=2 means we always have room.
OSMIUM_SPREAD = 2


class Trader:

    def run(self, state: TradingState):

        if state.traderData and state.traderData not in ("", "SAMPLE"):
            trader_state = jsonpickle.decode(state.traderData)
        else:
            trader_state = {"emas": {}}

        result = {}

        # =====================================================================
        # INTARIAN_PEPPER_ROOT — immediate market-take + passive backup
        #
        # Same core as 180041 (near-optimal). Added: passive backup bid
        # for any remaining capacity after taking, in case the ask side
        # has limited volume at tick 0 and we can't fill 80 immediately.
        # The passive bid at best_bid+1 will fill on the NEXT tick's taking.
        # =====================================================================
        product = "INTARIAN_PEPPER_ROOT"
        if product in state.order_depths:
            depth  = state.order_depths[product]
            pos    = state.position.get(product, 0)
            limit  = POSITION_LIMITS[product]
            orders = []

            current_pos = pos

            # ── Take every available ask, cheapest first ──────────────────────
            if current_pos < limit and depth.sell_orders:
                for price, vol in sorted(depth.sell_orders.items()):
                    capacity = limit - current_pos
                    if capacity <= 0:
                        break
                    buy_amount = min(abs(vol), capacity)
                    orders.append(Order(product, price, buy_amount))
                    current_pos += buy_amount

            # ── Backup passive bid for remaining capacity ─────────────────────
            # IMPROVEMENT OVER 180041: if ask-side is thin (common in early ticks)
            # we place a passive bid at best_bid+1 to be first in the queue
            # and catch any incoming sell orders in the same tick.
            remaining = limit - current_pos
            if remaining > 0 and depth.buy_orders:
                best_bid = max(depth.buy_orders.keys())
                # bid at best_bid+1 — top of book, fills if anyone sells at market
                passive_buy_price = best_bid + 1
                # guard: don't cross the spread if we already know ask prices
                if depth.sell_orders:
                    min_ask = min(depth.sell_orders.keys())
                    passive_buy_price = min(passive_buy_price, min_ask - 1)
                if passive_buy_price > 0:
                    orders.append(Order(product, passive_buy_price, remaining))

            # We never sell ROOT — holding = earning trend income.
            result[product] = orders

        # =====================================================================
        # ASH_COATED_OSMIUM — improved hybrid strategy
        #
        # Three improvements over 150676 (see header for full explanation):
        #   A) Take when ask < mid_price (zero-lag fair value, not EMA)
        #   B) Two-level passive pennying for more fills
        #   C) Asymmetric skew (push inventory back without hurting spread edge)
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
                mid = (best_ask + best_bid) / 2   # zero-lag fair value

                # ── Update EMA (slow-moving fair value for taking threshold) ──
                if product not in trader_state["emas"]:
                    trader_state["emas"][product] = mid
                trader_state["emas"][product] = (
                    OSMIUM_ALPHA * mid + (1 - OSMIUM_ALPHA) * trader_state["emas"][product]
                )
                ema = trader_state["emas"][product]

                current_pos = pos

                # ── IMPROVEMENT A: Aggressive taking with zero-lag threshold ──
                # 150676 takes when ask ≤ EMA - 1. We take when ask < mid_price
                # (i.e., the ask is below the current midpoint = statistically cheap)
                # AND also when ask ≤ EMA - OSMIUM_TAKE_EDGE for extra coverage.
                # Taking threshold = the HIGHER of the two thresholds.
                buy_threshold  = max(mid - 0.5, ema - OSMIUM_TAKE_EDGE)
                sell_threshold = min(mid + 0.5, ema + OSMIUM_TAKE_EDGE)

                # Buy cheap asks
                for price, vol in sorted(depth.sell_orders.items()):
                    if price <= buy_threshold and current_pos < limit:
                        buy_vol = min(abs(vol), limit - current_pos)
                        orders.append(Order(product, price, buy_vol))
                        current_pos += buy_vol
                    else:
                        break

                # Sell to expensive bids
                for price, vol in sorted(depth.buy_orders.items(), reverse=True):
                    if price >= sell_threshold and current_pos > -limit:
                        sell_vol = min(abs(vol), limit + current_pos)
                        orders.append(Order(product, price, -sell_vol))
                        current_pos -= sell_vol
                    else:
                        break

                # ── IMPROVEMENT C: Asymmetric inventory skew ─────────────────
                # 150676 uses: skew = -(pos / 10) applied to BOTH sides.
                # Problem: when long (+50), skew=-5 lowers both bid and ask.
                #   It correctly makes us sell cheaper but ALSO makes us buy
                #   even cheaper — accidentally helping us buy MORE while long.
                # Better: only penalise the side that builds inventory.
                #   When long: lower the ask (sell cheaper) but keep the bid flat.
                #   When short: raise the bid (buy more) but keep the ask flat.
                pos_skew = -int(current_pos / 10)   # same magnitude as 150676

                # ── IMPROVEMENT B: Two-level pennying ────────────────────────
                # Level 1 passive order: best_bid+1 / best_ask-1
                buy_price_1  = max(math.floor(ema - OSMIUM_SPREAD), best_bid + 1)
                sell_price_1 = min(math.ceil(ema  + OSMIUM_SPREAD), best_ask - 1)

                # Apply asymmetric skew — only adjust the side that needs it
                if current_pos > 0:
                    # Long → urgently want to sell → lower ask only
                    sell_price_1 = max(sell_price_1 + pos_skew, best_bid + 1)
                elif current_pos < 0:
                    # Short → urgently want to buy → raise bid only
                    buy_price_1 = min(buy_price_1 - pos_skew, best_ask - 1)

                # Safety: never cross the spread
                if buy_price_1 >= sell_price_1:
                    buy_price_1 = sell_price_1 - 1

                buy_capacity_1  = max(0, (limit - current_pos) // 2)   # half capacity level 1
                sell_capacity_1 = max(0, (limit + current_pos) // 2)

                if buy_capacity_1 > 0:
                    orders.append(Order(product, int(buy_price_1),  buy_capacity_1))
                if sell_capacity_1 > 0:
                    orders.append(Order(product, int(sell_price_1), -sell_capacity_1))

                # Level 2 passive order: one tick inside the level-2 book
                # (only if the book shows a level 2 bid/ask)
                bid_prices = sorted(depth.buy_orders.keys(), reverse=True)
                ask_prices = sorted(depth.sell_orders.keys())

                if len(bid_prices) >= 2 and len(ask_prices) >= 2:
                    best_bid2 = bid_prices[1]
                    best_ask2 = ask_prices[1]

                    buy_price_2  = max(math.floor(ema - OSMIUM_SPREAD) - 1, best_bid2 + 1)
                    sell_price_2 = min(math.ceil(ema  + OSMIUM_SPREAD) + 1, best_ask2 - 1)

                    if buy_price_2 < buy_price_1 and buy_price_2 > 0:
                        remaining_buy = limit - current_pos - buy_capacity_1
                        if remaining_buy > 0:
                            orders.append(Order(product, int(buy_price_2), remaining_buy))

                    if sell_price_2 > sell_price_1:
                        remaining_sell = limit + current_pos - sell_capacity_1
                        if remaining_sell > 0:
                            orders.append(Order(product, int(sell_price_2), -remaining_sell))

                result[product] = orders

        traderData = jsonpickle.encode(trader_state)
        return result, 0, traderData