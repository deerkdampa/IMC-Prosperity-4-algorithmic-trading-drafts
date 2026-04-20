# =============================================================================
# IMC Prosperity 4 — Round 1 Starter Bot
# Strategy: Market Making
# Products: INTARIAN_PEPPER_ROOT, ASH_COATED_OSMIUM
# =============================================================================
#
# ── WHAT IS MARKET MAKING? ───────────────────────────────────────────────────
#
# A market maker simultaneously quotes a BID (price to BUY) and an ASK (price
# to SELL).  The gap between them is called the SPREAD, and it is your profit
# per round-trip trade.
#
# Example: fair value = 10000
#   Your bid  = 9997  (you buy cheap)
#   Your ask  = 10003 (you sell expensive)
#   Spread    =    6  → you earn 6 per share if both sides fill
#
# The key is estimating FAIR VALUE accurately.  If your fair value is wrong
# your quotes will be one-sided and you will lose money.
#
# ── HOW THE EXCHANGE WORKS ───────────────────────────────────────────────────
#
# Each timestep ("tick") you receive a TradingState containing:
#   • order_depths  — the live limit-order book (best bid/ask + sizes)
#   • position      — how many units you currently hold (+ = long, - = short)
#   • traderData    — a string you wrote last tick (use it to persist state)
#
# You return a dict of Order lists.  Each Order is (symbol, price, quantity)
# where quantity > 0 = buy order, quantity < 0 = sell order.
#
# Your orders are matched against the book.  Anything that doesn't cross the
# book rests as a passive limit order until the next tick.
#
# ── POSITION LIMITS ──────────────────────────────────────────────────────────
#
# You cannot hold more than LIMIT units long OR short.  If you try to submit
# an order that would breach the limit it is simply ignored.  Always track
# remaining capacity before submitting.
#
# ── WHAT IS INVENTORY SKEW? ──────────────────────────────────────────────────
#
# If you keep buying you will eventually hit the long limit and be unable to
# buy more — even if the market is cheap.  To avoid this, you "skew" your
# quotes: when long, lower both bid and ask so you sell more easily; when
# short, raise both so you buy more.  The SKEW_FACTOR controls how
# aggressively you do this.
#
# =============================================================================

from datamodel import OrderDepth, TradingState, Order
from typing import List
import jsonpickle
import math


# =============================================================================
# ── POSITION LIMITS ──────────────────────────────────────────────────────────
# The maximum number of units you can hold long or short at any time.
# Submitting orders that would exceed these is silently ignored by the engine.
# =============================================================================
POSITION_LIMITS = {
    "INTARIAN_PEPPER_ROOT": 80,
    "ASH_COATED_OSMIUM":    80,
}


# =============================================================================
# ── ASH_COATED_OSMIUM PARAMETERS ─────────────────────────────────────────────
# (unchanged — this product is already trading fine)
# =============================================================================
OSMIUM_WINDOW      = 50
OSMIUM_BASE_SPREAD = 3
OSMIUM_SKEW_FACTOR = 0.05


# =============================================================================
# ── INTARIAN_PEPPER_ROOT PARAMETERS ──────────────────────────────────────────
#
# WHY THE OLD CODE NEVER TRADED:
#   Old code: spread = max(ROOT_BASE_SPREAD=6, floor(book_spread/2))
#   With book_spread ≈ 15 → floor(15/2) = 7 → spread = 7 (the max always won)
#   Result:
#     buy_price  = floor(mid) − 7 = floor(11998.5) − 7 = 11991 = best_bid exactly
#     sell_price = ceil(mid)  + 7 = ceil(11998.5)  + 7 = 12006 = best_ask exactly
#   The bot joined the queue BEHIND the 20 units already resting at best_bid
#   and the 11 units at best_ask.  In a trending market those never got
#   consumed before the price moved away → zero fills, zero PnL.
#
# THE FIX (two changes):
#   1. ROOT_BASE_SPREAD lowered from 6 → 3
#   2. spread formula changed to just ROOT_BASE_SPREAD (no book_spread clause)
#
#   Result with tick-0 data (best_bid=11991, best_ask=12006, mid=11998.5):
#     spread     = 3
#     buy_price  = min(floor(11998.5) − 3, 12005) = 11995  ← improves on best_bid by 4
#     sell_price = max(ceil(11998.5)  + 3, 11992) = 12002  ← improves on best_ask by 4
#   The bot is now the NEW best bid and best ask → it sits at the FRONT of the
#   queue and market takers fill it first.
#
# ANALYTICAL BASIS FOR ROOT_BASE_SPREAD = 3:
#   Tick-to-tick σ ≈ 3.0 (measured from log / stated in header).
#   Avellaneda-Stoikov optimal half-spread ≈ σ/2 ≈ 1.5 → round up to 2.
#   Add 1 tick of buffer against adverse selection → 3.
#   At 3 the bot improves on the existing quotes, guaranteeing queue priority.
#   Going below 2 risks negative expected value; going above 7 means the
#   bot falls back to quoting at or outside the best bid/ask (the old bug).
#
# ROOT_SKEW_FACTOR = 0.05 is kept as-is:
#   max skew at position limit (80) = 80 × 0.05 = 4 ticks.
#   This gently leans against inventory build-up without crushing the spread.
#   The upward trend means longs accumulate; if fills still lean heavily long
#   after a few runs, raise this toward 0.08.
# =============================================================================

