from datamodel import OrderDepth, UserId, TradingState, Order
from typing import List
import jsonpickle
import math
#Emeralds -> Intarian Pepper Root
#OSMIUM -> Ash-coated Osmium

POSITION_LIMITS = {
    "ROOTS": 40,
    "OSMIUM": 40,
}
# ROOT_FAIR_VALUE = 10000.0
# ROOT_TIGHT_SPREAD = 2
# ROOT_NORMAL_SPREAD = 1

# OSMIUM — behaves like Emeralds, stable mean reversion around 10000
OSMIUM_WINDOW       = 50     # short window fine, price barely drifts
OSMIUM_BASE_SPREAD  = 3      # market spread is 16, so 3 still gets fills easily
OSMIUM_SKEW_FACTOR  = 0.2    # light skew, price is very stable

# ROOTS — trending upward ~1000/day, oscillates ±~300 around trend
ROOT_WINDOW         = 200    # longer window to track the rising mean properly
ROOT_BASE_SPREAD    = 5      # market spread averages 13, so 5 is competitive
ROOT_SKEW_FACTOR    = 0.5    # stronger skew needed due to directional drift

class Trader:

    def run(self, state: TradingState):

        # --- Load persisted data ---
        if state.traderData and state.traderData not in ("", "SAMPLE"):
            trader_state = jsonpickle.decode(state.traderData)
        else:
            trader_state = {
                "osmium_prices": [],
                "root_prices": []
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

            # FIX: define these variables here so the aggressive-take
            # block in roots can safely reference them.
            # (In 97237 they were used but never defined, causing a
            # silent NameError if the mispricing branch ever triggered.)
            best_ask_amount = order_depth.sell_orders[best_ask]  # negative
            best_bid_amount = order_depth.buy_orders[best_bid]    # positive

            mid_price = (best_ask + best_bid) / 2

            if product == "INTARIAN_PEPPER_ROOT":
                trader_state["root_prices"].append(mid_price)
                prices = trader_state["root_prices"]

                if len(prices) < ROOT_WINDOW:
                    result[product] = orders
                    continue

                fair_value = sum(prices[-ROOT_WINDOW:]) / ROOT_WINDOW
                book_spread = best_ask - best_bid
                spread = max(OSMIUM_BASE_SPREAD, math.ceil(book_spread / 2) + 1)

                # Small inventory skew helps keep position size in check.
                skew = -int(round(position * ROOT_SKEW_FACTOR))

                buy_price  = min(round(fair_value) - spread + skew, best_ask - 1)
                sell_price = max(round(fair_value) + spread + skew, best_bid + 1)

                buy_volume  = limit - position
                sell_volume = limit + position

                if buy_volume > 0:
                    orders.append(Order(product, buy_price, buy_volume))
                if sell_volume > 0:
                    orders.append(Order(product, sell_price, -sell_volume))
                # trader_state["root_prices"].append(mid_price)
                # fair_value = ROOT_FAIR_VALUE

                # # Step 1: Aggressively take any clearly mispriced order.
                # if best_ask < fair_value:
                #     buy_volume = min(-best_ask_amount, limit - position)
                #     if buy_volume > 0:
                #         orders.append(Order(product, best_ask, buy_volume))

                # if best_bid > fair_value:
                #     sell_volume = min(best_bid_amount, limit + position)
                #     if sell_volume > 0:
                #         orders.append(Order(product, best_bid, -sell_volume))

                # # Step 2: Passive market-making around the known fair value.
                # already_buying  = sum(o.quantity for o in orders if o.quantity > 0)
                # already_selling = sum(-o.quantity for o in orders if o.quantity < 0)

                # remaining_buy  = limit - position - already_buying
                # remaining_sell = limit + position - already_selling

                # if best_ask - best_bid <= 1:
                #     # Tight or zero spread around 10000: quote a slightly wider spread
                #     # because counterparties can trade exactly at the fair price.
                #     mm_buy_price = int(fair_value) - ROOT_TIGHT_SPREAD
                #     mm_sell_price = int(fair_value) + ROOT_TIGHT_SPREAD
                # else:
                #     # If the book has a wider spread, quote one tick off fair to
                #     # remain competitive while still collecting a spread.
                #     mm_buy_price = int(fair_value) - ROOT_NORMAL_SPREAD
                #     mm_sell_price = int(fair_value) + ROOT_NORMAL_SPREAD

                # if remaining_buy > 0:
                #     orders.append(Order(product, mm_buy_price, remaining_buy))
                # if remaining_sell > 0:
                #     orders.append(Order(product, mm_sell_price, -remaining_sell))
            # -------------------------------------------------------
            elif product == "ASH_COATED_OSMIUM":
                trader_state["osmium_prices"].append(mid_price)
                prices = trader_state["osmium_prices"]

                if len(prices) < OSMIUM_WINDOW:
                    result[product] = orders
                    continue

                fair_value = sum(prices[-OSMIUM_WINDOW:]) / OSMIUM_WINDOW
                book_spread = best_ask - best_bid
                spread = max(OSMIUM_BASE_SPREAD, math.ceil(book_spread / 2) + 1)

                # Small inventory skew helps keep position size in check.
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