from datamodel import OrderDepth, UserId, TradingState, Order
from typing import List
import jsonpickle
import math

POSITION_LIMITS = {
    "INTARIAN_PEPPER_ROOT": 40,
    "ASH_COATED_OSMIUM": 40,
}

# OSMIUM — stable mean-reverting around ~10000, use short SMA as fair value
OSMIUM_WINDOW      = 50
OSMIUM_BASE_SPREAD = 3
OSMIUM_SKEW_FACTOR = 0.2

# ROOTS — trends up ~1000/day (0.1/tick), so we use the CURRENT mid_price as
# fair value instead of a lagging SMA.  A 200-step SMA always trails by ~10
# ticks, causing sell quotes to be too cheap and building a losing short.
# No warmup window is needed: mid_price is already the best local estimate.
ROOT_BASE_SPREAD   = 5   # book spread averages 13, so 5 is competitive
ROOT_SKEW_FACTOR   = 0.5 # stronger skew because price drifts directionally


class Trader:

    def run(self, state: TradingState):

        # --- Load persisted data ---
        if state.traderData and state.traderData not in ("", "SAMPLE"):
            trader_state = jsonpickle.decode(state.traderData)
        else:
            trader_state = {
                "osmium_prices": [],
            }

        result = {}

        for product in state.order_depths:
            order_depth: OrderDepth = state.order_depths[product]
            orders: List[Order] = []

            if len(order_depth.sell_orders) == 0 or len(order_depth.buy_orders) == 0:
                result[product] = orders
                continue

            position = state.position.get(product, 0)
            limit = POSITION_LIMITS.get(product, 20)

            best_ask = min(order_depth.sell_orders.keys())
            best_bid = max(order_depth.buy_orders.keys())
            mid_price = (best_ask + best_bid) / 2

            if product == "INTARIAN_PEPPER_ROOT":
                # Use the current mid_price directly as fair value.
                # The price trends linearly (~0.1/tick), so any backward-
                # looking average will lag and mis-price our quotes.
                fair_value = mid_price

                book_spread = best_ask - best_bid
                spread = max(ROOT_BASE_SPREAD, math.ceil(book_spread / 2) + 1)

                # Inventory skew: lean against our current position so we
                # mean-revert back toward flat over time.
                skew = -int(round(position * ROOT_SKEW_FACTOR))

                buy_price  = min(round(fair_value) - spread + skew, best_ask - 1)
                sell_price = max(round(fair_value) + spread + skew, best_bid + 1)

                buy_volume  = limit - position
                sell_volume = limit + position

                if buy_volume > 0:
                    orders.append(Order(product, buy_price, buy_volume))
                if sell_volume > 0:
                    orders.append(Order(product, sell_price, -sell_volume))

            elif product == "ASH_COATED_OSMIUM":
                # Stable, mean-reverting product — short SMA is appropriate here.
                trader_state["osmium_prices"].append(mid_price)
                prices = trader_state["osmium_prices"]

                if len(prices) < OSMIUM_WINDOW:
                    result[product] = orders
                    continue

                fair_value = sum(prices[-OSMIUM_WINDOW:]) / OSMIUM_WINDOW
                book_spread = best_ask - best_bid
                spread = max(OSMIUM_BASE_SPREAD, math.ceil(book_spread / 2) + 1)

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

        traderData = jsonpickle.encode(trader_state)
        conversions = 0
        return result, conversions, traderData