# ── CHANGE 1 ── was 6, now 3 (places quotes INSIDE the book spread)
ROOT_BASE_SPREAD   = 3
ROOT_SKEW_FACTOR   = 0.08 # for 2nd try on this file, I will change the skew factor from 0.05 to 0.08


class Trader:

    def run(self, state: TradingState):
        # ── 1. RESTORE STATE FROM LAST TICK ──────────────────────────────────
        if state.traderData and state.traderData not in ("", "SAMPLE"):
            trader_state = jsonpickle.decode(state.traderData)
        else:
            trader_state = {
                "osmium_prices": [],
            }

        result = {}

        # ── 2. LOOP OVER EVERY TRADEABLE PRODUCT ─────────────────────────────
        for product in state.order_depths:
            order_depth: OrderDepth = state.order_depths[product]
            orders: List[Order] = []

            # ── 2a. SKIP if the book is one-sided ────────────────────────────
            if len(order_depth.sell_orders) == 0 or len(order_depth.buy_orders) == 0:
                result[product] = orders
                continue

            # ── 2b. READ CURRENT POSITION ────────────────────────────────────
            position = state.position.get(product, 0)
            limit    = POSITION_LIMITS.get(product, 80)

            # ── 2c. READ BEST BID AND BEST ASK ───────────────────────────────
            best_ask = min(order_depth.sell_orders.keys())
            best_bid = max(order_depth.buy_orders.keys())

            mid_price   = (best_ask + best_bid) / 2
            book_spread = best_ask - best_bid

            # =================================================================
            # ── PRODUCT: INTARIAN_PEPPER_ROOT ─────────────────────────────────
            # =================================================================
            if product == "INTARIAN_PEPPER_ROOT":

                # FAIR VALUE: current mid-price (zero lag — correct for a
                # trending asset where any backward-looking average would lag).
                fair_value = mid_price

                # SPREAD CALCULATION ──────────────────────────────────────────
                # ── CHANGE 2 ── old: max(ROOT_BASE_SPREAD, floor(book_spread/2))
                #
                # The old formula caused spread = floor(book_spread/2) ≈ 7,
                # which placed the bot exactly at the existing best bid/ask
                # (back of queue, never filled).
                #
                # New formula: just use ROOT_BASE_SPREAD = 3.
                # This places the bot INSIDE the current book spread, making
                # it the new best bid and best ask → front of the queue.
                #
                # The best_ask-1 / best_bid+1 caps below still prevent the
                # bot from accidentally crossing the spread (no market orders).
                spread = ROOT_BASE_SPREAD

                # INVENTORY SKEW ──────────────────────────────────────────────
                skew = -int(round(position * ROOT_SKEW_FACTOR))

                # QUOTE PRICES ────────────────────────────────────────────────
                buy_price  = min(math.floor(fair_value) - spread + skew, best_ask - 1)
                sell_price = max(math.ceil(fair_value)  + spread + skew, best_bid + 1)

                # ORDER SIZES ─────────────────────────────────────────────────
                buy_volume  = limit - position
                sell_volume = limit + position

                if buy_volume > 0:
                    orders.append(Order(product, buy_price, buy_volume))
                if sell_volume > 0:
                    orders.append(Order(product, sell_price, -sell_volume))

            # =================================================================
            # ── PRODUCT: ASH_COATED_OSMIUM ────────────────────────────────────
            # (unchanged)
            # =================================================================
            elif product == "ASH_COATED_OSMIUM":

                trader_state["osmium_prices"].append(mid_price)
                prices = trader_state["osmium_prices"]

                window_size = min(len(prices), OSMIUM_WINDOW)
                fair_value  = sum(prices[-window_size:]) / window_size

                spread = max(OSMIUM_BASE_SPREAD, math.floor(book_spread / 2))

                skew = -int(round(position * OSMIUM_SKEW_FACTOR))

                buy_price  = min(round(fair_value) - spread + skew, best_ask - 1)
                sell_price = max(round(fair_value) + spread + skew, best_bid + 1)

                buy_volume  = limit - position
                sell_volume = limit + position

                if buy_volume > 0:
                    orders.append(Order(product, buy_price, buy_volume))
                if sell_volume > 0:
                    orders.append(Order(product, sell_price, -sell_volume))

            result[product] = orders

        # ── 3. PERSIST STATE FOR NEXT TICK ───────────────────────────────────
        traderData = jsonpickle.encode(trader_state)
        conversions = 0
        return result, conversions, traderData
