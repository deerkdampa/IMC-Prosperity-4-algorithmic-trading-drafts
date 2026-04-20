# =============================================================================
# IMC Prosperity 4 — Round 1 | Combined Best-of-Both Bot
#
# ROOT  strategy: from 180041 — pure market-take accumulation
# OSMIUM strategy: from 150676 — hybrid EMA take + pennying passive
#
# WHY THIS COMBINATION WINS (backed by log analysis):
#
# Bot       ROOT PnL  OSMIUM PnL  ROOT pos   OSMIUM fills  Root entry
# 180041      best      good         80 @ ts=0-200     18 RTs    immediate
# 150676      worst     BEST          17 @ ts=99500     29 RTs    late
# 153649      medium    medium        61 @ ts=6400-99500 28 RTs   slow
# 187744      best      poor          80 @ ts=0-200     28 RTs    immediate
#
# ROOT key insight:
#   PnL is driven by (units held) × (price rise per tick).
#   Price rises +1001 per day. Position limit = 80.
#   Every tick you wait to enter costs 80 × 0.1 = 8 seashells.
#   180041 buys 80 units by tick 200 at avg price 12008.
#   vs 153649 which buys 61 units slowly at avg price 12055.
#   Difference = 80×(13000−12008) − 61×(13000−12055) = 79,360 − 57,645 = 21,715
#
# OSMIUM key insight:
#   PnL = (round trips) × (avg spread per round trip)
#   150676: 29 round trips × avg spread 9.12 = 264 (then × avg trade qty)
#   180041: 18 round trips × avg spread 13.78 = 248 (then × avg trade qty)
#   150676 wins because it gets MORE FILLS via queue priority (best_bid+1)
#   and aggressive taking captures cheap asks.
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
# ASH_COATED_OSMIUM parameters (from 150676)
# EMA alpha=0.05 → ~SMA-39, smooth enough for flat-price OSMIUM
# OSMIUM_SPREAD=4 acts as a FLOOR only; pennying usually makes effective spread=1
# OSMIUM_SKEW = -(position / 10) ticks max skew at ±80 = ±8 ticks
# =============================================================================
OSMIUM_ALPHA  = 0.05
OSMIUM_SPREAD = 4


class Trader:

    def run(self, state: TradingState):

        if state.traderData and state.traderData not in ("", "SAMPLE"):
            trader_state = jsonpickle.decode(state.traderData)
        else:
            trader_state = {"emas": {}}

        result = {}

        # =====================================================================
        # INTARIAN_PEPPER_ROOT — take all available asks immediately (180041)
        #
        # Why market-take instead of passive limit orders:
        #   Book spread avg = 13. Taking costs us ~6.5 per unit at worst.
        #   The trend earns +0.1 per unit per TICK.
        #   So waiting even 65 ticks to save the spread costs as much in
        #   missed trend as the spread itself. Fill immediately.
        #
        # We never sell. ROOT is going up ~1000/day. Every unit we sell
        # is a unit that stops earning trend income.
        # =====================================================================
        product = "INTARIAN_PEPPER_ROOT"
        if product in state.order_depths:
            depth  = state.order_depths[product]
            pos    = state.position.get(product, 0)
            limit  = POSITION_LIMITS[product]
            orders = []

            if pos < limit and depth.sell_orders:
                # Sort asks cheapest first and take greedily up to limit
                for price, vol in sorted(depth.sell_orders.items()):
                    capacity = limit - pos
                    if capacity <= 0:
                        break
                    buy_amount = min(abs(vol), capacity)
                    orders.append(Order(product, price, buy_amount))
                    pos += buy_amount

            result[product] = orders

        # =====================================================================
        # ASH_COATED_OSMIUM — hybrid EMA take + pennying passive (150676)
        #
        # STEP 1 — Update EMA fair value
        #   EMA is better than SMA here: no list storage, equivalent smoothness.
        #   alpha=0.05 ≈ SMA-39 (stable for flat, mean-reverting price).
        #
        # STEP 2 — Aggressive taking
        #   If any ASK is ≤ EMA−1 → that ask is BELOW fair value → buy it.
        #   If any BID is ≥ EMA+1 → that bid is ABOVE fair value → sell to it.
        #   These are structural free-money trades. No queue risk.
        #
        # STEP 3 — Passive pennying
        #   After taking, place passive bids/asks at best_bid+1 / best_ask−1.
        #   This gives QUEUE PRIORITY over all existing orders at best bid/ask.
        #   Key advantage over 180041's passive approach (which joins AT best
        #   bid/ask = back of queue).
        #   The spread=4 floor prevents quoting at unprofitable prices.
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

                # ── STEP 1: Update EMA ───────────────────────────────────────
                if product not in trader_state["emas"]:
                    trader_state["emas"][product] = mid
                trader_state["emas"][product] = (
                    OSMIUM_ALPHA * mid + (1 - OSMIUM_ALPHA) * trader_state["emas"][product]
                )
                ema = trader_state["emas"][product]

                # ── STEP 2: Aggressive market taking ─────────────────────────
                # Take cheap asks (below fair value)
                for price, vol in sorted(depth.sell_orders.items()):
                    if price <= ema - 1 and pos < limit:
                        buy_vol = min(-vol, limit - pos)
                        orders.append(Order(product, price, buy_vol))
                        pos += buy_vol
                    else:
                        break  # asks are sorted ascending; no more cheap ones

                # Sell to expensive bids (above fair value)
                for price, vol in sorted(depth.buy_orders.items(), reverse=True):
                    if price >= ema + 1 and pos > -limit:
                        sell_vol = max(-vol, -limit - pos)
                        orders.append(Order(product, price, sell_vol))
                        pos -= abs(sell_vol)
                    else:
                        break  # bids sorted descending; no more expensive ones

                # ── STEP 3: Passive pennying with inventory skew ──────────────
                # Skew shifts quotes against current inventory.
                # At max long (+80): skew = -(80/10) = -8 → quotes lean downward
                # At max short (−80): skew = +(80/10) = +8 → quotes lean upward
                skew = -int(pos / 10)
                spread = OSMIUM_SPREAD   # floor on profitability

                my_bid = math.floor(ema - spread + skew)
                my_ask = math.ceil(ema + spread + skew)

                # PENNY: improve on current best bid and ask by 1 tick
                # This gives us queue priority — we fill before anyone else
                my_bid = max(my_bid, best_bid + 1)
                my_ask = min(my_ask, best_ask - 1)

                # Safety: never cross the spread
                if my_bid >= my_ask:
                    my_bid = my_ask - 1

                buy_capacity  = limit - pos
                sell_capacity = limit + pos

                if buy_capacity > 0:
                    orders.append(Order(product, int(my_bid), buy_capacity))
                if sell_capacity > 0:
                    orders.append(Order(product, int(my_ask), -sell_capacity))

                result[product] = orders

        traderData = jsonpickle.encode(trader_state)
        return result, 0, traderData