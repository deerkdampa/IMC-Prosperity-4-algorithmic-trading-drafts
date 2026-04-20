from datamodel import OrderDepth, UserId, TradingState, Order
from typing import List
import jsonpickle

POSITION_LIMITS = {
    "EMERALDS": 80,
    "TOMATOES": 80,
}

class Trader:

    def run(self, state: TradingState):

        # --- Load persisted data ---
        if state.traderData and state.traderData not in ("", "SAMPLE"):
            trader_state = jsonpickle.decode(state.traderData)
        else:
            trader_state = {
                "tomato_prices": [],
            }

        result = {}

        for product in state.order_depths:
            order_depth: OrderDepth = state.order_depths[product]
            orders: List[Order] = []
            position = state.position.get(product, 0)
            limit = POSITION_LIMITS.get(product, 20)

            if len(order_depth.sell_orders) == 0 or len(order_depth.buy_orders) == 0:
                result[product] = orders
                continue

            best_ask = min(order_depth.sell_orders.keys())
            best_bid = max(order_depth.buy_orders.keys())
            mid_price = (best_ask + best_bid) / 2

            best_ask_amount = order_depth.sell_orders[best_ask]  # negative
            best_bid_amount = order_depth.buy_orders[best_bid]   # positive

            # -------------------------------------------------------
            if product == "EMERALDS":
                acceptable_price = 10000

            # -------------------------------------------------------
            elif product == "TOMATOES":
                trader_state["tomato_prices"].append(mid_price)

                prices = trader_state["tomato_prices"]
                WINDOW = 100

                if len(prices) >= WINDOW:
                    window_prices = prices[-WINDOW:]
                    n = WINDOW
                    x = list(range(n))

                    mean_x = sum(x) / n
                    mean_y = sum(window_prices) / n

                    covariance = sum((x[i] - mean_x) * (window_prices[i] - mean_y) for i in range(n)) / n
                    variance_x = sum((x[i] - mean_x) ** 2 for i in range(n)) / n

                    slope = covariance / variance_x
                    intercept = mean_y - slope * mean_x

                    acceptable_price = slope * (n - 1) + intercept
                else:
                    acceptable_price = mid_price  # not enough data yet, don't trade

            else:
                result[product] = orders
                continue

            # -------------------------------------------------------
            # Buy/sell logic — shared for all products
            # -------------------------------------------------------
            if best_ask < acceptable_price:
                buy_volume = min(-best_ask_amount, limit - position)
                if buy_volume > 0:
                    print("BUY", buy_volume, "x", best_ask)
                    orders.append(Order(product, best_ask, buy_volume))

            if best_bid > acceptable_price:
                sell_volume = min(best_bid_amount, limit + position)
                if sell_volume > 0:
                    print("SELL", sell_volume, "x", best_bid)
                    orders.append(Order(product, best_bid, -sell_volume))

            result[product] = orders

        traderData = jsonpickle.encode(trader_state)
        conversions = 0
        return result, conversions, traderData