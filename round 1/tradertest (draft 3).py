from datamodel import OrderDepth, UserId, TradingState, Order
from typing import List
import jsonpickle
import math

# Updated to 80 as requested
POSITION_LIMITS = {
    "INTARIAN_PEPPER_ROOT": 80,
    "ASH_COATED_OSMIUM": 80,
}

# OSMIUM parameters
OSMIUM_WINDOW       = 50
OSMIUM_BASE_SPREAD  = 3
# Skew reduced because position limit is higher. 80 * 0.05 = max 4 tick skew.
OSMIUM_SKEW_FACTOR  = 0.05 

# ROOTS parameters
ROOT_BASE_SPREAD    = 5
# Skew reduced. 80 * 0.1 = max 8 tick skew.
ROOT_SKEW_FACTOR    = 0.1   
ROOT_EMA_ALPHA      = 0.2  

class Trader:

    def run(self, state: TradingState):

        if state.traderData and state.traderData not in ("", "SAMPLE"):
            trader_state = jsonpickle.decode(state.traderData)
        else:
            trader_state = {
                "osmium_prices": [],
                "root_ema": None  
            }

        result = {}

        for product in state.order_depths:
            order_depth: OrderDepth = state.order_depths[product]
            orders: List[Order] = []

            if len(order_depth.sell_orders) == 0 or len(order_depth.buy_orders) == 0:
                result[product] = orders
                continue

            position = state.position.get(product, 0)
            limit = POSITION_LIMITS.get(product, 80)

            best_ask = min(order_depth.sell_orders.keys())
            best_bid = max(order_depth.buy_orders.keys())
            
            mid_price = (best_ask + best_bid) / 2

            # -------------------------------------------------------
            if product == "INTARIAN_PEPPER_ROOT":
                
                if trader_state.get("root_ema") is None:
                    trader_state["root_ema"] = mid_price

                current_ema = (ROOT_EMA_ALPHA * mid_price) + ((1 - ROOT_EMA_ALPHA) * trader_state["root_ema"])
                trader_state["root_ema"] = current_ema
                fair_value = current_ema

                book_spread = best_ask - best_bid
                
                # FIX: Removed math.ceil()+1 and replaced with math.floor(). 
                # This ensures quotes are placed *at* the best bid/ask or slightly inside to guarantee trades.
                spread = max(ROOT_BASE_SPREAD, math.floor(book_spread / 2))

                skew = -int(round(position * ROOT_SKEW_FACTOR))

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

                # FIX: Removed the blackout period. If we have less than 50 prices, 
                # we just average whatever prices we *do* have so we can trade immediately.
                window_size = min(len(prices), OSMIUM_WINDOW)
                fair_value = sum(prices[-window_size:]) / window_size
                
                book_spread = best_ask - best_bid
                
                # FIX: Same competitive spread logic as Roots.
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

        traderData = jsonpickle.encode(trader_state)
        conversions = 0
        return result, conversions, traderData