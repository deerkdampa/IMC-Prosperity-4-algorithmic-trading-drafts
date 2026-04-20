from datamodel import OrderDepth, UserId, TradingState, Order
from typing import List
import jsonpickle
import math

# FIX 1: Use the exact product string IDs as keys so the limit lookup works.
POSITION_LIMITS = {
    "INTARIAN_PEPPER_ROOT": 40,
    "ASH_COATED_OSMIUM": 40,
}

# OSMIUM parameters
OSMIUM_WINDOW       = 50
OSMIUM_BASE_SPREAD  = 3
OSMIUM_SKEW_FACTOR  = 0.2

# ROOTS parameters
ROOT_BASE_SPREAD    = 5
ROOT_SKEW_FACTOR    = 0.5
ROOT_EMA_ALPHA      = 0.2  # Determines how fast the fair price tracks the mid price (0.0 to 1.0)

class Trader:

    def run(self, state: TradingState):

        # --- Load persisted data ---
        if state.traderData and state.traderData not in ("", "SAMPLE"):
            trader_state = jsonpickle.decode(state.traderData)
        else:
            trader_state = {
                "osmium_prices": [],
                "root_ema": None  # FIX 2: Store a single EMA value instead of a long list
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
            
            best_ask_amount = order_depth.sell_orders[best_ask]
            best_bid_amount = order_depth.buy_orders[best_bid]

            mid_price = (best_ask + best_bid) / 2

            if product == "INTARIAN_PEPPER_ROOT":
                # STRATEGY UPGRADE: Use an Exponential Moving Average (EMA)
                if trader_state.get("root_ema") is None:
                    trader_state["root_ema"] = mid_price

                # Update the EMA. This allows the fair value to closely track the trend without severe lag.
                current_ema = (ROOT_EMA_ALPHA * mid_price) + ((1 - ROOT_EMA_ALPHA) * trader_state["root_ema"])
                trader_state["root_ema"] = current_ema
                fair_value = current_ema

                book_spread = best_ask - best_bid
                
                # FIX 3: Use ROOT_BASE_SPREAD (Original accidentally used OSMIUM_BASE_SPREAD here)
                spread = max(ROOT_BASE_SPREAD, math.ceil(book_spread / 2) + 1)

                # Inventory Skew keeps position size in check
                skew = -int(round(position * ROOT_SKEW_FACTOR))

                # FIX 4: Floor the buy price and Ceil the sell price for conservative rounding
                buy_price  = min(math.floor(fair_value) - spread + skew, best_ask - 1)
                sell_price = max(math.ceil(fair_value) + spread + skew, best_bid + 1)

                buy_volume  = limit - position
                sell_volume = limit + position

                if buy_volume > 0:
                    orders.append(Order(product, buy_price, buy_volume))
                if sell_volume > 0:
                    orders.append(Order(product, sell_price, -sell_volume))

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