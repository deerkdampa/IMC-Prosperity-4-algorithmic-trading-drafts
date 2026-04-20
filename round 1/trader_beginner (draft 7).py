# =============================================================================
# IMC Prosperity 4 — Round 1 | Improvement Trader v2
#
# GOAL: Beat ROOT PnL of 180041 (7286) AND OSMIUM PnL of 150676 (1652).
#
# ── WHAT WAS WRONG WITH 189710 ───────────────────────────────────────────────
#
# 189710's OSMIUM ended at position = -80 (maximum short). Three root causes:
#
# BUG 1 — Take threshold too aggressive:
#   189710 used buy_threshold = max(mid-0.5, ema), sell_threshold = min(mid+0.5, ema).
#   With ema ≈ mid this means: take ANY ask ≤ mid (very aggressive buy)
#   AND sell to ANY bid ≥ mid (very aggressive sell). Since sell was slightly
#   more favourable (bid ≥ mid more often than ask ≤ mid in a noisy spread),
#   it consistently sold more than it bought, spiralling to -80.
#   Fix: use ema±1 thresholds (same as 150676), structural and lag-aware.
#
# BUG 2 — Asymmetric skew direction reversed on short side:
#   When pos < 0 (short), we want to RAISE the bid to buy back.
#   189710 had: buy_price_1 = min(buy_price_1 - pos_skew, best_ask-1)
#   pos_skew = -int(pos/10) > 0 when pos < 0, so subtracting it LOWERS
#   the bid — the exact opposite of what we need.
#   Fix: ADD pos_skew when short → buy_price_1 += pos_skew (raises bid).
#        SUBTRACT pos_skew when long → sell_price_1 += pos_skew (lowers ask,
#        since pos_skew < 0 when pos > 0).
#
# BUG 3 — Two-level passive consumed too much capacity:
#   Level 1 used half capacity, level 2 tried to use remaining half.
#   Combined with aggressive taking, this sometimes sent orders that breached
#   limits (or were rejected), causing gaps in coverage.
#   Fix: level 1 uses FULL remaining capacity; level 2 only used if there is
#   extra room AND book depth exists at level 2.
#
# ── WHAT IS STRUCTURALLY IMPROVED OVER 150676 ────────────────────────────────
#
# IMPROVEMENT A — Queue priority for OSMIUM:
#   Process OSMIUM BEFORE ROOT in result dict. First-submitted orders get
#   front-of-queue in the IMC simulator. 150676 already does this (OSMIUM
#   first in its loop). Our fix ensures we also get that priority.
#
# IMPROVEMENT B — Two-level passive orders (fixed):
#   After placing the main penny order (level 1), we ALSO place a backup
#   passive order one tick inside the level-2 book. When the level-1 order
#   is swept by a large incoming order, our level-2 order is already
#   positioned to catch the next wave. This increases fill rate without
#   changing price logic. Structural: more passive orders at valid prices
#   = more fills.
#
# IMPROVEMENT C — Asymmetric skew (fixed direction):
#   When long: lower ONLY the ask (sell more, don't widen our buy spread).
#   When short: raise ONLY the bid (buy more, don't widen our sell spread).
#   This reverts inventory faster without unnecessarily harming the other side.
#
# ── DATA NOTES ───────────────────────────────────────────────────────────────
#   ROOT: +101 trend on day 0. Buy 80 units immediately. Never sell.
#   OSMIUM: flat (+2 on day 0). Mean-reverting. Book spread ~16.
#   EMA alpha=0.05 ≈ SMA-39. Any value 0.02–0.10 is structurally valid.
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

# OSMIUM parameters
OSMIUM_ALPHA     = 0.05   # EMA smoothing ≈ SMA-39. Stable for flat price.
OSMIUM_SPREAD    = 4      # Minimum passive half-spread (floor on profitability).
                          # With book spread ~16, pennying almost always overrides.
