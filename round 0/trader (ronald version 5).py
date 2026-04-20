from datamodel import OrderDepth, UserId, TradingState, Order
from typing import List
import jsonpickle
import math

POSITION_LIMITS = {
    "EMERALDS": 80,
    "TOMATOES": 40,
}
EMERALD_FAIR_VALUE = 10000.0
EMERALD_TIGHT_SPREAD = 2
EMERALD_NORMAL_SPREAD = 1
TOMATO_WINDOW = 30
TOMATO_BASE_SPREAD = 5
TOMATO_SKEW_FACTOR = 0.05

class Trader:

    def run(self, state: TradingState):

        # --- Load persisted data ---
        if state.traderData and state.traderData not in ("", "SAMPLE"):
            trader_state = jsonpickle.decode(state.traderData)
        else:
            trader_state = {
                "tomato_prices": [],
                "emerald_prices": []
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
            # block in EMERALDS can safely reference them.
            # (In 97237 they were used but never defined, causing a
            # silent NameError if the mispricing branch ever triggered.)
            best_ask_amount = order_depth.sell_orders[best_ask]  # negative
            best_bid_amount = order_depth.buy_orders[best_bid]    # positive

            mid_price = (best_ask + best_bid) / 2

            if product == "EMERALDS":
                trader_state["emerald_prices"].append(mid_price)
                fair_value = EMERALD_FAIR_VALUE

                # Step 1: Aggressively take any clearly mispriced order.
                if best_ask < fair_value:
                    buy_volume = min(-best_ask_amount, limit - position)
                    if buy_volume > 0:
                        orders.append(Order(product, best_ask, buy_volume))

                if best_bid > fair_value:
                    sell_volume = min(best_bid_amount, limit + position)
                    if sell_volume > 0:
                        orders.append(Order(product, best_bid, -sell_volume))

                # Step 2: Passive market-making around the known fair value.
                already_buying  = sum(o.quantity for o in orders if o.quantity > 0)
                already_selling = sum(-o.quantity for o in orders if o.quantity < 0)

                remaining_buy  = limit - position - already_buying
                remaining_sell = limit + position - already_selling

                if best_ask - best_bid <= 1:
                    # Tight or zero spread around 10000: quote a slightly wider spread
                    # because counterparties can trade exactly at the fair price.
                    mm_buy_price = int(fair_value) - EMERALD_TIGHT_SPREAD
                    mm_sell_price = int(fair_value) + EMERALD_TIGHT_SPREAD
                else:
                    # If the book has a wider spread, quote one tick off fair to
                    # remain competitive while still collecting a spread.
                    mm_buy_price = int(fair_value) - EMERALD_NORMAL_SPREAD
                    mm_sell_price = int(fair_value) + EMERALD_NORMAL_SPREAD

                if remaining_buy > 0:
                    orders.append(Order(product, mm_buy_price, remaining_buy))
                if remaining_sell > 0:
                    orders.append(Order(product, mm_sell_price, -remaining_sell))
            # -------------------------------------------------------
            elif product == "TOMATOES":
                trader_state["tomato_prices"].append(mid_price)
                prices = trader_state["tomato_prices"]

                if len(prices) < TOMATO_WINDOW:
                    result[product] = orders
                    continue

                fair_value = sum(prices[-TOMATO_WINDOW:]) / TOMATO_WINDOW
                book_spread = best_ask - best_bid
                spread = max(TOMATO_BASE_SPREAD, math.ceil(book_spread / 2) + 1)

                # Small inventory skew helps keep position size in check.
                skew = -int(round(position * TOMATO_SKEW_FACTOR))

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