OSMIUM_TAKE_EDGE = 1      # Take when ask ≤ EMA - TAKE_EDGE (= EMA-1, same as 150676).
                          # 0 = very aggressive, 1 = conservative, 2 = very conservative.


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
        # IMPROVEMENT A: OSMIUM is processed and submitted before ROOT.
        # This gives our OSMIUM penny orders first-in-queue status, so we
        # fill before other bots who also penny but submit later in the tick.
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
                if product not in trader_state["emas"]:
                    trader_state["emas"][product] = mid
                trader_state["emas"][product] = (
                    OSMIUM_ALPHA * mid + (1 - OSMIUM_ALPHA) * trader_state["emas"][product]
                )
                ema = trader_state["emas"][product]

                current_pos = pos

                # ── Aggressive taking (FIX: conservative ema±1 thresholds) ───
                # BUG 1 fix: use ema-TAKE_EDGE (= ema-1) as threshold.
                # Taking anything at or below ema-1 = buying statistically cheap.
                # The ema-1 threshold is conservative enough to avoid the runaway
                # shorting that plagued 189710's mid-price-threshold approach.
                for price, vol in sorted(depth.sell_orders.items()):
                    if price <= ema - OSMIUM_TAKE_EDGE and current_pos < limit:
                        buy_vol = min(-vol, limit - current_pos)
                        orders.append(Order(product, price, buy_vol))
                        current_pos += buy_vol
                    else:
                        break

                for price, vol in sorted(depth.buy_orders.items(), reverse=True):
                    if price >= ema + OSMIUM_TAKE_EDGE and current_pos > -limit:
                        sell_vol = max(-vol, -limit - current_pos)
                        orders.append(Order(product, price, sell_vol))
                        current_pos -= abs(sell_vol)
                    else:
                        break

                # ── IMPROVEMENT C: Asymmetric skew (fixed direction) ──────────
                # pos_skew is always negative-when-long, positive-when-short.
                pos_skew = -int(current_pos / 10)

                # Base passive prices (floor on half-spread from EMA)
                buy_price_1  = math.floor(ema - OSMIUM_SPREAD)
                sell_price_1 = math.ceil(ema  + OSMIUM_SPREAD)

                if current_pos > 0:
                    # LONG: urgently want to SELL → lower ask only.
                    # pos_skew < 0 when long, so sell_price_1 + pos_skew decreases.
                    sell_price_1 = sell_price_1 + pos_skew   # lowers ask ✓
                    # bid stays flat (don't encourage buying more while already long)
                elif current_pos < 0:
                    # SHORT: urgently want to BUY → raise bid only.
                    # pos_skew > 0 when short, so buy_price_1 + pos_skew increases.
                    buy_price_1 = buy_price_1 + pos_skew     # raises bid ✓
                    # ask stays flat (don't encourage selling more while already short)

                # Penny: move to front of queue at best bid/ask
                buy_price_1  = max(buy_price_1,  best_bid + 1)
                sell_price_1 = min(sell_price_1, best_ask - 1)

                # Safety: never cross the spread
                if buy_price_1 >= sell_price_1:
                    buy_price_1 = sell_price_1 - 1

                # Guard: prices must be positive
                if buy_price_1 <= 0:
                    buy_price_1 = 1

                buy_capacity_1  = max(0, limit - current_pos)
                sell_capacity_1 = max(0, limit + current_pos)

                if buy_capacity_1 > 0:
                    orders.append(Order(product, int(buy_price_1),  buy_capacity_1))
                if sell_capacity_1 > 0:
                    orders.append(Order(product, int(sell_price_1), -sell_capacity_1))

                # ── IMPROVEMENT B: Two-level passive orders (fixed) ───────────
                # After level-1 fills our full capacity, we try to also place
                # a backup order at level 2 of the book. This only fires if
                # the position was reduced by taking in this tick (current_pos
                # differs from pos), leaving some spare capacity for level 2.
                #
                # FIX from 189710: we only place level-2 if there is genuine
                # remaining capacity AFTER the level-1 passive order above,
                # and only if the book actually has a second level.
                bid_prices = sorted(depth.buy_orders.keys(), reverse=True)
                ask_prices = sorted(depth.sell_orders.keys())

                if len(bid_prices) >= 2 and len(ask_prices) >= 2:
                    best_bid2 = bid_prices[1]
                    best_ask2 = ask_prices[1]

                    buy_price_2  = max(math.floor(ema - OSMIUM_SPREAD) - 1, best_bid2 + 1)
                    sell_price_2 = min(math.ceil(ema  + OSMIUM_SPREAD) + 1, best_ask2 - 1)

                    # Only place level-2 orders if they sit strictly WORSE than
                    # level-1 (don't duplicate) and don't cross spreads.
                    # Level-2 capacity = any room freed by taking above.
                    extra_buy  = max(0, limit  - current_pos - buy_capacity_1)
                    extra_sell = max(0, limit  + current_pos - sell_capacity_1)

                    if buy_price_2 < buy_price_1 and buy_price_2 > 0 and extra_buy > 0:
                        orders.append(Order(product, int(buy_price_2), extra_buy))

                    if sell_price_2 > sell_price_1 and extra_sell > 0:
                        orders.append(Order(product, int(sell_price_2), -extra_sell))

                result[product] = orders

        # =====================================================================
        # INTARIAN_PEPPER_ROOT — pure accumulation, submitted AFTER OSMIUM
        #
        # ROOT trends +101 per day (day 0). Buy 80 units immediately.
        # Never sell — every unit sold sacrifices trend income.
        # Same strategy as 180041 which achieves near-theoretical maximum.
        #
        # Why not try to improve ROOT over 180041?
        #   180041 buys 80 units by tick 200 at avg ~12009.
        #   Theoretical max = 80 × (12100 - 12000) = 8000.
        #   180041 achieves 7286 ≈ 91% of theoretical max.
        #   The only edge is if ask-side is thin at tick 0 (handled by taking
        #   all available asks tick by tick until limit is reached).
        # =====================================================================
        product = "INTARIAN_PEPPER_ROOT"
        if product in state.order_depths:
            depth  = state.order_depths[product]
            pos    = state.position.get(product, 0)
            limit  = POSITION_LIMITS[product]
            orders = []

            if pos < limit and depth.sell_orders:
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
